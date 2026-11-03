import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

import httpx
import jwt

logger = logging.getLogger(__name__)


class AuthError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class Claims:
    oid: str
    app_id: str
    roles: list[str]


class TokenValidator:
    """Validates Entra ID v2 bearer tokens for callers holding a required app role."""

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        required_role: str,
        jwks_fetcher: Callable[[], dict] | None = None,
    ):
        self._client_id = client_id
        self._required_role = required_role
        self._issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        self._jwks_url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        self._audiences = [client_id, f"api://{client_id}"]
        self._fetcher = jwks_fetcher or self._fetch_jwks
        self._keys: dict[str, jwt.PyJWK] = {}
        self._lock = asyncio.Lock()

    def _fetch_jwks(self) -> dict:
        response = httpx.get(self._jwks_url, timeout=10.0)
        response.raise_for_status()
        return response.json()

    async def _refresh_keys(self) -> None:
        try:
            jwks = await asyncio.to_thread(self._fetcher)
            keyset = jwt.PyJWKSet.from_dict(jwks)
        except Exception as exc:
            logger.warning("Failed to load signing keys: %s", type(exc).__name__)
            raise AuthError(503, "Unable to load signing keys") from exc
        self._keys = {key.key_id: key for key in keyset.keys if key.key_id}

    async def _signing_key(self, kid: str) -> jwt.PyJWK:
        async with self._lock:
            if not self._keys:
                await self._refresh_keys()
            if kid not in self._keys:
                await self._refresh_keys()
            key = self._keys.get(kid)
        if key is None:
            raise AuthError(401, "Unknown signing key")
        return key

    @staticmethod
    def _extract_token(bearer: str | None) -> str:
        if not bearer:
            raise AuthError(401, "Missing bearer token")
        parts = bearer.split(" ")
        if len(parts) == 1:
            # A bare token, as passed by callers that already stripped the scheme.
            return parts[0]
        if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
            raise AuthError(401, "Malformed Authorization header")
        return parts[1]

    async def validate(self, bearer: str) -> Claims:
        """Validate "Bearer <jwt>" (or a bare jwt) and return its claims."""
        token = self._extract_token(bearer)
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
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError(401, "Invalid token") from exc

        roles = payload.get("roles")
        if not isinstance(roles, list) or self._required_role not in roles:
            raise AuthError(403, "Missing required role")
        oid = payload.get("oid")
        if not isinstance(oid, str) or not oid:
            raise AuthError(401, "Invalid token")
        app_id = payload.get("azp") or payload.get("appid") or ""
        return Claims(oid=oid, app_id=str(app_id), roles=[str(r) for r in roles])
