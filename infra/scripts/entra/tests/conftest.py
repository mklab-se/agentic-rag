import json
import re
import uuid
from collections.abc import Callable

import httpx
import pytest
import respx

from voltrieve_entra.graph import GraphClient

BASE = "https://graph.microsoft.com/v1.0"


class GraphMock:
    """In-memory stand-in for the parts of Microsoft Graph the setup script uses."""

    def __init__(self, router: respx.MockRouter) -> None:
        self.applications: dict[str, dict] = {}
        self.service_principals: dict[str, dict] = {}
        self.users: dict[str, dict] = {}
        self.assignments: list[dict] = []
        self.grants: list[dict] = []
        self.log: list[tuple[str, str]] = []
        self._failures: list[dict] = []
        router.route(host="graph.microsoft.com").mock(side_effect=self._handle)

    # helpers used by tests
    def calls(self, method: str, path_prefix: str) -> int:
        return sum(1 for m, p in self.log if m == method and p.startswith(path_prefix))

    def user_id(self, upn: str) -> str:
        return self.users[upn]["id"]

    def role_assignments_for(self, principal: str) -> set[str]:
        return {a["appRoleId"] for a in self.assignments if a["principalId"] == principal}

    def fail_next(self, method: str, path_prefix: str, status: int, times: int = 1) -> None:
        self._failures.append(
            {"method": method, "prefix": path_prefix, "status": status, "times": times}
        )

    # request handling
    def _handle(self, request: httpx.Request) -> httpx.Response:
        method = request.method
        path = request.url.path.removeprefix("/v1.0")
        self.log.append((method, path))
        for failure in self._failures:
            if failure["times"] > 0 and failure["method"] == method and path.startswith(failure["prefix"]):
                failure["times"] -= 1
                return self._json(failure["status"], {"error": {"code": "Request_ResourceNotFound"}})
        body = json.loads(request.content) if request.content else {}
        params = request.url.params
        for pattern, handler in self._routes():
            m = re.fullmatch(pattern[1], path)
            if m and pattern[0] == method:
                return handler(m, body, params)
        return self._json(404, {"error": {"code": "NotFound", "message": path}})

    def _routes(self):
        return [
            (("GET", r"/applications"), self._list_apps),
            (("POST", r"/applications"), self._create_app),
            (("PATCH", r"/applications/([^/]+)"), self._patch_app),
            (("GET", r"/servicePrincipals"), self._list_sps),
            (("POST", r"/servicePrincipals"), self._create_sp),
            (("PATCH", r"/servicePrincipals/([^/]+)"), self._patch_sp),
            (("GET", r"/servicePrincipals/([^/]+)/appRoleAssignedTo"), self._list_assignments),
            (("POST", r"/servicePrincipals/([^/]+)/appRoleAssignedTo"), self._create_assignment),
            (("GET", r"/users/([^/]+)"), self._get_user),
            (("POST", r"/users"), self._create_user),
            (("GET", r"/oauth2PermissionGrants"), self._list_grants),
            (("POST", r"/oauth2PermissionGrants"), self._create_grant),
            (("PATCH", r"/oauth2PermissionGrants/([^/]+)"), self._patch_grant),
        ]

    @staticmethod
    def _json(status: int, payload: dict | None) -> httpx.Response:
        if payload is None:
            return httpx.Response(status)
        return httpx.Response(status, json=payload)

    @staticmethod
    def _filter_values(params) -> dict[str, str]:
        return dict(re.findall(r"(\w+) eq '((?:[^']|'')*)'", params.get("$filter", "")))

    def _list_apps(self, m, body, params):
        want = self._filter_values(params).get("displayName", "").replace("''", "'")
        return self._json(200, {"value": [a for a in self.applications.values() if a["displayName"] == want]})

    def _create_app(self, m, body, params):
        app = {"id": str(uuid.uuid4()), "appId": str(uuid.uuid4()), **body}
        self.applications[app["id"]] = app
        return self._json(201, app)

    def _patch_app(self, m, body, params):
        app = self.applications.get(m.group(1))
        if app is None:
            return self._json(404, {"error": {"code": "Request_ResourceNotFound"}})
        app.update(body)
        return self._json(204, None)

    def _list_sps(self, m, body, params):
        want = self._filter_values(params).get("appId")
        return self._json(200, {"value": [s for s in self.service_principals.values() if s["appId"] == want]})

    def _create_sp(self, m, body, params):
        if not any(a["appId"] == body.get("appId") for a in self.applications.values()):
            return self._json(400, {"error": {"code": "Request_BadRequest"}})
        sp = {"id": str(uuid.uuid4()), "appRoleAssignmentRequired": False, **body}
        self.service_principals[sp["id"]] = sp
        return self._json(201, sp)

    def _patch_sp(self, m, body, params):
        sp = self.service_principals.get(m.group(1))
        if sp is None:
            return self._json(404, {"error": {"code": "Request_ResourceNotFound"}})
        sp.update(body)
        return self._json(204, None)

    def _list_assignments(self, m, body, params):
        rid = m.group(1)
        if rid not in self.service_principals:
            return self._json(404, {"error": {"code": "Request_ResourceNotFound"}})
        return self._json(200, {"value": [a for a in self.assignments if a["resourceId"] == rid]})

    def _create_assignment(self, m, body, params):
        rid = m.group(1)
        if rid not in self.service_principals:
            return self._json(404, {"error": {"code": "Request_ResourceNotFound"}})
        item = {"id": str(uuid.uuid4()), **body, "resourceId": rid}
        self.assignments.append(item)
        return self._json(201, item)

    def _get_user(self, m, body, params):
        user = self.users.get(m.group(1))
        if user is None:
            return self._json(404, {"error": {"code": "Request_ResourceNotFound"}})
        return self._json(200, user)

    def _create_user(self, m, body, params):
        user = {k: v for k, v in body.items() if k != "passwordProfile"}
        user["id"] = str(uuid.uuid4())
        self.users[body["userPrincipalName"]] = user
        return self._json(201, user)

    def _list_grants(self, m, body, params):
        f = self._filter_values(params)
        return self._json(
            200,
            {"value": [g for g in self.grants if g["clientId"] == f.get("clientId") and g["resourceId"] == f.get("resourceId")]},
        )

    def _create_grant(self, m, body, params):
        grant = {"id": str(uuid.uuid4()), **body}
        self.grants.append(grant)
        return self._json(201, grant)

    def _patch_grant(self, m, body, params):
        for g in self.grants:
            if g["id"] == m.group(1):
                g.update(body)
                return self._json(204, None)
        return self._json(404, {"error": {"code": "Request_ResourceNotFound"}})


@pytest.fixture
def graph_mock():
    with respx.mock(assert_all_called=False) as router:
        yield GraphMock(router)


@pytest.fixture
def graph(graph_mock) -> GraphClient:
    return GraphClient(lambda: "tok")


@pytest.fixture
def no_sleep() -> Callable[[float], None]:
    return lambda _seconds: None
