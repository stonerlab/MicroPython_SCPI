# -*- coding: utf-8 -*-
"""Implement a file like interface for a LED1602RGB 2 line display with RGB backlighting."""
import time
from machine import Pin, I2C
from io import IOBase

__all__ = ["Display"]

# Device I2C Arress
LCD_ADDRESS = 0x7C >> 1
RGB_ADDRESS = 0xC0 >> 1

# color define

REG_RED = 0x04
REG_GREEN = 0x03
REG_BLUE = 0x02
REG_MODE1 = 0x00
REG_MODE2 = 0x01
REG_OUTPUT = 0x08
LCD_CLEARDISPLAY = 0x01
LCD_RETURNHOME = 0x02
LCD_ENTRYMODESET = 0x04
LCD_DISPLAYCONTROL = 0x08
LCD_CURSORSHIFT = 0x10
LCD_FUNCTIONSET = 0x20
LCD_SETCGRAMADDR = 0x40
LCD_SETDDRAMADDR = 0x80

# flags for display entry mode
LCD_ENTRYRIGHT = 0x00
LCD_ENTRYLEFT = 0x02
LCD_ENTRYSHIFTINCREMENT = 0x01
LCD_ENTRYSHIFTDECREMENT = 0x00

# flags for display on/off control
LCD_DISPLAYON = 0x04
LCD_DISPLAYOFF = 0x00
LCD_CURSORON = 0x02
LCD_CURSOROFF = 0x00
LCD_BLINKON = 0x01
LCD_BLINKOFF = 0x00

# flags for display/cursor shift
LCD_DISPLAYMOVE = 0x08
LCD_CURSORMOVE = 0x00
LCD_MOVERIGHT = 0x04
LCD_MOVELEFT = 0x00

# flags for function set
LCD_8BITMODE = 0x10
LCD_4BITMODE = 0x00
LCD_2LINE = 0x08
LCD_1LINE = 0x00
LCD_5x8DOTS = 0x00


class Colours(object):
    Black = (0, 0, 0)
    White = (255, 255, 255)
    Red = (255, 0, 0)
    Lime = (0, 255, 0)
    Blue = (0, 0, 255)
    Yellow = (255, 255, 0)
    Cyan = (0, 255, 255)
    Magenta = (255, 0, 255)
    Silver = (192, 192, 192)
    Gray = (128, 128, 128)
    Maroon = (128, 0, 0)
    Olive = (128, 128, 0)
    Green = (0, 128, 0)
    Purple = (128, 0, 128)
    Teal = (0, 128, 128)
    Navy = (0, 0, 128)


class Display(IOBase):

    """Driver for a LCD1602RGB Display module.

    Slightly hacked from the Waveshare demo driver to be a little more pythonic.
    """

    def __init__(self, sda=Pin(0), scl=Pin(1), col=16, row=2):
        """Initialise the driver module.

        Keyword Arguments:
            sda, scl (Machine.Pin):
                The I2C interface pins - defaults to Pin(1) and Pin(2).
            col, row (int):
                THe number of columns and rows in the display, defaults to 16 and 2.

        Notes:
            Unlike the demo driver, this version allows for the I2C pins to be specified per device rather than as
            a module level variable.
        """
        self._i2C = None

        self._row = row
        self._col = col
        self._currline = 0
        self._sda = sda
        self._scl = scl

        self._showfunction = LCD_4BITMODE | LCD_1LINE | LCD_5x8DOTS

    def __enter__(self):
        """Context Manager entry point."""
        self.open()
        return self

    def __exit__(self, type, value, traceback):
        """Context manager exit point."""
        self.close()

    def open(self):
        """Open the I2C comms and initialise the diplay."""
        self._i2C = I2C(0, sda=self._sda, scl=self._scl, freq=400000)
        self.begin()

    def close(self):
        """Implement an I2C close."""
        self.set_rgb(0, 0, 0)
        self.clear()
        self._i2C = None

    @property
    def closed(self):
        return self._i2C is None

    def command(self, cmd):
        """Send the specific command byte to the I2C interface."""
        self._i2C.writeto_mem(LCD_ADDRESS, 0x80, chr(cmd))

    def write_char(self, data):
        """Write data to the LCD display."""
        self._i2C.writeto_mem(LCD_ADDRESS, 0x40, chr(data))

    def set_reg(self, reg, data):
        """Set the specific register to the byte value.

        Args:
            reg (int): Register Address
            data int, chr): Byte to set
        """
        self._i2C.writeto_mem(RGB_ADDRESS, reg, chr(data))

    def set_rgb(self, r, g, b):
        """Set the display background colour.

        Args:
            r,g,b (int,chr): RFed, Green, Blue components (0-255)
        """
        self.set_reg(REG_RED, r)
        self.set_reg(REG_GREEN, g)
        self.set_reg(REG_BLUE, b)

    def set_cursor(self, col, row):
        """Position the cursor.

        Args:
            col,row (int):
                Columns and row cordinates (column 0-15, row 0,1)
        """
        if row == 0:
            col |= 0x80
        else:
            col |= 0xC0
        self._i2C.writeto(LCD_ADDRESS, bytearray([0x80, col]))

    def clear(self):
        """Clar the display."""
        self.command(LCD_CLEARDISPLAY)
        time.sleep(0.002)

    def write(self, data):
        """Display a message.

        Args:
            data (str):
                Data to display
        """
        if not isinstance(data, bytearray):
            data = bytearray(str(data), "utf-8")

        for x in data:
            if x == 10:
                self.set_cursor(0, 1)
            else:
                self.write_char(x)

    def display(self):
        self._showcontrol |= LCD_DISPLAYON
        self.command(LCD_DISPLAYCONTROL | self._showcontrol)

    def begin(self):
        """Start communications wityh the display."""
        cols = self._col
        lines = self._row
        if lines > 1:
            self._showfunction |= LCD_2LINE

        self._currline = 0

        time.sleep(0.05)

        # Send function set command sequence
        self.command(LCD_FUNCTIONSET | self._showfunction)
        # delayMicroseconds(4500);  # wait more than 4.1ms
        time.sleep(0.005)
        # second try
        self.command(LCD_FUNCTIONSET | self._showfunction)
        # delayMicroseconds(150);
        time.sleep(0.005)
        # third go
        self.command(LCD_FUNCTIONSET | self._showfunction)
        # finally, set # lines, font size, etc.
        self.command(LCD_FUNCTIONSET | self._showfunction)
        # turn the display on with no cursor or blinking default
        self._showcontrol = LCD_DISPLAYON | LCD_CURSOROFF | LCD_BLINKOFF
        self.display()
        # clear it off
        self.clear()
        # Initialize to default text direction (for romance languages)
        self._showmode = LCD_ENTRYLEFT | LCD_ENTRYSHIFTDECREMENT
        # set the entry mode
        self.command(LCD_ENTRYMODESET | self._showmode)
        # backlight init
        self.set_reg(REG_MODE1, 0)
        # set LEDs controllable by both PWM and GRPPWM registers
        self.set_reg(REG_OUTPUT, 0xFF)
        # set MODE2 values
        # 0010 0000 -> 0x20  (DMBLNK to 1, ie blinky mode)
        self.set_reg(REG_MODE2, 0x20)
        self.set_white()

    def set_white(self):
        self.set_rgb(255, 255, 255)

    def bgcolour(self, colour):
        if isinstance(colour, tuple):
            self.set_rgb(*colour)
        if isinstance(colour, str) and hasattr(Colours, colour):
            self.set_rgb(*getattr(Colours, colour))
        if isinstance(colour, int):
            r = (colour & 0xFF0000) >> 16
            g = (colour & 0xFF00) >> 8
            b = colour & 0xFF
            self.set_rgb(r, g, b)


if __name__ == "__main__":
    disp = Display()
