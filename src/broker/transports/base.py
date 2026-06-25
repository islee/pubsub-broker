"""
Transport interface.

Purpose: the pluggable contract every wire protocol implements. All transports share ONE storage
primitive (the per-subscription cursor) but split into two delivery models — do not force push
into pull (DESIGN.md §4):
  - client-driven reads  : SSE, long-poll, (WebSocket, deferred)
  - server-driven loop   : webhook

Selected at startup by config (BROKER_TRANSPORTS).
"""

from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter


class Transport(Protocol):
    """A pluggable transport. Each contributes its routes/loop to the app."""

    name: str

    def router(self) -> APIRouter:
        """Return the FastAPI routes this transport exposes (empty for pure background loops)."""
        ...
