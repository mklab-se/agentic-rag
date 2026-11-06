#!/bin/sh
set -eu
eval "$(azd env get-values)"
export STORAGE_ACCOUNT_NAME DOCS_CONTAINER PARTS_CONTAINER STORAGE_RESOURCE_ID FOUNDRY_ENDPOINT EMBEDDING_DEPLOYMENT EMBEDDING_MODEL SEARCH_ENDPOINT FOUNDRY_OPENAI_ENDPOINT PLANNING_DEPLOYMENT PLANNING_MODEL API_PRINCIPAL_ID DEALER_SP_OBJECT_ID DEALER_APP_ROLE_ID WEB_URL

# The role assignments for the signed-in user are created for the azd user, so the
# CLI must be signed in as the same user or every call below fails with 403.
signed_in="$(az ad signed-in-user show --query id -o tsv)"
if [ "$signed_in" != "$DEPLOYER_PRINCIPAL_ID" ]; then
  echo "postprovision: az is signed in as $signed_in but azd deployed as $DEPLOYER_PRINCIPAL_ID; run az login as the deploying user" >&2
  exit 1
fi

# Fresh role assignments can take minutes to propagate, so data plane calls retry.
retry() { n=0; until "$@"; do n=$((n+1)); [ "$n" -ge 10 ] && return 1; echo "retrying in 60s (role propagation)"; sleep 60; done; }

retry uv run --project search voltrieve-search upload --generated data/generated
retry uv run --project search voltrieve-search apply
retry uv run --project search voltrieve-search index

# The API calls the dealer as itself, so its identity needs the Dealer.Access app role.
retry uv run --project infra/scripts/entra voltrieve-entra assign-app-role \
  --principal-object-id "$API_PRINCIPAL_ID" \
  --resource-sp-object-id "$DEALER_SP_OBJECT_ID" \
  --app-role-id "$DEALER_APP_ROLE_ID"
# The Static Web App URL only exists after provisioning, so the first deployment adds it here.
retry uv run --project infra/scripts/entra voltrieve-entra set-spa-redirect --uri "$WEB_URL"
