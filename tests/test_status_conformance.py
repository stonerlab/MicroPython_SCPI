import asyncio

import pytest

from lib.instr.decorators import BACKGROUND, BuildCommands, Command
from lib.instr.exceptions import CommandError, ParameterDataOutOfRange
from lib.instr.scpi import SCPI


def run(coro):
    return asyncio.run(coro)


@BuildCommands
class StatusInstrument(SCPI):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.task_cleaned = False

    @Command(command="WORK", async_call=BACKGROUND)
    async def work(self):
        try:
            await asyncio.sleep(60)
        finally:
            self.task_cleaned = True


def test_standard_event_read_clears_esr_esb_and_service_request(capsys):
    instrument = SCPI()
    instrument.event_enab = 1
    instrument.service_enab = 32
    instrument.event_reg |= 1
    assert instrument.stb & 32
    assert instrument.stb & 64

    instrument.esrq()
    assert capsys.readouterr().out == "1\n"
    assert instrument.event_reg == 0
    assert not instrument.stb & (32 | 64)

    instrument.esrq()
    assert capsys.readouterr().out == "0\n"


def test_operation_positive_transition_latches_and_read_clears():
    instrument = SCPI()
    instrument.oper_enab = 1
    instrument.service_enab = 128
    instrument.oper_reg = 1
    assert instrument.stb & 128
    assert instrument.stb & 64
    assert instrument.oper_event == 1
    assert instrument.oper_reg == 1
    assert not instrument.stb & (128 | 64)

    instrument.oper_reg = 1
    assert instrument.oper_event == 0
    instrument.oper_reg = 0
    instrument.oper_reg = 1
    assert instrument.oper_event == 1


def test_questionable_enable_can_assert_and_deassert_existing_event_summary():
    instrument = SCPI()
    instrument.ques_event = 2
    assert not instrument.stb & 8
    instrument.ques_enab = 2
    assert instrument.stb & 8
    instrument.service_enab = 8
    assert instrument.stb & 64
    instrument.ques_enab = 0
    assert not instrument.stb & (8 | 64)


def test_error_queue_summary_participates_in_service_request():
    instrument = SCPI()
    instrument.service_enab = 4
    instrument.error_q.append(CommandError)
    assert instrument.stb & 4
    assert instrument.stb & 64
    instrument.error_q.popleft()
    assert not instrument.stb & (4 | 64)


def test_cls_clears_latches_and_errors_without_conditions_or_enables():
    instrument = SCPI()
    instrument.oper_enab = 1
    instrument.ques_enab = 2
    instrument.event_enab = 1
    instrument.service_enab = 4 | 8 | 32 | 128
    instrument.oper_reg = 1
    instrument.ques_reg = 2
    instrument.event_reg = 1
    instrument.error_q.append(CommandError)

    instrument.cls()

    assert instrument.oper_reg == 1
    assert instrument.ques_reg == 2
    assert instrument.oper_enab == 1
    assert instrument.ques_enab == 2
    assert instrument.event_enab == 1
    assert instrument.service_enab == 4 | 8 | 32 | 128
    assert instrument.oper_event == 0
    assert instrument.ques_event == 0
    assert instrument.event_event == 0
    assert len(instrument.error_q) == 0
    assert not instrument.stb & (4 | 8 | 32 | 64 | 128)


def test_status_preset_does_not_reset_tasks_errors_or_standard_status():
    async def scenario():
        instrument = StatusInstrument()
        instrument.oper_reg = 1
        instrument.ques_reg = 2
        instrument.oper_enab = 1
        instrument.ques_enab = 2
        instrument.event_enab = 1
        instrument.service_enab = 32
        instrument.event_reg = 1
        instrument.error_q.append(CommandError)
        task = instrument._start_task("work", instrument.work())
        await asyncio.sleep(0)

        instrument.status_preset()
        state = (
            task.done(),
            instrument.oper_reg,
            instrument.ques_reg,
            instrument.oper_enab,
            instrument.ques_enab,
            instrument.event_reg,
            instrument.event_enab,
            instrument.service_enab,
            len(instrument.error_q),
        )
        await instrument._cancel_tasks(include_system=True)
        return instrument, state

    instrument, state = run(scenario())
    assert state == (False, 1, 2, 0, 0, 1, 1, 32, 1)
    assert instrument.task_cleaned


def test_reset_waits_for_tasks_and_clears_conditions_events_and_errors():
    async def scenario():
        instrument = StatusInstrument()
        instrument.oper_enab = 1
        instrument.ques_enab = 2
        instrument.event_enab = 1
        instrument.service_enab = 32
        instrument.oper_reg = 1
        instrument.ques_reg = 2
        instrument.event_reg = 1
        instrument.error_q.append(CommandError)
        await instrument._dispatch_command(instrument._scpi_work, [])
        await asyncio.sleep(0)
        await instrument._dispatch_command(instrument._scpi_reset, [])
        return instrument

    instrument = run(scenario())
    assert instrument.task_cleaned
    assert instrument.tasks == []
    assert instrument.oper_reg == 0
    assert instrument.ques_reg == 0
    assert instrument.event_reg == 0
    assert len(instrument.error_q) == 0
    assert instrument.oper_enab == 1
    assert instrument.ques_enab == 2
    assert instrument.event_enab == 1
    assert instrument.service_enab == 32


def test_status_masks_are_bounded_and_sre_reserved_bit_is_ignored():
    instrument = SCPI()
    run(
        instrument.process_line(
            "*ESE 256;*SRE -1;STAT:OPER:ENAB 32768;STAT:QUES:ENAB 32768"
        )
    )
    errors = [instrument.error_q.popleft() for _ in range(4)]
    assert all(isinstance(error, ParameterDataOutOfRange) for error in errors)

    run(
        instrument.process_line(
            "*ESE 255;*SRE 255;STAT:OPER:ENAB 32767;STAT:QUES:ENAB 32767"
        )
    )
    assert instrument.event_enab == 255
    assert instrument.service_enab == 191
    assert instrument.oper_enab == 32767
    assert instrument.ques_enab == 32767


def test_self_test_is_query_only(capsys):
    instrument = SCPI()
    run(instrument.process_line("*TST?"))
    assert capsys.readouterr().out == "0\n"
    run(instrument.process_line("*TST"))
    assert isinstance(instrument.error_q.popleft(), CommandError)


def test_opc_sets_standard_event_and_summary_after_prior_work():
    @BuildCommands
    class OpcInstrument(SCPI):
        def __init__(self):
            super().__init__()
            self.finished = False

        @Command(command="WORK", async_call=BACKGROUND)
        async def work(self):
            await asyncio.sleep(0.01)
            self.finished = True

    async def scenario():
        instrument = OpcInstrument()
        instrument.event_enab = 1
        instrument.service_enab = 32
        await instrument._dispatch_command(instrument._scpi_work, [])
        await instrument._dispatch_command(instrument._scpi_opc, [])
        await asyncio.gather(*(task for _, task in instrument.tasks))
        return instrument

    instrument = run(scenario())
    assert instrument.finished
    assert instrument.event_reg & 1
    assert instrument.stb & 32
    assert instrument.stb & 64


def test_opc_query_does_not_set_standard_event(capsys):
    instrument = SCPI()
    run(instrument._dispatch_command(instrument._scpi_opcq, []))
    assert capsys.readouterr().out == "1\n"
    assert instrument.event_reg == 0
