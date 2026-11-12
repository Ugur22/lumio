import { describe, expect, it } from "vitest";
import { counterText, labelOf, orbStateOf, phaseOf, sourceDomains, thoughtOf, type PhaseInput } from "./thinking";

const base: PhaseInput = { elapsedMs: 0, reasoning: "", query: null, sources: [], hasText: false };
const phase = (over: Partial<PhaseInput>) => phaseOf({ ...base, ...over });
const src = (url: string) => ({ url, title: "" });

describe("phaseOf", () => {
  it("waits, then admits it is still thinking after 6 seconds without a signal", () => {
    expect(phase({ elapsedMs: 0 })).toBe("waiting");
    expect(phase({ elapsedMs: 5999 })).toBe("waiting");
    expect(phase({ elapsedMs: 6000 })).toBe("still");
  });

  it("thinks as soon as reasoning shows up, whatever the clock says", () => {
    expect(phase({ elapsedMs: 8000, reasoning: "Hmm" })).toBe("thinking");
    expect(phase({ reasoning: "  \n" })).toBe("waiting");
  });

  it("searches once the query is known and reads once sources are", () => {
    expect(phase({ query: "rust release" })).toBe("searching");
    expect(phase({ query: "  " })).toBe("waiting");
    expect(phase({ query: "rust", sources: [src("https://a.com")] })).toBe("reading");
    expect(phase({ reasoning: "x", query: "rust" })).toBe("searching");
  });

  it("writes once text has been shown, over every other phase", () => {
    expect(phase({ hasText: true, reasoning: "x", query: "q", sources: [src("https://a.com")], elapsedMs: 9000 })).toBe("writing");
  });
});

describe("orbStateOf", () => {
  it("gives each visible phase its own orb state", () => {
    expect(orbStateOf("waiting")).toBe("connecting");
    expect(orbStateOf("still")).toBe("breathing");
    expect(orbStateOf("thinking")).toBe("solving");
    expect(orbStateOf("searching")).toBe("searching");
    expect(orbStateOf("reading")).toBe("working");
  });
});

describe("labels and counter", () => {
  it("words each phase", () => {
    expect(labelOf("waiting")).toBe("Thinking");
    expect(labelOf("still")).toBe("Still thinking");
    expect(labelOf("thinking")).toBe("Thinking");
    expect(labelOf("searching")).toBe("Searching the web");
    expect(labelOf("reading")).toBe("Reading sources");
  });

  it("hides the counter until 3 seconds, then counts whole seconds", () => {
    expect(counterText(0)).toBe("");
    expect(counterText(2999)).toBe("");
    expect(counterText(3000)).toBe("· 3s");
    expect(counterText(4999)).toBe("· 4s");
    expect(counterText(61000)).toBe("· 61s");
  });
});

describe("sourceDomains", () => {
  it("lists each web host once, without www, and skips other schemes and junk", () => {
    expect(
      sourceDomains([
        src("https://www.knmi.nl/a"),
        src("https://knmi.nl/b"),
        src("http://deltawerken.com/x"),
        src("javascript:alert(1)"),
        src("https://"),
        src("not a url"),
      ]),
    ).toEqual(["knmi.nl", "deltawerken.com"]);
  });
});

describe("thoughtOf", () => {
  it("is the reasoning and the seconds until the first text, at least 1", () => {
    expect(thoughtOf("why", 1000, 13_400)).toEqual({ text: "why", seconds: 12 });
    expect(thoughtOf("why", 1000, 1200)).toEqual({ text: "why", seconds: 1 });
  });

  it("is null without reasoning or without timestamps", () => {
    expect(thoughtOf("", 0, 5000)).toBeNull();
    expect(thoughtOf("  ", 0, 5000)).toBeNull();
    expect(thoughtOf("why", null, 5000)).toBeNull();
    expect(thoughtOf("why", 0, null)).toBeNull();
  });
});
