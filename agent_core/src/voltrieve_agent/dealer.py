"""Client for the dealer service. Every method returns text the model can read."""

import uuid
from collections.abc import Awaitable, Callable

import httpx

from voltrieve_agent.tools import current_correlation_id


class DealerClient:
    def __init__(
        self,
        base_url: str,
        token_provider: Callable[[], Awaitable[str]],
        http: httpx.AsyncClient,
    ):
        self._base_url = base_url.rstrip("/")
        self._token_provider = token_provider
        self._http = http

    async def stock(self, model: str | None = None, city: str | None = None) -> str:
        params = {k: v for k, v in {"model": model, "city": city}.items() if v}
        return await self._call("GET", "/stock", params=params)

    async def prices(self, market: str = "SE") -> str:
        return await self._call("GET", "/prices", params={"market": market})

    async def book(self, model: str, city: str, date: str, requester: str) -> str:
        body = {"model": model, "city": city, "date": date, "requester": requester}
        return await self._call("POST", "/test-drives", json=body)

    async def _call(self, method: str, path: str, **kwargs) -> str:
        headers = {
            "Authorization": f"Bearer {await self._token_provider()}",
            "X-Correlation-Id": current_correlation_id.get() or str(uuid.uuid4()),
        }
        try:
            response = await self._http.request(
                method, f"{self._base_url}{path}", headers=headers, **kwargs
            )
        except httpx.HTTPError as exc:
            return f"The dealer service could not be reached ({type(exc).__name__}). Try again later."
        if response.is_success:
            return response.text
        if response.status_code >= 500:
            return (
                f"The dealer service is unavailable (HTTP {response.status_code}). "
                "Try again later."
            )
        return f"The dealer service rejected the request (HTTP {response.status_code}): {_detail(response)}"


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, list):  # FastAPI validation errors
        detail = "; ".join(
            f"{'.'.join(str(p) for p in e.get('loc', [])[1:])}: {e.get('msg')}" for e in detail
        )
    return str(detail or response.text or "no details")
