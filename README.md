# MicroPython SCPI

This is an implementation of a SCPI-1999 command set for a MicroPython based microcontroller - specifically it is
being written for a Raspberry Pi Pico board. In other words, it lets you interact with a Pico as if it were a SCPI
instrument.

To use it, you write a subclass of the scpi.SCPI class and implement methods that are mapped to SCPI commands. To run
the instrumnet, you instantiate your class and execute the .run() method. After that the Pico will wait for input
on the USB COM port and respond when it sees a \n.

It is possible to implement the class methods as co-routines that can be executed as seperate tasks, allowing your
microcontroller to respond to other commands (e.g. status requests) in the meantime.

# Example

A simple example:

    import uasyncio as asyncio
    from scpi import SCPI
    from decorators import Command, BuildCommands

    @BuildCommands
    class MyInstr(SCPI):

        """A trivial example."""

        @Command(command="SYSTem:EXAMple[:ECHO]", parameters=(str,))
        await def example(self, string):
            """An example method."""
            await asyncio.sleep(10)
            print(string)

This adds a new SCPI command SYST:EXAM str - or SYSTEM:EXAMPLE str or SYST:EXAM:ECHO str or SYSTEM:EXAMPLE:ECHO str
that will sleep for 10 seconds and then simple echo its parameter back to the user.
