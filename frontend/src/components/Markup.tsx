import { animated, config, useSpring, useTrail } from "@react-spring/web";
import {
  createContext,
  isValidElement,
  useContext,
  useRef,
  useState,
  type ComponentProps,
  type ReactNode,
} from "react";
import ReactMarkdown from "react-markdown";
import { useCodeRunner } from "../hooks/useCodeRunner";
import { runtimeFor } from "../lib/runner/languages";
import { prepare } from "../lib/markup/tags";
import { rehypePlugins, remarkPlugins } from "../lib/markup/plugins";
import { blockButton, OutputPanel, RunButtons } from "./CodeRunner";

function explicitLanguage(children: ReactNode): string | undefined {
  if (!isValidElement<{ "data-lang"?: unknown }>(children)) return undefined;
  const lang = children.props["data-lang"];
  return typeof lang === "string" ? lang : undefined;
}

function CodeBlock({ children }: ComponentProps<"pre">) {
  const ref = useRef<HTMLPreElement>(null);
  const [label, setLabel] = useState("Copy");
  const streaming = useContext(StreamingContext);
  // A block that is still streaming is incomplete code, so it cannot be run yet.
  const runtime = streaming ? null : runtimeFor(explicitLanguage(children));
  const runner = useCodeRunner(runtime);

  async function copy() {
    try {
      await navigator.clipboard.writeText(ref.current?.textContent ?? "");
      setLabel("Copied");
    } catch {
      setLabel("Failed");
    }
    setTimeout(() => setLabel("Copy"), 1500);
  }

  const run = () => runner.run(ref.current?.textContent ?? "");

  return (
    <div className="relative my-4">
      <div className="overflow-hidden rounded-[10px]">
        <pre ref={ref} className="overflow-x-auto">
          {children}
        </pre>
        {runtime && (
          <OutputPanel
            state={runner.state}
            runtime={runtime}
            onClear={runner.clear}
            onRerun={run}
            onAnswer={runner.submitAnswer}
          />
        )}
      </div>
      <div className="absolute right-1.5 top-1.5 flex items-center gap-1.5">
        {runtime && <RunButtons runtime={runtime} busy={runner.busy} onRun={run} onStop={runner.stop} />}
        <button type="button" onClick={copy} aria-label="Copy code" className={blockButton}>
          {label}
        </button>
      </div>
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

// Pieces of the generic UI sketch, in build-up order. `box` sizes and places the piece, `look`
// paints it; the pulse runs on an inner element because a CSS animation would override the
// opacity the build-up spring sets on the outer one.
const SKETCH = [
  { box: "h-6 w-6 shrink-0", look: "rounded-full bg-[color-mix(in_srgb,var(--accent)_35%,transparent)]" },
  { box: "h-2 w-16", look: "rounded-full bg-border" },
  { box: "h-2 w-10", look: "rounded-full bg-border" },
  { box: "h-5 w-[58%] self-start", look: "rounded-xl bg-border" },
  { box: "h-5 w-[42%] self-end", look: "rounded-xl border border-border bg-surface" },
  { box: "h-5 w-[66%] self-start", look: "rounded-xl bg-border" },
] as const;

// useTrail chains each spring to the previous one, so the stagger is spring lag, not fixed
// milliseconds. Reduced motion needs no branch here: main.tsx makes springs jump to the end.
function DrawingPlaceholder() {
  const trail = useTrail(SKETCH.length, {
    from: { opacity: 0, y: 6 },
    to: { opacity: 1, y: 0 },
    config: config.gentle,
  });
  const piece = (i: number) => {
    const sketch = SKETCH[i];
    if (!sketch) return null;
    return (
      <animated.div key={i} aria-hidden className={sketch.box} style={trail[i]}>
        <div
          className={`h-full w-full ${sketch.look} motion-safe:animate-sketch-pulse`}
          style={{ animationDelay: `${900 + i * 150}ms` }}
        />
      </animated.div>
    );
  };
  return (
    <div
      role="status"
      aria-label="Drawing"
      className="relative my-4 h-40 overflow-hidden rounded-2xl border border-border bg-bubble p-4 font-sans"
    >
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2.5">
          {piece(0)}
          <div className="flex flex-col gap-1.5">
            {piece(1)}
            {piece(2)}
          </div>
        </div>
        {SKETCH.slice(3).map((_, i) => piece(i + 3))}
      </div>
      <span className="absolute right-3 top-2.5 flex items-center gap-0.5 text-xs text-muted">
        Drawing
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            aria-hidden
            className="opacity-70 motion-safe:animate-dot-pulse"
            style={{ animationDelay: `${i * 200}ms` }}
          >
            .
          </span>
        ))}
      </span>
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 hidden bg-[linear-gradient(100deg,transparent_30%,color-mix(in_srgb,var(--accent)_14%,transparent)_50%,transparent_70%)] motion-safe:block motion-safe:animate-shimmer"
      />
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
