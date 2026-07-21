"""decorators for constructing SCPI driver class."""
__all__ = ["BuildCommands", "Command", "SYNC", "BACKGROUND", "AWAITED", "prep_plist"]
from copy import deepcopy
import re

from .exceptions import (
    CommandMapCollisionError,
    CommandSyntaxError,
    DataTypeError,
    SCPIError,
    TooFewParameters,
    TooManyParameters,
)


# Named execution modes.  The integer values preserve the public async_call=0/1/2
# API used by existing applications.
SYNC = 0
BACKGROUND = 1
AWAITED = 2


def _is_coroutine_function(fnc):
    """Return whether *fnc* is an async function without requiring inspect."""
    try:
        from inspect import iscoroutinefunction

        return iscoroutinefunction(fnc)
    except ImportError:  # MicroPython does not provide the full inspect module.
        code = getattr(fnc, "__code__", None)
        return bool(getattr(code, "co_flags", 0) & 0x80)


def tokenize(string, splitter):
    """Take string, look for quoted parts and replace with a token and then split on splitter."""
    tokens = []
    quote_search = re.compile(r"(\"[^\"]*\")")
    while '"' in string:
        match = quote_search.search(string)
        if not match:
            raise CommandSyntaxError
        ix = len(tokens)
        tokens.append(match.groups(0)[0])
        string = string[: match.start()] + f"<<{ix}>>" + string[match.end() :]
    words = string.split(splitter)
    for ix, word in enumerate(words):
        for iy in range(len(tokens)):
            if f"<<{iy}>>" in word:
                word = word.replace(f"<<{iy}>>", tokens[iy])
        words[ix] = word
    return words


def prep_part(cmd):
    """Split a command pattern on :, find stem long and short forms and remainder."""
    parts = cmd.split(":")
    stem = parts[0]
    remainder = ":".join(parts[1:])
    short_stem = re.sub("[a-z]", "", stem)
    stem = stem.upper()
    return short_stem, stem, remainder


def prep_plist(cmd):
    """Separate parameter list from commands."""
    if " " in cmd:  # We have some parameters
        plist = cmd[cmd.index(" ") :].strip()
        cmd = cmd[: cmd.index(" ")].upper().strip()
        plist = tokenize(plist, ",")
    else:
        plist = []
        cmd = cmd.upper().strip()
    return cmd, plist


def expand_optional(command):
    """Where there is a [] in the command, create an entry with and without it recursively."""
    commands = [command]
    ix = 0
    while ix < len(commands):
        command = commands[ix]
        if "[" in command:
            commands[ix] = re.sub(r"\[[^\[\]]*\]", "", command, 1)
            commands.append(re.sub(r"\[([^\[\]]*)\]", r"\1", command, 1))
        else:
            ix += 1
    return commands


def Command(command="", async_call=None, parameters=tuple()):
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
        is_async = _is_coroutine_function(fnc)
        if async_call is None:
            async_op = BACKGROUND if is_async else SYNC
        elif async_call in (False, SYNC):
            if is_async:
                raise TypeError(
                    f"Async command handler {fnc.__name__} cannot use synchronous execution mode"
                )
            async_op = SYNC
        elif async_call in (True, BACKGROUND):
            async_op = BACKGROUND
        elif async_call == AWAITED:
            async_op = AWAITED
        else:
            raise ValueError("async_call must be SYNC/0, BACKGROUND/1, or AWAITED/2")
        ret = Executable(fnc, async_call=async_op, command=command, parameters=parameters)
        return ret

    return _command


def _command_aliases(command):
    """Return aliases and canonical signatures for one expanded command."""
    aliases = []
    signature = []
    for part in command.split(":"):
        short, long, _ = prep_part(part)
        short, _ = prep_plist(short)
        long, _ = prep_plist(long)
        part_aliases = (short,) if short == long else (short, long)
        aliases.append(part_aliases)
        signature.append((short, long))
    return aliases, tuple(signature)


def _collision(cls, path, existing, command, name):
    alias = ":".join(path)
    owner = existing[2]
    owner_name = getattr(owner, "__name__", str(owner))
    old_command = existing[3]
    raise CommandMapCollisionError(
        f"SCPI command collision for {alias}: {owner_name}.{existing[1][6:]} "
        f"({old_command}) conflicts with {cls.__name__}.{name} ({command})"
    )


def _register_provenance(cls, method, name, node_provenance, command_provenance):
    """Validate and record every alias generated by one executable."""
    target = f"_scpi_{name}"
    expanded = expand_optional(method.command)
    declarations = []
    signatures = []
    for command in expanded:
        aliases, signature = _command_aliases(command)
        declarations.append((command, aliases, signature))
        signatures.append(signature)

    inherited_for_target = [
        entry for entry in command_provenance.values() if entry[1] == target and entry[2] is not cls
    ]
    for existing in inherited_for_target:
        if existing[0] not in signatures:
            _collision(cls, (existing[3],), existing, method.command, name)

    for command, aliases, signature in declarations:
        paths = [tuple()]
        for depth, part_aliases in enumerate(aliases):
            canonical_prefix = signature[: depth + 1]
            paths = [path + (alias,) for path in paths for alias in part_aliases]
            for path in paths:
                existing_node = node_provenance.get(path)
                if existing_node is not None and existing_node != canonical_prefix:
                    existing = command_provenance.get(path, (existing_node, "_scpi_node", "inherited", ":".join(path)))
                    _collision(cls, path, existing, command, name)
                node_provenance[path] = canonical_prefix

        entry = (signature, target, cls, method.command)
        for path in paths:
            existing = command_provenance.get(path)
            if existing is not None:
                same_declaration = existing[0] == signature
                same_handler = existing[1] == target
                inherited_override = same_declaration and existing[2] is not cls
                if not same_handler and not inherited_override:
                    _collision(cls, path, existing, command, name)
                if same_handler and not same_declaration:
                    _collision(cls, path, existing, command, name)
            command_provenance[path] = entry
    return declarations


def _insert_command(command_map, command, target):
    """Insert a validated expanded command into a nested command map."""
    add_to = command_map
    parts = command.split(":")
    for part in parts[:-1]:
        short, long, _ = prep_part(part)
        node = add_to.get(long) or add_to.get(short)
        if isinstance(node, str):
            node = {"_": node}
        if node is None:
            node = {"_": ""}
        add_to[long] = node
        add_to[short] = node
        add_to = node

    short, long, _ = prep_part(parts[-1])
    short, _ = prep_plist(short)
    long, _ = prep_plist(long)
    for alias in (short, long):
        if alias in add_to and isinstance(add_to[alias], dict):
            add_to[alias]["_"] = target
        else:
            add_to[alias] = target


def BuildCommands(cls):
    """Build and validate a command map from Executable class attributes.

    Notes:
        Typical usage is to decorate a class that has methods that have been decorated with @Command in order to
        define a set of SCPI commands that the class should respond to. If the class doesn't have a command_map defined on the class
        but a parent class does, then the parent class command_map is deep copied and added to the current class - thus commands can
        be inherited from parent classes, but the command_maps are not shared.

        The downside of this is that monkeypatching of additional commands in a parent class is not reflected in already defined child
        classes. It is, however, possible to override parent implementation of commands in a child class, or to monkeypatch the parent class
        implementations of existing commands.

        Command aliases and provenance are validated in temporary structures. A collision therefore raises
        CommandMapCollisionError without partially modifying the class. A subclass can replace a handler only when it declares the
        same complete canonical command as its parent.

        It is also possible to simply have Executable instance class attributes that wrap arbitary functions so long as they expect an
        Instrument class argument as their first parameter.
    """
    command_map = deepcopy(getattr(cls, "command_map", {}))
    node_provenance = deepcopy(getattr(cls, "_command_node_provenance", {}))
    command_provenance = deepcopy(getattr(cls, "_command_provenance", {}))
    methods = [
        (name, method)
        for name, method in cls.__dict__.items()
        if not name.startswith("_scpi_") and isinstance(method, Executable)
    ]
    registrations = []
    for name, method in methods:
        declarations = _register_provenance(
            cls, method, name, node_provenance, command_provenance
        )
        registrations.append((name, method, declarations))
        for command, _, _ in declarations:
            _insert_command(command_map, command, f"_scpi_{name}")

    # Commit only after the complete class validates, so a collision cannot
    # leave a partially-built command map or partially-unwrapped methods.
    cls.command_map = command_map
    cls._command_node_provenance = node_provenance
    cls._command_provenance = command_provenance
    for name, method, _ in registrations:
        setattr(cls, name, method.fnc)
        setattr(cls, f"_scpi_{name}", method)
    return cls


class Executable(object):

    """Wrapper class that permits metadata about the SCPI command to be stored aloing with the method."""

    def __init__(self, fnc, async_call=True, command="", parameters=tuple()):
        self.fnc = fnc
        self.async_call = async_call
        self.command = command
        self.parameters = parameters
        self.name = fnc.__name__
        self.is_query = command.rstrip().endswith("?")

    def __call__(self, *args):
        """Actually run the command."""
        return self.fnc(*args)

    def __repr__(self):
        return f"{self.command} - {self.fnc.__name__} ({self.fnc.__class__.__name__})({','.join([str(x) for x in self.parameters])})"

    def prep_parameters(self, plist):
        """Convert plist in strings to correct python types using parameters attribute."""
        if len(plist) > len(self.parameters):
            raise TooManyParameters
        if len(plist) < len(self.parameters):
            raise TooFewParameters
        for ix, (arg, param) in enumerate(zip(plist, self.parameters)):
            try:
                if param is bool:
                    # Import lazily to avoid the decorators/types import cycle.
                    from .types import Boolean

                    plist[ix] = Boolean(arg)
                else:
                    plist[ix] = param(arg)
            except SCPIError:
                raise
            except (TypeError, ValueError):
                raise DataTypeError
        return plist
