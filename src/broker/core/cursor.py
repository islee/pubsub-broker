"""
Cursor encoding and gap resolution.

Purpose: encode/decode the (epoch, seq) cursor for the wire, and decide when a presented cursor is
stale — which the transports surface as 409 + resync hint. This is the mechanism that makes
post-restart / post-eviction discontinuity explicit, not silent corruption. See DESIGN.md §2.1.
"""

from __future__ import annotations

from enum import StrEnum

from .models import Cursor


class ResyncHint(StrEnum):
    """Where a client should resync to after a stale cursor."""

    EARLIEST = "earliest"
    LATEST = "latest"


class CursorGap(Exception):
    """Raised when a presented cursor can no longer be served (stale epoch or evicted seq).

    Carries the resync hint the transport should return alongside a 409.
    """

    def __init__(self, hint: ResyncHint) -> None:
        super().__init__(f"cursor gap; resync to {hint.value}")
        self.hint = hint


def encode(cursor: Cursor) -> str:
    """Serialize a cursor to its opaque wire token (e.g. "<epoch>:<seq>")."""
    raise NotImplementedError


def decode(token: str) -> Cursor:
    """Parse an opaque wire token back into a Cursor. Raises on malformed input."""
    raise NotImplementedError


def validate(cursor: Cursor, current_epoch: str, earliest_seq: int) -> None:
    """Validate a presented cursor against the live state.

    Raises CursorGap(EARLIEST/LATEST) when the epoch is stale or `seq` predates the earliest
    retained message. Returns None when the cursor is serviceable.
    """
    raise NotImplementedError
