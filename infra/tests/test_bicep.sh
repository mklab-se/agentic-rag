#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
az bicep build --file main.bicep --stdout > /dev/null
az bicep lint --file main.bicep
# every role assignment uses a GUID, never a role name
if grep -rn "roleDefinitionId.*'[A-Z][a-zA-Z ]*'" modules/ main.bicep; then echo "role name used"; exit 1; fi
# the only key lookups allowed are the commented, non-application ones
if grep -rn -i "listKeys\|apiKey\|accountKey" modules/ main.bicep | grep -v "not an application secret"; then echo "key usage found"; exit 1; fi
# the API emits GenAI spans, and nothing reads the knowledge base connection name at runtime
grep -q "AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING" modules/api-app.bicep || { echo "api-app lacks the GenAI tracing setting"; exit 1; }
if grep -q "KB_CONNECTION_NAME\|kbConnectionName" modules/api-app.bicep; then echo "api-app still takes the knowledge base connection name"; exit 1; fi
echo "bicep ok"
