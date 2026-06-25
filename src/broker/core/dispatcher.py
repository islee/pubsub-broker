"""
In-memory live dispatcher.

Purpose: fan out freshly-appended messages to live subscribers via bounded per-subscriber queues.
On overflow the slow consumer is dropped and must resume from its cursor via the Store; if the
Store has also evicted those messages the resume yields a CursorGap (DESIGN.md §2.2).

CRITICAL: in-process only → requires a single uvicorn worker. Multiple workers split the fan-out.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from .models import Message


class Dispatcher:
    """topic -> set of bounded subscriber queues."""

    def __init__(self, queue_maxsize: int) -> None:
        self._queue_maxsize = queue_maxsize
        self._subscribers: dict[str, set[asyncio.Queue[Message]]] = {}

    def publish(self, message: Message) -> None:
        """Non-blocking fan-out to all live queues for the topic. Overflow drops the consumer."""
        raise NotImplementedError

    async def subscribe(self, topic: str) -> AsyncIterator[Message]:
        """Register a bounded queue and yield live messages until the consumer disconnects.

        This is the live "tail"; replay-from-cursor is layered on top by the transport before it
        attaches here, so the two streams join without gaps.
        """
        raise NotImplementedError
