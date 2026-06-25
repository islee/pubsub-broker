"""
Configuration.

Purpose: a single env-driven config object that selects enabled transports, the auth backend, the
persistence backend (none | postgres | kv), the retention budget B and per-topic floor, queue
bounds, and webhook/sync policy. Everything pluggable is chosen here at startup. See `.env.example`
for the full, documented env var contract (DESIGN.md cross-references the design intent).

Two credential-loading conventions (DESIGN.md §8, README "Configuration"):
  - `.env` is loaded if present (real process env always wins), for local development.
  - Any secret `BROKER_X` also accepts `BROKER_X_FILE` pointing at a file whose contents are the
    value — for Docker/Render secret mounts and key-file credentials. Env var wins if both set.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Config:
    # --- storage / retention ---
    db_path: str = "/tmp/broker.db"  # SQLite cache; ephemeral on free tier
    budget_bytes: int = 50 * 1024 * 1024  # cache byte ceiling B (DESIGN.md §5)
    min_retain: int = 16  # MANDATORY per-topic floor (last K), gated by a live subscriber
    low_water_ratio: float = 0.9
    queue_maxsize: int = 256  # bounded live queue per subscriber

    # --- external durable tier (DESIGN.md §§4.3, 6) ---
    persist_backend: str = "none"  # none | postgres | kv
    persist_dsn: str = field(default="", repr=False)  # postgres DSN / kv conn; never logged
    persist_lease_key: int = 0xB30CE  # pg_advisory_lock key (single-writer lease)
    sync_batch_size: int = 256
    sync_breaker_threshold: int = 5

    # --- transports ---
    transports: tuple[str, ...] = ("sse", "longpoll", "webhook")  # ws deferred

    # --- publish rate limit (per-topic token bucket, DESIGN.md §5.3) ---
    ratelimit_capacity: int = 10  # burst: 10 msgs per topic
    ratelimit_refill_per_sec: float = 10.0  # sustained: 10 msg/s per topic
    ratelimit_max_topics: int = 10_000  # LRU bound on tracked buckets

    # --- auth (DESIGN.md §8) ---
    auth_backend: str = "oauth"  # oauth | api_key | none
    # Enabled OAuth providers (all JWKS); a token is matched to one by its `iss` claim.
    oauth_providers: tuple[str, ...] = ()  # subset of: supabase,cloudflare_access,auth0,okta,google
    oauth_svc_scope: str = "broker:svc"  # scope/claim granting svc (Auth0/Okta)
    oauth_svc_principals: tuple[str, ...] = ()  # subject allowlist → svc (CF Access / Google)
    # per-provider settings (only the ones for enabled providers are required)
    supabase_project_ref: str = ""
    cf_access_team_domain: str = ""
    cf_access_aud: str = field(default="", repr=False)
    auth0_domain: str = ""
    auth0_audience: str = ""
    okta_domain: str = ""
    okta_auth_server: str = "default"
    okta_audience: str = ""
    google_client_id: str = field(default="", repr=False)
    api_keys_raw: str = field(default="", repr=False)  # "svc:<key>,user:<key>"; never logged

    # --- webhook ---
    webhook_max_attempts: int = 5
    webhook_breaker_threshold: int = 10
    webhook_hmac_secret: str = field(default="", repr=False)  # signs callbacks; never logged

    @staticmethod
    def from_env() -> Config:
        """Build config from BROKER_* environment variables, falling back to defaults.

        Loads a local `.env` first (real env vars win), and resolves secrets from either the env
        var or a `<NAME>_FILE` path (key-file credentials). See the module docstring.
        """
        load_dotenv()  # no-op if no .env present; never overrides existing process env

        def _int(name: str, default: int) -> int:
            v = os.environ.get(name)
            return int(v) if v else default

        def _float(name: str, default: float) -> float:
            v = os.environ.get(name)
            return float(v) if v else default

        def _csv(name: str) -> tuple[str, ...]:
            raw = os.environ.get(name, "")
            return tuple(x.strip() for x in raw.split(",") if x.strip())

        def _secret(name: str) -> str:
            """Read a secret from `BROKER_X`, else from the file at `BROKER_X_FILE`."""
            direct = os.environ.get(name)
            if direct:
                return direct
            path = os.environ.get(f"{name}_FILE")
            if path:
                return Path(path).read_text(encoding="utf-8").strip()
            return ""

        transports_raw = os.environ.get("BROKER_TRANSPORTS", "sse,longpoll,webhook")
        return Config(
            db_path=os.environ.get("BROKER_DB_PATH", "/tmp/broker.db"),
            budget_bytes=_int("BROKER_BUDGET_BYTES", 50 * 1024 * 1024),
            min_retain=_int("BROKER_MIN_RETAIN", 16),
            queue_maxsize=_int("BROKER_QUEUE_MAXSIZE", 256),
            persist_backend=os.environ.get("BROKER_PERSIST_BACKEND", "none"),
            persist_dsn=_secret("BROKER_PERSIST_DSN"),
            sync_batch_size=_int("BROKER_SYNC_BATCH_SIZE", 256),
            sync_breaker_threshold=_int("BROKER_SYNC_BREAKER_THRESHOLD", 5),
            transports=tuple(t.strip() for t in transports_raw.split(",") if t.strip()),
            ratelimit_capacity=_int("BROKER_RATELIMIT_CAPACITY", 10),
            ratelimit_refill_per_sec=_float("BROKER_RATELIMIT_REFILL_PER_SEC", 10.0),
            ratelimit_max_topics=_int("BROKER_RATELIMIT_MAX_TOPICS", 10_000),
            auth_backend=os.environ.get("BROKER_AUTH_BACKEND", "oauth"),
            oauth_providers=_csv("BROKER_OAUTH_PROVIDERS"),
            oauth_svc_scope=os.environ.get("BROKER_OAUTH_SVC_SCOPE", "broker:svc"),
            oauth_svc_principals=_csv("BROKER_OAUTH_SVC_PRINCIPALS"),
            supabase_project_ref=os.environ.get("BROKER_SUPABASE_PROJECT_REF", ""),
            cf_access_team_domain=os.environ.get("BROKER_CF_ACCESS_TEAM_DOMAIN", ""),
            cf_access_aud=os.environ.get("BROKER_CF_ACCESS_AUD", ""),
            auth0_domain=os.environ.get("BROKER_AUTH0_DOMAIN", ""),
            auth0_audience=os.environ.get("BROKER_AUTH0_AUDIENCE", ""),
            okta_domain=os.environ.get("BROKER_OKTA_DOMAIN", ""),
            okta_auth_server=os.environ.get("BROKER_OKTA_AUTH_SERVER", "default"),
            okta_audience=os.environ.get("BROKER_OKTA_AUDIENCE", ""),
            google_client_id=os.environ.get("BROKER_GOOGLE_CLIENT_ID", ""),
            api_keys_raw=_secret("BROKER_API_KEYS"),
            webhook_max_attempts=_int("BROKER_WEBHOOK_MAX_ATTEMPTS", 5),
            webhook_breaker_threshold=_int("BROKER_WEBHOOK_BREAKER_THRESHOLD", 10),
            webhook_hmac_secret=_secret("BROKER_WEBHOOK_HMAC_SECRET"),
        )
