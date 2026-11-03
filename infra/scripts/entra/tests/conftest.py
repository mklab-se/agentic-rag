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
        query = request.url.query.decode()
        self.log.append((method, f"{path}?{query}" if query else path))
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

    @staticmethod
    def _bad_request(message: str) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": "Request_BadRequest", "message": message}})

    @staticmethod
    def _missing(body: dict, required: list[str]) -> list[str]:
        return [f for f in required if not body.get(f)]

    def _create_app(self, m, body, params):
        if self._missing(body, ["displayName"]):
            return self._bad_request("displayName is required")
        app = {"id": str(uuid.uuid4()), "appId": str(uuid.uuid4()), **body}
        self.applications[app["id"]] = app
        return self._json(201, app)

    def _patch_app(self, m, body, params):
        app = self.applications.get(m.group(1))
        if app is None:
            return self._json(404, {"error": {"code": "Request_ResourceNotFound"}})
        for key, id_field in (("appRoles", "id"), ("api.oauth2PermissionScopes", "id")):
            if "." in key:
                outer, inner = key.split(".")
                old = app.get(outer, {}).get(inner, [])
                new = body.get(outer, {}).get(inner) if outer in body else None
            else:
                old, new = app.get(key, []), body.get(key)
            if new is None:
                continue
            new_by_id = {n[id_field]: n for n in new}
            for o in old:
                if o.get("isEnabled") and (
                    o[id_field] not in new_by_id or new_by_id[o[id_field]].get("value") != o.get("value")
                ):
                    return self._bad_request(f"Cannot remove or change enabled entry {o[id_field]}")
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
        if self._missing(body, ["principalId", "resourceId", "appRoleId"]):
            return self._bad_request("principalId, resourceId and appRoleId are required")
        if body["resourceId"] != rid:
            return self._bad_request("resourceId does not match the path")
        app = next(a for a in self.applications.values() if a["appId"] == self.service_principals[rid]["appId"])
        if body["appRoleId"] not in {r["id"] for r in app.get("appRoles", [])}:
            return self._bad_request("appRoleId is not defined on the resource")
        item = {"id": str(uuid.uuid4()), **body}
        self.assignments.append(item)
        return self._json(201, item)

    def _get_user(self, m, body, params):
        user = self.users.get(m.group(1))
        if user is None:
            return self._json(404, {"error": {"code": "Request_ResourceNotFound"}})
        return self._json(200, user)

    def _create_user(self, m, body, params):
        required = ["accountEnabled", "displayName", "mailNickname", "userPrincipalName", "passwordProfile"]
        if self._missing({**body, "accountEnabled": "accountEnabled" in body}, required) or not body.get(
            "passwordProfile", {}
        ).get("password"):
            return self._bad_request("missing required user properties")
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
        if self._missing(body, ["clientId", "consentType", "resourceId", "scope"]):
            return self._bad_request("clientId, consentType, resourceId and scope are required")
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
