"""
Async write-back sync worker (durable mode) — the real durability path (DESIGN.md §6).

Continuously replicates SQLite→external in batches. Best-effort, at-least-once, with a lag window.
On external outage/overflow → circuit breaker + drop-with-metric; NEVER blocks publish. On recovery
(half-open) it replays the gap between external high-water and the SQLite tail so the outage window
isn't lost. At teardown it flushes once and writes the attested clean-shutdown marker.

CRITICAL: dropping replication ≠ dropping the message (still in cache, served live). The only TRUE
loss is "evicted from cache before ever replicated" — that is a loud metric, distinct from "in
cache, not yet durable".
"""

from __future__ import annotations

from ..persist.base import PersistentStore
from .store import Store


class SyncWorker:
    """Batches SQLite appends to the external store with a circuit breaker."""

    def __init__(self, store: Store, external: PersistentStore, epoch: str, *,
                 batch_size: int = 256, breaker_threshold: int = 5) -> None:
        self._store = store
        self._external = external
        self._epoch = epoch
        self._batch_size = batch_size
        self._breaker_threshold = breaker_threshold

    async def run(self) -> None:
        """Background loop: drain the write-back queue → append_batch → advance durable_high_water.
        Trip the breaker after `breaker_threshold` consecutive failures; probe + recovery-replay
        while open. Started as an asyncio task at app startup.
        """
        raise NotImplementedError

    async def teardown_sink(self) -> bool:
        """SIGTERM path (§6.2/§6.3): one final flush; if external high_water == accepted for every
        topic, write {clean_shutdown:true, epoch, final_high_water} atomically and return True.
        Otherwise return False (next boot mints a new epoch). Best-effort; SIGKILL may preempt.
        """
        raise NotImplementedError
