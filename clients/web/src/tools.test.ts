import { describe, expect, it, vi } from "vitest";
import { buildToolResultsRequest } from "./chat";
import { runClientTool } from "./tools";

describe("set_theme", () => {
  it("changes the theme and tells the model", () => {
    const setTheme = vi.fn();
    const output = runClientTool({ call_id: "1", name: "set_theme", arguments: '{"theme":"dark"}' }, { setTheme });
    expect(setTheme).toHaveBeenCalledWith("dark");
    expect(output).toBe("The theme is now dark.");
  });

  it("refuses an unknown theme without changing anything", () => {
    const setTheme = vi.fn();
    const output = runClientTool({ call_id: "1", name: "set_theme", arguments: '{"theme":"pink"}' }, { setTheme });
    expect(setTheme).not.toHaveBeenCalled();
    expect(output).toContain("Error");
  });

  it("answers an unknown tool with text so that the turn can finish", () => {
    const output = runClientTool({ call_id: "1", name: "beep", arguments: "{}" }, { setTheme: vi.fn() });
    expect(output).toContain("no tool named 'beep'");
  });

  it("survives arguments that are not JSON", () => {
    const output = runClientTool({ call_id: "1", name: "set_theme", arguments: "{oops" }, { setTheme: vi.fn() });
    expect(output).toContain("Error");
  });
});

describe("the tool results request", () => {
  it("continues the paused turn on the same correlation id", () => {
    const { url, init } = buildToolResultsRequest({
      apiUrl: "https://api/",
      token: "t",
      backend: "loop",
      conversationId: "c1",
      turnId: "t1",
      correlationId: "x",
      results: [{ call_id: "1", output: "ok" }],
    });
    expect(url).toBe("https://api/chat/tool-results");
    expect(JSON.parse(init.body as string)).toEqual({
      conversation_id: "c1",
      turn_id: "t1",
      results: [{ call_id: "1", output: "ok" }],
    });
    expect((init.headers as Record<string, string>)["X-Correlation-Id"]).toBe("x");
  });
});
