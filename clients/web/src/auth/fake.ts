import type { Auth, AuthSession } from "./types";

/** Dev-only stand-in so the UI can run against the mock SSE server. Never imported in production. */
export function createFakeAuth(): Auth {
  const KEY = "fake-auth";
  const session: AuthSession = { name: "Dev Tester", username: "dev@voltrieve.example" };
  return {
    kind: "fake",
    async init() {
      try {
        return sessionStorage.getItem(KEY) ? session : null;
      } catch {
        return null;
      }
    },
    async signIn() {
      try { sessionStorage.setItem(KEY, "1"); } catch { /* ignore */ }
      location.reload();
    },
    async signOut() {
      try { sessionStorage.removeItem(KEY); } catch { /* ignore */ }
      location.reload();
    },
    async getToken() {
      return "dev-fake-token";
    },
  };
}
