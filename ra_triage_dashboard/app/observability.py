from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from typing import Generic, Hashable, TypeVar


ObservationT = TypeVar("ObservationT", bound=Hashable)


class BoundedObservationSet(Generic[ObservationT]):
    """Thread-safe, insertion-ordered set with a strict memory bound."""

    def __init__(self, max_entries: int = 1024):
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._items: OrderedDict[ObservationT, None] = OrderedDict()
        self._lock = Lock()

    def add_if_new(self, observation: ObservationT) -> bool:
        """Return True only for a newly observed value.

        Repeated values are moved to the end so the least recently observed
        diagnostic is evicted first.
        """

        with self._lock:
            if observation in self._items:
                self._items.move_to_end(observation)
                return False
            self._items[observation] = None
            while len(self._items) > self._max_entries:
                self._items.popitem(last=False)
            return True

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
