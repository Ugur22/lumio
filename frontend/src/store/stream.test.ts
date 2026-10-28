import { beforeEach, describe, expect, it } from "vitest";
import { useStream } from "./stream";

const get = () => useStream.getState();

describe("stream store", () => {
  beforeEach(() => get().clear());

  it("starts as thinking for the given chat", () => {
    get().start("c1", "hi");
    expect(get().pending).toEqual({ text: "hi", chatId: "c1", status: "thinking" });
  });

  it("replaces the reply as it streams in", () => {
    get().start(null, "hi");
    get().setReply("Hel");
    get().setReply("Hello");
    expect(get().pending).toEqual({ text: "hi", chatId: null, status: "streaming", reply: "Hello" });
  });

  it("keeps the question and chat when the stream fails, and drops the partial reply", () => {
    get().start("c1", "hi");
    get().setReply("Hel");
    get().fail("boom");
    expect(get().pending).toEqual({ text: "hi", chatId: "c1", status: "error", error: "boom" });
  });

  it("stays failed when a late reply frame arrives", () => {
    get().start("c1", "hi");
    get().fail("boom");
    get().setReply("late");
    expect(get().pending?.status).toBe("error");
  });

  it("ignores late updates once cleared", () => {
    get().start("c1", "hi");
    get().clear();
    get().setReply("late");
    get().fail("late");
    expect(get().pending).toBeNull();
  });
});
