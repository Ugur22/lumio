import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Select } from "./Select";
import { TextInput } from "./TextField";

// 16px on phones stops iOS Safari zooming into a focused field.
describe("phone font size", () => {
  it("applies to text inputs", () => {
    expect(renderToStaticMarkup(<TextInput aria-label="x" />)).toContain("max-[720px]:text-base");
  });

  it("applies to selects, with a 44px target", () => {
    const out = renderToStaticMarkup(<Select value="a" onChange={() => undefined} options={[{ value: "a", label: "A" }]} aria-label="p" />);
    expect(out).toContain("max-[720px]:text-base");
    expect(out).toContain("max-[720px]:min-h-11");
  });
});
