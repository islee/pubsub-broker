"""
Application wiring.

Purpose: build the FastAPI app and run the startup/shutdown sequence that establishes cursor
continuity, then mount the transports/auth selected by config. Exposes /healthz + publish.

Startup sequence (DESIGN.md §§3, 6):
  1. open external store (durable mode) and ACQUIRE THE SINGLE-WRITER LEASE — else refuse to serve.
  2. resolve epoch: durable + clean marker that CROSS-CHECKS against external high-water → adopt
     persisted epoch + seed seq high-water; else mint a NEW epoch (stale cursors safely 409).
  3. open Store(seed_high_water); start Dispatcher, Evictor, SyncWorker, webhook loop.
Shutdown: stop intake → SyncWorker.teardown_sink() (final flush + attested marker) → close.

CRITICAL: run with a SINGLE uvicorn worker. The dispatcher and epoch are in-process; multiple
workers split fan-out and desync the cursor epoch. The lease guards overlapping-deploy 2-writer
windows but does not substitute for single-worker. See render.yaml + CONTRIBUTING.md.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import Config


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Run the startup/shutdown sequence documented in the module header."""
    # TODO(impl): open external + acquire_lease (refuse if not); resolve epoch via clean-marker
    #   cross-check; Store.open(seed_high_water); start Dispatcher/Evictor/SyncWorker/webhook.
    yield
    # TODO(impl): stop intake; SyncWorker.teardown_sink(); stop tasks; Store.close(); release lease.


def create_app(config: Config | None = None) -> FastAPI:
    """Assemble the app: select auth + transports per config, mount routers, add /healthz."""
    raise NotImplementedError


# ASGI entrypoint: `uvicorn broker.app:app --workers 1`
# app = create_app()  # uncomment once create_app is implemented
