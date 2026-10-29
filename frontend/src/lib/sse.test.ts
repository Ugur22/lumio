import { describe, expect, it } from "vitest";
import { parseIllustrationFailure } from "../api";
import { createSseParser, type SseEvent } from "./sse";

function collect(chunks: string[]): SseEvent[] {
  const events: SseEvent[] = [];
  const feed = createSseParser((e) => events.push(e));
  chunks.forEach(feed);
  return events;
}

describe("createSseParser", () => {
  it("parses named events with JSON data", () => {
    expect(collect(['event: delta\ndata: {"text":"hi"}\n\n'])).toEqual([
      { event: "delta", data: '{"text":"hi"}' },
    ]);
  });

  it("reassembles an event split across chunks, even mid-delimiter", () => {
    expect(collect(["event: del", 'ta\ndata: {"a":1}\n', "\nevent: done\ndata: {}\n\n"])).toEqual([
      { event: "delta", data: '{"a":1}' },
      { event: "done", data: "{}" },
    ]);
  });

  it("handles CRLF and holds back an unfinished event", () => {
    expect(collect(["event: a\r\ndata: 1\r\n\r\nevent: b\r\ndata: 2"])).toEqual([{ event: "a", data: "1" }]);
  });
});

describe("illustration_failed event", () => {
  it("parses into a failure, tolerating missing fields", () => {
    const [e] = collect(['event: illustration_failed\ndata: {"prompt":"p","status":400,"detail":"bad"}\n\n']);
    expect(e?.event).toBe("illustration_failed");
    expect(parseIllustrationFailure(JSON.parse(e?.data ?? "{}") as Record<string, unknown>)).toEqual({
      prompt: "p",
      status: 400,
      detail: "bad",
    });
    expect(parseIllustrationFailure({ status: null })).toEqual({ prompt: "", status: null, detail: "" });
  });
});
