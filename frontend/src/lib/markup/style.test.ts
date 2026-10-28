import { describe, expect, it } from "vitest";
import { safeStyle } from "./style";

describe("safeStyle", () => {
  it("keeps plain visual properties", () => {
    expect(safeStyle("background:#17212b; color: #fff; border-radius:12px; padding:8px 10px")).toBe(
      "background:#17212b;color:#fff;border-radius:12px;padding:8px 10px",
    );
  });

  it("drops properties that are not on the list", () => {
    expect(safeStyle("position:fixed; z-index:9999; top:0; color:red")).toBe("color:red");
  });

  it("drops values that load, escape or run things", () => {
    for (const bad of [
      "background:url(https://x.test/a.png)",
      "background:red url( x )",
      "width:100vw",
      "height:100vh",
      "color:var(--text)",
      "color:expression(alert(1))",
      "color:\\72 ed",
      "margin-left:-40px",
      "margin:0 -10px",
      "color:red}</style>",
    ]) {
      expect(safeStyle(bad), bad).toBe("");
    }
  });

  it("allows only listed keywords for keyword-valued properties", () => {
    expect(safeStyle("display:flex")).toBe("display:flex");
    expect(safeStyle("display:grid")).toBe("");
    expect(safeStyle("font-family:monospace")).toBe("font-family:monospace");
    expect(safeStyle("font-family:Papyrus")).toBe("");
  });

  it("allows a capped blur and nothing else as a filter", () => {
    expect(safeStyle("filter:blur(8px)")).toBe("filter:blur(8px)");
    expect(safeStyle("filter:blur(400px)")).toBe("");
    expect(safeStyle("filter:drop-shadow(0 0 4px red)")).toBe("");
    expect(safeStyle("filter:blur(4px) url(x)")).toBe("");
    expect(safeStyle("overflow:hidden")).toBe("overflow:hidden");
    expect(safeStyle("overflow:scroll")).toBe("");
  });

  it("drops overlong values and malformed declarations", () => {
    expect(safeStyle(`color:${"a".repeat(100)}`)).toBe("");
    expect(safeStyle("nonsense; :; color")).toBe("");
  });
});
