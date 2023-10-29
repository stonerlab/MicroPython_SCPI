# -*- coding: utf-8 -*-
"""
Types to represent types for Instruments.
"""
__all__ = ["inf", "nan", "isnan", "OnOffFloat", "Boolean", "Float", "Int", "Enum"]

from .decorators import prep_part
from .exceptions import DataTypeError, ParameterDataOutOfRange


inf = float("inf")
nan = float("nan")


def isnan(value):
    """Determines if input is a NaN value

    Args:
        value (float, str): Value to test whether it is a NaN.

    Returns:
        bool: True if the lowercase string represention of value is nan.

    """
    return str(value).lower() == "nan"


def OnOffFloat(value):
    """Converts some commmon strings for boolean values to 100.0 or 0.0 and passes floats.

    Args:
        value (str): String representation of a on/off or floating point value

    Raises:
        DataTypeError: if value is not a string, or cannot be recognised as an on/off or float value.

    Returns:
        float: A floating point value with "on" values mapped to 100.0 and "off" values to 0.0

    Notes:
        "On" values include: On, Yes, True, Def and Default
        "Off" values are Off, No, False.
    """
    try:
        value = value.upper()
    except (AttributeError, TypeError):
        raise DataTypeError
    if value in ["ON", "YES", "TRUE", "DEF", "DEFAULT"]:
        value = 100.0
    if value in ["OFF", "NO", "FALSE"]:
        value = 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        raise DataTypeError


def Boolean(value):
    """Convert copmmon strings for On/Off to a boolean value.

    Args:
        value (str): Value to interpret as On/Off.

    Raises:
        DataTypeError: Raised if the value is not a string or does not match an on/off value.

    Returns:
        bool: True if value matches an "on" string and False if it matches an "off" value.

    Notes:
        "on" values are "On","Yes","1", "True"
        "off" values are "Off", "No", "0", "False"
    """
    try:
        value=value.strip().upper()
    except (ValueError, TypeError, AttributeError):
        raise DataTypeError
    if value in ["1", "ON", "YES", "TRUE"]:
        return True
    if value in ["0", "OFF", "NO", "FALSE"]:
        return False
    raise DataTypeError


class Float(object):

    """Creates a callable to convert string representation of a float to an float with optional special strings.

    As well as the floating point values, the code will also accept the following 'special' values if the corresponding
    value has been set by the constructor.
    - MINimum: a minimum legal value
    - MAXimum: a maximum legal value
    - DEFault: a standard default value
    - NAN: a special not-a-number value

    The constructor can also take arbitary keywords that can be used to create standard string that can map to
    particular values. The keyword arguments can be specified SCPI style e.g. COLour will match COL and COLOUR.
    """

    def __init__(self, min=None, max=None, nan=None, default=None, **kargs):
        """Set values to be used for MIN MAX NAN and DEF."""
        self._mapping = {
            "MIN": min,
            "MINIMUM": min,
            "MAX": max,
            "MAXIMUM": max,
            "DEF": default,
            "DEFAULT": default,
            "NAN": nan,
        }
        for k, v in kargs.items():
            short, long, _ = prep_part(k)
            self._mapping[short.upper()] = float(v)
            self._mapping[long.upper()] = float(v)

    def __call__(self, value):
        """Do the conversion of a string value to a floating point number taking into account the bounds and defaults.

        Args:
            value (str): Value string to be converted to a float.

        Raises:
            ParameterDataOutOfRange: Raised if value can be converted to a float, but that float is out of bounds.
            DataTypeError: Raise if value is not a string or cannot be interpreted as a float or recognised string.

        Returns:
            float: Floating point value to return.
        """
        if isinstance(value, str) and self._mapping.get(value.strip().upper(), None) is not None:
            return self._mapping[value.strip().upper()]
        try:
            ret = float(value)
            if isinstance(self._mapping["MIN"], float) and ret < self._mapping["MIN"]:
                raise ParameterDataOutOfRange
            if isinstance(self._mapping["MAX"], float) and ret > self._mapping["MAX"]:
                raise ParameterDataOutOfRange
            return ret
        except (TypeError, ValueError):
            raise DataTypeError


class Int(object):

    """Creates a callable to convert string representation of an integer to an integer with optional special strings.

    As well as the integer values, the code will also accept the following 'special' values if the corresponding
    value has been set by the constructor.
    - MINimum: a minimum legal value
    - MAXimum: a maximum legal value
    - DEFault: a standard default value

    The constructor can also take arbitary keywords that can be used to create standard string that can map to
    particular values. The keyword arguments can be specified SCPI style e.g. COLour will match COL and COLOUR.
    """

    def __init__(self, min=None, max=None, default=None, **kargs):
        """Set values to be used for MIN MAX NAN and DEF."""
        self._mapping = {
            "MIN": min,
            "MINIMUM": min,
            "MAX": max,
            "MAXIMUM": max,
            "DEF": default,
            "DEFAULT": default,
        }
        for k, v in kargs.items():
            short, long, _ = prep_part(k)
            self._mapping[short.upper()] = int(v)
            self._mapping[long.upper()] = int(v)

    def __call__(self, value):
        """Do the conversion of a string value to an integer number taking into account the bounds and defaults.

        Args:
            value (str): Value string to be converted to an int.

        Raises:
            ParameterDataOutOfRange: Raised if value can be converted to an int, but that int is out of bounds.
            DataTypeError: Raise if value is not a string or cannot be interpreted as an int or recognised string.

        Returns:
            float: Floating point value to return.
        """
        if isinstance(value, str) and self._mapping.get(value.strip().upper(), None) is not None:
            return self._mapping[value.strip().upper()]
        try:
            ret = int(value)
            if isinstance(self._mapping["MIN"], float) and ret < self._mapping["MIN"]:
                raise ParameterDataOutOfRange
            if isinstance(self._mapping["MAX"], float) and ret > self._mapping["MAX"]:
                raise ParameterDataOutOfRange
            return ret
        except (TypeError, ValueError):
            raise DataTypeError

class Enum(object):

    """Map a set of SCPI strings to values."""

    def __init__(self, *args, **kargs):
        """Create an obkect with a mapping between string labels and values.

        Either pass keyword arguments mapping labels to values or positional
        arguments get mapped to 0,1,2...
        """
        for ix, arg in enumerate(args):
            kargs[arg] = ix
        self.mapping = {}
        for label, value in kargs.items():
            short, long, _ = prep_part(value)
            self.mapping[short] = label
            self.mapping[long] = label

    def __call__(self, value):
        """Do the conversion of a string to a value by consulting the mapping defined by the constructor.

        Args:
            value (str): Label to be translated to a value.

        Raises:
            DataTypeError: Raised if the value is not a string or cannot be matched to one of the defined labels.

        Returns:
            ret (Any): Whatever value has been defined to match the input Label.

        """
        try:
            value = value.upper()
        except (TypeError, ValueError, AttributeError):
            raise DataTypeError
        if value in self.mapping:
            ret = self.mapping.get(value, "Ooops")
            return ret
        raise DataTypeError
