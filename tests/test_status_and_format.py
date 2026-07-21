import math

import pytest

from lib.instr.scpi import Instrument, SCPI


def test_status_event_registers_are_zero_after_construction():
    instrument = SCPI()
    assert instrument.oper_event == 0
    assert instrument.ques_event == 0
    assert instrument.event_event == 0


def test_operation_event_and_deprecated_alias_are_read_and_clear():
    instrument = SCPI()
    instrument.oper_event = 3
    assert instrument.oper_event == 3
    assert instrument.oper_event == 0
    instrument.open_event = 4
    assert instrument.open_event == 4
    assert instrument.oper_event == 0


@pytest.mark.parametrize(
    "value, expected",
    [
        (0, (0, "")),
        (1, (1.0, "")),
        (-1, (-1.0, "")),
        (1e-3, (1.0, "m")),
        (1e3, (1.0, "k")),
        (1e33, (1000.0, "Q")),
        (1e-33, (0.001, "q")),
    ],
)
def test_engineering_format_finite_values(value, expected):
    scaled, prefix = Instrument.format(value)
    assert scaled == pytest.approx(expected[0])
    assert prefix == expected[1]


def test_engineering_format_preserves_negative_zero():
    scaled, prefix = Instrument.format(-0.0)
    assert math.copysign(1, scaled) == -1
    assert prefix == ""


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_engineering_format_non_finite_values_have_no_prefix(value):
    scaled, prefix = Instrument.format(value)
    assert (math.isnan(scaled) and math.isnan(value)) or scaled == value
    assert prefix == ""
