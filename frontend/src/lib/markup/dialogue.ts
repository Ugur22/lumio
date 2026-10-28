import type { Element, Root, RootContent, Text } from "hast";

export type Segment = { text: string; dialogue: boolean };

const QUOTE = /("[^"\n]+"|“[^”\n]+”)/;

export function splitDialogue(text: string): Segment[] {
  return text
    .split(QUOTE)
    .map((part, i) => ({ text: part, dialogue: i % 2 === 1 }))
    .filter((s) => s.text !== "");
}

// Chats keep raw text, so typographic quotes are applied only when rendering.
const APOSTROPHE = /(?<=\w)'(?=\w)/g;
const curly = (text: string) => text.replace(APOSTROPHE, "’");

function curlyDialogue(text: string): string {
  const quoted = text.startsWith('"') && text.endsWith('"') && text.length > 1;
  return quoted ? `“${curly(text.slice(1, -1))}”` : curly(text);
}

const SKIP = new Set(["code", "pre"]);

function walk(parent: Root | Element): void {
  const next: RootContent[] = [];
  for (const node of parent.children) {
    if (node.type === "element") {
      // Blocks the model styled itself (a chat window, a note) keep their own colours.
      if (!SKIP.has(node.tagName) && !node.properties?.style) walk(node);
      next.push(node);
    } else if (node.type === "text") {
      const segs = splitDialogue(node.value);
      if (segs.length === 1 && !segs[0]?.dialogue) {
        node.value = curly(node.value);
        next.push(node);
        continue;
      }
      for (const s of segs) {
        next.push(
          s.dialogue
            ? ({
                type: "element",
                tagName: "span",
                properties: { className: ["dialogue"] },
                children: [{ type: "text", value: curlyDialogue(s.text) } satisfies Text],
              } satisfies Element)
            : ({ type: "text", value: curly(s.text) } satisfies Text),
        );
      }
    } else {
      next.push(node);
    }
  }
  parent.children = next;
}

// Rehype plugin; runs after sanitize, so it only ever adds our own span.
export function rehypeDialogue() {
  return (tree: Root) => walk(tree);
}
