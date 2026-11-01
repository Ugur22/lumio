// @vitest-environment jsdom
import { cleanup, renderHook, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useStreamingSend } from "../hooks/useStreamingSend";
import { bodyOf, json, mockFetch, noContent, renderWithClient, stubMatchMedia, stubResizeObserver } from "../test/helpers";
import { Composer } from "./Composer";
import { TranscribeDialog } from "./TranscribeDialog";

beforeEach(() => {
  stubMatchMedia();
  stubResizeObserver();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const putBody = (fn: ReturnType<typeof mockFetch>) =>
  fn.mock.calls.map(([, i]) => i).find((i) => i?.method === "PUT")?.body;

const ok = { available: true, reason: "", model: "large-v3", max_minutes: 20, max_download_mb: 100 };
const job = (state: string, extra = {}) => ({ id: "j1", chat_id: "c1", url: "u", state, title: "Song", error: "", transcript_id: null as string | null, ...extra });
const transcript = (extra = {}) => ({
  id: "t1", title: "Song", url: "https://youtu.be/x", language: "en", model: "large-v3", created: "", edited: false,
  video_id: "x", original_text: "la la", edited_text: null as string | null, segments: [{ start: 65, end: 70, text: "la la" }], ...extra,
});

function renderDialog(overrides: Record<string, unknown> = {}) {
  return renderWithClient(<TranscribeDialog open chatId="c1" attached={null} onAttach={() => undefined} onClose={() => undefined} {...overrides} />);
}

describe("TranscribeDialog", () => {
  it("shows the reason and disables the action when unavailable", async () => {
    mockFetch((url) =>
      url === "/api/transcription" ? json({ ...ok, available: false, reason: "Install whisper.cpp first." }) : json([]),
    );
    renderDialog();
    expect(await screen.findByText("Install whisper.cpp first.")).toBeTruthy();
    await userEvent.type(screen.getByLabelText("YouTube link"), "https://youtu.be/x");
    expect((screen.getByRole("button", { name: "Transcribe audio" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows the stage while running and cancels with DELETE", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch((url, init) => {
      if (url === "/api/transcription") return json(ok);
      if (url === "/api/chats/c1/transcripts") return json([]);
      if (url === "/api/chats/c1/transcriptions") return init?.method === "POST" ? json(job("queued"), 202) : json(null);
      if (init?.method === "DELETE") return json(job("cancelled"));
      return json(job("downloading"));
    });
    renderDialog();
    await waitFor(() => expect((screen.getByRole("button", { name: "Transcribe audio" }) as HTMLButtonElement).disabled).toBe(true));
    await user.type(screen.getByLabelText("YouTube link"), "https://youtu.be/x");
    await waitFor(() => expect((screen.getByRole("button", { name: "Transcribe audio" }) as HTMLButtonElement).disabled).toBe(false));
    await user.click(screen.getByRole("button", { name: "Transcribe audio" }));
    const post = fetchMock.mock.calls.find(([u, i]) => u === "/api/chats/c1/transcriptions" && i?.method === "POST");
    expect(JSON.parse(post?.[1]?.body as string)).toEqual({ url: "https://youtu.be/x", language: "auto" });
    expect(await screen.findByText("Downloading audio…")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u, i]) => u === "/api/chats/c1/transcriptions/j1" && i?.method === "DELETE")).toBe(true),
    );
    expect(await screen.findByText("Transcription cancelled.")).toBeTruthy();
  });

  it("shows the job error when it fails", async () => {
    const user = userEvent.setup();
    mockFetch((url, init) => {
      if (url === "/api/transcription") return json(ok);
      if (url === "/api/chats/c1/transcripts") return json([]);
      if (url === "/api/chats/c1/transcriptions") return init?.method === "POST" ? json(job("queued"), 202) : json(null);
      return json(job("failed", { error: "Video is private." }));
    });
    renderDialog();
    await waitFor(() => expect(screen.getByLabelText("YouTube link")).toBeTruthy());
    await user.type(screen.getByLabelText("YouTube link"), "https://youtu.be/x");
    await waitFor(() => expect((screen.getByRole("button", { name: "Transcribe audio" }) as HTMLButtonElement).disabled).toBe(false));
    await user.click(screen.getByRole("button", { name: "Transcribe audio" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Video is private.");
  });

  it("picks up a running job when the dialog is reopened", async () => {
    mockFetch((url) => {
      if (url === "/api/transcription") return json(ok);
      if (url === "/api/chats/c1/transcripts") return json([]);
      if (url === "/api/chats/c1/transcriptions") return json(job("transcribing"));
      return json(job("transcribing"));
    });
    renderDialog();
    expect(await screen.findByRole("button", { name: "Cancel" })).toBeTruthy();
  });

  it("stops waiting when the server no longer knows the job", async () => {
    mockFetch((url) => {
      if (url === "/api/transcription") return json(ok);
      if (url === "/api/chats/c1/transcripts") return json([]);
      if (url === "/api/chats/c1/transcriptions") return json(job("transcribing"));
      return json({ detail: "Transcription not found" }, 404);
    });
    renderDialog();
    expect(await screen.findByText(/This transcription was lost/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
  });

  describe("transcript view", () => {
    const setup = (current = transcript()) => {
      let t = current;
      const fetchMock = mockFetch((url, init) => {
        if (url === "/api/transcription") return json(ok);
        if (url === "/api/chats/c1/transcripts") return json([{ ...t }]);
        if (init?.method === "PUT") {
          const { edited_text } = JSON.parse(init.body as string) as { edited_text: string | null };
          t = { ...t, edited_text };
          return json(t);
        }
        return json(t);
      });
      renderDialog();
      return fetchMock;
    };

    it("saves edited text with PUT", async () => {
      const user = userEvent.setup();
      const fetchMock = setup();
      await user.click(await screen.findByRole("button", { name: "Open Song" }));
      const box = await screen.findByLabelText("Transcript text");
      await user.clear(box);
      await user.type(box, "fixed");
      await user.click(screen.getByRole("button", { name: "Save edits" }));
      await waitFor(() => expect(JSON.parse(String(putBody(fetchMock)))).toEqual({ edited_text: "fixed" }));
    });

    it("resets to the original with null after an in-page confirmation", async () => {
      const user = userEvent.setup();
      const fetchMock = setup(transcript({ edited_text: "mine", edited: true }));
      await user.click(await screen.findByRole("button", { name: "Open Song" }));
      await user.click(await screen.findByRole("button", { name: "Reset to original" }));
      expect(fetchMock.mock.calls.some(([, i]) => i?.method === "PUT")).toBe(false);
      await user.click(screen.getByRole("button", { name: "Restore original" }));
      await waitFor(() => expect(JSON.parse(String(putBody(fetchMock)))).toEqual({ edited_text: null }));
    });

    it("deletes a saved transcript", async () => {
      const user = userEvent.setup();
      const fetchMock = mockFetch((url, init) =>
        url === "/api/transcription" ? json(ok) : init?.method === "DELETE" ? noContent() : json([transcript()]),
      );
      renderDialog();
      await user.click(await screen.findByRole("button", { name: "Delete Song" }));
      await user.click(await screen.findByRole("button", { name: "Delete" }));
      await waitFor(() => expect(fetchMock.mock.calls.some(([, i]) => i?.method === "DELETE")).toBe(true));
    });
  });
});

describe("transcript chip", () => {
  it("shows the chip with its privacy note and a remove button", () => {
    const out = renderToStaticMarkup(
      <Composer disabled={false} vision={false} providerName={null} transcript={{ id: "t1", title: "Song" }} onSend={() => undefined} onStop={() => undefined} />,
    );
    expect(out).toContain("Transcript: Song");
    expect(out).toContain("Sends this transcript to your chat provider");
    expect(out).toContain('aria-label="Remove transcript"');
  });

  it("adds transcript_id to the send request only when one is attached", async () => {
    const fetchMock = mockFetch(() => new Response("event: done\ndata: " + JSON.stringify({ id: "c1", messages: [], context: null, usage: null }) + "\n\n"));
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
    const { result } = renderHook(() => useStreamingSend(), { wrapper });
    result.current.send("c1", "hi", [], false, false, () => undefined, undefined, "t1");
    await waitFor(() => expect(bodyOf(fetchMock, "/api/chats/c1/messages")?.transcript_id).toBe("t1"));
    fetchMock.mockClear();
    result.current.send("c1", "again", [], false, false, () => undefined);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(bodyOf(fetchMock, "/api/chats/c1/messages")).not.toHaveProperty("transcript_id");
  });
});
