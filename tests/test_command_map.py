import pytest

from lib.instr.decorators import BuildCommands, Command
from lib.instr.scpi import SCPI


def test_inherited_command_metadata_is_not_reprocessed():
    @BuildCommands
    class ChildInstrument(SCPI):
        @Command(command="CHILD")
        def child(self):
            pass

    assert ChildInstrument._scpi_opc.name == "opc"
    assert ChildInstrument.command_map["*OPC"] == "_scpi_opc"


@pytest.mark.xfail(strict=True, reason="F-15 collision detection is scheduled for change set 5")
def test_duplicate_command_aliases_are_rejected():
    with pytest.raises(ValueError, match="collision"):

        @BuildCommands
        class DuplicateCommands:
            @Command(command="SYSTem:ERRor?")
            def first(self):
                pass

            @Command(command="SYSTem:ERRor?")
            def second(self):
                pass
