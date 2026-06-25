# pubsub-broker — Design

A lightweight, general-purpose pub/sub broker for a **single Render instance**. Pluggable
transports, **structural topic-based authz**, a **SQLite hot-cache tier** in front of an optional
**external persistent store** (Postgres), adaptive (traffic-driven) retention.

> Status: design v2 (architect-reviewed). Scaffold stage — interface contracts + the pure logic
> (topic parsing, authz policy, config); core/persist/sync bodies are stubs. No deployment yet.

---

## 1. What this is — two modes

The deployment target is **one instance, single uvicorn worker** (the dispatcher and epoch are
in-process). Two persistence modes, chosen by config:

- **Ephemeral mode** (`persist=none`, Render free tier — no disk, 15-min spin-down): SQLite is the
  only store and is wiped on restart. Messages are conceptually ephemeral. This is the v1 system.
- **Durable mode** (`persist=postgres`): SQLite is a **hot cache** in front of Postgres. Messages
  are asynchronously replicated to Postgres; cursors survive **clean** restarts. Needs a paid
  instance (the external DB is the durability, not local disk).

v2's real scope is exactly: *"add optional Postgres-backed durability with cursor survival across
clean restarts,"* without disturbing the ephemeral mode.

Non-goals: horizontal scale, multi-instance fan-out coordination, exactly-once, message ordering
across topics (per-topic order only).

---

## 2. Topic naming & structural authz

### 2.1 Grammar

A topic is exactly three dot-separated fields: **`<a>.<b>.<thread>`**, where `0` is the wildcard.

| Pattern | Shape | Who publishes | Who subscribes |
|---------|-------|---------------|----------------|
| `<sender>.<receiver>.<thread>` | 1:1 | `sender` | `receiver` |
| `<sender>.0.<thread>`          | 1:n | `sender` | anyone (broadcast) |
| `0.<receiver>.<thread>`        | n:1 | anyone (fan-in) | `receiver` |

`<thread>` is an opaque conversation/stream discriminator (a literal `0` thread is just an id, not
a wildcard).

### 2.2 Authz is a pure function (no stored ownership)

Authority is **derivable from the topic name** — there is no `owned_topics` table. Parse the topic
into sender field `S`, receiver field `R`. For role `user`:

- **publish** permitted iff `S == principal.id` **or** `S == "0"`
- **subscribe** permitted iff `R == principal.id` **or** `R == "0"`

`svc` is always permitted. Authz = `f(principal, parsed_topic, action)`, resolved per request off a
parsed topic — cheap, stateless, nothing to keep consistent.

### 2.3 Strict validation & abuse controls (load-bearing, not optional)

The namespace is now attacker-controlled and each topic claims a per-topic retention floor, so the
validator is a real access control, not a formatting nicety:

- **Exact arity 3.** Reject `a.b`, `a.b.c.d`, empty fields (`a..t`, `.b.t`), trailing dots.
- **Charset/length.** Each field: bounded length; **forbid the field delimiter `.` and the persist
  key delimiter `|`** (the Postgres/KV key is derived from the topic — see §4). Pin case-sensitivity
  + Unicode NFC so `Bob` ≠ `bob` can't be used to dodge a grant.
- **Reserve `0`.** No principal may be provisioned with id `0`, contain `.`/`|`, or match the
  reserved token. Enforced at registration and re-checked here.
- **Forbid `0.0.*` for `user`** — that is an open relay (anyone pub + anyone sub). `svc` only.
- **Namespace/budget DoS guard (§5.2):** require `S`/`R` to reference an existing principal, OR cap
  topics-per-principal, AND only honor `min_retain` for topics with ≥1 live subscriber. Without
  this, `user` can mint unlimited `0.<random>.<random>` topics each claiming the floor and exhaust
  budget `B`.
- **Open-inbox abuse:** `0.<receiver>.*` lets any `user` publish to a receiver's inbox by design
  (fan-in). Gate with rate-limiting; this is intentional but unbounded otherwise.

---

## 3. Cursor & continuity — `(epoch, seq)`

Every message gets a **per-topic monotonic `seq`**, assigned inside the write transaction.
Subscribers track a cursor = last-seen `(epoch, seq)`. Client-driven transports reduce to "read
from cursor, then tail."

`epoch` is the **continuity token**. A request whose cursor carries a stale epoch, or a `seq` older
than the earliest available (cache floor *and* external), gets **`409`** with a resync hint
(`earliest`/`latest`). This turns every discontinuity (restart, eviction outrunning a slow consumer,
lost unsynced tail) into an **explicit gap**, never silent corruption or a misleading empty `200`.

### 3.1 Epoch lifecycle by mode

- **Ephemeral mode:** `epoch` = random UUID minted per process start. Any restart → new epoch → all
  cursors `409`-resync. (v1 behavior.)
- **Durable mode:** `epoch` is **persisted in Postgres** and adopted across restarts **only when
  proven safe** (§6.3). Otherwise a fresh epoch is minted (safe discontinuity).

### 3.2 Single-writer lease (durable mode — required)

Render deploys overlap (new instance boots before the old gets SIGTERM), so "single instance" has a
brief 2-writer window. Two writers sharing one Postgres = epoch/seq corruption. On boot the instance
acquires a **`pg_advisory_lock` lease**; **if it can't, it refuses to serve.** Only the lease holder
adopts an epoch or accepts publishes. This makes the continuity scheme sound across deploys.

---

## 4. Storage tiers

### 4.1 SQLite — hot cache (write-then-dispatch, unchanged on the publish path)

`publish → authz → assign seq inside write txn → SQLite append → notify dispatcher → fan out →
enqueue for async write-back`. WAL, single writer connection, `synchronous=NORMAL`. Do **not** invert
write-then-dispatch; group-commit if latency ever matters.

SQLite is a **bounded cache**, not the source of truth in durable mode. Eviction keeps it under
budget `B` (§5).

> **Eviction policy: FIFO / seq-order per topic — NOT touch-based LRU.** You asked for "LRU cache";
> the cache *role* (bounded, miss → external) is exactly that, but the replacement *policy* is
> seq-order. Rationale: a pub/sub log is tail-read; recency already predicts hotness, true LRU adds
> a write-on-every-read and lets one deep historical replay scan evict the live tail (cache
> pollution). Seq-order eviction is simpler, ordering-aligned, and scan-resistant. (Switchable.)

### 4.2 Read path — read-through with gap honesty

- cache hit → serve.
- miss **+ external configured + `supports_range_replay`** → fetch the `seq` range from external
  (ordered by `seq`), **stream to the client without inserting into the hot cache** (or cap
  repopulation) so a deep replay can't evict the live tail. Single-flight concurrent identical
  ranges.
- miss **+ no external (or store lacks range replay)** → `CursorGap`/`409`.
- **External also can't satisfy the range** (fully evicted/trimmed everywhere) → `409`, **never an
  empty `200`** (which a client reads as "caught up"). Distinguish "caught up"
  (`after_seq == high_water`) from "gap" (`after_seq < min_available`) explicitly.

### 4.3 PersistentStore — pluggable (`none` | `postgres` | capability-gated KV)

```
append_batch(messages)            # IDEMPOTENT — upsert by (topic, seq); re-sent after crash
read_range(topic, after_seq, n)   # (after_seq, high_water], ordered by seq, paged
high_water_seq(topic)             # also the cheap health/ready probe for the circuit breaker
load_meta() / save_meta(...)      # epoch, per-topic high_water, clean_shutdown — atomically
supports_range_replay: bool       # capability flag
```

- **`postgres`** — reference backend. `messages(topic, seq, ...)` table; range queries natural;
  `save_meta` is one atomic txn; advisory lock for the lease. **Decide external retention now:** a
  background trim (TTL or max-rows per topic) or it grows forever.
- **KV** — only an **ordered-scan + read-your-writes** KV (FoundationDB, etcd, Redis sorted-sets)
  may set `supports_range_replay=true`. A plain/eventually-consistent hash-KV (Cloudflare KV, basic
  Redis) sets it `false` → point/recent reads only, deep replay degrades to `409`. Eventual
  consistency also breaks `high_water` (read-your-writes required) — hence not the reference.
- **`none`** — ephemeral mode.

`append_batch` idempotency is contractual (write-back is at-least-once and replays after a crash).

---

## 5. Adaptive retention + namespace guard

Retention is a function of traffic/memory, never a static count or TTL.

- **Global byte budget `B`** (~50MB on free tier) is the ceiling; evictor trims to a low-water mark.
- **Per-topic floor** (`min_retain` = last K) is **mandatory** — pure global eviction lets a chatty
  topic evict a quiet topic's lone message within seconds, starving exactly the low-traffic topic
  that should retain longest.
- Effective retention `T ≈ B / (rate × size)` above the floor: high traffic shrinks the window, low
  traffic grows it.

### 5.2 Floor is gated by a live subscriber

To defuse the namespace DoS (§2.3): **honor `min_retain` only for topics with ≥1 live subscriber.**
A flood of throwaway `0.<random>.<random>` topics with no subscriber gets no floor protection and is
evicted freely. Combine with topics-per-principal cap and/or principal-existence checks.

**Cut:** `max_ttl` wall-clock ceiling, per-topic fair-share byte accounting (over-engineered for a
single light instance).

### 5.3 Per-topic publish rate limit

A simple in-memory **token bucket per topic** on the publish path (`core/ratelimit.py`): capacity
`C` tokens refilled at `refill_per_sec`; each publish consumes one; empty → **429**. Default `C=10`,
`refill=10/s` ("10 msg per topic" burst, 10 msg/s sustained). Applies to every publish entry point
(POST publish + any transport-side publish), checked **after** authz, **before** the SQLite write.

This is the §2.3 open-inbox mitigation: it bounds how fast any `user` can flood a `0.<receiver>.*`
fan-in topic. The bucket map is **LRU-bounded** (`max_topics`); an evicted bucket is recreated full
on next use — safe, since a full bucket never wrongly rejects. Single instance → in-memory state is
authoritative (no shared limiter needed).

---

## 6. Sync semantics (durable mode)

### 6.1 Continuous async write-back — the real durability path

Messages are batched and replicated SQLite→Postgres shortly after write. Bounded sync queue. On
external outage/overflow → **circuit breaker + drop-with-metric, never block publish.** This (not
teardown) is what makes durability hold; it is **best-effort, at-least-once, with a lag window.**

- **Expose `durable_high_water` (replicated) vs `high_water` (accepted)** per topic, so a client
  that needs durability can wait for the durable watermark. Without exposing it the guarantee is
  unobservable/untestable.
- **Drop semantics:** dropping *replication* ≠ dropping the *message* — it's still in cache and
  served live. The only **true loss** is "evicted from cache before ever replicated"; that is a
  loud metric/alert, distinct from "in cache, not yet durable."
- **Circuit recovery (half-open):** probe `high_water_seq`; on recovery **replay the gap** between
  external high-water and the current SQLite tail (don't just resume new appends, or messages from
  the outage window are lost though still in cache). Dropped ranges are recorded as durability gaps
  so recovery doesn't think they're covered.

### 6.2 Teardown sink — minimal, best-effort

On SIGTERM: stop intake, attempt **one final flush**, then write the attested marker (§6.3). That's
it — Render SIGKILLs after the grace period, and continuous write-back already keeps the window
small, so elaborate drain choreography is **cut**. Teardown's only load-bearing job is the marker.

### 6.3 Epoch continuity — attested marker + startup cross-check

The danger: a crash loses the unsynced tail; resuming `seq` from external high-water would reassign
`seq` numbers a surviving stale cursor points at → silent corruption. The defense:

1. **Marker is an attestation of completeness, written last.** Teardown drains until
   `external high_water == in-memory high_water` for every topic, **then** writes
   `{clean_shutdown:true, epoch, final_high_water}` as the **last** write, in **one atomic txn**.
2. **Startup adopts only after cross-check.** Marker present **AND** `final_high_water ==
   external high_water_seq` per topic → adopt epoch + high-water (cursors survive). Any mismatch
   (marker stale, a write landed after it, drain incomplete) or **no marker** → **mint a new epoch**
   (stale cursors `409`). The marker says "I believe I'm consistent"; the cross-check proves it.
3. Marker cleared immediately on adopt; only ever written at shutdown → a crash always lacks it.

This converts "trust a best-effort write" into "trust + verify," closing the corruption hole. The
single-writer lease (§3.2) guarantees only one instance ever adopts/issues.

---

## 7. Transports — one storage primitive, two delivery models

Unchanged from v1. Storage (per-subscription cursor) is unified; delivery splits into client-driven
reads (SSE, long-poll) and a server-driven loop (webhook). WebSocket deferred behind the interface.

| Transport | Model | v1/v2 |
|-----------|-------|-------|
| SSE | client read | ✅ |
| Long-poll | client read | ✅ |
| Webhook | server-driven loop | ✅ |
| WebSocket | client read | ⏳ deferred |

**Webhook:** background task (never inline with publish), capped exponential backoff + jitter,
`seq` header for subscriber-side idempotency, no DLQ (drop-with-metric), **per-subscription circuit
breaker** (suspend after N consecutive failures). Callbacks are **HMAC-signed** (§8).

---

## 8. Auth

Split authn (who) from authz (§2.2). Both pluggable; auth backend selected by config.

- **Authn backends (inbound):**
  - **`oauth`** (primary) — **JWKS-only, provider-preset-driven** (`auth/oauth_providers.py`).
    Minimal per-provider settings expand into a `ProviderConfig` (issuer, JWKS URI, audiences,
    algorithms, token location, claim mappings); incoming tokens are matched to a provider by their
    **`iss` claim**, so **several providers can be enabled at once**. The broker reads `iss`
    unverified, matches the registry, then verifies the signature against that provider's JWKS
    (keys cached, refetched on `kid` miss — cold-start refetch accepted) with the provider's
    audience + algorithms. **No token introspection** — all supported providers issue JWTs.

    | Provider | Token location | Issuer / JWKS | svc-role source |
    |----------|----------------|---------------|-----------------|
    | **Supabase Auth** | `Authorization: Bearer` | `https://<ref>.supabase.co/auth/v1` · `/.well-known/jwks.json` | allowlist or `role=service_role` |
    | **Cloudflare Access** | `Cf-Access-Jwt-Assertion` | `https://<team>.cloudflareaccess.com` · `/cdn-cgi/access/certs` (aud = app AUD tag) | allowlist (no role claim) |
    | **Auth0** | `Authorization: Bearer` | `https://<domain>/` · `/.well-known/jwks.json` | scope/permissions claim |
    | **Okta** | `Authorization: Bearer` | `https://<domain>/oauth2/<server>` · `/v1/keys` | scope (`scp`) claim |
    | **Google** | `Authorization: Bearer` (ID token) | `accounts.google.com` · `oauth2/v3/certs` (aud = client id) | allowlist (no role claim) |

    `principal.id` = subject claim (`sub`); **role** = `svc` iff the subject is in the provider's
    **svc allowlist** OR the configured **svc scope** is present (Auth0/Okta), else `user`. The id
    must satisfy the principal-id rules (§2.3) — reject subs containing `.`/`|`/`0`. Misconfigured
    enabled providers fail fast at startup (missing required setting → `ValueError`).
  - **`api_key`** — static key→principal map (dev / service-to-service).
  - **`none`** — dev only; fixed `svc` principal.
- **Authz:** the two-role structural policy of §2.2.
- **HMAC** is **not** an inbound backend — it signs **outbound webhook callbacks** (§7) so
  subscribers can verify origin. Always available regardless of inbound backend.

---

## 9. Module layout

```
src/broker/
  app.py            FastAPI wiring; lease acquire, epoch adopt/cross-check, start sync + webhook tasks
  config.py         env-driven config; persist backend, oauth providers, budget B, floor, transports
  core/
    models.py       Message, Topic(parse/validate), Subscription, Principal, Cursor
    topics.py       topic grammar: parse, validate, wildcard rules (§2)
    cursor.py       (epoch, seq) encode/decode + 409/gap resolution
    store.py        SQLite hot cache; write-then-dispatch append; read-through; watermarks
    dispatcher.py   in-memory topic -> bounded queues; live fan-out + backpressure
    retention.py    budget-B evictor, seq-order, live-subscriber-gated floor (§5)
    ratelimit.py    per-topic token-bucket publish limiter (§5.3)
    sync.py         async write-back worker, circuit breaker, recovery-replay, teardown marker (§6)
  persist/
    base.py         PersistentStore protocol + supports_range_replay capability (§4.3)
    postgres.py     reference backend: messages table, atomic meta, advisory-lock lease, trim
    kv.py           capability-gated KV adapter (range replay only if ordered-scan + RYW)
    # none -> store used directly, no external
  transports/
    base.py         Transport interface
    sse.py / longpoll.py / webhook.py   [v1]   (websocket.py deferred)
  auth/
    base.py            Authenticator + Principal protocol
    backends.py        oauth / api_key / none  (hmac = webhook signing, in transports/webhook.py)
    oauth_providers.py provider presets + registry (iss-match) + claim→role mapping (§8)
    policy.py          structural svc/user authz over parsed topics (§2.2)
```

---

## 10. Render consequences (explicit)

- **Free tier (ephemeral mode):** no disk → SQLite wiped on redeploy/spin-down; per-process epoch +
  `409` resync. Single worker, single instance.
- **Durable mode:** needs a paid instance + managed Postgres. Overlapping deploys handled by the
  single-writer lease; cross-restart cursor survival only on clean shutdown (else safe resync).
- **512MB RAM:** bounded queues + byte-budget `B` keep memory flat regardless of traffic.

---

## 11. Open items for implementation phase

- Exact `409`/gap wire format and resync handshake per transport; "caught up" vs "gap" signaling.
- OAuth: JWKS cache/rotation policy; introspection caching TTL; `sub`→principal-id mapping/rejection.
- Topic validator: field length caps, charset, NFC normalization; topics-per-principal cap value.
- Postgres schema + external retention/trim policy; advisory-lock key; `save_meta` txn shape.
- Sync: batch size/interval, queue bound, breaker thresholds, recovery-replay paging, durability-gap
  bookkeeping.
- Config schema + defaults for all of the above; `B`, low-water, `min_retain` K, queue bounds.
