"""Allocation-light transport adapters for SCPI command sessions."""

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio
import sys

from .exceptions import TransportClosed


def _is_awaitable(value):
    return hasattr(value, "__await__") or value.__class__.__name__ in ("coroutine", "generator")


class Transport:
    """Minimal interface implemented by command transports."""

    async def readline(self):
        raise NotImplementedError

    async def write_response(self, text):
        raise NotImplementedError

    async def close(self):
        return None


class _SyncStreamReader:
    def __init__(self, stream):
        self.stream = stream

    async def readline(self):
        to_thread = getattr(asyncio, "to_thread", None)
        if to_thread is not None:
            return await to_thread(self.stream.readline)
        return self.stream.readline()


def new_stdin_reader():
    """Create a reader compatible with MicroPython and desktop CPython."""
    try:
        return asyncio.StreamReader(sys.stdin)
    except (TypeError, ValueError):
        return _SyncStreamReader(sys.stdin)


async def _write(writer, payload):
    result = writer.write(payload)
    if _is_awaitable(result):
        await result
    drain = getattr(writer, "drain", None)
    if drain is not None:
        result = drain()
        if _is_awaitable(result):
            await result


class StreamTransport(Transport):
    """Adapter for async byte or text stream reader/writer pairs."""

    def __init__(self, reader, writer, terminator="\n", binary=False):
        self.reader = reader
        self.writer = writer
        self.terminator = terminator
        self.binary = binary

    async def readline(self):
        return await self.reader.readline()

    async def write_response(self, text):
        payload = str(text).rstrip("\r\n") + self.terminator
        if self.binary:
            payload = payload.encode()
        await _write(self.writer, payload)

    async def close(self):
        close = getattr(self.writer, "close", None)
        if close is not None:
            result = close()
            if _is_awaitable(result):
                await result
        wait_closed = getattr(self.writer, "wait_closed", None)
        if wait_closed is not None:
            result = wait_closed()
            if _is_awaitable(result):
                await result


class StdioTransport(StreamTransport):
    """Default USB-serial/stdin compatibility transport."""

    def __init__(self, reader=None, writer=None, terminator="\n"):
        super().__init__(reader, writer or sys.stdout, terminator, False)

    async def readline(self):
        if self.reader is None:
            self.reader = new_stdin_reader()
        return await self.reader.readline()

    async def close(self):
        # Process-owned stdin/stdout must remain open for REPL inspection or a
        # later explicitly-created session.
        return None


class UARTTransport(Transport):
    """Polling adapter for a MicroPython machine.UART-like object."""

    def __init__(self, uart, poll_interval=0.01, terminator="\n"):
        self.uart = uart
        self.poll_interval = poll_interval
        self.terminator = terminator
        self.closed = False

    async def readline(self):
        while not self.closed:
            data = self.uart.readline()
            if data is not None:
                return data
            await asyncio.sleep(self.poll_interval)
        raise TransportClosed

    async def write_response(self, text):
        if self.closed:
            raise TransportClosed
        self.uart.write((str(text).rstrip("\r\n") + self.terminator).encode())

    async def close(self):
        if self.closed:
            return
        self.closed = True
        deinit = getattr(self.uart, "deinit", None)
        if deinit is not None:
            deinit()


class MemoryTransport(Transport):
    """Deterministic transport for host tests and application simulations."""

    def __init__(self, lines=(), terminator="\n"):
        self.lines = list(lines)
        self.responses = []
        self.terminator = terminator
        self.closed = False

    async def readline(self):
        if self.closed or not self.lines:
            return ""
        return self.lines.pop(0)

    async def write_response(self, text):
        if self.closed:
            raise TransportClosed
        self.responses.append(str(text).rstrip("\r\n") + self.terminator)

    async def close(self):
        self.closed = True
