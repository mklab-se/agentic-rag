#!/bin/sh
set -eu
eval "$(azd env get-values)"
export STORAGE_ACCOUNT_NAME DOCS_CONTAINER STORAGE_RESOURCE_ID FOUNDRY_ENDPOINT EMBEDDING_DEPLOYMENT EMBEDDING_MODEL SEARCH_ENDPOINT
uv run --project search voltrieve-search upload --generated data/generated
uv run --project search voltrieve-search apply
uv run --project search voltrieve-search index
uv run --project search voltrieve-search smoke
