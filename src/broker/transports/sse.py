"""
SSE transport (client-driven read) — v1.

Purpose: GET .../stream?cursor=<token> opens a text/event-stream. The transport replays from the
cursor via the Store, then attaches to the Dispatcher's live tail — the two join without gaps.
A stale cursor surfaces as 409 + resync hint (DESIGN.md §§2.1, 4).
"""

from __future__ import annotations

from fastapi import APIRouter

from ..core.dispatcher import Dispatcher
from ..core.store import Store


class SSETransport:
    name = "sse"

    def __init__(self, store: Store, dispatcher: Dispatcher) -> None:
        self._store = store
        self._dispatcher = dispatcher

    def router(self) -> APIRouter:
        """Routes: GET /topics/{topic}/stream (replay-from-cursor then live tail)."""
        raise NotImplementedError
