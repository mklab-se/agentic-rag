/** Pure incremental parser for text/event-stream. No I/O, no DOM. */

export interface SseMessage {
  event: string;
  data: string;
}

export interface SseParser {
  /** Feed a decoded text chunk; returns the messages completed by it. */
  feed(chunk: string): SseMessage[];
  /** Call at end of stream; dispatches a final message not ended by a blank line. */
  flush(): SseMessage[];
}

export function createSseParser(): SseParser {
  let buffer = "";
  let event = "";
  let data: string[] = [];
  let sawCR = false;

  function dispatch(out: SseMessage[]): void {
    if (data.length > 0) out.push({ event: event || "message", data: data.join("\n") });
    event = "";
    data = [];
  }

  function line(text: string, out: SseMessage[]): void {
    if (text === "") return dispatch(out);
    if (text.startsWith(":")) return; // comment / keep-alive
    const colon = text.indexOf(":");
    const field = colon === -1 ? text : text.slice(0, colon);
    let value = colon === -1 ? "" : text.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
    // id and retry are irrelevant to this client.
  }

  function consume(text: string, out: SseMessage[]): void {
    for (const ch of text) {
      if (sawCR && ch === "\n") {
        sawCR = false;
        continue; // second half of CRLF, line already ended
      }
      sawCR = false;
      if (ch === "\n" || ch === "\r") {
        sawCR = ch === "\r";
        line(buffer, out);
        buffer = "";
      } else {
        buffer += ch;
      }
    }
  }

  return {
    feed(chunk) {
      const out: SseMessage[] = [];
      consume(chunk, out);
      return out;
    },
    flush() {
      const out: SseMessage[] = [];
      if (buffer !== "") {
        line(buffer, out);
        buffer = "";
      }
      dispatch(out);
      return out;
    },
  };
}
