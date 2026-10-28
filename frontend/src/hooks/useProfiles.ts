import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { EditProfileBody, NewProfileBody, ProfileList } from "../types";

export const profilesKey = ["profiles"] as const;

export function useProfiles() {
  return useQuery({ queryKey: profilesKey, queryFn: api.listProfiles });
}

// Not useMutation on purpose: TanStack keeps mutation variables in memory, and a raw
// API key should not outlive the call.
export function useProfileActions() {
  const qc = useQueryClient();
  // The window belongs to the active profile, so any profile change can change every chat's meter.
  const store = (list: ProfileList) => {
    qc.setQueryData(profilesKey, list);
    void qc.invalidateQueries({ queryKey: ["context"] });
  };
  return {
    create: async (body: NewProfileBody) => store(await api.createProfile(body)),
    edit: async (id: string, body: EditProfileBody) => store(await api.editProfile(id, body)),
    remove: async (id: string) => store(await api.deleteProfile(id)),
    activate: async (id: string) => store(await api.activateProfile(id)),
    models: api.listModels,
  };
}
