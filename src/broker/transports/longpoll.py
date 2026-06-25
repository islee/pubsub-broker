"""
Long-poll transport (client-driven read) — v1.

Purpose: GET .../poll?cursor=<token>&timeout=<s> returns messages after the cursor, blocking until
at least one arrives or the timeout elapses (then 204/empty). For dumb clients with no persistent
connection. Stale cursor → 409 + resync hint (DESIGN.md §§2.1, 4).
"""

from __future__ import annotations

from fastapi import APIRouter

from ..core.dispatcher import Dispatcher
from ..core.store import Store


class LongPollTransport:
    name = "longpoll"

    def __init__(self, store: Store, dispatcher: Dispatcher) -> None:
        self._store = store
        self._dispatcher = dispatcher

    def router(self) -> APIRouter:
        """Routes: GET /topics/{topic}/poll (block until >=1 msg after cursor or timeout)."""
        raise NotImplementedError
