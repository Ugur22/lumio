import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { WebStatus } from "../types";

export const webKey = ["web"] as const;

export function useWebStatus() {
  return useQuery({ queryKey: webKey, queryFn: api.getWebStatus });
}

// Not useMutation on purpose, for the same reason as useProfileActions: the raw key
// should not outlive the call.
export function useWebKeyActions() {
  const qc = useQueryClient();
  const store = (status: WebStatus) => {
    qc.setQueryData(webKey, status);
  };
  return {
    save: async (key: string) => store(await api.setWebKey(key)),
    remove: async () => store(await api.deleteWebKey()),
  };
}
