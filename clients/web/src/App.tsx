import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { createAuth, type Auth, type AuthSession } from "./auth";
import { streamChat } from "./chat";
import { Chat } from "./components/Chat";
import { Header } from "./components/Header";
import { ConfigMissing, Loading, SignIn } from "./components/Notices";
import { Recorder } from "./components/Recorder";
import { readConfig, type AppConfig } from "./config";
import { chatReducer, initialChatState } from "./turns";
import type { Backend } from "./types";

type Theme = "light" | "dark";

function initialTheme(): Theme {
  const set = document.documentElement.dataset.theme;
  if (set === "light" || set === "dark") return set;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function App() {
  const result = readConfig(import.meta.env as Record<string, string | undefined>, import.meta.env.DEV);
  if (!result.ok) return <ConfigMissing missing={result.missing} />;
  return <Authed config={result.config} />;
}

function Authed({ config }: { config: AppConfig }) {
  const [auth, setAuth] = useState<Auth | null>(null);
  const [session, setSession] = useState<AuthSession | null>(null);
  const [error, setError] = useState<string>();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const a = await createAuth(config);
        const s = await a.init();
        if (cancelled) return;
        setAuth(a);
        setSession(s);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Sign-in could not start.");
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [config]);

  if (!ready) return <Loading />;
  if (!auth) return <ConfigMissing missing={[error ?? "authentication failed to initialise"]} />;
  if (!session) return <SignIn auth={auth} error={error} />;
  return <Workspace config={config} auth={auth} session={session} />;
}

function Workspace({ config, auth, session }: { config: AppConfig; auth: Auth; session: AuthSession }) {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const [backend, setBackend] = useState<Backend>("loop");
  const [busy, setBusy] = useState(false);
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [view, setView] = useState<"chat" | "recorder">("chat");
  const abort = useRef<AbortController | null>(null);
  const conversationId = useRef<string | undefined>(undefined);
  conversationId.current = state.conversationId;

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => () => abort.current?.abort(), []);

  const send = useCallback(
    async (message: string) => {
      setBusy(true);
      dispatch({ type: "start", message, backend });
      const ctrl = new AbortController();
      abort.current = ctrl;
      try {
        const token = await auth.getToken();
        for await (const event of streamChat(
          { apiUrl: config.apiUrl, token, backend, conversationId: conversationId.current, message },
          ctrl.signal,
        )) {
          dispatch({ type: "event", event });
        }
      } catch (e) {
        dispatch({
          type: "event",
          event: { type: "error", data: { code: "auth", message: e instanceof Error ? e.message : "Could not get a token." } },
        });
      } finally {
        setBusy(false);
      }
    },
    [auth, backend, config.apiUrl],
  );

  function toggleTheme() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    try {
      localStorage.setItem("theme", next);
    } catch {
      /* storage may be unavailable */
    }
  }

  return (
    <div className="app" data-view={view}>
      <Header
        backend={backend}
        onBackend={setBackend}
        session={session}
        onSignOut={() => void auth.signOut()}
        theme={theme}
        onToggleTheme={toggleTheme}
        onNewChat={() => dispatch({ type: "reset" })}
        busy={busy}
      />
      <nav className="tabs" aria-label="View">
        <button className={view === "chat" ? "on" : ""} onClick={() => setView("chat")}>
          Chat
        </button>
        <button className={view === "recorder" ? "on" : ""} onClick={() => setView("recorder")}>
          Timeline
        </button>
      </nav>
      <main className="panes">
        <Chat state={state} busy={busy} onSend={(t) => void send(t)} />
        <Recorder state={state} />
      </main>
    </div>
  );
}
