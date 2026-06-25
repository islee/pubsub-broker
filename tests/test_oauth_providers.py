"""OAuth provider presets, issuer matching, and claim→role mapping (DESIGN.md §8)."""

from __future__ import annotations

import pytest

from broker.auth.oauth_providers import (
    GOOGLE_ISSUER,
    OAuthProvider,
    TokenSource,
    UnknownIssuer,
    auth0,
    build_registry,
    cloudflare_access,
    google,
    okta,
    resolve_role,
    supabase,
)
from broker.config import Config
from broker.core.models import Role


# --- presets: issuer + JWKS URI shapes ---
def test_supabase_preset() -> None:
    p = supabase("abcxyz")
    assert p.issuer == "https://abcxyz.supabase.co/auth/v1"
    assert p.jwks_uri == "https://abcxyz.supabase.co/auth/v1/.well-known/jwks.json"
    assert p.token_source is TokenSource.BEARER


def test_cf_access_uses_cf_header() -> None:
    p = cloudflare_access("myteam", aud="tag123")
    assert p.issuer == "https://myteam.cloudflareaccess.com"
    assert p.jwks_uri == "https://myteam.cloudflareaccess.com/cdn-cgi/access/certs"
    assert p.audiences == ("tag123",)
    assert p.token_source is TokenSource.CF_ACCESS


def test_auth0_issuer_has_trailing_slash() -> None:
    p = auth0("acme.us.auth0.com", audience="https://api.broker")
    assert p.issuer == "https://acme.us.auth0.com/"
    assert p.jwks_uri == "https://acme.us.auth0.com/.well-known/jwks.json"


def test_okta_default_auth_server() -> None:
    p = okta("dev-1.okta.com", audience="api://broker")
    assert p.issuer == "https://dev-1.okta.com/oauth2/default"
    assert p.jwks_uri == "https://dev-1.okta.com/oauth2/default/v1/keys"


def test_google_fixed_issuer() -> None:
    p = google("client-123.apps.googleusercontent.com")
    assert p.issuer == GOOGLE_ISSUER
    assert p.audiences == ("client-123.apps.googleusercontent.com",)


# --- registry: build + iss matching ---
def test_build_registry_multi_provider() -> None:
    cfg = Config(
        oauth_providers=("supabase", "google"),
        supabase_project_ref="abcxyz",
        google_client_id="cid",
    )
    reg = build_registry(cfg)
    assert reg.match("https://abcxyz.supabase.co/auth/v1").provider is OAuthProvider.SUPABASE
    # Google tokens may carry the bare issuer form.
    assert reg.match("accounts.google.com").provider is OAuthProvider.GOOGLE
    with pytest.raises(UnknownIssuer):
        reg.match("https://evil.example.com/")


def test_build_registry_missing_setting_fails_fast() -> None:
    with pytest.raises(ValueError):
        build_registry(Config(oauth_providers=("auth0",)))  # no domain/audience


# --- claim → role ---
def test_role_svc_via_allowlist() -> None:
    p = google("cid", svc_principals=frozenset({"svc-account-sub"}))
    assert resolve_role({"sub": "svc-account-sub"}, p) is Role.SVC
    assert resolve_role({"sub": "someone-else"}, p) is Role.USER


def test_role_svc_via_scope() -> None:
    p = auth0("acme.us.auth0.com", audience="api", svc_scope="broker:svc")
    assert resolve_role({"sub": "u", "scope": "openid broker:svc"}, p) is Role.SVC
    assert resolve_role({"sub": "u", "scp": ["broker:svc"]}, p) is Role.SVC
    assert resolve_role({"sub": "u", "scope": "openid"}, p) is Role.USER
