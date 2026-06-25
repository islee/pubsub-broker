"""
PersistentStore protocol — the external durable tier behind the SQLite cache.

Selected by config (none | postgres | kv). The SQLite cache reads through to this on a miss and the
sync worker replicates to it asynchronously. See DESIGN.md §§4.3, 6.

CONTRACT:
  - append_batch is IDEMPOTENT (upsert by (topic, seq)) — write-back is at-least-once and re-sends
    the same batch after a crash.
  - read_range returns (after_seq, high_water] ordered by seq, paged by `limit`.
  - supports_range_replay gates deep replay: a store without ordered scan + read-your-writes sets
    it False, and the broker degrades cache misses to a 409 gap rather than serving incomplete data.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from ..core.models import Message


@dataclass(frozen=True, slots=True)
class Meta:
    """Continuity metadata persisted atomically (DESIGN.md §6.3)."""

    epoch: str
    high_water: dict[str, int]  # per-topic accepted high-water at clean shutdown
    clean_shutdown: bool


class PersistentStore(Protocol):
    """External durable store. All methods are async; implementations own their own connection."""

    supports_range_replay: bool

    async def open(self) -> None: ...

    async def close(self) -> None: ...

    async def acquire_lease(self) -> bool:
        """Acquire single-writer lease (e.g. pg_advisory_lock); False → caller refuses (§3.2)."""
        ...

    async def append_batch(self, messages: Sequence[Message]) -> None:
        """Idempotent upsert by (topic, seq). Safe to re-send after a crash."""
        ...

    async def read_range(self, topic: str, after_seq: int, limit: int) -> Sequence[Message]:
        """(after_seq, high_water] ordered by seq. Only meaningful when supports_range_replay."""
        ...

    async def high_water_seq(self, topic: str) -> int:
        """Highest durable seq for a topic (0 if none). Doubles as the breaker health probe."""
        ...

    async def load_meta(self) -> Meta | None:
        """Read continuity metadata, or None if absent (first boot)."""
        ...

    async def save_meta(self, meta: Meta) -> None:
        """Persist continuity metadata atomically (single txn). Written last at teardown."""
        ...
