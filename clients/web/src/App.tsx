import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { bootAuth, type Auth, type AuthSession } from "./auth";
import { streamChat, streamToolResults } from "./chat";
import { Chat } from "./components/Chat";
import { Header } from "./components/Header";
import { ConfigMissing, Loading, SignIn } from "./components/Notices";
import { Recorder } from "./components/Recorder";
import { readConfig, type AppConfig } from "./config";
import { runClientTool, toolsFor, type Theme } from "./tools";
import { chatReducer, initialChatState } from "./turns";
import type { Backend, ClientToolCall } from "./types";

// A client tool result can lead to another tool call, but not forever.
const MAX_TOOL_ROUNDS = 5;

function initialTheme(): Theme {
  const set = document.documentElement.dataset.theme;
  if (set === "light" || set === "dark") return set;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function initialGaugeOn(): boolean {
  try {
    return localStorage.getItem("gauge") === "on";
  } catch {
    return false;
  }
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
        const { auth: a, session: s } = await bootAuth(config);
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
  const [gauge, setGauge] = useState(0);
  const [gaugeOn, setGaugeOn] = useState(initialGaugeOn);
  const [view, setView] = useState<"chat" | "recorder">("chat");
  const abort = useRef<AbortController | null>(null);
  const conversationId = useRef<string | undefined>(undefined);
  conversationId.current = state.conversationId;

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => () => abort.current?.abort(), []);

  const applyTheme = useCallback((next: Theme) => {
    setTheme(next);
    try {
      localStorage.setItem("theme", next);
    } catch {
      /* storage may be unavailable */
    }
  }, []);

  const send = useCallback(
    async (message: string) => {
      setBusy(true);
      const correlationId = crypto.randomUUID();
      dispatch({ type: "start", message, backend, correlationId });
      const ctrl = new AbortController();
      abort.current = ctrl;
      try {
        const token = await auth.getToken();
        let events = streamChat(
          {
            apiUrl: config.apiUrl,
            token,
            backend,
            conversationId: conversationId.current,
            message,
            correlationId,
            clientTools: toolsFor(gaugeOn),
          },
          ctrl.signal,
        );
        for (let round = 0; round <= MAX_TOOL_ROUNDS; round += 1) {
          let paused: { turnId: string; conversationId: string; calls: ClientToolCall[] } | undefined;
          for await (const event of events) {
            dispatch({ type: "event", event });
            if (event.type === "client_tool_calls" && event.data.turn_id && event.data.conversation_id) {
              paused = {
                turnId: event.data.turn_id,
                conversationId: event.data.conversation_id,
                calls: event.data.calls,
              };
            }
          }
          if (!paused) break;
          const results = paused.calls.map((call) => ({
            call_id: call.call_id,
            output: runClientTool(call, { setTheme: applyTheme, setGauge }),
          }));
          events = streamToolResults(
            {
              apiUrl: config.apiUrl,
              token: await auth.getToken(),
              backend,
              conversationId: paused.conversationId,
              turnId: paused.turnId,
              correlationId,
              results,
            },
            ctrl.signal,
          );
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
    [applyTheme, auth, backend, config.apiUrl, gaugeOn],
  );

  function toggleGauge() {
    const next = !gaugeOn;
    setGaugeOn(next);
    try {
      localStorage.setItem("gauge", next ? "on" : "off");
    } catch {
      /* storage may be unavailable */
    }
  }

  function toggleTheme() {
    applyTheme(theme === "dark" ? "light" : "dark");
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
        gaugeOn={gaugeOn}
        onToggleGauge={toggleGauge}
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
        <Chat state={state} busy={busy} gauge={gaugeOn ? gauge : undefined} onSend={(t) => void send(t)} />
        <Recorder state={state} />
      </main>
    </div>
  );
}
