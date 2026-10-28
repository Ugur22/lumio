import { describe, expect, it } from "vitest";
import { fitWithin, MAX_EDGE, MAX_IMAGES, rejectReason } from "./images";

const file = (type: string, name = "a") => new File(["x"], name, { type });

describe("fitWithin", () => {
  it("leaves small images alone", () => {
    expect(fitWithin(800, 600)).toEqual({ width: 800, height: 600 });
  });

  it("scales the long edge down and keeps the aspect ratio", () => {
    expect(fitWithin(3136, 1568)).toEqual({ width: MAX_EDGE, height: 784 });
    expect(fitWithin(1000, 4000, 2000)).toEqual({ width: 500, height: 2000 });
  });

  it("never collapses to zero", () => {
    expect(fitWithin(5000, 1, 100).height).toBe(1);
  });
});

describe("rejectReason", () => {
  it("accepts supported images", () => {
    expect(rejectReason(file("image/png"), 0)).toBeNull();
    expect(rejectReason(file("image/webp"), 3)).toBeNull();
  });

  it("explains an unsupported type by file name", () => {
    expect(rejectReason(file("application/pdf", "report.pdf"), 0)).toContain("report.pdf");
    expect(rejectReason(file("image/svg+xml"), 0)).not.toBeNull();
  });

  it("stops at the per-message limit", () => {
    expect(rejectReason(file("image/png"), MAX_IMAGES)).toContain(String(MAX_IMAGES));
  });
});
