import { describe, expect, it } from "vitest";
import { FRAME_CSP, WORKER_SOURCE, frameDocument } from "./frameSource";

describe("sandbox frame", () => {
  it("reads the URL of a fetch call that passes a URL object, which has no .url", () => {
    expect(WORKER_SOURCE).toContain("input instanceof Request ? input.url : String(input)");
  });

  it("starts a classic worker, since module workers fail to load from blob URLs without an origin", () => {
    expect(frameDocument()).not.toContain('type: \\"module\\"');
    expect(frameDocument()).not.toContain('type: "module"');
  });

  it("echoes each line handed to input() after the prompt", () => {
    expect(WORKER_SOURCE).toContain('emit("echo", line + "\\n")');
  });

  it("forbids network connections and nested content", () => {
    expect(FRAME_CSP).toContain("connect-src 'none'");
    expect(FRAME_CSP).toContain("default-src 'none'");
    expect(FRAME_CSP).not.toMatch(/https?:|\*/);
  });

  it("applies the policy before any script and embeds the worker without closing the script tag", () => {
    const doc = frameDocument();
    expect(doc.indexOf("Content-Security-Policy")).toBeLessThan(doc.indexOf("<script>"));
    expect(doc.match(/<\/script>/g)).toHaveLength(1);
  });
});
