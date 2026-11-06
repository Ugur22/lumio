import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createSmoother, FLUSH_MS, releaseCount } from "./smoother";

describe("releaseCount", () => {
  it("lets a fifth of the buffer through, at least one character", () => {
    expect(releaseCount("")).toBe(0);
    expect(releaseCount("a")).toBe(1);
    expect(releaseCount("abcd")).toBe(1);
    expect(releaseCount("a".repeat(10))).toBe(2);
    expect(releaseCount("a".repeat(11))).toBe(3);
    expect(releaseCount("a".repeat(100))).toBe(20);
  });

  it("does not cut a surrogate pair in half", () => {
    expect(releaseCount("😀".repeat(10))).toBe(4); // 20 units, a fifth is 4: whole pairs
    expect(releaseCount("ab" + "😀".repeat(5))).toBe(4); // 12 units, 3 would end on a high surrogate
  });
});

describe("createSmoother", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  function setup() {
    const chunks: string[] = [];
    const smoother = createSmoother((c) => chunks.push(c));
    return { chunks, smoother, shown: () => chunks.join("") };
  }

  it("releases nothing before the first beat, then a fifth per beat", () => {
    const { chunks, smoother } = setup();
    smoother.push("a".repeat(100));
    vi.advanceTimersByTime(FLUSH_MS - 1);
    expect(chunks).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(chunks.map((c) => c.length)).toEqual([20]);
    vi.advanceTimersByTime(FLUSH_MS);
    expect(chunks.map((c) => c.length)).toEqual([20, 16]);
  });

  it("drains a burst steadily and loses no characters", () => {
    const { chunks, smoother, shown } = setup();
    const text = "The rain had been at Vlissen Quay for six days.".repeat(8);
    smoother.push(text.slice(0, 200));
    vi.advanceTimersByTime(FLUSH_MS * 3);
    smoother.push(text.slice(200));
    vi.advanceTimersByTime(FLUSH_MS * 200);
    expect(shown()).toBe(text);
    expect(chunks.length).toBeGreaterThan(5);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("moves a trickle one character per beat", () => {
    const { chunks, smoother } = setup();
    smoother.push("ab");
    vi.advanceTimersByTime(FLUSH_MS);
    expect(chunks).toEqual(["a"]);
    vi.advanceTimersByTime(FLUSH_MS);
    expect(chunks).toEqual(["a", "b"]);
  });

  it("flushes everything at once, for done, errors and Stop", () => {
    const { chunks, smoother, shown } = setup();
    smoother.push("hello ");
    smoother.push("world");
    vi.advanceTimersByTime(FLUSH_MS);
    smoother.flush();
    expect(shown()).toBe("hello world");
    expect(chunks.length).toBe(2);
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(FLUSH_MS * 5);
    expect(shown()).toBe("hello world");
  });

  it("flush with nothing buffered releases nothing", () => {
    const { chunks, smoother } = setup();
    smoother.flush();
    expect(chunks).toEqual([]);
  });

  it("keeps working after a flush", () => {
    const { smoother, shown } = setup();
    smoother.push("one");
    smoother.flush();
    smoother.push("two");
    vi.advanceTimersByTime(FLUSH_MS * 10);
    expect(shown()).toBe("onetwo");
  });

  it("cancel drops the buffer", () => {
    const { chunks, smoother } = setup();
    smoother.push("never shown");
    smoother.cancel();
    vi.advanceTimersByTime(FLUSH_MS * 10);
    expect(chunks).toEqual([]);
    expect(vi.getTimerCount()).toBe(0);
  });
});
