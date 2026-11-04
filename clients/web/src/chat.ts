import { parseServerEvent } from "./events";
import { createSseParser } from "./sse";
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

/**
 * Build the POST /chat request. The body deliberately has no `client_tools`
 * key: this client exposes no tools, which is part of what the demo shows.
 */
export function buildChatRequest(input: ChatRequestInput): { url: string; init: RequestInit } {
  const body: { conversation_id?: string; message: string } = { message: input.message };
  if (input.conversationId) body.conversation_id = input.conversationId;
  return {
    url: `${input.apiUrl.replace(/\/+$/, "")}/chat`,
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
export async function* streamChat(
  input: ChatRequestInput,
  signal?: AbortSignal,
  fetchImpl: typeof fetch = fetch,
): AsyncGenerator<ServerEvent> {
  const { url, init } = buildChatRequest(input);
  let res: Response;
  try {
    res = await fetchImpl(url, { ...init, signal });
  } catch (e) {
    if (signal?.aborted) return;
    yield {
      type: "error",
      data: { code: "network", message: `Could not reach the API at ${input.apiUrl}.` },
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
