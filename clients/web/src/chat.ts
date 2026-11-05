import { parseServerEvent } from "./events";
import { createSseParser } from "./sse";
import { CLIENT_TOOLS } from "./tools";
import type { Backend, ServerEvent } from "./types";

export interface ChatRequestInput {
  apiUrl: string;
  token: string;
  backend: Backend;
  conversationId?: string;
  message: string;
  /** One id for the whole turn, sent on every request of it. */
  correlationId: string;
}

export interface ToolResultsInput {
  apiUrl: string;
  token: string;
  backend: Backend;
  conversationId: string;
  turnId: string;
  correlationId: string;
  results: { call_id: string; output: string }[];
}

type Sendable = Pick<ChatRequestInput, "apiUrl" | "token" | "backend" | "correlationId">;

function post(input: Sendable, path: string, body: unknown): { url: string; init: RequestInit } {
  return {
    url: `${input.apiUrl.replace(/\/+$/, "")}${path}`,
    init: {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        Authorization: `Bearer ${input.token}`,
        "X-Agent-Backend": input.backend,
        "X-Correlation-Id": input.correlationId,
      },
      body: JSON.stringify(body),
    },
  };
}

/** Build the POST /chat request, with the tools this client can run. */
export function buildChatRequest(input: ChatRequestInput): { url: string; init: RequestInit } {
  const body: { conversation_id?: string; message: string; client_tools: typeof CLIENT_TOOLS } = {
    message: input.message,
    client_tools: CLIENT_TOOLS,
  };
  if (input.conversationId) body.conversation_id = input.conversationId;
  return post(input, "/chat", body);
}

/** Build the POST /chat/tool-results request that continues a paused turn. */
export function buildToolResultsRequest(input: ToolResultsInput): { url: string; init: RequestInit } {
  return post(input, "/chat/tool-results", {
    conversation_id: input.conversationId,
    turn_id: input.turnId,
    results: input.results,
  });
}

function httpError(status: number): ServerEvent {
  const message =
    status === 401
      ? "The API rejected the access token (401). Try signing in again."
      : status === 403
        ? "The API refused the request (403). Check that your account has the Chat.User role, that the token carries the access_as_user scope, and that the conversation is yours."
        : `The API answered with HTTP ${status}.`;
  return { type: "error", data: { code: `http_${status}`, message } };
}

/** POST /chat and yield typed events as they arrive. Never throws for network or HTTP errors. */
export function streamChat(
  input: ChatRequestInput,
  signal?: AbortSignal,
  fetchImpl: typeof fetch = fetch,
): AsyncGenerator<ServerEvent> {
  return stream(input.apiUrl, buildChatRequest(input), signal, fetchImpl);
}

/** POST /chat/tool-results, with the same stream as /chat. */
export function streamToolResults(
  input: ToolResultsInput,
  signal?: AbortSignal,
  fetchImpl: typeof fetch = fetch,
): AsyncGenerator<ServerEvent> {
  return stream(input.apiUrl, buildToolResultsRequest(input), signal, fetchImpl);
}

async function* stream(
  apiUrl: string,
  { url, init }: { url: string; init: RequestInit },
  signal: AbortSignal | undefined,
  fetchImpl: typeof fetch,
): AsyncGenerator<ServerEvent> {
  let res: Response;
  try {
    res = await fetchImpl(url, { ...init, signal });
  } catch (e) {
    if (signal?.aborted) return;
    yield {
      type: "error",
      data: { code: "network", message: `Could not reach the API at ${apiUrl}.` },
    };
    return;
  }
  if (!res.ok || !res.body) {
    yield httpError(res.status);
    return;
  }

  const parser = createSseParser();
  const decoder = new TextDecoder();
  const reader = res.body.getReader();
  let terminal = false;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      const messages = done ? parser.flush() : parser.feed(decoder.decode(value, { stream: true }));
      for (const m of messages) {
        const ev = parseServerEvent(m);
        if (ev) {
          if (ev.type === "done" || ev.type === "error" || ev.type === "client_tool_calls") terminal = true;
          yield ev;
        }
      }
      if (done) break;
    }
    if (!terminal && !signal?.aborted) {
      yield {
        type: "error",
        data: { code: "incomplete", message: "The stream ended before the turn completed." },
      };
    }
  } catch {
    if (signal?.aborted) return;
    yield { type: "error", data: { code: "stream", message: "The event stream was interrupted." } };
  } finally {
    reader.releaseLock();
  }
}
