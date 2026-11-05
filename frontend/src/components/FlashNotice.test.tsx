// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useSession } from "../store/session";
import { resetSession } from "../test/helpers";
import { FlashNotice } from "./FlashNotice";

beforeEach(resetSession);
afterEach(cleanup);

describe("FlashNotice", () => {
  it("renders nothing without a flash", () => {
    const { container } = render(<FlashNotice onAddProvider={() => undefined} />);
    expect(container.innerHTML).toBe("");
  });

  it("explains the used trial, offers Providers, and can be dismissed", async () => {
    const user = userEvent.setup();
    const open = vi.fn();
    useSession.getState().reportAuthError("trial_used");
    render(<FlashNotice onAddProvider={open} />);
    expect(screen.getByRole("status").textContent).toContain("already used its free trial");
    await user.click(screen.getByRole("button", { name: "Add provider" }));
    expect(open).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("status")).toBeNull();
  });
});
