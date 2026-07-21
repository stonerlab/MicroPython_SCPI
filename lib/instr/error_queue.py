"""Small bounded FIFO queue for SCPI errors."""

from .exceptions import QueueOverflow


class ErrorQueue:
    """Allocation-bounded FIFO with an explicit overflow marker."""

    def __init__(self, capacity=16, on_change=None):
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("error queue capacity must be a positive integer")
        self.capacity = capacity
        self._items = []
        self._on_change = on_change

    def __len__(self):
        return len(self._items)

    def _changed(self):
        if self._on_change is not None:
            self._on_change(bool(self._items))

    def append(self, error):
        """Compatibility alias for enqueue()."""
        self.enqueue(error)

    def enqueue(self, error):
        if len(self._items) < self.capacity:
            self._items.append(error)
        elif self._items[-1] is not QueueOverflow:
            # Preserve the oldest errors and reserve the newest slot as the
            # notification that later errors were discarded.
            self._items[-1] = QueueOverflow
        self._changed()

    def popleft(self):
        if not self._items:
            raise IndexError("pop from empty error queue")
        error = self._items.pop(0)
        self._changed()
        return error

    def clear(self):
        self._items = []
        self._changed()
