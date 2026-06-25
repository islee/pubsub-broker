# pubsub-broker

A lightweight, general-purpose **pub/sub broker** designed to run on a **single Render free-tier
instance**. Pluggable transports, a SQLite replay cache, and retention that adapts to traffic
rather than a fixed count or TTL.

> **Scaffold stage** — interface contracts + the pure logic (topic parsing, authz, rate limiting,
> OAuth provider presets, config) are implemented and tested; the I/O-bound bodies (SQLite, sync,
> transports, JWKS verify) are stubs. See **[DESIGN.md](DESIGN.md)** for the full architecture and
> the constraints that shape it, and **[CONTRIBUTING.md](CONTRIBUTING.md)** for setup + invariants.

## At a glance

- **Topics drive authz:** `<sender>.<receiver>.<thread>`, `0` = wildcard (1:1, 1:n broadcast, n:1
  fan-in). Authority is a pure function of the parsed name — no stored ownership.
- **Two modes:** *ephemeral* (`persist=none`, free tier, SQLite wiped on restart) or *durable*
  (`persist=postgres`, SQLite is a hot cache in front of Postgres; cursors survive clean restarts).
- **Cursor `(epoch, seq)`:** `epoch` makes restart/eviction discontinuity an explicit `409` resync,
  never silent corruption. In durable mode it's adopted only after a cross-checked clean-shutdown
  marker, behind a single-writer lease.
- **Transports (pluggable):** SSE, long-poll, webhook; WebSocket deferred behind the interface.
- **SQLite hot cache:** seq-order eviction (not touch-LRU), budget `B` + a mandatory, live-
  subscriber-gated per-topic floor; misses read through to the external store (or `409`).
- **Auth:** OAuth (JWKS), multi-provider by `iss` — **Supabase Auth, Cloudflare Access, Auth0,
  Okta, Google** (api_key/none for dev). HMAC signs webhook callbacks. Two roles — `svc` (all),
  `user` (structural).
- **Single worker, single instance.** The dispatcher and epoch are in-process by design.

## Quick start

```bash
uv sync
cp .env.example .env                         # configure (real env vars override .env)
uv run uvicorn broker.app:app --workers 1    # ALWAYS one worker
uv run pytest && uv run ruff check && uv run pyright
```

## Configuration

All configuration is environment-driven (`BROKER_*`); **[`.env.example`](.env.example)** is the
documented, authoritative list. Precedence is **process env > `.env` file > defaults**.

Secrets can be supplied two ways: directly as `BROKER_X`, or via `BROKER_X_FILE` pointing at a file
whose contents are the value — for Docker / Render secret mounts and key-file credentials. The env
var wins if both are set. Only `.env.example` is committed; every other `.env*` file is git-ignored.

`render.yaml` is a Blueprint for a single web service (ephemeral mode on free tier; durable mode
needs a paid instance + managed Postgres).

## Layout

| Path | Role |
|------|------|
| `src/broker/core/` | `store` (SQLite cache), `dispatcher`, `cursor`, `topics`, `retention`, `sync`, `models` |
| `src/broker/persist/` | `base` (PersistentStore protocol), `postgres` (reference), `kv` (capability-gated) |
| `src/broker/transports/` | `sse`, `longpoll`, `webhook` (+ `base` interface; WS deferred) |
| `src/broker/auth/` | `backends` (oauth/api_key/none), `oauth_providers` (presets+registry), `policy`, `base` |
| `src/broker/{config,app}.py` | env-driven config + FastAPI wiring (lease, epoch adopt, tasks) |
| `render.yaml` | single web service blueprint (ephemeral on free tier) |

## Gotchas

1. **Never run more than one worker** — splits the in-memory dispatcher and desyncs the epoch.
2. **Ephemeral mode: SQLite is wiped on redeploy/spin-down** (no free-tier disk). Durable mode needs
   a paid instance + managed Postgres; the external DB *is* the durability, not local disk.
3. **Per-topic retention floor is mandatory** (and gated by a live subscriber to block a namespace
   DoS) — not a tuning knob.
4. **Durable mode adopts a persisted epoch only after the clean-marker cross-check, behind a
   single-writer lease** — otherwise it mints a fresh epoch and clients `409`-resync.
5. **Async write-back is the durability path; teardown is best-effort.** The only true data loss is
   a message evicted from cache before it was ever replicated (a loud metric).

## Contributing & license

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and the design invariants. Licensed under the
[MIT License](LICENSE).
