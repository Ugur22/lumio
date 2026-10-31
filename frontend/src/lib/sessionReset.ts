import type { QueryClient } from "@tanstack/react-query";
import { useStream } from "../store/stream";
import { clearUserStorage } from "./auth";

// Everything the previous user's session left in the browser, so the next sign-in starts empty.
// Component state (drafts, open dialogs) goes with the unmounted app; this covers what outlives it.
export function resetClientState(qc: QueryClient) {
  void qc.cancelQueries();
  qc.clear();
  useStream.getState().clear();
  useStream.getState().clearFailures();
  clearUserStorage();
}
