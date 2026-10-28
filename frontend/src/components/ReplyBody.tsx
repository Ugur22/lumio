import { splitReply, type Illustration } from "../lib/illustrations";
import { AttachedImage } from "./AttachedImage";
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
            <div
              key={i}
              role="status"
              className="my-4 flex h-24 max-w-[62ch] items-center justify-center rounded-2xl border border-dashed border-border bg-bubble text-sm text-muted motion-safe:animate-pulse"
            >
              Illustrating…
            </div>
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
