import { describe, expect, it } from "vitest";
import { canReplay, describeStatus, MAX_OUTPUT_CHARS, reduceRun, startState, type RunState } from "./state";

const apply = (state: RunState, ...events: Parameters<typeof reduceRun>[1][]) => events.reduce(reduceRun, state);

describe("reduceRun", () => {
  it("merges consecutive chunks of one stream and keeps streams apart", () => {
    const s = apply(startState("javascript"), { type: "stdout", text: "a" }, { type: "stdout", text: "b" }, { type: "stderr", text: "c" });
    expect(s.chunks).toEqual([
      { stream: "stdout", text: "ab" },
      { stream: "stderr", text: "c" },
    ]);
  });

  it("finishes with ok or error and ignores events after that", () => {
    const ok = apply(startState("javascript"), { type: "done", ok: true, elapsedMs: 120 });
    expect(ok.status).toBe("ok");
    expect(apply(ok, { type: "stdout", text: "late" }).chunks).toEqual([]);
    expect(apply(startState("javascript"), { type: "done", ok: false, elapsedMs: 5 }).status).toBe("error");
  });

  it("caps the output and says so", () => {
    const s = apply(startState("javascript"), { type: "stdout", text: "x".repeat(MAX_OUTPUT_CHARS + 50) }, { type: "stdout", text: "more" });
    expect(s.size).toBe(MAX_OUTPUT_CHARS);
    expect(s.truncated).toBe(true);
  });

  it("keeps echoed answers apart from stdout and counts them against the cap", () => {
    const s = apply(
      startState("python"),
      { type: "stdout", text: "Enter: " },
      { type: "echo", text: "1\n" },
      { type: "stdout", text: "Enter: " },
      { type: "echo", text: "2\n" },
    );
    expect(s.chunks.map((c) => c.stream)).toEqual(["stdout", "echo", "stdout", "echo"]);
    const full = apply(startState("python"), { type: "stdout", text: "x".repeat(MAX_OUTPUT_CHARS) }, { type: "echo", text: "late\n" });
    expect(full.size).toBe(MAX_OUTPUT_CHARS);
    expect(full.truncated).toBe(true);
  });

  it("starts python in the loading state", () => {
    expect(startState("python").status).toBe("loading");
    expect(apply(startState("python"), { type: "started" }).status).toBe("running");
  });
});

describe("describeStatus", () => {
  it("words each outcome", () => {
    const run = (e: Parameters<typeof reduceRun>[1]) => apply(startState("python"), e);
    expect(describeStatus(startState("python"), "python")).toBe("Loading Python runtime…");
    expect(describeStatus(run({ type: "done", ok: true, elapsedMs: 123 }), "python")).toBe("Finished in 0.12 s");
    expect(describeStatus(run({ type: "done", ok: false, elapsedMs: 50 }), "python")).toBe("Exited with error in 0.05 s");
    expect(describeStatus(run({ type: "timeout", phase: "running", limitMs: 10_000 }), "python")).toBe("Timed out after 10 s");
    expect(describeStatus(run({ type: "stopped" }), "python")).toBe("Stopped");
  });
});

describe("replay", () => {
  const eof = { type: "stderr", text: "EOFError: EOF when reading a line\n" } as const;
  const done = { type: "done", ok: false, elapsedMs: 5 } as const;
  const waiting = apply(startState("python"), { type: "stdout", text: "A? " }, eof, done);

  it("recognises the waiting state for python only", () => {
    expect(canReplay(waiting, "python")).toBe(true);
    expect(canReplay(waiting, "javascript")).toBe(false);
    expect(canReplay(apply(startState("python"), { type: "done", ok: true, elapsedMs: 1 }), "python")).toBe(false);
  });

  it("keeps the previous output on screen while the replay runs, then swaps it in at the next wait", () => {
    const replaying = reduceRun(waiting, { type: "replay", answer: "4" });
    expect(replaying.status).toBe("loading");
    expect(replaying.answers).toEqual(["4"]);
    expect(replaying.held?.chunks).toEqual(waiting.chunks);
    expect(replaying.chunks).toEqual([]);

    const mid = apply(replaying, { type: "started" }, { type: "stdout", text: "A? " }, { type: "echo", text: "4\n" });
    expect(mid.held).not.toBeNull();
    expect(mid.chunks.map((c) => c.text)).toEqual(["A? ", "4\n"]);

    const next = apply(mid, { type: "stdout", text: "B? " }, eof, done);
    expect(next.held).toBeNull();
    expect(next.diverged).toBe(false);
    expect(next.answers).toEqual(["4"]);
    expect(canReplay(next, "python")).toBe(true);
    expect(describeStatus(next, "python")).toBe("Waiting for your answer");
  });

  it("swaps at finish and says Finished", () => {
    const next = apply(reduceRun(waiting, { type: "replay", answer: "" }), { type: "stdout", text: "A? " }, { type: "echo", text: "\n" }, { type: "done", ok: true, elapsedMs: 9 });
    expect(next.held).toBeNull();
    expect(next.status).toBe("ok");
    expect(describeStatus(next, "python")).toBe("Finished in 0.01 s");
  });

  it("flags a replay whose output differs", () => {
    const next = apply(reduceRun(waiting, { type: "replay", answer: "1" }), { type: "stdout", text: "Z? " }, { type: "done", ok: true, elapsedMs: 1 });
    expect(next.diverged).toBe(true);
  });

  it("does not flag a stopped or timed out replay and still ends on the new output", () => {
    const replaying = reduceRun(waiting, { type: "replay", answer: "1" });
    const stopped = reduceRun(replaying, { type: "stopped" });
    expect(stopped.status).toBe("stopped");
    expect(stopped.held).toBeNull();
    expect(stopped.diverged).toBe(false);
    expect(reduceRun(replaying, { type: "timeout", phase: "running", limitMs: 10_000 }).held).toBeNull();
  });

  it("ignores a replay unless the program is waiting", () => {
    const running = startState("python");
    expect(reduceRun(running, { type: "replay", answer: "1" })).toBe(running);
  });

  it("accumulates answers across replays", () => {
    const second = apply(reduceRun(waiting, { type: "replay", answer: "1" }), { type: "stdout", text: "A? " }, { type: "echo", text: "1\n" }, { type: "stdout", text: "B? " }, eof, done);
    expect(reduceRun(second, { type: "replay", answer: "2" }).answers).toEqual(["1", "2"]);
  });

  describe("feedback", () => {
    const again = [{ type: "stdout", text: "A? " }, { type: "echo", text: "4\n" }] as const;
    const replayed = (answer: string) => reduceRun(waiting, { type: "replay", answer });

    it("is silent when the replay printed nothing after the answer", () => {
      expect(apply(replayed("4"), ...again, eof, done).feedback).toBe("silent");
      expect(apply(replayed("4"), ...again, { type: "done", ok: true, elapsedMs: 1 }).feedback).toBe("silent");
    });

    it("flags the same prompt asked again", () => {
      expect(apply(replayed("4"), ...again, { type: "stdout", text: "A? " }, eof, done).feedback).toBe("repeated");
    });

    it("is null for a new question, and while the replay runs", () => {
      expect(apply(replayed("4"), ...again, { type: "stdout", text: "B? " }, eof, done).feedback).toBeNull();
      expect(apply(replayed("4"), ...again).feedback).toBeNull();
      expect(waiting.feedback).toBeNull();
    });

    it("is null after a real error, timeout, stop or a diverged replay", () => {
      const boom = { type: "stderr", text: "ValueError: no\n" } as const;
      expect(apply(replayed("4"), ...again, boom, done).feedback).toBeNull();
      expect(apply(replayed("4"), ...again, { type: "timeout", phase: "running", limitMs: 10_000 }).feedback).toBeNull();
      expect(apply(replayed("4"), ...again, { type: "stopped" }).feedback).toBeNull();
      expect(apply(replayed("4"), { type: "stdout", text: "Z? " }, { type: "echo", text: "4\n" }, eof, done).feedback).toBeNull();
    });

    it("clears on the next replay and on a fresh run", () => {
      const silent = apply(replayed("4"), ...again, eof, done);
      expect(silent.feedback).toBe("silent");
      expect(reduceRun(silent, { type: "replay", answer: "5" }).feedback).toBeNull();
      expect(startState("python").feedback).toBeNull();
    });
  });
});
