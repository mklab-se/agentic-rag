# Decisions

What was decided, why, and what was found on the live service. Dated facts are from 2026-11-04 unless noted. The comparison is in [why-foundry.md](why-foundry.md).

## API versions

### Latest versions everywhere, including preview

The user decided to use the latest API versions, preview included. This replaced an earlier plan to stay on GA.

| Surface | Version |
| --- | --- |
| Search data plane (REST) | `2026-08-01-preview` |
| Knowledge base MCP endpoint | `2026-08-01-preview` |
| Search management (Bicep) | `2026-09-01-preview` |
| `Microsoft.CognitiveServices/*` | `2026-09-15-preview` |
| `Microsoft.App/*` | `2026-07-01` |
| `Microsoft.Storage/*` | `2026-09-01` |
| `Microsoft.ContainerRegistry/registries` | `2026-09-01-preview` |
| `Microsoft.OperationalInsights/workspaces` | `2026-03-01` |
| `Microsoft.Web/staticSites` | `2025-03-01` |
| `Microsoft.ManagedIdentity/userAssignedIdentities` | `2024-11-30` |
| `Microsoft.Insights/components` | `2020-02-02` |

### Search management stepped back from the newest listed version

`2026-11-01` is listed in the docs but was not live in France Central, so Bicep uses `2026-09-01-preview`, the newest the service accepted.

### Bicep BCP081 warnings are expected

The lint reports BCP081 ("does not have types available") for `Microsoft.CognitiveServices/*@2026-09-15-preview` and `Microsoft.Storage/*@2026-09-01`. These versions are newer than Bicep's type data. The warnings do not block deployment, but Bicep cannot validate those resources' properties before deploying, so errors there appear at deployment time. `infra/tests/test_bicep.sh` does not fail on them.

## Search

### Query planning on

The knowledge base has the chat model in `models` with `retrievalReasoningEffort` low. On `2026-08-01-preview` this produced `modelQueryPlanning` activity and three sub-queries for one question. GA `2026-04-01` cannot plan with a model for `searchIndex` sources. The search service identity needs Cognitive Services User on Foundry for this. Output mode is `extractiveData`: the agent writes the answer.

### Retrieve request shape

The retrieve body uses `messages` and `maxOutputSize`. Live testing settled this: the docs also list `maxOutputSizeInTokens`, but the service wanted `maxOutputSize`.

### No page or section field in the chunk index

The skillset splits extracted text into character-based chunks, and extraction gives no reliable page or section for Markdown, DOCX and PDF alike. A field would be wrong or empty for some formats. Citations use the document title and the chunk content.

## Regions

- Sweden Central holds everything except the two below.
- Azure AI Search is in France Central (`AZURE_SEARCH_LOCATION`). Sweden Central and West Europe were flagged as not accepting new Search services. The cross-region placement costs a little latency.
- The Static Web App metadata is in East US 2. West Europe rejected new Static Web Apps. The content is global, so users are not affected.

## Models

- Chat: `gpt-5.4-mini` version `2026-03-17`, GlobalStandard, capacity 50. The agents later moved to `gpt-6.1-terra`: see below.
- Embeddings: `text-embedding-3-large` version 1, GlobalStandard, capacity 10.
- Capacity 10 on chat broke multi-question runs with rate limits. On pay-per-token, capacity is a cap, not a cost, so it was raised to 50.

## Agent core

### Plain Responses loop instead of Agent Framework

The design preferred Microsoft Agent Framework, with the plain OpenAI SDK as the stated fallback. `agent_core` uses the fallback: a plain loop over the Responses API. Pausing for client tools and emitting trace events are first class in the loop, and the comparison needs an honest line count. Agent Framework was not tried, so this does not show that it cannot do the job. The choice is reversible.

### Server tools are listed whatever the role

`ToolSet.definitions` offers every server tool, and `execute` enforces roles. A denied call must be a visible `authorization_denied` event, and a prompt agent cannot hide tools per user anyway. This overrides the plan text.

### Hosts emit `done`

The core never emits `done`, because only the host knows the backend. `TurnOutcome` carries `failed` status and `client_call_ids`, and terminal events stay single.

### Client tool calls carry the conversation id

`client_tool_calls` includes `conversation_id`, amending design section 8.1. A first-turn client has no other way to learn it.

## Turn state

### In-process turn state and `maxReplicas` 1

Paused turns live in a dict in the API process, so the API runs with `maxReplicas` 1. A restart loses paused turns and the client gets `turn_expired`. This is acceptable for a reference implementation at low cost. Running more replicas needs a shared store.

The pause limit is 15 minutes. A turn survives a client disconnect, and SSE sends a keep-alive every 15 seconds, because Container Apps closes connections idle for 240 seconds.

### Conversation owner stored in Foundry metadata

The owner `oid` goes into the Foundry conversation's metadata when the conversation is created. The in-process map is a bounded cache (1000 conversations). Otherwise scale to zero would break every conversation. Reading it back after a real restart is not in the recorded evidence.

A foreign conversation gets the same 403 as an unknown one, so ids cannot be probed. A foreign paused turn gets the same `turn_expired` answer as an unknown one, and is left untouched for its owner. If Foundry cannot be read at all, the lookup answers 503: an outage is not an unknown conversation.

### Stateless repair

A conversation touched first by a process, or left dirty by a failure, is repaired before use: function calls without an output get a synthetic one. This costs one extra list call per conversation per process. It covers lost pauses, failed closes and restarts.

### Concurrent turns

A second message while a turn is running gets 409 `turn_in_progress`. It is the simplest correct behaviour, and the client must retry.

## Backends

### A: two agents

Tools are fixed in the definition, so there are two agents, `voltrieve-prompt-cli` and `voltrieve-prompt-web`. The API picks by whether the request has `client_tools`, and refers to the agent by name, which gives the latest version.

### C: Invocations protocol

Measured: the hosted Responses protocol drops caller `tools` and `metadata` (they arrive as `None`). Invocations forwards arbitrary JSON, SSE and `traceparent`.

### C: caller check fails closed

The agent accepts only the API's managed identity, read from `x-ms-original-subject`. With `ALLOWED_CALLER_OID` empty, every request is refused. `ALLOW_ANY_CALLER=true` is for local use only. The operator must keep `API_PRINCIPAL_ID` correct.

### C: lost stream grace

When the stream to the hosted agent breaks, the conversation stays blocked for 120 seconds and is then repaired. This avoids racing a detached turn. The user can wait up to two minutes after a dropped connection.

## Clients and observability

### Backends are indistinguishable to clients

The prompt backend rewrites Foundry citation markers (`【5:0†file】` becomes ` (file)`, `【4:0†source】` is dropped) before text reaches a client, holding a marker back across deltas until it closes. The fact checks in `scripts/voltrieve_facts.py` no longer strip markers, so they judge what a client sees. The error code for a failed hosted call is `agent_unavailable`, not a name that gives the backend away.

### Client tool arguments are validated, and schemas may not use `$ref`

A client declares the schema of its tools, and the model is not bound to it. `ToolSet.validate_client` checks each call before it is forwarded; a failing call is answered with the error and never reaches the client. The API rejects `$ref` and `$dynamicRef` anywhere in a client schema (422), so the validator can never be made to fetch a URL.

### One correlation id per turn

The CLI and the SPA generate an id for each turn and send it as `X-Correlation-Id` on every request of the turn, and show it. A client tool turn is two requests under one id. Every hop of a turn is a log line and a span event, with arguments and result previews at debug level only.

### The CLI reads the azd environment

The CLI maps the azd keys (`API_URL`, `TENANT_ID`, `CLI_CLIENT_ID`, `API_CLIENT_ID`) itself; `VOLTRIEVE_*` variables override them. `voltrieve login` shows the account picker every time and `voltrieve logout` forgets the cache. Control characters in model text are removed before they reach the terminal.

### Dates follow the dealer

`get_current_date` and the dealer's "future date" rule use Europe/Stockholm, not the host's clock: containers run in UTC, which is a day behind for the first hours after midnight in Sweden.

## Identity

### Azure CLI pre-authorized on the API

`voltrieve-api` lists the Azure CLI as a pre-authorized application for `access_as_user`, so scripts can get tokens without an interactive login. Tokens still need the `Chat.User` role. This slightly widens who can mint tokens for the API in the tenant.

### Roles live in Bicep

Direct `az role assignment` was blocked by a safety check in this environment. Every Azure role is declared in Bicep, by GUID, at the target resource. App roles such as `Dealer.Access` go through Graph in the hook and scripts.

### Application Insights connection string

It is an ingestion identifier, not a secret: it only allows sending telemetry. It is set as a plain value. Everything else uses Entra tokens.

## Deployment

- Provision runs before package, because the web build needs provision outputs.
- The SPA upload runs in Docker on Apple Silicon. The SWA CLI's client is x86, and installing Rosetta is a system change.
- The root `.dockerignore` is an allow-list, because `azd` tar failed on files changing during the archive.
- The search smoke test runs in `postup`, so a miss cannot block a deployment. `scripts/smoke.py` runs at the end of `scripts/deploy-agents.sh` and covers the API, the dealer, the indexer and one turn per backend.
- The dealer client timeout is 45 seconds, because the dealer scales to zero. The earlier 15 seconds caused one grounding miss.

## Live findings

- Prompt agent with `agent_reference` plus `tools`: `400 Not allowed when agent is specified.`
- Responses with `conversation` plus per-request `tools` works. `function_call_output` works with a model and with `agent_reference`.
- Prompt agent: the knowledge base attaches by MCP through a `RemoteTool` connection with `ProjectManagedIdentity`. The result has no references or activity, and citations appear as `【5:0†file】` markers, which the API rewrites before they reach a client. Roles can only be enforced in the relay in the API.
- Hosted: the gateway replaces `x-ms-original-subject`. A forged request as the deployer got 403 from the handler.
- Hosted: each agent has an Entra identity (`instance_identity.principal_id`), stable across versions.
- Hosted: the first call on a new session is slow, a broken image gives `session_not_ready`, sessions bind to one version, the idle timeout minimum is 120 seconds, and billing is for active sessions only.
- Hosted deployment needs a `linux/amd64` image, Foundry Project Manager, and registry pull roles for the project identity. Search and dealer roles for the agent identity come after that identity exists, so a second provision is needed.
- Grounding, 30 questions over 3 backends: 30 passed on the final build (`docs/evidence/grounding.txt`). An early run had 28: a dealer cold-start timeout, fixed with a 45 second timeout, and one wrong answer.
- "Cheapest AWD in Sweden" repeated 6 times per backend: 18 of 18 right at reasoning effort medium (`docs/evidence/cross-document-repeat.txt`). At the default effort it was 13, 11 and 15 of 18 on three builds, with wrong answers treating AWD-only models as the only AWD models. An added instruction did not help and was removed. Effort is set in `voltrieve_agent.model.REASONING_EFFORT`, for the Responses call and for the prompt agents' definitions alike.
- Rate limits: Foundry reports them mid-stream, so SDK retries never see them. `ResponsesModelClient` retries up to 3 times before output starts. The chat deployment cap is 150 (150k tokens a minute); it is a limit, not a cost. Lower caps caused `model_error` in burst runs.
- Paused turn abandoned, and conversation resumed after 420 seconds idle so the API scaled to zero: passed on all three backends, with `turn_abandoned` and `conversation_repaired` in the trace. `docs/evidence/repair.txt`.
- One trace id spans the API, Foundry, the hosted agent and the dealer. Foundry adds its own `responsesapi` spans for prompt and hosted agents, and an `agentsv2` request for hosted. The direct loop gets none of these. `docs/evidence/application-insights.txt`.
- `scripts/denied_demo.py` on `loop` gave `authorization_denied` and a polite refusal (`docs/evidence/authorization-denied.txt`).

### Second knowledge base

Spare parts are a separate knowledge base with its own container, index, indexer and knowledge source, not a second source in `voltrieve-kb`. A knowledge base with both sources let the search planner route, and it used only the parts source in 3 of 3 runs.

The service guide sits in the documents base and has no article numbers. The catalogs have no procedures. This makes the question that needs both real, instead of a test written to pass.

Every catalog row names its vehicle, because search returns chunks and a row must make sense without its heading. Parts search uses an overlap of 200 characters instead of 500, since rows stand alone.

### Parallel tools

Reads of one model response run together. A tool with `concurrent=False` waits for them and runs alone, so a booking never races a read. Outputs reach the model in call order, whichever finished first.

### No router step

A separate planning call would add a model round trip to every turn, to do what the first model call does anyway. The routing check found no call in vain without one.

### Follow-up search for what the first search could not know

After a job search, the agent checks each component against the catalog results and searches again for the rest. It costs a third step on some turns. It does not always fire: in the final run brake fluid was still missing from 4 of 36 job answers on the own loop and hosted agent.

### Search retries on 429

A retrieve spends model tokens on query planning, so a busy deployment answers `429`. `KnowledgeBase` retries twice, after 10 and 20 seconds. Other failures go straight to the model as a tool error.

### The deployment script refreshes search as well

`scripts/deploy-agents.sh` reinstalls `voltrieve-search` next to `voltrieve-agent-core`. Without it the prompt agents failed on a stale copy, and the agents stayed on the previous version.

### Curated answers in the model's first call

The tool list costs a few hundred tokens and no call. A check in front of the model, or a search on every turn, would make every question pay for answers that a few need. An embedding match in the API would be faster for a curated question but cannot see the conversation, and it could match "the phone number to the Stockholm dealer". A handler returns `FinalAnswer`, a `str` subclass, so the loop can skip the second model call without any change to the tool contract. Errors stay plain text and go to the model. The short cut only fires when the tool is the only call of the first model response. The first live run showed why: the prompt agent called the tool in 11 of 12 two-base job questions on its way to the searches, the same habit `prompt-extra-steps.txt` shows with dealer tools, and one brake question ended with the phone number. Genuine curated questions chose it in the first response in 81 of 81 runs. After the fix the prompt agent still made the needless call in 7 of 12 job questions, but none ended early: 117 of 117 article numbers were found, and curated questions stayed at 81 of 81. If writing the answer to the conversation fails, the turn fails with `model_error` before any text is sent, and the conversation is repaired on next use.

### Prompt agents get their own sentence on searching

The instruction "call them all in the same step" made the prompt agent emit two parallel function calls before searching, because it cannot run MCP searches in parallel: 11 of 12 first responses. `parallel_tool_calls=False` on the request also stopped it, in 4 of 4 runs, but it would make a mixed curated question end early, so the instructions differ instead. Search, then catalog, and no other tool first: 0 of 7 first responses, then 1 of 27 job runs in the live checks.

### All backends run gpt-6.1-terra

Speed decides as long as quality holds. `gpt-6.1-terra` had the fewest turns over 10 seconds to the first token, or tied for the fewest, on every backend, at about the cost of `gpt-5.4-mini`. Search planning stays on `gpt-5.4-mini`, because Search refuses GPT-6 models. So there are two chat deployments, which also stops the agent and the planner sharing a token limit. The figures are in `docs/model-comparison.md`.

### Brake fluid is listed in the brake catalog too

All remaining article misses were brake fluid, which only sat among the service items, so a search for brake parts did not reach it. The brake catalog now has a section for consumables, and all 111 article numbers were found on all three backends. Regenerating also brought the catalog in line with the generator: 429 parts, and new article numbers from the old 433.

## Not recorded or not verified

- Interactive SPA sign-in, and a real browser sign-in with `voltrieve login` (tested against a fake MSAL application).
- A real sign-in as the tester. The denied case ran with a fake validator.
- Publishing to Teams and Microsoft 365.
- Cold-start figures. Whole turn times are in `docs/why-foundry.md` section 6, measured from one laptop.
- Whether `alwaysQuerySource` would make one knowledge base cover both sources.
- The 10 minute run expiry from older documentation.
- Whether an MCP tool with a project connection works outside an agent definition.
- Indexer duration, final item counts, how long role propagation retries waited, and smoke test scores. The first deployment did not keep these.
