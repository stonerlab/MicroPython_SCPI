try:
    import uasyncio as asyncio
except ImportError:
    import asyncio
import sys

from decorators import BuildCommands, Command, prep_plist, tokenize
from exceptions import SCPIError, CommandError

def OnOffFloat(value):
    value=value.upper()
    if value in ["ON","YES","TRUE","DEF","DEFAULT"]:
        value=100.0
    if value in ["OFF","NO","FALSE"]:
        value=0.0
    return float(value)

class Instrument(object):

    """Base class to define the machinery for the REPL and commnd dispatch.

    Nothing in this class should need to be overriden other than the version string.

    After initialising the instrument, run instr.run() to start the event loop.
    """

    version = "0.0.1"

    def __init__(self):
        """Fire up an Async stream reader for sys,stdin and start reading commands."""
        self.current_node=None
        self.error_q=[]
        self.tasks=[]
        self.lock=asyncio.Lock()


    def run(self):
        self.reader=asyncio.StreamReader(sys.stdin)
        asyncio.run(self.read_commands())

    async def ainput(self):
        """Async read input from STDIN for reading commands."""
        cmd=""
        while True:
            cmd = await self.reader.readline()
            cmd=cmd.decode().strip()
            if cmd!="":
                break
        return cmd

    def parse_cmd(self,command):
        """Find the command in the command table and get the correspoindig method name and parameter list."""
        while True: # We potentially sscan the dictionary multiple times to locale a relative node
            cmd=command # Restart processing with whole command
            cmd,plist=prep_plist(cmd) #Get the parameters off the command first
            if cmd[0] in ":*" or self.current_node is None: #Start scanning from the root command map
                read_from=self.command_map
                self.current_node=None
            else: # Start scanning from the last node dictionary
                read_from=self.current_node
            if cmd[0]==":": cmd=cmd[1:] # Strip a leading : if present
            while ":" in cmd: # Split the command into levels
                parts=cmd.split(":")
                stem=parts[0].upper()
                cmd=":".join(parts[1:])
                if isinstance(read_from.get(stem,None),dict): #There are subcommands to this node
                    read_from=read_from[stem]
                elif self.current_node is not None: # Command not here, but we can try again with root node
                    break
                else: # Failed to find the next level and we were looking from the root node
                    raise CommandError
            if cmd not in read_from and self.current_node is not None: # restart from root node
                self.current_node=None
                continue
            if cmd in read_from: # Set the root lookup for the future
                self.current_node=read_from
            return read_from.get(cmd,None),plist

    async def read_commands(self):
        """Main dispatcher of commands."""
        try: # Catch KeyBoard Interrupt
            while True: # Main loop
                cmd_String = await self.ainput()
                for cmd in tokenize(cmd_String, ";"): # Deal with multiple commands
                    try:
                        cmd_runner,plist=self.parse_cmd(cmd)
                        if isinstance(cmd_runner,dict):
                            cmd_runner=cmd_runner.get("_",None)
                        if cmd_runner is None:
                            raise CommandError
                        cmd_runner=getattr(self,cmd_runner)
                        plist=cmd_runner.prep_parameters(plist)
                        real_command=getattr(self,cmd_runner.name,cmd_runner)
                        if cmd_runner.async_call==1: # Run as async task, continue to process requests
                            self.tasks.append((cmd_runner.name,asyncio.create_task(real_command(*plist))))
                        elif cmd_runner.async_call==2: # async task, but block executing more tasks for now
                            await real_command(*plist)
                        else: # Non async task
                            real_command(*plist)
                        done=list(reversed([ix for ix,task in enumerate(self.tasks) if task[1].done()]))
                        for ix in done: # Dead task collection
                            del self.tasks[ix]
                    except SCPIError as e: #Catch Instrument errors and append to the error queue
                        self.error_q.append(e)
                        continue
        except KeyboardInterrupt:
            return True


@BuildCommands
class SCPI(Instrument):

    """Base class that defines the minimum necessary comands to be SCPI Compatible"""

    @property
    def oper_reg(self):
        return self._oper_reg

    @oper_reg.setter #Setting operational status register might trigger events and stb changes
    def oper_reg(self,value):
        self._oper_reg=value
        if value&self.oper_enab:
            self.oper_event=value&self.oper_enab

    @property # Reading event register clears it.
    def open_event(self):
        ret=self._oper_event
        self._oper_event=0
        return ret

    @open_event.setter # Writing the event regist might also change the stb
    def oper_event(self,value):
        self._oper_event=value
        if value!=0:
            self.stb|=128
        if self.service_enab&128:
            self.stb|=64

    @property
    def ques_reg(self):
        return self._ques_reg

    @ques_reg.setter # Writing the questionable status register can cause events too
    def ques_reg(self,value):
        self._ques_reg=value
        if value&self.ques_enab:
            self.ques_event=value&self.ques_enab

    @property # Reading the event register will clear it
    def ques_event(self):
        ret=self._ques_event
        self._ques_event=0
        return ret

    @ques_event.setter # Writing the event register might change the stb
    def ques_event(self,value):
        self._ques_event=value
        if value!=0:
            self.stb|=8
        if self.service_enab&8:
            self.stb|=64

    @property
    def event_reg(self):
        return self._event_reg

    @event_reg.setter # Reading the standard event register can change the standard event event register
    def event_reg(self,value):
        self._event_reg=value
        if value&self.event_enab:
            self.event_event=value&self.event_enab

    @property # Reading the stadnard event event register clears it
    def event_event(self):
        ret=self._event_event
        self._event_event=0
        return ret

    @event_event.setter # Writing the standard event event register may change the stb.
    def event_event(self,value):
        self._event_event=value
        if value!=0:
            self.stb|=32
        if self.service_enab&32:
            self.stb|=64

    def __init__(self):
        """Initialise our registeres and other state."""
        self.stb=0
        self._oper_reg=0
        self.oper_enab=0
        self._oper_event=0
        self._ques_reg=0
        self._qyes_event=0
        self.ques_enab=0
        self._event_reg=0
        self.event_enab=0
        self._event_event=0
        self.service_enab=0
        super().__init__()

    @Command(command="*CLS")
    def cls(self):
        """Clear status registers and error queue."""
        self.error_q=[]
        self.stb=0
        self.ques_reg=0
        self.oper_reg=0

    @Command(command="*ESE",parameters=(int,))
    def ese(self,mask):
        """Set Standard Event Enable."""
        self.event_enab=mask

    @Command(command="*ESE?")
    def eseq(self):
        """Report Standard Event Enable."""
        print(self.event_enab)

    @Command(command="*ESR?")
    def esrq(self):
        """Report Standard Event Register."""
        print(self.event_reg)

    @Command(command="*IDN?")
    def idnq(self):
        """Implements *IDN?"""
        print(f"Raspberry Pico (MicroPython),{self.__class__.__name__},,{sys.version.split(' ')[2]}:{self.version}")

    @Command(command="*OPC")
    async def opc(self):
        """Keep checking for the currently executing tasks to finish."""
        tasks=[(name,x) for name,x in self.tasks if name not in ["opcq","opc","wait"]]
        while True:
            for task in tasks:
                if not task[1].done():
                    break
            else:
                break
            await asyncio.sleep(0.1)
        self.event_reg|=1

    @Command(command="*OPC?", async_call=2)
    async def opcq(self):
        """Block until all tasks are done."""
        tasks=[(name,x) for name,x in self.tasks if name not in ["opcq","opc","wait"]]
        while True:
            for task in tasks:
                if not task[1].done():
                    break
            else:
                break
            await asyncio.sleep(0.1)
        print(1)

    @Command(command="*RST")
    def reset(self):
        """This needs to be overriden to actually do the reset."""
        for task in self.tasks:
            task.cancel()
        self.cls()

    @Command(command="*SRE",parameters=(int,))
    def sre(self,mask):
        """Set the SRE register."""
        self.service_enab=mask

    @Command(command="*SRE?")
    def sreq(self):
        print(self.service_enab)

    @Command(command="*STB?")
    def stbq(self):
        """Implement a dummy *STB?"""
        if len(self.error_q):
            self.stb|=4
        else:
            self.stb&=251
        print(self.stb)

    @Command(command="*TST")
    def self_test(self):
        """Really a NOP !"""
        print(0)

    @Command(command="*WAI", async_call=2)
    async def wait(self):
        """Holduntil all tasks have stopped."""
        while True:
            for name,task in self.tasks:
                if name in ["opc","opcq","wait"]:
                    continue
                if not task.done():
                    break
            else:
                break
            await asyncio.sleep(0.1)

    @Command(command="SYSTem:ERRor[:NEXT]?")
    def read_error_q(self):
        """Pop the next error message of the queue and report it."""
        if len(self.error_q):
            err=self.error_q.pop()
        else:
            err=SCPIError
        print(f"{err.code},{err.message}")

    @Command(command="SYSTem:VERSion?")
    def read_version(self):
        print("1999.1")

    @Command(command="STATus:OPERation[:EVENt]?")
    def scpi_oper_event(self):
        print(self.oper_event)

    @Command(command="STATus:OPERation:CONDition?")
    def scpi_oper_reg(self):
        print(self.oper_reg)

    @Command(command="STATus:OPERation:ENABle?")
    def scpi_oper_enabq(self):
        print(self.oper_enab)

    @Command(command="STATus:OPERation:ENABle", parameters=(int,))
    def scpi_oper_enab(self, value):
        self.oper_enab=value

    @Command(command="STATus:QUEStionable[:EVENt]?")
    def scpi_ques_event(self):
        print(self.ques_event)

    @Command(command="STATus:QUEStionable:CONDition?")
    def scpi_ques_reg(self):
        print(self.ques_reg)

    @Command(command="STATus:QUEStionable:ENABle?")
    def scpi_ques_enabq(self):
        print(self.ques_enab)

    @Command(command="STATus:QUEStionable:ENABle", parameters=(int,))
    def scpi_ques_enab(self, value):
        self.ques_enab=value

    @Command(command="STATus:PRESet")
    def status_preset(self):
        self.reset()

@BuildCommands
class TestInstrument(SCPI):

    """Implement a set of test SCPI commands."""

    @Command(command="SYSTem:SLEEP",parameters=(float,))
    async def sleep(self,sleep_time):
        """Simply sleep for sleep_time seconds then print done."""
        if self.stb&1:
            print("Already sleeping!")
            return None
        print("Sleepy time....")
        self.stb^=1
        await asyncio.sleep(sleep_time)
        self.stb^=1
        print("Done")

    @Command(command="SYSTem:EXIT")
    def exit(self):
        """Exit the driver."""
        for name,task in self.tasks:
            task.cancel()
        sys.exit(self.stb)

    @Command(command="SYSTem:PRINt",parameters=(str,))
    def print(self,string):
        """Test command to echo back the input."""
        print(string)

    @Command(command="SYSTem:DEBUg?")
    def debug_tasks(self):
        for name,task in self.tasks:
            print(name,task.done())




if __name__=="__main__":
    runner=TestInstrument()
