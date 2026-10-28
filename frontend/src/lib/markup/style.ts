import type { Element, Root } from "hast";

// The model may style its own in-story blocks (a chat window, a note, a screen), but only with
// this fixed vocabulary. Anything that could cover the app, load a resource or escape the
// reply is simply not on the list.
const ANY = /./;
const NO_NEGATIVE = /^[^-]*$/;
const sides = (prop: string) => ["", "-top", "-bottom", "-left", "-right"].map((side) => prop + side);

const RULES = new Map<string, RegExp>([
  ...[
    "color", "background", "background-color", "border-radius", "font-size", "font-weight",
    "font-style", "text-align", "letter-spacing", "line-height", "width", "max-width", "gap",
    "opacity", "flex-direction", "align-items", "justify-content", ...sides("border"), ...sides("padding"),
  ].map((prop): [string, RegExp] => [prop, ANY]),
  // Negative margins can pull a block out of the reply.
  ...sides("margin").map((prop): [string, RegExp] => [prop, NO_NEGATIVE]),
  ["display", /^(block|inline|inline-block|flex)$/],
  // Blur loads nothing and moves nothing; the cap keeps it from smearing the whole reply.
  ["filter", /^blur\(([0-9]|1[0-9]|20)(\.\d+)?px\)$/],
  ["overflow", /^hidden$/],
  ["font-family", /^(monospace|serif|sans-serif|cursive)$/],
  ["text-decoration", /^(none|underline|line-through)$/],
  ["white-space", /^(normal|pre|pre-wrap)$/],
  ["text-transform", /^(none|uppercase|lowercase|capitalize)$/],
]);
// url()/var()/escapes can load or hide things; viewport units can leave the reply.
const FORBIDDEN = /url\s*\(|expression|@import|javascript:|var\s*\(|attr\s*\(|\\|[<>{}]|\d(vw|vh|vmin|vmax)\b/i;
const MAX_VALUE = 80;

export function safeStyle(style: string): string {
  const kept: string[] = [];
  for (const decl of style.split(";")) {
    const at = decl.indexOf(":");
    if (at < 0) continue;
    const prop = decl.slice(0, at).trim().toLowerCase();
    const value = decl.slice(at + 1).trim();
    if (!value || value.length > MAX_VALUE || FORBIDDEN.test(value)) continue;
    if (RULES.get(prop)?.test(value.toLowerCase())) kept.push(`${prop}:${value}`);
  }
  return kept.join(";");
}

function walk(parent: Root | Element): void {
  for (const node of parent.children) {
    if (node.type !== "element") continue;
    const style = node.properties?.style;
    if (typeof style === "string") {
      const safe = safeStyle(style);
      if (safe) node.properties.style = safe;
      else delete node.properties.style;
    }
    walk(node);
  }
}

export function rehypeSafeStyle() {
  return (tree: Root) => walk(tree);
}
