import vm from "node:vm";
import { describe, expect, it } from "vitest";
import { WORKER_SOURCE } from "./frameSource";

type Msg = { type: string; text?: string; ok?: boolean };

// Runs the worker source in a Node vm with just enough of the worker globals to drive a JS run.
async function runWorker(code: string, stdin = "") {
  const posted: Msg[] = [];
  let closed = false;
  const sandbox: Record<string, unknown> = {
    postMessage: (m: Msg) => posted.push(m),
    addEventListener: () => {},
    close: () => {
      closed = true;
    },
  };
  sandbox.self = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(WORKER_SOURCE, sandbox);
  await (sandbox.onmessage as (e: unknown) => Promise<void>)({ data: { type: "run", runtime: "javascript", code, stdin } });
  const text = (type: string) => posted.filter((m) => m.type === type).map((m) => m.text).join("");
  return { posted, closed, stdout: text("stdout"), stderr: text("stderr"), echo: text("echo"), dones: posted.filter((m) => m.type === "done") };
}

describe("worker prompt() and alert()", () => {
  it("hands out stdin lines in order, echoing each after the prompt text", async () => {
    const r = await runWorker('const a = prompt("A? "); const b = prompt("B? "); console.log(a + "|" + b);', "one\ntwo\n");
    expect(r.posted.filter((m) => m.type !== "started").map((m) => [m.type, m.text])).toEqual([
      ["stdout", "A? "],
      ["echo", "one\n"],
      ["stdout", "B? "],
      ["echo", "two\n"],
      ["stdout", "one|two\n"],
      ["done", undefined],
    ]);
    expect(r.dones).toEqual([{ type: "done", ok: true }]);
  });

  it("keeps an empty answer", async () => {
    const r = await runWorker("console.log(JSON.stringify(prompt('x')));", "\n");
    expect(r.stdout).toBe('x""\n');
  });

  it("ends as waiting with the marker when no lines are left, and prints nothing after it", async () => {
    const r = await runWorker('const n = parseInt(prompt("Enter a number: ")); console.log("got", n);');
    expect(r.stdout).toBe("Enter a number: ");
    expect(r.stderr).toBe("Lumio: waiting for input\n");
    expect(r.dones).toEqual([{ type: "done", ok: false }]);
    expect(r.posted[r.posted.length - 1]).toEqual({ type: "done", ok: false });
    expect(r.closed).toBe(true);
  });

  it("does not leak later output when the user code swallows the exception", async () => {
    const r = await runWorker('try { prompt("Q? "); } catch (e) { console.log("caught", e.message); } console.log("after"); console.error("later");');
    expect(r.stdout).toBe("Q? ");
    expect(r.stderr).toBe("Lumio: waiting for input\n");
    expect(r.dones).toHaveLength(1);
  });

  it("alert prints the message with a newline and returns undefined", async () => {
    const r = await runWorker('console.log(alert("hi") === undefined);');
    expect(r.stdout).toBe("hi\ntrue\n");
  });

  it("leaves programs that never call prompt() unchanged", async () => {
    const r = await runWorker('console.log("a", 1); console.warn("w");');
    expect(r.stdout).toBe("a 1\n");
    expect(r.stderr).toBe("w\n");
    expect(r.echo).toBe("");
    expect(r.dones).toEqual([{ type: "done", ok: true }]);
    expect(r.closed).toBe(false);
  });
});
