export type Runtime = "python" | "javascript";

const RUNTIMES: Record<string, Runtime> = {
  python: "python",
  py: "python",
  javascript: "javascript",
  js: "javascript",
};

// Anything else (shell, sql, a guessed language) gets no Run button.
export function runtimeFor(lang: string | undefined): Runtime | null {
  if (!lang) return null;
  return RUNTIMES[lang.toLowerCase()] ?? null;
}

export const RUNTIME_LABEL: Record<Runtime, string> = { python: "Python", javascript: "JavaScript" };
