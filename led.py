from scpi import TestInstrument, OnOffFloat
from decorators import Command, BuildCommands

from machine import Pin, PWM

from exceptions import ParameterDataOutOfRange

@BuildCommands
class LED(TestInstrument):
    
    def __init__(self):
        self.pwm=PWM(Pin(14))
        self.pwm.freq(10000)
        self.pwm.duty_u16(0)
        self.level=0.0
        super().__init__()
        
    @Command(command="OUTput[:LEVeL]", parameters=(OnOffFloat,))
    def set_level(self,level):
        if not 0<=level<=100:
            raise ParameterDataOutOfRange
        self.level=level
        int_level=int(round(650.25*level))
        self.pwm.duty_u16(int_level)
        
    @Command(command="OUTput[:LEVeL]?")
    def read_level(self):
        print(f"{self.level:.1f}%")
        
    @Command(command="OUTput:FREQuerncy", parameters=(int,))
    def set_freq(self,freq):
        if not 7.5<freq<10E6:
            raise ParameterDataOutOfRange
        self.pwm.freq(freq)
        
    @Command(command="OUTput:FREQuency?")
    def read_freq(self):
        print(self.pwm.freq())
        

if __name__=="__main__":
    runner=LED()
    
        