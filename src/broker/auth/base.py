"""
Authn interface.

Purpose: the pluggable contract that resolves an inbound request to a Principal. Backends are
selected by config (BROKER_AUTH_BACKEND). Authn (who are you) is kept separate from authz
(what may you do — see policy.py). See DESIGN.md §5.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import Request

from ..core.models import Principal


class Authenticator(Protocol):
    """Resolve a request to a Principal, or raise to reject (401)."""

    async def authenticate(self, request: Request) -> Principal:
        """Return the authenticated Principal (id, role, owned_topics) or raise on failure."""
        ...
