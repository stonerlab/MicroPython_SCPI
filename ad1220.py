# -*- coding: utf-8 -*-
"""
AD1220 driver
"""
import math
from machine import SPI, Pin

from scpi import TestInstrument
from decorator import BuildCommands, Command
import uasyncio as asyncio

RESET=0b0000_0110
START=0b0000_1000
PWRDOWN=0b0000_0010
READ=0b0001_0000
RREG=0b0010_0000
WREG=0b0100_0000

@BuildCommands
class ADC1220(TestInstrument):

    """Implement a SCPI command interface to a TI ADC1220 confgiured for measuring a Hall sensor."""

    def __init__(self):
        self.spi=SPI(baudrate=1_000_000,
                     polarity=0,
                     phase=1,
                     bits=1,
                     firstbit=SPI.MSB,
                     sck=Pin(18),
                     mosi=Pin(19),
                     miso=Pin(16))
        self.cs=Pin(17,Pin.OUT)
        self.cs.value(1)
        self.drdy=Pin(20,Pin.IN)
        self._mux=0
        self._gain=1
        self._pga=1
        self._rate=20
        self._idac_level=0
        self._idac_mux=[0,0]
        self._filter=0
        self._vref=0
        self.setup()
        super().__init__()

    @property
    def mux(self):
        return self._mux

    @mux.setter
    def mux(self, value):
        if not 0<=value<16:
            raise ValueError(f"Mux {value} out of range 0-15")
        self._mux=value
        self.wreg0()

    @property
    def gain(self):
        return self._gain

    @gain.setter
    def gain(self, value):
        if not value in [1,2,4,8,16,32,64,128]:
            raise ValueError(f"Gain value was not valid: {value}")
        self._gain=value
        self.wreg0()

    @property
    def pga(self):
        return bool(self._pga)

    @pga.setter
    def pga(self,value):
        value=int(bool(value))
        self._pga=value
        self.wreg0()

    @property
    def rate(self):
        return self._rate

    @rate.setter
    def rate(self,value):
        if int(value) not in [20,45,90,175,330,600,1000]:
            raise ValueError(f"Illeagal rate value {value} selected.")
        rate=[20,45,90,175,330,600,1000].index(int(value))
        data=rate*32+4
        self.write_reg(1, data)
        self._rate=value

    @property
    def idac_level(self):
        return self._idac_level

    @idac_level.setter
    def idac_level(self,value):
        if value not in [0,1E-5,5E-5,1E-4,2.5E-4,5E-4,1E-3,1.5E-3]:
            raise ValueError(f"Illeagal current source value {value} requested.")
        self._idac_level=value
        self.wreg23()

    @property
    def pswitch(self):
        return bool(self._pswitch)

    @pswitch.setter
    def pswitch(self,value):
        value=int(bool(value))
        self._pswitch=value
        self.wreg23()

    @property
    def filter_mode(self):
        return self._filter

    @filter_mode.setter
    def filter_mode(self,value):
        if not 0<=value<4:
            raise ValueError(f"Illeagal filter value {value} requested.")
        self._filter=value
        self.wreg23()

    @property
    def vref(self):
        return self._vref

    @vref.setter
    def vref(self,value):
        if not 0<=value<4:
            raise ValueError(f"Illeagal filter value {value} requested.")
        self._vref=value
        self.wreg23()

    @property
    def idac1_mux(self):
        return self._idac_mux[0]

    @idac1_mux.setter
    def idac1_mux(self,value):
        if not 0<=value<8:
            raise ValueError(f"Illeagal IDAC1 mux {value} request.")
        self._idac_mux[0]=value
        self.wreg23()

    @property
    def idac2_mux(self):
        return self._idac_mux[1]

    @idac2_mux.setter
    def idac2_mux(self,value):
        if not 0<=value<8:
            raise ValueError(f"Illeagal IDAC2 mux {value} request.")
        self._idac_mux[1]=value
        self.wreg23()

    def wreg0(self):
        gain=[1,2,4,8,16,32,64,128].index(self._gain)
        data=self._pga|gain*2|self._mux*16
        self.write_reg(0, data)

    def wreg23(self):
        idac_level=[0,1E-5,5E-5,1E-4,2.5E-4,5E-4,1E-3,1.5E-3].index(self._idac_level)
        data=idac_level|self._pswitch*8|self._filter*16|self._vref*64|256*(4*self._idac_mux[1]|32*self._idac_mux[0])
        self.write_reg(2, data)

    def read_reg(self,register,nbytes=1):
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
        if not 0<nbytes<4:
            raise ValueError(f"Incorrect number of bytes {nbytes} requested")
        if not 0<register<4:
            raise ValueError(f"Incorrect register {register} requested")

        data=RREG|register*4|bytes
        self.cs.value(0)
        await asyncio.sleep_ms(1)
        self.spi.write(bytes[data])
        ret=int.from_butes(self.spi.read(nbytes),"big")
        return ret

    def write_reg(self,register,data):
        """Write a single register.

        Args:
            register (int):
                Register to read
            data (int):
                data to write

        Returns:
            None
            """
        if not 0<register<4:
            raise ValueError(f"Incorrect register {register} requested")

        data1=bytes([RREG|register*4|len(data)])
        for datalen in range(10):
            if data<2**(datalen*8):
                break
        data2=data.to_bytes(datalen,"big")

        self.cs.value(0)
        await asyncio.sleep_ms(1)
        self.spi.write(data1+data2)

    def setup(self):
        """Set defaults for Hall measurements."""
        self.mux=3
        self.pga=1
        self.gain=16
        self.rate=20
        self.filter=2
        self.idac1_mux=1
        self.idac2_mux=0
        self.idac_level=1E-3
