# MicroPython SCPI

This is a simplified partial implementation of a SCPI-1999 command parser for a MicroPython based microcontroller -
specifically it is being written for a Raspberry Pi Pico board. In other words, it lets you interact with a Pico as if
 it were a SCPI instrument.

To use it, you write a subclass of the scpi.SCPI class and implement methods that are mapped to SCPI commands. To run
the instrumnet, you instantiate your class and execute the .run() method. After that the Pico will wait for input
on the USB COM port and respond when it sees a \n.

It is possible to implement the class methods as co-routines that can be executed as seperate tasks, allowing your
microcontroller to respond to other commands (e.g. status requests) in the meantime.

This code was written by Gavin Burnell <G.Burnell@leeds.ac.uk> and is (C) University of Leeds 2023. It is licensed for use under the MIT license - see LICENSE
for more details.

# Example

A simple example:

    import uasyncio as asyncio
    from instr import SCPI, Command, BuildCommands

    @BuildCommands
    class MyInstr(SCPI):

        """A trivial example."""

        @Command(command="SYSTem:EXAMple[:ECHO]", parameters=(str,))
        await def example(self, string):
            """An example method."""
            await asyncio.sleep(10)
            print(string)

    if __name__ == "__main__":
      while True:
      try:
          MyInstr().run()
      except KeyboardInterrupt:
          break
      except Exception as e:
          pass

This adds a new SCPI command SYST:EXAM str - or SYSTEM:EXAMPLE str or SYST:EXAM:ECHO str or SYSTEM:EXAMPLE:ECHO str
that will sleep for 10 seconds and then simply echo its parameter back to the user. If the code is exectured as the top level file (e.g. by being saved as `main.py`, it will execute the instrument loop. As well as implementing the 
SYST:EXAM etc commands, it also implements the standard IEEE488.2 *IDN?, *RST etc commands and a SCPI commands related to operational condition registers and an error message queue - as required by the SCPI-99 Specification.

# Warning !

This code is really very experimental! It's not extensively tested and is probably rather fragile so please don't try to use it in a situation where expensive damage or harm to people might result from failure without doing a full check and test yourself!

# Disclaimer

The full SCPI specification is fairly detailed and has a number of features that are not widely used in real world instruments.
This code implements most of the common requirements however.

Specifically, it supports the common '\*' required IEEE488.2 commands. It supports long and short forms of device dependent
commands and optional nodes and optional numeric suffixes. Commands can be concatendated with semi-colons and device
dependent commands can be absolute from the root node of the command tree (with the initial colon being optional) or
relative to the parent of the last executed command node.

What is not supported ;out of the box' is units on parameters and expressions. In principle both could be implemented
by providing parameter conversion functions that were aware of either. The provided parameter conversion functions are:
- **scpi.Float**(min=\<val\>,max=\<val\>,nan=\<val\>,default=\<val\>) supports conversions with optinal MIN, MAX, NAN and DEF
  values. If the min or max values are floats, then the input value is also range checked against the corresponding limit
  and a ParameterDataOutOfRange error is raised.
- **scpi.Int**(max=\<val\>,max=\<val\>, default=\<val\>) similarly to scpi.Float converts values to integers with limits and default
  value.
- **scpi.Bool**() converts "1" or "ON" to a True and "0" and "OFF" to a False
- **scpi.Enum**(LABel1=\<val\>,LABel2=\<val\>...) builds a mappin between labels with long and shrt forms and a value. Input
  values are converted to UPPERCASE beore being compared against the possible mapping values. Unmatched labels get a
  DataTypeError.

# Details

The bulk of the work of mapping SCPI commands to python methods is done by the two decorators: @BuildCommands and @Command.

The SCPI class defines the minimum set of commands needed for compliance with the SCPI-1999 standard, the main machinery
is handles by the Instrument class. This has an async run_commands() method that runs the main loop, collecting input
from sys.stdin via an async ainput() method and then passing the resultant string to the parse_cmd() method that is
responsible for extracting any parameters and then attemptoing to map the SCPI command string to a method. If the
command doesn't start with a : or * then the search starts at the last command_map dictionary tried - thus supporting
the SCPI standard for by passing a long traversal of the command tree for adjacent commands. Note the parse_cmd() method
exclusively deals with strings - it does not map either the command or the parameters to relevant types.

Once the parse_cmd() method passes back to the run_commands() method, run_commands()then looks up the corresponding
attribute to return the Executable instance. This instance provides the prep_parameters() method that transforms the
string parameters to the correct native Python types. After this the async_Call attribute of the Executable instance is
inspected to dtermine the calling method (async task, async blocking or synchronous) and the method is dispatched.

The SCPIError exception (and subclasses) is used to flag parsing errors and also command execution errors and are
trapped within the the run_commands() method and appened to an error_q attribute. This attribute is depleted by the
SYST:ERROR:NEXT? command and the status byte error bit is set.

Async tasks are appeneded as a tuple of command method, task to Instrument.tasks. This list is scanned looking for
completed tasks that can be deleted and is also used by status commands such as *OPC? to determine when all running
tasks have completed. Finally *RST will cancel all running tasks before clearing the registers.

## @Command Decorator

Synopsis:

    @Command(command=<SCPI command string>, async_call=bool|int, parameters=tuple)

The \<SCPI Command string\> tries to be similar to how SCPI commands are documented in manuals - a mixture of short
UPPer case letters defining a command abreviation and a verbose command defines in mixed case. As with all SCPI
commands, they are organised in a tree like structure with : separating the levels. Optional parts of the commands can
be enclosed in []. It is possible to have both multiple and nested optional parts of the command string and all the
permutations will be supported.

The async_call parameter is optional and can fine tune how tthe method should be called. If it is False, or not given
and the method is not a *generator* then the method will be called synchronously. This means the microcontroller will
only run that method and will not respond to other commands or let other commands tunning in the background run. For
obvious reasons, therefore, you should ensure that all synchronous methods are quick! If the async_call parameter is
not given and the method is a *generator*, or the parameter is set to 1, the method will be rund as a background task
with uasyncio.create_task(). Such a mthod will run when the microcontroller is waiting for further commands or in
parallel with other tasks that have yielded time. Finally if you set the async_call to 2, then the method will be run
asynchornously, but with a blocking uasyncio.run() call. This will allow other backgrounded commands to run (so long as
 your command yields the processor with a uasyncio.sleep() or similar) but will not all any further commands to be
processed. This is used, for example, for the *OPC? and *WAI commands to block further commands until the current
operations are all finshed.

The parser will handle arguments being passed to commands. At present it cannot handle optional parameters and strings
that contain , should be " quoted ". The parameters parameter takes a tuple of callabel functions which will be used to
 coinvert the string argument to whatever python type is expected.


## @BuildCommands Decorator

Synopsis:

    @BuildCommands

This decorartor should be placed on your SCPI subclass. There are no parameters to pass to it. What it is doing is to
create a class attribute *command_map* dictionary into the class, ensuring it contains a copy of the parent's
command_map so commands can be inherited. It then fills this dictionary with a mapping between the SCPI command words
and either a dictionary of the next level of command words, or the name of the method to call. Where a SCPI command can
 both be a terminal node and a branch point for the next level, the method to be called if the command is used as a
terminal node is given by the special "_" key in the command_map dictionary. In order to allow the original methods to
work as regular methods, the @BuilCommands decorator restores the callable method to it's original name and then adds a
new attribute to the class _scpi_{name} that holds the Executable class instance that holds the metadata about the
command parameters - so it is this attribute name that is referred to in the command_map.

Note that this scheme does have a limitation of only supporting single inheritence of classes that implment SCPI
commands. This is another limitation to be addressed in a later version! On the otherhand, MicroPython itself has some
significant difference in how multiple inheritance is done from CPython and the offiical advice is to avoid complex
class heirarchies - so perhas it's better to stick to single inheritance anyway!'
