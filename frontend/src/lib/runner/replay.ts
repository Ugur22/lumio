// The runtime cannot pause at input(), so every answer re-runs the program from the start with all
// answers so far. Past this many the session stops offering the prompt.
export const MAX_ANSWERS = 200;

export const DIVERGED_NOTE = "Output differed on replay; this program isn't deterministic.";
export const CAP_NOTE = `Answer limit reached (${MAX_ANSWERS}). Run again to start over.`;

type Piece = { stream: string; text: string };

// What the program and the echoes showed. stderr is left out because the EOF traceback of a
// waiting run is hidden and differs from the next run's by definition.
export const outputText = (chunks: readonly Piece[]): string =>
  chunks
    .filter((c) => c.stream !== "stderr")
    .map((c) => c.text)
    .join("");

// A deterministic program repeats its earlier output exactly before it goes on.
export const diverged = (prevText: string, nextText: string): boolean => !nextText.startsWith(prevText);

export type AnswerFeedback = "silent" | "repeated";

export const FEEDBACK_NOTE: Record<AnswerFeedback, string> = {
  silent: "Answer received. The program printed nothing in response.",
  repeated: "Answer received. The program asked the same question again.",
};

const lastLine = (text: string): string => {
  const lines = text.split("\n").map((l) => l.trim());
  return lines.findLast((l) => l !== "") ?? "";
};

// What the program did with the latest answer. Compared by last line because a menu prompt
// is several lines long but re-asks with the same final one.
export function answerFeedback(
  prevChunks: readonly Piece[],
  nextChunks: readonly Piece[],
  answers: readonly string[],
): AnswerFeedback | null {
  if (answers.length === 0) return null;
  const echoAt = nextChunks.findLastIndex((c) => c.stream === "echo");
  if (echoAt < 0) return null;
  const reply = outputText(nextChunks.slice(echoAt + 1)).trim();
  if (reply === "") return "silent";
  const asked = lastLine(outputText(prevChunks));
  return asked !== "" && lastLine(reply) === asked ? "repeated" : null;
}

export const atCap =(used: number): boolean => used >= MAX_ANSWERS;

// Every line is terminated: the worker drops one trailing newline, which would otherwise eat a final empty answer.
export const buildStdin = (lines: readonly string[]): string => lines.map((l) => `${l}\n`).join("");
