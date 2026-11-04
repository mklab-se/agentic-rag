"""Entra sign-in. Kept thin: MSAL public client plus an encrypted on-disk cache."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .config import Settings

CACHE_PATH = Path.home() / ".voltrieve" / "msal_cache.bin"


class AuthError(Exception):
    pass


def az_cli_token(settings: Settings) -> str:
    """Token for the API from the Azure CLI session."""
    try:
        out = subprocess.run(
            ["az", "account", "get-access-token", "--scope", settings.scope,
             "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, timeout=60, check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AuthError("az account get-access-token failed; run `az login` first") from exc
    token = out.stdout.strip()
    if not token:
        raise AuthError("az returned an empty token")
    return token


def _build_app(settings: Settings):  # pragma: no cover - needs a real tenant and a keychain
    import msal
    from msal_extensions import FilePersistence, PersistedTokenCache, build_encrypted_persistence

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        persistence = build_encrypted_persistence(str(CACHE_PATH))
    except Exception:
        print("warning: encrypted token cache unavailable, using a plaintext cache file", file=sys.stderr)
        persistence = FilePersistence(str(CACHE_PATH))
    return msal.PublicClientApplication(
        settings.cli_client_id,
        authority=f"https://login.microsoftonline.com/{settings.tenant_id}",
        token_cache=PersistedTokenCache(persistence),
    )


def msal_token(settings: Settings, device_code: bool = False, interactive: bool = True,
               fresh: bool = False) -> str:
    """Silent from cache when possible, else interactive browser or device code.

    `fresh` is for `voltrieve login`: it skips the cache and always shows the account picker, so
    a user with several accounts can choose which one the CLI signs in as."""
    app = _build_app(settings)
    scopes = [settings.scope]
    accounts = [] if fresh else app.get_accounts()
    result = app.acquire_token_silent(scopes, account=accounts[0]) if accounts else None
    if not result and interactive:
        if device_code:
            flow = app.initiate_device_flow(scopes=scopes)
            if "user_code" not in flow:
                raise AuthError(f"Device code flow failed: {flow.get('error_description', flow)}")
            print(flow["message"])
            result = app.acquire_token_by_device_flow(flow)
        else:
            result = app.acquire_token_interactive(scopes=scopes, prompt="select_account")
    if not result or "access_token" not in result:
        detail = (result or {}).get("error_description", "no cached session; run `voltrieve login`")
        raise AuthError(detail)
    return result["access_token"]


def login(settings: Settings, device_code: bool = False) -> None:
    """Sign in as an account the user picks, replacing nothing until the sign-in succeeds."""
    msal_token(settings, device_code=device_code, fresh=True)


def logout(settings: Settings) -> int:
    """Forget every cached account. Returns how many there were."""
    app = _build_app(settings)
    accounts = app.get_accounts()
    for account in accounts:
        app.remove_account(account)
    return len(accounts)


def get_token(settings: Settings, az_token: bool = False, interactive: bool = True) -> str:
    if az_token:
        return az_cli_token(settings)
    return msal_token(settings, interactive=interactive)
