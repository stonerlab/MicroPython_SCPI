import asyncio
import ast
from pathlib import Path

import pytest

from lib.instr.decorators import AWAITED, BACKGROUND, BuildCommands, Command
from lib.instr.error_queue import ErrorQueue
from lib.instr.exceptions import (
    CommandError,
    CommandExecutionError,
    DataTypeError,
    QueueOverflow,
    TransportClosed,
)
from lib.instr.scpi import Instrument, SCPI, ainput


class SequenceReader:
    def __init__(self, *items):
        self.items = list(items)
        self.calls = 0

    async def readline(self):
        self.calls += 1
        if self.items:
            return self.items.pop(0)
        return b""


class BlockingReader:
    def __init__(self, first_line):
        self.first_line = first_line
        self.block = asyncio.Event()

    async def readline(self):
        if self.first_line is not None:
            line = self.first_line
            self.first_line = None
            return line
        await self.block.wait()
        return b""


@BuildCommands
class ResilientInstrument(SCPI):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.good_calls = 0
        self.cancelled_cleanup = False

    @Command(command="GOOD")
    def good(self):
        self.good_calls += 1

    @Command(command="BAD")
    def bad(self):
        raise ValueError("driver failed")

    @Command(command="BADAWAIT", async_call=AWAITED)
    async def bad_awaited(self):
        await asyncio.sleep(0)
        raise OSError("awaited driver failed")

    @Command(command="KEYBOARD")
    def keyboard_interrupt(self):
        raise KeyboardInterrupt

    @Command(command="SYSTEMEXIT")
    def system_exit(self):
        raise SystemExit

    @Command(command="SCPI", async_call=BACKGROUND)
    async def scpi_failure(self):
        await asyncio.sleep(0)
        raise DataTypeError

    @Command(command="FAIL", async_call=BACKGROUND)
    async def unexpected_failure(self):
        await asyncio.sleep(0)
        raise RuntimeError("background failed")

    @Command(command="LONG", async_call=BACKGROUND)
    async def long_running(self):
        try:
            await asyncio.sleep(60)
        finally:
            self.cancelled_cleanup = True


def run(coro):
    return asyncio.run(coro)


def test_ainput_accepts_byte_and_text_readers_and_skips_blank_lines():
    byte_reader = SequenceReader(b"\n", b"  *IDN? \r\n")
    assert run(ainput(reader=byte_reader)) == "*IDN?"
    assert byte_reader.calls == 2
    assert run(ainput(reader=SequenceReader("   \n", "GOOD\n"))) == "GOOD"


@pytest.mark.parametrize("eof", [b"", ""])
def test_ainput_distinguishes_eof_from_blank_input(eof):
    with pytest.raises(TransportClosed):
        run(ainput(reader=SequenceReader(eof)))


def test_disconnect_policy_runs_once_per_transport_session_without_leaks():
    disconnects = []
    instrument = ResilientInstrument(disconnect_handler=lambda: disconnects.append("closed"))
    run(instrument.read_commands(reader=SequenceReader(b"")))
    run(instrument.read_commands(reader=SequenceReader("")))
    assert disconnects == ["closed", "closed"]
    assert instrument.tasks == []


def test_eof_after_a_command_ends_the_session_cleanly():
    disconnects = []
    instrument = ResilientInstrument(disconnect_handler=lambda: disconnects.append("closed"))
    run(instrument.read_commands(reader=SequenceReader(b"GOOD\n", b"")))
    assert instrument.good_calls == 1
    assert disconnects == ["closed"]


def test_error_queue_is_bounded_fifo_with_overflow_marker():
    queue = ErrorQueue(capacity=3)
    queue.append(CommandError)
    queue.append(DataTypeError)
    queue.append(CommandExecutionError)
    queue.append(CommandError)
    queue.append(DataTypeError)
    assert [queue.popleft(), queue.popleft(), queue.popleft()] == [
        CommandError,
        DataTypeError,
        QueueOverflow,
    ]


@pytest.mark.parametrize("capacity", [0, -1, True, 1.5])
def test_error_queue_rejects_invalid_capacity(capacity):
    with pytest.raises(ValueError, match="positive integer"):
        ErrorQueue(capacity=capacity)


def test_error_queue_updates_status_summary_and_cls_clears_it():
    instrument = SCPI(error_queue_capacity=2)
    instrument.error_q.append(CommandError)
    assert instrument.stb & 4
    instrument.cls()
    assert len(instrument.error_q) == 0
    assert not instrument.stb & 4


def test_empty_error_query_uses_scpi_no_error_response(capsys):
    SCPI().read_error_q()
    assert capsys.readouterr().out == '0,"No error"\n'


def test_command_errors_are_fifo(capsys):
    instrument = SCPI()
    instrument.error_q.append(CommandError)
    instrument.error_q.append(DataTypeError)
    instrument.read_error_q()
    instrument.read_error_q()
    assert capsys.readouterr().out.splitlines() == [
        '-100,"Command Error"',
        '-104,"Data Type Error"',
    ]


def test_successful_and_cancelled_tasks_are_reaped_without_errors():
    async def scenario():
        instrument = ResilientInstrument()
        instrument._start_task("ok", asyncio.sleep(0))
        cancelled = instrument._start_task("cancelled", asyncio.sleep(60))
        cancelled.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await instrument._reap_tasks()
        return instrument

    instrument = run(scenario())
    assert instrument.tasks == []
    assert len(instrument.error_q) == 0


def test_scpi_task_failure_is_reported_once():
    async def scenario():
        instrument = ResilientInstrument()
        await instrument._dispatch_command(instrument._scpi_scpi_failure, [])
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await instrument._reap_tasks()
        await instrument._reap_tasks()
        return instrument

    instrument = run(scenario())
    assert isinstance(instrument.error_q.popleft(), DataTypeError)
    assert len(instrument.error_q) == 0


def test_unexpected_task_failures_run_hooks_and_report_exactly_once():
    fail_safe = []
    diagnostics = []

    async def scenario():
        instrument = ResilientInstrument(
            fail_safe=lambda name, error: fail_safe.append((name, error)),
            diagnostic_handler=lambda name, error: diagnostics.append((name, error)),
        )
        for name in ("one", "two"):
            async def fail(task_name=name):
                await asyncio.sleep(0)
                raise RuntimeError(task_name)

            instrument._start_task(name, fail())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await instrument._reap_tasks()
        await instrument._reap_tasks()
        return instrument

    instrument = run(scenario())
    assert [name for name, _ in fail_safe] == ["one", "two"]
    assert [name for name, _ in diagnostics] == ["one", "two"]
    assert [instrument.error_q.popleft(), instrument.error_q.popleft()] == [
        CommandExecutionError,
        CommandExecutionError,
    ]
    assert len(instrument.error_q) == 0


def test_background_failure_is_reaped_while_input_is_idle():
    async def scenario():
        instrument = ResilientInstrument()
        service = asyncio.create_task(instrument.read_commands(reader=BlockingReader("FAIL\n")))
        await asyncio.sleep(0.05)
        service.cancel()
        with pytest.raises(asyncio.CancelledError):
            await service
        return instrument

    instrument = run(scenario())
    assert instrument.error_q.popleft() is CommandExecutionError
    assert instrument.tasks == []


def test_unexpected_sync_failure_is_contained_and_next_unit_runs():
    calls = []
    instrument = ResilientInstrument(fail_safe=lambda name, error: calls.append((name, error)))
    run(instrument.process_line("BAD;GOOD"))
    assert instrument.good_calls == 1
    assert calls[0][0] == "bad"
    assert isinstance(instrument.last_diagnostic[1], ValueError)
    assert instrument.error_q.popleft() is CommandExecutionError


def test_unexpected_awaited_failure_is_contained():
    calls = []
    instrument = ResilientInstrument(fail_safe=lambda name, error: calls.append((name, error)))
    run(instrument.process_line("BADAWAIT"))
    assert calls[0][0] == "bad_awaited"
    assert isinstance(calls[0][1], OSError)
    assert instrument.error_q.popleft() is CommandExecutionError


@pytest.mark.parametrize(
    "command, error_type", [("KEYBOARD", KeyboardInterrupt), ("SYSTEMEXIT", SystemExit)]
)
def test_process_control_exceptions_are_not_converted_to_device_errors(command, error_type):
    instrument = ResilientInstrument()
    with pytest.raises(error_type):
        run(instrument.process_line(command))
    assert len(instrument.error_q) == 0


def test_line_tokenization_error_is_queued_without_escaping():
    instrument = ResilientInstrument()
    run(instrument.process_line('GOOD "unterminated'))
    assert instrument.error_q.popleft().code == -102


@pytest.mark.parametrize("line", [";GOOD", "GOOD;", "GOOD;;GOOD", ";;;", "   "])
def test_empty_program_message_units_are_ignored(line):
    instrument = ResilientInstrument()
    run(instrument.process_line(line))
    assert instrument.good_calls == line.count("GOOD")
    assert len(instrument.error_q) == 0


def test_reset_waits_for_cancelled_task_cleanup():
    async def scenario():
        instrument = ResilientInstrument()
        await instrument._dispatch_command(instrument._scpi_long_running, [])
        await asyncio.sleep(0)
        await instrument._dispatch_command(instrument._scpi_reset, [])
        return instrument

    instrument = run(scenario())
    assert instrument.cancelled_cleanup
    assert instrument.tasks == []


def test_main_has_no_blanket_exception_pass_or_automatic_restart_loop():
    tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.Pass) for node in ast.walk(tree))
    assert not any(isinstance(node, ast.While) for node in ast.walk(tree))
