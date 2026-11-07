import { splitReply, type Illustration } from "../lib/illustrations";
import { AttachedImage } from "./AttachedImage";
import { SparklesIcon } from "./icons";
import { Markup } from "./Markup";

interface Props {
  content: string;
  illustrations?: Illustration[];
  streaming?: boolean;
}

export function ReplyBody({ content, illustrations = [], streaming = false }: Props) {
  const segments = splitReply(content, illustrations, streaming);
  // Plain replies keep the exact single-Markup tree they always had.
  if (segments.length === 1 && segments[0]?.kind === "text") return <Markup text={segments[0].text} streaming={streaming} />;

  let n = 0;
  return (
    <>
      {segments.map((seg, i) => {
        if (seg.kind === "text") {
          // Only the last text can still be growing.
          const live = streaming && i === segments.length - 1;
          return <Markup key={i} text={seg.text} streaming={live} />;
        }
        if (seg.kind === "pending") {
          return (
            <figure key={i} className="my-4 max-w-[62ch]">
              {/* Same box as AttachedImage's img cap (h-48, sm:h-56, square) so the swap does not shift the page. */}
              <div
                role="status"
                aria-label="Illustrating"
                className="relative flex size-48 max-w-full flex-col items-center justify-center gap-2 overflow-hidden rounded-xl border border-border bg-bubble text-sm text-muted sm:size-56"
              >
                <span
                  aria-hidden="true"
                  className="pointer-events-none absolute inset-0 hidden bg-[linear-gradient(100deg,transparent_30%,color-mix(in_srgb,var(--accent)_14%,transparent)_50%,transparent_70%)] motion-safe:block motion-safe:animate-shimmer"
                />
                <SparklesIcon aria-hidden="true" className="motion-safe:animate-sketch-pulse" />
                <span aria-hidden="true">Illustrating…</span>
              </div>
            </figure>
          );
        }
        n += 1;
        const { url, prompt } = seg.illustration;
        return (
          <figure key={i} className="my-4 max-w-[62ch]">
            <AttachedImage url={url} label={`Illustration ${n}`} />
            {prompt && <figcaption className="mt-1.5 break-words text-[13px] italic text-muted">{prompt}</figcaption>}
          </figure>
        );
      })}
    </>
  );
}
