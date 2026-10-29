import { describe, expect, it } from "vitest";
import { parseFrameMessage } from "./protocol";

describe("parseFrameMessage", () => {
  it("accepts the messages the frame sends", () => {
    expect(parseFrameMessage({ type: "ready" })).toEqual({ type: "ready" });
    expect(parseFrameMessage({ type: "stdout", text: "hi\n" })).toEqual({ type: "stdout", text: "hi\n" });
    expect(parseFrameMessage({ type: "done", ok: false })).toEqual({ type: "done", ok: false });
  });

  it("accepts echo with a string and drops it otherwise", () => {
    expect(parseFrameMessage({ type: "echo", text: "23 + 33\n", extra: 1 })).toEqual({ type: "echo", text: "23 + 33\n" });
    expect(parseFrameMessage({ type: "echo" })).toBeNull();
    expect(parseFrameMessage({ type: "echo", text: 5 })).toBeNull();
  });

  it("drops anything malformed or unknown and strips extra fields", () => {
    expect(parseFrameMessage(null)).toBeNull();
    expect(parseFrameMessage("done")).toBeNull();
    expect(parseFrameMessage({ type: "stdout", text: 1 })).toBeNull();
    expect(parseFrameMessage({ type: "done", ok: "yes" })).toBeNull();
    expect(parseFrameMessage({ type: "timeout" })).toBeNull();
    expect(parseFrameMessage({ type: "stderr", text: "x", html: "<b>" })).toEqual({ type: "stderr", text: "x" });
  });
});
