#!/bin/sh
set -eu
eval "$(azd env get-values)"
export STORAGE_ACCOUNT_NAME DOCS_CONTAINER STORAGE_RESOURCE_ID FOUNDRY_ENDPOINT EMBEDDING_DEPLOYMENT EMBEDDING_MODEL SEARCH_ENDPOINT

# The role assignments for the signed-in user are created for AZURE_PRINCIPAL_ID, so the
# CLI must be signed in as the same user or every call below fails with 403.
signed_in="$(az ad signed-in-user show --query id -o tsv)"
if [ "$signed_in" != "$AZURE_PRINCIPAL_ID" ]; then
  echo "postprovision: az is signed in as $signed_in but AZURE_PRINCIPAL_ID is $AZURE_PRINCIPAL_ID; run az login as the deploying user" >&2
  exit 1
fi

# Fresh role assignments can take minutes to propagate, so data plane calls retry.
retry() { n=0; until "$@"; do n=$((n+1)); [ "$n" -ge 10 ] && return 1; echo "retrying in 60s (role propagation)"; sleep 60; done; }

retry uv run --project search voltrieve-search upload --generated data/generated
retry uv run --project search voltrieve-search apply
retry uv run --project search voltrieve-search index
