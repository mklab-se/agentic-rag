import type { Backend, ServerEvent } from "./types";

export type TimelineEntry =
  | { kind: "trace"; step: string; component: string; detail: string; elapsedMs: number }
  | { kind: "done"; backend: string; turnId: string; usage: Record<string, unknown> | null }
  | { kind: "error"; code: string; message: string };

export interface Turn {
  id: number;
  userText: string;
  /** Sent as X-Correlation-Id: the id to search for in logs and traces. */
  correlationId: string;
  requestedBackend: Backend;
  answer: string;
  entries: TimelineEntry[];
  status: "streaming" | "done" | "error";
  error?: string;
  /** Backend that the API reports in its done event. */
  backend?: string;
}

export interface ChatState {
  conversationId?: string;
  turns: Turn[];
}

export type ChatAction =
  | { type: "start"; message: string; backend: Backend; correlationId: string }
  | { type: "event"; event: ServerEvent }
  | { type: "reset" };

export const initialChatState: ChatState = { turns: [] };

function updateLast(state: ChatState, fn: (t: Turn) => Turn): ChatState {
  if (state.turns.length === 0) return state;
  const turns = state.turns.slice();
  turns[turns.length - 1] = fn(turns[turns.length - 1]!);
  return { ...state, turns };
}

function fail(t: Turn, code: string, message: string): Turn {
  return { ...t, status: "error", error: message, entries: [...t.entries, { kind: "error", code, message }] };
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "reset":
      return initialChatState;
    case "start": {
      const turn: Turn = {
        id: state.turns.length + 1,
        userText: action.message,
        correlationId: action.correlationId,
        requestedBackend: action.backend,
        answer: "",
        entries: [],
        status: "streaming",
      };
      return { ...state, turns: [...state.turns, turn] };
    }
    case "event": {
      const ev = action.event;
      switch (ev.type) {
        case "trace":
          return updateLast(state, (t) => ({
            ...t,
            entries: [
              ...t.entries,
              {
                kind: "trace",
                step: ev.data.step,
                component: ev.data.component,
                detail: ev.data.detail,
                elapsedMs: ev.data.elapsed_ms,
              },
            ],
          }));
        case "delta":
          return updateLast(state, (t) => ({ ...t, answer: t.answer + ev.data.text }));
        case "client_tool_calls": {
          // This client declares no tools, so the API should never ask for any.
          const names = ev.data.calls.map((c) => c.name).filter(Boolean).join(", ") || "unknown";
          return updateLast(state, (t) =>
            fail(
              t,
              "unexpected_client_tool_calls",
              `The agent asked this client to run tools (${names}), but the web app declares none. The turn was stopped.`,
            ),
          );
        }
        case "done":
          return {
            ...updateLast(state, (t) => ({
              ...t,
              status: t.status === "error" ? "error" : "done",
              backend: ev.data.backend,
              entries: [
                ...t.entries,
                { kind: "done", backend: ev.data.backend, turnId: ev.data.turn_id, usage: ev.data.usage ?? null },
              ],
            })),
            conversationId: ev.data.conversation_id || state.conversationId,
          };
        case "error":
          return updateLast(state, (t) => fail(t, ev.data.code, ev.data.message));
      }
    }
  }
}
