"""Board entry point with an explicit, fail-safe instrument lifecycle."""

from instr.ad1220 import ADC1220


LAST_BOOT_ERROR = None
LAST_SHUTDOWN_ERROR = None


def safe_shutdown(instrument):
    """Put board outputs into their safe state without using SCPI stdout."""
    global LAST_SHUTDOWN_ERROR
    if instrument is None:
        return
    for action in (lambda: setattr(instrument, "idac_level", 0), instrument._display.close):
        try:
            action()
        except Exception as error:
            # Preserve the diagnostic for inspection from the MicroPython REPL.
            # Do not print it into the active SCPI response stream.
            LAST_SHUTDOWN_ERROR = error


def main():
    """Construct and run one transport session; restart policy belongs to the board app."""
    global LAST_BOOT_ERROR
    instrument = None
    try:
        # ADC1220 setup leaves its current source disabled before returning.
        instrument = ADC1220()
        instrument.set_fail_safe(lambda _name, _error: safe_shutdown(instrument))
        instrument.set_disconnect_handler(lambda: safe_shutdown(instrument))
        instrument.run()
    except KeyboardInterrupt:
        safe_shutdown(instrument)
    except Exception as error:
        safe_shutdown(instrument)
        LAST_BOOT_ERROR = error


if __name__ == "__main__":
    main()
