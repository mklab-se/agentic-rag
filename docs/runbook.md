# Demo runbook

This walks through design section 13 for each backend, with the trace you should see beside each step. Results are from the live run of 2026-11-04, recorded in `docs/evidence/`. Deployment is in [deploy.md](deploy.md).

## Before you start

Sign in as the deployer. That account holds `Chat.User` and `TestDrive.Book`.

```sh
az login
azd env select voltrieve-dev
```

The CLI reads `API_URL`, `TENANT_ID`, `CLI_CLIENT_ID` and `API_CLIENT_ID` from the azd environment (`azd env get-values`), so nothing has to be exported. A `VOLTRIEVE_API_URL`, `VOLTRIEVE_TENANT_ID`, `VOLTRIEVE_CLI_CLIENT_ID` or `VOLTRIEVE_API_CLIENT_ID` variable overrides the azd value, for pointing the CLI at another API.

```sh
export FOUNDRY_PROJECT_ENDPOINT="$(azd env get-value FOUNDRY_PROJECT_ENDPOINT)"
alias voltrieve='uv run --project clients/cli voltrieve'
```

The CLI asks for the `access_as_user` scope. `voltrieve login` always shows the Microsoft account picker and does not reuse a cached sign-in, so you can choose which account to use. `voltrieve logout` forgets the cached accounts. Each `ask` and each turn of `chat` generates a correlation id and sends it as `X-Correlation-Id` on every request of the turn; `ask` prints it on stderr, and `chat` shows it in the trace panel.

Run everything from the repository root. `voltrieve ask` prints the answer on stdout and the trace on stderr. Add `--json` to get every event as a JSON line. `voltrieve chat` shows the chat and a live trace panel.

The first call to a backend can be slow, because the API and dealer scale to zero and a hosted session starts cold.

## Run it all at once

```sh
uv run scripts/runbook.py                       # steps 1 to 12, all backends
uv run scripts/runbook.py --backends loop --steps 2,8
uv run tests/grounding/check.py                 # 10 questions per backend
uv run tests/grounding/check.py --backends prompt --only atlas-stock
uv run tests/routing/check.py                   # 14 questions, 3 repeats, all backends
uv run tests/routing/check.py --only brakes-fjord --repeats 1 --no-save
```

`scripts/runbook.py` prints a table and writes `docs/evidence/<backend>.json` and `runbook-table.txt`, overwriting what is there. Saved files keep model output verbatim except for em-dashes and absolute paths ([docs/evidence/README.md](evidence/README.md)). It sends `runbook-<backend>-<step>` as the correlation id. Keep the committed evidence with `git checkout docs/evidence` after a partial run.

Both scripts compare answers with `data/voltrieve.yaml` and exit 1 on a miss. Recorded results:

- Runbook: every step passes on every backend on the final build. Step 11 is `prompt` only. Step 12 is checked automatically by `scripts/runbook.py`, which waits for telemetry and writes `docs/evidence/application-insights.txt`.
- Grounding: 30 of 30 passed (`docs/evidence/grounding.txt`).
- Routing: 45 of 45 runs used exactly the right sources on every backend, with no knowledge base call in vain. Overlapping calls on two source questions: 12 of 12 on `loop` and `hosted`, 0 of 12 on `prompt`. Article numbers: 117 of 117 on `prompt`, 115 of 117 on `loop` and `hosted`, none invented. The script exits 1 on a missing article, so the recorded run exits 1. Run it with `--workers 1`: more turns at once measure the rate limit, not the routing.

`uv run scripts/new_client_tool_demo.py` shows a client bringing a tool the server has never seen, as a thermal camera would.

Step 7 and `cheapest-awd-se` are the same question. At the default reasoning effort it varied between runs on every backend. At medium effort it passed 18 of 18 (`docs/evidence/cross-document-repeat.txt`).

The recorded evidence comes from these scripts, which speak the same contract as the CLI. There is no transcript of `voltrieve` itself in `docs/evidence/`. `voltrieve login` and `logout` are tested against a fake MSAL application; a real browser sign-in was not exercised.

`uv run scripts/smoke.py` is the quick check after a deployment (`scripts/deploy-agents.sh` runs it last): `/healthz` of the API and the dealer, the indexer's last run, and one question on each backend.

## Backend A: prompt

Each knowledge base is an MCP tool inside Foundry, so a retrieval shows as one `mcp_tool_called` event per base, with no sub-queries or references. Foundry writes citations as `【5:0†voltrieve-fjord-specifications.pdf】`. The API rewrites them to ` (voltrieve-fjord-specifications.pdf)` and drops a marker that names no file (`【4:0†source】`), so a client cannot tell this backend by its text. The recorded runs predate that filter and show the raw markers.

| Step | Command | Expected trace | Recorded result |
| --- | --- | --- | --- |
| 1 | `voltrieve ask "Hello" --backend prompt --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, deltas, `model_returned`, `done`. `token_validated` shows the roles. | PASS (roles: Chat.User, TestDrive.Book) |
| 2 | `voltrieve ask "What is the towing capacity of the Fjord?" --backend prompt --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `mcp_tool_called`, deltas, `model_returned`, `done` | PASS |
| 3 | `voltrieve ask "Which of the 84 kWh models tows more?" --backend prompt --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `mcp_tool_called`, deltas, `model_returned`, `done` | PASS |
| 4 | `voltrieve ask "Which Voltrieve charges fastest?" --backend prompt --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `mcp_tool_called`, deltas, `model_returned`, `done` | PASS |
| 5 | `voltrieve ask "Can the Spark tow a trailer?" --backend prompt --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `mcp_tool_called`, deltas, `model_returned`, `done` | PASS |
| 6 | `voltrieve ask "What is the Lumen's Euro NCAP rating?" --backend prompt --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `mcp_tool_called`, deltas, `model_returned`, `done` | PASS |
| 7 | `voltrieve ask "What is the cheapest AWD Voltrieve in Sweden?" --backend prompt --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `mcp_tool_called`, deltas, `model_returned`, `done`. | PASS (Voltrieve Lumen AWD, 419,000 SEK) |
| 8 | `voltrieve ask "Is the Atlas in stock in Göteborg?" --backend prompt --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `model_returned`, `server_tool_called`, `server_tool_returned`, `model_called`, deltas, `model_returned`, `done`. The tool is `check_stock`. | PASS |
| 9a | `voltrieve ask "Book me a test drive of the Atlas in Göteborg on Saturday (YYYY-MM-DD)." --backend prompt --az-token`, using the coming Saturday | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `model_returned`, `server_tool_called`, `server_tool_returned`, `model_called`, deltas, `model_returned`, `done`. The tool is `book_test_drive`. | PASS |
| 9b | `uv run scripts/denied_demo.py --backend prompt` | `server_tool_called`, `authorization_denied`, `server_tool_returned`, `model_called`, polite refusal, then `PASS: authorization_denied emitted` | Not recorded for this backend |
| 10 | In `voltrieve chat --backend prompt --az-token`, ask: `What is the towing capacity of the Voltrieve Fjord? When you have the answer, beep three times.` | `token_validated`, `backend_selected`, `model_called`, `model_returned`, `client_tool_requested`, `client_tool_calls`. The CLI rings the bell and posts the result. Then `token_validated`, `backend_selected`, `model_called`, deltas, `model_returned`, `done`. There is no `conversation_created`: the conversation already exists. | PASS (`make_noise`, times=3) |
| 11 | `uv run scripts/runbook.py --backends prompt --steps 11` for the API's refusal, and `uv run --project agents/prompt agents/prompt/demo_rejection.py` for Foundry's 400 | Runbook script: `token_validated`, `backend_selected`, `conversation_created`, `unsupported_client_tool`, `error`. Demo script prints `400 invalid_payload: Error code: 400 - Not allowed when agent is specified.` | PASS, `docs/evidence/prompt-agent-rejection.txt` |
| 12 | See [Follow a correlation id](#follow-a-correlation-id), with `runbook-prompt-2` or `runbook-prompt-8` | One `chat.turn` span and the calls around it | MANUAL, not recorded |

Step 1 alternative for an interactive sign-in: `voltrieve login`, then leave out `--az-token`.

## Backend B: loop

The API runs the loop, so every hop is an event. `knowledge_base_retrieved` carries the sub-queries and references. With query planning on, one question can give several sub-queries.

| Step | Command | Expected trace | Recorded result |
| --- | --- | --- | --- |
| 1 | `voltrieve ask "Hello" --backend loop --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, deltas, `model_returned`, `done`. `token_validated` shows the roles. | PASS (roles: Chat.User, TestDrive.Book) |
| 2 | `voltrieve ask "What is the towing capacity of the Fjord?" --backend loop --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `model_returned`, `server_tool_called`, `knowledge_base_retrieved`, `server_tool_returned`, `model_called`, deltas, `model_returned`, `done` | PASS |
| 3 | `voltrieve ask "Which of the 84 kWh models tows more?" --backend loop --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `model_returned`, `server_tool_called`, `knowledge_base_retrieved`, `server_tool_returned`, `model_called`, deltas, `model_returned`, `done` | PASS |
| 4 | `voltrieve ask "Which Voltrieve charges fastest?" --backend loop --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `model_returned`, `server_tool_called`, `knowledge_base_retrieved`, `server_tool_returned`, `model_called`, deltas, `model_returned`, `done` | PASS |
| 5 | `voltrieve ask "Can the Spark tow a trailer?" --backend loop --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `model_returned`, `server_tool_called`, `knowledge_base_retrieved`, `server_tool_returned`, `model_called`, deltas, `model_returned`, `done` | PASS |
| 6 | `voltrieve ask "What is the Lumen's Euro NCAP rating?" --backend loop --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `model_returned`, `server_tool_called`, `knowledge_base_retrieved`, `server_tool_returned`, `model_called`, deltas, `model_returned`, `done` | PASS |
| 7 | `voltrieve ask "What is the cheapest AWD Voltrieve in Sweden?" --backend loop --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `model_returned`, `server_tool_called`, `knowledge_base_retrieved`, `server_tool_returned`, `server_tool_called`, `server_tool_returned`, `model_called`, deltas, `model_returned`, `done`. The recorded run called two tools. | PASS |
| 8 | `voltrieve ask "Is the Atlas in stock in Göteborg?" --backend loop --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `model_returned`, `server_tool_called`, `server_tool_returned`, `model_called`, deltas, `model_returned`, `done`. The tool is `check_stock`. | PASS |
| 9a | `voltrieve ask "Book me a test drive of the Atlas in Göteborg on Saturday (YYYY-MM-DD)." --backend loop --az-token`, using the coming Saturday | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `model_returned`, `server_tool_called`, `server_tool_returned`, `model_called`, deltas, `model_returned`, `done`. The tool is `book_test_drive`. | PASS |
| 9b | `uv run scripts/denied_demo.py --backend loop` | `server_tool_called`, `authorization_denied`, `server_tool_returned`, `model_called`, polite refusal, then `PASS: authorization_denied emitted` | PASS, `docs/evidence/authorization-denied.txt` |
| 10 | In `voltrieve chat --backend loop --az-token`, ask: `What is the towing capacity of the Voltrieve Fjord? When you have the answer, beep three times.` | `token_validated`, `backend_selected`, `model_called`, `model_returned`, `client_tool_requested`, `client_tool_calls`. The CLI rings the bell and posts the result. Then `token_validated`, `backend_selected`, `model_called`, deltas, `model_returned`, `done`. There is no `conversation_created`: the conversation already exists. | PASS (`make_noise`, times=3) |
| 11 | Skip | Backend A only. | SKIP |
| 12 | See [Follow a correlation id](#follow-a-correlation-id), with `runbook-loop-2` or `runbook-loop-8` | One `chat.turn` span and the calls around it | MANUAL, not recorded |

## Backend C: hosted

The same core runs in the Foundry container. The trace sequence matches backend B. The API only relays it.

| Step | Command | Expected trace | Recorded result |
| --- | --- | --- | --- |
| 1 | `voltrieve ask "Hello" --backend hosted --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, deltas, `model_returned`, `done`. `token_validated` shows the roles. | PASS (roles: Chat.User, TestDrive.Book) |
| 2 | `voltrieve ask "What is the towing capacity of the Fjord?" --backend hosted --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `model_returned`, `server_tool_called`, `knowledge_base_retrieved`, `server_tool_returned`, `model_called`, deltas, `model_returned`, `done` | PASS |
| 3 | `voltrieve ask "Which of the 84 kWh models tows more?" --backend hosted --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `model_returned`, `server_tool_called`, `knowledge_base_retrieved`, `server_tool_returned`, `model_called`, deltas, `model_returned`, `done` | PASS |
| 4 | `voltrieve ask "Which Voltrieve charges fastest?" --backend hosted --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `model_returned`, `server_tool_called`, `knowledge_base_retrieved`, `server_tool_returned`, `model_called`, deltas, `model_returned`, `done` | PASS |
| 5 | `voltrieve ask "Can the Spark tow a trailer?" --backend hosted --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `model_returned`, `server_tool_called`, `knowledge_base_retrieved`, `server_tool_returned`, `model_called`, deltas, `model_returned`, `done` | PASS |
| 6 | `voltrieve ask "What is the Lumen's Euro NCAP rating?" --backend hosted --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `model_returned`, `server_tool_called`, `knowledge_base_retrieved`, `server_tool_returned`, `model_called`, deltas, `model_returned`, `done` | PASS |
| 7 | `voltrieve ask "What is the cheapest AWD Voltrieve in Sweden?" --backend hosted --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `model_returned`, `server_tool_called`, `knowledge_base_retrieved`, `server_tool_returned`, `server_tool_called`, `server_tool_returned`, `model_called`, deltas, `model_returned`, `done`. The recorded run called two tools. | PASS |
| 8 | `voltrieve ask "Is the Atlas in stock in Göteborg?" --backend hosted --az-token` | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `model_returned`, `server_tool_called`, `server_tool_returned`, `model_called`, deltas, `model_returned`, `done`. The tool is `check_stock`. | PASS |
| 9a | `voltrieve ask "Book me a test drive of the Atlas in Göteborg on Saturday (YYYY-MM-DD)." --backend hosted --az-token`, using the coming Saturday | `token_validated`, `backend_selected`, `conversation_created`, `model_called`, `model_returned`, `server_tool_called`, `server_tool_returned`, `model_called`, deltas, `model_returned`, `done`. The tool is `book_test_drive`. | PASS |
| 9b | No in-process demo for this backend. Sign in as the tester in the SPA or with `voltrieve login`, choose hosted, and ask the same question. | Should match backend B: `server_tool_called`, `authorization_denied`, `server_tool_returned`, polite refusal. Role gating here is covered by offline tests. | Not tested live |
| 10 | In `voltrieve chat --backend hosted --az-token`, ask: `What is the towing capacity of the Voltrieve Fjord? When you have the answer, beep three times.` | `token_validated`, `backend_selected`, `model_called`, `model_returned`, `client_tool_requested`, `client_tool_calls`. The CLI rings the bell and posts the result. Then `token_validated`, `backend_selected`, `model_called`, deltas, `model_returned`, `done`. There is no `conversation_created`: the conversation already exists. | PASS (`make_noise`, times=3) |
| 11 | Skip | Backend A only. | SKIP |
| 12 | See [Follow a correlation id](#follow-a-correlation-id), with `runbook-hosted-2` or `runbook-hosted-8` | One `chat.turn` span and the calls around it | MANUAL, not recorded |

## Step 9 as the tester, for real

`scripts/denied_demo.py` runs the real API in process with a fake token validator that returns only `Chat.User`, against the real Foundry backend. It does not sign in as the tester, and it never reaches the dealer service. To use the real account, sign in to the SPA as below, or run `voltrieve login` as the tester, and ask for the booking. This real-account path was not tested.

## Step 10 in the SPA

The SPA declares one client tool, `set_theme`, so "Switch to the dark theme." changes the theme on all three backends. It has no beep tool, so the same question should get an explanation that it cannot beep, with no `client_tool_calls` event. On `prompt` the API picks the web agent, which has no client tools. This was not tested in the browser.

## Sign in to the SPA

The URL is `azd env get-value WEB_URL`. Sign-in is an Entra redirect with PKCE. Interactive sign-in was not verified: the SPA was tested with a mock server and fake auth, and the deployed site has not had a recorded browser sign-in.

| Account | User | Holds |
| --- | --- | --- |
| Deployer | Your own | `Chat.User`, `TestDrive.Book` |
| Tester | `azd env get-value TEST_USER_UPN` (`voltrieve-tester@<your domain>`) | `Chat.User` only |

The tester's password is generated by `azd up` and printed once by the preprovision hook, when the account is created. It is not stored anywhere. If it is lost, reset it in the Entra admin center. A tenant's MFA or sign-in policies may also apply to this account.

The header has a backend selector, which sets `X-Agent-Backend`. The side panel shows the same trace events as the CLI.

To try the SPA without Azure:

```sh
cd clients/web
npm ci
npm run mock          # scripted API on port 8787
npm run dev:mock      # in a second terminal, SPA with fake auth
```

## Follow a correlation id

The API takes `X-Correlation-Id` from the request, or generates one. It sets it as `correlation_id` on the request span and the `chat.turn` span, and passes it to the dealer, which sets it on its own span. The hosted agent logs it with the user's oid on every turn. The value is therefore in `customDimensions` of `requests` and `dependencies`. It is not on log records in Application Insights: there, join on `operation_Id`. The JSON logs on stdout do carry it.

Every hop of a turn is also a log line (`trace`, with `step`, `component`, `detail` and `elapsed_ms`) and an event on the `chat.turn` span, so the logs show the same sequence the client sees. Tool arguments and result previews are logged only at `LOG_LEVEL=DEBUG`, truncated.

In the Azure portal, open the Application Insights resource and choose Logs:

```kusto
let cid = "runbook-loop-8";
let ops = union requests, dependencies
    | where timestamp > ago(1d)
    | where tostring(customDimensions.correlation_id) == cid
    | distinct operation_Id;
union requests, dependencies, traces, exceptions
| where timestamp > ago(1d)
| where operation_Id in (ops)
| project timestamp, itemType, cloud_RoleName, name, message,
          duration, resultCode, target,
          turn_id = tostring(customDimensions.turn_id),
          backend = tostring(customDimensions.backend)
| order by timestamp asc
```

Expect `cloud_RoleName` `voltrieve-api`, with `voltrieve-dealer` for the dealer call, and these rows from the code:

- on `loop`: `POST /chat`, the `chat.turn` span, calls to the Foundry project and Search, the call to the dealer;
- on `prompt`: the same, with no Search call, because Foundry makes it;
- on `hosted`: the call to `.../protocols/invocations`. The model and dealer calls are made in the agent, under whatever service name the agent host sets.

A client tool turn is two HTTP requests, so it spans two `operation_Id` values under one correlation id. The query handles that when the client sends the same id on both, as `scripts/runbook.py` and the CLI do.

`voltrieve` and the SPA generate one id per turn, send it on every request of the turn and show it (the CLI on stderr, with `--trace` and with `/trace` in the chat, in the trace panel, the SPA in the event timeline). Copy it into `cid` above. Without an id, take `turn_id` from `voltrieve ask --json` and filter on it instead:

```kusto
dependencies
| where name == "chat.turn" and tostring(customDimensions.turn_id) == "<turn id>"
| project timestamp, operation_Id, duration, customDimensions
```

Step 12 stayed manual in the recorded run, and this query was written from the code. It has not been run against the deployment, so adjust it if the rows differ. Whether spans from the hosted agent join the same trace is also unverified, although `traceparent` is forwarded.

## Run locally against Azure

The services can run locally with your Azure CLI identity. This path has no recorded run, apart from `scripts/denied_demo.py`, which runs the API in process.

```sh
set -a; eval "$(azd env get-values)"; set +a
export CORS_ORIGINS=http://localhost:5173 VOLTRIEVE_API_URL=http://localhost:8000
(cd api && uv run uvicorn --factory app.main:build_app --port 8000)
```

Foundry and Search work through your roles. Dealer tools fail against the deployed dealer, because it requires the `Dealer.Access` application role, which a user token does not have.

For the SPA against that API or the deployed one:

```sh
cd clients/web
cp .env.production .env.local     # written by azd; edit VITE_API_URL if needed
npm ci && npm run dev             # http://localhost:5173, a registered redirect URI
```
