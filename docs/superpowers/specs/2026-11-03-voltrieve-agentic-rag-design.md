# Voltrieve: agentic RAG reference implementation on Azure

Design document, 2026-11-03. Status: draft for approval.

## 1. Intent

A clean-room reference implementation of agentic RAG on Azure, built from
nothing and reusing no code or tooling from earlier projects. It exists to
answer two questions with running code and visible logs rather than with
opinion:

1. **How do client-side tools coexist with a Foundry-based agentic RAG
   solution?** A Foundry prompt agent owns its tool loop and rejects a
   per-request `tools` list, so the documented RAG pattern breaks as soon as
   the caller has tools of its own (a camera that can set emissivity, a CLI
   that can beep). This project shows the three ways around that, each as a
   separate runnable backend, so their strengths and weaknesses can be seen
   side by side.
2. **Why define and host an agent in Microsoft Foundry at all?** Foundry
   hosting models is uncontroversial. Hosting the *agent* there is not: a web
   API can run the orchestration loop itself. The project makes concrete what
   Foundry adds on top (identity, tracing, publishing to Teams and Microsoft
   365 Copilot, governance), what you miss without it, and how much code the
   "do it yourself" path costs.

The immediate reason is a problem met in a live client system. This
implementation is the neutral ground on which to settle it, and later a
teaching sample.

## 2. Goals, non-goals, anti-goals

### Goals

- Three complete, independently runnable agent backends behind one Web API:
  prompt agent, own loop in the API, hosted agent. The clients cannot tell
  which one answered.
- A CLI client that declares its own tools per request, and a SPA client that
  declares none, both talking to the same API.
- A Web API protected by OAuth 2.0 with Entra ID as identity provider, with
  authorization enforced at API and tool level.
- One knowledge base and one knowledge source in Azure AI Search, built by
  hand from the primitives (data source, index, skillset, indexer) and then
  composed into a knowledge source and a knowledge base.
- A server-side tool that calls a separate sample web service (the Voltrieve
  dealer service), simulating an external system.
- Every hop visible: a live event timeline in both clients, structured logs
  in the API and the dealer service, and distributed traces with one
  correlation id from client to model and back.
- A written comparison, produced after all three backends run, that answers
  the two questions in section 1 with evidence from this code.
- Security as a default, not a layer: managed identities, RBAC, no API keys,
  no secrets in source, token validation done properly, documents treated as
  untrusted data.

### Non-goals

- Document-level (security-trimmed) retrieval. Authorization stops at API and
  tool level. The comparison should still note where each backend would take
  the user's identity if trimming were added.
- Actually publishing the agent to Teams or Microsoft 365 Copilot. The path is
  described and the prerequisites are shown; the final publishing step is out
  of scope.
- Evaluations, red-teaming pipelines, fine-tuning, multi-region, autoscaling,
  WAF, private networking. Mentioned in the comparison where relevant, not
  built.
- Mobile or embedded clients.
- Production-grade dealer service. It is a stub with in-memory data.

### Anti-goals (failure even if it works)

- Anything that hides what happens. A backend that answers correctly but
  whose tool calls, retrievals and relays cannot be followed in the logs is
  a failed backend.
- API keys anywhere, including "just for the demo".
- Clients that know which backend they talk to, or that contain
  backend-specific code paths.
- A comparison written from the docs instead of from running the sample.
- Reusing designs, prompts or code from earlier projects.

## 3. Constraints

- Azure, Microsoft Foundry and Azure AI Search are fixed. Everything else is
  open.
- Documents and UI text in English.
- Entra ID is the only identity provider.
- Low-cost SKUs throughout; this is a sample, not a service.
- Region: Sweden Central if every required feature is available there,
  otherwise West Europe. My call. The builder verifies model and feature
  availability before fixing it.
- Deployment runs in the author's own Entra tenant and subscription with
  full administrative rights. Scripts may create app registrations, grant
  admin consent, assign app roles and create a second test user unattended.
  No admin-checklist fallback is needed.
- No interim deliverable is required. Build order is free; the comparison is
  written once all three backends run.

## 4. The domain: Voltrieve

Voltrieve is a fictional EV maker. Fictional data makes grounding testable:
nothing about Voltrieve exists on the internet, so any correct fact the agent
produces must have come from our index, and any Voltrieve "fact" not in our
documents is a hallucination by definition.

### 4.1 Models

Five models on two shared platforms, with features that repeat with small
differences across models (so retrieval must find the right document) and a
few features unique to one model.

| Model | Segment | Platform | Battery (kWh) | WLTP range (km) | Peak charge (kW) | Towing (kg) | Drive |
|---|---|---|---|---|---|---|---|
| Voltrieve Spark | city car | V1 (400 V) | 42 | 310 | 95 | not rated | RWD |
| Voltrieve Lumen | hatchback | V1 (400 V) | 61 | 455 | 135 | 750 | RWD / AWD |
| Voltrieve Ragn | crossover | V2 (800 V) | 84 | 530 | 240 | 1 800 | AWD |
| Voltrieve Fjord | estate | V2 (800 V) | 84 | 575 | 240 | 2 100 | RWD / AWD |
| Voltrieve Atlas | large SUV | V2 (800 V) | 112 | 610 | 320 | 2 500 | AWD |

Figures are deliberately not copies of any real car. The builder may adjust
numbers for internal consistency but keeps these properties:

- Two models share a battery size (Ragn and Fjord, 84 kWh) but differ in
  range and towing, so "which 84 kWh model tows more" has one right answer.
- One feature exists on exactly one model (Atlas: 320 kW charging, 112 kWh).
- One capability is explicitly absent on one model (Spark: not rated for
  towing; no heat pump as standard).
- Software features are shared across the range with version differences
  (for example "Voltrieve Pilot" driver assistance: Pilot 2 on V1, Pilot 3
  on V2).
- Prices appear only in the buyer's guide, in SEK and EUR, so price questions
  depend on a specific document.

### 4.2 Documents

Eleven documents, generated by a script from a single structured data file
(YAML or JSON) so that every number in every document comes from one source
of truth and can be checked against agent answers automatically:

- Five **sales brochures**, one per model: persuasive, light on numbers,
  DOCX format.
- Five **technical specification and feature guides**, one per model: dense,
  exact numbers, charging curves as tables, option packs, software features,
  PDF format.
- One **buyer's guide** across the range: comparison tables, prices per
  market, option pack availability matrix, Markdown format.

Three formats so the indexing pipeline does real document cracking.

### 4.3 Deliberate test cases

The documents and the data file include planted cases, and the demo runbook
(section 10) asks about each:

- Shared-but-different: towing on Ragn vs Fjord.
- Unique: fastest charging model.
- Absent-by-design: Spark towing.
- Not in the documents at all: crash test ratings, battery warranty length,
  production location. The correct answer is "the documents don't say".
- Cross-document: cheapest AWD model (needs buyer's guide plus a spec guide).

### 4.4 The dealer service

A separate small HTTP service in the same fictional world, standing in for an
external system. In-memory data, three operations:

- `GET /stock?model=&city=` stock count per model per Swedish city.
- `GET /prices?market=` list price per model and market.
- `POST /test-drives` book a test drive (model, city, date, requester).

It requires a bearer token issued for its own Entra app registration. The
Web API calls it with its managed identity. It logs every request with the
inbound correlation id.

## 5. Architecture

```
 CLI (tools: yes)  ─┐                                  ┌─ Backend A: prompt agent (Foundry)
                    ├─ Entra ID OAuth ─► Web API ──────┼─ Backend B: own loop in the API
 SPA (tools: no)   ─┘                     │            └─ Backend C: hosted agent (Foundry)
                                          │                     │
                                          │                     ├─► Foundry model deployment
                                          │                     ├─► Azure AI Search knowledge base
                                          ├─► Dealer service    │       (knowledge source ─► index ◄─ indexer ◄─ skillset ◄─ blob)
                                          └─► App Insights ◄────┘
```

One Web API, three backends behind a single internal interface. All three
share: the clients, the API contract, the Entra configuration, the knowledge
base, the dealer service, the logging and tracing conventions.

### 5.1 Repository layout (my call)

```
infra/            Bicep modules and azd configuration
search/           JSON definitions and apply script for the AI Search objects
data/             Voltrieve source data file, document generator, generated docs
services/dealer/  The dealer web service
api/              The Web API, including the three backends
agents/           Prompt agent definitions and scripts; hosted agent packaging
clients/cli/      The CLI client
clients/web/      The SPA client
docs/             Runbook, comparison write-up, this design
```

## 6. Identity, authentication and authorization

### 6.1 Entra app registrations

Three app registrations in the user's tenant, created by a script run as an
`azd` pre-provision hook (Bicep cannot create them without the Graph
extension; a script is simpler and visible). Object ids and client ids flow
into Bicep parameters and app settings.

- **voltrieve-api**: exposes scope `access_as_user`. Defines app roles
  `Chat.User` (may chat and use read-only tools) and `TestDrive.Book` (may
  have the agent book test drives). Users are assigned roles in Entra; the
  demo script assigns both to the deploying user and creates a second test
  user (`voltrieve-tester`) holding only `Chat.User`, for runbook step 9.
- **voltrieve-cli**: public client, redirect for interactive browser flow and
  device code flow enabled. Requests `voltrieve-api/access_as_user`.
- **voltrieve-web**: SPA platform, PKCE, redirect to the Static Web App URL
  and `http://localhost:5173`. Requests `voltrieve-api/access_as_user`.
- **voltrieve-dealer**: exposes an application permission `Dealer.Access`,
  granted to the Web API's managed identity.

### 6.2 Token validation in the Web API

- Validate signature against the tenant's JWKS (cached, refreshed on key
  rollover), issuer, audience (the API's application id URI or client id),
  expiry and not-before.
- Require scope `access_as_user` and role `Chat.User` for any chat endpoint.
- Never log tokens. Log `oid`, `preferred_username` and roles only.

### 6.3 Authorization at API and tool level

- API level: no valid token, no scope or no `Chat.User` role gives 401/403
  with no further processing.
- Tool level: every server tool declares the role it needs. The dealer
  booking tool requires `TestDrive.Book`. A model request to call a tool the
  user is not allowed to call is not executed; the API returns a tool result
  saying the action is not permitted for this user, logs an `authorization
  denied` event, and the agent tells the user. This is demonstrated in the
  runbook with the second test user.
- Client tools are always allowed to be *requested* by the model; whether
  they run is the client's decision. The API never executes a client tool.
- Backend-specific: in backend A, tools are enforced the same way, in the
  relay layer, since the agent definition cannot see user roles. The
  comparison should call this out.

### 6.4 Service-to-service

- Web API to Foundry: system-assigned managed identity, role Azure AI User
  on the Foundry project.
- Web API to AI Search: managed identity, Search Index Data Reader.
- Web API to dealer service: managed identity token for the dealer
  app registration.
- AI Search to Storage: search service managed identity, Storage Blob Data
  Reader.
- AI Search to Foundry (embedding skill and knowledge base model): search
  service managed identity, Cognitive Services OpenAI User.
- Hosted agent to everything: its own agent identity, same roles as the
  Web API where it needs them.

No connection strings, no keys. Local development uses the developer's
Azure CLI credential through `DefaultAzureCredential`.

### 6.5 User identity in backend C (my call)

In backend C the hosted agent, not the Web API, executes server tools, so it
needs the user's `oid` and roles to enforce tool-level authorization and to
record the requester on a booking. The Web API forwards a `user` object
(`oid`, `preferred_username`, `roles`) in the request body it sends to the
hosted agent. The hosted agent trusts those claims because only the Web
API's managed identity holds the role that allows invoking it; the hosted
agent rejects requests whose caller is not the Web API. If the Responses
protocol cannot carry such a field, this pushes backend C to the
Invocations protocol (see 9.3), which is acceptable.

Alternatives considered and left for the comparison write-up to discuss,
not to build: an on-behalf-of token exchange to a dedicated hosted-agent
app registration (the right answer once document-level trimming is wanted),
and having the hosted agent return server tool calls to the Web API for
execution (keeps authorization in one place but breaks "same core, only the
host differs").

## 7. Azure AI Search

Built by hand, in order, each object a committed JSON file applied by a
script using the REST API with the developer's Entra token. The order itself
is part of what the sample teaches:

1. **Data source**: Azure Blob container `voltrieve-docs`, managed identity
   authentication.
2. **Index**: fields for id, parent document, title, model name (filterable),
   document type (brochure, spec, guide; filterable), chunk text, chunk
   vector, page or section. Vector search profile with HNSW and an Azure
   OpenAI vectorizer. A semantic configuration (required by knowledge
   sources).
3. **Skillset**: text split (pages, with overlap), Azure OpenAI embedding
   skill, index projections writing one search document per chunk. Document
   cracking of DOCX, PDF and Markdown is done by the indexer itself.
4. **Indexer**: binds data source, skillset and index; runs on demand.
5. **Knowledge source** of type `searchIndex` wrapping the index, with the
   semantic configuration and the fields to return.
6. **Knowledge base** over that knowledge source, with the Foundry model
   deployment set for query planning, and `knowledgeRetrieval` billing left
   at the default unless the builder finds a feature needs otherwise.

API version: the builder uses the GA agentic retrieval version (2026-04-01 at
time of writing) unless a required capability only exists in the newest
preview, and records which features forced a preview version. My call.

The knowledge base is reached two ways, and the sample shows both:

- From backends B and C: our own `search_voltrieve_docs` function tool calls
  the knowledge base `retrieve` endpoint and returns the grounding chunks with
  references, so citations and the retrieval activity are visible in the
  logs.
- From backend A: the knowledge base's MCP endpoint attached as an MCP tool
  on the prompt agent through a project connection, which is the documented
  Foundry IQ pattern.

## 8. The Web API

Python, FastAPI. My call. The stack choice is a default, not a requirement:
the design holds for .NET as well.

### 8.1 Contract

All backends implement the same contract. The clients only know this
contract.

`POST /chat`

```json
{
  "conversation_id": "optional, omitted on first turn",
  "message": "user text",
  "client_tools": [ { "name": "...", "description": "...", "parameters": { JSON schema } } ]
}
```

`client_tools` is optional. The SPA never sends it. The CLI sends its tool
list on every turn.

`POST /chat/tool-results`

```json
{
  "conversation_id": "...",
  "turn_id": "...",
  "results": [ { "call_id": "...", "output": "string or JSON" } ]
}
```

Both endpoints respond with a server-sent event stream. Event types:

- `trace`: `{ step, component, detail, elapsed_ms }` one per visible hop
  (token validated, backend selected, model called, retrieval started,
  retrieval returned N chunks, server tool called, server tool returned,
  client tool requested, authorization denied, and so on).
- `delta`: streamed answer text.
- `client_tool_calls`: `{ turn_id, calls: [ { call_id, name, arguments } ] }`
  The stream ends after this event. The client executes the calls and posts
  to `/chat/tool-results`, which continues the same turn.
- `done`: `{ conversation_id, turn_id, backend, usage }`.
- `error`: `{ code, message }` with no internal detail.

Backend selection: an app setting `AGENT_BACKEND` with values `prompt`,
`loop`, `hosted` sets the default. A request header `X-Agent-Backend` may
override it so all three can be compared live without redeploying. The
backend used is always reported in `trace` and `done`. My call.

### 8.2 Backend interface

One internal interface, three implementations:

```
run_turn(user, conversation_id, message, client_tools, emit) -> TurnResult
continue_turn(user, conversation_id, turn_id, results, emit) -> TurnResult
```

`emit` publishes trace and delta events. Server tools and their role
requirements are registered once and handed to each backend.

### 8.3 Server tools

- `search_voltrieve_docs(query)`: knowledge base retrieve (backends B and C).
- `check_stock(model, city)`: dealer service.
- `get_prices(market)`: dealer service.
- `book_test_drive(model, city, date)`: dealer service, requires
  `TestDrive.Book`, passes the user's `oid` as requester.

### 8.4 Conversation state

Server-side, in Foundry's Conversations API for all three backends, so the
clients only hold a `conversation_id`. My call. If the hosted agent's state
store turns out to be the natural home for backend C, the builder may use it
and note the difference in the comparison.

### 8.5 Logging and tracing

- Structured JSON logs to stdout in the API and the dealer service, with
  `correlation_id`, `conversation_id`, `turn_id`, `backend`, `user_oid`.
- OpenTelemetry with the Azure Monitor exporter to the project's
  Application Insights; W3C trace context propagated to the dealer service
  and into Foundry calls so one trace spans client request to model call.
- Foundry's own tracing (prompt agent and hosted agent) lands in the same
  Application Insights, so the comparison can show what each backend traces
  for free and what the own-loop backend must emit itself.
- Prompt and tool payloads are logged at debug level only, truncated, and
  never include tokens or credentials.

### 8.6 Security details

- CORS restricted to the SPA origin(s).
- Request body size limits; `client_tools` capped in count and schema size.
- Tool arguments produced by the model are validated against the declared
  JSON schema before any tool runs.
- Retrieved chunks and tool results are passed to the model as data, with a
  system prompt that tells the model so. The comparison notes that this is
  mitigation, not prevention.
- Foundry project content filters stay on in all backends.
- Dependency pinning and a lock file; container runs as non-root.

## 9. The three backends

Each backend has its own section in the comparison write-up with the same
headings: how client tools work, how the knowledge base is attached, what
is visible in the logs, what Foundry provides, what the code must provide,
and what breaks.

### 9.1 Backend A: prompt agent in Foundry

- Agent defined in the Foundry project through the SDK by a script in
  `agents/prompt/`, versioned. Instructions, the knowledge base as an MCP
  tool through a project connection, the dealer operations as function
  tools.
- Client tools must be in the agent definition, so the script creates two
  agent versions (or two agents, builder's call): one with the CLI's tools
  as function tools and one without, for the SPA. The Web API picks by
  whether the request carries `client_tools`, and refuses with a clear
  error if a client sends tools not in the agent definition.
- The Web API drives the agent through the Responses API with an agent
  reference. When the agent returns a function call for a dealer tool the
  API executes it and submits the output; for a client tool it emits
  `client_tool_calls` and continues when `/chat/tool-results` arrives,
  within the run expiry window.
- Demonstrated explicitly: the `400 invalid_payload: tools not allowed when
  agent is specified` response when `tools` is passed alongside the agent
  reference. The runbook triggers it on purpose, and the trace shows it.

### 9.2 Backend B: own loop in the Web API

- The API calls the project's Responses endpoint directly against the model
  deployment. On every turn the `tools` array is built from the server tools
  the user may call plus the `client_tools` from the request.
- The loop: call model; if it returns function calls for server tools, run
  them and call again; if it returns function calls for client tools, emit
  them and pause the turn; continue on `/chat/tool-results`.
- The shared agent core lives in a package used unchanged by backend C.
  Implementation with Microsoft Agent Framework for Python is my preference
  so the same code can be hosted in Foundry; the builder falls back to the
  plain OpenAI SDK if Agent Framework cannot express "declared but not
  executed here" client tools cleanly, and records why.
- This backend is the one that solves the client-tool problem with no
  workaround, and the comparison must list what it gives up (see section
  11).

### 9.3 Backend C: hosted agent in Foundry

- The same agent core from backend B, packaged as a container and deployed
  as a Foundry hosted agent with its own agent identity.
- The Web API forwards the turn to the hosted agent and streams back. The
  builder verifies whether the hosted agent's Responses protocol forwards a
  caller-supplied `tools` list and can carry the `user` object from 6.5; if
  it does, that is the path. If not, the agent is exposed over the
  Invocations protocol with a request body that carries `client_tools` and
  `user` explicitly. Either way the finding is recorded; it is one of the
  answers this project exists to produce.
- Shows what hosting buys: agent identity, automatic tracing, versions,
  session isolation, the Activity protocol bridge toward Teams (described,
  not published).

## 10. Clients

### 10.1 CLI

Python, Typer and Rich. My call.

- Sign-in through MSAL with interactive browser flow, device code as a
  fallback flag, token cache on disk in the user's profile with OS
  protection where available.
- Declares three local tools on every request:
  - `make_noise(times)`: terminal bell `times` times (capped at 10).
  - `get_local_time()`: the machine's local time and timezone.
  - `show_banner(text)`: prints a highlighted banner in the terminal.
- Renders the chat in one panel and the live `trace` events in a second
  panel, timestamped, so the audience can watch retrievals, tool calls and
  relays as they happen.
- `--backend prompt|loop|hosted` sets the `X-Agent-Backend` header.
- Executes `client_tool_calls` locally, prints what it did, posts results,
  and keeps rendering the continued stream.

### 10.2 SPA

Vite, React, TypeScript, MSAL.js with PKCE. My call. Deployed to Azure
Static Web Apps.

- Chat view plus an event timeline side panel fed by the same `trace`
  events.
- Backend selector in the header, same header mechanism as the CLI.
- Sends no `client_tools`. When a user asks it to beep, the agent explains
  it has no such tool in this client. That contrast is the point.
- No secrets; the API URL and client id come from build-time configuration.

## 11. The comparison write-up

`docs/why-foundry.md`, written after all three backends run, with evidence
from logs and traces in this repository. It must answer, in this order:

1. What happened with client tools in each backend, with the actual error
   from backend A and the actual request shapes from B and C.
2. What Foundry provided in each backend without code: identity, tracing,
   conversation storage, content filters, versioning, publishing channels,
   registry and governance hooks.
3. What the own-loop backend had to implement itself, measured in lines of
   code and listed by concern, and what it cannot get at all (publishing to
   Teams and Microsoft 365 Copilot, a managed agent identity, registry
   entries).
4. Whether agentic RAG without Foundry agents is hard: how many lines the
   loop is, where the complexity really sits (tool relay, state, tracing,
   safety), and whether any of it is Foundry-specific.
5. Hosted agent versus custom code in a web API: the same code in both
   places, so the difference is who runs it, with what identity, with what
   observability, reachable through which channels, at what operational
   cost.
6. A recommendation, stated as conditions: when to pick each backend.

## 12. Infrastructure and deployment

- Bicep, deployed with `azd up`. Resources: resource group, Foundry resource
  and project, one chat model deployment and one embedding model deployment,
  Azure AI Search (Basic, semantic ranker enabled), Storage account,
  Container Apps environment with the Web API and the dealer service,
  Static Web App for the SPA, Log Analytics and Application Insights. Role
  assignments as in section 6.4.
- `azd` hooks: pre-provision creates or updates the Entra app registrations
  and exports their ids; post-provision uploads documents, applies the
  search objects in order, runs the indexer, creates the prompt agent
  versions, and deploys the hosted agent.
- Model deployments: a current GPT-class chat model and a current text
  embedding model available in the chosen region, selected by the builder.
- Local run: the API, dealer service, CLI and SPA all run locally against
  the deployed Azure resources using the developer's Azure CLI identity;
  documented in the runbook.

## 13. Demo runbook

`docs/runbook.md` walks through, for each backend in turn, with expected
trace events listed next to each step:

1. Sign in from the CLI; show the token's roles in the trace.
2. "What is the towing capacity of the Fjord?" (grounded, single document).
3. "Which of the 84 kWh models tows more?" (shared-but-different).
4. "Which Voltrieve charges fastest?" (unique feature).
5. "Can the Spark tow a trailer?" (absent by design).
6. "What is the Lumen's Euro NCAP rating?" (not in documents; expect the
   model to say so).
7. "What is the cheapest AWD Voltrieve in Sweden?" (cross-document).
8. "Is the Atlas in stock in Göteborg?" (server tool to dealer service).
9. "Book me a test drive of the Atlas in Göteborg on Saturday." as the
   full-role user (succeeds) and as the `Chat.User`-only user (authorization
   denied event, polite refusal).
10. "Beep three times when you have the answer to question 2." (client tool
    in the CLI; in the SPA the agent explains it cannot).
11. Backend A only: send client tools to the agent and show the 400.
12. Open Application Insights and follow one correlation id end to end.

## 14. Testing

- Unit tests: token validation (good, expired, wrong audience, missing role),
  tool authorization, JSON schema validation of model-produced arguments,
  the loop in backend B against a fake model that scripts tool calls, the
  SSE event framing.
- Contract tests: all three backends against the same scripted conversation
  produce the same event sequence shape.
- Grounding check: a script asks each backend the runbook's factual
  questions and compares the answers against the Voltrieve data file.
- Smoke test after `azd up`: health endpoints, indexer status, one chat turn
  per backend.

## 15. Left to the builder

- Exact library versions, model deployment names, container base images.
- Document generation details, typography, how charging curves are tabled.
- Index field names, chunk sizes, overlap, vector dimensions.
- The system prompt wording (within the constraints in 8.6).
- CLI and SPA visual design.
- Whether backend A uses two agents or two versions of one agent.
- Which hosted agent protocol is used, once verified (9.3).
- Test framework choices.

## 16. Open items recorded during research (for the builder's attention)

- The `400` rejection of `tools` with an agent reference is documented in a
  Microsoft GitHub issue, not on Learn. Confirm current behaviour against
  the live service and record the exact response.
- The 10-minute run expiry for pending tool outputs comes from older
  documentation. Measure it in backend A.
- Whether an MCP tool with a project connection id works outside an agent
  definition is not confirmed in the docs. Backend B does not depend on it
  (it uses the retrieve endpoint), but note the answer if found.
- Hosted agents are generally available while the Python hosting package is
  prerelease; pin versions and record which.
