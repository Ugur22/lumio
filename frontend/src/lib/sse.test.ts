import { describe, expect, it } from "vitest";
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
