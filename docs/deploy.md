# Deployment

How to deploy Voltrieve to Azure, in the order that worked on 2026-11-04. Nothing here uses API keys: every call uses Entra tokens.

## Prerequisites

Tools:

- Azure CLI (`az`) and Azure Developer CLI (`azd`)
- `uv` (Python 3.12 is resolved per project)
- Node.js and npm, for the SPA build
- Docker, where the Static Web Apps CLI cannot run (see below)

Rights, for one user account. A service principal does not work, because the deployer role assignments use `principalType: 'User'`:

- enough on the subscription to create resources and role assignments;
- in Entra: create app registrations, service principals, a user, and app role assignments.

Sign in to both tools as the same user. The post-provision hook checks this and stops if they differ:

```sh
az login
azd auth login
```

## Regions and why

| Resource | Region | Why |
| --- | --- | --- |
| Foundry, storage, Container Apps, registry, monitoring | Sweden Central (`AZURE_LOCATION`) | The primary region |
| Azure AI Search | France Central (`AZURE_SEARCH_LOCATION`, the default) | Sweden Central and West Europe were flagged as not accepting new Search services. France Central is the nearest EU region that does. |
| Static Web App | East US 2 (`webLocation` in Bicep) | West Europe rejected new Static Web Apps. This region holds the metadata; the content is global. |

Search reaches Foundry and storage over public endpoints with Entra tokens.

The own loop runs `gpt-6.1-terra` version `2026-10-26`, set with `loopModelName`. The prompt agents, the hosted agent and Search planning use the chat model, and Search refuses GPT-6 models for planning. Do not move the chat model without checking availability: `gpt-5.4-mini` version `2026-03-17` is deployed as GlobalStandard with capacity 50. Capacity 10 caused rate limit failures in multi-question runs. On pay-per-token, capacity is a cap, not a cost.

## Environment

```sh
azd env new voltrieve-dev
azd env set AZURE_LOCATION swedencentral
```

The name is limited to 22 characters and appears in resource names. Optional values:

| Name | Default | Purpose |
| --- | --- | --- |
| `AZURE_SEARCH_LOCATION` | `francecentral` | Search region |
| `VOLTRIEVE_VERIFIED_DOMAIN` | the tenant's default domain | Domain for the tester account |

The hooks and scripts fill in the rest, such as `TENANT_ID`, `API_CLIENT_ID`, `WEB_URL`, `TEST_USER_UPN` and `HOSTED_AGENT_PRINCIPAL_ID`. All of them are identifiers. The Application Insights connection string is an ingestion identifier, not a secret.

## Order

### 1. `azd up`

```sh
azd up
```

Stay at the terminal: the preprovision hook prints the tester's password once, the first time the account is created, and it is not stored anywhere. Do not paste it into docs or tickets.

`azure.yaml` replaces the default order with provision, `package --all`, `deploy --all`. The default packages first, which is too early: the web build needs values that provision creates.

What each hook does:

| Hook | When | What |
| --- | --- | --- |
| `hooks/preprovision.sh` | Before each provision | Creates or updates the app registrations (`voltrieve-api`, `voltrieve-cli`, `voltrieve-web`, `voltrieve-dealer`), the tester, roles and consent, and stores the ids in the azd environment. Idempotent. Runs interactively so the password is visible. |
| `hooks/postprovision.sh` | After each provision | Checks that `az` and `azd` are the same user. Uploads the documents to their two containers, applies the search objects of both knowledge bases, runs both indexers, gives the API identity `Dealer.Access`, and adds the SPA redirect URI. Each step retries up to 10 times, 60 seconds apart, for role propagation. |
| `hooks/web-prepackage.sh` | Before the web package | Writes `clients/web/.env.production` with public values only. |
| `hooks/postup.sh` | After `azd up` | Runs the search smoke test. It runs last so that a retrieval miss cannot block a deployment. |

Provision keeps deployed images: azd sets `SERVICE_API_RESOURCE_EXISTS` and `SERVICE_DEALER_RESOURCE_EXISTS`, so Bicep reuses the current image instead of the placeholder.

### 2. Apple Silicon without Rosetta: `scripts/deploy-web.sh`

`azd` deploys the SPA with the Static Web Apps CLI, whose upload client is an x86 binary. On Apple Silicon without Rosetta that step fails. `dealer` and `api` deploy first, so only `web` is missing. Installing Rosetta is a system change, so this repository uses a container instead:

```sh
azd package web        # only if clients/web/dist is missing or stale
scripts/deploy-web.sh
```

It runs the Linux `StaticSitesClient` in Docker against `clients/web/dist`, and keeps the deployment token in memory. If `azd up` stopped at this step, run the smoke test by hand, since the `postup` hook may not have run:

```sh
SEARCH_ENDPOINT="$(azd env get-value SEARCH_ENDPOINT)" uv run --project search voltrieve-search smoke
```

### 3. `scripts/deploy-agents.sh`

Run this after `azd up`, from the repository root, as the deployer:

```sh
scripts/deploy-agents.sh
```

1. `agents/prompt/create_agents.py` creates a new version of `voltrieve-prompt-cli` and `voltrieve-prompt-web`.
2. `agents/hosted/deploy.py` builds the `linux/amd64` image with `az acr build`, creates a hosted agent version, waits until it is active, and stores `HOSTED_AGENT_PRINCIPAL_ID`.
3. `azd provision --no-prompt` runs again, because the agent identity did not exist before step 2. Bicep then gives it its Foundry and Search roles. All provision hooks run again too.
4. `voltrieve-entra assign-app-role` gives the agent identity `Dealer.Access`, with the same retry.

Until step 4 has propagated, hosted dealer tools fail. Sessions are bound to the agent version they started on, so conversations in flight stay on the old version until the API restarts or a call fails and the session is dropped.

### 4. Check it

```sh
uv run scripts/runbook.py
uv run tests/grounding/check.py
```

See [runbook.md](runbook.md).

## Redeploying

| Change | Command |
| --- | --- |
| API or dealer code, `agent_core` | `azd deploy api`, `azd deploy dealer` |
| SPA | `azd deploy web`, or `azd package web && scripts/deploy-web.sh` |
| Agents, including `agent_core` as used by the hosted agent | `scripts/deploy-agents.sh` |
| Infrastructure | `azd provision` |
| Documents | `azd provision` (the post-provision hook uploads and indexes) |

## Idle cost

Approximate:

| Resource | Idle cost |
| --- | --- |
| Azure AI Search Basic | About 75 USD a month |
| Container Registry Basic | About 5 USD a month |
| Log Analytics | Small, by ingestion |
| Container Apps | None when scaled to zero |
| Static Web App Free | None |
| Models | None: per token |
| Hosted agent | None: per active session |

Search is the cost that matters. Tear down when you are done.

## Before a demo

The API and the dealer scale to zero after 5 idle minutes. A cold start took 34 seconds for the API and 30 for the dealer in a measured run, which is far over the 10 second limit for the first token. `just warm-up` wakes everything and asks a real question on each backend. `just keep-warm` does the same, then pings `/healthz` every 2 minutes until Ctrl-C, which costs no tokens.

## Budget alert

The resource group has a budget named `voltrieve-monthly` of 990 SEK a month, which is about USD 100, because the subscription bills in SEK. It sends an email when actual cost goes over the budget. It was created by hand, so it is not part of `azd up`. An alert does not stop any spending, and cost data can lag by up to a day.

## Teardown

```sh
azd down --purge
```

`--purge` also removes the soft-deleted resources that would otherwise keep their names reserved.

**Entra objects survive teardown.** `azd` does not remove the app registrations or the tester, because hooks created them, not Bicep. To delete them:

```sh
UPN="$(azd env get-value TEST_USER_UPN)"
az ad user delete --id "$UPN"

for name in voltrieve-api voltrieve-cli voltrieve-web voltrieve-dealer; do
  az ad app delete --id "$(az ad app list --display-name "$name" --query '[0].id' -o tsv)"
done
```

Deleted applications stay in the Entra recycle bin for a while. These commands were not run in this project, so check the names first if the tenant has anything else called `voltrieve-*`. Whether the hosted agent's Entra identity goes away with the project was also not checked.

If you deploy again into the same azd environment after teardown, clear the stale agent identity first, or provision will try to assign roles to a principal that no longer exists:

```sh
azd env set HOSTED_AGENT_PRINCIPAL_ID ""
```

The tester password is printed again only if the account was deleted and is recreated.
