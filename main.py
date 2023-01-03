from led import LED
while True:
    try:
        LED().run()
    except KeyboardInterrupt:
        break
    except Exception as e:
        pass