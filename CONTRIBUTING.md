# Contributing

Thanks for your interest in pubsub-broker. This is a deliberately small, single-instance,
dependency-light broker — please keep changes in that spirit. Read [DESIGN.md](DESIGN.md) before
working on the core; it is the source of truth for the architecture and the constraints behind it.

## Development setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                         # install (incl. dev tools)
cp .env.example .env            # configure locally (real env vars still win)
uv run uvicorn broker.app:app --host 0.0.0.0 --port 8000 --workers 1
```

## Quality gates (all must pass)

```bash
uv run ruff check               # lint
uv run pyright                  # type check (strict)
uv run pytest                   # tests
```

CI runs the same three. Add tests for any logic you change; keep the type checker at zero errors.

## Design invariants — do not violate

These are load-bearing; breaking one is a correctness bug, not a style choice (see DESIGN.md):

1. **Single uvicorn worker.** The dispatcher and the per-process epoch are in-memory; multiple
   workers split the fan-out and desync the cursor epoch.
2. **`seq` is assigned inside the SQLite write transaction.** It is the spine of the cursor model.
3. **Never invert write-then-dispatch.** Persist to the SQLite cache before dispatching; the
   external store is written asynchronously by the sync worker, never on the publish hot path.
4. **The per-topic `min_retain` floor is mandatory** (and gated by a live subscriber) — without it a
   chatty topic starves quiet ones, and an unbounded topic namespace becomes a memory DoS.
5. **Durable mode:** acquire the single-writer lease or refuse to serve, and adopt a persisted epoch
   only after the clean-shutdown-marker cross-check; otherwise mint a fresh epoch.
6. **Never evict an un-replicated message in durable mode** — that is true data loss.
7. **Principal ids may never be `0` or contain `.` / `|`** — otherwise the structural topic authz
   can be bypassed.
8. **Webhook delivery runs as a background task**, never inline with publish.

## Conventions

- Comments explain **why**, not what. Prefix non-obvious notes with `NOTE:` / `WHY:` / `CRITICAL:`.
- Keep modules cohesive (`core/`, `transports/`, `auth/`, `persist/`); pluggable seams stay behind
  their interface (`transports/base.py`, `auth/base.py`, `persist/base.py`).
- No new heavyweight runtime dependencies without discussion — "vanilla" is a feature.

## Secrets

Never commit secrets. Only `.env.example` is tracked; all other `.env*` files are ignored. Secrets
may be supplied via a `BROKER_X` env var or a `BROKER_X_FILE` path (key-file credentials).
