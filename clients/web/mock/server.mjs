// Tiny mock of the Web API's POST /chat, for running and screenshotting the SPA
// without Azure. Emits a scripted turn as server-sent events.
//
//   npm run mock            (listens on :8787)
//   npm run dev:mock        (SPA with fake auth pointing here)
//
// Special messages: containing "tools" emits client_tool_calls, "error" emits an
// error event. Everything else gets the scripted grounded answer.
import { createServer } from "node:http";
import { randomUUID } from "node:crypto";

const PORT = Number(process.env.PORT ?? 8787);
const FAST = process.env.MOCK_FAST === "1";
const sleep = (ms) => new Promise((r) => setTimeout(r, FAST ? 0 : ms));

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, content-type, x-agent-backend",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function script(message, backend) {
  const t = [
    ["token validated", "auth", "oid 7f3a..., roles Chat.User, TestDrive.Book", 4],
    ["backend selected", "agent", `backend ${backend}`, 6],
    ["model called", "model", "gpt chat deployment, 2 server tools available", 38],
    ["server tool requested", "tool", "search_documents(query=\"Fjord towing capacity\")", 920],
    ["retrieval started", "search", "knowledge base voltrieve-kb, semantic reranker", 931],
    ["retrieval returned 4 chunks", "search", "fjord-owners-manual p.41, fjord-spec-sheet p.2", 1384],
    ["model called", "model", "answering from 4 chunks", 1402],
  ];
  const answer =
    message.toLowerCase().includes("beep")
      ? "I can't beep: this client doesn't give me any tools to run on your device. I can only search Voltrieve documents and look up dealer stock from the server."
      : "The Fjord can tow up to 1,600 kg braked with the 84 kWh battery, and 750 kg unbraked. The 63 kWh version is rated for 1,200 kg braked. [fjord-owners-manual p.41]";
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
    send("trace", { step: "token validated", component: "auth", detail: "ok", elapsed_ms: el() });
    await sleep(300);
    send("error", { code: "backend_failed", message: "The backend could not complete the turn." });
    return;
  }
  for (const [step, component, detail, at] of trace) {
    await sleep(220);
    send("trace", { step, component, detail, elapsed_ms: at });
  }
  if (/tools/i.test(msg)) {
    send("client_tool_calls", { turn_id, calls: [{ call_id: "c1", name: "beep", arguments: { times: 3 } }] });
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
  res.writeHead(200, { ...CORS, "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
  try {
    await turn(res, body, backend);
  } finally {
    res.end();
  }
}).listen(PORT, "127.0.0.1", () => console.log(`mock Web API on http://127.0.0.1:${PORT}`));
