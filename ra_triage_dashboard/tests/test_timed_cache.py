from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from ra_triage_dashboard.app.timed_cache import TimedSingleFlightCache


class TimedSingleFlightCacheTest(unittest.TestCase):
    def test_cache_returns_defensive_copies(self) -> None:
        cache = TimedSingleFlightCache[str, dict[str, list[str]]](
            ttl_seconds=30,
            max_entries=2,
        )
        calls = 0

        def loader() -> dict[str, list[str]]:
            nonlocal calls
            calls += 1
            return {"items": ["original"]}

        first = cache.get_or_load("case", loader)
        first["items"].append("mutated")
        second = cache.get_or_load("case", loader)

        self.assertEqual(calls, 1)
        self.assertEqual(second, {"items": ["original"]})

    def test_concurrent_misses_share_one_loader(self) -> None:
        cache = TimedSingleFlightCache[str, dict[str, int]](
            ttl_seconds=30,
            max_entries=2,
        )
        entered = threading.Event()
        release = threading.Event()
        calls = 0
        lock = threading.Lock()

        def loader() -> dict[str, int]:
            nonlocal calls
            with lock:
                calls += 1
            entered.set()
            self.assertTrue(release.wait(timeout=2))
            return {"value": 1}

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(cache.get_or_load, "case", loader) for _ in range(4)]
            self.assertTrue(entered.wait(timeout=2))
            release.set()
            results = [future.result(timeout=2) for future in futures]

        self.assertEqual(calls, 1)
        self.assertEqual(results, [{"value": 1}] * 4)

    def test_invalidate_does_not_restore_an_older_inflight_value(self) -> None:
        """A manual refresh must not inherit a status read that it invalidated."""

        cache = TimedSingleFlightCache[str, dict[str, str]](
            ttl_seconds=30,
            max_entries=2,
        )
        old_started = threading.Event()
        release_old = threading.Event()

        def old_loader() -> dict[str, str]:
            old_started.set()
            self.assertTrue(release_old.wait(timeout=2))
            return {"version": "old"}

        def fresh_loader() -> dict[str, str]:
            return {"version": "fresh"}

        with ThreadPoolExecutor(max_workers=2) as executor:
            old = executor.submit(cache.get_or_load, "case", old_loader)
            self.assertTrue(old_started.wait(timeout=2))
            cache.invalidate("case")
            fresh = executor.submit(cache.get_or_load, "case", fresh_loader)
            release_old.set()
            self.assertEqual(old.result(timeout=2), {"version": "old"})
            self.assertEqual(fresh.result(timeout=2), {"version": "fresh"})

        self.assertEqual(
            cache.get_or_load("case", lambda: {"version": "unexpected"}),
            {"version": "fresh"},
        )


if __name__ == "__main__":
    unittest.main()
