import type { PluggableList } from "unified";
import rehypeHighlight from "rehype-highlight";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { rehypeDialogue } from "./dialogue";
import { schema } from "./sanitize";

export const remarkPlugins: PluggableList = [remarkGfm, remarkBreaks];

// Order matters: sanitize runs right after raw HTML is parsed, so everything
// the model wrote is filtered before our own plugins add classes.
export const rehypePlugins: PluggableList = [
  rehypeRaw,
  [rehypeSanitize, schema],
  rehypeDialogue,
  [rehypeHighlight, { detect: true, ignoreMissing: true }],
];
