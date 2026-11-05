import type { ClientToolCall } from "./types";

export type Theme = "light" | "dark";

/** What this client can do. A copy is in WEB_TOOLS in agents/prompt/create_agents.py. */
export const CLIENT_TOOLS = [
  {
    name: "set_theme",
    description: "Switch the web app between its light and dark theme.",
    parameters: {
      type: "object",
      properties: { theme: { type: "string", enum: ["light", "dark"] } },
      required: ["theme"],
    },
  },
];

export interface ToolHandlers {
  setTheme: (theme: Theme) => void;
}

function parseArguments(value: unknown): Record<string, unknown> {
  if (typeof value !== "string") return typeof value === "object" && value ? (value as Record<string, unknown>) : {};
  try {
    const parsed: unknown = JSON.parse(value);
    return typeof parsed === "object" && parsed ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

/** Run one tool and return text for the model. A failure is text too, so the turn can go on. */
export function runClientTool(call: ClientToolCall, handlers: ToolHandlers): string {
  if (call.name !== "set_theme") return `Error: this client has no tool named '${call.name}'.`;
  const { theme } = parseArguments(call.arguments);
  if (theme !== "light" && theme !== "dark") return "Error: theme must be light or dark.";
  handlers.setTheme(theme);
  return `The theme is now ${theme}.`;
}
