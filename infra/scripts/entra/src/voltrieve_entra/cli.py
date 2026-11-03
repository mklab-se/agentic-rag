import argparse
import base64
import json
import subprocess
import sys

from azure.identity import AzureCliCredential

from .apps import ensure_app_role_assignment, setup
from .graph import GraphClient

GRAPH_SCOPE = "https://graph.microsoft.com/.default"


def _graph() -> tuple[GraphClient, str]:
    credential = AzureCliCredential()
    token = credential.get_token(GRAPH_SCOPE).token
    return GraphClient(lambda: credential.get_token(GRAPH_SCOPE).token), token


def _tenant_id(token: str) -> str:
    """Read the tid claim of the already trusted az cli token (no verification needed)."""
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))["tid"]


def _azd_env_set(key: str, value: str) -> None:
    subprocess.run(["azd", "env", "set", key, value], check=True)


def _print_password(password: str) -> None:
    print(
        "\nTest user password (shown once, not stored anywhere, save it now):\n"
        f"  {password}\n",
        file=sys.stdout,
    )


def _run_setup(args: argparse.Namespace) -> None:
    g, token = _graph()
    me = g.get("/me?$select=id") or {}
    env = setup(
        g,
        _tenant_id(token),
        me["id"],
        args.verified_domain,
        args.web_redirect_uri,
        on_password=_print_password,
    )
    for key, value in env.items():
        _azd_env_set(key, value)


def _run_assign(args: argparse.Namespace) -> None:
    g, _ = _graph()
    ensure_app_role_assignment(
        g, args.principal_object_id, args.resource_sp_object_id, args.app_role_id
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="voltrieve-entra")
    sub = parser.add_subparsers(dest="command", required=True)

    p_setup = sub.add_parser("setup", help="Create or update the Voltrieve app registrations")
    p_setup.add_argument("--verified-domain", required=True)
    p_setup.add_argument("--web-redirect-uri", action="append", default=[])
    p_setup.set_defaults(func=_run_setup)

    p_assign = sub.add_parser("assign-app-role", help="Assign an app role to a principal")
    p_assign.add_argument("--principal-object-id", required=True)
    p_assign.add_argument("--resource-sp-object-id", required=True)
    p_assign.add_argument("--app-role-id", required=True)
    p_assign.set_defaults(func=_run_assign)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
