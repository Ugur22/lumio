// Replaces [[key]]/[[note]]/[[warn]] pairs with raw HTML that rehype-raw parses
// and rehype-sanitize then restricts to the hl-* classes. Code is masked first
// so tags inside fences or inline code stay literal.
const CODE = /(^|\n)(```|~~~)[^\n]*\n[\s\S]*?(?:\n\2[^\n]*(?=\n|$)|$)|`+[^`\n]+`+/g;
// Citation markup the model sometimes echoes back verbatim, as [[web_source url="..."]] or <web_source>.
// Quoted attribute values may contain "]" or ">", so they are matched as units.
const ATTRS = `(?:\\s+(?:"[^"]*"|'[^']*'|[^\\]>"'])*)?`;
const STRAY_SOURCE = new RegExp(`\\[\\[/?web_source${ATTRS}\\]\\]|</?web_source${ATTRS}/?>`, "gi");
// The same token still arriving while streaming.
const STRAY_SOURCE_PARTIAL = new RegExp(
  `(?:\\[{1,2}|<)/?(?:web_source[^\\n]*|${"web_source".split("").map((_, n, a) => a.slice(0, n + 1).join("")).join("|")})$`,
  "i",
);
const TAG = /\[\[(key|note|warn)\]\]([\s\S]*?)\[\[\/\1\]\]/g;
// NUL cannot appear in sane chat text, so it makes a collision-free placeholder.
const NUL = String.fromCharCode(0);
const MASK = new RegExp(`${NUL}(\\d+)${NUL}`, "g");

const TAG_NAMES = ["key", "note", "warn"];
// A marker still arriving, such as "[", "[[ke" or "[[/key]".
const PARTIAL_MARKER = /\[{1,2}\/?[a-z]*\]?$/;

// While a reply streams, hide half-typed markers and close open tags so the
// highlight shows up as it grows instead of flashing literal brackets.
function completeOpenTags(masked: string): string {
  let out = masked.replace(PARTIAL_MARKER, "");
  for (const tag of TAG_NAMES) {
    if (out.lastIndexOf(`[[${tag}]]`) > out.lastIndexOf(`[[/${tag}]]`)) out += `[[/${tag}]]`;
  }
  return out;
}

export function applyTags(text: string, streaming = false): string {
  const stash: string[] = [];
  const masked = text.replace(CODE, (m) => `${NUL}${stash.push(m) - 1}${NUL}`);
  const stripped = masked.replace(STRAY_SOURCE, "");
  const source = streaming ? completeOpenTags(stripped.replace(STRAY_SOURCE_PARTIAL, "")) : stripped;
  const tagged = source.replace(TAG, (_, tag: string, body: string) =>
    tag === "key"
      ? `<mark class="hl-key">${body}</mark>`
      : `<aside class="hl-${tag}">\n\n${body}\n\n</aside>`,
  );
  return tagged.replace(MASK, (_, i: string) => stash[Number(i)] ?? "");
}
