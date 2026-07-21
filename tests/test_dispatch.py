import asyncio

import pytest

from lib.instr.decorators import AWAITED, BACKGROUND, SYNC, BuildCommands, Command
from lib.instr.exceptions import CommandExecutionError
from lib.instr.scpi import Instrument, SCPI, TestInstrument as FrameworkTestInstrument


@BuildCommands
class DispatchInstrument(Instrument):
    def __init__(self):
        super().__init__()
        self.calls = []

    @Command(command="SYNC")
    def sync_command(self):
        self.calls.append("sync")

    @Command(command="AWAIT", async_call=AWAITED)
    async def awaited_command(self):
        self.calls.append("await-start")
        await asyncio.sleep(0)
        self.calls.append("await-done")

    @Command(command="BACK", async_call=BACKGROUND)
    async def background_command(self):
        self.calls.append("background-start")
        await asyncio.sleep(0)
        self.calls.append("background-done")

    @Command(command="INVALID", async_call=BACKGROUND)
    def invalid_background_command(self):
        return None


def run(coro):
    return asyncio.run(coro)


def test_sync_handler_executes_once():
    instrument = DispatchInstrument()
    run(instrument._dispatch_command(instrument._scpi_sync_command, []))
    assert instrument.calls == ["sync"]


def test_awaited_handler_finishes_before_next_dispatch():
    async def scenario():
        instrument = DispatchInstrument()
        await instrument._dispatch_command(instrument._scpi_awaited_command, [])
        await instrument._dispatch_command(instrument._scpi_sync_command, [])
        return instrument.calls

    assert run(scenario()) == ["await-start", "await-done", "sync"]


def test_background_handler_allows_next_dispatch():
    async def scenario():
        instrument = DispatchInstrument()
        await instrument._dispatch_command(instrument._scpi_background_command, [])
        await instrument._dispatch_command(instrument._scpi_sync_command, [])
        await asyncio.gather(*(task for _, task in instrument.tasks))
        return instrument.calls

    calls = run(scenario())
    assert calls.index("sync") < calls.index("background-done")


def test_async_handler_default_is_inferred_as_background():
    @Command(command="INFER")
    async def inferred(_instrument):
        await asyncio.sleep(0)

    assert inferred.async_call == BACKGROUND


def test_builtin_async_handlers_have_explicit_modes():
    assert SCPI._scpi_opc.async_call == BACKGROUND
    assert SCPI._scpi_opcq.async_call == AWAITED
    assert SCPI._scpi_wait.async_call == AWAITED
    assert FrameworkTestInstrument._scpi_sleep.async_call == BACKGROUND


def test_async_handler_rejects_explicit_sync_mode_at_construction():
    with pytest.raises(TypeError, match="cannot use synchronous"):

        @Command(command="BAD", async_call=SYNC)
        async def bad(_instrument):
            await asyncio.sleep(0)


def test_background_mode_rejects_non_awaitable_result():
    instrument = DispatchInstrument()
    with pytest.raises(CommandExecutionError, match="did not return an awaitable"):
        run(instrument._dispatch_command(instrument._scpi_invalid_background_command, []))


def test_opc_sets_event_after_existing_background_work_finishes():
    async def scenario():
        instrument = DispatchInstrumentWithOpc()
        await instrument._dispatch_command(instrument._scpi_work, [])
        await instrument._dispatch_command(instrument._scpi_opc, [])
        await asyncio.gather(*(task for _, task in instrument.tasks))
        return instrument.event_reg, instrument.work_done

    event_reg, work_done = run(scenario())
    assert work_done
    assert event_reg & 1


@BuildCommands
class DispatchInstrumentWithOpc(SCPI):
    def __init__(self):
        super().__init__()
        self.work_done = False

    @Command(command="WORK", async_call=BACKGROUND)
    async def work(self):
        await asyncio.sleep(0.01)
        self.work_done = True
