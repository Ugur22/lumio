import { defaultSchema } from "rehype-sanitize";
import type { Options } from "rehype-sanitize";

// Default GitHub-style schema plus only the elements/classes introduced by the
// highlight tags. Nothing else (scripts, event handlers, styles) is allowed.
export const schema: Options = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames ?? []), "mark", "aside"],
  attributes: {
    ...defaultSchema.attributes,
    mark: [["className", "hl-key"]],
    aside: [["className", "hl-note", "hl-warn"]],
  },
};
