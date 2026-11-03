import secrets
import time
import uuid
from collections.abc import Callable
from typing import TypeVar

from .graph import GraphClient, GraphError

T = TypeVar("T")
Sleep = Callable[[float], None]

RETRY_ATTEMPTS = 6
RETRY_BACKOFF_SECONDS = 1.0
SCOPE_VALUE = "access_as_user"


def stable_id(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"voltrieve:{name}"))


def _retrying(call: Callable[[], T], sleep: Sleep) -> T:
    """Run call, retrying on 404 and 400, which Graph returns while a freshly created
    object has not replicated yet. Bounded, with linear backoff."""
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return call()
        except GraphError as err:
            if err.status not in (400, 404) or attempt == RETRY_ATTEMPTS:
                raise
            sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise AssertionError("unreachable")


def _quote(value: str) -> str:
    return value.replace("'", "''")


# Application bodies


def _app_role(role_id: str, value: str, description: str, member_types: list[str]) -> dict:
    return {
        "id": role_id,
        "value": value,
        "displayName": value,
        "description": description,
        "isEnabled": True,
        "allowedMemberTypes": member_types,
    }


def api_application_body(scope_id: str, chat_role_id: str, book_role_id: str) -> dict:
    return {
        "signInAudience": "AzureADMyOrg",
        "api": {
            "requestedAccessTokenVersion": 2,
            "oauth2PermissionScopes": [
                {
                    "id": scope_id,
                    "value": SCOPE_VALUE,
                    "type": "User",
                    "isEnabled": True,
                    "adminConsentDisplayName": "Access Voltrieve as the signed-in user",
                    "adminConsentDescription": "Allows the app to call the Voltrieve API on behalf of the signed-in user.",
                    "userConsentDisplayName": "Access Voltrieve as you",
                    "userConsentDescription": "Allows the app to call the Voltrieve API on your behalf.",
                }
            ],
        },
        "appRoles": [
            _app_role(chat_role_id, "Chat.User", "Can chat with the Voltrieve assistant.", ["User"]),
            _app_role(book_role_id, "TestDrive.Book", "Can book test drives.", ["User"]),
        ],
    }


def _required_access(api_client_id: str, scope_id: str) -> list[dict]:
    return [
        {
            "resourceAppId": api_client_id,
            "resourceAccess": [{"id": scope_id, "type": "Scope"}],
        }
    ]


def cli_application_body(api_client_id: str, scope_id: str) -> dict:
    return {
        "signInAudience": "AzureADMyOrg",
        "isFallbackPublicClient": True,
        "publicClient": {"redirectUris": ["http://localhost"]},
        "requiredResourceAccess": _required_access(api_client_id, scope_id),
    }


def web_application_body(api_client_id: str, scope_id: str, redirect_uris: list[str]) -> dict:
    return {
        "signInAudience": "AzureADMyOrg",
        "spa": {"redirectUris": ["http://localhost:5173", *redirect_uris]},
        "requiredResourceAccess": _required_access(api_client_id, scope_id),
    }


def dealer_application_body(role_id: str) -> dict:
    return {
        "signInAudience": "AzureADMyOrg",
        "api": {"requestedAccessTokenVersion": 2},
        "appRoles": [
            _app_role(role_id, "Dealer.Access", "Can call the Voltrieve dealer service.", ["Application"])
        ],
    }


# Idempotent operations


def ensure_application(
    g: GraphClient, display_name: str, desired: dict, sleep: Sleep = time.sleep
) -> dict:
    found = g.get(f"/applications?$filter=displayName eq '{_quote(display_name)}'") or {}
    matches = found.get("value", [])
    if len(matches) > 1:
        raise RuntimeError(
            f"{len(matches)} applications are named '{display_name}'; "
            "delete the duplicates in Entra and rerun"
        )
    app = matches[0] if matches else g.post("/applications", {"displayName": display_name})
    assert app is not None
    # A PATCH right after the POST can 404 until the new application has replicated.
    _retrying(lambda: g.patch(f"/applications/{app['id']}", desired), sleep)
    return {**app, **desired}


def ensure_service_principal(g: GraphClient, app_id: str, sleep: Sleep = time.sleep) -> dict:
    def call() -> dict:
        found = g.get(f"/servicePrincipals?$filter=appId eq '{_quote(app_id)}'") or {}
        if found.get("value"):
            return found["value"][0]
        created = g.post("/servicePrincipals", {"appId": app_id})
        assert created is not None
        return created

    return _retrying(call, sleep)


def ensure_app_role_assignment(
    g: GraphClient,
    principal_object_id: str,
    resource_sp_object_id: str,
    app_role_id: str,
    sleep: Sleep = time.sleep,
) -> dict:
    def call() -> dict:
        existing = g.get(f"/servicePrincipals/{resource_sp_object_id}/appRoleAssignedTo") or {}
        for item in existing.get("value", []):
            if item["principalId"] == principal_object_id and item["appRoleId"] == app_role_id:
                return item
        created = g.post(
            f"/servicePrincipals/{resource_sp_object_id}/appRoleAssignedTo",
            {
                "principalId": principal_object_id,
                "resourceId": resource_sp_object_id,
                "appRoleId": app_role_id,
            },
        )
        assert created is not None
        return created

    return _retrying(call, sleep)


def ensure_oauth2_grant(
    g: GraphClient, client_sp_id: str, resource_sp_id: str, scope: str, sleep: Sleep = time.sleep
) -> dict:
    def call() -> dict:
        existing = g.get(
            f"/oauth2PermissionGrants?$filter=clientId eq '{client_sp_id}' and resourceId eq '{resource_sp_id}'"
        ) or {}
        for item in existing.get("value", []):
            if set(item.get("scope", "").split()) >= set(scope.split()):
                return item
        if existing.get("value"):
            current = existing["value"][0]
            merged = " ".join(sorted(set(current.get("scope", "").split()) | set(scope.split())))
            g.patch(f"/oauth2PermissionGrants/{current['id']}", {"scope": merged})
            return {**current, "scope": merged}
        created = g.post(
            "/oauth2PermissionGrants",
            {
                "clientId": client_sp_id,
                "consentType": "AllPrincipals",
                "resourceId": resource_sp_id,
                "scope": scope,
            },
        )
        assert created is not None
        return created

    return _retrying(call, sleep)


def ensure_user(
    g: GraphClient, upn: str, display_name: str, sleep: Sleep = time.sleep
) -> tuple[dict, str | None]:
    """Return the user and, only when it was just created, the generated password."""
    try:
        existing = g.get(f"/users/{upn}")
    except GraphError as err:
        if err.status != 404:
            raise
        existing = None
    if existing:
        return existing, None
    # The fixed suffix guarantees upper, lower, digit and symbol for the Entra complexity rules.
    password = secrets.token_urlsafe(24) + "aA1!"
    body = {
        "accountEnabled": True,
        "displayName": display_name,
        "mailNickname": upn.split("@")[0],
        "userPrincipalName": upn,
        "passwordProfile": {"forceChangePasswordNextSignIn": False, "password": password},
    }
    created = _retrying(lambda: g.post("/users", body), sleep)
    assert created is not None
    return created, password


def setup(
    g: GraphClient,
    tenant_id: str,
    deployer_object_id: str,
    verified_domain: str,
    web_redirect_uris: list[str],
    sleep: Sleep = time.sleep,
    on_password: Callable[[str], None] | None = None,
) -> dict[str, str]:
    scope_id = stable_id("scope:access_as_user")
    chat_role_id = stable_id("role:Chat.User")
    book_role_id = stable_id("role:TestDrive.Book")
    dealer_role_id = stable_id("role:Dealer.Access")

    api = ensure_application(
        g, "voltrieve-api", api_application_body(scope_id, chat_role_id, book_role_id), sleep
    )
    # The identifier URI embeds the appId, so it can only be set after creation.
    _retrying(
        lambda: g.patch(f"/applications/{api['id']}", {"identifierUris": [f"api://{api['appId']}"]}),
        sleep,
    )
    cli = ensure_application(g, "voltrieve-cli", cli_application_body(api["appId"], scope_id), sleep)
    web = ensure_application(
        g, "voltrieve-web", web_application_body(api["appId"], scope_id, web_redirect_uris), sleep
    )
    dealer = ensure_application(
        g, "voltrieve-dealer", dealer_application_body(dealer_role_id), sleep
    )
    _retrying(
        lambda: g.patch(
            f"/applications/{dealer['id']}", {"identifierUris": [f"api://{dealer['appId']}"]}
        ),
        sleep,
    )

    api_sp = ensure_service_principal(g, api["appId"], sleep)
    cli_sp = ensure_service_principal(g, cli["appId"], sleep)
    web_sp = ensure_service_principal(g, web["appId"], sleep)
    dealer_sp = ensure_service_principal(g, dealer["appId"], sleep)
    _retrying(
        lambda: g.patch(f"/servicePrincipals/{dealer_sp['id']}", {"appRoleAssignmentRequired": True}),
        sleep,
    )

    for client_sp in (cli_sp, web_sp):
        ensure_oauth2_grant(g, client_sp["id"], api_sp["id"], SCOPE_VALUE, sleep)

    for role_id in (chat_role_id, book_role_id):
        ensure_app_role_assignment(g, deployer_object_id, api_sp["id"], role_id, sleep)

    upn = f"voltrieve-tester@{verified_domain}"
    user, password = ensure_user(g, upn, "Voltrieve Tester", sleep)
    if password is not None and on_password is not None:
        on_password(password)
    ensure_app_role_assignment(g, user["id"], api_sp["id"], chat_role_id, sleep)

    return {
        "TENANT_ID": tenant_id,
        "API_CLIENT_ID": api["appId"],
        "API_SCOPE_ID": scope_id,
        "CLI_CLIENT_ID": cli["appId"],
        "WEB_CLIENT_ID": web["appId"],
        "DEALER_CLIENT_ID": dealer["appId"],
        "DEALER_APP_ROLE_ID": dealer_role_id,
        "DEALER_SP_OBJECT_ID": dealer_sp["id"],
        "API_SP_OBJECT_ID": api_sp["id"],
        "CHAT_USER_ROLE_ID": chat_role_id,
        "TESTDRIVE_BOOK_ROLE_ID": book_role_id,
        "TEST_USER_UPN": upn,
    }
