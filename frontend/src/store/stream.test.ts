import { beforeEach, describe, expect, it, vi } from "vitest";
import { useStream } from "./stream";

const get = () => useStream.getState();

describe("stream store", () => {
  beforeEach(() => get().clear());

  it("starts as thinking for the given chat", () => {
    get().start("c1", "hi");
    expect(get().pending).toEqual({ text: "hi", chatId: "c1", images: [], status: "thinking" });
  });

  it("keeps the thumbnails through the turn and revokes them when it is cleared", () => {
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    get().start("c1", "hi", ["blob:a", "blob:b"]);
    get().setReply("Hel");
    expect(get().pending?.images).toEqual(["blob:a", "blob:b"]);
    get().clear();
    expect(revoke).toHaveBeenCalledWith("blob:a");
    expect(revoke).toHaveBeenCalledWith("blob:b");
    revoke.mockRestore();
  });

  it("replaces the reply as it streams in", () => {
    get().start(null, "hi");
    get().setReply("Hel");
    get().setReply("Hello");
    expect(get().pending).toEqual({ text: "hi", chatId: null, images: [], status: "streaming", reply: "Hello" });
  });

  it("keeps the question and chat when the stream fails, and drops the partial reply", () => {
    get().start("c1", "hi");
    get().setReply("Hel");
    get().fail("boom");
    expect(get().pending).toEqual({ text: "hi", chatId: "c1", images: [], status: "error", error: "boom" });
  });

  it("stays failed when a late reply frame arrives", () => {
    get().start("c1", "hi");
    get().fail("boom");
    get().setReply("late");
    expect(get().pending?.status).toBe("error");
  });

  it("holds the sources read for the turn, and forgets them on the next turn", () => {
    get().start("c1", "hi");
    get().setSources([{ url: "https://a.com", title: "A" }], ["Could not read https://b.com"]);
    expect(get().sources).toEqual([{ url: "https://a.com", title: "A" }]);
    expect(get().notes).toEqual(["Could not read https://b.com"]);

    get().clear();
    get().start("c1", "again");
    expect(get().sources).toEqual([]);
  });

  it("ignores sources that arrive after the turn was cleared", () => {
    get().start("c1", "hi");
    get().clear();
    get().setSources([{ url: "https://a.com", title: "A" }], []);
    expect(get().sources).toEqual([]);
  });

  it("ignores late updates once cleared", () => {
    get().start("c1", "hi");
    get().clear();
    get().setReply("late");
    get().fail("late");
    expect(get().pending).toBeNull();
  });
});
