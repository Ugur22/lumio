import { defaultSchema } from "rehype-sanitize";
import type { Options } from "rehype-sanitize";

// Default GitHub-style schema plus the highlight tags and a `style` attribute on a few text
// elements. Sanitize only lets the attribute through; rehypeSafeStyle then cuts its value down
// to the allowed properties, so it must always run right after this.
const STYLED = ["div", "span", "p", "b", "i", "em", "strong", "small"];
const styledAttributes = Object.fromEntries(
  STYLED.map((tag) => [tag, [...(defaultSchema.attributes?.[tag] ?? []), "style"]]),
);

export const schema: Options = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames ?? []), "mark", "aside", "small"],
  attributes: {
    ...defaultSchema.attributes,
    ...styledAttributes,
    mark: [["className", "hl-key"]],
    aside: [["className", "hl-note", "hl-warn"]],
  },
};
