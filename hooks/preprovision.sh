#!/bin/sh
set -eu
DOMAIN="${VOLTRIEVE_VERIFIED_DOMAIN:-$(az rest -m GET -u 'https://graph.microsoft.com/v1.0/domains' --query "value[?isDefault].id | [0]" -o tsv)}"
uv run --project infra/scripts/entra voltrieve-entra setup --verified-domain "$DOMAIN"
