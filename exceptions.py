"""SCPI Instrument exceptions."""
__all__=["SCPIError",
         "CommandError",
         "CommandSyntaxError",
         "DataTypeError",
         "TooFewParameters",
         "TooManyParameters",
         "InstrumentBusy",
         "ParameterDataOutOfRange",
         ]

class SCPIError(TypeError):
    code=0
    message="No Error"
    
class CommandError(SCPIError):
    code=-100
    message="Command Error"
    
class CommandSyntaxError(SCPIError):
    code=-102
    message="Syntax Error"
    
class DataTypeError(SCPIError):
    code=-104
    message="Data Type Error"
    
class TooFewParameters(SCPIError):
    code=-109
    message="Missing parameter"
    
class TooManyParameters(SCPIError):
    code=-108
    message="Parmaeter not allowed"
    
class InstrumentBusy(SCPIError):
    code=-200
    message="Instrument busy"

class ParameterDataOutOfRange(SCPIError):
    code=-222
    message="Parameter Out of Range"