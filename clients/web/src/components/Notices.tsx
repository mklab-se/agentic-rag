import type { Auth } from "../auth";

export function ConfigMissing({ missing }: { missing: string[] }) {
  return (
    <main className="gate">
      <div className="gate-card">
        <p className="eyebrow">Configuration</p>
        <h1>This build is not configured</h1>
        <p>
          The app reads its settings from build-time <code>VITE_*</code> variables. These are missing:
        </p>
        <ul className="missing">
          {missing.map((m) => (
            <li key={m}>
              <code>{m}</code>
            </li>
          ))}
        </ul>
        <p className="muted">
          Copy <code>.env.example</code> to <code>.env.local</code>, fill it in and restart. None of the values are secrets.
        </p>
      </div>
    </main>
  );
}

export function SignIn({ auth, error }: { auth: Auth; error?: string }) {
  return (
    <main className="gate">
      <div className="gate-card">
        <p className="eyebrow">Voltrieve · Flight Recorder</p>
        <h1>Watch an agent work</h1>
        <p>
          Ask about Voltrieve vehicles and see every hop the agent takes: token check, model calls, retrieval, tools. This
          web app declares no client tools of its own.
        </p>
        {error && <p className="notice error">{error}</p>}
        <button className="primary" onClick={() => void auth.signIn()}>
          {auth.kind === "fake" ? "Continue as dev tester" : "Sign in with Microsoft"}
        </button>
        {auth.kind === "fake" && <p className="muted">Dev-only fake sign-in against the mock server.</p>}
      </div>
    </main>
  );
}

export function Loading() {
  return (
    <main className="gate">
      <p className="muted">Starting…</p>
    </main>
  );
}
