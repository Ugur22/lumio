// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QuickActions } from "./MessageList";

afterEach(cleanup);

function setup(props: { focused?: boolean; canAttach?: boolean } = {}) {
  const fns = { onStory: vi.fn(), onScene: vi.fn(), onWeb: vi.fn(), onAttach: vi.fn() };
  render(<QuickActions focused={props.focused ?? false} canAttach={props.canAttach ?? true} {...fns} />);
  return fns;
}

describe("QuickActions", () => {
  it("runs the matching action for each row", async () => {
    const user = userEvent.setup();
    const fns = setup();
    await user.click(screen.getByRole("button", { name: "Continue my story" }));
    await user.click(screen.getByRole("button", { name: "Write a scene" }));
    await user.click(screen.getByRole("button", { name: "Search the web" }));
    await user.click(screen.getByRole("button", { name: "Attach an image" }));
    for (const fn of Object.values(fns)) expect(fn).toHaveBeenCalledTimes(1);
  });

  it("hides the attach row when the provider can't read images", () => {
    setup({ canAttach: false });
    expect(screen.queryByRole("button", { name: "Attach an image" })).toBeNull();
    expect(screen.getAllByRole("button")).toHaveLength(3);
  });

  it("renders nothing while the composer is focused", () => {
    setup({ focused: true });
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("carries the CSS that hides it while the keyboard is open", () => {
    setup();
    expect(screen.getByRole("list").className).toContain("[[data-keyboard=open]_&]:hidden");
  });
});
