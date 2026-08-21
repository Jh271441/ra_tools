"""Small, dependency-free caches for bounded filesystem and remote lookups.

The dashboard has a few read-heavy paths that are expensive only on a cold
cache: resolving a capture manifest, scanning a camera directory, or probing
one Trail view.  A plain dictionary cache avoids repeat work after the first
request, but still allows a burst of concurrent requests to trigger the same
slow lookup.  ``TimedSingleFlightCache`` gives those paths a common, bounded
implementation: one caller loads a key while the others wait for its result.

Values are deep-copied at the boundary.  Callers can safely enrich a returned
payload for presentation without corrupting a later request's cached value.
"""

from __future__ import annotations

import copy
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Generic, Hashable, TypeVar


K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


@dataclass(frozen=True)
class _TimedCacheEntry(Generic[V]):
    value: V
    expires_at: float


class TimedSingleFlightCache(Generic[K, V]):
    """A bounded TTL cache that coalesces concurrent cache misses.

    ``None`` is a valid cached value, which matters for negative media lookups
    while a capture job has not produced a video yet.  Exceptions are never
    cached: all waiters are released and the next request can retry normally.
    """

    def __init__(self, *, ttl_seconds: float, max_entries: int = 1024):
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._ttl_seconds = float(ttl_seconds)
        self._max_entries = int(max_entries)
        self._lock = threading.RLock()
        self._entries: OrderedDict[K, _TimedCacheEntry[V]] = OrderedDict()
        self._inflight: dict[K, threading.Event] = {}
        # ``invalidate`` may race an existing loader (for example a manual
        # Trail refresh while the automatic status read is still in flight).
        # A generation prevents that older loader from repopulating the value
        # the caller explicitly asked us to forget.
        self._generations: dict[K, int] = {}

    def clear(self) -> None:
        """Drop cached values without interrupting an already-running load."""

        with self._lock:
            self._entries.clear()
            self._generations = {
                key: self._generations.get(key, 0) + 1
                for key in self._inflight
            }

    def invalidate(self, key: K) -> None:
        """Forget one value while allowing a concurrent leader to finish."""

        with self._lock:
            self._entries.pop(key, None)
            if key in self._inflight:
                self._generations[key] = self._generations.get(key, 0) + 1
            else:
                # No loader can restore a forgotten value, so retaining a
                # generation marker would only make this bounded cache grow.
                self._generations.pop(key, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def get_or_load(self, key: K, loader: Callable[[], V]) -> V:
        """Return a defensive copy, loading one expired key at most once."""

        while True:
            now = time.monotonic()
            with self._lock:
                entry = self._entries.get(key)
                if entry is not None and entry.expires_at > now:
                    self._entries.move_to_end(key)
                    return copy.deepcopy(entry.value)
                if entry is not None:
                    self._entries.pop(key, None)

                waiter = self._inflight.get(key)
                if waiter is None:
                    waiter = threading.Event()
                    self._inflight[key] = waiter
                    generation = self._generations.get(key, 0)
                    leader = True
                else:
                    leader = False

            if not leader:
                # The loader is deliberately synchronous: callers use this
                # class inside worker threads, never on an async event loop.
                waiter.wait()
                continue

            try:
                value = loader()
            except Exception:
                with self._lock:
                    self._inflight.pop(key, None)
                    waiter.set()
                raise

            with self._lock:
                if self._generations.get(key, 0) == generation:
                    self._entries[key] = _TimedCacheEntry(
                        value=copy.deepcopy(value),
                        expires_at=time.monotonic() + self._ttl_seconds,
                    )
                    self._entries.move_to_end(key)
                    while len(self._entries) > self._max_entries:
                        self._entries.popitem(last=False)
                    self._generations.pop(key, None)
                else:
                    # Any caller released below must become a fresh loader;
                    # the old result is deliberately not reusable.
                    self._generations.pop(key, None)
                self._inflight.pop(key, None)
                waiter.set()
            return copy.deepcopy(value)
