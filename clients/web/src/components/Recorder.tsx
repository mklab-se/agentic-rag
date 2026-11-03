import { useEffect, useRef } from "react";
import { componentFamily, formatElapsed } from "../format";
import type { ChatState, Turn } from "../turns";

function totalMs(t: Turn): number {
  return t.entries.reduce((m, e) => (e.kind === "trace" ? Math.max(m, e.elapsedMs) : m), 0);
}

function usageText(u: Record<string, unknown> | null): string {
  if (!u) return "";
  const parts = Object.entries(u)
    .filter(([, v]) => typeof v === "number")
    .map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`);
  return parts.join(" · ");
}

export function Recorder({ state }: { state: ChatState }) {
  const endRef = useRef<HTMLDivElement>(null);
  const count = state.turns.reduce((n, t) => n + t.entries.length, 0);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [count]);

  return (
    <section className="recorder" aria-label="Event timeline">
      <div className="rec-head">
        <span className="rec-dot" data-live={state.turns.some((t) => t.status === "streaming")} />
        <h2>Event timeline</h2>
        <span className="muted">{count} events</span>
      </div>
      <div className="rec-scroll">
        {state.turns.length === 0 && (
          <p className="muted rec-empty">Nothing recorded yet. Events from the API appear here as they arrive, grouped per turn.</p>
        )}
        {state.turns.map((t) => (
          <article className="rec-turn" key={t.id}>
            <header>
              <span className="turn-no">Turn {t.id}</span>
              <span className="turn-q" title={t.userText}>
                {t.userText}
              </span>
              <span className="turn-meta">
                {t.requestedBackend}
                {totalMs(t) > 0 && ` · ${formatElapsed(totalMs(t))}`}
              </span>
            </header>
            <ol className="rail">
              {t.entries.map((e, i) =>
                e.kind === "trace" ? (
                  <li key={i} className="ev" data-fam={componentFamily(e.component)}>
                    <time>+{formatElapsed(e.elapsedMs)}</time>
                    <div>
                      <span className="comp">{e.component}</span>
                      <span className="step">{e.step}</span>
                      {e.detail && <p className="detail">{e.detail}</p>}
                    </div>
                  </li>
                ) : e.kind === "done" ? (
                  <li key={i} className="ev end" data-fam="done">
                    <time>done</time>
                    <div>
                      <span className="comp">{e.backend}</span>
                      <span className="step">turn complete</span>
                      {usageText(e.usage) && <p className="detail">{usageText(e.usage)}</p>}
                    </div>
                  </li>
                ) : (
                  <li key={i} className="ev end" data-fam="error">
                    <time>error</time>
                    <div>
                      <span className="comp">{e.code}</span>
                      <span className="step">{e.message}</span>
                    </div>
                  </li>
                ),
              )}
              {t.status === "streaming" && (
                <li className="ev live" data-fam="other">
                  <time>…</time>
                  <div>
                    <span className="step">recording</span>
                  </div>
                </li>
              )}
            </ol>
          </article>
        ))}
        <div ref={endRef} />
      </div>
    </section>
  );
}
