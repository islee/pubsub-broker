"""
SQLite hot cache — the write-then-dispatch tier (DESIGN.md §4).

Every publish writes here first and gets its per-topic `seq` assigned inside the write transaction;
readers replay from a cursor. WAL mode, single writer connection, synchronous=NORMAL.

In ephemeral mode this is the only store (wiped on restart). In durable mode it is a BOUNDED CACHE
in front of a PersistentStore: misses below the cache floor read through to the external store
(read-through is wired in app/transport, not here). Eviction is seq-order per topic (NOT touch-based
LRU) — scan-resistant and ordering-aligned (DESIGN.md §4.1).

CRITICAL: seq is allocated inside the write txn (derive from MAX(seq) per topic). Never invert
write-then-dispatch. The optional `external` is used only to seed seq from durable high-water at
startup in durable mode; it is NOT written on the publish hot path (the SyncWorker does that async).
"""

from __future__ import annotations

from collections.abc import Sequence

from .models import Message, Watermarks


class Store:
    """Async SQLite-backed hot cache."""

    def __init__(self, db_path: str, epoch: str) -> None:
        """`epoch` is the generation stamped onto every appended message (DESIGN.md §3)."""
        self._db_path = db_path
        self._epoch = epoch

    async def open(self, seed_high_water: dict[str, int] | None = None) -> None:
        """Open the connection, set WAL + synchronous=NORMAL, create schema. In durable mode,
        `seed_high_water` (from adopted external meta) initializes per-topic seq so allocation
        continues monotonically across a clean restart (DESIGN.md §6.3).
        """
        raise NotImplementedError

    async def close(self) -> None:
        """Close the writer connection."""
        raise NotImplementedError

    async def append(self, topic: str, payload: bytes, ts: float,
                     headers: dict[str, str] | None = None) -> Message:
        """Allocate seq inside the write txn and append. Returns the stored Message."""
        raise NotImplementedError

    async def read_from(self, topic: str, after_seq: int, limit: int) -> Sequence[Message]:
        """Up to `limit` cached messages with seq > after_seq, ascending. Cache-only; the
        read-through to the external store on a miss is composed above this layer.
        """
        raise NotImplementedError

    async def earliest_seq(self, topic: str) -> int:
        """Smallest CACHED seq for a topic (0 if empty). Drives cursor-gap / read-through paths."""
        raise NotImplementedError

    async def watermarks(self, topic: str) -> Watermarks:
        """Accepted (and, in durable mode, durable) high-water for a topic (DESIGN.md §6.1)."""
        raise NotImplementedError

    async def set_durable_high_water(self, topic: str, seq: int) -> None:
        """Advance the durable watermark after SyncWorker confirms replication (DESIGN.md §6.1)."""
        raise NotImplementedError

    async def db_size_bytes(self) -> int:
        """Current on-disk size; input to the retention evictor's budget check."""
        raise NotImplementedError

    async def evict(self, topic: str, keep_min: int, up_to_seq: int) -> int:
        """Delete cached messages for a topic below the floor, seq-order. Returns rows deleted.

        In durable mode a message must be durable (replicated) before it may be evicted, else it is
        true data loss; the evictor checks this against the durable watermark (see retention.py).
        """
        raise NotImplementedError
