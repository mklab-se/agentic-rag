"""Build the hosted agent image and deploy it as a new version of the Foundry hosted agent.

    uv run deploy.py        (from the repository root: uv run --project agents/hosted agents/hosted/deploy.py)

Reads the azd environment from the process environment (`eval "$(azd env get-values)"`):
FOUNDRY_PROJECT_ENDPOINT, AZURE_CONTAINER_REGISTRY_NAME, AZURE_CONTAINER_REGISTRY_ENDPOINT,
CHAT_DEPLOYMENT, SEARCH_ENDPOINT, DEALER_URL, DEALER_CLIENT_ID and API_PRINCIPAL_ID.
Optional: HOSTED_AGENT_NAME, and ALLOWED_CALLER_OID (default API_PRINCIPAL_ID, which must not be
empty: the agent refuses every caller but this one).

Steps: `az acr build` (linux/amd64, repository root as context, a unique tag), create the agent
version, wait until it is active, then store the agent identity's principal id with
`azd env set HOSTED_AGENT_PRINCIPAL_ID`. Bicep grants that identity its roles on the next
provision; scripts/deploy-agents.sh does the provision and the Dealer.Access assignment.
"""

import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from azure.ai.projects.models import (
    AgentEndpointProtocol,
    ContainerConfiguration,
    HostedAgentDefinition,
    ProtocolVersionRecord,
    SessionConfiguration,
)

DEFAULT_AGENT_NAME = "voltrieve-hosted"
IMAGE_REPOSITORY = "voltrieve/hosted"
REPO_ROOT = Path(__file__).resolve().parents[2]
POLL_SECONDS = 10
POLL_LIMIT_SECONDS = 15 * 60


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"Missing environment variable {name}. Run `eval \"$(azd env get-values)\"` first.")
    return value


def unique_tag(now: datetime | None = None, sha: str = "") -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d%H%M%S")
    return f"{stamp}-{sha}" if sha else stamp


def _git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def environment_variables(env: dict[str, str]) -> dict[str, str]:
    """What the container needs. FOUNDRY_PROJECT_ENDPOINT and the Application Insights
    connection string are injected by the platform, and FOUNDRY_ names are reserved."""
    allowed = (env.get("ALLOWED_CALLER_OID") or env.get("API_PRINCIPAL_ID") or "").strip()
    if not allowed:
        raise SystemExit("API_PRINCIPAL_ID (or ALLOWED_CALLER_OID) is empty: the agent would refuse every caller.")
    return {
        "MODEL_DEPLOYMENT_NAME": env["CHAT_DEPLOYMENT"],
        "SEARCH_ENDPOINT": env["SEARCH_ENDPOINT"],
        "DEALER_URL": env["DEALER_URL"],
        "DEALER_CLIENT_ID": env["DEALER_CLIENT_ID"],
        "ALLOWED_CALLER_OID": allowed,
        "PYTHONNOUSERSITE": "1",
    }


def hosted_definition(image: str, env: dict[str, str]) -> HostedAgentDefinition:
    return HostedAgentDefinition(
        protocol_versions=[
            ProtocolVersionRecord(protocol=AgentEndpointProtocol.INVOCATIONS, version="2.0.0")
        ],
        cpu="0.5",
        memory="1Gi",
        container_configuration=ContainerConfiguration(image=image),
        # The minimum the platform allows: an idle session is suspended after two minutes.
        session_configuration=SessionConfiguration(idle_timeout_seconds=timedelta(seconds=120)),
        environment_variables=environment_variables(env),
    )


def build_image(registry: str, tag: str) -> None:
    subprocess.run(
        [
            "az", "acr", "build",
            "-r", registry,
            "-t", f"{IMAGE_REPOSITORY}:{tag}",
            "--platform", "linux/amd64",
            "-f", "agents/hosted/Dockerfile",
            ".",
        ],
        cwd=REPO_ROOT,
        check=True,
    )


def wait_until_active(project, name: str, version: str):
    deadline = time.monotonic() + POLL_LIMIT_SECONDS
    while True:
        current = project.agents.get_version(agent_name=name, agent_version=version)
        status = current["status"]
        print(f"{name} version {version}: {status}")
        if status == "active":
            return current
        if status == "failed":
            sys.exit(f"The hosted agent version failed to start: {current}")
        if time.monotonic() > deadline:
            sys.exit(f"The hosted agent version is still {status} after {POLL_LIMIT_SECONDS}s.")
        time.sleep(POLL_SECONDS)


def main() -> None:
    env = dict(os.environ)
    endpoint = _require("FOUNDRY_PROJECT_ENDPOINT")
    registry = _require("AZURE_CONTAINER_REGISTRY_NAME")
    login_server = _require("AZURE_CONTAINER_REGISTRY_ENDPOINT")
    for name in ("CHAT_DEPLOYMENT", "SEARCH_ENDPOINT", "DEALER_URL", "DEALER_CLIENT_ID"):
        _require(name)
    agent_name = env.get("HOSTED_AGENT_NAME") or DEFAULT_AGENT_NAME

    tag = unique_tag(sha=_git_sha())
    build_image(registry, tag)
    image = f"{login_server}/{IMAGE_REPOSITORY}:{tag}"

    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=endpoint, credential=credential
    ) as project:
        created = project.agents.create_version(
            agent_name=agent_name, definition=hosted_definition(image, env)
        )
        print(f"{agent_name}: created version {created['version']} from {image}")
        active = wait_until_active(project, agent_name, created["version"])

    principal_id = active["instance_identity"]["principal_id"]
    subprocess.run(["azd", "env", "set", "HOSTED_AGENT_PRINCIPAL_ID", principal_id], check=True)
    print(f"HOSTED_AGENT_PRINCIPAL_ID set to {principal_id}")


if __name__ == "__main__":
    main()
