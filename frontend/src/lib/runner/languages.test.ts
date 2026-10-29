import { describe, expect, it } from "vitest";
import { runtimeFor } from "./languages";

describe("runtimeFor", () => {
  it("maps python and javascript names and aliases", () => {
    expect(runtimeFor("python")).toBe("python");
    expect(runtimeFor("py")).toBe("python");
    expect(runtimeFor("javascript")).toBe("javascript");
    expect(runtimeFor("js")).toBe("javascript");
    expect(runtimeFor("JS")).toBe("javascript");
  });

  it("gives other languages and missing ones no runner", () => {
    for (const lang of ["bash", "typescript", "ts", "sql", "", undefined]) expect(runtimeFor(lang)).toBeNull();
  });
});
