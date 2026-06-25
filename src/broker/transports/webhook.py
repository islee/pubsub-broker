"""
Webhook transport (server-driven consumer loop) — v1.

Purpose: the broker POSTs messages to subscriber-registered callback URLs. Unlike the read
transports, the cursor here is server-owned DELIVERY state (DESIGN.md §4.1). Runs as a background
task, never inline with publish.

Reliability (the load-bearing part):
  - capped exponential backoff + jitter (~5 attempts)
  - `seq` (+ message id) sent as a header → subscriber-side idempotency
  - NO dead-letter queue: after max attempts, advance past the poison message and drop-with-metric
  - per-subscription circuit breaker: after N consecutive failures, suspend and expose status —
    this is what protects the single worker from a dead endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..core.models import Subscription
from ..core.store import Store


class WebhookTransport:
    name = "webhook"

    def __init__(self, store: Store, max_attempts: int, breaker_threshold: int,
                 hmac_secret: str = "") -> None:
        self._store = store
        self._max_attempts = max_attempts
        self._breaker_threshold = breaker_threshold
        # HMAC-signs each outbound POST so subscribers can verify origin (DESIGN.md §8).
        self._hmac_secret = hmac_secret

    def router(self) -> APIRouter:
        """Routes: POST/DELETE subscriptions, GET .../subscriptions/{id} for status."""
        raise NotImplementedError

    async def run(self) -> None:
        """Background delivery loop: read per-subscription cursor, POST with backoff, advance or
        trip the circuit breaker. Started as an asyncio task at app startup.
        """
        raise NotImplementedError

    async def _deliver(self, sub: Subscription) -> bool:
        """Attempt one delivery cycle for a subscription. Returns True on 2xx ack."""
        raise NotImplementedError
