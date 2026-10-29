import type { Runtime } from "./languages";

// Wall-clock budget for the code itself; loading the runtime has its own, longer one.
export const RUN_TIMEOUT_MS = 10_000;
export const LOAD_TIMEOUT_MS = 60_000;

export type RunRequest = { runtime: Runtime; code: string; stdin: string };

// What the sandbox reports to the page. `timeout` is produced by the page, the rest by the frame.
export type RunEvent =
  | { type: "started" }
  | { type: "stdout"; text: string }
  | { type: "stderr"; text: string }
  | { type: "echo"; text: string }
  | { type: "done"; ok: boolean; elapsedMs: number }
  | { type: "timeout"; phase: "loading" | "running"; limitMs: number };

// Messages the frame posts. They come from a frame that runs untrusted code, so anything that
// does not match exactly is dropped instead of being trusted.
export type FrameMessage =
  | { type: "ready" }
  | { type: "started" }
  | { type: "stdout"; text: string }
  | { type: "stderr"; text: string }
  | { type: "echo"; text: string }
  | { type: "done"; ok: boolean };

export function parseFrameMessage(data: unknown): FrameMessage | null {
  if (typeof data !== "object" || data === null) return null;
  const m = data as Record<string, unknown>;
  switch (m.type) {
    case "ready":
    case "started":
      return { type: m.type };
    case "stdout":
    case "stderr":
    case "echo":
      return typeof m.text === "string" ? { type: m.type, text: m.text } : null;
    case "done":
      return typeof m.ok === "boolean" ? { type: "done", ok: m.ok } : null;
    default:
      return null;
  }
}
