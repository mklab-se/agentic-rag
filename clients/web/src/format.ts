export function formatElapsed(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`;
}

/** Map a free-form component label to one of a few stable colour families. */
export function componentFamily(component: string): string {
  const c = component.toLowerCase();
  if (/auth|token|identity|entra/.test(c)) return "auth";
  if (/model|llm|openai|completion/.test(c)) return "model";
  if (/search|retriev|knowledge|kb|index/.test(c)) return "search";
  if (/dealer|tool/.test(c)) return "tool";
  if (/agent|loop|prompt|hosted|backend|foundry/.test(c)) return "agent";
  if (/api|http|server/.test(c)) return "api";
  return "other";
}
