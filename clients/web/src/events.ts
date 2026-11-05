import type { SseMessage } from "./sse";
import type { ServerEvent } from "./types";

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function malformed(message: string): ServerEvent {
  return { type: "error", data: { code: "malformed_event", message } };
}

/** Turn one SSE message into a typed event; unknown event names yield null. */
export function parseServerEvent(msg: SseMessage): ServerEvent | null {
  let payload: unknown;
  try {
    payload = JSON.parse(msg.data);
  } catch {
    return malformed(`Event "${msg.event}" carried invalid JSON.`);
  }
  if (!isRecord(payload)) return malformed(`Event "${msg.event}" carried a non-object payload.`);

  switch (msg.event) {
    case "trace":
      return {
        type: "trace",
        data: {
          step: String(payload.step ?? ""),
          component: String(payload.component ?? ""),
          detail: String(payload.detail ?? ""),
          elapsed_ms: typeof payload.elapsed_ms === "number" ? payload.elapsed_ms : 0,
        },
      };
    case "status":
      return {
        type: "status",
        data: { code: String(payload.code ?? ""), message: String(payload.message ?? "") },
      };
    case "delta":
      return { type: "delta", data: { text: String(payload.text ?? "") } };
    case "client_tool_calls": {
      const calls = Array.isArray(payload.calls) ? payload.calls.filter(isRecord) : [];
      return {
        type: "client_tool_calls",
        data: {
          turn_id: typeof payload.turn_id === "string" ? payload.turn_id : undefined,
          calls: calls.map((c) => ({
            call_id: String(c.call_id ?? ""),
            name: String(c.name ?? ""),
            arguments: c.arguments,
          })),
        },
      };
    }
    case "done":
      return {
        type: "done",
        data: {
          conversation_id: String(payload.conversation_id ?? ""),
          turn_id: String(payload.turn_id ?? ""),
          backend: String(payload.backend ?? ""),
          usage: isRecord(payload.usage) ? payload.usage : null,
        },
      };
    case "error":
      return {
        type: "error",
        data: { code: String(payload.code ?? "error"), message: String(payload.message ?? "") },
      };
    default:
      return null;
  }
}
