import { describe, expect, it } from "vitest";
import { chatReducer, initialChatState, type ChatState } from "./turns";
import type { ServerEvent } from "./types";

function run(events: ServerEvent[], start: ChatState = initialChatState): ChatState {
  let s = chatReducer(start, { type: "start", message: "q", backend: "loop", correlationId: "corr-1" });
  for (const event of events) s = chatReducer(s, { type: "event", event });
  return s;
}

describe("chatReducer", () => {
  it("accumulates deltas and groups trace entries under the turn", () => {
    const s = run([
      { type: "trace", data: { step: "token", component: "api", detail: "ok", elapsed_ms: 3 } },
      { type: "delta", data: { text: "Hel" } },
      { type: "delta", data: { text: "lo" } },
      { type: "done", data: { conversation_id: "c1", turn_id: "t1", backend: "loop", usage: { total_tokens: 9 } } },
    ]);
    const t = s.turns[0]!;
    expect(t.answer).toBe("Hello");
    expect(t.status).toBe("done");
    expect(t.entries.map((e) => e.kind)).toEqual(["trace", "done"]);
    expect(s.conversationId).toBe("c1");
  });

  it("keeps the correlation id of each turn", () => {
    let s = chatReducer(initialChatState, { type: "start", message: "a", backend: "loop", correlationId: "c-1" });
    s = chatReducer(s, { type: "start", message: "b", backend: "loop", correlationId: "c-2" });
    expect(s.turns.map((t) => t.correlationId)).toEqual(["c-1", "c-2"]);
  });

  it("keeps separate timelines per turn and the conversation id across turns", () => {
    const first = run([{ type: "done", data: { conversation_id: "c1", turn_id: "t1", backend: "loop" } }]);
    const second = run(
      [{ type: "trace", data: { step: "s", component: "model", detail: "", elapsed_ms: 1 } }],
      first,
    );
    expect(second.turns).toHaveLength(2);
    expect(second.turns[0]!.entries).toHaveLength(1);
    expect(second.turns[1]!.entries).toHaveLength(1);
    expect(second.conversationId).toBe("c1");
  });

  it("keeps the turn running through client_tool_calls and remembers the conversation", () => {
    const s = run([
      {
        type: "client_tool_calls",
        data: { conversation_id: "c1", calls: [{ call_id: "1", name: "set_theme", arguments: "{}" }] },
      },
    ]);
    const t = s.turns[0]!;
    expect(t.status).toBe("streaming");
    expect(t.entries.at(-1)).toMatchObject({ step: "client_tool_ran", detail: "set_theme" });
    expect(s.conversationId).toBe("c1");
  });

  it("marks the turn failed on an error event", () => {
    const s = run([{ type: "error", data: { code: "boom", message: "bad" } }]);
    expect(s.turns[0]).toMatchObject({ status: "error", error: "bad" });
  });
});
