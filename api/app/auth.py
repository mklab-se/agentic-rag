import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
import jwt

logger = logging.getLogger(__name__)

REQUIRED_SCOPE = "access_as_user"
REQUIRED_ROLE = "Chat.User"


class AuthError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class Claims:
    oid: str
    username: str
    roles: list[str]


class TokenValidator:
    """Validates Entra ID v2 bearer tokens for users with the chat scope and role."""

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        jwks_fetcher: Callable[[], dict] | None = None,
        miss_refetch_interval: float = 300.0,
    ):
        self._issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        self._jwks_url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        self._audiences = [client_id, f"api://{client_id}"]
        self._fetcher = jwks_fetcher or self._fetch_jwks
        self._keys: dict[str, jwt.PyJWK] = {}
        self._lock = asyncio.Lock()
        self._miss_refetch_interval = miss_refetch_interval
        self._last_miss_refresh: float | None = None

    def _fetch_jwks(self) -> dict:
        response = httpx.get(self._jwks_url, timeout=10.0)
        response.raise_for_status()
        return response.json()

    async def _refresh_keys(self) -> None:
        try:
            jwks = await asyncio.to_thread(self._fetcher)
            # Only RSA keys can verify RS256; ignore anything else the endpoint lists.
            rsa_keys = [k for k in jwks.get("keys", []) if k.get("kty") == "RSA"]
            keyset = jwt.PyJWKSet.from_dict({"keys": rsa_keys})
        except Exception as exc:
            logger.warning("Failed to load signing keys: %s", type(exc).__name__)
            raise AuthError(503, "Unable to load signing keys") from exc
        self._keys = {key.key_id: key for key in keyset.keys if key.key_id}

    async def _signing_key(self, kid: str) -> jwt.PyJWK:
        # Cached keys are served without touching the lock, so a slow JWKS fetch
        # never delays tokens signed with a known key.
        key = self._keys.get(kid)
        if key is not None:
            return key
        if self._keys and self._in_cooldown():
            raise AuthError(401, "Unknown signing key")
        async with self._lock:
            key = self._keys.get(kid)
            if key is not None:
                return key
            if self._keys:
                # A miss with keys already loaded: rate limit forged kids.
                if self._in_cooldown():
                    raise AuthError(401, "Unknown signing key")
                self._last_miss_refresh = time.monotonic()
            await self._refresh_keys()
            key = self._keys.get(kid)
        if key is None:
            raise AuthError(401, "Unknown signing key")
        return key

    def _in_cooldown(self) -> bool:
        return (
            self._last_miss_refresh is not None
            and time.monotonic() - self._last_miss_refresh < self._miss_refetch_interval
        )

    @staticmethod
    def _extract_token(header: str | None) -> str:
        if not header:
            raise AuthError(401, "Missing bearer token")
        parts = header.split(" ")
        if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
            raise AuthError(401, "Malformed Authorization header")
        return parts[1]

    async def validate(self, authorization: str | None) -> Claims:
        """Validate an Authorization header value ("Bearer <jwt>") and return its claims."""
        token = self._extract_token(authorization)
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthError(401, "Invalid token") from exc
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise AuthError(401, "Invalid token")

        key = await self._signing_key(kid)
        try:
            payload = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self._audiences,
                issuer=self._issuer,
                options={"require": ["exp", "iss", "aud", "nbf"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError(401, "Invalid token") from exc

        oid = payload.get("oid")
        if not isinstance(oid, str) or not oid:
            raise AuthError(401, "Invalid token")
        scopes = str(payload.get("scp") or "").split()
        if REQUIRED_SCOPE not in scopes:
            raise AuthError(403, "Missing required scope")
        roles = payload.get("roles")
        if not isinstance(roles, list) or REQUIRED_ROLE not in roles:
            raise AuthError(403, "Missing required role")
        return Claims(
            oid=oid,
            username=str(payload.get("preferred_username") or ""),
            roles=[str(r) for r in roles],
        )
