"""decorators for constructing SCPI driver class."""
__all__=["BuildCommands","Command","prep_plist"]
from copy import deepcopy
import re

from exceptions import TooFewParameters, TooManyParameters, DataTypeError

def prep_part(cmd):
    """Split a command pattern on :, find stem long and short forms and remainder."""
    parts=cmd.split(":")
    stem=parts[0]
    remainder=":".join(parts[1:])
    short_stem=re.sub("[a-z]","",stem)
    stem=stem.upper()
    return short_stem,stem,remainder

def prep_plist(cmd):
    """Separate parameter list from commands."""
    if " " in cmd: # We have some parameters
        plist=cmd[cmd.index(" "):].strip()
        cmd=cmd[:cmd.index(" ")].upper().strip()
        plist=re.sub(r'\"([^\"]*)\,([^\"]*)\"',r'\1|\2',plist)
        plist=re.sub(r'\"([^\"]*)\"',r'\1',plist)
        plist=[x.replace("|",",") for x in plist.split(",")]
    else:
        plist=[]
        cmd=cmd.upper().strip()
    return cmd,plist

def expand_optional(command):
    """Where there is a [] in the command, create an entry with and without it recursively."""
    commands=[command]
    ix=0
    while ix<len(commands):
        command=commands[ix]
        if "[" in command:
            commands[ix]=re.sub(r'\[[^\[\]]*\]','',command, 1)
            commands.append(re.sub(r'\[([^\[\]]*)\]',r'\1',command, 1))
        else:
            ix+=1
    return commands


def Command(command="",async_call=False, parameters=tuple()):
    """Mark the class method as implementing a SCPI Command.

    Keyword Arguments:
        command (str):
            SCPI command to bind to the method. The command can be given in mixed case with optional sections - e.g.
            SYSTem:ERRor[:NEXT]? the upper case letters construct the short form abbreviation and the square brackets indicate
            parts that may be ommitted. Entries for all variants are added to the command_map dictionary.
        async_call (bool, int):
            Is the command run as an async task or not. If False, run synchonously, this will
            block all other commands from running and new commands being accepted, so commands
            should be quick to execute.
            If 1, then run the command as an async task and return to process more tasks
            If 2, then the command is run asynchronously, but waited for. This blocks other
            new commands from being accepted, but allows existing async commands to finish.
        parameters (tuple of callable):
            A set of callables that should be used to convert the string arguments to the correct python type
            for passing to the method.

    Notes:
        This decorator replaces the method in the class with an instance of the Executable class that stores the metadata.
        This is because a generator object cannot have arbitary attributes added to it to store the extra metadata.
    """
    def _command(fnc):
        """Real decorator for function."""
        if not async_call and fnc.__class__.__name__=="generator":
            async_op=1 # Call with await
        else:
            async_op=async_call
        ret= Executable(fnc,async_call=async_op,command=command,parameters=parameters)
        return ret
    return _command

def BuildCommands(cls):
    """Class decorator that scans for Executable instance attributes and builds a command_map ictionary attribute.

    Notes:
        Typical usage is to decorate a class that has methods that have been decorated with @Command in order to
        define a set of SCPI commands that the class shopuld respond to. If the class doesn't have a command_map defined on the class
        but a parent class does, then the parent class command_map is deep copied and added to the current class - thus commands can
        be inherited from parent classes, but the command_maps are not shared.

        The downside of this is that monkeypatching of additional commands in a parent class is not reflected in already defined child
        classes. It is, however, possible to override parent implementation of commands in a child class, or to monkeypatch the parent class
        implementations of existing commands.

        It is also possible to simply have Executable instance class attributes that wrap arbitary functions so long as they expect an
        Instrument class argument as their first parameter.
    """
    if "command_map" not in cls.__dict__: # Ensure each class has it's own copy of the command_map
        if not hasattr(cls,"command_map"):
            setattr(cls,"command_map",dict())
        else:
            setattr(cls,"command_map",deepcopy(cls.command_map))
    for name,method in [(x, getattr(cls,x)) for x in dir(cls) if isinstance(getattr(cls,x),Executable)]:
            setattr(cls,name,method.fnc) # restore the original method
            setattr(cls,f"_scpi_{name}",method) # The shadow SCPI method
            commands=expand_optional(method.command)
            for command in commands:
                add_to=cls.command_map
                while ":" in command:
                    sstem,stem,command=prep_part(command)
                    if isinstance(add_to.get(stem,None),str):
                        add_to[stem]={"_":add_to[stem]}
                    if isinstance(add_to.get(sstem,None),str):
                        add_to[sstem]=add_to[stem]
                    add_to.setdefault(stem,{"_":""})
                    add_to.setdefault(sstem,add_to[stem])
                    add_to=add_to[stem]
                command,long_command,_=prep_part(command)
                command,_=prep_plist(command)
                long_command,_=prep_plist(long_command)
                if command in add_to and isinstance(add_to[command],dict):
                    add_to[command]["_"]=name
                else:
                    add_to[command]=name
                if long_command in add_to and isinstance(add_to[long_command],dict):
                    add_to[long_command]["_"]=name
                else:
                    add_to[long_command]=f"_scpi_{name}"
    return cls

class Executable(object):

    """Wrapper class that permits metadata about the SCPI command to be stored aloing with the method."""

    def __init__(self,fnc,async_call=True,command="", parameters=tuple()):
        self.fnc=fnc
        self.async_call=async_call
        self.command=command
        self.parameters=parameters
        self.name=fnc.__name__

    def __call__(self,*args):
        """Actually run the command."""
        return self.fnc(*args)

    def __repr__(self):
        return f"{self.command} - {self.fnc.__name__} ({self.fnc.__class__.__name__})({','.join([str(x) for x in self.parameters])})"

    def prep_parameters(self,plist):
        """Convert plist in strings to correct python types using parameters attribute."""
        if len(plist)>len(self.parameters):
            raise TooManyParameters
        if len(plist)<len(self.parameters):
            raise TooFewParameters
        for ix,(arg,param) in enumerate(zip(plist,self.parameters)):
            try:
                if param is bool:
                    arg=arg.upper().replace("OFF","False").replace("0","False").replace("NO","False")
                plist[ix]=param(arg)
            except (TypeError,ValueError):
                raise DataTypeError
        return plist
