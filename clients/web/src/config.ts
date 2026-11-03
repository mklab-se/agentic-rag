export interface AppConfig {
  apiUrl: string;
  tenantId: string;
  clientId: string;
  scope: string;
  /** Dev-only mock sign-in; always false in production builds. */
  fakeAuth: boolean;
}

export type ConfigResult = { ok: true; config: AppConfig } | { ok: false; missing: string[] };

type Env = Record<string, string | undefined>;

const REQUIRED = ["VITE_API_URL", "VITE_ENTRA_TENANT_ID", "VITE_ENTRA_CLIENT_ID", "VITE_API_SCOPE"] as const;

/** All configuration comes from build-time VITE_* variables. No secrets. */
export function readConfig(env: Env, isDev: boolean): ConfigResult {
  const fakeAuth = isDev && env.VITE_DEV_FAKE_AUTH === "true";
  const required = fakeAuth ? (["VITE_API_URL"] as const) : REQUIRED;
  const missing = required.filter((k) => !env[k]?.trim());
  if (missing.length > 0) return { ok: false, missing: [...missing] };
  return {
    ok: true,
    config: {
      apiUrl: env.VITE_API_URL!.trim(),
      tenantId: env.VITE_ENTRA_TENANT_ID?.trim() ?? "",
      clientId: env.VITE_ENTRA_CLIENT_ID?.trim() ?? "",
      scope: env.VITE_API_SCOPE?.trim() ?? "",
      fakeAuth,
    },
  };
}
