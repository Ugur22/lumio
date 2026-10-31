import type { ChatModelBody } from "../types";

interface ShownModelInput {
  // The open chat's override; undefined while it loads or on a blank chat.
  chatModel: string | null | undefined;
  // A blank chat's unsent pick.
  pending: ChatModelBody | null;
  profileModel: string;
  blank: boolean;
}

/** An existing chat shows its own override, a blank one shows the pending pick; otherwise the profile's model. */
export function shownModel({ chatModel, pending, profileModel, blank }: ShownModelInput): string {
  return overrideModel(chatModel, pending, blank) ?? profileModel;
}

/** The override currently in force, or null when the chat follows its profile. */
export function overrideModel(chatModel: string | null | undefined, pending: ChatModelBody | null, blank: boolean): string | null {
  return (blank ? pending?.model : chatModel) || null;
}

/** null clears the override; a model with no known window sends null so the server treats the size as unset. */
const MIN_WINDOW = 1000;

export function modelBody(model: string | null, windows: Readonly<Record<string, number>>): ChatModelBody {
  if (model === null) return { model: null, context_window: null };
  const window = windows[model];
  // The server rejects windows under 1000; a provider reporting one should not make the pick unsendable.
  return { model, context_window: window !== undefined && window >= MIN_WINDOW ? window : null };
}

export const showDefaultItem = (override: string | null): boolean => override !== null;
