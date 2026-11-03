import { describe, expect, it } from "vitest";
import { createSseParser } from "./sse";

describe("createSseParser", () => {
  it("parses a complete message", () => {
    const p = createSseParser();
    expect(p.feed('event: delta\ndata: {"text":"hi"}\n\n')).toEqual([
      { event: "delta", data: '{"text":"hi"}' },
    ]);
  });

  it("reassembles messages split across arbitrary chunk boundaries", () => {
    const p = createSseParser();
    const wire = 'event: trace\ndata: {"a":1}\n\nevent: done\ndata: {"b":2}\n\n';
    const out = [...wire].flatMap((ch) => p.feed(ch));
    expect(out).toEqual([
      { event: "trace", data: '{"a":1}' },
      { event: "done", data: '{"b":2}' },
    ]);
  });

  it("handles CRLF, including a CR and LF split across chunks", () => {
    const p = createSseParser();
    const out = [...p.feed("event: delta\r"), ...p.feed("\ndata: x\r\n\r"), ...p.feed("\n")];
    expect(out).toEqual([{ event: "delta", data: "x" }]);
  });

  it("joins multi-line data with newlines and strips one leading space", () => {
    const p = createSseParser();
    expect(p.feed("data: a\ndata:  b\n\n")).toEqual([{ event: "message", data: "a\n b" }]);
  });

  it("ignores comments and messages without data", () => {
    const p = createSseParser();
    expect(p.feed(": keep-alive\n\nevent: x\n\n")).toEqual([]);
  });

  it("does not leak the event name into the next message", () => {
    const p = createSseParser();
    const out = p.feed("event: a\ndata: 1\n\ndata: 2\n\n");
    expect(out.map((m) => m.event)).toEqual(["a", "message"]);
  });

  it("flush dispatches a final unterminated message", () => {
    const p = createSseParser();
    expect(p.feed("event: done\ndata: {}")).toEqual([]);
    expect(p.flush()).toEqual([{ event: "done", data: "{}" }]);
  });

  it("keeps multibyte text intact", () => {
    const p = createSseParser();
    expect(p.feed("data: Göteborg ⚡\n\n")).toEqual([{ event: "message", data: "Göteborg ⚡" }]);
  });
});
