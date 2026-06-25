"""
OAuth provider presets & registry (DESIGN.md §8).

The four supported providers all issue JWTs validated via JWKS (no introspection): Supabase Auth,
Cloudflare Access, Auth0, Okta, Google. This module turns minimal per-provider settings into a
concrete ProviderConfig (issuer, JWKS URI, audiences, algorithms, token location, claim mappings)
and matches an incoming token to its provider by the `iss` claim — so several providers can be
enabled at once. JWKS fetch + signature verification live in auth/backends.py (network/crypto);
everything here is pure and unit-testable.

Role mapping: a subject in the provider's svc allowlist → `svc`; or a configured svc scope/claim
present (Auth0/Okta) → `svc`; otherwise `user`. CF Access / Google have no role claim, so they rely
on the allowlist.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from ..core.models import Role

if TYPE_CHECKING:
    from ..config import Config

# Google's issuer is fixed; tokens may carry either form in `iss`.
GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_ISSUER_BARE = "accounts.google.com"
GOOGLE_JWKS = "https://www.googleapis.com/oauth2/v3/certs"


class OAuthProvider(StrEnum):
    SUPABASE = "supabase"
    CLOUDFLARE_ACCESS = "cloudflare_access"
    AUTH0 = "auth0"
    OKTA = "okta"
    GOOGLE = "google"


class TokenSource(StrEnum):
    BEARER = "bearer"  # Authorization: Bearer <jwt>
    CF_ACCESS = "cf_access_header"  # Cf-Access-Jwt-Assertion: <jwt>


class UnknownIssuer(Exception):
    """Raised when a token's `iss` matches no enabled provider."""


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """A resolved provider: how to locate, verify, and map a token to a Principal."""

    provider: OAuthProvider
    issuer: str
    jwks_uri: str
    audiences: tuple[str, ...]
    token_source: TokenSource
    algorithms: tuple[str, ...] = ("RS256",)
    subject_claim: str = "sub"
    svc_scope: str | None = None  # scope/claim value granting svc (Auth0/Okta)
    svc_principals: frozenset[str] = frozenset()  # allowlist by subject (immutable default is safe)


# --- preset builders: minimal settings → ProviderConfig -------------------------------------------

def supabase(project_ref: str, svc_principals: frozenset[str] = frozenset()) -> ProviderConfig:
    issuer = f"https://{project_ref}.supabase.co/auth/v1"
    return ProviderConfig(
        provider=OAuthProvider.SUPABASE,
        issuer=issuer,
        jwks_uri=f"{issuer}/.well-known/jwks.json",  # asymmetric (RS256/ES256) signing keys
        audiences=("authenticated",),
        token_source=TokenSource.BEARER,
        algorithms=("RS256", "ES256"),
        svc_scope="service_role",  # Supabase `role` claim; allowlist still applies
        svc_principals=svc_principals,
    )


def cloudflare_access(team_domain: str, aud: str,
                      svc_principals: frozenset[str] = frozenset()) -> ProviderConfig:
    issuer = f"https://{team_domain}.cloudflareaccess.com"
    return ProviderConfig(
        provider=OAuthProvider.CLOUDFLARE_ACCESS,
        issuer=issuer,
        jwks_uri=f"{issuer}/cdn-cgi/access/certs",
        audiences=(aud,),  # the Access application AUD tag
        token_source=TokenSource.CF_ACCESS,
        svc_principals=svc_principals,
    )


def auth0(domain: str, audience: str, svc_scope: str | None = None,
          svc_principals: frozenset[str] = frozenset()) -> ProviderConfig:
    issuer = f"https://{domain}/"  # Auth0 issuer carries a trailing slash
    return ProviderConfig(
        provider=OAuthProvider.AUTH0,
        issuer=issuer,
        jwks_uri=f"https://{domain}/.well-known/jwks.json",
        audiences=(audience,),
        token_source=TokenSource.BEARER,
        svc_scope=svc_scope,
        svc_principals=svc_principals,
    )


def okta(domain: str, audience: str, auth_server: str = "default", svc_scope: str | None = None,
         svc_principals: frozenset[str] = frozenset()) -> ProviderConfig:
    base = f"https://{domain}/oauth2/{auth_server}"
    return ProviderConfig(
        provider=OAuthProvider.OKTA,
        issuer=base,
        jwks_uri=f"{base}/v1/keys",
        audiences=(audience,),
        token_source=TokenSource.BEARER,
        svc_scope=svc_scope,
        svc_principals=svc_principals,
    )


def google(client_id: str, svc_principals: frozenset[str] = frozenset()) -> ProviderConfig:
    return ProviderConfig(
        provider=OAuthProvider.GOOGLE,
        issuer=GOOGLE_ISSUER,
        jwks_uri=GOOGLE_JWKS,
        audiences=(client_id,),  # ID token `aud` == OAuth client id
        token_source=TokenSource.BEARER,
        svc_principals=svc_principals,
    )


def build_registry(cfg: Config) -> OAuthRegistry:
    """Build the registry from config: one ProviderConfig per name in cfg.oauth_providers.

    Raises ValueError if an enabled provider is missing its required settings, so a misconfiguration
    fails fast at startup rather than silently rejecting every token.
    """
    svc = frozenset(cfg.oauth_svc_principals)
    providers: list[ProviderConfig] = []
    for name in cfg.oauth_providers:
        provider = OAuthProvider(name)
        if provider is OAuthProvider.SUPABASE:
            _require(cfg.supabase_project_ref, "BROKER_SUPABASE_PROJECT_REF")
            providers.append(supabase(cfg.supabase_project_ref, svc))
        elif provider is OAuthProvider.CLOUDFLARE_ACCESS:
            _require(cfg.cf_access_team_domain, "BROKER_CF_ACCESS_TEAM_DOMAIN")
            _require(cfg.cf_access_aud, "BROKER_CF_ACCESS_AUD")
            providers.append(cloudflare_access(cfg.cf_access_team_domain, cfg.cf_access_aud, svc))
        elif provider is OAuthProvider.AUTH0:
            _require(cfg.auth0_domain, "BROKER_AUTH0_DOMAIN")
            _require(cfg.auth0_audience, "BROKER_AUTH0_AUDIENCE")
            providers.append(auth0(cfg.auth0_domain, cfg.auth0_audience, cfg.oauth_svc_scope, svc))
        elif provider is OAuthProvider.OKTA:
            _require(cfg.okta_domain, "BROKER_OKTA_DOMAIN")
            _require(cfg.okta_audience, "BROKER_OKTA_AUDIENCE")
            providers.append(
                okta(cfg.okta_domain, cfg.okta_audience, cfg.okta_auth_server,
                     cfg.oauth_svc_scope, svc))
        elif provider is OAuthProvider.GOOGLE:
            _require(cfg.google_client_id, "BROKER_GOOGLE_CLIENT_ID")
            providers.append(google(cfg.google_client_id, svc))
    return OAuthRegistry(tuple(providers))


def _require(value: str, env_name: str) -> None:
    if not value:
        raise ValueError(f"OAuth provider enabled but {env_name} is unset")


class OAuthRegistry:
    """The enabled providers, indexed by issuer for `iss`-based matching."""

    def __init__(self, providers: tuple[ProviderConfig, ...]) -> None:
        self._providers = providers
        self._by_issuer = {p.issuer: p for p in providers}

    @property
    def empty(self) -> bool:
        return not self._providers

    def token_sources(self) -> frozenset[TokenSource]:
        """Where to look for a token across all enabled providers."""
        return frozenset(p.token_source for p in self._providers)

    def match(self, iss: str) -> ProviderConfig:
        """Resolve a token's `iss` to its provider config, or raise UnknownIssuer."""
        cfg = self._by_issuer.get(iss)
        if cfg is None and iss == GOOGLE_ISSUER_BARE:
            cfg = self._by_issuer.get(GOOGLE_ISSUER)
        if cfg is None:
            raise UnknownIssuer(iss)
        return cfg


# --- claim → principal/role mapping (pure) --------------------------------------------------------

def resolve_principal_id(claims: dict[str, object], cfg: ProviderConfig) -> str:
    """Extract the principal id from the configured subject claim ('' if absent)."""
    value = claims.get(cfg.subject_claim, "")
    return str(value) if value else ""


def _scopes(claims: dict[str, object]) -> set[str]:
    """Collect scope-like values across common claim shapes (scope str, scp/permissions/roles)."""
    out: set[str] = set()
    scope = claims.get("scope")
    if isinstance(scope, str):
        out.update(scope.split())
    for key in ("scp", "permissions", "roles", "role"):
        val = claims.get(key)
        if isinstance(val, str):
            out.add(val)
        elif isinstance(val, list):
            for item in val:  # pyright: ignore[reportUnknownVariableType]
                out.add(str(item))  # pyright: ignore[reportUnknownArgumentType]
    return out


def resolve_role(claims: dict[str, object], cfg: ProviderConfig) -> Role:
    """svc iff subject is allowlisted OR the configured svc scope/claim is present; else user."""
    pid = resolve_principal_id(claims, cfg)
    if pid and pid in cfg.svc_principals:
        return Role.SVC
    if cfg.svc_scope and cfg.svc_scope in _scopes(claims):
        return Role.SVC
    return Role.USER
