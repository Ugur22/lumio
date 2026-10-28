export interface Edit {
  value: string;
  caret: number;
}

const ITEM = /^(\s*)([-*]|\d+\.)( +)(.*)$/;
const INDENT = "  ";

function lineAt(value: string, pos: number) {
  const start = value.lastIndexOf("\n", pos - 1) + 1;
  const nl = value.indexOf("\n", pos);
  const end = nl === -1 ? value.length : nl;
  return { start, end, match: ITEM.exec(value.slice(start, end)) };
}

/** Enter on a list item: continue the list, or end it when the item is empty. Null when not on a list item. */
export function continueList(value: string, caret: number): Edit | null {
  const { start, end, match } = lineAt(value, caret);
  if (!match) return null;
  const [, indent = "", marker = "", gap = "", content = ""] = match;
  if (caret < start + indent.length + marker.length + gap.length) return null;
  if (content === "") {
    return { value: value.slice(0, start) + value.slice(end), caret: start };
  }
  const next = /^\d+\./.test(marker) ? `${parseInt(marker, 10) + 1}.` : marker;
  const insert = `\n${indent}${next} `;
  return { value: value.slice(0, caret) + insert + value.slice(caret), caret: caret + insert.length };
}

/** Tab / Shift+Tab on a list item. Null when not on a list item or there is nothing to outdent. */
export function shiftList(value: string, caret: number, outdent: boolean): Edit | null {
  const { start, match } = lineAt(value, caret);
  if (!match) return null;
  if (!outdent) {
    return { value: value.slice(0, start) + INDENT + value.slice(start), caret: caret + INDENT.length };
  }
  const lead = Math.min(INDENT.length, (match[1] ?? "").length);
  if (lead === 0) return null;
  return { value: value.slice(0, start) + value.slice(start + lead), caret: Math.max(start, caret - lead) };
}
