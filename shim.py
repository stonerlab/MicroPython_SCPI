"""Shim classes for testing when hardware is present."""
__all__=["Pin","PWM"]

class Pin(object):

    def __init__(self,*args,**kargs):
        pass

class PWM(object):
    def __init__(self,*args,**kargs):
        pass

    def freq(self,*args):
        if len(args)==0: return 1000.0

    def duty_u16(self,*args):
        if len(args)==0: return 32767
