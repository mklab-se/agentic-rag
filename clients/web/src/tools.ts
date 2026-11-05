import type { ClientToolCall } from "./types";

export type Theme = "light" | "dark";

/**
 * What this client can do. set_theme has a copy in WEB_TOOLS in agents/prompt/create_agents.py.
 * set_gauge has none on purpose: the prompt agent refuses a tool outside its definition, and this
 * shows that limit.
 */
export const CLIENT_TOOLS = [
  {
    name: "set_gauge",
    description:
      "Set the speedometer gauge in this app to a value from 0 to 100. Use it when the user asks to set or change the gauge.",
    parameters: {
      type: "object",
      properties: { value: { type: "integer", minimum: 0, maximum: 100 } },
      required: ["value"],
    },
  },
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

/** The tools to offer: set_gauge only while the gauge is on. */
export function toolsFor(gaugeOn: boolean): typeof CLIENT_TOOLS {
  return CLIENT_TOOLS.filter((tool) => gaugeOn || tool.name !== "set_gauge");
}

export interface ToolHandlers {
  setTheme: (theme: Theme) => void;
  setGauge: (value: number) => void;
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
  if (call.name === "set_gauge") {
    const { value } = parseArguments(call.arguments);
    if (typeof value !== "number" || !Number.isInteger(value) || value < 0 || value > 100) {
      return "Error: value must be a whole number from 0 to 100.";
    }
    handlers.setGauge(value);
    return `The gauge now shows ${value}.`;
  }
  if (call.name !== "set_theme") return `Error: this client has no tool named '${call.name}'.`;
  const { theme } = parseArguments(call.arguments);
  if (theme !== "light" && theme !== "dark") return "Error: theme must be light or dark.";
  handlers.setTheme(theme);
  return `The theme is now ${theme}.`;
}
