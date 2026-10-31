import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

const NO_WINDOWS: Record<string, number> = {};
const NO_MODELS: string[] = [];

// Only fetched while the picker is open; the server holds the key, so nothing secret is sent.
export function useProviderModels(profileId: string, enabled = true) {
  const q = useQuery({
    queryKey: ["provider-models", profileId],
    queryFn: () => api.listModels({ profile_id: profileId }),
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
  });
  return {
    models: q.data?.models ?? NO_MODELS,
    windows: q.data?.context_windows ?? NO_WINDOWS,
    error: q.error,
    isPending: q.isPending,
  };
}
