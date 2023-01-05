from scpi import TestInstrument, OnOffFloat
from decorators import Command, BuildCommands

try:
    from machine import Pin, PWM
except ImportError:
    from shim import Pin, PWM

from exceptions import ParameterDataOutOfRange

@BuildCommands
class LED(TestInstrument):

    def __init__(self):
        self.pwm=[PWM(Pin(14)),PWM(Pin(15))]
        self.pwm[0].freq(10000)
        self.pwm[1].freq(10000)
        self.pwm[0].duty_u16(0)
        self.pwm[1].duty_u16(0)
        self.level=[0.0,0.0]
        super().__init__()

    @Command(command="OUTput[0][:LEVeL]", parameters=(OnOffFloat,))
    def set_level(self,level):
        if not 0<=level<=100:
            raise ParameterDataOutOfRange
        self.level[0]=level
        int_level=int(round(650.25*level))
        self.pwm[0].duty_u16(int_level)

    @Command(command="OUTput[0][:LEVeL]?")
    def read_level(self):
        print(f"{self.level[0]:.1f}%")

    @Command(command="OUTput[0]:FREQuerncy", parameters=(int,))
    def set_freq(self,freq):
        if not 7.5<freq<10E6:
            raise ParameterDataOutOfRange
        self.pwm[0].freq(freq)

    @Command(command="OUTput[0]:FREQuency?")
    def read_freq(self):
        print(self.pwm[0].freq())

    @Command(command="OUTput1[:LEVeL]", parameters=(OnOffFloat,))
    def set_level1(self,level):
        if not 0<=level<=100:
            raise ParameterDataOutOfRange
        self.level[1]=level
        int_level=int(round(650.25*level))
        self.pwm[1].duty_u16(int_level)

    @Command(command="OUTput1[:LEVeL]?")
    def read_level1(self):
        print(f"{self.level[1]:.1f}%")

    @Command(command="OUTput1:FREQuerncy", parameters=(int,))
    def set_freq1(self,freq):
        if not 7.5<freq<10E6:
            raise ParameterDataOutOfRange
        self.pwm[1].freq(freq)

    @Command(command="OUTput1:FREQuency?")
    def read_freq1(self):
        print(self.pwm[1].freq())


if __name__=="__main__":
    runner=LED()
