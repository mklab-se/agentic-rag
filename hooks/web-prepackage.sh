#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
eval "$(azd env get-values)"
# Public values only: the SPA is a public client, so no secret belongs in this file.
for v in API_URL TENANT_ID WEB_CLIENT_ID API_CLIENT_ID; do
  eval "[ -n \"\${$v:-}\" ]" || { echo "prepackage: $v is not set in the azd environment" >&2; exit 1; }
done
cat > clients/web/.env.production <<ENV
VITE_API_URL=$API_URL
VITE_ENTRA_TENANT_ID=$TENANT_ID
VITE_ENTRA_CLIENT_ID=$WEB_CLIENT_ID
VITE_API_SCOPE=api://$API_CLIENT_ID/access_as_user
ENV
