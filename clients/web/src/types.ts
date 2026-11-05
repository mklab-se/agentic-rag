export type Backend = "loop" | "prompt" | "hosted";
export const BACKENDS: readonly Backend[] = ["loop", "prompt", "hosted"];

export interface TraceData {
  step: string;
  component: string;
  detail: string;
  elapsed_ms: number;
}

export interface ClientToolCall {
  call_id: string;
  name: string;
  arguments: unknown;
}

export interface DoneData {
  conversation_id: string;
  turn_id: string;
  backend: string;
  usage?: Record<string, unknown> | null;
}

export type ServerEvent =
  | { type: "trace"; data: TraceData }
  | { type: "status"; data: { code: string; message: string } }
  | { type: "delta"; data: { text: string } }
  | { type: "client_tool_calls"; data: { turn_id?: string; calls: ClientToolCall[] } }
  | { type: "done"; data: DoneData }
  | { type: "error"; data: { code: string; message: string } };
