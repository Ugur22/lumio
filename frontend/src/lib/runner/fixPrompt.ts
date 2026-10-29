import type { Runtime } from "./languages";
import { RUNTIME_LABEL } from "./languages";
import type { RunState } from "./state";
import { needsInput } from "./stdin";

export const MAX_FIX_OUTPUT = 4000;

// Only a real failure or a timeout can be fixed; waiting for input and success cannot.
export function canFix(state: Pick<RunState, "status" | "answers" | "chunks">): boolean {
  if (state.status === "timeout") return true;
  return state.status === "error" && !needsInput(state);
}

// The fence has to outgrow any backtick run in the content, or the content could close it early.
function fenced(text: string): string {
  const longest = Math.max(0, ...(text.match(/`+/g) ?? []).map((run) => run.length));
  const fence = "`".repeat(Math.max(3, longest + 1));
  return `${fence}\n${text}\n${fence}`;
}

export function buildFixPrompt(state: RunState, runtime: Runtime, stdin: string): string {
  const language = RUNTIME_LABEL[runtime];
  const intro =
    state.status === "timeout"
      ? `This code didn't finish within ${Math.round((state.timeoutMs ?? 0) / 1000)} seconds when I ran it. Please fix it and show the corrected full code.`
      : "This code failed when I ran it. Please fix it and show the corrected full code.";
  const parts = [`${intro} (It is the ${language} code block above.)`];

  if (stdin.trim() !== "") parts.push(`stdin I used:\n${fenced(stdin.replace(/\n+$/, ""))}`);

  const output = state.chunks.map((c) => c.text).join("").replace(/\s+$/, "");
  if (output !== "") {
    const cut = output.length > MAX_FIX_OUTPUT;
    const shown = cut ? `[truncated]\n${output.slice(-MAX_FIX_OUTPUT)}` : output;
    parts.push(`Output:\n${fenced(shown)}`);
  }
  return parts.join("\n\n");
}
