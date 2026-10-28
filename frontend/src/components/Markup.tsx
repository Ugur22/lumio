import { useRef, useState, type ComponentProps } from "react";
import ReactMarkdown from "react-markdown";
import { applyTags } from "../lib/markup/tags";
import { rehypePlugins, remarkPlugins } from "../lib/markup/plugins";

function CodeBlock({ children }: ComponentProps<"pre">) {
  const ref = useRef<HTMLPreElement>(null);
  const [label, setLabel] = useState("Copy");

  async function copy() {
    try {
      await navigator.clipboard.writeText(ref.current?.textContent ?? "");
      setLabel("Copied");
    } catch {
      setLabel("Failed");
    }
    setTimeout(() => setLabel("Copy"), 1500);
  }

  return (
    <div className="relative my-4">
      <pre ref={ref} className="overflow-x-auto">
        {children}
      </pre>
      <button
        type="button"
        onClick={copy}
        aria-label="Copy code"
        className="absolute right-1.5 top-1.5 rounded-lg border border-[#444c56] px-2 py-0.5 font-sans text-xs text-[#c9d1d9] hover:brightness-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
      >
        {label}
      </button>
    </div>
  );
}

export function Markup({ text, streaming = false }: { text: string; streaming?: boolean }) {
  return (
    <div className="prose max-w-none prose-p:my-[0.8em] [&>:first-child]:mt-0 [&>:last-child]:mb-0">
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        rehypePlugins={rehypePlugins}
        components={{ pre: CodeBlock }}
      >
        {applyTags(text, streaming)}
      </ReactMarkdown>
    </div>
  );
}
