"""
Per-topic publish rate limiter (DESIGN.md §5.3).

A simple in-memory token bucket per topic: capacity `C` tokens, refilled at `refill_per_sec`. Each
publish consumes one token; an empty bucket rejects (the transport maps this to HTTP 429). Default
C=10, refill=10/s → a 10-message burst and 10 msg/s sustained per topic.

This is the mitigation the design calls for against open-inbox abuse (`0.<receiver>.*` lets any
user publish to a receiver's inbox — §2.3). Single instance → in-memory state is authoritative.

Memory: one bucket per active topic. The bucket map is LRU-bounded by `max_topics`; an evicted
bucket is simply recreated full on next use, which is safe (a full bucket never wrongly rejects).
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(slots=True)
class _Bucket:
    tokens: float
    last: float  # monotonic timestamp of the last refill


class RateLimiter:
    """In-memory per-topic token bucket. Inject `clock` (monotonic seconds) for testability."""

    def __init__(self, capacity: int = 10, refill_per_sec: float = 10.0,
                 max_topics: int = 10_000, clock: Callable[[], float] = time.monotonic) -> None:
        if capacity < 1 or refill_per_sec <= 0:
            raise ValueError("capacity must be >= 1 and refill_per_sec > 0")
        self._capacity = float(capacity)
        self._refill = refill_per_sec
        self._max_topics = max_topics
        self._clock = clock
        # OrderedDict as an LRU: most-recently-touched topic at the end.
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()

    def allow(self, topic: str) -> bool:
        """Consume one token for `topic`. Return True if permitted, False if the bucket is empty."""
        now = self._clock()
        bucket = self._buckets.get(topic)
        if bucket is None:
            bucket = _Bucket(tokens=self._capacity, last=now)
            self._buckets[topic] = bucket
            self._evict_if_needed()
        else:
            # Refill proportional to elapsed time, capped at capacity, then mark as recently used.
            elapsed = now - bucket.last
            if elapsed > 0:
                bucket.tokens = min(self._capacity, bucket.tokens + elapsed * self._refill)
                bucket.last = now
            self._buckets.move_to_end(topic)

        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True
        return False

    def _evict_if_needed(self) -> None:
        """Drop least-recently-used buckets over the cap (safe — recreated full on next use)."""
        while len(self._buckets) > self._max_topics:
            self._buckets.popitem(last=False)
