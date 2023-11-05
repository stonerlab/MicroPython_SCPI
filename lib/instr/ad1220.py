# -*- coding: utf-8 -*-
"""
ADS1220 driver based on instr.scpi.TestInstrument
"""
import os
import sys
from machine import SPI, Pin

if int(sys.version.split(".")[3]) >= 20:  # Lightsleep in 1.20+ seems to put the RP2 to sleep forever
    from utime import sleep_ms as lightsleep
else:
    from machine import lightsleep
try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

from .scpi import TestInstrument
from .types import Float, inf, Enum
from .decorators import BuildCommands, Command
from .RGB1602 import Display

RESET = 0b0000_0110
START = 0b0000_1000
PWRDOWN = 0b0000_0010
READ = 0b0001_0000
RREG = 0b0010_0000
WREG = 0b0100_0000


@BuildCommands
class ADC1220(TestInstrument):

    """Implement a SCPI command interface to a TI ADC1220 confgiured for measuring a Hall sensor.

    This class implements the following device specific commands:

    - MEASure[:FieLD]? - read the hall sensor and return the current magnetic field using the stored calibration.
    - MEASure[:FieLD]:RANGe? - Read the current maximum field on the current range.
    - MEASure[:FieLD]:RANGe <float> - Set the range to be able to read <float> magnetic field. The actual range
      set will likely differ and there is an absolute limit due to the fixed gains on the ADC1220's PGA
    - MEASure[:FieLD]:CALibration? - Read the calibration constant (in Volts/magnetic field unit. The instrument
      does not care what units are used for magnetic field since it just reports a bare number.
    - MEASure[:FieLD]:CAK <float> - set the calibration constance in Volts/magnetic field unit. This constant is
      written to a file on the Pico so will persist until it is overwritten.
    - MEASure:VOLTage? - Read the hall sensor's voltage directly.
    - MEASure:HallRESistance? - Read the hall sensor's voltage and divide by the current level to get Rxy.
    - MEASure:RAW? - Read the raw signed integer code from the AD convertor.
    - MEASure:TEMPerature? - Access the ADC1220's temperature sensor
    - SOURce:LEVeL <float> - set the current source that excites the hall sensor. Can be int he range 10uA to 1.5mA
      but with fixed values.
    - SOURce:LEVel? - Read the current source level
    - DISPlay:MODE FieLD|VOLTage|TEMPerature|HallRESistance|RA - what to show on the LCD display
    - DISPLAY:MODE? return the display mode

    To be implemented
    ~~~~~~~~~~~~~~~~~
    - MEASure[:FieLD]:RATE? - report the ADC rate
    - MEASure[:FieLD]:RATE <int> - set the sample rate in S/s
    - *RST - override to re run self.setup()
    - *STB - override the status byte property to use self.ready for MAV bit.
    """

    version = 20230113

    def __init__(self):
        self.spi = SPI(
            0,
            baudrate=10_000_000,
            polarity=0,
            phase=1,
            bits=8,
            firstbit=SPI.MSB,
            sck=Pin(18),
            mosi=Pin(19),
            miso=Pin(16),
        )
        self.cs = Pin(17, Pin.OUT)
        self.cs.value(1)
        self.drdy = Pin(20, Pin.IN)
        self._mux = 0
        self._gain = 1
        self._pga = 1
        self._rate = 20
        self._idac_level = 0
        self._idac_mux = [0, 0]
        self._filter = 0
        self._vref = 0
        self._pswitch = 0
        self._temp = 0
        self._display = Display()
        self._display.open()
        self._display_message = "Ready"
        self._mode = "field"

        if "calibration.txt" not in os.listdir():
            with open("calibration.txt", "w") as calib:
                calib.write("1.000000,0.0000000\n")
        with open("calibration.txt", "r") as calib:
            self._calib = [float(x) for x in calib.readline().strip().split(",")] + [1.0, 0.0]
            self._calib = self._calib[:2]
        self.setup()
        super().__init__()
        self.tasks.append(("_display", asyncio.create_task(self._display_measurement())))

    @property
    def mux(self):
        return self._mux

    @mux.setter
    def mux(self, value):
        if not 0 <= value < 16:
            raise ValueError(f"Mux {value} out of range 0-15")
        self._mux = value
        self.wreg0()

    @property
    def gain(self):
        return self._gain

    @gain.setter
    def gain(self, value):
        if value not in [1, 2, 4, 8, 16, 32, 64, 128]:
            raise ValueError(f"Gain value was not valid: {value}")
        self._gain = value
        self.wreg0()

    @property
    def pga(self):
        return bool(self._pga)

    @pga.setter
    def pga(self, value):
        value = int(bool(value))
        self._pga = value
        self.wreg0()

    @property
    def rate(self):
        return self._rate

    @rate.setter
    def rate(self, value):
        if int(value) not in [20, 45, 90, 175, 330, 600, 1000]:
            raise ValueError(f"Illeagal rate value {value} selected.")
        self._rate = value
        self.wreg1()

    @property
    def temperature(self):
        return bool(self._temp)

    @temperature.setter
    def temperature(self, value):
        self._temp = int(bool(value))
        self.wreg1()

    @property
    def idac_level(self):
        return self._idac_level

    @idac_level.setter
    def idac_level(self, value):
        if value not in [0, 1e-5, 5e-5, 1e-4, 2.5e-4, 5e-4, 1e-3, 1.5e-3]:
            raise ValueError(f"Illeagal current source value {value} requested.")
        self._idac_level = value
        self.wreg23()

    @property
    def pswitch(self):
        return bool(self._pswitch)

    @pswitch.setter
    def pswitch(self, value):
        value = int(bool(value))
        self._pswitch = value
        self.wreg23()

    @property
    def filter_mode(self):
        return self._filter

    @filter_mode.setter
    def filter_mode(self, value):
        if not 0 <= value < 4:
            raise ValueError(f"Illeagal filter value {value} requested.")
        self._filter = value
        self.wreg23()

    @property
    def vref(self):
        return self._vref

    @vref.setter
    def vref(self, value):
        if not 0 <= value < 4:
            raise ValueError(f"Illeagal filter value {value} requested.")
        self._vref = value
        self.wreg23()

    @property
    def idac1_mux(self):
        return self._idac_mux[0]

    @idac1_mux.setter
    def idac1_mux(self, value):
        if not 0 <= value < 8:
            raise ValueError(f"Illeagal IDAC1 mux {value} request.")
        self._idac_mux[0] = value
        self.wreg23()

    @property
    def idac2_mux(self):
        return self._idac_mux[1]

    @idac2_mux.setter
    def idac2_mux(self, value):
        if not 0 <= value < 8:
            raise ValueError(f"Illeagal IDAC2 mux {value} request.")
        self._idac_mux[1] = value
        self.wreg23()

    @property
    def ready(self):
        return self.drdy.value() == 0

    def wreg0(self):
        gain = [1, 2, 4, 8, 16, 32, 64, 128].index(self._gain)
        data = self._pga | gain * 2 | self._mux * 16
        self.write_reg(0, data)

    def wreg1(self):
        rate = [20, 45, 90, 175, 330, 600, 1000].index(int(self.rate))
        data = rate * 32 + 4 + 2 * self._temp
        self.write_reg(1, data)

    def wreg23(self):
        idac_level = [0, 1e-5, 5e-5, 1e-4, 2.5e-4, 5e-4, 1e-3, 1.5e-3].index(self._idac_level)
        data = (
            idac_level
            | self._pswitch * 8
            | self._filter * 16
            | self._vref * 64
            | 256 * (4 * self._idac_mux[1] | 32 * self._idac_mux[0])
        )
        self.write_reg(2, data)

    def read_reg(self, register, nbytes=1):
        """Read a single register.

        Args:
            register (int):
                Register to read

        Keyword Arguments:
            mbytes (int):
                Number of bytes to read.

        Returns:
            (bytes):
                1-3 bytes of data
        """
        if not 0 < nbytes <= 4:
            raise ValueError(f"Illegal number of bytes {nbytes} requested")
        if not 0 <= register < 4:
            raise ValueError(f"Illegal register {register} requested")

        data = RREG | register * 4 | (nbytes - 1)
        self.cs.value(0)
        lightsleep(10)
        self.spi.write(bytes([data]))
        ret = self.spi.read(nbytes)
        ret = int.from_bytes(ret, "little", False)
        self.cs.value(1)
        return ret

    def write_reg(self, register, data):
        """Write a single register.

        Args:
            register (int):
                Register to read
            data (int):
                data to write

        Returns:
            None
        """
        if not 0 <= register < 4:
            raise ValueError(f"Illegal register {register} requested")
        for datalen in range(10):
            if data < 2 ** (datalen * 8):
                break
        data1 = bytes([WREG | register * 4 | (datalen - 1)])

        data2 = data.to_bytes(datalen, "little")

        # rep=f"{{:0{8*datalen+8}b}}"

        self.cs.value(0)
        lightsleep(10)
        self.spi.write(data1 + data2)
        self.cs.value(1)

    def setup(self):
        """Set defaults for Hall measurements."""
        self.send(RESET)
        lightsleep(10)
        self.mux = 3
        self.pga = 1
        self.gain = 1
        self.rate = 20
        self.temperature = False
        self.filter = 2
        self.idac1_mux = 1
        self.idac2_mux = 0
        self.idac_level = 1e-3

    async def _display_measurement(self):
        """Show the current measurement on the display."""
        try:  # Catch KeyBoard Interrupt
            self._display.write("Ready")
            while True:
                await asyncio.sleep(0.5)
                if self._mode == "field":
                    self.read_field(output=None)
                elif self._mode == "volt":
                    self.read_volt(output=None)
                elif self._mode == "temp":
                    self.read_temperature(output=None)
                elif self._mode == "hres":
                    self.read_resistance(output=None)
                elif self._mode == "message":
                    self._display.clear()
                    self._display.write(self._display_message)
                else:
                    self.read_raw(output=None)
        except KeyboardInterrupt:
            self.exit()

    def exit(self):
        self._display.close()
        super().exit()

    def send(self, command, readbytes=0):
        self.cs.value(0)
        lightsleep(10)
        self.spi.write(bytes([command]))
        lightsleep(10)
        if readbytes > 0:
            ret = self.spi.read(readbytes)
            ret = int.from_bytes(ret, "big")
            if ret > 2**23:
                ret -= 2**24
            lightsleep(10)
        else:
            ret = None
        self.cs.value(1)
        return ret

    def read(self):
        if not self.ready:
            self.send(START)
            while not self.ready:
                lightsleep(10)
        ret = self.send(READ, 3)
        return ret

    @Command(command="MEASure:RAW?")
    def read_raw(self, output=True):
        code = self.read()
        self._display.clear()
        self._display.write(f"{code}")
        if output:
            print(code)

    @Command(command="MEASure:VOLTage?")
    def read_volt(self, output=True):
        code = self.read()
        volt = (code / 2**23) * (2.048 / self._gain)
        self._display.clear()
        val, lett = self.format(volt)
        self._display.write(f"{val:.2f}{lett}V")
        if output:
            print(volt)

    @Command(command="MEASure:HallRESistance?")
    def read_resistance(self, output=True):
        code = self.read()
        volt = (code / 2**23) * (2.048 / self._gain)
        self._display.clear()
        val, lett = self.format(volt / self.idac_level)
        self._display.write(f"{val:.2f}{lett}Ohm")
        if output:
            print(volt / self.idac_level)

    @Command(command="MEASure[:FieLD]?")
    def read_field(self, output=True):
        code = self.read()
        volt = (code / 2**23) * (2.048 / self._gain)
        field = (volt - self._calib[1]) / self._calib[0]
        self._display.clear()
        val, lett = self.format(field)
        self._display.write(f"{val:.2f}{lett}T")
        if output:
            print(field)

    @Command(command="MEASure:TEMPerature?")
    def read_temperature(self, output=True):
        self.temperature = True
        lightsleep(20)
        code = self.read()
        code = code >> 10
        if code > 2**13:
            code -= 2**14
        self.temperature = False
        lightsleep(20)
        self._display.clear()
        self._display.write(f"{0.03125*code:.2f}C")
        if output:
            print(0.03125 * code)

    @Command(command="MEASure[:FieLD]:CALibration[:LINear]?")
    def read_calibration(self):
        print(self._calib[0])

    @Command(command="MEASure[:FieLD]:CALibration:OFFset?")
    def read_calibration_offset(self):
        print(self._calib[1])

    @Command(command="MEASure[:FieLD]:CALibration[:LINear]", parameters=(float,))
    def set_calibration(self, value):
        rng = (2.048 - abs(self._calib[1])) / (self.gain * self._calib[0])
        self._calib = value, self._calib[1]
        with open("calibration.txt", "w") as calib:
            calib.write(f"{self._calib[0]},{self._calib[1]}\n")
        self.set_range(rng)

    @Command(command="MEASure[:FieLD]:CALibration:OFFset", parameters=(float,))
    def set_calibration_offset(self, value):
        self._calib = self._valib[0], value
        rng = (2.048 - abs(self._calib[1])) / (self.gain * self._calib[0])
        with open("calibration.txt", "w") as calib:
            calib.write(f"{self._calib[0]},{self._calib[1]}\n")
        self.set_range(rng)

    @Command(command="MEASure[:FieLD]:RANGe?")
    def read_range(self):
        max_f = (2.048 - abs(self._calib[1])) / (self.gain * self._calib[0])
        print(max_f)

    @Command(command="MEASure[:FieLD]:RANGe", parameters=(Float(min=0, max=inf),))
    def set_range(self, value):
        value = abs(value) * self._calib[0] - self.calib[1]
        value = max(2.048 / 128, min(2.048, value))
        for gain in [128, 64, 32, 16, 8, 4, 2, 1]:
            if value <= 2.048 / gain:
                break
        self.gain = gain

    @Command(command="SOURce[:LEVeL]?")
    def read_source_level(self):
        print(self.idac_level)

    @Command(command="SOURce[:LEVeL]", parameters=(Float(default=1e-3, min=1e-5, max=1.5e-3, OFF=0),))
    def set_source_level(self, level):
        for step in [0, 1e-5, 5e-5, 1e-4, 2.5e-4, 5e-4, 1e-3, 1.5e-3]:
            if step >= level:
                break
        self.idac_level = step

    @Command(
        command="DISPlay:MODE",
        parameters=(
            (
                Enum(
                    field="FieLD",
                    volt="VOLTage",
                    temp="TEMPerature",
                    hres="HallRESistance",
                    raw="RAW",
                    message="MESSage",
                )
            ),
        ),
    )
    def set_display_mode(self, mode):
        self._mode = mode

    @Command(command="DISPlay:MODE?")
    def get_display_mode(self):
        mapping = {"field": "FIELD", "volt": "VOLTAAGE", "temp": "TEMPERATURE", "hres": "HALLRESISTANCE"}
        print(mapping.get(self._mode, "NONE"))

    @Command(command="DISPlay:MESSage", parameters=(str,))
    def set_display_message(self, string):
        self._display_message = string

    @Command(command="DISPlay:MESSage?")
    def get_display_message(self):
        print(self._display_message)

    @Command(command="DISPlay:COLour", parameters=(str,))
    def sef_display_colour(self, colour):
        self._display.bgcolour(colour)
