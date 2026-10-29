const EOF_LINE = "EOFError: EOF when reading a line";

type Run = { status: string; chunks: readonly { stream: string; text: string }[] };

// Python reports a drained stdin as this error, whether it was empty or ran out.
export function needsInput(run: Run): boolean {
  if (run.status !== "error") return false;
  const stderr = run.chunks
    .filter((c) => c.stream === "stderr")
    .map((c) => c.text)
    .join("");
  return stderr.trimEnd().endsWith(EOF_LINE);
}
