import asyncio

import pytest

from lib.instr.decorators import AWAITED, BACKGROUND, BuildCommands, Command
from lib.instr.exceptions import CommandExecutionError, TransportClosed
from lib.instr.scpi import SCPI, TestInstrument as FrameworkTestInstrument
from lib.instr.transport import MemoryTransport, StreamTransport, UARTTransport


def run(coro):
    return asyncio.run(coro)


@BuildCommands
class TransportInstrument(SCPI):
    @Command(command="ECHO?", parameters=(str,))
    def echo(self, value):
        return value

    @Command(command="BOOL?")
    def boolean(self):
        return True

    @Command(command="EMPTY?")
    def empty(self):
        return None

    @Command(command="SET")
    def setter(self):
        return "must not be sent"

    @Command(command="SLOW?", async_call=AWAITED, parameters=(str,))
    async def slow(self, value):
        await asyncio.sleep(0.01)
        return value

    @Command(command="BACK?", async_call=BACKGROUND)
    async def invalid_background_query(self):
        await asyncio.sleep(0)
        return "late"

    @Command(command="FAIL?")
    def fail(self):
        raise RuntimeError("diagnostic only")


def test_memory_transport_frames_one_response_per_query_and_ignores_setter_returns():
    transport = MemoryTransport(["ECHO? first;BOOL?;EMPTY?;SET\n"])
    instrument = TransportInstrument(transport=transport)
    run(instrument._run_service())
    assert transport.responses == ["first\n", "1\n", "\n"]
    assert transport.closed


def test_builtin_queries_use_the_transport_response_path():
    transport = MemoryTransport(["*ESE?;*TST?;SYST:VERS?\n"])
    instrument = SCPI(transport=transport)
    run(instrument._run_service())
    assert transport.responses == ["0\n", "0\n", "1999.1\n"]


def test_builtin_background_command_emits_no_unsolicited_output(capsys):
    transport = MemoryTransport(["SYST:SLEEP 0;*IDN?\n"])
    instrument = FrameworkTestInstrument(transport=transport)
    run(instrument._run_service())
    assert capsys.readouterr().out == ""
    assert len(transport.responses) == 1
    assert transport.responses[0].startswith("Raspberry Pico (MicroPython),")


def test_awaited_query_responses_remain_in_command_order():
    transport = MemoryTransport(["SLOW? first;ECHO? second\n"])
    instrument = TransportInstrument(transport=transport)
    run(instrument._run_service())
    assert transport.responses == ["first\n", "second\n"]


def test_response_framing_removes_handler_newlines():
    transport = MemoryTransport()
    instrument = TransportInstrument()
    run(instrument._write_response("value\r\n", transport))
    assert transport.responses == ["value\n"]


def test_background_queries_are_rejected_before_the_handler_starts():
    transport = MemoryTransport()
    instrument = TransportInstrument()
    run(instrument.process_line("BACK?", transport=transport))
    assert isinstance(instrument.error_q.popleft(), CommandExecutionError)
    assert instrument.tasks == []
    assert transport.responses == []


def test_diagnostics_do_not_enter_response_stream():
    diagnostics = []
    transport = MemoryTransport()
    instrument = TransportInstrument(
        diagnostic_handler=lambda name, error: diagnostics.append((name, error))
    )
    run(instrument.process_line("FAIL?;SYST:ERR?", transport=transport))
    assert len(diagnostics) == 1
    assert diagnostics[0][0] == "fail"
    assert isinstance(diagnostics[0][1], RuntimeError)
    assert transport.responses == ['-200,"Execution error"\n']


def test_response_disconnect_uses_transport_policy_not_device_error():
    class DisconnectingTransport(MemoryTransport):
        async def write_response(self, text):
            raise TransportClosed

    disconnects = []
    transport = DisconnectingTransport(["ECHO? value\n"])
    instrument = TransportInstrument(
        transport=transport, disconnect_handler=lambda: disconnects.append("closed")
    )
    run(instrument._run_service())
    assert disconnects == ["closed"]
    assert len(instrument.error_q) == 0


def test_legacy_print_handler_path_is_explicit(capsys):
    @BuildCommands
    class LegacyInstrument(SCPI):
        @Command(command="LEGACY?")
        def legacy(self):
            print("legacy response")

    transport = MemoryTransport()
    instrument = LegacyInstrument(legacy_print_handlers=True)
    run(instrument.process_line("LEGACY?", transport=transport))
    assert capsys.readouterr().out == "legacy response\n"
    assert transport.responses == []


def test_none_query_is_still_framed_when_legacy_mode_is_disabled():
    transport = MemoryTransport()
    instrument = TransportInstrument(legacy_print_handlers=False)
    run(instrument.process_line("EMPTY?", transport=transport))
    assert transport.responses == ["\n"]


class AsyncReader:
    def __init__(self, lines):
        self.lines = list(lines)

    async def readline(self):
        return self.lines.pop(0) if self.lines else b""


class AsyncWriter:
    def __init__(self):
        self.data = []
        self.drained = 0
        self.closed = False
        self.waited = False

    def write(self, value):
        self.data.append(value)

    async def drain(self):
        self.drained += 1

    def close(self):
        self.closed = True

    async def wait_closed(self):
        self.waited = True


def test_stream_transport_supports_binary_async_reader_writer_pairs():
    async def scenario():
        writer = AsyncWriter()
        transport = StreamTransport(AsyncReader([b"ECHO? stream\n"]), writer, binary=True)
        instrument = TransportInstrument(transport=transport)
        await instrument._run_service()
        return writer

    writer = run(scenario())
    assert writer.data == [b"stream\n"]
    assert writer.drained == 1
    assert writer.closed and writer.waited


class FakeUART:
    def __init__(self):
        self.reads = [None, b"ECHO? uart\n"]
        self.writes = []
        self.deinitialized = False

    def readline(self):
        return self.reads.pop(0) if self.reads else None

    def write(self, value):
        self.writes.append(value)

    def deinit(self):
        self.deinitialized = True


def test_uart_transport_polls_and_writes_bytes():
    async def scenario():
        uart = FakeUART()
        transport = UARTTransport(uart, poll_interval=0)
        assert await transport.readline() == b"ECHO? uart\n"
        await transport.write_response("ok")
        await transport.close()
        return uart

    uart = run(scenario())
    assert uart.writes == [b"ok\n"]
    assert uart.deinitialized
