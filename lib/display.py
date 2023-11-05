"""Driver for a Waveshare 1.28" round display and touch screen."""
from machine import SPI, I2C, Pin, PWM
import time
import framebuf

__version__="0.1.0a1"

def RGB565_to_BRG565(value):
    """Convert RGB565 to BRG565."""
    value=value&65535 # Unset any high bits
    r=(value&0b1111100000000000)>>11
    g=(value&0b0000011111100000)>>5
    b=value&0b0000000000011111
    return g+(b<<6)+(r<<11)

def RGB_to_BRG565(value):
    """Convert 24 bit RGB to 16bit BRG,"""
    r=(value&0xFF0000)>>16
    g=(value&0x00FF00)>>8
    b=value&0x0000FF
    r=(r//8) # approximate integer division 
    g=(g//8)
    b=(b//8)
    return g+(r<<6)+(b<<11)

# Web colours mapped to the correct colour codes
WHITE = RGB_to_BRG565(0xFFFFFF) # #FFFFFF
SILVER = RGB_to_BRG565(0xC0C0C0) # #C0C0C0
GRAY = RGB_to_BRG565(0x808080) # #808080
BLACK = RGB_to_BRG565(0x000000) # #000000
RED = RGB_to_BRG565(0xFF0000) # #FF0000
MAROON = RGB_to_BRG565(0x800000) # #800000
YELLOW = RGB_to_BRG565(0xFFFF00) # #FFFF00
OLIVE = RGB_to_BRG565(0x808000) # #808000
LIME = RGB_to_BRG565(0x00FF00) # #00FF00
GREEN = RGB_to_BRG565(0x008000) # #008000
AQUA = RGB_to_BRG565(0x00FFFF) # #00FFFF
TEAL = RGB_to_BRG565(0x008080) # #008080
BLUE = RGB_to_BRG565(0x0000FF) # #0000FF
NAVY = RGB_to_BRG565(0x000080) # #000080
FUCHSIA = RGB_to_BRG565(0xFF00FF) # #FF00FF
PURPLE = RGB_to_BRG565(0x800080) # #800080

class Display(framebuf.FrameBuffer):
    
    """Dip[lay class adds SPI and I2C capability to a FrameBuffer."""

    def __init__(self,
                 miso=Pin(4, mode=Pin.IN),
                 mosi=Pin(3, mode=Pin.OUT),
                 sck=Pin(2),
                 cs=Pin(1, mode=Pin.OUT, value=1),
                 dc=Pin(0, mode=Pin.OUT, value=0),
                 backlight=PWM(Pin(12), freq=2000, duty_u16=32768),
                 rst=Pin(5, mode=Pin.OUT,value=1),
                 reset=Pin(15, mode=Pin.OUT, value=1),
                 interrupt=Pin(14, Pin.IN, Pin.PULL_UP),
                 scl=Pin(7),
                 sda=Pin(6)
        ):
        """Setup the SPI and I2C interfaces,"""
        self.spi=SPI(0,40_000_000,miso=miso,mosi=mosi,sck=sck, polarity=0, phase=0)
        self.i2c=I2C(1,freq=400_000, scl=scl, sda=sda)
        self.cs=cs
        self.dc=dc
        self.rst=rst
        self.backlight=backlight
        self.reset=reset
        self.interrupt=interrupt
        self.reset()
        self.i2c_address=self.i2c.scan()[0]
        self.init_display()
        self.xdim=self.ydim=240
        self.buffer=bytearray(self.xdim*self.ydim*2) # Buffer for screen display
        self.window=(0,0,self.xdim,self.ydim)
        super().__init__(self.buffer, self.xdim, self.ydim, framebuf.RGB565)
        self.fill(WHITE)
        self.show()


    @property
    def brightness(self):
        """Return backlight as 0-100%"""
        return self.backlight.duty_u16()/655.36

    @brightness.setter
    def brightness(self,value):
        """Set backlight brightness 0-100%"""
        value=min(100,max(value,0))
        self.backlight.duty_u16(int(value*655.36))
        
    @property
    def window(self):
        return self._window
    
    @window.setter
    def window(self,window):
        Xstart,Ystart,Xend,Yend=window
        Xstart=int(min(self.xdim,max(Xstart,0)))
        Ystart=int(min(self.ydim,max(Ystart,0)))
        Xend=int(min(self.xdim,max(Xend,0)))
        Ystart=int(min(self.ydim,max(Ystart,0)))
        Xstart,Xend=min(Xstart,Xend),max(Xstart,Xend)
        Ystart,Yend=min(Ystart,Yend),max(Ystart,Yend)
        self._window=(Xstart,Ystart,Xend,Yend)
        self.spi_write(0x2A,0x00,Xstart,0x00,Xend-1)
        self.spi_write(0x2B,0x00,Ystart,0x00,Yend-1)
        self.spi_write(0x2C)
        
    @property
    def bg(self):
        raise NotImplementedError("bg is write only!")
    
    @bg.setter
    def bg(self,value):
        self.fill(value)
        self.show()

    def reset(self):
        """Toggle the reset bits of both the LCD and TP modules."""
        self.rst(1)
        time.sleep_ms(10)
        self.reset(0)
        self.rst(0)
        time.sleep_ms(10)
        self.reset(1)
        self.rst(1)
        time.sleep_ms(50)
        
    def show(self):
        """Blit the current buffer to the screen."""
        self.window=(0,0,self.xdim,self.ydim)
        self.spi_write_data(self.buffer)
        
    def show_window(self,window=None):
        """Blit just the partial screen."""
        if window is not None: # Sanitize window co-ordinates
            Xstart,Ystart,Xend,Yend=window
            Xstart=int(min(self.xdmin,max(Xstart,0)))
            Ystart=int(min(self.ydmin,max(Ystart,0)))
            Xend=int(min(self.xdmin,max(Xend,0)))
            Ystart=int(min(self.ydmin,max(Ystart,0)))
            Xstart,Xend=min(Xstart,Xend),max(Xstart,Xend)
            Ystart,Yend=min(Ystart,Yend),max(Ystart,Yend)
            _window=self._window
        else: # Already have a window so not need to sanitize
            Xstart,Ystart,Xend,Yend=self._window
            _window=None
        self.window = (Xstart,Ystart,Xend,Yend)      
        #Manually do the sending data    
        self.cs(1)
        self.dc(1)
        self.cs(0)
        for i in range (Ystart,Yend-1):             
            Addr = (Xstart * 2) + (i * 240 * 2)                
            self.spi.write(self.buffer[Addr : Addr+((Xend-Xstart)*2)])
        self.cs(1)
        if _window is not None: # restore previous window
            self.window=_window
        

    def spi_write_cmd(self,cmd):
        """Write an SPI cmd."""
        self.cs(1) #Toggle cable select and set data/command pin
        self.dc(0)
        self.cs(0)
        self.spi_write(bytearray([cmd])) # send trhe data
        self.cs(1)

    def spi_write_data(self,buffer):
        """Write buffer to the SPI bus."""
        self.cs(1) # Toggle the cable select and set data/command bit for data
        self.dc(1)
        self.cs(0)
        if isinstance(buffer, int):
            buffer=[buffer]
        if not isinstance(buffer, bytearray):
            buffer=bytearray(buffer)
        self.spi.write(buffer) # send the data
        self.cs(1)

    def spi_write(self,cmd,*data):
        """Combo write cmd followed by data."""
        if not isinstance(cmd,bytearray):
            cmd=bytearray(cmd)
        self.spi.write(cmd)
        if data:
            self.spi_write_data(data)

    def spi_read_data(self,n_bytes):
        """Read fromt he SPI interface."""
        self.cs(1) # Toggle the cable select and set data/command bit for data
        self.dc(1)
        self.cs(0)
        ret=self.spi.read(n_bytes)
        self.cs(1)
        return [int(x) for x in ret]

    def init_display(self):
        """Initialise the display - magic settings from example driver."""
        self.spi_write(0xEF)
        self.spi_write(0xEB,0x14)

        self.spi_write(0xFE)
        self.spi_write(0xEF)

        self.spi_write(0xEB,0x14)
        self.spi_write(0x84,0x40)
        self.spi_write(0x85,0xFF)
        self.spi_write(0x86,0xFF)
        self.spi_write(0x87,0xFF)
        self.spi_write(0x88,0x0A)
        self.spi_write(0x89,0x21)
        self.spi_write(0x8A,0x00)
        self.spi_write(0x8B,0x80)
        self.spi_write(0x8C,0x01)
        self.spi_write(0x8D,0x01)
        self.spi_write(0x8E,0xFF)
        self.spi_write(0x8F,0xFF)

        self.spi_write(0xB6,0x00,0x20)
        self.spi_write(0x36,0x98)
        self.spi_write(0x3A,0x05)

        self.spi_write(0x90,0x08,0x08,0x08,0x08)
        self.spi_write(0xBD,0x06)
        self.spi_write(0xBC,0x00)
        self.spi_write(0xFF,0x60,0x01,0x04)
        self.spi_write(0xC3,0x13)
        self.spi_write(0xC4,0x13)
        self.spi_write(0xC9,0x22)
        self.spi_write(0xBE,0x11)
        self.spi_write(0xE1,0x10,0x0E)

        self.spi_write(0xDF,0x21,0x0c,0x02)
        self.spi_write(0xF0,0x45,0x09,0x08,0x08,0x26,0x2A)
        self.spi_write(0xF1,0x43,0x70,0x72,0x36,0x37,0x6F)

        self.spi_write(0xF2,0x45,0x09,0x08,0x08,0x26,0x2A)
        self.spi_write(0xF3,0x43,0x70,0x72,0x36,0x37,0x6F)
        self.spi_write(0xED,0x1B,0x0B)
        self.spi_write(0xAE,0x77)
        self.spi_write(0xCD,0x63)

        self.spi_write(0x70,0x07,0x07,0x04,0x0E,0x0F,0x09,0x07,0x08,0x03)
        self.spi_write(0xE8,0x34)
        self.spi_write(0x62,0x18,0x0D,0x71,0xED,0x70,0x70,0x18,0x0F,0x71,0xEF,0x70,0x70)
        self.spi_write(0x63,0x18,0x11,0x71,0xF1,0x70,0x70,0x18,0x13,0x71,0xF3,0x70,0x70)
        self.spi_write(0x64,0x28,0x29,0xF1,0x01,0xF1,0x00,0x07)
        self.spi_write(0x66,0x3C,0x00,0xCD,0x67,0x45,0x45,0x10,0x00,0x00,0x00)
        self.spi_write(0x67,0x00,0x3C,0x00,0x00,0x00,0x01,0x54,0x10,0x32,0x98)
        self.spi_write(0x74,0x10,0x85,0x80,0x00,0x00,0x4E,0x00)

        self.spi_write(0x98,0x3e,0x07)
        self.spi_write(0x35)
        self.spi_write(0x21)
        self.spi_write(0x11)
        self.spi_write(0x29)

    @property
    def identify(self):
        """Read and return display idenitification."""
        self.spi_write(0x4)
        return self.spi_read_data(4)


if __name__=="__main__":
    disp=Display()

