// Source text for the sandbox. It is plain JavaScript in strings, not TypeScript, because it is
// never bundled: the page injects it into a sandboxed frame and the frame into a worker.

// Everything the frame is allowed to do. `connect-src 'none'` is the point: nothing in here can
// open a network connection, so the Pyodide runtime is handed over as bytes instead of being
// fetched (a frame without an origin could not read same-origin files anyway, since the static
// server sends no CORS headers). Nested frames, images, forms and <base> are closed off too.
export const FRAME_CSP = [
  "default-src 'none'",
  "script-src 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' blob:",
  "worker-src blob:",
  "connect-src 'none'",
  "form-action 'none'",
  "base-uri 'none'",
].join("; ");

// Runs inside a classic worker (a module worker cannot load from a blob URL in a frame without an
// origin; dynamic import() still works), so a blocking loop never freezes any thread that has a UI.
export const WORKER_SOURCE = String.raw`
const LIMIT = 1000000;
let sent = 0;
// Set once a prompt() ran dry: the run is over, so nothing after it may reach the page.
let closed = false;
// Printed on stderr when the program ran out of stdin lines; stdin.ts looks for this exact line.
const WAIT_MARKER = "Lumio: waiting for input";
function emit(type, text) {
  if (closed || sent >= LIMIT) return;
  // Count a fixed cost per message too, so a loop of empty prints is bounded as well.
  sent += text.length + 80;
  postMessage({ type, text });
}
function show(v) {
  if (typeof v === "string") return v;
  if (v instanceof Error) return v.name + ": " + v.message;
  if (typeof v === "object" && v !== null) {
    try { return JSON.stringify(v, null, 2); } catch (e) { return String(v); }
  }
  return String(v);
}
function describe(e) {
  return e instanceof Error ? e.name + ": " + e.message : String(e);
}
self.addEventListener("unhandledrejection", (e) => emit("stderr", "Unhandled rejection: " + describe(e.reason) + "\n"));
self.addEventListener("error", (e) => emit("stderr", "Uncaught " + (e.message || "error") + "\n"));

function parseStdin(stdin) {
  return stdin === "" ? [] : stdin.replace(/\r\n/g, "\n").replace(/\n$/, "").split("\n");
}

async function runJavascript(m) {
  const lines = parseStdin(m.stdin);
  const to = (type) => (...args) => emit(type, args.map(show).join(" ") + "\n");
  const con = { log: to("stdout"), info: to("stdout"), debug: to("stdout"), warn: to("stderr"), error: to("stderr") };
  const alertFn = (message) => { emit("stdout", (message === undefined ? "" : String(message)) + "\n"); };
  const promptFn = (message) => {
    emit("stdout", message === undefined ? "" : String(message));
    if (!lines.length) {
      // The user's code may catch the exception below, or sit in a loop, so throwing alone cannot
      // end the run. Report "waiting" and "done" right here and mute the worker; the page then
      // tears the frame down, which kills the worker whatever the code is still doing.
      emit("stderr", WAIT_MARKER + "\n");
      postMessage({ type: "done", ok: false });
      closed = true;
      self.close();
      throw new Error(WAIT_MARKER);
    }
    const line = lines.shift();
    emit("echo", line + "\n");
    return line;
  };
  postMessage({ type: "started" });
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  await new AsyncFunction("console", "prompt", "alert", m.code)(con, promptFn, alertFn);
  return true;
}

const BASE = "https://lumio-runtime.invalid/";

async function runPython(m) {
  const a = m.assets;
  const files = {
    "pyodide.asm.wasm": [a.wasm, "application/wasm"],
    "python_stdlib.zip": [a.stdlib, "application/zip"],
  };
  const realFetch = self.fetch.bind(self);
  // Pyodide fetches its wasm and standard library by URL; answer those two from memory.
  self.fetch = (input, init) => {
    const url = input instanceof Request ? input.url : String(input);
    const hit = url.startsWith(BASE) ? files[url.slice(BASE.length)] : undefined;
    if (hit) return Promise.resolve(new Response(hit[0], { headers: { "Content-Type": hit[1] } }));
    return realFetch(input, init);
  };
  const blobUrl = (text) => URL.createObjectURL(new Blob([text], { type: "text/javascript" }));
  const asm = await import(blobUrl(a.asmSource));
  const { loadPyodide } = await import(blobUrl(a.loaderSource));
  const py = await loadPyodide({ indexURL: BASE, lockFileContents: a.lockSource, createPyodideModule: asm.default });
  self.fetch = realFetch;

  const decoders = { stdout: new TextDecoder(), stderr: new TextDecoder() };
  const writer = (type) => ({
    write: (buf) => { emit(type, decoders[type].decode(buf, { stream: true })); return buf.length; },
  });
  py.setStdout(writer("stdout"));
  py.setStderr(writer("stderr"));
  const lines = parseStdin(m.stdin);
  // input() has already written and flushed its prompt when it reads, so the echo lands right after
  // the prompt; Pyodide adds the newline to the returned line itself.
  py.setStdin({
    stdin: () => {
      if (!lines.length) return null;
      const line = lines.shift();
      emit("echo", line + "\n");
      return line;
    },
  });

  postMessage({ type: "started" });
  let ok = true;
  try {
    await py.runPythonAsync(m.code);
  } catch (e) {
    const msg = String(e && e.message ? e.message : e);
    const last = msg.trim().split("\n").pop();
    if (!/^SystemExit(: (0|None))?$/.test(last)) {
      ok = false;
      // Drop Pyodide's own frames; the traceback should start at the user's code.
      const i = msg.indexOf('  File "<exec>"');
      emit("stderr", (i >= 0 ? "Traceback (most recent call last):\n" + msg.slice(i) : msg).replace(/\n*$/, "\n"));
    }
  }
  try { py.runPython("import sys\nsys.stdout.flush()\nsys.stderr.flush()"); } catch (e) {}
  return ok;
}

self.onmessage = async (event) => {
  const m = event.data;
  let ok = true;
  try {
    ok = m.runtime === "python" ? await runPython(m) : await runJavascript(m);
  } catch (e) {
    ok = false;
    emit("stderr", describe(e) + "\n");
  }
  if (closed) return;
  postMessage({ type: "done", ok });
};
`;

const escapeForScript = (json: string) => json.replace(/</g, "\\u003c");

// The frame only relays: it starts the worker and forwards what the worker says.
export function frameDocument(): string {
  const script = String.raw`
const WORKER = ${escapeForScript(JSON.stringify(WORKER_SOURCE))};
let started = false;
function fail(text) {
  parent.postMessage({ type: "stderr", text: text + "\n" }, "*");
  parent.postMessage({ type: "done", ok: false }, "*");
}
addEventListener("message", (e) => {
  const m = e.data;
  if (e.source !== parent || started || !m || m.type !== "run") return;
  started = true;
  try {
    const worker = new Worker(URL.createObjectURL(new Blob([WORKER], { type: "text/javascript" })));
    worker.onmessage = (ev) => parent.postMessage(ev.data, "*");
    worker.onerror = (ev) => fail(ev.message || "The sandbox worker failed to load (" + (ev.filename || "no file") + ")");
    worker.postMessage(m);
  } catch (err) {
    fail("Could not start the sandbox worker: " + err);
  }
});
parent.postMessage({ type: "ready" }, "*");
`;
  return `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="${FRAME_CSP}"></head><body><script>${script}</script></body></html>`;
}
