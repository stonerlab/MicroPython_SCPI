import asyncio

import pytest

from lib.instr.decorators import BuildCommands, Command, Executable
from lib.instr.exceptions import CommandError, CommandMapCollisionError
from lib.instr.scpi import Instrument, SCPI
from lib.instr.transport import MemoryTransport
from lib.instr.types import Int


def run(coro):
    return asyncio.run(coro)


def test_inherited_command_metadata_is_not_reprocessed():
    @BuildCommands
    class ChildInstrument(SCPI):
        @Command(command="CHILD")
        def child(self):
            pass

    assert ChildInstrument._scpi_opc.name == "opc"
    assert ChildInstrument.command_map["*OPC"] == "_scpi_opc"


def test_duplicate_command_aliases_are_rejected_atomically():
    class DuplicateCommands:
        @Command(command="SYSTem:ERRor?")
        def first(self):
            pass

        @Command(command="SYSTem:ERRor?")
        def second(self):
            pass

    with pytest.raises(CommandMapCollisionError, match=r"SYST:ERR\?.*first.*second"):
        BuildCommands(DuplicateCommands)
    assert "command_map" not in DuplicateCommands.__dict__
    assert isinstance(DuplicateCommands.first, Executable)
    assert isinstance(DuplicateCommands.second, Executable)


def test_short_form_terminal_collision_is_rejected():
    class ShortCollision:
        @Command(command="VOLTage?")
        def voltage(self):
            pass

        @Command(command="VOLTime?")
        def time(self):
            pass

    with pytest.raises(CommandMapCollisionError, match=r"VOLT\?"):
        BuildCommands(ShortCollision)


def test_short_form_node_collision_is_rejected_even_with_different_leaves():
    class NodeCollision:
        @Command(command="SENSe:VOLTage?")
        def voltage(self):
            pass

        @Command(command="SENSor:CURRent?")
        def current(self):
            pass

    with pytest.raises(CommandMapCollisionError, match="SENS"):
        BuildCommands(NodeCollision)


def test_long_alias_collision_with_different_short_forms_is_rejected():
    class LongCollision:
        @Command(command="SYSTem?")
        def first(self):
            pass

        @Command(command="SYStem?")
        def second(self):
            pass

    with pytest.raises(CommandMapCollisionError, match=r"SYSTEM\?"):
        BuildCommands(LongCollision)


def test_optional_expansion_cannot_duplicate_another_handler():
    class OptionalCollision:
        @Command(command="MEASure[:VOLTage]?")
        def optional(self):
            pass

        @Command(command="MEASure?")
        def direct(self):
            pass

    with pytest.raises(CommandMapCollisionError, match=r"MEAS\?"):
        BuildCommands(OptionalCollision)


def test_optional_node_expands_to_valid_terminal_and_branch_forms():
    @BuildCommands
    class OptionalCommand:
        @Command(command="SYSTem[:VERSion]?")
        def version(self):
            pass

    assert OptionalCommand.command_map["SYST?"] == "_scpi_version"
    assert OptionalCommand.command_map["SYSTEM?"] == "_scpi_version"
    assert OptionalCommand.command_map["SYST"]["VERS?"] == "_scpi_version"
    assert OptionalCommand.command_map["SYSTEM"]["VERSION?"] == "_scpi_version"


def test_terminal_and_branch_for_same_canonical_node_can_coexist():
    @BuildCommands
    class TerminalAndBranch:
        @Command(command="SYSTem")
        def system(self):
            pass

        @Command(command="SYSTem:VERSion?")
        def version(self):
            pass

    node = TerminalAndBranch.command_map["SYST"]
    assert node is TerminalAndBranch.command_map["SYSTEM"]
    assert node["_"] == "_scpi_system"
    assert node["VERS?"] == "_scpi_version"
    assert node["VERSION?"] == "_scpi_version"


def test_subclass_can_intentionally_override_same_canonical_command():
    @BuildCommands
    class Base(Instrument):
        @Command(command="READing?")
        def base_reading(self):
            return "base"

    @BuildCommands
    class Child(Base):
        @Command(command="READing?")
        def child_reading(self):
            return "child"

    assert Base.command_map["READ?"] == "_scpi_base_reading"
    assert Child.command_map["READ?"] == "_scpi_child_reading"
    transport = MemoryTransport()
    run(Child().process_line("READ?", transport=transport))
    assert transport.responses == ["child\n"]


def test_subclass_same_method_name_cannot_change_canonical_command():
    @BuildCommands
    class Base:
        @Command(command="READing?")
        def reading(self):
            pass

    class Child(Base):
        @Command(command="FETCh?")
        def reading(self):
            pass

    with pytest.raises(CommandMapCollisionError, match="READing"):
        BuildCommands(Child)


def test_inherited_alias_collision_with_different_command_is_rejected():
    @BuildCommands
    class Base:
        @Command(command="VOLTage?")
        def voltage(self):
            pass

    class Child(Base):
        @Command(command="VOLTime?")
        def time(self):
            pass

    with pytest.raises(CommandMapCollisionError, match=r"VOLT\?"):
        BuildCommands(Child)


def test_monkeypatched_existing_implementation_is_seen_by_existing_child():
    @BuildCommands
    class Base(Instrument):
        @Command(command="VALUE?")
        def value(self):
            return "original"

    @BuildCommands
    class Child(Base):
        pass

    def replacement(self):
        return "patched"

    Base.value = replacement
    transport = MemoryTransport()
    run(Child().process_line("VALUE?", transport=transport))
    assert transport.responses == ["patched\n"]


def test_monkeypatched_new_parent_command_does_not_mutate_existing_child_map():
    @BuildCommands
    class Base:
        @Command(command="FIRST?")
        def first(self):
            pass

    @BuildCommands
    class Child(Base):
        pass

    def second(self):
        return 2

    Base.second = Command(command="SECOND?")(second)
    BuildCommands(Base)
    assert Base.command_map["SECOND?"] == "_scpi_second"
    assert "SECOND?" not in Child.command_map


def test_numeric_suffix_is_not_implicit_and_explicit_channel_parameter_works():
    @BuildCommands
    class ChannelInstrument(Instrument):
        @Command(command="CHANnel:LEVel?", parameters=(Int(min=0, max=7),))
        def level(self, channel):
            return channel

    instrument = ChannelInstrument()
    transport = MemoryTransport()
    run(instrument.process_line("CHANNEL:LEVEL? 2", transport=transport))
    assert transport.responses == ["2\n"]

    run(instrument.process_line("CHANNEL2:LEVEL?", transport=transport))
    assert isinstance(instrument.error_q.popleft(), CommandError)
    assert transport.responses == ["2\n"]
