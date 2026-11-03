"""Minimal Azure AI Search REST client authenticated with Entra bearer tokens."""

from collections.abc import Callable

import httpx

DEFAULT_API_VERSION = "2026-08-01-preview"


class SearchApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


class SearchRestClient:
    def __init__(
        self,
        endpoint: str,
        token_provider: Callable[[], str],
        api_version: str = DEFAULT_API_VERSION,
    ):
        self._endpoint = endpoint.rstrip("/")
        self._token_provider = token_provider
        self._api_version = api_version

    def put(self, path: str, body: dict) -> dict:
        _, payload = self._request("PUT", path, body, {"Prefer": "return=representation"})
        return payload

    def post(self, path: str, body: dict | None = None) -> tuple[int, dict]:
        return self._request("POST", path, body)

    def get(self, path: str) -> dict:
        _, payload = self._request("GET", path, None)
        return payload

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, dict]:
        response = httpx.request(
            method,
            f"{self._endpoint}{path}",
            params={"api-version": self._api_version},
            headers={"Authorization": f"Bearer {self._token_provider()}", **(extra_headers or {})},
            json=body,
            timeout=60.0,
        )
        payload = _json_or_empty(response)
        if response.status_code >= 400:
            raise SearchApiError(response.status_code, _error_message(payload, response))
        return response.status_code, payload


def _json_or_empty(response: httpx.Response) -> dict:
    if not response.content:
        return {}
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _error_message(payload: dict, response: httpx.Response) -> str:
    error = payload.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    return response.text or response.reason_phrase
