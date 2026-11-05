import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Answer } from "./components/Answer";

const html = (text: string) => renderToStaticMarkup(<Answer text={text} />);

describe("Answer", () => {
  it("renders bold text and lists", () => {
    const out = html("**Lumen**\n\n- one\n- two");
    expect(out).toContain("<strong>Lumen</strong>");
    expect(out).toContain("<li>one</li>");
  });

  it("renders a table, wrapped so that it can scroll", () => {
    const out = html("| Model | Price |\n|---|---:|\n| Ragn | 549,000 SEK |");
    expect(out).toContain('class="table-wrap"');
    expect(out).toContain("<th>Model</th>");
    expect(out).toContain("549,000 SEK");
  });

  it("drops raw HTML from the model", () => {
    const out = html('Hello <img src=x onerror="alert(1)"> <script>alert(2)</script>');
    expect(out).not.toContain("<img");
    expect(out).not.toContain("<script");
  });

  it("refuses script links", () => {
    expect(html("[click](javascript:alert(1))")).not.toContain("javascript:");
  });

  it("opens links safely in a new tab", () => {
    expect(html("[guide](https://example.com)")).toContain('rel="noopener noreferrer"');
  });
});
