import { emptyKind, type EmptyKind } from "../lib/emptyProviders";
import { useProfiles } from "./useProfiles";
import { useTrial } from "./useTrial";

// A failed trial request still counts as answered (it reads as "no trial"), so a flaky endpoint cannot hide the onboarding.
export function useEmptyKind(): EmptyKind | null {
  const profiles = useProfiles().data;
  const trial = useTrial();
  return emptyKind(profiles, trial.data, !trial.isPending);
}
