import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import type { JobState, TranscribeBody, Transcript } from "../types";

export const transcriptionStatusKey = ["transcription"] as const;
export const transcriptsKey = (chatId: string) => ["transcripts", chatId] as const;
const transcriptKey = (chatId: string, id: string) => ["transcript", chatId, id] as const;
const activeKey = (chatId: string) => ["transcription-active", chatId] as const;
const jobKey = (chatId: string, jobId: string) => ["transcription-job", chatId, jobId] as const;

// The server keeps jobs in memory only, so a restart makes a running job 404.
export const jobGone = (e: unknown) => e instanceof ApiError && e.status === 404;
export const isFinished = (state: JobState) => state === "done" || state === "failed" || state === "cancelled";

export function useTranscriptionStatus() {
  return useQuery({ queryKey: transcriptionStatusKey, queryFn: api.getTranscriptionStatus });
}

export function useTranscripts(chatId: string) {
  return useQuery({ queryKey: transcriptsKey(chatId), queryFn: () => api.listTranscripts(chatId) });
}

export function useTranscript(chatId: string, id: string | null) {
  return useQuery({
    queryKey: transcriptKey(chatId, id ?? ""),
    queryFn: () => api.getTranscript(chatId, id as string),
    enabled: id !== null,
  });
}

// The running job of this chat, so a dialog that was closed (or a page that was reloaded) finds it again.
export function useActiveTranscription(chatId: string) {
  return useQuery({
    queryKey: activeKey(chatId),
    queryFn: () => api.getActiveTranscription(chatId),
    staleTime: 0,
    refetchOnMount: "always",
  });
}

export function useStartTranscription(chatId: string) {
  return useMutation({ mutationFn: (body: TranscribeBody) => api.startTranscription(chatId, body) });
}

export function useCancelTranscription(chatId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => api.cancelTranscription(chatId, jobId),
    onSuccess: (job) => qc.setQueryData(jobKey(chatId, job.id), job),
  });
}

// Polling stops by itself on unmount (the observer goes away) and once the job reaches a final state.
export function useTranscriptionJob(chatId: string, jobId: string | null) {
  const qc = useQueryClient();
  return useQuery({
    queryKey: jobKey(chatId, jobId ?? ""),
    queryFn: async () => {
      const job = await api.getTranscriptionJob(chatId, jobId as string).catch((e: unknown) => {
        if (jobGone(e)) qc.setQueryData(activeKey(chatId), null); // else the dialog would adopt the dead job again
        throw e;
      });
      if (job.state === "done") void qc.invalidateQueries({ queryKey: transcriptsKey(chatId) });
      if (isFinished(job.state)) qc.setQueryData(activeKey(chatId), null);
      return job;
    },
    enabled: jobId !== null,
    retry: false,
    refetchInterval: (query) => (jobGone(query.state.error) || (query.state.data && isFinished(query.state.data.state)) ? false : 1000),
    staleTime: 0,
  });
}

export function useSaveTranscript(chatId: string, id: string) {
  const qc = useQueryClient();
  const stored = (t: Transcript) => {
    qc.setQueryData(transcriptKey(chatId, id), t);
    void qc.invalidateQueries({ queryKey: transcriptsKey(chatId) });
  };
  // null resets to the original text.
  return useMutation({
    mutationFn: (editedText: string | null) => api.saveTranscript(chatId, id, { edited_text: editedText }),
    onSuccess: stored,
  });
}

export function useDeleteTranscript(chatId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteTranscript(chatId, id),
    onSuccess: (_, id) => {
      qc.removeQueries({ queryKey: transcriptKey(chatId, id) });
      return qc.invalidateQueries({ queryKey: transcriptsKey(chatId) });
    },
  });
}
