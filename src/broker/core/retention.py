"""
Adaptive retention evictor (DESIGN.md §5).

Keeps the SQLite cache under a global byte budget B while honoring a MANDATORY per-topic floor
(last K messages). Effective retention T ≈ B / (rate × size) above the floor — high traffic shrinks
the window, low traffic grows it.

Two guards layered on the simple budget:
  - seq-order eviction per topic (NOT touch-based LRU): scan-resistant, ordering-aligned (§4.1).
  - the floor is honored ONLY for topics with a live subscriber (§5.2): defuses the namespace DoS
    where a `user` mints throwaway `0.<random>.<random>` topics each claiming the floor.

WHY the floor at all: pure global oldest-first lets a chatty topic evict a quiet topic's lone
message within seconds, starving exactly the low-traffic topic that should retain longest.

In durable mode a message may be evicted only once it is durable (replicated); evicting an
un-replicated message is true data loss (DESIGN.md §6.1).
"""

from __future__ import annotations

from collections.abc import Callable

from .store import Store


class Evictor:
    """Budget-B evictor: seq-order, live-subscriber-gated floor, durability-safe."""

    def __init__(self, store: Store, budget_bytes: int, min_retain: int,
                 has_live_subscriber: Callable[[str], bool],
                 low_water_ratio: float = 0.9, durable_required: bool = False) -> None:
        """`has_live_subscriber(topic)` gates the floor; `durable_required` blocks eviction of
        un-replicated messages in durable mode.
        """
        self._store = store
        self._budget_bytes = budget_bytes
        self._min_retain = min_retain
        self._has_live_subscriber = has_live_subscriber
        self._low_water_ratio = low_water_ratio
        self._durable_required = durable_required

    async def run_once(self) -> int:
        """If over budget, evict oldest (lowest-seq) messages above each topic's effective floor
        down to the low-water mark. Returns total rows deleted. Triggered on write or periodically.
        """
        raise NotImplementedError
