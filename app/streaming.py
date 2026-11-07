"""Streaming a reply to the client as server-sent events, illustrating it, and saving the finished turn."""

import asyncio
import json
import re
import sqlite3
from collections.abc import AsyncIterator

from fastapi.concurrency import run_in_threadpool
from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

import images
import storage
from app import providers, runtime
from app.logs import log
from app.story import DIRECTIVE, UNCLOSED, context_info
from models import Chat, ImageData, ImageRef, Message, Source, Usage

EMPTY_REPLY = "The model returned no answer. Try again or rephrase."
MAX_ILLUSTRATIONS = 3
MAX_IMAGE_PROMPT_CHARS = 1_000
MAX_PER_REPLY = f"at most {MAX_ILLUSTRATIONS} pictures per reply"
# [[img:<id>]] is what a directive becomes once its image is stored. The grammar (app/story.py) is the clients' own, so
# what they show as "Illustrating..." is what is generated; a narrower one would leave their skeleton with no picture.
_DIRECTIVE = DIRECTIVE
_UNCLOSED = UNCLOSED
_OPENER = "[[image:"


class DirectiveFilter:
    """Keeps [[image: ...]] directives out of the text streamed when no pictures are being made, so a client never
    shows a skeleton for one. Holds back only what could still turn into a directive: a partial `[[image:` at the end of a
    chunk, or an opened directive until its `]]`."""

    def __init__(self) -> None:
        self.held = ""

    def feed(self, text: str) -> str:
        buf, out = self.held + text, []
        while True:
            at = buf.find(_OPENER)
            if at < 0:
                break
            end = buf.find("]]", at + len(_OPENER))
            if end < 0:
                out.append(buf[:at])
                self.held = buf[at:]  # opened, not closed yet
                return "".join(out)
            out.append(buf[:at])
            buf = buf[end + 2 :]
        keep = next((n for n in range(min(len(_OPENER) - 1, len(buf)), 0, -1) if _OPENER.startswith(buf[-n:])), 0)
        out.append(buf[: len(buf) - keep])
        self.held = buf[len(buf) - keep :]
        return "".join(out)

    def finish(self) -> str:
        """The held tail at the end of the reply: a cut-off directive goes (as strip_directives drops it from the saved text), a stray `[` stays."""
        held, self.held = self.held, ""
        return "" if held.startswith(_OPENER) else held


def make_title(content: str, limit: int = 50) -> str:
    text = " ".join(content.split())
    if len(text) <= limit:
        return text or "Image"
    cut = text[:limit].rsplit(" ", 1)[0] if " " in text[:limit] else text[:limit]
    return cut.rstrip(" ,;:-") + "…"


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def tidy(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text)


def clean_prompt(raw: str) -> str:
    return " ".join(raw.split())


def strip_directives(text: str) -> str:
    """Removes every directive, closed or not: raw `[[image: ...]]` is never shown as text."""
    if "[[image:" not in text:
        return text
    return tidy(_UNCLOSED.sub("", _DIRECTIVE.sub("", text)))


class IllustrationFailure(BaseModel):
    prompt: str
    status: int | None
    detail: str


def append_turn(
    chat: Chat,
    lease: storage.Lease,
    content: str,
    reply: str,
    sources: list[Source],
    uploads: list[ImageData] = (),
    query: str | None = None,
    usage: Usage | None = None,
    reply_images: list[ImageRef] = (),
    rev: int | None = None,
) -> Chat:
    """Adds the question and its reply to the stored chat.

    Raises storage.ChatNotFound if it was deleted meanwhile and storage.LeaseLost if `lease` no longer owns the chat;
    either way nothing is stored and the files saved for the uploads are removed.
    """
    refs = images.save_images(runtime.settings, chat.id, list(uploads))
    try:
        return runtime.db.append_generated(
            lease,
            [
                Message(role="user", content=content, sources=sources, images=refs, query=query),
                Message(role="assistant", content=reply, images=list(reply_images)),
            ],
            title=make_title(content),
            usage=usage,
            rev=rev,
        )
    except BaseException:
        images.delete_images(runtime.settings, chat.id, [*refs, *reply_images])
        raise


class StopReport:
    """Where a cancelled stream_reply leaves its last frame (done if the partial reply was saved, else error), so the
    job can close its readers with a terminal event instead of a silent end."""

    def __init__(self) -> None:
        self.frame: str | None = None
        self.event = asyncio.Event()

    def set(self, frame: str) -> None:
        if self.frame is None:
            self.frame = frame
            self.event.set()


def save_failure(e: BaseException) -> str:
    """The `error` frame for a save that did not happen."""
    if isinstance(e, storage.ChatNotFound):
        return sse("error", {"detail": "This chat was deleted while the reply was being written"})
    if isinstance(e, storage.LeaseLost):
        log.warning("Reply not saved: its generation lease expired or was taken over")
        return sse("error", {"detail": "This reply was not saved because another request took over this chat. Try again."})
    log.error("Could not save the reply", exc_info=e)
    return sse("error", {"detail": "The reply could not be saved. Try again."})


async def stream_reply(
    chat: Chat,
    content: str,
    stream,
    sources: list[Source],
    notes: list[str],
    uploads: list[ImageData] = (),
    query: str | None = None,
    window: int | None = None,
    illustrate: tuple[OpenAI, str, str | None] | None = None,
    *,
    lease: storage.Lease,
    rev: int | None = None,
    trial_call: storage.TrialCall | None = None,
    key: str | None = None,
    report: StopReport | None = None,
) -> AsyncIterator[str]:
    """Yields the reply as SSE frames, then appends it in one short transaction. `lease` is released on every exit path.

    Driven by a job (app/jobs.py), whose cancel() reaches the stop path below. Each [[image: ...]] directive starts
    generating as soon as it closes in the text, in parallel with the rest of the reply, and its `image` event goes out
    as soon as the file is stored. Images of a turn that is not saved are deleted.

    A `trial_call` is given back when the provider fails before any text reached the client, or when the stream ends or is
    stopped before anything arrived; never once the provider has started answering. `key` only keeps it out of error text."""
    parts: list[str] = []
    received = False  # any delta, reasoning included: the provider has already spent tokens on it
    usage: Usage | None = None
    reasoning = False
    finish_reason = None
    finished = False
    saving = False  # the final save runs in a worker thread that outlives a cancelled job and then releases the lease
    committed = False
    chunks = None
    slots: list[tuple[int, int, asyncio.Task | None]] = []  # (start, end, image task) of each directive, in text order
    tasks: list[asyncio.Task] = []
    ready: list[str] = []  # frames written by image tasks, flushed by this generator
    stored: list[ImageRef] = []
    scanned = 0
    hidden = DirectiveFilter()  # used only when illustrate is off
    fetch: asyncio.Future | None = None

    def dropped(prompt: str, why: str) -> None:
        log.warning("Illustration dropped (%s) for prompt %r", why, prompt[:200])
        failure = IllustrationFailure(prompt=prompt[:200], status=None, detail=why)
        ready.append(sse("illustration_failed", failure.model_dump()))

    async def make_image(prompt: str) -> ImageRef | None:
        client, model, image_key = illustrate
        try:
            data = await run_in_threadpool(providers.generate_image, client, model, prompt)
        except (OpenAIError, ValueError, ValidationError, IndexError, AttributeError) as e:
            log.warning("Illustration failed (%s) for prompt %r", providers.describe_provider_error(e, image_key), prompt[:200])
            status, detail = providers.provider_error_parts(e, image_key, 2000)
            failure = IllustrationFailure(prompt=prompt[:200], status=status, detail=providers.readable_reason(detail)[:200])
            ready.append(sse("illustration_failed", failure.model_dump()))
            return None
        ref = images.save_images(runtime.settings, chat.id, [data])[0].model_copy(update={"prompt": prompt})
        stored.append(ref)
        ready.append(sse("image", {"id": ref.id, "media_type": ref.media_type, "prompt": ref.prompt}))
        return ref

    def start_images() -> None:
        # Only closed directives match, so one split across chunks starts once its `]]` arrives.
        nonlocal scanned
        for match in _DIRECTIVE.finditer("".join(parts), scanned):
            scanned = match.end()
            prompt = clean_prompt(match.group(1))
            if not prompt or len(slots) >= MAX_ILLUSTRATIONS:
                # Removed on purpose, so the client is told instead of left with a skeleton that never fills.
                dropped(prompt, "the picture description was empty" if not prompt else MAX_PER_REPLY)
                slots.append((match.start(), match.end(), None))
                continue
            task = asyncio.ensure_future(make_image(prompt[:MAX_IMAGE_PROMPT_CHARS]))
            tasks.append(task)
            slots.append((match.start(), match.end(), task))

    save_task: asyncio.Future | None = None

    def done_frame(saved: Chat) -> str:
        # Extra keys are additive: the chat fields stay where the existing frontend reads them.
        return sse(
            "done",
            saved.model_dump(mode="json")
            | {
                "usage": usage.model_dump() if usage else None,
                "context": context_info(saved, window).model_dump(),
            }
            | ({"trial": {"remaining": trial_call.remaining}} if trial_call else {}),
        )

    def flush() -> list[str]:
        out = list(ready)
        ready.clear()
        return out

    try:
        chunks = iter(stream)  # inside the try: a stream that cannot start must still release the lease
        if sources or notes or query:
            yield sse(
                "sources",
                {"sources": [{"url": s.url, "title": s.title} for s in sources], "notes": notes, "query": query},
            )
        while True:
            # The OpenAI stream is blocking, so each read runs off the event loop; images that finish meanwhile go out at once.
            fetch = asyncio.ensure_future(run_in_threadpool(next, chunks, None))
            while not fetch.done():
                for frame in flush():
                    yield frame
                await asyncio.wait({fetch, *(t for t in tasks if not t.done())}, return_when=asyncio.FIRST_COMPLETED)
            chunk = fetch.result()
            if chunk is None:
                break
            reported = getattr(getattr(chunk, "usage", None), "prompt_tokens", None)
            if isinstance(reported, int) and not isinstance(reported, bool):
                usage = Usage(prompt_tokens=reported)
            delta = chunk.choices[0].delta if chunk.choices else None
            text = getattr(delta, "content", None)
            if chunk.choices and getattr(chunk.choices[0], "finish_reason", None):
                finish_reason = chunk.choices[0].finish_reason
            if any(getattr(delta, f, None) for f in ("reasoning_content", "reasoning", "thinking")):
                reasoning = True
            if text or reasoning:
                received = True
            # Ephemeral: shown live by the client, never added to `parts` or saved.
            thought = next(
                (v for f in ("reasoning_content", "reasoning", "thinking") if isinstance(v := getattr(delta, f, None), str) and v),
                None,
            )
            for frame in flush():
                yield frame
            if thought:
                yield sse("reasoning", {"text": thought})
            if text:
                parts.append(text)
                if illustrate and "]" in text:
                    start_images()
                shown = text if illustrate else hidden.feed(text)
                if shown:
                    yield sse("delta", {"text": shown})
        if tail := hidden.finish():
            yield sse("delta", {"text": tail})
        raw = "".join(parts)
        if not raw.strip():
            # Nothing to show, typically reasoning that used up max_tokens. Not saved, so no blank turn and no dangling question.
            finished = True
            log.warning("Empty reply for chat %s (finish_reason=%s, reasoning_seen=%s)", chat.id, finish_reason, reasoning)
            if trial_call:
                trial_call.refund()
            yield sse("error", {"detail": EMPTY_REPLY})
            return
        # Saved only after success so a failed request leaves no dangling question.
        while True:
            for frame in flush():
                yield frame
            running = [t for t in tasks if not t.done()]
            if not running:
                break
            await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
        reply_images: list[ImageRef] = []
        if illustrate:
            out, last = [], 0
            for start, end, task in slots:
                ref = task.result() if task else None
                out += [raw[last:start], f"[[img:{ref.id}]]" if ref else ""]
                reply_images += [ref] if ref else []
                last = end
            out.append(raw[last:])
            reply = "".join(out)
            for left in _UNCLOSED.findall(reply):
                dropped(left.removeprefix("[[image:").strip(), "the picture description was never closed")
        else:
            reply = raw
            for match in _DIRECTIVE.finditer(raw):
                dropped(clean_prompt(match.group(1)), "illustrations were off for this message")
        reply = strip_directives(reply)
        if slots:
            reply = tidy(reply)
        for frame in flush():
            yield frame
        finished = True  # whatever happens next, the partial-save fallback below must not run twice

        def save_and_release() -> Chat:
            # Released only once the commit is visible, so the next send never builds its history from a chat missing this turn.
            try:
                return append_turn(chat, lease, content, reply, sources, uploads, query, usage, reply_images, rev)
            finally:
                lease.release()

        saving = True
        # Shielded: a cancel during the save must not orphan the worker thread's outcome, which the job still reports.
        save_task = asyncio.ensure_future(run_in_threadpool(save_and_release))
        try:
            saved = await asyncio.shield(save_task)
        except (storage.ChatNotFound, storage.LeaseLost, sqlite3.Error) as e:
            yield save_failure(e)
            return
        committed = True
        yield done_frame(saved)
    except OpenAIError as e:
        finished = True
        if trial_call and not received:
            trial_call.refund()
        yield sse("error", {"detail": providers.client_error(e, key)})
    except BaseException:
        # A bug, or the job was cancelled (Stop): the partial save is in the finally. Given back only when nothing had arrived.
        if trial_call and not received:
            trial_call.refund()
        raise
    finally:
        # Plain synchronous calls only: this block also runs on cancellation, where an await would be cut short.
        try:
            if fetch is not None:
                fetch.cancel()
            for task in tasks:
                task.cancel()
            stream.close()
            # Reached unfinished when the job is cancelled: keep what was written, without directives or images.
            if not finished:
                last = sse("error", {"detail": "The reply was stopped before anything was written."})
                if "".join(parts).strip():
                    if "[[image:" in "".join(parts):
                        log.warning("Illustrations dropped from a stopped reply in chat %s", chat.id)
                    try:
                        saved = append_turn(chat, lease, content, strip_directives("".join(parts)), sources, uploads, query, usage, rev=rev)
                        last = done_frame(saved)
                    except (storage.ChatNotFound, storage.LeaseLost) as e:
                        last = save_failure(e)  # deleted or taken over meanwhile: the partial reply goes with it
                if report:
                    report.set(last)
            elif saving and not committed and report and save_task is not None:
                # Cancelled while the save thread runs: it finishes on its own, and its outcome closes the stream.
                def settle(t: asyncio.Future) -> None:
                    report.set(save_failure(t.exception()) if t.exception() else done_frame(t.result()))

                if save_task.done():
                    settle(save_task)
                else:
                    save_task.add_done_callback(settle)
        finally:
            # Once the save thread runs, append_turn removes the files itself if it fails.
            if not saving and not committed:
                images.delete_images(runtime.settings, chat.id, stored)
            if not saving:
                lease.release()


