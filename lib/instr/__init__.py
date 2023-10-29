# -*- coding: utf-8 -*-
"""Provide classes and functions to make micropython based controllers into instruments that can respond to commands.

Traditional scientific instruments can be programmed through sening ASCII strings over a command bus such as TS232 or
GPIB. This micropython package makes it easier to implement command style codes for microcontrollers. In particular it
implements classes that can conform (broadly) to the SCPI-99 standard."""
__all__ = ["Instrument", "SCPI", "TestInstrument", "BuildCommands", "Command", "Int", "Float", "Enum", "Boolean", "OnOffFloat", "isnan", "__version__", "__versioninfo__"]

from .scpi import Instrument, TestInstrument, SCPI
from .decorators import BuildCommands, Command
from .types import Int, Float, Enum, Boolean, OnOffFloat, isnan

__versioninfo__=(0,2,0)
__version__ = ".".join(__versioninfo__)
