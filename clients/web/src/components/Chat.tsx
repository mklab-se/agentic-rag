import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import type { ChatState } from "../turns";
import { Answer } from "./Answer";

const STARTERS = [
  "What is the towing capacity of the Fjord?",
  "Which Voltrieve charges fastest?",
  "Is the Atlas in stock in Göteborg?",
  "Switch to the dark theme.",
];

interface Props {
  state: ChatState;
  busy: boolean;
  onSend: (text: string) => void;
}

export function Chat({ state, busy, onSend }: Props) {
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const last = state.turns[state.turns.length - 1];

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [state.turns.length, last?.answer, last?.status]);

  function submit(e?: FormEvent) {
    e?.preventDefault();
    const t = text.trim();
    if (!t || busy) return;
    setText("");
    onSend(t);
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) submit(e);
  }

  return (
    <section className="chat" aria-label="Chat">
      <div className="messages" aria-live="polite">
        {state.turns.length === 0 && (
          <div className="empty">
            <h2>Ask the agent something</h2>
            <p className="muted">Each answer appears here. The recorder shows how it got there.</p>
            <div className="starters">
              {STARTERS.map((s) => (
                <button key={s} className="chip" onClick={() => onSend(s)} disabled={busy}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {state.turns.map((t) => (
          <div className="exchange" key={t.id}>
            <div className="bubble user">{t.userText}</div>
            <div className={`bubble agent ${t.status}`}>
              {t.answer ? (
                <Answer text={t.answer} />
              ) : t.status === "streaming" ? (
                <p className="thinking" role="status" aria-label={t.activity ?? "Agent is working"}>
                  <i /><i /><i />
                  {t.activity && <span>{t.activity}</span>}
                </p>
              ) : null}
              {t.error && (
                <p className="notice error" role="alert">
                  {t.error}
                </p>
              )}
              {t.backend && <p className="meta">via {t.backend} · turn {t.id}</p>}
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </div>
      <form className="composer" onSubmit={submit}>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          placeholder="Ask about a Voltrieve model…"
          rows={1}
          aria-label="Message"
        />
        <button className="primary" type="submit" disabled={busy || !text.trim()}>
          Send
        </button>
      </form>
    </section>
  );
}
