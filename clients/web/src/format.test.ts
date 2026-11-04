import { describe, expect, it } from "vitest";
import { componentFamily, formatElapsed } from "./format";

describe("componentFamily", () => {
  it("maps the five components the API emits", () => {
    expect(["auth", "api", "model", "tools", "search"].map(componentFamily)).toEqual([
      "auth",
      "api",
      "model",
      "tool",
      "search",
    ]);
  });

  it("does not guess at other labels", () => {
    expect(componentFamily("dealer")).toBe("other");
    expect(componentFamily("")).toBe("other");
  });
});

describe("formatElapsed", () => {
  it("switches to seconds at one second", () => {
    expect(formatElapsed(420)).toBe("420 ms");
    expect(formatElapsed(1500)).toBe("1.50 s");
    expect(formatElapsed(12500)).toBe("12.5 s");
  });
});
