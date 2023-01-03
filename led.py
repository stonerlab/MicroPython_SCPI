from scpi import TestInstrument
from decorators import Command, BuildCommands

from machine import Pin, PWM

@BuildCommands
class LED(TestInstrument):
    
    def __init__(self):
        self.pwm=PWM(Pin(14))
        self.pwm.freq(1000)
        self.pwm.duty_u16(0)
        self.level=0.0
        super().__init__()
        
    @Command(command="OUTput[:LEVeL]", parameters=(float,))
    def set_level(self,level):
        self.level=level
        int_level=int(round(650.25*level))
        self.pwm.duty_u16(int_level)
        
    @Command(command="OUTput[:LEVeL]?")
    def read_level(self):
        print(f"{self.level:.1f}%")
        
    @Command(command="OUTput:FREQuerncy", parameters=(int,))
    def set_freq(self,freq):
        self.pwm.freq(freq)
        
    @Command(command="OUTput:FREQuency?")
    def read_freq(self):
        print(self.pwm.freq())
        

if __name__=="__main__":
    runner=LED()
    
        