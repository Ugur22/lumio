import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { startState, reduceRun, idleState, type RunAction } from "../lib/runner/state";
import { createElement } from "react";
import { CodeActionsContext, type CodeActions } from "./CodeActionsContext";
import { MAX_ANSWERS } from "../lib/runner/replay";
import { OutputPanel } from "./CodeRunner";

type Props = Parameters<typeof OutputPanel>[0];
const render = (state: Props["state"], extra: Partial<Props> = {}) =>
  renderToStaticMarkup(<OutputPanel state={state} runtime="javascript" onClear={() => {}} onRerun={() => {}} onAnswer={() => {}} {...extra} />);

const renderPy = (state: Props["state"], extra: Partial<Props> = {}) =>
  renderToStaticMarkup(<OutputPanel state={state} runtime="python" onClear={() => {}} onRerun={() => {}} onAnswer={() => {}} {...extra} />);

describe("OutputPanel", () => {
  it("renders nothing before a run", () => {
    expect(render(idleState)).toBe("");
  });

  it("renders output as text, never as markup", () => {
    const state = reduceRun(startState("javascript"), { type: "stdout", text: '<img src=x onerror="alert(1)"><script>1</script>' });
    const out = render(state);
    expect(out).not.toContain("<img");
    expect(out).not.toContain("<script");
    expect(out).toContain("&lt;img src=x");
  });

  it("marks stderr apart and shows the status", () => {
    const state = [
      { type: "stdout", text: "ok\n" } as const,
      { type: "stderr", text: "Boom\n" } as const,
      { type: "done", ok: false, elapsedMs: 40 } as const,
    ].reduce(reduceRun, startState("javascript"));
    const out = render(state);
    expect(out).toContain("Exited with error in 0.04 s");
    expect(out).toMatch(/text-\[#f0a08a\]">Boom/);
    expect(out).toContain('aria-live="polite"');
  });

  it("offers Run again only once the run has finished", () => {
    expect(render(startState("javascript"))).not.toContain("Run again");
    expect(render(reduceRun(startState("javascript"), { type: "done", ok: true, elapsedMs: 3 }))).toContain("Run again");
  });

  it("shows a muted placeholder when a finished run printed nothing", () => {
    const out = render(reduceRun(startState("javascript"), { type: "done", ok: true, elapsedMs: 3 }));
    expect(out).toContain("(no output)");
  });

  describe("when a JavaScript program ran out of input", () => {
    const marker = { type: "stderr", text: "Lumio: waiting for input\n" } as const;
    const done = { type: "done", ok: false, elapsedMs: 4 } as const;
    const PROMPT = 'aria-label="Answer to the program&#x27;s prompt"';

    it("shows the prompt row, hides the marker and reports waiting", () => {
      const out = render([{ type: "stdout", text: "Enter a number: " } as const, marker, done].reduce(reduceRun, startState("javascript")));
      expect(out).toContain(PROMPT);
      expect(out).toContain("Waiting for your answer");
      expect(out).not.toContain("Lumio: waiting");
      expect(out).not.toContain("Exited with error");
    });

    it("shows no prompt row for a plain run or an ordinary error", () => {
      const plain = render([{ type: "stdout", text: "hi\n" } as const, { type: "done", ok: true, elapsedMs: 1 } as const].reduce(reduceRun, startState("javascript")));
      expect(plain).not.toContain(PROMPT);
      const failed = render([{ type: "stderr", text: "ReferenceError: x\n" } as const, done].reduce(reduceRun, startState("javascript")));
      expect(failed).not.toContain(PROMPT);
      expect(failed).toContain("Exited with error");
    });

    it("shows the answer feedback note after a replay settles", () => {
      const waiting = [{ type: "stdout", text: "N? " } as const, marker, done].reduce(reduceRun, startState("javascript"));
      const replayed = [
        { type: "replay", answer: "5" } as const,
        { type: "stdout", text: "N? " } as const,
        { type: "echo", text: "5\n" } as const,
        { type: "done", ok: true, elapsedMs: 2 } as const,
      ].reduce<Props["state"]>(reduceRun, waiting);
      expect(render(replayed)).toContain("Answer received. The program printed nothing in response.");
    });
  });

  describe("when the program ran out of input", () => {
    const eofTrace = { type: "stderr", text: "Traceback (most recent call last):\nEOFError: EOF when reading a line\n" } as const;
    const done = { type: "done", ok: false, elapsedMs: 40 } as const;
    const waitingAfter = (...events: RunAction[]) => [...events, eofTrace, done].reduce(reduceRun, startState("python"));
    const PROMPT = 'aria-label="Answer to the program&#x27;s prompt"';

    it("shows a live prompt row after the program's own prompt, with a calm status", () => {
      const out = renderPy(waitingAfter({ type: "stdout", text: "Enter operation: " }));
      expect(out).toContain("Waiting for your answer");
      expect(out).toContain(PROMPT);
      expect(out).not.toContain(`disabled=""`);
      expect(out.indexOf("Enter operation: ")).toBeLessThan(out.indexOf("<input"));
      expect(out).not.toMatch(/#e5b567|#f0a08a/);
      expect(out).not.toContain("EOFError");
      expect(out).not.toContain("traceback");
      expect(out).not.toContain("Exited with error");
      expect(out).not.toContain("Waiting for more input");
    });

    it("shows the row with no amber hint when nothing was answered yet", () => {
      const out = renderPy(waitingAfter({ type: "stdout", text: "Name? " }));
      expect(out).toContain(PROMPT);
      expect(out).not.toContain("This program asks for input");
      expect(out).not.toContain("#e5b567");
    });

    it("keeps answers in the output in the echo style", () => {
      const out = renderPy(waitingAfter({ type: "stdout", text: "Expr: " }, { type: "echo", text: "23 + 33\n" }, { type: "stdout", text: "Result: 56\nExpr: " }));
      expect(out).toMatch(/text-\[#7ec4ae\]">23 \+ 33/);
      expect(out).toContain(PROMPT);
    });

    it("keeps the previous output and a disabled field with the submitted answer while a replay runs", () => {
      const waiting = waitingAfter({ type: "stdout", text: "Expr: " });
      const replaying = reduceRun(waiting, { type: "replay", answer: "<b>7</b>" });
      const out = renderPy(replaying);
      expect(out).toContain("Expr: ");
      expect(out).toMatch(/<input[^>]*disabled=""/);
      expect(out).toContain('value="&lt;b&gt;7&lt;/b&gt;"');
      expect(out).not.toContain("<b>7");
      expect(out).not.toContain("EOFError");
      expect(out).toContain("Running…");
    });

    it("swaps to the new output once the replay waits again", () => {
      const replaying = reduceRun(waitingAfter({ type: "stdout", text: "Old? " }), { type: "replay", answer: "1" });
      const next = [{ type: "stdout", text: "Old? " } as const, { type: "echo", text: "1\n" } as const, { type: "stdout", text: "Next? " } as const, eofTrace, done].reduce(reduceRun, replaying);
      const out = renderPy(next);
      expect(out).toContain("Next? ");
      expect(out).not.toMatch(/<input[^>]*disabled=""/);
      expect(out).toContain("<input");
    });

    it("shows the placeholder and the Enter key-cap while the field is enabled", () => {
      const out = renderPy(waitingAfter({ type: "stdout", text: "Name? " }));
      expect(out).toContain('placeholder="Type here, then Enter"');
      expect(out).toContain("<kbd");
      expect(out).toContain("↵");
    });

    it("hides the placeholder and key-cap while a replay runs", () => {
      const out = renderPy(reduceRun(waitingAfter({ type: "stdout", text: "Expr: " }), { type: "replay", answer: "7" }));
      expect(out).not.toContain("placeholder=");
      expect(out).not.toContain("<kbd");
    });

    it("renders no prefill UI", () => {
      const out = renderPy(waitingAfter({ type: "stdout", text: "Name? " }));
      expect(out).not.toMatch(/prefill/i);
      expect(out).not.toContain("<textarea");
      expect(out).not.toContain("Ctrl/");
    });

    it("has no prompt row after finishing or while running", () => {
      const finished = [{ type: "stdout", text: "bye\n" } as const, { type: "done", ok: true, elapsedMs: 3 } as const].reduce(reduceRun, startState("python"));
      expect(renderPy(finished)).not.toContain("<input");
      expect(renderPy(startState("python"))).not.toContain("<input");
    });

    it("stops offering the field at the answer cap and says so", () => {
      const answered = { ...waitingAfter({ type: "stdout", text: "Name? " }), answers: Array.from({ length: MAX_ANSWERS }, () => "x") };
      const out = renderPy(answered);
      expect(out).not.toContain("<input");
      expect(out).toContain("Answer limit reached");
    });

    it("notes a replay that differed", () => {
      const next = [{ type: "stdout", text: "Z? " } as const, { type: "done", ok: true, elapsedMs: 1 } as const].reduce(reduceRun, reduceRun(waitingAfter({ type: "stdout", text: "A? " }), { type: "replay", answer: "1" }));
      expect(renderPy(next)).toContain("Output differed on replay; this program isn&#x27;t deterministic.");
      expect(renderPy(waitingAfter({ type: "stdout", text: "A? " }))).not.toContain("Output differed");
    });

    describe("answer feedback", () => {
      const replayedWith = (...events: RunAction[]) =>
        [...events].reduce(reduceRun, reduceRun(waitingAfter({ type: "stdout", text: "Op: " }), { type: "replay", answer: "x" }));
      const asked = [{ type: "stdout", text: "Op: " }, { type: "echo", text: "x\n" }] as const;
      const SILENT = "Answer received. The program printed nothing in response.";
      const REPEATED = "Answer received. The program asked the same question again.";

      it("notes a silent reply", () => {
        const out = renderPy(replayedWith(...asked, eofTrace, done));
        expect(out).toContain(SILENT);
        expect(out).not.toContain(REPEATED);
      });

      it("notes the same question asked again", () => {
        const out = renderPy(replayedWith(...asked, { type: "stdout", text: "Op: " }, eofTrace, done));
        expect(out).toContain(REPEATED);
        expect(out).not.toContain(SILENT);
      });

      it("notes a program that finished without replying", () => {
        expect(renderPy(replayedWith(...asked, { type: "done", ok: true, elapsedMs: 1 }))).toContain(SILENT);
      });

      it("has no note for a new question, while replaying, or before any answer", () => {
        expect(renderPy(replayedWith(...asked, { type: "stdout", text: "Next: " }, eofTrace, done))).not.toContain("Answer received");
        expect(renderPy(replayedWith(...asked))).not.toContain("Answer received");
        expect(renderPy(waitingAfter({ type: "stdout", text: "Op: " }))).not.toContain("Answer received");
      });

      it("has no note after an error or a timeout", () => {
        const boom = { type: "stderr", text: "ValueError: no\n" } as const;
        expect(renderPy(replayedWith(...asked, boom, done))).not.toContain("Answer received");
        expect(renderPy(replayedWith(...asked, { type: "timeout", phase: "running", limitMs: 10_000 }))).not.toContain("Answer received");
      });
    });

    it("escapes echoed text", () => {
      const out = renderPy(waitingAfter({ type: "echo", text: "<img src=x onerror=1>\n" }));
      expect(out).not.toContain("<img");
      expect(out).toContain("&lt;img src=x onerror=1&gt;");
    });

    it("keeps escaping program output", () => {
      const out = renderPy(waitingAfter({ type: "stdout", text: "<b onclick=x>hi</b>" }));
      expect(out).not.toContain("<b ");
      expect(out).toContain("&lt;b onclick=x&gt;");
    });

    it("leaves other errors red and without a prompt", () => {
      const state = [{ type: "stderr", text: "ValueError: nope\n" } as const, { type: "done", ok: false, elapsedMs: 5 } as const].reduce(reduceRun, startState("python"));
      const out = renderPy(state);
      expect(out).toContain("Exited with error");
      expect(out).toContain("ValueError: nope");
      expect(out).not.toContain("<input");
    });
  });
});

describe("Fix with AI button", () => {
  const withActions = (state: Parameters<typeof OutputPanel>[0]["state"], actions?: CodeActions) => {
    const panel = createElement(OutputPanel, { state, runtime: "python", onClear: () => {}, onRerun: () => {}, onAnswer: () => {} });
    return renderToStaticMarkup(actions ? createElement(CodeActionsContext.Provider, { value: actions }, panel) : panel);
  };
  const live: CodeActions = { askAboutRun: () => {}, busy: false };
  const error = [{ type: "stderr", text: "ValueError: x\n" } as const, { type: "done", ok: false, elapsedMs: 1 } as const].reduce(reduceRun, startState("python"));
  const timeout = reduceRun(startState("python"), { type: "timeout", phase: "running", limitMs: 10_000 });
  const eofDone = [
    { type: "echo", text: "1\n" } as const,
    { type: "stderr", text: "EOFError: EOF when reading a line\n" } as const,
    { type: "done", ok: false, elapsedMs: 1 } as const,
  ].reduce(reduceRun, startState("python"));

  it("shows for an error and for a timeout", () => {
    expect(withActions(error, live)).toContain("Fix with AI");
    expect(withActions(timeout, live)).toContain("Fix with AI");
  });

  it("does not show for success, a running run, waiting for input or without a provider", () => {
    expect(withActions(reduceRun(startState("python"), { type: "done", ok: true, elapsedMs: 1 }), live)).not.toContain("Fix with AI");
    expect(withActions(startState("python"), live)).not.toContain("Fix with AI");
    expect(withActions(eofDone, live)).not.toContain("Fix with AI");
    expect(withActions(error)).not.toContain("Fix with AI");
  });

  it("is enabled when idle and disabled with an explanation while a reply streams", () => {
    // Attribute order differs by renderer, so the button's own tag is matched and inspected whole.
    const fixTag = (html: string) => html.match(/<button[^>]*aria-label="Ask the model to fix this code"[^>]*>/)?.[0];
    expect(fixTag(withActions(error, live))).toBeDefined();
    expect(fixTag(withActions(error, live))).not.toContain('disabled=""');
    const out = withActions(error, { ...live, busy: true });
    expect(out).toContain("Wait for the current reply to finish");
    expect(fixTag(out)).toContain('disabled=""');
  });
});
