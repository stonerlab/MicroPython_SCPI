from led import LED
from ad1220 import ADC1220
while True:
    try:
        runner=ADC1220()
        runner.run()
    except KeyboardInterrupt:
        break
    except Exception as e:
        pass