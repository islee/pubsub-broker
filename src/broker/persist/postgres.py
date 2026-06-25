"""
Postgres PersistentStore — the reference durable backend (DESIGN.md §4.3).

`messages(topic, seq, ...)` table with range queries; `save_meta` in one atomic txn; single-writer
lease via pg_advisory_lock; a background trim enforces external retention (TTL or max-rows/topic) so
the table does not grow forever. Supports range replay.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..core.models import Message
from .base import Meta


class PostgresStore:
    supports_range_replay = True

    def __init__(self, dsn: str, lease_key: int, trim_max_rows: int | None = None) -> None:
        self._dsn = dsn
        self._lease_key = lease_key
        self._trim_max_rows = trim_max_rows

    async def open(self) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    async def acquire_lease(self) -> bool:
        """pg_advisory_lock(lease_key); False if held by another (overlapping deploy)."""
        raise NotImplementedError

    async def append_batch(self, messages: Sequence[Message]) -> None:
        """INSERT ... ON CONFLICT (topic, seq) DO NOTHING — idempotent."""
        raise NotImplementedError

    async def read_range(self, topic: str, after_seq: int, limit: int) -> Sequence[Message]:
        raise NotImplementedError

    async def high_water_seq(self, topic: str) -> int:
        raise NotImplementedError

    async def load_meta(self) -> Meta | None:
        raise NotImplementedError

    async def save_meta(self, meta: Meta) -> None:
        raise NotImplementedError

    async def trim(self) -> int:
        """Enforce external retention (max-rows/topic or TTL). Returns rows trimmed."""
        raise NotImplementedError
