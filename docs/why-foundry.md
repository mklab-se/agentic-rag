# Why Foundry, and how client tools fit

Written after all three backends ran live on 2026-11-04 (Sweden Central project, `gpt-5.4-mini`). Evidence is in `docs/evidence/`. Where something was not tried, this document says "not tested".

## Short answer

A Foundry prompt agent owns its tool list: sending `tools` with an agent reference returns `400 Not allowed when agent is specified.`
So client tools must already be in the agent definition, which only works for a fixed, known list.
The Responses API with a model instead of an agent accepts per-request tools, so an own loop in a web API solves it directly.
A hosted agent can run that same loop, but its Responses protocol dropped caller tools, so it needs Invocations and a custom contract.
All three ran the same runbook. Answer quality matched: 30 of 30 grounding questions on all hosts once reasoning effort was raised, which mattered more than the host. They differed in how much the trace shows.
Agentic RAG without Foundry agents is not hard: the loop is 252 lines. The hard part is pausing and repairing turns, which every backend needs.
Foundry agents add a managed identity, versions and a path to Teams and Microsoft 365. Publishing was not exercised here.
Two knowledge bases are chosen equally well on every host, with no call in vain, but only the own loop and the hosted agent run them together (section 6).
Recommendation: own loop when clients bring tools, hosted agent when you also need agent identity or publishing, prompt agent when tools are fixed.

## 1. What happened with client tools

All three backends share one client contract. The CLI sends its tools on every turn, the SPA sends none:

```json
POST /chat
{ "conversation_id": "optional", "message": "user text",
  "client_tools": [ { "name": "make_noise", "description": "...", "parameters": { } } ] }
```

The stream pauses with `client_tool_calls` (`turn_id`, `conversation_id`, `calls`). The client runs the calls and continues the same turn:

```json
POST /chat/tool-results
{ "conversation_id": "...", "turn_id": "...",
  "results": [ { "call_id": "...", "output": "Rang the terminal bell." } ] }
```

Runbook step 10 ("Beep three times when you have the answer to question 2.") passed on all three backends: `make_noise` was requested with `{"times":3}` and the turn continued after the result.

### Backend A: prompt agent

Sending tools with an agent reference, from `agents/prompt/demo_rejection.py`:

```python
client.responses.create(
    input="Hello",
    tools=[tool],
    extra_body={"agent_reference": {"name": agent, "type": "agent_reference"}},
)
```

The answer, verbatim from `docs/evidence/prompt-agent-rejection.txt`:

```text
400 invalid_payload: Error code: 400 - Not allowed when agent is specified.
```

The request that works carries no model, instructions or tools (`agent_core/.../model.py`):

```python
client.responses.create(
    conversation=conversation,
    input=input,
    extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
    stream=True,
)
```

So the tools go into the definition, and there are two agents: `voltrieve-prompt-cli` with the CLI's three tools and `voltrieve-prompt-web` without them. The API picks one by whether the request carries `client_tools`. A tool outside the definition never reaches Foundry: the API answers with the `unsupported_client_tool` error (runbook step 11).

Function calls still come back to the caller. Dealer tools and client tools are function tools on the agent, so the API runs the dealer calls and relays client calls. Sending `function_call_output` with `agent_reference` plus `conversation` works. A prompt agent therefore does not remove the relay: backend A reuses the same loop as backend B.

### Backend B: own loop

Responses with a conversation and per-request tools works (`agent_core/.../model.py`):

```python
client.responses.create(
    model=model,
    instructions=instructions,
    conversation=conversation,
    input=input,        # text, or function_call_output items
    tools=tools,        # server tools plus this request's client_tools
    stream=True,
)
```

There is no workaround. The tool list is rebuilt on every turn, and a function call whose name is a client tool pauses the turn.

### Backend C: hosted agent

The first try was the hosted agent's Responses protocol. Caller `tools` and `metadata` arrived in the agent as `None`: they were dropped without an error. The Invocations protocol forwards arbitrary JSON, SSE and `traceparent`, so backend C uses that. The request is ours, not an OpenAI shape (`api/app/backends/hosted.py`):

```text
POST {project}/agents/voltrieve-hosted/endpoint/protocols/invocations?api-version=v1[&agent_session_id=...]
Authorization: Bearer <token for https://ai.azure.com/.default>
Accept: text/event-stream
```

```json
{ "conversation_id": "...", "turn_id": "...", "input": "text or function_call_output items",
  "client_tools": [ { "name": "...", "description": "...", "parameters": { } } ],
  "pending_outputs": [ ],
  "user": { "oid": "...", "username": "...", "roles": [ "Chat.User" ] },
  "correlation_id": "..." }
```

The agent answers with the same events the loop emits, plus a last `outcome` event (`status`, `pending_outputs`, `client_call_ids`, `usage`) that the API consumes. Inside the container, `agent_core.run_turn` runs unchanged.

## 2. What Foundry provided without code

"Not exercised" means the capability is described by the product but this project did not use it.

| Capability | A: prompt agent | B: own loop | C: hosted agent |
| --- | --- | --- | --- |
| Tool loop | MCP tool calls run inside Foundry. Function tools still return to the caller. | None. | None: our code in Foundry's container. |
| Knowledge base access | Each attached as an MCP tool through a `RemoteTool` connection with `ProjectManagedIdentity`. No retrieval code. | None: retrieve client in our code. | None: same retrieve client. |
| Identity | Project managed identity, for the MCP call. No identity per agent. | None from Foundry. The API has its Container App managed identity. | A per-agent Entra identity (`instance_identity.principal_id`), stable across versions. |
| Caller assurance | Project roles. | Not applicable. | Gateway replaces `x-ms-original-subject`. A forged value as the deployer got 403 from the handler. |
| Tracing | Foundry adds `responsesapi` spans into the same trace. | Nothing beyond the HTTP calls we make: no `responsesapi` spans. | Platform injects the connection string. Foundry adds `agentsv2` and `responsesapi`, and the agent's own spans appear as `voltrieve-hosted`. |
| Conversation storage | Foundry Conversations. | Foundry Conversations: available without an agent. | Foundry Conversations, driven by the API. |
| Content filters | Default filter on the deployment. Not triggered on purpose. | Same deployment, same filter. | Same deployment, same filter. |
| Versioning | `create_version`. The API references the agent by name, so it gets the latest. | None: container image tags. | Agent versions over image tags. Sessions stay on the version they started on. |
| Publishing to Teams and Microsoft 365 | Possible. Not exercised. | Not possible: a direct Responses call from our own API cannot publish. | Possible through the Activity protocol. Not exercised, and our version declares only Invocations. |
| Registry and governance | Agent objects in the project, created by a role-gated script. No governance feature exercised. | None. | Same as A. |

Backend B still depends on Foundry: models, Responses and Conversations all come from the project endpoint. What it does not use is an agent object.

## 3. What the own-loop backend had to implement

Measured with `uv run scripts/measure_loc.py`: non-blank Python lines, excluding comments and docstrings. Each line counts in one group. An `x` means the backend needs that group.

| Concern | Lines | A | B | C |
| --- | ---: | --- | --- | --- |
| Orchestration loop and events | 252 | x | x | x |
| Instructions (system prompt) | 33 | x | x | x |
| Model client (Responses streaming) | 137 | x | x | x |
| Tool set (validate, authorize, run) | 102 | x | x | x |
| Server tool definitions | 106 | x | x | x |
| Dealer client | 57 | x | x | x |
| Knowledge base client (retrieve) | 212 |  | x | x |
| API contract (routes, schemas, app) | 366 | x | x | x |
| Auth (token validation) | 116 | x | x | x |
| Turn state and repair | 413 | x | x | x |
| Telemetry and logging | 70 | x | x | x |
| Backend registry | 43 | x | x | x |
| Loop host in the API (backends/loop.py) | 75 | x | x |  |
| Prompt backend (backends/prompt.py) | 128 | x |  |  |
| Prompt agent definitions (create_agents.py) | 109 | x |  |  |
| Hosted relay (backends/hosted.py) | 172 |  |  | x |
| Hosted agent entry point (main.py) | 186 |  |  | x |
| Hosted agent deployment (deploy.py) | 107 |  |  | x |
| **Total the backend runs** | 2684 | 2007 | 1982 | 2372 |

For scale, not part of the totals above:

| Other Python | Lines |
| --- | ---: |
| CLI client | 495 |
| Dealer service | 341 |
| Search setup (rest of search/) | 267 |
| Entra setup | 377 |
| Demo and test scripts | 970 |
| Automated tests | 3964 |

Reading the table:

- The totals are close because the backends share so much. Backend A is not smaller, because it has the same clients to serve and the same function calls to relay. A prompt agent saves the 212 line retrieve client and costs 237 lines for its definitions and its backend (128 of them filter and rewrite Foundry's citation markers, so clients see the same text as from the other backends).
- The agent proper in backend B (loop through knowledge base client) is 899 lines. The web API around it is 1083 lines. Most of that API would exist whichever backend answered.
- The telemetry row counts only the setup. Trace events are emitted inside the loop and the tool set and are counted there.
- Bicep, shell, the SPA and the client apps are not counted. Backend A could be written with a smaller relay than the shared loop, so 2007 is what this repository has, not a floor.

What backend B cannot get at all: publishing to Teams and Microsoft 365 Copilot, a managed agent identity, and registry entries for the agent.

## 4. Is agentic RAG without Foundry agents hard?

No. The orchestration loop is 252 lines including its events, and the model client is 137. The loop itself is short: call the model, run server tools, stop for client tools, repeat, with a cap of eight iterations.

The complexity sits elsewhere:

- **Turn state (413 lines, the largest group).** A paused turn is stored with its pending server outputs and expected call ids, for 15 minutes. A second message during a running turn gets 409. A new message on a paused conversation closes the old turn with synthetic outputs. Conversation ownership is checked on every use. A conversation left dirty by a failure, or touched first by a new process, is repaired before use.
- **Tool relay.** Server and client calls can arrive in the same model response. Server outputs must wait and reach the conversation together with the client results.
- **Tool safety (102 lines).** Arguments from the model are validated against JSON schema, for server tools in `execute` and for client tools before the call is forwarded (a call the client's own schema rejects is answered with the error and never sent on). Roles are checked in `execute`, and failures go back to the model as text. The requester on a booking comes from the token, never from the model.
- **Tracing.** Every visible hop is an event we emit. This is what makes the three backends comparable, and it has to be written whichever backend is used.

Almost none of it is Foundry-specific. Only `model.py` speaks the Responses API, and only `ConversationBackend` speaks the Conversations API. Both are OpenAI SDK calls. Apart from the model endpoint, the conversation store is the one piece you would replace if you left Foundry entirely. The tool relay, turn state, auth and tracing are ordinary web API work.

Answer quality did not depend on the host. Grounding on the final build: 30 of 30 answers passed (`docs/evidence/grounding.txt`). One setting mattered more than any hosting choice. At the default reasoning effort the cross-document question "cheapest AWD in Sweden" was right only 11 to 15 of 18 times, on all hosts, with the ranking changing between runs. At reasoning effort medium it was 18 of 18 (`docs/evidence/cross-document-repeat.txt`). So measure such questions by repetition rather than one pass, and treat reasoning effort as a design choice. A prompt agent sets it in its definition, your own loop per call.

Recovery was tested live too. A paused turn nobody answers, and a conversation resumed after the API scaled to zero, both recovered on all three backends (`docs/evidence/repair.txt`).

## 5. Hosted agent versus custom code in a web API

The code is the same: `agent_core.run_turn` runs unchanged in both places. Moving from B to C costs 465 lines (relay, entry point, deployment) and frees 75. The API stays in front in both cases, because it holds the client contract, the token validation and the paused turns.

| | Custom code in the web API (B) | Hosted agent (C) |
| --- | --- | --- |
| Who runs it | Your Container App, scaling 0 to 1 | Foundry, in sessions of 0.5 vCPU and 1 GiB |
| Identity | API managed identity | Per-agent Entra identity, stable across versions |
| Tool authorization | In the API process, on validated token claims | In the agent, on claims the API forwards in the body. Trusted because only the API may call. |
| Observability | One process, spans in one service | Same trace events reach the client. Model and dealer calls happen in the agent, not the API. |
| Trace seen by the client | Same event sequence as C | Same event sequence as B (compare `docs/evidence/loop.json` and `hosted.json`) |
| Channels | Your API only | Your API, plus the Activity protocol path to Teams and Microsoft 365 (not exercised) |
| Protocol | Your contract | Your contract as well: Invocations carries your JSON and SSE |
| Deploy | `azd deploy`, new revision | Image build, new agent version, wait until active |
| Cost model | Container Apps, scales to zero | Billed only for active sessions |

Section 6 measures whole turns, from a laptop in one region: the hosted agent adds about 4 to 5 seconds per turn. Cold starts were not measured apart.

### Honest limits of hosted agents

- **Invocations is a custom contract.** You write both ends: 172 lines in the API and 186 in the agent, plus the `outcome` event. It is not a drop-in target for an OpenAI client.
- **No OpenAI compatibility for caller tools.** Over the Responses protocol, caller `tools` and `metadata` arrive as `None`, with no error. The failure is silent, so test it before you design around it.
- **Identity setup has an order.** The agent identity only exists after the first version is created. You need a `linux/amd64` image, Foundry Project Manager for the deployer, and registry pull roles for the project identity. Then you create the version, read the principal id, provision a second time so Bicep can assign Search and Foundry roles, and assign `Dealer.Access` through Graph. Until then the running agent lacks its access.
- **Cold starts are real.** The first call on a new session is slow. No figure was recorded. The API allows a 300 second read timeout for this. A broken image shows up as `session_not_ready`.
- **Sessions are pinned to versions.** A conversation in flight stays on the old version after a deployment, until its session is dropped: an API restart, or a non-200 that makes the API retry without the session.
- **Idle timeout has a floor of 120 seconds.** An idle session is suspended, so the next call may be cold again.
- **Part of the SDK is draft.** The packages are pinned (`azure-ai-agentserver-invocations` 1.3.0, `azure-ai-agentserver-core` 2.3.0, `azure-ai-projects` 2.10.0) and report Production/Stable. But the class that parses `x-ms-original-subject`, which our caller check relies on, is marked `@experimental` in core 2.3.0, and its docstring says "These values are not proof of identity." We tested that the gateway replaces a forged value, once, as the deployer. If that behaviour changes, the check fails closed.
- **A lost stream is awkward.** The agent runs the turn detached from the response. When the stream breaks the API cannot tell whether it is still running, so it keeps the conversation blocked for 120 seconds before repairing it.

### Publishing

Publishing to Teams and Microsoft 365 was not exercised. It requires a prompt or hosted agent. Hosted agents support the Activity protocol, but our version declares only Invocations, so that protocol would have to be added and tested.

## 6. Two knowledge bases: who chooses, and who runs them together

A second knowledge base holds 433 spare parts across five catalogs. The first gained a service guide that says what each job consists of, with no article numbers. The catalogs have the article numbers, with no procedures. So "which parts do I need to change the front left brake on my Fjord?" really needs both.

Two different decisions are involved, and they are often confused:

- **Which sources to use, and how many at once.** The model decides this on every backend, from the tool descriptions and the instructions. Nothing in this repository routes by code.
- **Whether the calls really run at the same time.** Whoever executes the tools decides this. In the own loop and the hosted agent that is our code. In a prompt agent it is Foundry.

### Not calling in vain

There is no router step, and no search on every turn. Thinking first comes from three things in the prompt, shared by all backends:

1. Each description says what its base holds and what it does not: "It has no article numbers", and "It does not say which parts a job needs". The model routes on these words (`server_tools.py`).
2. The instructions list when no search is needed, including another car brand or a parts question with no model. Then the agent answers or asks, and spends nothing.
3. The instructions say a question needing two sources calls them in the same step.

Measured with `tests/routing/check.py`: 14 questions, 3 repeats, one at a time (`docs/evidence/routing.txt`).

| | A: prompt agent | B: own loop | C: hosted agent |
| --- | --- | --- | --- |
| Runs with exactly the right sources | 45 of 45 | 45 of 45 | 45 of 45 |
| Knowledge base calls in vain | 0 | 0 | 0 |
| Two source runs with overlapping calls | 0 of 12 | 12 of 12 | 12 of 12 |
| Median seconds, no search | 1.6 | 1.4 | 6.0 |
| Median seconds, one base | 4.8 to 5.2 | 4.7 to 4.8 | 9.2 to 9.7 |
| Median seconds, two bases | 24.6 | 12.3 | 17.1 |
| Median model steps, two bases | 3.5 | 2 | 2 |
| Expected article numbers in the answer | 117 of 117 | 115 of 117 | 115 of 117 |
| Invented article numbers | 0 | 0 | 0 |

The scores are the same, so the choice of source does not depend on the host. Speed does.

### Parallel calls

In backends B and C, `run_turn` runs all the read tools of one model response with `asyncio.gather`. A tool that changes something (`book_test_drive`) waits and runs alone. The trace shows `tools_parallel_started`, then `tools_parallel_finished` with the time taken and the time one at a time would have taken. The median saving was 1.9 seconds per turn.

Backend A has less control:

- `PromptAgentDefinition` has no `parallel_tool_calls` field.
- A request with an agent reference does accept the setting, and it changes function tools: `true` gave 2 calls in one response, `false` gave 1 (`docs/evidence/parallel-setting.txt`).
- It did not make the knowledge bases run together. The two MCP calls never overlapped in 12 runs, and the second query was written after the first result had come back. The explicit setting was tried on a few direct calls only, and only one of those reached the knowledge bases, so treat it as a strong hint.

The prompt agent also lost time on something else. In 4 of 4 traced runs of a job question it first called `check_stock`, `get_prices` or `get_current_date` for several steps, although the instructions forbid that (`docs/evidence/prompt-extra-steps.txt`). Those are function tools, so each one returns to the API. Questions for one base took one step, and the other backends did not do this. The cause was not established.

### Parallel is not always better

A parallel search cannot use what the other one finds. Brake fluid is a part of the job, so only the service guide reveals it, and it sits in a different catalog from the brake parts. Backends B and C searched before they knew, so they missed it unless they searched again. That follow-up is why two base turns sometimes take a third step. It is also why the instructions tell the agent to check every component against the results.

All four missing article numbers were brake fluid, so the follow-up does not always fire. The slower prompt agent found all of them, because it wrote the second query after reading the first answer. Choose by the dependency: search together when each query can be written from the question alone, and in sequence when one depends on the other. A good agent does the first, then fills the gaps.

### One knowledge base with two sources

This looks like a way to give a prompt agent fan-out with a single tool. In a short experiment a temporary knowledge base with both sources answered in about 2.3 seconds, but its query planner used only the parts source in 3 of 3 runs, so the job definition was missing. The routing decision moves to the search service. `alwaysQuerySource` might force both, and was not tested. The experiment was deleted.

### Limits under load

Each retrieve also spends model tokens on query planning, so parallel searches reach the deployment's limit of 150k tokens a minute sooner. With four turns at once, before any fix, 5 of 45 runs on the prompt agent failed with `model_error` and the own loop and hosted agent reported the search as unavailable. The API's own loop and the hosted agent now wait out a `429` from search, up to twice. A repeat with four turns at once gave no errors on any backend (`docs/evidence/routing-load.txt`), with one missed source on the prompt agent. A prompt agent's retrieve runs inside Foundry, so we cannot add a retry there. This is not a load test: real traffic needs a capacity plan.

## 7. Recommendation

Choose by what the clients need, in this order.

**Pick the own loop in a web API (B) when:**

- clients bring their own tools, or the tool list varies per client, device or request;
- turns reach several knowledge bases and speed matters, since you run them together;
- you need no Teams or Microsoft 365 channel;
- you already run a web API with Entra auth.

**Pick a hosted agent (C) when:**

- you also need a managed per-agent identity, Foundry-run containers and agent versions, or expect to publish through the Activity protocol;
- and you accept a custom Invocations contract, cold starts, the identity setup order and version-pinned sessions.

Start with B if unsure. The core moves to C unchanged, for about 465 lines.

**Pick a prompt agent (A) when:**

- the tool list is fixed and known when the agent is defined, and changes rarely;
- you want instructions and tools managed in Foundry, and the knowledge base attached without retrieval code;
- speed across several knowledge bases matters less, since they ran one after the other here;
- you can live with no references or retrieval activity in the result (Foundry's citation markers such as `【5:0†file】` are rewritten by the API to ` (file)`, and a marker with no file name is dropped, so clients cannot tell this backend by its text) and roles enforced only in the relay.

**Do not** build on the hosted Responses protocol if the caller must supply tools or metadata.

## The Irma situation

This was run against the deployed API with `scripts/new_client_tool_demo.py`. A script declares `set_emissivity` in the request, and nothing about that tool exists in the API, the agents or Foundry. Backends B and C relayed the call to the client with the value 0.95 and finished the turn, with no server change. Backend A refused it with `unsupported_client_tool` (`docs/evidence/new-client-tool.txt`). The script stands in for a camera: no Android code or device was involved.

The problem: an Android camera client exposes `set_emissivity` to the agent, alongside knowledge bases. This repository did not test an Android client or a real `set_emissivity`. Two knowledge bases are tested in section 6. The advice below follows from what was measured.

**Pick option B, the own loop in a web API.** The camera declares a device capability, which is what per-request tools exist for. The model must ask the camera to act, and the camera answers. Backend B does this with no workaround, and the Android app talks to a contract you own.

What it would take:

1. **Declare the tool on every turn.** Send `set_emissivity` in `client_tools`, with a schema that states the range the camera accepts. The API validates the shape of the schema and enforces limits (16 tools, 16 KiB).
2. **Speak the stream.** Read SSE, handle `trace`, `delta`, `client_tool_calls`, `done` and `error`. On `client_tool_calls`, apply the setting and post one result per `call_id` to `/chat/tool-results` within 15 minutes. `clients/cli/src/voltrieve_cli/api.py` is the reference, 40 lines for the turn loop.
3. **Validate on the device.** The API never runs client tools. It does check the model's arguments against the schema you declared and answers a call that fails the check with the error instead of forwarding it (`ToolSet.validate_client`), but the schema is only as strict as you wrote it. The app must still check the value, and decide whether the user confirms a change that affects measurements. A schema may not use `$ref`: the API rejects it with 422.
4. **Add a client registration.** Register a public client like `voltrieve-cli`, with the Android redirect, requesting `access_as_user`. Users need the `Chat.User` role. MSAL for Android was not tested.
5. **Add the knowledge bases.** Add one server tool per knowledge base, as `search_voltrieve_docs` and `search_spare_parts` do, and say in each description what it does not hold. The loop runs them together when the model asks for both.
6. **Plan for a mobile network.** A turn survives a dropped connection, but there is no way to resume a stream. If `client_tool_calls` is lost, the turn waits until the next message closes it with "the client did not return a result". A real app needs a resume or poll endpoint, which does not exist here.
7. **Move turn state out of the process before scaling.** `TurnStore` is a dict, so this API runs with `maxReplicas` 1 and a restart loses paused turns. More than one replica needs a shared store.

Alternatives for the same client:

- **If the camera's tools are fixed and rarely change,** a prompt agent also works: add `set_emissivity` to the definition, as `CLI_TOOLS` does in `agents/prompt/create_agents.py`, and keep the relay in the API. Every tool change then needs a new agent version before the app ships it, and tools cannot vary by device or firmware.
- **If agent identity or Foundry-run hosting is a hard requirement,** use C. The app does not change, because the API hides the difference. Items 1 to 7 still apply.
- **If Teams or Microsoft 365 is also wanted,** treat it as a second client. `set_emissivity` means nothing in Teams, since there is no camera there. A published prompt agent over the same knowledge bases can sit beside the camera's backend. This was not tested.

## Appendix: backend sheets

| | A: prompt agent | B: own loop | C: hosted agent |
| --- | --- | --- | --- |
| How client tools work | In the agent definition. Two agents, API picks one. Unknown tool is refused by the API. | Per request, in `tools`. | Per request, in our Invocations body, turned into tools inside the agent. |
| How the knowledge bases are attached | One MCP tool per base, each with a project connection. Both expose `knowledge_base_retrieve`, so only the server label and description differ. | `search_voltrieve_docs` and `search_spare_parts` server tools, retrieve endpoint | Same as B |
| What is visible in the trace | `mcp_tool_called` with an output preview. No references or activity. | `server_tool_called`, `knowledge_base_retrieved` (sub-queries, references), `server_tool_returned` | Same as B |
| What Foundry provides | Tool definition, MCP call, versions, project identity | Models and Conversations | Models, Conversations, runtime, agent identity, versions |
| What the code must provide | Relay for function calls, roles, turn state | Everything in section 3 | Everything in section 3, plus the Invocations contract and caller check |
| What breaks | Any tool outside the definition. Tools cannot be hidden per user, so roles are enforced in the relay. | Nothing Foundry-related, but no publishing. | Cold starts, identity order, version pinning, lost streams. |
| Where user identity would go if document trimming were added (not built) | Nowhere yet: the MCP call uses the project identity | The retrieve call is ours, so it can carry the user's identity | The body carries claims, not a token. An on-behalf-of exchange to a hosted agent app registration would be needed. |

Token use differed. Backend A used more on the same questions, as in step 2 (4712 total tokens against 3309 on B and C) and even on "Hello" (1107 against 460). The cause was not investigated.

Open items from the design that were not settled:

- The 10 minute expiry for pending tool outputs from older documentation was not measured. The API's own pause limit is 15 minutes, and no pause that long was tested against Foundry.
- Whether an MCP tool with a project connection works outside an agent definition is unanswered. Backend B does not depend on it.
