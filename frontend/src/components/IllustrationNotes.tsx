import type { IllustrationFailure } from "../types";

// Everything here is untrusted (it can echo model text or provider errors), so it is only ever
// rendered as React text children.
export function IllustrationNotes({ failures }: { failures: IllustrationFailure[] }) {
  if (failures.length === 0) return null;
  return (
    <div className="mt-3 space-y-1.5">
      {failures.map((f, i) => {
        const what = `Couldn't generate an image${f.status === null ? "" : ` (${f.status})`}`;
        return (
          <div
            key={i}
            role="status"
            className="max-w-[62ch] break-words border-l-2 border-warn-bar pl-3 text-[13px] text-muted [overflow-wrap:anywhere]"
          >
            {what}
            {f.detail && `: ${f.detail}`}
            {f.prompt && (
              <details className="mt-0.5">
                <summary className="cursor-pointer rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
                  Prompt
                </summary>
                <p className="mt-1 whitespace-pre-wrap italic">{f.prompt}</p>
              </details>
            )}
          </div>
        );
      })}
    </div>
  );
}
