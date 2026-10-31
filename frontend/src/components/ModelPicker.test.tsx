import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ModelChoices, ModelPicker } from "./ModelPicker";

const noop = () => undefined;
const choices = (over: Partial<Parameters<typeof ModelChoices>[0]> = {}) =>
  renderToStaticMarkup(
    <ModelChoices
      heading="Model for this chat"
      current="gpt-4o"
      defaultModel="base-model"
      showDefault={false}
      models={["openai/gpt-4o", "gpt-4o", "meta/llama"]}
      loading={false}
      error={null}
      onPick={noop}
      onManage={noop}
      {...over}
    />,
  );

describe("ModelChoices", () => {
  it("lists vendor groups, the heading and the settings item last", () => {
    const out = choices();
    expect(out).toContain("Model for this chat");
    expect(out).toContain("openai");
    expect(out).toContain("Other");
    expect(out.lastIndexOf("Provider settings")).toBeGreaterThan(out.lastIndexOf("meta/llama"));
  });

  it("offers the provider default only when asked", () => {
    expect(choices()).not.toContain("Use provider default");
    expect(choices({ showDefault: true })).toContain("Use provider default (base-model)");
  });

  it("shows a fetch failure inline and still offers the settings link", () => {
    const out = choices({ models: [], error: "Couldn't load models: no key" });
    expect(out).toContain("Couldn&#x27;t load models: no key");
    expect(out).toContain("Provider settings");
  });
});

describe("ModelPicker", () => {
  it("renders closed with the shown model and no list request", () => {
    const out = renderToStaticMarkup(
      <ModelPicker
        disabled={false}
        heading="Model for this chat"
        current="gpt-4o"
        defaultModel="base"
        showDefault={false}
        profileId="p1"
        saveError={null}
        onPickWithWindows={noop}
        onManage={noop}
      />,
    );
    expect(out).toContain("gpt-4o");
    expect(out).not.toContain("Model for this chat");
  });
});
