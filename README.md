# MicroPython SCPI

This is a simplified partial implementation of a SCPI-1999 command parser for a MicroPython based microcontroller -
specifically it is being written for a Raspberry Pi Pico board. In other words, it lets you interact with a Pico as if
 it were a SCPI instrument.

To use it, you write a subclass of the scpi.SCPI class and implement methods that are mapped to SCPI commands. To run
the instrumnet, you instantiate your class and execute the .run() method. After that the Pico will wait for input
on the USB COM port and respond when it sees a \n.

The normative requirements for constructors, command handlers, execution modes, task ownership, reset/status behavior,
and safety callbacks are collected in [`INSTRUMENT_SUBCLASS_CONTRACT.md`](INSTRUMENT_SUBCLASS_CONTRACT.md). Read that
contract before implementing a hardware-backed subclass.

It is possible to implement the class methods as co-routines that can be executed as seperate tasks, allowing your
microcontroller to respond to other commands (e.g. status requests) in the meantime.

This code was written by Gavin Burnell <G.Burnell@leeds.ac.uk> and is (C) University of Leeds 2023. It is licensed for use under the MIT license - see LICENSE
for more details.

# Example

A simple example:

    import uasyncio as asyncio
    from instr import AWAITED, SCPI, Command, BuildCommands

    @BuildCommands
    class MyInstr(SCPI):

        """A trivial example."""

        @Command(command="SYSTem:EXAMple[:ECHO]?", async_call=AWAITED, parameters=(str,))
        async def example(self, string):
            """An example method."""
            await asyncio.sleep(10)
            return string

    if __name__ == "__main__":
        MyInstr().run()

This adds a new SCPI query SYST:EXAM? str - or SYSTEM:EXAMPLE? str or SYST:EXAM:ECHO? str or SYSTEM:EXAMPLE:ECHO? str
that will sleep for 10 seconds and then simply echo its parameter back to the user. If the code is exectured as the top level file (e.g. by being saved as `main.py`, it will execute the instrument loop. As well as implementing the 
SYST:EXAM etc commands, it also implements the standard IEEE488.2 *IDN?, *RST etc commands and a SCPI commands related to operational condition registers and an error message queue - as required by the SCPI-99 Specification.

# Warning !

This code is really very experimental! It's not extensively tested and is probably rather fragile so please don't try to use it in a situation where expensive damage or harm to people might result from failure without doing a full check and test yourself!

# Disclaimer

The full SCPI specification is fairly detailed and has a number of features that are not widely used in real world instruments.
This code implements a limited, tested subset rather than claiming complete SCPI-1999 or IEEE 488.2 conformance.

Specifically, it supports the common '\*' required IEEE488.2 commands. It supports long and short forms of device dependent
commands and optional nodes. Commands can be concatendated with semi-colons and device
dependent commands can be absolute from the root node of the command tree (with the initial colon being optional) or
relative to the parent of the last executed command node.

## Command grammar and channels

Numeric suffixes are not inferred from command headers. A digit is accepted only when it is part of an explicitly declared
header, such as `OUTput1`. For channel-oriented commands, define the channel as a normal parameter so that conversion and
bounds checking remain explicit:

    @Command(
        command="OUTPut:LEVel",
        parameters=(Int(min=0, max=7), Float(min=0, max=100)),
    )
    def set_level(self, channel, level):
        ...

This accepts `OUTPUT:LEVEL 2,50`; it does not derive `OUTPUT2:LEVEL 50`. Existing applications with literal numbered
headers remain supported because those digits are part of their declared command strings.

What is not supported ;out of the box' is units on parameters and expressions. In principle both could be implemented
by providing parameter conversion functions that were aware of either. The provided parameter conversion functions are:
- **scpi.Float**(min=\<val\>,max=\<val\>,nan=\<val\>,default=\<val\>) supports conversions with optional MIN, MAX, NAN and DEF
  values. Every numeric min or max is enforced inclusively and a ParameterDataOutOfRange error is raised for values outside it.
- **scpi.Int**(min=\<val\>,max=\<val\>, default=\<val\>) similarly to scpi.Float converts values to integers with limits and default
  value.
- **scpi.Boolean** converts `ON`, `1`, `YES`, and `TRUE` to True and `OFF`, `0`, `NO`, and `FALSE` to False. A built-in
  `bool` command parameter uses the same conversion for compatibility.
- **scpi.Enum**(LABel1=\<val\>,LABel2=\<val\>...) maps SCPI labels, including their long and short forms, to Python values.
  Positional labels map to themselves. Input values are converted to uppercase before matching. Unmatched labels get a
  DataTypeError.

# Details

The bulk of the work of mapping SCPI commands to python methods is done by the two decorators: @BuildCommands and @Command.

The SCPI class defines the framework's supported common-command and status subset, documented in
[`STATUS_MODEL.md`](STATUS_MODEL.md). The main machinery is handled by the Instrument class. Its async command loop
collects input from a transport and passes each line to the parse_cmd() method that is
responsible for extracting any parameters and then attemptoing to map the SCPI command string to a method. If the
command doesn't start with a : or * then the search starts at the last command_map dictionary tried - thus supporting
the SCPI standard for by passing a long traversal of the command tree for adjacent commands. Note the parse_cmd() method
exclusively deals with strings - it does not map either the command or the parameters to relevant types.

Once the parse_cmd() method passes back to the run_commands() method, run_commands()then looks up the corresponding
attribute to return the Executable instance. This instance provides the prep_parameters() method that transforms the
string parameters to the correct native Python types. After this the async_Call attribute of the Executable instance is
inspected to dtermine the calling method (async task, async blocking or synchronous) and the method is dispatched.
For queries, the returned scalar or string is serialized by the dispatcher and written as exactly one terminated
response through the active transport. Non-query return values are ignored.

The SCPIError exception (and subclasses) is used to flag parsing and command execution errors. They are caught at the
command boundary and added to a bounded FIFO `error_q`. This queue is depleted by `SYST:ERROR:NEXT?`; its state updates
the status-byte error summary bit.

Async tasks are created by `_start_task()` and completed by `_reap_tasks()`, which always retrieves the task result.
Expected SCPI failures enter the queue directly; unexpected failures invoke the configured fail-safe and diagnostic
hooks before one execution error is queued. A lightweight monitor performs this cleanup even while command input is
idle. Status commands such as `*OPC?` use the task list to determine when work has completed. `*RST` cancels and awaits
non-system tasks before clearing the registers.

## @Command Decorator

Synopsis:

@Command(command=<SCPI command string>, async_call=SYNC|BACKGROUND|AWAITED, parameters=tuple)

The \<SCPI Command string\> tries to be similar to how SCPI commands are documented in manuals - a mixture of short
UPPer case letters defining a command abreviation and a verbose command defines in mixed case. As with all SCPI
commands, they are organised in a tree like structure with : separating the levels. Optional parts of the commands can
be enclosed in []. It is possible to have both multiple and nested optional parts of the command string and all the
permutations will be supported.

The async_call parameter is optional and controls how the method is called. Use the exported `SYNC`, `BACKGROUND`, and
`AWAITED` names; the compatibility values `0`, `1`, and `2` are also accepted. If it is not given, coroutine functions
are detected where the runtime supports it and run in the background; ordinary functions run synchronously. Synchronous execution
means the microcontroller will
only run that method and will not respond to other commands or let other commands tunning in the background run. For
obvious reasons, therefore, you should ensure that all synchronous methods are quick! With `BACKGROUND`, the method runs as a background task
with uasyncio.create_task(). Such a mthod will run when the microcontroller is waiting for further commands or in
parallel with other tasks that have yielded time. With `AWAITED`, the coroutine is awaited before another command is processed. This will allow other backgrounded commands to run (so long as
 your command yields the processor with a uasyncio.sleep() or similar) but will not all any further commands to be
processed. This is used, for example, for the *OPC? and *WAI commands to block further commands until the current
operations are all finshed.

Async execution modes must return an awaitable. Conversely, a synchronous command that returns an awaitable is rejected
with a controlled execution error so a coroutine cannot be silently dropped.
Queries cannot use `BACKGROUND`, because that could reorder their responses; use `AWAITED` for asynchronous queries.

## Compatibility notes for the converter/dispatch fixes

- `bool` parameters now interpret SCPI false tokens correctly instead of relying on Python string truthiness.
- `Int` and `Float` enforce integer-valued bounds as well as floating-point bounds; boolean and invalid bounds are rejected at construction.
- `Enum` keyword arguments are now label-to-value mappings, for example `Enum(POWer="power")`. Applications written around the former reversed behavior must swap their keyword names and values.
- Async handlers should declare `BACKGROUND` or `AWAITED` explicitly for portability to MicroPython runtimes that cannot identify coroutine functions reliably.
- `SCPI.reset()` is now awaited so task cancellation can finish before `*RST` completes. Overrides must therefore be async and should await `super().reset()`.

## Runtime safety and lifecycle

This section is an overview. [`INSTRUMENT_SUBCLASS_CONTRACT.md`](INSTRUMENT_SUBCLASS_CONTRACT.md) is authoritative for
subclass implementations.

`Instrument` accepts optional `fail_safe`, `diagnostic_handler`, and `disconnect_handler` callbacks. A fail-safe callback
has the signature `(command_name, exception)` and should disable hazardous outputs. A diagnostic callback has the same
signature and must write only to a separate diagnostic sink, never the SCPI response stream. The disconnect callback is
zero-argument. Callbacks can also be installed later with `set_fail_safe()` and `set_disconnect_handler()`.

The error queue defaults to 16 entries and can be configured with `error_queue_capacity`. It is oldest-first. If it
fills, the newest slot becomes `-350,"Queue overflow"`; subsequent errors are discarded until the host drains space.
An empty `SYSTem:ERRor[:NEXT]?` returns `0,"No error"`.

Blank and whitespace-only input lines are ignored. EOF raises the distinct `TransportClosed` condition internally,
runs the disconnect policy, and ends that transport session. Reconnection is deliberately owned by the application or
transport layer. Empty semicolon-separated units are also ignored, so leading, trailing, and repeated semicolons are
safe.

The repository `main.py` demonstrates a single-session lifecycle. The ADC current source starts disabled, failures are
preserved in `LAST_BOOT_ERROR` without printing into SCPI output, and no automatic restart occurs. A board application
that opts into restart should add an explicit delayed policy around `main()`.

## Status behavior

The tested status flow is condition to positive-transition event latch to enable mask to status-byte summary to
service request. `*ESR?` and device event queries are read-and-clear; `*CLS` clears latches and errors without changing
conditions or enable masks; `STATus:PRESet` affects only the operation/questionable status subsystem; and self-test is
the query `*TST?`. Mask widths and the reserved SRE bit are validated explicitly. See
[`STATUS_MODEL.md`](STATUS_MODEL.md) for the precise behavior and exclusions.

## Transports and query responses

`Transport` defines three async methods: `readline()`, `write_response(text)`, and `close()`. `Instrument.run()` uses
`StdioTransport` by default, preserving the USB serial/stdin workflow. A transport can instead be supplied to the
instrument constructor:

    from instr import SCPI, UARTTransport
    from machine import UART

    instrument = SCPI(transport=UARTTransport(UART(0, baudrate=115200)))
    instrument.run()

`StreamTransport` adapts asynchronous byte or text reader/writer pairs, including TCP-style streams.
`MemoryTransport` provides deterministic host-side sessions and records fully framed responses.

Query handlers should return a scalar or string. The dispatcher converts booleans to `0`/`1`, strips any handler-supplied
line ending, adds the transport terminator once, and serializes writes with a lock. Built-in SCPI, ADC1220, and LED query
handlers all use this path; background framework commands no longer print progress into the response stream.

For one compatibility release, an application that still has `print()`-based query handlers can construct its instrument
with `legacy_print_handlers=True`. In that mode a query returning `None` is assumed to have printed its own response and
the dispatcher does not add another. This compatibility mode is intended only for the original stdio transport and can
still interleave global stdout; migrate handlers to returned values before selecting UART/TCP transports.

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

Command maps are validated before they are attached to the class. Collisions between short forms, long forms, optional
expansions, inherited commands, or terminal aliases raise `CommandMapCollisionError` without leaving a partially built
class. A subclass may intentionally replace an inherited handler only by declaring the same complete canonical command.
Changing the command attached to an inherited Python method name is rejected as ambiguous.

See [`MIGRATION.md`](MIGRATION.md) for compatibility guidance and [`CHANGELOG.md`](CHANGELOG.md) for the current release
summary.
