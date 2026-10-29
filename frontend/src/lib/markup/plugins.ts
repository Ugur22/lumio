import type { PluggableList } from "unified";
import rehypeHighlight from "rehype-highlight";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { rehypeExplicitLanguage } from "./codeLang";
import { rehypeDialogue } from "./dialogue";
import { schema } from "./sanitize";
import { rehypeSafeStyle } from "./style";

export const remarkPlugins: PluggableList = [remarkGfm, remarkBreaks];

// Order matters: sanitize runs right after raw HTML is parsed, so everything
// the model wrote is filtered before our own plugins add classes.
export const rehypePlugins: PluggableList = [
  rehypeRaw,
  [rehypeSanitize, schema],
  rehypeSafeStyle,
  rehypeDialogue,
  rehypeExplicitLanguage,
  [rehypeHighlight, { detect: true, ignoreMissing: true }],
];
