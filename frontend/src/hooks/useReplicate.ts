import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { ReplicateStatus } from "../types";

export const replicateKey = ["replicate"] as const;

export function useReplicateStatus() {
  return useQuery({ queryKey: replicateKey, queryFn: api.getReplicate });
}

// Not useMutation on purpose, same as useWebKeyActions: the raw key should not outlive the call.
export function useReplicateKeyActions() {
  const qc = useQueryClient();
  const store = (status: ReplicateStatus) => {
    qc.setQueryData(replicateKey, status);
  };
  return {
    save: async (key: string) => store(await api.setReplicateKey(key)),
    remove: async () => store(await api.deleteReplicateKey()),
  };
}
