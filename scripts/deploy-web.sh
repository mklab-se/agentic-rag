#!/bin/sh
# Uploads clients/web/dist with the Linux StaticSitesClient in Docker. Use this where the SWA CLI
# cannot run its client, such as Apple Silicon without Rosetta. The deployment token stays in memory.
set -eu
cd "$(dirname "$0")/.."
eval "$(azd env get-values | grep -E '^AZURE_RESOURCE_GROUP=')"
name="$(az staticwebapp list -g "$AZURE_RESOURCE_GROUP" --query '[0].name' -o tsv)"
TOKEN="$(az staticwebapp secrets list -n "$name" -g "$AZURE_RESOURCE_GROUP" --query properties.apiKey -o tsv)"
export TOKEN
docker run --rm --platform linux/amd64 -e TOKEN -e DEPLOYMENT_PROVIDER=SwaCli -e REPOSITORY_BASE=/ \
  -v "$PWD/clients/web/dist:/app/dist:ro" -w /admin \
  mcr.microsoft.com/appsvc/staticappsclient:stable \
  sh -c '/bin/staticsites/StaticSitesClient upload --workdir /app --app /app/dist --skipAppBuild true --apiToken "$TOKEN"' 
