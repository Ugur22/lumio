import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { InviteCreate } from "../types";

export const invitesKey = ["admin", "invites"] as const;

// Fetched only while the page is open; the list changes when the admin acts, so nothing refetches on a timer.
export function useInvites(enabled: boolean) {
  return useQuery({ queryKey: invitesKey, queryFn: api.listInvites, enabled });
}

// Plain functions, not useMutation: TanStack keeps a mutation's result in memory, and a one-time code should not
// outlive the dialog that shows it.
export function useInviteActions() {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: invitesKey });
  return {
    create: async (body: InviteCreate) => {
      const made = await api.createInvite(body);
      void refresh();
      return made;
    },
    // A 409 means it was used meanwhile, so the list is stale whether this worked or not.
    revoke: async (id: string) => {
      try {
        await api.revokeInvite(id);
      } finally {
        void refresh();
      }
    },
  };
}
