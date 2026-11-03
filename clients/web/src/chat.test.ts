import { describe, expect, it } from "vitest";
import { buildChatRequest, streamChat } from "./chat";
import type { ServerEvent } from "./types";

const base = { apiUrl: "https://api.example/", token: "tok", backend: "loop" as const, message: "hello" };

function sseResponse(chunks: string[], status = 200): Response {
  const enc = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch));
      c.close();
    },
  });
  return new Response(body, { status, headers: { "Content-Type": "text/event-stream" } });
}

async function collect(gen: AsyncGenerator<ServerEvent>): Promise<ServerEvent[]> {
  const out: ServerEvent[] = [];
  for await (const e of gen) out.push(e);
  return out;
}

describe("buildChatRequest", () => {
  it("sends only message on the first turn and never client_tools", () => {
    const { url, init } = buildChatRequest(base);
    expect(url).toBe("https://api.example/chat");
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({ message: "hello" });
    expect("client_tools" in body).toBe(false);
  });

  it("includes conversation_id on later turns, still without client_tools", () => {
    const { init } = buildChatRequest({ ...base, conversationId: "c1" });
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({ conversation_id: "c1", message: "hello" });
    expect("client_tools" in body).toBe(false);
  });

  it("sets bearer auth and the backend header", () => {
    const { init } = buildChatRequest({ ...base, backend: "hosted" });
    const h = init.headers as Record<string, string>;
    expect(h.Authorization).toBe("Bearer tok");
    expect(h["X-Agent-Backend"]).toBe("hosted");
    expect(init.method).toBe("POST");
  });
});

describe("streamChat", () => {
  it("yields typed events across split chunks", async () => {
    const fetchImpl = (async () =>
      sseResponse([
        'event: trace\ndata: {"step":"s","component":"api","detail":"d","elapsed_ms":5}\n',
        '\nevent: delta\ndata: {"text":"Hi"}\n\nevent: done\n',
        'data: {"conversation_id":"c","turn_id":"t","backend":"loop","usage":{}}\n\n',
      ])) as unknown as typeof fetch;
    const events = await collect(streamChat(base, undefined, fetchImpl));
    expect(events.map((e) => e.type)).toEqual(["trace", "delta", "done"]);
    expect(events[0]).toMatchObject({ data: { component: "api", elapsed_ms: 5 } });
  });

  it("maps HTTP failures and network failures to error events", async () => {
    const f403 = (async () => new Response("", { status: 403 })) as unknown as typeof fetch;
    const e1 = await collect(streamChat(base, undefined, f403));
    expect(e1).toMatchObject([{ type: "error", data: { code: "http_403" } }]);

    const fnet = (async () => {
      throw new TypeError("failed");
    }) as unknown as typeof fetch;
    const e2 = await collect(streamChat(base, undefined, fnet));
    expect(e2).toMatchObject([{ type: "error", data: { code: "network" } }]);
  });

  it("reports malformed event JSON as an error event instead of throwing", async () => {
    const fetchImpl = (async () => sseResponse(["event: delta\ndata: {nope\n\n"])) as unknown as typeof fetch;
    const events = await collect(streamChat(base, undefined, fetchImpl));
    expect(events).toMatchObject([{ type: "error", data: { code: "malformed_event" } }]);
  });
});
