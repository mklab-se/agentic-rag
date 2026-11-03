import pytest

from voltrieve_entra import apps
from voltrieve_entra.graph import GraphError

DOMAIN = "contoso.onmicrosoft.com"


def test_api_body_has_scope_and_user_roles():
    body = apps.api_application_body("s", "c", "b")
    assert body["api"]["oauth2PermissionScopes"][0]["value"] == "access_as_user"
    assert {r["value"] for r in body["appRoles"]} == {"Chat.User", "TestDrive.Book"}
    assert all(r["allowedMemberTypes"] == ["User"] for r in body["appRoles"])


def test_dealer_body_has_application_role_and_v2_tokens():
    body = apps.dealer_application_body("r")
    assert body["appRoles"][0]["allowedMemberTypes"] == ["Application"]
    assert body["api"]["requestedAccessTokenVersion"] == 2


def test_cli_and_web_bodies():
    cli = apps.cli_application_body("api-id", "s")
    assert cli["isFallbackPublicClient"] is True
    assert cli["publicClient"]["redirectUris"] == ["http://localhost"]
    assert cli["requiredResourceAccess"][0]["resourceAppId"] == "api-id"
    web = apps.web_application_body("api-id", "s", ["https://x.example"])
    assert web["spa"]["redirectUris"] == ["http://localhost:5173", "https://x.example"]


def test_ensure_application_creates_when_missing(graph_mock, graph):
    app = apps.ensure_application(graph, "voltrieve-api", {"signInAudience": "AzureADMyOrg"})
    assert graph_mock.calls("POST", "/applications") == 1 and app["appId"]


def test_ensure_application_is_idempotent(graph_mock, graph):
    apps.ensure_application(graph, "voltrieve-api", {})
    apps.ensure_application(graph, "voltrieve-api", {})
    assert graph_mock.calls("POST", "/applications") == 1
    assert graph_mock.calls("PATCH", "/applications") == 2


def test_setup_twice_yields_same_ids_and_no_duplicates(graph_mock, graph):
    first = apps.setup(graph, "tid", "deployer-oid", DOMAIN, [])
    second = apps.setup(graph, "tid", "deployer-oid", DOMAIN, [])
    assert first == second
    assert graph_mock.calls("POST", "/applications") == 4
    assert graph_mock.calls("POST", "/users") == 1


def test_test_user_gets_only_chat_role(graph_mock, graph):
    env = apps.setup(graph, "tid", "deployer-oid", DOMAIN, [])
    roles = graph_mock.role_assignments_for(principal=graph_mock.user_id(env["TEST_USER_UPN"]))
    assert roles == {env["CHAT_USER_ROLE_ID"]}


def test_deployer_gets_both_roles_and_dealer_requires_assignment(graph_mock, graph):
    env = apps.setup(graph, "tid", "deployer-oid", DOMAIN, [])
    assert graph_mock.role_assignments_for("deployer-oid") == {
        env["CHAT_USER_ROLE_ID"],
        env["TESTDRIVE_BOOK_ROLE_ID"],
    }
    assert graph_mock.service_principals[env["DEALER_SP_OBJECT_ID"]]["appRoleAssignmentRequired"] is True
    assert env["TENANT_ID"] == "tid"


def test_identifier_uri_is_set_on_api_app(graph_mock, graph):
    env = apps.setup(graph, "tid", "deployer-oid", DOMAIN, [])
    api = next(a for a in graph_mock.applications.values() if a["appId"] == env["API_CLIENT_ID"])
    assert api["identifierUris"] == [f"api://{env['API_CLIENT_ID']}"]


def test_ids_are_pinned_literals():
    assert apps.stable_id("role:Chat.User") == "699e5049-b427-5f0a-9191-79d004d41eaf"


def test_ids_are_stable_across_runs():
    assert apps.stable_id("chat-user") == apps.stable_id("chat-user")
    assert apps.stable_id("chat-user") != apps.stable_id("testdrive-book")


def test_password_is_returned_only_when_user_is_created(graph_mock, graph, no_sleep):
    _, first = apps.ensure_user(graph, f"u@{DOMAIN}", "U", sleep=no_sleep)
    _, second = apps.ensure_user(graph, f"u@{DOMAIN}", "U", sleep=no_sleep)
    assert first and second is None


def test_setup_hands_password_to_callback_not_result(graph_mock, graph):
    seen: list[str] = []
    env = apps.setup(graph, "tid", "deployer-oid", DOMAIN, [], on_password=seen.append)
    assert len(seen) == 1 and seen[0] not in env.values()
    apps.setup(graph, "tid", "deployer-oid", DOMAIN, [], on_password=seen.append)
    assert len(seen) == 1


def test_role_assignment_is_noop_when_present(graph_mock, graph, no_sleep):
    role = {
        "id": "r", "value": "R", "displayName": "R", "description": "R",
        "isEnabled": True, "allowedMemberTypes": ["User"],
    }
    app = apps.ensure_application(graph, "a", {"appRoles": [role]})
    sp = apps.ensure_service_principal(graph, app["appId"], sleep=no_sleep)
    apps.ensure_app_role_assignment(graph, "p", sp["id"], "r", sleep=no_sleep)
    apps.ensure_app_role_assignment(graph, "p", sp["id"], "r", sleep=no_sleep)
    assert graph_mock.calls("POST", f"/servicePrincipals/{sp['id']}/appRoleAssignedTo") == 1


def test_oauth2_grant_is_noop_when_present(graph_mock, graph, no_sleep):
    apps.ensure_oauth2_grant(graph, "c", "r", "access_as_user", sleep=no_sleep)
    apps.ensure_oauth2_grant(graph, "c", "r", "access_as_user", sleep=no_sleep)
    assert graph_mock.calls("POST", "/oauth2PermissionGrants") == 1


def test_service_principal_retries_transient_not_found(graph_mock, graph):
    app = apps.ensure_application(graph, "a", {})
    graph_mock.fail_next("POST", "/servicePrincipals", 400, times=2)
    sleeps: list[float] = []
    sp = apps.ensure_service_principal(graph, app["appId"], sleep=sleeps.append)
    assert sp["appId"] == app["appId"]
    assert graph_mock.calls("POST", "/servicePrincipals") == 3
    assert len(sleeps) == 2


def test_retry_is_bounded_and_surfaces_error(graph_mock, graph):
    app = apps.ensure_application(graph, "a", {})
    graph_mock.fail_next("POST", "/servicePrincipals", 404, times=100)
    sleeps: list[float] = []
    with pytest.raises(GraphError) as err:
        apps.ensure_service_principal(graph, app["appId"], sleep=sleeps.append)
    assert err.value.status == 404
    assert graph_mock.calls("POST", "/servicePrincipals") == apps.RETRY_ATTEMPTS


def test_non_transient_errors_are_not_retried(graph_mock, graph):
    app = apps.ensure_application(graph, "a", {})
    graph_mock.fail_next("POST", "/servicePrincipals", 403, times=5)
    sleeps: list[float] = []
    with pytest.raises(GraphError):
        apps.ensure_service_principal(graph, app["appId"], sleep=sleeps.append)
    assert sleeps == []


def test_application_patch_retries_after_create(graph_mock, graph):
    graph_mock.fail_next("PATCH", "/applications", 404, times=2)
    sleeps: list[float] = []
    app = apps.ensure_application(graph, "voltrieve-api", {"signInAudience": "AzureADMyOrg"}, sleep=sleeps.append)
    assert graph_mock.calls("POST", "/applications") == 1
    assert graph_mock.calls("PATCH", "/applications") == 3
    assert len(sleeps) == 2 and graph_mock.applications[app["id"]]["signInAudience"] == "AzureADMyOrg"


def test_setup_identifier_uri_patches_retry(graph_mock, graph):
    graph_mock.fail_next("PATCH", "/applications", 404, times=3)
    env = apps.setup(graph, "tid", "deployer-oid", DOMAIN, [], sleep=lambda _s: None)
    api = next(a for a in graph_mock.applications.values() if a["appId"] == env["API_CLIENT_ID"])
    assert api["identifierUris"] == [f"api://{env['API_CLIENT_ID']}"]


def test_duplicate_display_name_is_an_error(graph_mock, graph):
    graph_mock.applications["1"] = {"id": "1", "appId": "a1", "displayName": "dup"}
    graph_mock.applications["2"] = {"id": "2", "appId": "a2", "displayName": "dup"}
    with pytest.raises(RuntimeError, match="dup"):
        apps.ensure_application(graph, "dup", {})


def test_setup_grant_bodies(graph_mock, graph):
    env = apps.setup(graph, "tid", "deployer-oid", DOMAIN, [])
    sps = {s["appId"]: s["id"] for s in graph_mock.service_principals.values()}
    assert sorted((g["clientId"], g["resourceId"], g["consentType"], g["scope"]) for g in graph_mock.grants) == sorted(
        (sps[env[k]], env["API_SP_OBJECT_ID"], "AllPrincipals", "access_as_user")
        for k in ("CLI_CLIENT_ID", "WEB_CLIENT_ID")
    )


def test_removing_an_enabled_role_is_rejected_by_graph(graph_mock, graph):
    apps.setup(graph, "tid", "deployer-oid", DOMAIN, [])
    api = next(a for a in graph_mock.applications.values() if a["displayName"] == "voltrieve-api")
    with pytest.raises(GraphError) as err:
        graph.patch(f"/applications/{api['id']}", {"appRoles": []})
    assert err.value.status == 400


def test_generated_password_meets_complexity(graph_mock, graph, no_sleep):
    _, password = apps.ensure_user(graph, f"p@{DOMAIN}", "P", sleep=no_sleep)
    assert any(c.isupper() for c in password) and any(c.islower() for c in password)
    assert any(c.isdigit() for c in password) and any(not c.isalnum() for c in password)


def _app(graph_mock, name):
    return next(a for a in graph_mock.applications.values() if a["displayName"] == name)


def test_azure_cli_is_pre_authorized_for_the_scope(graph_mock, graph):
    env = apps.setup(graph, "tid", "deployer-oid", DOMAIN, [])
    api = _app(graph_mock, "voltrieve-api")
    assert api["api"]["preAuthorizedApplications"] == [
        {"appId": "04b07795-8ddb-461a-bbee-02f9e1bf7b46", "delegatedPermissionIds": [env["API_SCOPE_ID"]]}
    ]
    assert api["api"]["oauth2PermissionScopes"][0]["value"] == "access_as_user"


def test_pre_authorization_survives_a_second_setup(graph_mock, graph):
    apps.setup(graph, "tid", "deployer-oid", DOMAIN, [])
    apps.setup(graph, "tid", "deployer-oid", DOMAIN, [])
    api = _app(graph_mock, "voltrieve-api")
    assert len(api["api"]["preAuthorizedApplications"]) == 1
    assert len(api["api"]["oauth2PermissionScopes"]) == 1


def test_graph_rejects_pre_authorization_of_an_unknown_scope(graph_mock, graph):
    apps.setup(graph, "tid", "deployer-oid", DOMAIN, [])
    api = _app(graph_mock, "voltrieve-api")
    with pytest.raises(GraphError) as err:
        graph.patch(
            f"/applications/{api['id']}",
            {"api": {"preAuthorizedApplications": [{"appId": "x", "delegatedPermissionIds": ["nope"]}]}},
        )
    assert err.value.status == 400


def test_setup_passes_web_redirect_uri(graph_mock, graph):
    apps.setup(graph, "tid", "deployer-oid", DOMAIN, ["https://web.example"])
    assert _app(graph_mock, "voltrieve-web")["spa"]["redirectUris"] == [
        "http://localhost:5173",
        "https://web.example",
    ]


def test_set_spa_redirect_adds_once_and_keeps_existing(graph_mock, graph, no_sleep):
    apps.setup(graph, "tid", "deployer-oid", DOMAIN, [])
    apps.ensure_spa_redirect(graph, "https://web.example", no_sleep)
    apps.ensure_spa_redirect(graph, "https://web.example", no_sleep)
    assert _app(graph_mock, "voltrieve-web")["spa"]["redirectUris"] == [
        "http://localhost:5173",
        "https://web.example",
    ]
    assert graph_mock.calls("PATCH", "/applications") > 0


def test_set_spa_redirect_requires_the_web_app(graph_mock, graph, no_sleep):
    with pytest.raises(RuntimeError, match="voltrieve-web"):
        apps.ensure_spa_redirect(graph, "https://web.example", no_sleep)
