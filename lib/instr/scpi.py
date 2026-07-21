"""Provides classes to represent basic instruments, SCPI instruments.

Instrument is the base class and provides basic  synchronous and aynchronous command handling.

SCPI extends Instrument to implement the required commands for IEEE488.2 standard commands and other required commands
of the SCPI-99 standard.

TestInstrument is a subclass of SCPI that adds some exit and debugging commands.
"""
__all__ = ["Instrument", "SCPI", "TestInstrument", "ainput"]
try:  # For micropython <=1.20
    import uasyncio as asyncio
except ImportError:  # Desktop python or micropython>=1.21
    import asyncio
import sys
from math import floor, log10

from .decorators import AWAITED, BACKGROUND, BuildCommands, Command, prep_plist, tokenize
from .error_queue import ErrorQueue
from .exceptions import CommandError, CommandExecutionError, SCPIError, TransportClosed
from .transport import StdioTransport
from .types import Int


BYTE_MASK = Int(min=0, max=255)
STATUS_MASK = Int(min=0, max=32767)


def _is_awaitable(value):
    """Portable awaitable check for CPython and MicroPython coroutine objects."""
    return hasattr(value, "__await__") or value.__class__.__name__ in ("coroutine", "generator")


async def ainput(repl=None, reader=None):
    """Asynchornous input function.

    Args:
        repl (str, optional): Prompt for the input. Defaults to None.

    Returns:
        cmd (str): Input string recieved from stdin.

    """
    transport = StdioTransport(reader=reader)

    while True:
        if repl:
            print(repl,end=None)
        data = await transport.readline()
        if data == b"" or data == "":
            raise TransportClosed
        if isinstance(data, bytes):
            data = data.decode()
        elif not isinstance(data, str):
            raise TypeError("transport readline() must return bytes or str")
        cmd = data.strip()
        if cmd:
            return cmd
        # A blank line is recoverable input, not EOF. Yield before retrying so
        # background task failures can be reaped without a busy loop.
        await asyncio.sleep(0)


class Instrument(object):

    """Base class to define the machinery for the REPL and commnd dispatch.

    Nothing in this class should need to be overriden other than the version string.

    After initialising the instrument, run instr.run() to start the event loop.
    """

    version = "0.0.1"

    def __init__(
        self,
        debug=False,
        error_queue_capacity=16,
        fail_safe=None,
        diagnostic_handler=None,
        disconnect_handler=None,
        transport=None,
        legacy_print_handlers=False,
    ):
        """Initialise some instrument parameters, but do not start the main event loop"""
        self.current_node = None
        self._error_summary = False
        self.error_q = ErrorQueue(error_queue_capacity, self._set_error_summary)
        self.tasks = []
        self.lock = asyncio.Lock()
        self.debug = debug
        self.stb = 0
        self.fail_safe = fail_safe
        self.diagnostic_handler = diagnostic_handler
        self.disconnect_handler = disconnect_handler
        self.last_diagnostic = None
        self.callback_error = None
        self.transport = transport
        self.legacy_print_handlers = legacy_print_handlers
        self._active_transport = None

    def _set_error_summary(self, has_errors):
        self._error_summary = has_errors
        update_status = getattr(self, "_update_status_byte", None)
        if update_status is not None:
            update_status()
        elif has_errors:
            self.stb |= 4
        else:
            self.stb &= ~4

    def set_fail_safe(self, callback):
        """Register callback(command_name, exception) for unexpected failures."""
        self.fail_safe = callback

    def set_disconnect_handler(self, callback):
        """Register a zero-argument callback for transport disconnects."""
        self.disconnect_handler = callback

    def _call_safely(self, callback, *args):
        if callback is None:
            return
        try:
            callback(*args)
        except Exception as error:
            self.callback_error = error

    def _handle_unexpected_exception(self, name, error):
        self.last_diagnostic = (name, error)
        self._call_safely(self.fail_safe, name, error)
        self._call_safely(self.diagnostic_handler, name, error)
        self.error_q.append(CommandExecutionError)

    def _handle_disconnect(self):
        if self.disconnect_handler is not None:
            self._call_safely(self.disconnect_handler)
        else:
            self._call_safely(self.fail_safe, "transport", TransportClosed())

    def run(self):
        """Fire up the main event loop task for the instrument."""
        asyncio.run(self._run_service())

    async def _run_service(self):
        try:
            await self.read_commands()
        finally:
            await self._cancel_tasks(include_system=True)

    def exit(self):
        """Exit the instrument."""
        self._call_safely(self.fail_safe, "exit", None)
        for name, task in self.tasks:
            task.cancel()
        sys.exit(self.stb)

    def parse_cmd(self, command):
        """Find the command in the command table and get the correspoindig method name and parameter list.

        Args:
            command (str): A complete command string wuith parameters.

        Raises:
            CommandError: Raised when the parser can't match the command from either the current node or root..

        Returns:
            str: The name of an executable attriobute (i.e. method) to run for this command.
            plist (list of str): The command parameters a a list of strings, dealing with quotes and quoted commas.
        """
        if not isinstance(command, str) or not command.strip():
            raise CommandError
        while True:  # We potentially sscan the dictionary multiple times to locale a relative node
            cmd = command  # Restart processing with whole command
            cmd, plist = prep_plist(cmd)  # Get the parameters off the command first
            if cmd[0] in ":*" or self.current_node is None:  # Start scanning from the root command map
                read_from = self.command_map
                self.current_node = None
            else:  # Start scanning from the last node dictionary
                read_from = self.current_node
            if cmd[0] == ":":
                cmd = cmd[1:]  # Strip a leading : if present
            while ":" in cmd:  # Split the command into levels
                parts = cmd.split(":")
                stem = parts[0].upper()
                cmd = ":".join(parts[1:])
                if isinstance(read_from.get(stem, None), dict):  # There are subcommands to this node
                    read_from = read_from[stem]
                elif self.current_node is not None:  # Command not here, but we can try again with root node
                    break
                else:  # Failed to find the next level and we were looking from the root node
                    raise CommandError
            if cmd not in read_from and self.current_node is not None:  # restart from root node
                self.current_node = None
                continue
            if cmd in read_from:  # Set the root lookup for the future
                self.current_node = read_from
            return read_from.get(cmd, None), plist

    async def read_commands(self, reader=None, transport=None):
        """Main event loop for the instrument.

        Raises:
            CommandError: Raised if the instrument is sent an unrecognised command.

        Returns:
            None.

        Notes:
            This function is run asynchronously by the run() method. It will wait asynchronously for an input line from
            the user via stdin, split the command on semi-colons and then parse it. After parsing, it looks for an
            attribute of the matching name. That sttribute should have additional metadata that determines how the
            command should run (synchronously, asynchronously, asynchronously but awaited). The attribute also provides
            information about the parameters to allow the parameter list (which are strings) to be converted to the
            correct python types.

            THe main loop also looks for asynchronous tasks that have completed and removes them from the list of
            currently running tasks.

            Any SCPIError exceptions that are raised are handled by appending to the errors list for the instrument.
        """
        if transport is None:
            if reader is not None:
                transport = StdioTransport(reader=reader)
            else:
                transport = self.transport or StdioTransport()
        self._active_transport = transport
        monitor = asyncio.create_task(self._monitor_tasks())
        try:  # Catch KeyBoard Interrupt
            while True:  # Main loop
                cmd_string = await self._read_command_line(transport)
                await self.process_line(cmd_string, transport=transport)
        except TransportClosed:
            self._handle_disconnect()
        finally:
            monitor.cancel()
            try:
                await monitor
            except asyncio.CancelledError:
                pass
            await transport.close()
            self._active_transport = None

    async def _read_command_line(self, transport):
        """Read one non-blank command line from a transport."""
        while True:
            data = await transport.readline()
            if data == b"" or data == "":
                raise TransportClosed
            if isinstance(data, bytes):
                data = data.decode()
            elif not isinstance(data, str):
                raise TypeError("transport readline() must return bytes or str")
            command = data.strip()
            if command:
                return command
            await asyncio.sleep(0)

    async def process_line(self, command_line, transport=None):
        """Process each non-empty program-message unit in one input line."""
        try:
            commands = tokenize(command_line, ";")
        except SCPIError as error:
            self.error_q.append(error)
            return
        except Exception as error:
            self._handle_unexpected_exception("parser", error)
            return
        for command in commands:
            if not command.strip():
                continue
            cmd_runner = None
            try:
                cmd_runner, plist = self.parse_cmd(command)
                if isinstance(cmd_runner, dict):
                    cmd_runner = cmd_runner.get("_", None)
                if cmd_runner is None:
                    raise CommandError
                cmd_runner = getattr(self, cmd_runner)
                plist = cmd_runner.prep_parameters(plist)
                if cmd_runner.is_query and cmd_runner.async_call == BACKGROUND:
                    raise CommandExecutionError("Query commands cannot run in the background")
                result = await self._dispatch_command(cmd_runner, plist)
                if cmd_runner.is_query and (result is not None or not self.legacy_print_handlers):
                    await self._write_response(result, transport)
            except SCPIError as error:
                self.error_q.append(error)
            except TransportClosed:
                raise
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._handle_unexpected_exception(getattr(cmd_runner, "name", command), error)
            await self._reap_tasks()

    async def _write_response(self, value, transport=None):
        """Serialize and frame exactly one query response through a transport."""
        if isinstance(value, bool):
            value = int(value)
        elif isinstance(value, bytes):
            value = value.decode()
        if value is None:
            value = ""
        response_transport = transport or self._active_transport
        if response_transport is None:
            response_transport = StdioTransport()
        await self.lock.acquire()
        try:
            await response_transport.write_response(str(value))
        finally:
            self.lock.release()

    def _start_task(self, name, awaitable):
        """Create and register a background task in one place."""
        task = asyncio.create_task(awaitable)
        self.tasks.append((name, task))
        return task

    async def _monitor_tasks(self):
        """Reap completed background work even while command input is idle."""
        while True:
            await asyncio.sleep(0.01)
            await self._reap_tasks()

    async def _reap_tasks(self):
        """Retrieve results for every completed task exactly once."""
        completed = [entry for entry in self.tasks if entry[1].done()]
        if not completed:
            return
        self.tasks = [entry for entry in self.tasks if not entry[1].done()]
        for name, task in completed:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except SCPIError as error:
                self.error_q.append(error)
            except Exception as error:
                self._handle_unexpected_exception(name, error)

    async def _cancel_tasks(self, include_system=False):
        """Cancel selected tasks and retrieve their terminal results."""
        selected = [
            (name, task)
            for name, task in self.tasks
            if include_system or not name.startswith("_")
        ]
        selected_tasks = [task for _, task in selected]
        self.tasks = [entry for entry in self.tasks if entry[1] not in selected_tasks]
        for _, task in selected:
            if not task.done():
                task.cancel()
        for name, task in selected:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except SCPIError as error:
                self.error_q.append(error)
            except Exception as error:
                self._handle_unexpected_exception(name, error)
        await self._reap_tasks()

    async def _dispatch_command(self, cmd_runner, plist):
        """Execute one prepared command according to its declared execution mode."""
        real_command = getattr(self, cmd_runner.name, cmd_runner)
        result = real_command(*plist)
        if cmd_runner.async_call in (BACKGROUND, AWAITED):
            if not _is_awaitable(result):
                raise CommandExecutionError(
                    f"Command {cmd_runner.name} did not return an awaitable"
                )
            if cmd_runner.async_call == BACKGROUND:
                self._start_task(cmd_runner.name, result)
            else:
                return await result
        elif _is_awaitable(result):
            close = getattr(result, "close", None)
            if close is not None:
                close()
            raise CommandExecutionError(
                f"Command {cmd_runner.name} returned an awaitable in synchronous mode"
            )
        return result

    @staticmethod
    def format(value):
        mag_letters = {
            -30: "q",
            -27: "r",
            -24: "y",
            -21: "z",
            -18: "a",
            -15: "f",
            -12: "p",
            -9: "n",
            -6: "u",
            -3: "m",
            0: "",
            3: "k",
            6: "M",
            9: "G",
            12: "T",
            15: "P",
            18: "E",
            21: "Z",
            24: "Y",
            27: "R",
            30: "Q",
        }
        absolute = abs(value)
        if absolute == 0 or absolute == float("inf") or value != value:
            return value, ""
        mag = 3 * (floor(log10(absolute)) // 3)
        mag = max(min(mag, 30), -30)
        return value / 10**mag, mag_letters[mag]


@BuildCommands
class SCPI(Instrument):

    """Base class implementing the framework's tested IEEE 488.2/SCPI subset.

    Implements the following commands:
        - *ESE, &ESE?, *ESR
        - *IDN?
        - *OPC, *OPC?
        - *CLS
        - *RST
        - *SRE, *SRE?
        - *STB?
        - *TST?
        - *WAI
        - SYSTem:ERRor[:NEXT]?
        - SYSTem:VERSion?
        - STATus:OPERation[:EVENt]?
        - STATus:OPERation:CONDition?
        - STATus:OPERation:ENABle?
        - STATus:OPERation:ENABle
        - STATus:QUEStionable[:EVENt]?
        - STATus:QUEStionable:CONDition?
        - STATus:QUEStionable:ENABle?
        - STATus:QUEStionable:ENABle
        - STATus:PRESet
    """

    @property
    def oper_reg(self):
        return self._oper_reg

    @oper_reg.setter  # Setting operational status register might trigger events and stb changes
    def oper_reg(self, value):
        value &= 0x7FFF
        self._oper_event |= value & ~self._oper_reg
        self._oper_reg = value
        self._update_status_byte()

    @property  # Reading event register clears it.
    def oper_event(self):
        ret = self._oper_event
        self._oper_event = 0
        self._update_status_byte()
        return ret

    @oper_event.setter  # Writing the event regist might also change the stb
    def oper_event(self, value):
        self._oper_event = value & 0x7FFF
        self._update_status_byte()

    @property
    def oper_enab(self):
        return self._oper_enab

    @oper_enab.setter
    def oper_enab(self, value):
        self._oper_enab = value & 0x7FFF
        self._update_status_byte()

    @property
    def open_event(self):
        """Deprecated compatibility alias for the misspelled operation event property."""
        return self.oper_event

    @open_event.setter
    def open_event(self, value):
        self.oper_event = value

    @property
    def ques_reg(self):
        return self._ques_reg

    @ques_reg.setter  # Writing the questionable status register can cause events too
    def ques_reg(self, value):
        value &= 0x7FFF
        self._ques_event |= value & ~self._ques_reg
        self._ques_reg = value
        self._update_status_byte()

    @property  # Reading the event register will clear it
    def ques_event(self):
        ret = self._ques_event
        self._ques_event = 0
        self._update_status_byte()
        return ret

    @ques_event.setter  # Writing the event register might change the stb
    def ques_event(self, value):
        self._ques_event = value & 0x7FFF
        self._update_status_byte()

    @property
    def ques_enab(self):
        return self._ques_enab

    @ques_enab.setter
    def ques_enab(self, value):
        self._ques_enab = value & 0x7FFF
        self._update_status_byte()

    @property
    def event_reg(self):
        return self._event_reg

    @event_reg.setter  # Reading the standard event register can change the standard event event register
    def event_reg(self, value):
        self._event_reg = value & 0xFF
        self._update_status_byte()

    @property  # Reading the stadnard event event register clears it
    def event_event(self):
        ret = self._event_reg
        self._event_reg = 0
        self._update_status_byte()
        return ret

    @event_event.setter  # Writing the standard event event register may change the stb.
    def event_event(self, value):
        self.event_reg = value

    @property
    def event_enab(self):
        return self._event_enab

    @event_enab.setter
    def event_enab(self, value):
        self._event_enab = value & 0xFF
        self._update_status_byte()

    @property
    def service_enab(self):
        return self._service_enab

    @service_enab.setter
    def service_enab(self, value):
        # IEEE 488.2 bit 6 is the MSS/RQS result and is never enabled itself.
        self._service_enab = value & 0xBF
        self._update_status_byte()

    def _update_status_byte(self):
        """Recompute implemented SCPI summary bits and the MSS/RQS bit."""
        status = self.stb & ~(4 | 8 | 32 | 64 | 128)
        if self._error_summary:
            status |= 4
        if self._ques_event & self._ques_enab:
            status |= 8
        if self._event_reg & self._event_enab:
            status |= 32
        if self._oper_event & self._oper_enab:
            status |= 128
        if status & self._service_enab:
            status |= 64
        self.stb = status

    def __init__(self, debug=False, **kwargs):
        """Initialise our registeres and other state."""
        self._oper_reg = 0
        self._oper_enab = 0
        self._oper_event = 0
        self._ques_reg = 0
        self._ques_event = 0
        self._ques_enab = 0
        self._event_reg = 0
        self._event_enab = 0
        self._service_enab = 0
        super().__init__(debug, **kwargs)
        self._update_status_byte()

    @Command(command="*CLS")
    def cls(self):
        """Clear event latches and errors without changing conditions or enables."""
        self.error_q.clear()
        self._oper_event = 0
        self._ques_event = 0
        self._event_reg = 0
        self._update_status_byte()

    @Command(command="*ESE", parameters=(BYTE_MASK,))
    def ese(self, mask):
        """Set Standard Event Enable."""
        self.event_enab = mask

    @Command(command="*ESE?")
    def eseq(self):
        """Report Standard Event Enable."""
        return self.event_enab

    @Command(command="*ESR?")
    def esrq(self):
        """Read and clear the Standard Event Status Register."""
        return self.event_event

    @Command(command="*IDN?")
    def idnq(self):
        """Implements *IDN?"""
        return f"Raspberry Pico (MicroPython),{self.__class__.__name__},,{sys.version.split(' ')[2]}:{self.version}"

    @Command(command="*OPC", async_call=BACKGROUND)
    async def opc(self):
        """Keep checking for the currently executing tasks to finish."""
        tasks = [(name, x) for name, x in self.tasks if name not in ["opcq", "opc", "wait"]]
        while True:
            for task in tasks:
                if not task[1].done():
                    break
            else:
                break
            await asyncio.sleep(0.1)
        self.event_reg |= 1

    @Command(command="*OPC?", async_call=AWAITED)
    async def opcq(self):
        """Block until all tasks are done."""
        tasks = [(name, x) for name, x in self.tasks if name not in ["opcq", "opc", "wait"]]
        while True:
            for task in tasks:
                if not task[1].done():
                    break
            else:
                break
            await asyncio.sleep(0.1)
        return 1

    @Command(command="*RST", async_call=AWAITED)
    async def reset(self):
        """This needs to be overriden to actually do the reset."""
        await self._cancel_tasks()
        self._oper_reg = 0
        self._ques_reg = 0
        self.cls()

    @Command(command="*SRE", parameters=(BYTE_MASK,))
    def sre(self, mask):
        """Set the SRE register."""
        self.service_enab = mask

    @Command(command="*SRE?")
    def sreq(self):
        return self.service_enab

    @Command(command="*STB?")
    def stbq(self):
        """Report the currently derived status byte."""
        self._update_status_byte()
        return self.stb

    @Command(command="*TST?")
    def self_test(self):
        """Really a NOP !"""
        return 0

    @Command(command="*WAI", async_call=AWAITED)
    async def wait(self):
        """Holduntil all tasks have stopped."""
        while True:
            for name, task in self.tasks:
                if name in ["opc", "opcq", "wait"] or name.startswith("_"):
                    continue
                if not task.done():
                    break
            else:
                break
            await asyncio.sleep(0.1)

    @Command(command="SYSTem:ERRor[:NEXT]?")
    def read_error_q(self):
        """Pop the next error message of the queue and report it."""
        if len(self.error_q):
            err = self.error_q.popleft()
            return f'{err.code},"{err.message}"'
        else:
            return '0,"No error"'

    @Command(command="SYSTem:VERSion?")
    def read_version(self):
        return "1999.1"

    @Command(command="STATus:OPERation[:EVENt]?")
    def scpi_oper_event(self):
        return self.oper_event

    @Command(command="STATus:OPERation:CONDition?")
    def scpi_oper_reg(self):
        return self.oper_reg

    @Command(command="STATus:OPERation:ENABle?")
    def scpi_oper_enabq(self):
        return self.oper_enab

    @Command(command="STATus:OPERation:ENABle", parameters=(STATUS_MASK,))
    def scpi_oper_enab(self, value):
        self.oper_enab = value

    @Command(command="STATus:QUEStionable[:EVENt]?")
    def scpi_ques_event(self):
        return self.ques_event

    @Command(command="STATus:QUEStionable:CONDition?")
    def scpi_ques_reg(self):
        return self.ques_reg

    @Command(command="STATus:QUEStionable:ENABle?")
    def scpi_ques_enabq(self):
        return self.ques_enab

    @Command(command="STATus:QUEStionable:ENABle", parameters=(STATUS_MASK,))
    def scpi_ques_enab(self, value):
        self.ques_enab = value

    @Command(command="STATus:PRESet")
    def status_preset(self):
        """Preset only the device status subsystem; do not reset the device."""
        self._oper_enab = 0
        self._ques_enab = 0
        self._oper_event = 0
        self._ques_event = 0
        self._update_status_byte()


@BuildCommands
class TestInstrument(SCPI):

    """Implement a set of test SCPI commands for debugging and testing.

    - SYSTem:SLEEP - Asynchronous sleep command
    - SYSTem:EXIT - Exit the instrument command parser
    - SYSTem:PRINt - Store a test string without emitting unsolicited output
    - SYSTem:DEBUg? - Check running async tasks
    """

    @Command(command="SYSTem:SLEEP", async_call=BACKGROUND, parameters=(float,))
    async def sleep(self, sleep_time):
        """Simply sleep for sleep_time seconds as background work."""
        if self.stb & 1:
            return None
        self.stb ^= 1
        await asyncio.sleep(sleep_time)
        self.stb ^= 1

    @Command(command="SYSTem:EXIT")
    def exit_instrument(self):
        self.exit()

    @Command(command="SYSTem:PRINt", parameters=(str,))
    def print(self, string):
        """Store a test string without writing outside the response boundary."""
        self.last_print = string

    @Command(command="SYSTem:DEBUg?")
    def debug_tasks(self):
        return ",".join(f"{name}:{int(task.done())}" for name, task in self.tasks)


if __name__ == "__main__":
    runner = TestInstrument()
