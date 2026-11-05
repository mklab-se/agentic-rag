#!/bin/sh
# Run the routing questions on all three backends with each model, then finish on gpt-5.4-mini.
#
#   scripts/compare_architectures.sh gpt-6.1-terra gpt-6-luna gpt-5.4-mini
#
# For each model this updates the prompt agents and the hosted agent, then the API, so the API's
# restart drops sessions of the old agent version. Results land in
# docs/evidence/models/arch-<model>.json. Each model needs a deployment of the same name.
set -u
cd "$(dirname "$0")/.."
set -a; eval "$(azd env get-values)"; set +a
uv sync -q --project agents/prompt --reinstall-package voltrieve-agent-core --reinstall-package voltrieve-search

use_model() {
  CHAT_DEPLOYMENT=$1 uv run --project agents/prompt agents/prompt/create_agents.py || return 1
  CHAT_DEPLOYMENT=$1 uv run --project agents/hosted agents/hosted/deploy.py || return 1
  az containerapp update -g "$AZURE_RESOURCE_GROUP" -n ca-api-voltrieve-dev \
    --set-env-vars "CHAT_DEPLOYMENT=$1" --only-show-errors -o none || return 1
  sleep 60
}

for model in "$@"; do
  echo "== $model $(date +%H:%M)"
  use_model "$model" > /dev/null 2>&1 || { echo "could not switch to $model"; continue; }
  echo "switched $(date +%H:%M)"
  uv run tests/routing/check.py --backends loop,prompt,hosted --repeats 2 --workers 3 \
    --label "arch-$model" 2>/dev/null | grep -E "^(loop|prompt|hosted) " | cut -c1-90
done
echo "== restoring gpt-5.4-mini"
use_model gpt-5.4-mini > /dev/null 2>&1 && echo "restored $(date +%H:%M)"
