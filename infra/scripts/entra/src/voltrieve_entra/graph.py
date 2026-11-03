from collections.abc import Callable

import httpx

BASE_URL = "https://graph.microsoft.com/v1.0"


class GraphError(Exception):
    def __init__(self, status: int, body: object) -> None:
        super().__init__(f"Graph request failed with {status}: {body}")
        self.status = status
        self.body = body


class GraphClient:
    """Minimal Microsoft Graph client. The token provider is called for every request."""

    def __init__(self, token_provider: Callable[[], str], timeout: float = 30.0) -> None:
        self._token_provider = token_provider
        self._http = httpx.Client(base_url=BASE_URL, timeout=timeout)

    def get(self, path: str, json: dict | None = None) -> dict | None:
        return self._request("GET", path, json)

    def post(self, path: str, json: dict | None = None) -> dict | None:
        return self._request("POST", path, json)

    def patch(self, path: str, json: dict | None = None) -> dict | None:
        return self._request("PATCH", path, json)

    def _request(self, method: str, path: str, json: dict | None) -> dict | None:
        response = self._http.request(
            method,
            path,
            json=json,
            headers={"Authorization": f"Bearer {self._token_provider()}"},
        )
        if response.status_code >= 400:
            try:
                body: object = response.json()
            except ValueError:
                body = response.text
            raise GraphError(response.status_code, body)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()
