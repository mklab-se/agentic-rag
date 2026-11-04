#!/bin/sh
# Create the Foundry agents of backends A and C, then grant the hosted agent its access.
#
#   scripts/deploy-agents.sh
#
# 1. create_agents.py   the two prompt agents (backend A)
# 2. deploy.py          builds the hosted agent image in ACR, creates the agent version, waits until
#                       it is active and stores HOSTED_AGENT_PRINCIPAL_ID in the azd environment
# 3. azd provision      Bicep assigns the hosted agent identity its roles on Foundry and Search
# 4. assign-app-role    the hosted agent identity gets Dealer.Access (Graph, not Bicep)
# 5. smoke.py           health of the API and dealer, the indexer, one turn per backend
# Run it after `azd up`, from the repository root, signed in with az and azd as the deployer.
set -eu
cd "$(dirname "$0")/.."

load_env() { set -a; eval "$(azd env get-values)"; set +a; }
# Fresh role assignments can take minutes to propagate, so calls retry.
retry() { n=0; until "$@"; do n=$((n+1)); [ "$n" -ge 10 ] && return 1; echo "retrying in 60s (role propagation)"; sleep 60; done; }

load_env
# Path dependencies are installed as copies, so pick up the current agent_core.
uv sync -q --project agents/prompt --reinstall-package voltrieve-agent-core
uv run --project agents/prompt agents/prompt/create_agents.py
uv run --project agents/hosted agents/hosted/deploy.py

# Provision again so Bicep sees HOSTED_AGENT_PRINCIPAL_ID.
azd provision --no-prompt

load_env
[ -n "${HOSTED_AGENT_PRINCIPAL_ID:-}" ] || { echo "deploy-agents: HOSTED_AGENT_PRINCIPAL_ID is not set" >&2; exit 1; }
retry uv run --project infra/scripts/entra voltrieve-entra assign-app-role \
  --principal-object-id "$HOSTED_AGENT_PRINCIPAL_ID" \
  --resource-sp-object-id "$DEALER_SP_OBJECT_ID" \
  --app-role-id "$DEALER_APP_ROLE_ID"

# A new agent version and fresh role assignments can take minutes to settle, so the check retries.
retry uv run scripts/smoke.py
echo "Note: sessions are bound to the agent version they started on; conversations in flight stay on the old version until the API restarts (or a call fails and the session is dropped)."
echo "Agents deployed. Hosted agent: ${HOSTED_AGENT_NAME:-voltrieve-hosted} (principal $HOSTED_AGENT_PRINCIPAL_ID)"
