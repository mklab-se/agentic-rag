import type { AppConfig } from "../config";
import type { Auth } from "./types";

export type { Auth, AuthSession } from "./types";

export async function createAuth(config: AppConfig): Promise<Auth> {
  // import.meta.env.DEV is a build-time constant: in production this branch,
  // and the whole fake module, is removed from the bundle.
  if (import.meta.env.DEV && config.fakeAuth) {
    const { createFakeAuth } = await import("./fake");
    return createFakeAuth();
  }
  const { createMsalAuth } = await import("./msal");
  return createMsalAuth(config);
}
