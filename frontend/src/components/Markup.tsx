import { animated, useSpring } from "@react-spring/web";
import { createContext, useContext, useRef, useState, type ComponentProps } from "react";
import ReactMarkdown from "react-markdown";
import { prepare } from "../lib/markup/tags";
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

const StreamingContext = createContext(false);
const InBlockContext = createContext(false);

// Top-level model-styled blocks rise in when they appear during a stream. Replies that were
// already finished on first mount (reloads, history) mount with streaming off and skip it.
// Reduced motion is handled globally: main.tsx makes every spring jump to its end state.
function Reveal(props: ComponentProps<"div">) {
  const style = useSpring({
    from: { opacity: 0, y: 12 },
    to: { opacity: 1, y: 0 },
    config: { tension: 170, friction: 22 },
  });
  return <animated.div {...props} style={{ ...props.style, ...style }} />;
}

function StyledBlock(all: ComponentProps<"div"> & { node?: unknown }) {
  // react-markdown passes its hast `node`, which must not reach the DOM.
  const props = { ...all };
  delete props.node;
  const nested = useContext(InBlockContext);
  const streaming = useRef(useContext(StreamingContext)).current;
  if (nested) return <div {...props} />;
  return (
    <InBlockContext.Provider value>
      {streaming && props.style ? <Reveal {...props} /> : <div {...props} />}
    </InBlockContext.Provider>
  );
}

function DrawingPlaceholder() {
  return (
    <div
      role="status"
      aria-label="Drawing"
      className="my-4 flex h-40 items-center justify-center rounded-2xl border border-border bg-bubble font-sans text-sm text-muted motion-safe:animate-pulse"
    >
      Drawing…
    </div>
  );
}

const components = { pre: CodeBlock, div: StyledBlock };

export function Markup({ text, streaming = false }: { text: string; streaming?: boolean }) {
  const { source, drawing } = prepare(text, streaming);
  return (
    <StreamingContext.Provider value={streaming}>
      <div className="prose max-w-[62ch] prose-p:my-[0.8em] [&>:first-child]:mt-0 [&>:last-child]:mb-0">
        <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={components}>
          {source}
        </ReactMarkdown>
        {drawing && <DrawingPlaceholder />}
      </div>
    </StreamingContext.Provider>
  );
}
