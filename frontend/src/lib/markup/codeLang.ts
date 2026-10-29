import type { Element, Root } from "hast";

const LANG = /^language-(.+)$/;

function languageOf(code: Element): string | undefined {
  const classes = code.properties?.className;
  if (!Array.isArray(classes)) return undefined;
  for (const c of classes) {
    const lang = typeof c === "string" ? LANG.exec(c)?.[1] : undefined;
    if (lang) return lang;
  }
  return undefined;
}

function walk(parent: Root | Element): void {
  for (const node of parent.children) {
    if (node.type !== "element") continue;
    if (node.tagName === "pre") {
      for (const child of node.children) {
        if (child.type === "element" && child.tagName === "code") {
          const lang = languageOf(child);
          if (lang) child.properties.dataLang = lang;
        }
      }
    } else {
      walk(node);
    }
  }
}

// rehype-highlight (with detect) adds a language-* class to every block it can guess a language
// for, so the class alone cannot tell a labelled fence from a guess. This runs before it and
// records only the languages the author wrote, which is all the Run button may act on.
export function rehypeExplicitLanguage() {
  return (tree: Root) => walk(tree);
}
