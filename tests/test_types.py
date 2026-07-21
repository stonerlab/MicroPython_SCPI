import pytest

from lib.instr.decorators import Command
from lib.instr.exceptions import DataTypeError, ParameterDataOutOfRange
from lib.instr.types import Boolean, Enum, Float, Int


@pytest.mark.parametrize("token", ["ON", "1", "YES", "TRUE", " on ", "True"])
def test_boolean_true_tokens(token):
    assert Boolean(token) is True


@pytest.mark.parametrize("token", ["OFF", "0", "NO", "FALSE", " off ", "False"])
def test_boolean_false_tokens(token):
    assert Boolean(token) is False


@pytest.mark.parametrize("token", ["", "2", "ENABLE", None, 0])
def test_boolean_rejects_other_tokens(token):
    with pytest.raises(DataTypeError):
        Boolean(token)


@pytest.mark.parametrize("token, expected", [("ON", True), ("OFF", False), ("0", False)])
def test_builtin_bool_parameter_uses_scpi_boolean(token, expected):
    @Command(parameters=(bool,))
    def handler(_instrument, _value):
        pass

    assert handler.prep_parameters([token]) == [expected]


@pytest.mark.parametrize("converter", [Int(min=0, max=7), Float(min=0, max=7)])
def test_numeric_integer_bounds_are_inclusive(converter):
    assert converter("MIN") == 0
    assert converter("0") == 0
    assert converter("7") == 7
    assert converter("MAX") == 7
    with pytest.raises(ParameterDataOutOfRange):
        converter("-1")
    with pytest.raises(ParameterDataOutOfRange):
        converter("99")


def test_float_bounds_accept_floating_point_limits():
    converter = Float(min=-0.5, max=0.5)
    assert converter("-0.5") == -0.5
    assert converter("0.5") == 0.5
    with pytest.raises(ParameterDataOutOfRange):
        converter("0.5001")


@pytest.mark.parametrize(
    "factory, kwargs, error",
    [
        (Int, {"min": True}, TypeError),
        (Float, {"max": False}, TypeError),
        (Int, {"min": 1.5}, TypeError),
        (Float, {"min": float("nan")}, TypeError),
        (Int, {"min": 2, "max": 1}, ValueError),
        (Float, {"min": 2, "max": 1}, ValueError),
    ],
)
def test_invalid_numeric_bounds_fail_at_construction(factory, kwargs, error):
    with pytest.raises(error):
        factory(**kwargs)


def test_enum_maps_scpi_keyword_labels_to_python_values():
    mode = Enum(POWer="power", VOLTage="voltage")
    assert mode("POW") == "power"
    assert mode("power") == "power"
    assert mode(" VOLT ") == "voltage"
    assert mode("VOLTAGE") == "voltage"


def test_positional_enum_labels_map_to_themselves():
    mode = Enum("POWer", "VOLTage")
    assert mode("POW") == "POWer"
    assert mode("VOLTAGE") == "VOLTage"


def test_enum_rejects_unknown_and_duplicate_aliases():
    with pytest.raises(DataTypeError):
        Enum(POWer="power")("CURRENT")
    with pytest.raises(ValueError, match="Duplicate Enum alias"):
        Enum(POWer="power", Power="other")
