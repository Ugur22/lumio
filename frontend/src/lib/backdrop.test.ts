import { describe, expect, it } from "vitest";
import { isBackdropClick } from "./backdrop";

const dialog = new EventTarget();
const input = new EventTarget();

describe("isBackdropClick", () => {
  it("closes when the press and the click both hit the backdrop", () => {
    expect(isBackdropClick(dialog, dialog, dialog)).toBe(true);
  });

  it("ignores a drag that started in a field and was released on the backdrop", () => {
    expect(isBackdropClick(input, dialog, dialog)).toBe(false);
  });

  it("ignores clicks inside the dialog and clicks with no recorded press", () => {
    expect(isBackdropClick(input, input, dialog)).toBe(false);
    expect(isBackdropClick(null, dialog, dialog)).toBe(false);
    expect(isBackdropClick(null, null, null)).toBe(false);
  });
});
