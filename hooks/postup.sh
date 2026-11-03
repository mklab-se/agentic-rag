#!/bin/sh
set -eu
eval "$(azd env get-values)"
export SEARCH_ENDPOINT
# Runs after the dealer has shipped, so a retrieval miss cannot block the deployment.
uv run --project search voltrieve-search smoke
