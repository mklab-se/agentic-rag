#!/bin/sh
set -eu
DOMAIN="${VOLTRIEVE_VERIFIED_DOMAIN:-$(az rest -m GET -u 'https://graph.microsoft.com/v1.0/domains' --query "value[?isDefault].id | [0]" -o tsv)}"
if [ -z "$DOMAIN" ]; then
  echo "preprovision: could not determine the verified domain; set VOLTRIEVE_VERIFIED_DOMAIN" >&2
  exit 1
fi
uv run --project infra/scripts/entra voltrieve-entra setup --verified-domain "$DOMAIN"
