import type { ProfileList, TrialStatus } from "../types";
import { hasOwnProvider, trialActive } from "./trial";

export type EmptyKind = "new" | "ended";

// What a blank chat shows when there is nothing to send to: an account that never had a provider, or one whose
// free trial has run out. Until both answers are in, nothing is shown, so the screen does not flash.
export function emptyKind(profiles: ProfileList | undefined, trial: TrialStatus | undefined, trialSettled: boolean): EmptyKind | null {
  if (!profiles || !trialSettled) return null;
  if (hasOwnProvider(profiles) || trialActive(trial)) return null;
  return trial?.enrolled ? "ended" : "new";
}

export const EMPTY_COPY: Record<EmptyKind, { title: string; body: string }> = {
  new: {
    title: "Connect a provider to start chatting",
    body: "Lumio is a chat app. It sends your messages to an AI model provider that you choose.",
  },
  ended: {
    title: "Your free trial has ended",
    body: "Your chats are still here. Add a provider of your own to keep going.",
  },
};

export const KEY_NOTE = "Your key is stored on your Lumio server, never in this browser.";

export const PROVIDER_EXPLAINER =
  "A provider is a service, such as DeepSeek or OpenAI, that runs the model. You bring an account and an API key from them.";

export const STEPS = ["Pick a provider.", "Paste its API key.", "Choose a model and start."] as const;
