"""Streaming a reply to the client as server-sent events, illustrating it, and saving the finished turn."""

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
from app.story import context_info
from models import Chat, ImageData, ImageRef, Message, Source, Usage

MAX_ILLUSTRATIONS = 3
MAX_IMAGE_PROMPT_CHARS = 1_000
# [[img:<id>]] is what a directive becomes once its image is stored.
_DIRECTIVE = re.compile(r"\[\[image:\s*([^\]\n]+?)\s*\]\]")


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


def strip_directives(text: str) -> str:
    return tidy(_DIRECTIVE.sub("", text)) if _DIRECTIVE.search(text) else text


class IllustrationFailure(BaseModel):
    prompt: str
    status: int | None
    detail: str


async def illustrate_reply(
    chat_id: str, text: str, client: OpenAI, model: str, key: str | None
) -> tuple[str, list[ImageRef], list[IllustrationFailure]]:
    """Turns [[image: ...]] directives into stored images and [[img:<id>]] markers.

    A directive that fails (provider error, bad data) or exceeds the cap is removed and the text kept;
    real failures are returned so the caller can report them (directives over the cap are not failures).
    """
    refs: list[ImageRef] = []
    failures: list[IllustrationFailure] = []
    wanted = 0

    async def replace(match: re.Match) -> str:
        nonlocal wanted
        wanted += 1
        if wanted > MAX_ILLUSTRATIONS:
            return ""
        prompt = match.group(1)[:MAX_IMAGE_PROMPT_CHARS]
        try:
            data = await run_in_threadpool(providers.generate_image, client, model, prompt)
        except (OpenAIError, ValueError, ValidationError, IndexError, AttributeError) as e:
            log.warning("Illustration failed (%s) for prompt %r", providers.describe_provider_error(e, key), prompt[:200])
            status, detail = providers.provider_error_parts(e, key, 2000)
            failures.append(IllustrationFailure(prompt=prompt[:200], status=status, detail=providers.readable_reason(detail)[:200]))
            return ""
        ref = images.save_images(runtime.settings, chat_id, [data])[0].model_copy(update={"prompt": prompt})
        refs.append(ref)
        return f"[[img:{ref.id}]]"

    out, last = [], 0
    for match in _DIRECTIVE.finditer(text):
        out += [text[last : match.start()], await replace(match)]
        last = match.end()
    out.append(text[last:])
    return (tidy("".join(out)) if last else text), refs, failures


def append_turn(
    chat: Chat,
    content: str,
    reply: str,
    sources: list[Source],
    uploads: list[ImageData] = (),
    query: str | None = None,
    usage: Usage | None = None,
    reply_images: list[ImageRef] = (),
    rev: int | None = None,
) -> Chat:
    """Adds the question and its reply to the stored chat; raises storage.ChatNotFound if it was deleted meanwhile."""
    refs = images.save_images(runtime.settings, chat.id, list(uploads))
    try:
        return runtime.db.append_messages(
            chat.id,
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
    lease: storage.Lease | None = None,
    rev: int | None = None,
) -> AsyncIterator[str]:
    """Streams the reply, then appends it in one short transaction. `lease` is released on every exit path."""
    parts: list[str] = []
    usage: Usage | None = None
    finished = False
    saving = False  # the final save runs in a worker thread that outlives a cancelled request and then releases the lease
    chunks = iter(stream)
    try:
        if sources or notes or query:
            yield sse(
                "sources",
                {"sources": [{"url": s.url, "title": s.title} for s in sources], "notes": notes, "query": query},
            )
        while True:
            # The OpenAI stream is blocking, so each read runs off the event loop.
            chunk = await run_in_threadpool(next, chunks, None)
            if chunk is None:
                break
            reported = getattr(getattr(chunk, "usage", None), "prompt_tokens", None)
            if isinstance(reported, int) and not isinstance(reported, bool):
                usage = Usage(prompt_tokens=reported)
            text = chunk.choices[0].delta.content if chunk.choices else None
            if text:
                parts.append(text)
                yield sse("delta", {"text": text})
        # Saved only after success so a failed request leaves no dangling question.
        reply = "".join(parts)
        reply_images: list[ImageRef] = []
        failures: list[IllustrationFailure] = []
        if illustrate:
            reply, reply_images, failures = await illustrate_reply(chat.id, reply, *illustrate)
        else:
            reply = strip_directives(reply)
        finished = True  # whatever happens next, the partial-save fallback below must not run twice

        def save_and_release() -> Chat:
            # Released only once the commit is visible, so the next send never builds its history from a chat missing this turn.
            try:
                return append_turn(chat, content, reply, sources, uploads, query, usage, reply_images, rev)
            finally:
                if lease:
                    lease.release()

        saving = lease is not None
        try:
            saved = await run_in_threadpool(save_and_release)
        except storage.ChatNotFound:
            images.delete_images(runtime.settings, chat.id, reply_images)
            yield sse("error", {"detail": "This chat was deleted while the reply was being written"})
            return
        except sqlite3.Error:
            log.exception("Could not save the reply")
            images.delete_images(runtime.settings, chat.id, reply_images)
            yield sse("error", {"detail": "The reply could not be saved. Try again."})
            return
        for ref in reply_images:
            yield sse("image", {"id": ref.id, "media_type": ref.media_type, "prompt": ref.prompt})
        for failure in failures:
            yield sse("illustration_failed", failure.model_dump())
        # Extra keys are additive: the chat fields stay where the existing frontend reads them.
        yield sse(
            "done",
            saved.model_dump(mode="json")
            | {
                "usage": usage.model_dump() if usage else None,
                "context": context_info(saved, window).model_dump(),
            },
        )
    except OpenAIError as e:
        finished = True
        yield sse("error", {"detail": providers.error_text(e)})
    finally:
        # Plain synchronous calls only: this block also runs on cancellation, where an await would be cut short.
        try:
            stream.close()
            # Reached unfinished when the client stops or disconnects: keep what it saw.
            if not finished and parts:
                try:
                    append_turn(chat, content, strip_directives("".join(parts)), sources, uploads, query, usage, rev=rev)
                except storage.ChatNotFound:
                    pass  # deleted while generating: the partial reply goes with it
        finally:
            if lease and not saving:
                lease.release()
