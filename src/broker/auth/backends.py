"""
Authn backends (inbound) — v2: oauth (primary), api_key, none.

Each resolves a request to a Principal{id, role}; authority over topics is then derived structurally
(auth/policy.py). HMAC is NOT an inbound backend — it signs OUTBOUND webhook callbacks
(transports/webhook.py). See DESIGN.md §8.

The principal id (e.g. OAuth `sub`) must satisfy core.topics.is_valid_principal_id — not the
wildcard, no delimiters — or the structural authz can be bypassed; reject otherwise.
"""

from __future__ import annotations

from fastapi import Request

from ..core.models import Principal
from .oauth_providers import OAuthRegistry, TokenSource


class OAuthAuthenticator:
    """JWT bearer/CF-Access token → Principal, across enabled providers (DESIGN.md §8).

    Provider-agnostic: extract the token from the locations the enabled providers use, read its
    `iss` (unverified), match it to a ProviderConfig via the registry, then verify the signature
    against that provider's JWKS (keys cached, refetched on `kid` miss) with the provider's
    audience + algorithms. Claims map to Principal via oauth_providers.resolve_principal_id /
    resolve_role; the resulting id is rejected unless core.topics.is_valid_principal_id.

    Supported providers: Supabase Auth, Cloudflare Access, Auth0, Okta, Google.
    """

    def __init__(self, registry: OAuthRegistry) -> None:
        self._registry = registry
        # NOTE(impl): hold a per-jwks_uri key cache (e.g. PyJWKClient) keyed by ProviderConfig.

    def _extract_token(self, request: Request) -> str | None:
        """Pull the raw JWT from the locations the enabled providers use (bearer / CF header)."""
        sources = self._registry.token_sources()
        if TokenSource.CF_ACCESS in sources:
            cf = request.headers.get("Cf-Access-Jwt-Assertion")
            if cf:
                return cf
        if TokenSource.BEARER in sources:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                return auth[len("Bearer "):]
        return None

    async def authenticate(self, request: Request) -> Principal:
        """Extract → match issuer → verify JWKS → map claims → Principal (validated id)."""
        # TODO(impl): _extract_token; jwt.get_unverified_claims -> iss; registry.match(iss);
        #   verify signature/aud/alg via cached JWKS; resolve_principal_id/resolve_role;
        #   reject if not is_valid_principal_id. Raise 401 on any failure.
        raise NotImplementedError


class ApiKeyAuthenticator:
    """Static key → principal map (dev / service-to-service)."""

    def __init__(self, keys: dict[str, Principal]) -> None:
        self._keys = keys

    async def authenticate(self, request: Request) -> Principal:
        raise NotImplementedError


class NoneAuthenticator:
    """Dev backend: unconditionally returns a fixed svc principal. Never use in production."""

    def __init__(self, principal: Principal) -> None:
        self._principal = principal

    async def authenticate(self, request: Request) -> Principal:
        raise NotImplementedError
