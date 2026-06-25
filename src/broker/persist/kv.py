"""
KV PersistentStore — capability-gated (DESIGN.md §4.3).

Only an ORDERED-SCAN + READ-YOUR-WRITES KV (FoundationDB, etcd, Redis sorted-sets) may serve deep
replay; such an adapter sets `supports_range_replay=True` and stores messages under composite keys
"<topic>|<zero-padded seq>". A plain/eventually-consistent hash-KV (Cloudflare KV, basic Redis) sets
it False → point/recent reads only, and the broker degrades cache misses to a 409 gap.

WHY not the reference backend: eventual consistency breaks high_water_seq (read-your-writes needed)
and the atomic clean-shutdown marker (§6.3), both load-bearing for cursor continuity.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..core.models import Message
from .base import Meta


class KVStore:
    def __init__(self, *, supports_range_replay: bool) -> None:
        # Set True ONLY for an ordered-scan + read-your-writes KV; otherwise replay degrades to 409.
        self.supports_range_replay = supports_range_replay

    async def open(self) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    async def acquire_lease(self) -> bool:
        raise NotImplementedError

    async def append_batch(self, messages: Sequence[Message]) -> None:
        raise NotImplementedError

    async def read_range(self, topic: str, after_seq: int, limit: int) -> Sequence[Message]:
        """Ordered prefix scan over "<topic>|<seq>"; raises if supports_range_replay is False."""
        raise NotImplementedError

    async def high_water_seq(self, topic: str) -> int:
        raise NotImplementedError

    async def load_meta(self) -> Meta | None:
        raise NotImplementedError

    async def save_meta(self, meta: Meta) -> None:
        raise NotImplementedError
