from led import LED
while True:
    try:
        runner=LED()
        runner.run()
    except KeyboardInterrupt:
        break
    except Exception as e:
        pass