export function formatElapsed(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`;
}

/** The components the API (and the agent code behind it) put on trace events, by colour family. */
const FAMILIES: Record<string, string> = {
  auth: "auth",
  api: "api",
  model: "model",
  tools: "tool",
  search: "search",
};

export function componentFamily(component: string): string {
  return FAMILIES[component] ?? "other";
}
