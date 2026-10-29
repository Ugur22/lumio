const EOF_LINES = ["EOFError: EOF when reading a line", "Lumio: waiting for input"];

type Run = { status: string; chunks: readonly { stream: string; text: string }[] };

// Python reports a drained stdin as an EOFError; the JavaScript worker prints its own marker line.
export function needsInput(run: Run): boolean {
  if (run.status !== "error") return false;
  const stderr = run.chunks
    .filter((c) => c.stream === "stderr")
    .map((c) => c.text)
    .join("");
  const tail = stderr.trimEnd();
  return EOF_LINES.some((l) => tail.endsWith(l));
}
