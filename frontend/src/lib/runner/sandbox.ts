import { frameDocument } from "./frameSource";
import { LOAD_TIMEOUT_MS, RUN_TIMEOUT_MS, parseFrameMessage, type RunEvent, type RunRequest } from "./protocol";

export type SandboxHandle = { stop: () => void };

// Runs the code in a hidden iframe with `sandbox="allow-scripts"` (no `allow-same-origin`), so it
// has an opaque origin and cannot read the app's /api or storage. The frame's CSP also forbids
// network connections. Removing the iframe kills everything in it, which is how both Stop and
// the timeout end an infinite loop.
export function runInSandbox(req: RunRequest, onEvent: (event: RunEvent) => void): SandboxHandle {
  const iframe = document.createElement("iframe");
  iframe.setAttribute("sandbox", "allow-scripts");
  iframe.setAttribute("aria-hidden", "true");
  iframe.tabIndex = -1;
  iframe.style.display = "none";

  let finished = false;
  let began = false;
  let startedAt = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const teardown = () => {
    finished = true;
    clearTimeout(timer);
    window.removeEventListener("message", onMessage);
    iframe.remove();
  };
  const finish = (event: RunEvent) => {
    if (finished) return;
    teardown();
    onEvent(event);
  };
  const arm = (phase: "loading" | "running", limitMs: number) => {
    clearTimeout(timer);
    timer = setTimeout(() => finish({ type: "timeout", phase, limitMs }), limitMs);
  };

  async function begin() {
    if (began) return;
    began = true;
    try {
      const assets = req.runtime === "python" ? (await import("./assets")).loadPythonAssets() : undefined;
      const message = { type: "run", runtime: req.runtime, code: req.code, stdin: req.stdin, assets: await assets };
      if (!finished) iframe.contentWindow?.postMessage(message, "*");
    } catch (e) {
      const reason = e instanceof Error ? e.message : String(e);
      onEvent({ type: "stderr", text: `Could not load the ${req.runtime} runtime: ${reason}\n` });
      finish({ type: "done", ok: false, elapsedMs: 0 });
    }
  }

  function onMessage(e: MessageEvent) {
    if (e.source !== iframe.contentWindow) return;
    const msg = parseFrameMessage(e.data);
    if (!msg) return;
    switch (msg.type) {
      case "ready":
        void begin();
        break;
      case "started":
        startedAt = performance.now();
        arm("running", RUN_TIMEOUT_MS);
        onEvent({ type: "started" });
        break;
      case "stdout":
      case "stderr":
      case "echo":
        onEvent(msg);
        break;
      case "done":
        finish({ type: "done", ok: msg.ok, elapsedMs: startedAt ? performance.now() - startedAt : 0 });
        break;
    }
  }

  window.addEventListener("message", onMessage);
  arm("loading", LOAD_TIMEOUT_MS);
  iframe.srcdoc = frameDocument();
  document.body.appendChild(iframe);

  return { stop: teardown };
}
