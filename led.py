from instr import TestInstrument, OnOffFloat, Int, Command, BuildCommands

try:
    from machine import Pin, PWM
except ImportError:
    from shim import Pin, PWM

from instr.exceptions import ParameterDataOutOfRange


@BuildCommands
class LED(TestInstrument):
    def __init__(self):
        self.pwm = []
        self.level = []
        for ix in range(14, 17):
            pwm = PWM(Pin(ix))
            pwm.freq(10_000)
            pwm.duty_u16(0)
            self.pwm.append(pwm)
            self.level.append(0)
        super().__init__()

    def _set_level(self, led, level):
        if not 0 <= level <= 100:
            raise ParameterDataOutOfRange
        self.level[led] = level
        int_level = int(round(650.25 * level))
        self.pwm[led].duty_u16(int_level)

    def _set_freq(self, led, freq):
        if not 7.5 < freq < 10e6:
            raise ParameterDataOutOfRange
        self.pwm[led].freq(freq)

    @Command(command="OUTput[0][:LEVeL]", parameters=(OnOffFloat,))
    def set_level(self, level):
        self._set_level(0, level)

    @Command(command="OUTput[0][:LEVeL]?")
    def read_level(self):
        print(f"{self.level[0]:.1f}%")

    @Command(command="OUTput[0]:FREQuerncy", parameters=(Int(min=10, max=1_000_000, default=10_000),))
    def set_freq(self, freq):
        self._set_freq(0, freq)

    @Command(command="OUTput[0]:FREQuency?")
    def read_freq(self):
        print(self.pwm[0].freq())

    @Command(command="OUTput1[:LEVeL]", parameters=(OnOffFloat,))
    def set_level1(self, level):
        self._set_level(1, level)

    @Command(command="OUTput1[:LEVeL]?")
    def read_level1(self):
        print(f"{self.level[1]:.1f}%")

    @Command(command="OUTput1:FREQuerncy", parameters=(Int(min=10, max=1_000_000, default=10_000),))
    def set_freq1(self, freq):
        self._set_freq(1, freq)

    @Command(command="OUTput1:FREQuency?")
    def read_freq1(self):
        print(self.pwm[1].freq())

    @Command(command="OUTput2[:LEVeL]", parameters=(OnOffFloat,))
    def set_level2(self, level):
        self._set_level(2, level)

    @Command(command="OUTput2[:LEVeL]?")
    def read_level2(self):
        print(f"{self.level[2]:.1f}%")

    @Command(command="OUTput2:FREQuerncy", parameters=(Int(min=10, max=1_000_000, default=10_000),))
    def set_freq2(self, freq):
        self._set_freq(2, freq)

    @Command(command="OUTput2:FREQuency?")
    def read_freq2(self):
        print(self.pwm[2].freq())

    @Command(command="OUTput:ALL[:LEVeL]", parameters=(OnOffFloat,))
    def set_all_level(self, level):
        for ix in range(3):
            self._set_level(ix, level)


if __name__ == "__main__":
    runner = LED()
