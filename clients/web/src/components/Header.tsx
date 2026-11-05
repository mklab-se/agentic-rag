import type { AuthSession } from "../auth";
import { BACKENDS, type Backend } from "../types";

const HINT: Record<Backend, string> = {
  loop: "Own loop in the Web API",
  prompt: "Prompt agent in Foundry",
  hosted: "Hosted agent in Foundry",
};

interface Props {
  backend: Backend;
  onBackend: (b: Backend) => void;
  session: AuthSession;
  onSignOut: () => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  gaugeOn: boolean;
  onToggleGauge: () => void;
  onNewChat: () => void;
  busy: boolean;
}

export function Header({ backend, onBackend, session, onSignOut, theme, onToggleTheme, gaugeOn, onToggleGauge, onNewChat, busy }: Props) {
  return (
    <header className="topbar">
      <div className="brand">
        <svg viewBox="0 0 32 32" width="22" height="22" aria-hidden="true">
          <path d="M18 3 7 18h7l-1 11 11-15h-7z" fill="currentColor" />
        </svg>
        <span className="brand-name">Voltrieve</span>
        <span className="brand-sub">Flight Recorder</span>
      </div>
      <div className="seg" role="radiogroup" aria-label="Agent backend">
        {BACKENDS.map((b) => (
          <button
            key={b}
            role="radio"
            aria-checked={b === backend}
            className={b === backend ? "on" : ""}
            title={HINT[b]}
            disabled={busy}
            onClick={() => onBackend(b)}
          >
            {b}
          </button>
        ))}
      </div>
      <div className="actions">
        <button className="ghost" onClick={onNewChat} disabled={busy}>
          New chat
        </button>
        <button
          className="ghost"
          aria-pressed={gaugeOn}
          onClick={onToggleGauge}
          disabled={busy}
          title="Show the gauge and offer the set_gauge tool. The prompt agent refuses that tool."
        >
          Gauge
        </button>
        <button className="ghost icon" onClick={onToggleTheme} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} title="Toggle theme">
          {theme === "dark" ? "☀" : "☾"}
        </button>
        <button className="ghost who" onClick={onSignOut} title={`Signed in as ${session.username}. Click to sign out.`}>
          <span className="who-name">{session.name}</span>
          <span className="who-out">Sign out</span>
        </button>
      </div>
    </header>
  );
}
