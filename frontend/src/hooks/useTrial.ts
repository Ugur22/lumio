import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

export const trialKey = ["trial"] as const;

// Not refetched on a timer: the count moves only when a reply says so (see useSendMessage), which invalidates this.
// `data` is undefined until the answer arrives or when the request failed; both read as "no trial".
export function useTrial() {
  return useQuery({ queryKey: trialKey, queryFn: api.getTrial });
}
