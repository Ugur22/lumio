import { DialogTitle } from "@headlessui/react";
import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../api";
import {
  isFinished,
  useActiveTranscription,
  useCancelTranscription,
  useDeleteTranscript,
  useSaveTranscript,
  useStartTranscription,
  useTranscript,
  useTranscripts,
  jobGone,
  useTranscriptionJob,
  useTranscriptionStatus,
} from "../hooks/useTranscripts";
import type { JobState, TranscriptSummary } from "../types";
import { CloseIcon, TrashIcon } from "./icons";
import { Button, ConfirmDialog, Modal, PressButton, TextArea, TextField } from "./ui";

export interface AttachedTranscript {
  id: string;
  title: string;
}

interface Props {
  open: boolean;
  chatId: string | null;
  attached: AttachedTranscript | null;
  onAttach: (t: AttachedTranscript | null) => void;
  onClose: () => void;
}

const STAGES: Partial<Record<JobState, string>> = {
  queued: "Waiting to start",
  checking: "Checking video",
  downloading: "Downloading audio",
  converting: "Converting audio",
  transcribing: "Transcribing",
};

const startError = (err: unknown) => {
  const status = err instanceof ApiError ? err.status : 0;
  if (status === 409) return "Another transcription is already running. Cancel it or wait for it to finish, then try again.";
  if (status === 503) return "Transcription isn't available right now. Check the setup notes above.";
  if (status === 404) return "This chat no longer exists. Open another chat and try again.";
  return (err as Error).message;
};

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export function TranscribeDialog({ open, chatId, attached, onAttach, onClose }: Props) {
  return (
    <Modal open={open && chatId !== null} onClose={onClose} className="w-[min(94vw,42rem)]">
      {chatId && <Body key={chatId} chatId={chatId} attached={attached} onAttach={onAttach} onClose={onClose} />}
    </Modal>
  );
}

function Body({ chatId, attached, onAttach, onClose }: Omit<Props, "open" | "chatId"> & { chatId: string }) {
  const status = useTranscriptionStatus();
  const list = useTranscripts(chatId);
  const start = useStartTranscription(chatId);
  const cancel = useCancelTranscription(chatId);
  const del = useDeleteTranscript(chatId);
  const [url, setUrl] = useState("");
  const [language, setLanguage] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [lost, setLost] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<TranscriptSummary | null>(null);
  const jobQuery = useTranscriptionJob(chatId, jobId);
  const job = jobQuery.data;
  const active = useActiveTranscription(chatId).data;

  const available = status.data?.available ?? false;
  const running = jobId !== null && (!job || !isFinished(job.state));

  // Reopening the dialog while a job runs: pick it up instead of letting a second start answer 409.
  useEffect(() => {
    if (jobId === null && active) setJobId(active.id);
  }, [active, jobId]);

  // The server forgot the job (it restarted): stop waiting and say so.
  useEffect(() => {
    if (jobId !== null && jobGone(jobQuery.error)) {
      setJobId(null);
      setLost(true);
    }
  }, [jobId, jobQuery.error]);

  useEffect(() => {
    if (job?.state === "done" && job.transcript_id) {
      setOpenId(job.transcript_id);
      setJobId(null);
    }
  }, [job]);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!available || running || !url.trim()) return;
    setLost(false);
    start.mutate(
      { url: url.trim(), language: language.trim().toLowerCase() || "auto" },
      { onSuccess: (j) => setJobId(j.id) },
    );
  }

  return (
    <div className="flex flex-col gap-5 p-5">
      <div className="flex items-center justify-between gap-2">
        <DialogTitle as="h2" className="font-display text-lg font-semibold">Transcribe a song</DialogTitle>
        <Button variant="bare" aria-label="Close" onClick={onClose} className="grid size-8 place-items-center rounded-lg text-muted hover:text-text">
          <CloseIcon width={18} height={18} />
        </Button>
      </div>

      <form onSubmit={submit} className="flex flex-col gap-3">
        <p className="text-[13px] text-muted">
          Transcription runs on this computer. Sending a transcript to your chat provider shares that text with them.
        </p>
        {status.data && !status.data.available && (
          <p role="status" className="rounded-xl bg-warn-bg px-3 py-2 text-[13px] text-warn-bar">{status.data.reason}</p>
        )}
        {status.error && <p role="alert" className="text-warn-bar">{status.error.message}</p>}
        <TextField
          label="YouTube link"
          type="url"
          inputMode="url"
          placeholder="https://www.youtube.com/watch?v=…"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          disabled={running}
          surface
          description={status.data ? `Up to ${status.data.max_minutes} minutes of audio.` : undefined}
        />
        <TextField
          label="Language (optional)"
          placeholder="auto"
          maxLength={4}
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          disabled={running}
          surface
          fieldClassName="max-w-48"
          description="Leave on auto, or name the language (en, nl, de…). Naming it helps with music."
        />
        <div className="flex flex-wrap items-center gap-2">
          <PressButton type="submit" variant="primary" disabled={!available || running || !url.trim()} loading={start.isPending}>
            Transcribe audio
          </PressButton>
        </div>
        {start.error && <p role="alert" className="text-warn-bar">{startError(start.error)}</p>}
        {lost && <p role="alert" className="text-warn-bar">This transcription was lost, probably because Lumio restarted. Start it again.</p>}
      </form>

      <div aria-live="polite" className="empty:hidden">
        {running && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border px-3 py-2.5">
            <div>
              <p className="font-medium">{STAGES[job?.state ?? "queued"] ?? "Working"}…</p>
              {job?.title && <p className="text-[13px] text-muted">{job.title}</p>}
              {job?.state === "transcribing" && (
                <p className="text-[13px] text-muted">
                  The {status.data?.model ?? "speech"} model can take several minutes on a long song.
                </p>
              )}
            </div>
            <Button variant="secondary" loading={cancel.isPending} onClick={() => jobId && cancel.mutate(jobId)}>
              Cancel
            </Button>
          </div>
        )}
        {job?.state === "failed" && <p role="alert" className="text-warn-bar">{job.error || "Transcription failed."}</p>}
        {job?.state === "cancelled" && <p className="text-muted">Transcription cancelled.</p>}
      </div>
      {cancel.error && <p role="alert" className="text-warn-bar">{cancel.error.message}</p>}

      {openId && <TranscriptView key={openId} chatId={chatId} id={openId} attached={attached} onAttach={onAttach} />}

      <section aria-labelledby="saved-transcripts" className="flex flex-col gap-2">
        <h3 id="saved-transcripts" className="text-[13px] font-medium">Saved transcripts</h3>
        {list.isSuccess && list.data.length === 0 && <p className="text-[13px] text-muted">None in this chat yet.</p>}
        {list.error && <p role="alert" className="text-warn-bar">{list.error.message}</p>}
        <ul className="flex flex-col gap-1.5">
          {list.data?.map((t) => (
            <li key={t.id} className="flex items-center justify-between gap-2 rounded-xl border border-border px-3 py-2">
              <div className="min-w-0">
                <p className="truncate font-medium">{t.title}</p>
                <p className="text-[12px] text-muted">{t.language} · {t.model}{t.edited ? " · edited" : ""}</p>
              </div>
              <div className="flex flex-none items-center gap-1">
                <Button aria-label={`Open ${t.title}`} onClick={() => setOpenId(t.id)}>Open</Button>
                <Button variant="danger" aria-label={`Delete ${t.title}`} onClick={() => setDeleting(t)}>
                  <TrashIcon width={16} height={16} />
                </Button>
              </div>
            </li>
          ))}
        </ul>
        {del.error && <p role="alert" className="text-warn-bar">{del.error.message}</p>}
      </section>

      <ConfirmDialog
        open={deleting !== null}
        title="Delete this transcript?"
        description={deleting ? `"${deleting.title}" will be removed from this chat.` : undefined}
        confirmLabel="Delete"
        danger
        onCancel={() => setDeleting(null)}
        onConfirm={() => {
          if (!deleting) return;
          const gone = deleting.id;
          setDeleting(null);
          del.mutate(gone, {
            onSuccess: () => {
              setOpenId((cur) => (cur === gone ? null : cur));
              if (attached?.id === gone) onAttach(null);
            },
          });
        }}
      />
    </div>
  );
}

function TranscriptView({ chatId, id, attached, onAttach }: { chatId: string; id: string; attached: AttachedTranscript | null; onAttach: (t: AttachedTranscript | null) => void }) {
  const { data, error } = useTranscript(chatId, id);
  const save = useSaveTranscript(chatId, id);
  const [draft, setDraft] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);

  if (error) return <p role="alert" className="text-warn-bar">{error.message}</p>;
  if (!data) return <p className="text-muted">Loading transcript…</p>;

  const saved = data.edited_text ?? data.original_text;
  const text = draft ?? saved;
  const isAttached = attached?.id === id;

  return (
    <section aria-label="Transcript" className="flex flex-col gap-3 rounded-2xl border border-border p-4">
      <div>
        <h3 dir="auto" className="font-display text-base font-semibold">{data.title}</h3>
        <p className="break-all text-[12px] text-muted">{data.url}</p>
        <p className="text-[12px] text-muted">Model {data.model} · language {data.language}</p>
      </div>
      <TextArea
        aria-label="Transcript text"
        dir="auto"
        rows={10}
        surface
        value={text}
        onChange={(e) => setDraft(e.target.value)}
        className="w-full font-serif leading-relaxed"
      />
      <div className="flex flex-wrap items-center gap-2">
        <PressButton
          variant="primary"
          disabled={text === saved || !text.trim()}
          loading={save.isPending}
          onClick={() => save.mutate(text, { onSuccess: () => setDraft(null) })}
        >
          Save edits
        </PressButton>
        <Button variant="secondary" disabled={data.edited_text === null || save.isPending} onClick={() => setConfirmReset(true)}>
          Reset to original
        </Button>
        {isAttached ? (
          <Button variant="secondary" onClick={() => onAttach(null)}>Detach from chat</Button>
        ) : (
          <Button variant="secondary" onClick={() => onAttach({ id, title: data.title })}>Attach to chat</Button>
        )}
      </div>
      {confirmReset && (
        <div role="alertdialog" aria-label="Confirm reset" className="flex flex-wrap items-center gap-2 rounded-xl bg-warn-bg px-3 py-2 text-warn-bar">
          <span className="text-[13px]">Discard your edits and restore the original text?</span>
          <Button
            variant="destructive"
            autoFocus
            onClick={() => save.mutate(null, { onSuccess: () => { setDraft(null); setConfirmReset(false); } })}
          >
            Restore original
          </Button>
          <Button onClick={() => setConfirmReset(false)}>Keep my edits</Button>
        </div>
      )}
      {save.error && <p role="alert" className="text-warn-bar">{save.error.message}</p>}
      <details>
        <summary className="cursor-pointer text-[13px] text-muted">Original text</summary>
        <p dir="auto" className="mt-2 whitespace-pre-wrap font-serif text-[14px]">{data.original_text}</p>
      </details>
      <details>
        <summary className="cursor-pointer text-[13px] text-muted">Timestamped segments</summary>
        <ol className="mt-2 flex flex-col gap-1 text-[13px]">
          {data.segments.map((s, i) => (
            <li key={i} className="flex gap-3">
              <time className="flex-none tabular-nums text-muted">{clock(s.start)}</time>
              <span dir="auto">{s.text}</span>
            </li>
          ))}
        </ol>
      </details>
    </section>
  );
}
