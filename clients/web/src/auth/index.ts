import type { AppConfig } from "../config";
import type { Auth, AuthSession } from "./types";

export type { Auth, AuthSession };

export interface AuthBoot {
  auth: Auth;
  session: AuthSession | null;
}

let boot: Promise<AuthBoot> | undefined;

/** Create and initialise auth once per page load (StrictMode runs effects twice). */
export function bootAuth(config: AppConfig): Promise<AuthBoot> {
  boot ??= (async () => {
    const auth = await createAuth(config);
    return { auth, session: await auth.init() };
  })();
  boot.catch(() => {
    boot = undefined;
  });
  return boot;
}

async function createAuth(config: AppConfig): Promise<Auth> {
  // import.meta.env.DEV is a build-time constant: in production this branch,
  // and the whole fake module, is removed from the bundle.
  if (import.meta.env.DEV && config.fakeAuth) {
    const { createFakeAuth } = await import("./fake");
    return createFakeAuth();
  }
  const { createMsalAuth } = await import("./msal");
  return createMsalAuth(config);
}
