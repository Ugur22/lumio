import type { Runtime } from "./languages";
import { RUNTIME_LABEL } from "./languages";
import type { RunEvent } from "./protocol";
import { answerFeedback, diverged, outputText, type AnswerFeedback } from "./replay";
import { needsInput } from "./stdin";

// Past this the panel stops growing; a print loop must not be able to freeze the page.
export const MAX_OUTPUT_CHARS = 100_000;

export type RunStatus = "idle" | "loading" | "running" | "ok" | "error" | "timeout" | "stopped";
export type Chunk = { stream: "stdout" | "stderr" | "echo"; text: string };

export type HeldOutput = { chunks: Chunk[]; size: number; truncated: boolean };

export type RunState = {
  status: RunStatus;
  chunks: Chunk[];
  size: number;
  // Lines typed at the prompt this session, in order; each one re-runs the program.
  answers: string[];
  // The previous output, kept on screen while a replay runs so the panel does not flicker.
  held: HeldOutput | null;
  // The last replay did not repeat the output before it.
  diverged: boolean;
  // What the program did with the latest answer, once the replay has settled.
  feedback: AnswerFeedback | null;
  truncated: boolean;
  elapsedMs: number | null;
  timeoutMs: number | null;
};

export const idleState: RunState = {
  status: "idle",
  chunks: [],
  size: 0,
  answers: [],
  held: null,
  diverged: false,
  feedback: null,
  truncated: false,
  elapsedMs: null,
  timeoutMs: null,
};

// Python downloads and compiles its runtime first; JavaScript starts at once.
export const startState = (runtime: Runtime): RunState => ({
  ...idleState,
  status: runtime === "python" ? "loading" : "running",
});

export const isBusy = (s: RunState) => s.status === "loading" || s.status === "running";

export type RunAction = RunEvent | { type: "stopped" } | { type: "replay"; answer: string };

// Ran out of input and not running: the one state the prompt row can answer.
export const canReplay = (s: RunState): boolean => needsInput(s);

// Swap the replay's output in for the held one. Only a run that got to its end is comparable.
function settle(state: RunState, compare: boolean): RunState {
  const { held } = state;
  if (!held) return state;
  const differs = compare && !held.truncated && !state.truncated && diverged(outputText(held.chunks), outputText(state.chunks));
  // Only a replay that reached a waiting prompt or a clean finish has a reply worth describing.
  const reached = state.status === "ok" || needsInput(state);
  const feedback =
    reached && !differs && !held.truncated && !state.truncated ? answerFeedback(held.chunks, state.chunks, state.answers) : null;
  return { ...state, held: null, diverged: differs, feedback };
}

function replay(state: RunState, answer: string): RunState {
  if (!needsInput(state)) return state;
  return {
    ...idleState,
    status: "loading",
    answers: [...state.answers, answer],
    held: { chunks: state.chunks, size: state.size, truncated: state.truncated },
  };
}

function append(state: RunState, stream: Chunk["stream"], text: string): RunState {
  const room = MAX_OUTPUT_CHARS - state.size;
  if (room <= 0) return state.truncated ? state : { ...state, truncated: true };
  const kept = text.slice(0, room);
  const last = state.chunks[state.chunks.length - 1];
  const chunks =
    last?.stream === stream
      ? [...state.chunks.slice(0, -1), { stream, text: last.text + kept }]
      : [...state.chunks, { stream, text: kept }];
  return { ...state, chunks, size: state.size + kept.length, truncated: kept.length < text.length };
}

export function reduceRun(state: RunState, action: RunAction): RunState {
  if (action.type === "replay") return replay(state, action.answer);
  if (!isBusy(state)) return state;
  switch (action.type) {
    case "started":
      return { ...state, status: "running" };
    case "stdout":
    case "stderr":
      return append(state, action.type, action.text);
    case "echo":
      return append(state, "echo", action.text);
    case "done":
      return settle({ ...state, status: action.ok ? "ok" : "error", elapsedMs: action.elapsedMs }, true);
    case "timeout":
      return settle({ ...state, status: "timeout", timeoutMs: action.limitMs }, false);
    case "stopped":
      return settle({ ...state, status: "stopped" }, false);
  }
}

const seconds = (ms: number) => `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;

export function describeStatus(state: RunState, runtime: Runtime): string {
  const took = state.elapsedMs === null ? "" : ` in ${seconds(state.elapsedMs)}`;
  const cut = state.truncated ? " · output truncated" : "";
  switch (state.status) {
    case "idle":
      return "";
    case "loading":
      if (state.held) return "Running…";
      return `Loading ${RUNTIME_LABEL[runtime]} runtime…`;
    case "running":
      return `Running…${cut}`;
    case "ok":
      return `Finished${took}${cut}`;
    case "error":
      if (needsInput(state)) return `Waiting for your answer${cut}`;
      return `Exited with error${took}${cut}`;
    case "timeout":
      return `Timed out after ${Math.round((state.timeoutMs ?? 0) / 1000)} s${cut}`;
    case "stopped":
      return `Stopped${cut}`;
  }
}
