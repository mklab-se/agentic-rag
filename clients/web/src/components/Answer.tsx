import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

// The text comes from a model, so raw HTML is dropped and links open away from the app.
const components: Components = {
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
  table: ({ children }) => (
    <div className="table-wrap">
      <table>{children}</table>
    </div>
  ),
};

export function Answer({ text }: { text: string }) {
  return (
    <div className="answer">
      <Markdown remarkPlugins={[remarkGfm]} skipHtml components={components}>
        {text}
      </Markdown>
    </div>
  );
}
