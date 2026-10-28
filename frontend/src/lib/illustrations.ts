// Splits a reply into text, stored illustrations and "being illustrated" placeholders.
// The model writes `[[image: ...]]`; the server swaps each for `[[img:<id>]]` once the picture exists.
export interface Illustration {
  id: string;
  url: string;
  prompt: string | null;
}

export type Segment =
  | { kind: "text"; text: string }
  | { kind: "image"; illustration: Illustration }
  | { kind: "pending" };

const MARKER = /\[\[(?:image:[\s\S]*?|img:([0-9a-f]{32}))\]\]/g;
const OPENERS = ["[[image:", "[[img:"];

// While streaming, a directive may be cut mid-way ("[[ima"); drop that tail so it never flashes as text.
function withoutPartialTail(text: string): string {
  const start = text.lastIndexOf("[[");
  if (start >= 0) {
    const tail = text.slice(start);
    if (!tail.includes("]]") && OPENERS.some((o) => o.startsWith(tail) || tail.startsWith(o))) return text.slice(0, start);
  }
  return text.endsWith("[") && !text.endsWith("[[") ? text.slice(0, -1) : text;
}

// Only ids in `known` (that message's own images) become pictures, so reply text can't point at other files.
export function splitReply(content: string, known: Illustration[], streaming: boolean): Segment[] {
  const byId = new Map(known.map((i) => [i.id, i]));
  const source = streaming ? withoutPartialTail(content) : content;
  const out: Segment[] = [];
  const pushText = (text: string) => {
    if (text.trim() !== "") out.push({ kind: "text", text });
  };

  let last = 0;
  for (const m of source.matchAll(MARKER)) {
    pushText(source.slice(last, m.index));
    last = m.index + m[0].length;
    const id = m[1];
    if (id === undefined) {
      // A directive still in the text: the picture is on its way while streaming, stale otherwise.
      if (streaming) out.push({ kind: "pending" });
      continue;
    }
    const illustration = byId.get(id);
    if (illustration) out.push({ kind: "image", illustration });
  }
  pushText(source.slice(last));
  return out;
}

// What "Copy" puts on the clipboard: the story text without markers or placeholders.
export function copyText(content: string): string {
  return content.replace(MARKER, "").replace(/\n{3,}/g, "\n\n").trim();
}
