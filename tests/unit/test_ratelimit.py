"""Spec 07 § 4: a sliding window per client IP, in memory."""

from __future__ import annotations

from inkthread.core.ratelimit import SlidingWindow


def test_the_window_slides() -> None:
    now = [1000.0]
    w = SlidingWindow(limit=2, window_s=3600, clock=lambda: now[0])
    assert w.hit("a") is None
    now[0] += 10
    assert w.hit("a") is None
    retry = w.hit("a")
    assert retry is not None
    assert 3589 <= retry <= 3590
    assert w.hit("b") is None
    now[0] += 3591
    assert w.hit("a") is None
    assert w.hit("a") is not None


def test_a_refused_hit_is_not_counted() -> None:
    now = [0.0]
    w = SlidingWindow(limit=1, window_s=10, clock=lambda: now[0])
    assert w.hit("a") is None
    for _ in range(5):
        assert w.hit("a") is not None
    now[0] = 10.5
    assert w.hit("a") is None
