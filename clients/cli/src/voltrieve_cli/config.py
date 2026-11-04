"""Settings from the environment, falling back to `azd env get-values`."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

# name -> (environment variable that overrides, key in the azd environment)
KEYS = {
    "api_url": ("VOLTRIEVE_API_URL", "API_URL"),
    "tenant_id": ("VOLTRIEVE_TENANT_ID", "TENANT_ID"),
    "cli_client_id": ("VOLTRIEVE_CLI_CLIENT_ID", "CLI_CLIENT_ID"),
    "api_client_id": ("VOLTRIEVE_API_CLIENT_ID", "API_CLIENT_ID"),
}


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    api_url: str
    tenant_id: str
    cli_client_id: str
    api_client_id: str

    @property
    def scope(self) -> str:
        return f"api://{self.api_client_id}/access_as_user"


def parse_env_values(text: str) -> dict[str, str]:
    """Parse KEY="value" lines as printed by `azd env get-values`."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"')
    return values


def _azd_values() -> dict[str, str]:
    try:
        out = subprocess.run(
            ["azd", "env", "get-values"], capture_output=True, text=True, timeout=20, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    return parse_env_values(out.stdout)


def load_settings(env: dict[str, str] | None = None, azd: dict[str, str] | None = None) -> Settings:
    """A VOLTRIEVE_* variable wins; otherwise the azd environment is read (lazily, only if
    needed), so inside an azd project nothing has to be exported."""
    env = dict(os.environ) if env is None else env
    found = {name: env.get(var, "") for name, (var, _) in KEYS.items()}
    if not all(found.values()):
        azd_values = _azd_values() if azd is None else azd
        found = {name: found[name] or azd_values.get(key, "") for name, (_, key) in KEYS.items()}
    missing = [KEYS[n][0] for n, v in found.items() if not v]
    if missing:
        raise ConfigError(
            f"Missing settings: {', '.join(missing)}. Set them, or run inside an azd environment "
            "(`azd env select`)."
        )
    found["api_url"] = found["api_url"].rstrip("/")
    return Settings(**found)
