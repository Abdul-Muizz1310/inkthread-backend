"""An in-memory sliding-window rate limiter (spec 07 § 4: one instance, so memory is enough)."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable


class SlidingWindow:
    """At most `limit` hits per key within any `window_s` seconds. Refused hits are not counted."""

    def __init__(
        self, *, limit: int, window_s: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if limit < 1 or window_s <= 0:
            msg = "a rate limit needs limit >= 1 and a positive window"
            raise ValueError(msg)
        self._limit = limit
        self._window = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> int | None:
        """Record a hit and return None, or refuse it and return the seconds until one is free."""
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self._window:
                hits.popleft()
            if len(hits) >= self._limit:
                return max(1, math.ceil(hits[0] + self._window - now))
            hits.append(now)
            self._prune(now)
            return None

    def _prune(self, now: float) -> None:
        """Drop keys whose every hit has left the window, so memory stays bounded."""
        if len(self._hits) < 1024:
            return
        stale = [k for k, v in self._hits.items() if not v or v[-1] <= now - self._window]
        for k in stale:
            del self._hits[k]
