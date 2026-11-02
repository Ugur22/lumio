// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { stubMatchMedia, stubResizeObserver } from "../../test/helpers";
import { BottomSheet } from "./BottomSheet";

beforeEach(() => {
  stubMatchMedia();
  stubResizeObserver();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("BottomSheet", () => {
  it("renders nothing while closed", () => {
    render(<BottomSheet open={false} onClose={() => undefined} title="Add">x</BottomSheet>);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("is a dialog named by its title and shows its children", () => {
    render(<BottomSheet open onClose={() => undefined} title="Add to message"><button>Row</button></BottomSheet>);
    expect(screen.getByRole("dialog", { name: "Add to message" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Row" })).toBeTruthy();
  });

  it("closes on Escape", async () => {
    const onClose = vi.fn();
    render(<BottomSheet open onClose={onClose} title="Add">x</BottomSheet>);
    await userEvent.setup().keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});
