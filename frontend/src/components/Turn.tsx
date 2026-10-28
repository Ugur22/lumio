import { animated, useSpring, useTrail } from "@react-spring/web";
import { useState, type ComponentPropsWithoutRef } from "react";
import { match } from "ts-pattern";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { APP_NAME } from "../lib/brand";
import { LumioMark } from "./icons";
import { Markup } from "./Markup";

export type Reply =
  | { kind: "text"; content: string; streaming?: boolean }
  | { kind: "thinking" }
  | { kind: "error"; message: string }
  | { kind: "none" };

type AppearProps = ComponentPropsWithoutRef<"div"> & { live: boolean };

// Only new content animates in; history that was already there stays still.
function Appear({ live, ...rest }: AppearProps) {
  const style = useSpring({
    from: live ? { opacity: 0, y: 14, scale: 0.985 } : { opacity: 1, y: 0, scale: 1 },
    to: { opacity: 1, y: 0, scale: 1 },
    config: { tension: 240, friction: 24 },
  });
  return <animated.div {...rest} style={style} />;
}

export function Turn({ question, reply }: { question: string; reply: Reply }) {
  // A turn that mounts while still waiting for its reply is new; history mounts with its reply.
  const [live] = useState(reply.kind === "thinking");

  return (
    <div className="mb-8 [&:not(:first-child)]:border-t [&:not(:first-child)]:border-border [&:not(:first-child)]:pt-8">
      <Appear
        live={live}
        className="ml-auto w-fit max-w-[85%] origin-right whitespace-pre-wrap break-words rounded-[12px_12px_3px_12px] bg-bubble px-4 py-2.5 shadow-soft [overflow-wrap:anywhere]"
      >
        {question}
      </Appear>
      {match(reply)
        .with({ kind: "text" }, (r) => (
          <Appear live={live} className="mt-5">
            <Who />
            <Markup text={r.content} streaming={r.streaming} />
          </Appear>
        ))
        .with({ kind: "thinking" }, () => (
          <div className="mt-5">
            <Who />
            <ThinkingDots />
          </div>
        ))
        .with({ kind: "error" }, (r) => (
          <Appear
            live
            role="alert"
            className="mt-5 rounded-xl border border-warn-bar/40 bg-warn-bg px-4 py-3 text-warn-bar"
          >
            Failed: {r.message}
          </Appear>
        ))
        .with({ kind: "none" }, () => null)
        .exhaustive()}
    </div>
  );
}

function Who() {
  return (
    <div className="mb-2.5 flex items-center gap-2 text-[13px] font-semibold leading-none text-muted">
      <LumioMark size={20} />
      {APP_NAME}
    </div>
  );
}

function ThinkingDots() {
  const reduceMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const dots = useTrail(3, {
    from: { y: 0, opacity: 0.35 },
    to: [
      { y: -5, opacity: 1 },
      { y: 0, opacity: 0.35 },
    ],
    loop: true,
    config: { tension: 300, friction: 14 },
  });

  // A looping spring would spin when springs are skipped, so reduced motion gets plain text.
  if (reduceMotion) return <div className="italic text-muted">Thinking…</div>;

  return (
    <div role="status" aria-label="Thinking" className="flex h-6 items-center gap-1.5">
      {dots.map((style, i) => (
        <animated.span key={i} style={style} className="size-2 rounded-full bg-accent" />
      ))}
    </div>
  );
}
