// Tiny mock of the Web API's POST /chat, for running and screenshotting the SPA
// without Azure. Emits a scripted turn as server-sent events.
//
//   npm run mock            (listens on :8787)
//   npm run dev:mock        (SPA with fake auth pointing here)
//
// The steps and components are the ones the real API emits (token_validated, backend_selected,
// conversation_created, model_called, server_tool_called, knowledge_base_retrieved,
// server_tool_returned, model_returned). Special messages: containing "tools" emits
// client_tool_calls, "error" emits an error event. Everything else gets the scripted grounded
// answer. The X-Correlation-Id of the request is echoed back, as the real API does.
import { createServer } from "node:http";
import { randomUUID } from "node:crypto";

const PORT = Number(process.env.PORT ?? 8787);
const FAST = process.env.MOCK_FAST === "1";
const sleep = (ms) => new Promise((r) => setTimeout(r, FAST ? 0 : ms));

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, content-type, x-agent-backend, x-correlation-id",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Expose-Headers": "x-correlation-id",
};

function script(message, backend) {
  const t = [
    ["token_validated", "auth", "roles: Chat.User, TestDrive.Book", 4],
    ["backend_selected", "api", backend, 6],
    ["conversation_created", "api", "conv_mock", 21],
    ["model_called", "model", "iteration 1", 38],
    ["model_returned", "model", "0 text deltas, 1 tool calls", 910],
    ["server_tool_called", "tools", "search_voltrieve_docs", 920],
    ["knowledge_base_retrieved", "search", "4 chunks from 2 documents", 1384],
    ["server_tool_returned", "tools", "search_voltrieve_docs", 1390],
    ["model_called", "model", "iteration 2", 1402],
  ];
  const answer =
    message.toLowerCase().includes("beep")
      ? "I can't beep: this client doesn't give me any tools to run on your device. I can only search Voltrieve documents and look up dealer stock from the server."
      : "The **Fjord** can tow up to 1,600 kg braked:\n\n" +
        "| Battery | Braked | Unbraked |\n|---|---:|---:|\n" +
        "| 84 kWh | 1,600 kg | 750 kg |\n| 63 kWh | 1,200 kg | 750 kg |\n\n" +
        "Source: *voltrieve-fjord-specifications.pdf*";
  return { trace: t, answer };
}

async function turn(res, body, backend) {
  const t0 = Date.now();
  const send = (event, data) => res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  const el = () => Date.now() - t0;
  const msg = String(body.message ?? "");
  const conversation_id = body.conversation_id ?? `conv-${randomUUID().slice(0, 8)}`;
  const turn_id = `turn-${randomUUID().slice(0, 8)}`;

  const { trace, answer } = script(msg, backend);
  if (/error/i.test(msg)) {
    send("trace", { step: "token_validated", component: "auth", detail: "roles: Chat.User", elapsed_ms: el() });
    await sleep(300);
    send("error", { code: "model_error", message: "The model call failed." });
    return;
  }
  for (const [step, component, detail, at] of trace) {
    await sleep(220);
    send("trace", { step, component, detail, elapsed_ms: at });
  }
  if (/tools/i.test(msg)) {
    send("trace", { step: "client_tool_requested", component: "tools", detail: "beep", elapsed_ms: el() });
    send("client_tool_calls", {
      turn_id,
      conversation_id,
      calls: [{ call_id: "c1", name: "beep", arguments: JSON.stringify({ times: 3 }) }],
    });
    return;
  }
  for (const word of answer.split(/(?<=\s)/)) {
    await sleep(35);
    send("delta", { text: word });
  }
  send("done", { conversation_id, turn_id, backend, usage: { prompt_tokens: 1840, completion_tokens: 62, total_tokens: 1902 } });
}

createServer(async (req, res) => {
  if (req.method === "OPTIONS") {
    res.writeHead(204, CORS).end();
    return;
  }
  if (req.method !== "POST" || req.url !== "/chat") {
    res.writeHead(404, CORS).end();
    return;
  }
  if (!req.headers.authorization?.startsWith("Bearer ")) {
    res.writeHead(401, CORS).end();
    return;
  }
  let raw = "";
  for await (const chunk of req) raw += chunk;
  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    res.writeHead(400, CORS).end();
    return;
  }
  const backend = String(req.headers["x-agent-backend"] ?? "loop");
  const correlationId = String(req.headers["x-correlation-id"] ?? randomUUID());
  res.writeHead(200, {
    ...CORS,
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "X-Correlation-Id": correlationId,
  });
  try {
    await turn(res, body, backend);
  } finally {
    res.end();
  }
}).listen(PORT, "127.0.0.1", () => console.log(`mock Web API on http://127.0.0.1:${PORT}`));
