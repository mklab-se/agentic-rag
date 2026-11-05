import { describe, expect, it, vi } from "vitest";
import { buildChatRequest, buildToolResultsRequest } from "./chat";
import { CLIENT_TOOLS, runClientTool, toolsFor } from "./tools";

describe("set_theme", () => {
  it("changes the theme and tells the model", () => {
    const setTheme = vi.fn();
    const output = runClientTool({ call_id: "1", name: "set_theme", arguments: '{"theme":"dark"}' }, { setTheme, setGauge: vi.fn() });
    expect(setTheme).toHaveBeenCalledWith("dark");
    expect(output).toBe("The theme is now dark.");
  });

  it("refuses an unknown theme without changing anything", () => {
    const setTheme = vi.fn();
    const output = runClientTool({ call_id: "1", name: "set_theme", arguments: '{"theme":"pink"}' }, { setTheme, setGauge: vi.fn() });
    expect(setTheme).not.toHaveBeenCalled();
    expect(output).toContain("Error");
  });

  it("answers an unknown tool with text so that the turn can finish", () => {
    const output = runClientTool({ call_id: "1", name: "beep", arguments: "{}" }, { setTheme: vi.fn(), setGauge: vi.fn() });
    expect(output).toContain("no tool named 'beep'");
  });

  it("survives arguments that are not JSON", () => {
    const output = runClientTool({ call_id: "1", name: "set_theme", arguments: "{oops" }, { setTheme: vi.fn(), setGauge: vi.fn() });
    expect(output).toContain("Error");
  });
});

describe("the gauge switch", () => {
  const names = (gaugeOn: boolean) => toolsFor(gaugeOn).map((t) => t.name);

  it("offers set_gauge only while the gauge is on", () => {
    expect(names(true)).toContain("set_gauge");
    expect(names(false)).not.toContain("set_gauge");
    expect(names(false)).toContain("set_theme");
    expect(toolsFor(true)).toEqual(CLIENT_TOOLS);
  });

  it("leaves it out of the request when off", () => {
    const { init } = buildChatRequest({
      apiUrl: "https://api",
      token: "t",
      backend: "prompt",
      message: "hi",
      correlationId: "x",
      clientTools: toolsFor(false),
    });
    const body = JSON.parse(init.body as string);
    expect(body.client_tools.map((t: { name: string }) => t.name)).toEqual(["set_theme"]);
  });
});

describe("set_gauge", () => {
  it("moves the gauge and tells the model", () => {
    const setGauge = vi.fn();
    const output = runClientTool({ call_id: "1", name: "set_gauge", arguments: '{"value":70}' }, { setTheme: vi.fn(), setGauge });
    expect(setGauge).toHaveBeenCalledWith(70);
    expect(output).toBe("The gauge now shows 70.");
  });

  it.each(['{"value":101}', '{"value":-1}', '{"value":1.5}', '{"value":"70"}', "{}"])("refuses %s", (args) => {
    const setGauge = vi.fn();
    const output = runClientTool({ call_id: "1", name: "set_gauge", arguments: args }, { setTheme: vi.fn(), setGauge });
    expect(setGauge).not.toHaveBeenCalled();
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
