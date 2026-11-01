"""Chat routes: CRUD, images, story/behavior/model/summary settings, context size, and sending a message."""

import weakref
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, StreamingResponse
from openai import OpenAIError
from starlette.background import BackgroundTask

import images
import profile_store
import secret_store
import storage
import web
from app import auth, providers, runtime, story, streaming
from models import (
    MAX_SUMMARY_CHARS,
    BehaviorUpdate,
    Chat,
    ChatModelUpdate,
    ChatSummary,
    ContextInfo,
    NewMessage,
    RenameChat,
    StoryUpdate,
    SummaryProposal,
    SummaryUpdate,
    UserView,
)

# Origin == Host on a server (the cookie's SameSite=Lax is the first line of defence); reads are exempt.
router = APIRouter(dependencies=[Depends(auth.require_same_origin)])
# Every chat route is scoped to the caller: another user's chat answers 404 exactly like a missing one.
CurrentUser = Annotated[UserView, Depends(auth.current_user)]

# Hex-only ids keep user input from ever becoming a path outside data_dir.
ChatId = Annotated[str, PathParam(pattern=r"^[0-9a-f]{32}$")]

def load_chat(chat_id: str, user: UserView) -> Chat:
    try:
        return runtime.db.get_chat(chat_id, owner=user.id)
    except storage.ChatNotFound:
        raise HTTPException(404, "Chat not found")


def chat_gone() -> HTTPException:
    return HTTPException(404, "Chat not found")


@router.get("/api/chats", response_model=list[ChatSummary])
def list_chats(user: CurrentUser):
    return runtime.db.list_chats(owner=user.id)


@router.post("/api/chats", response_model=Chat, status_code=201)
def create_chat(user: CurrentUser):
    store = profile_store.load_store(runtime.settings, user)
    return runtime.db.create_chat(store.active, owner=user.id)


@router.get("/api/chats/{chat_id}", response_model=Chat)
def get_chat(chat_id: ChatId, user: CurrentUser):
    return load_chat(chat_id, user)


@router.patch("/api/chats/{chat_id}", response_model=Chat)
def rename_chat(chat_id: ChatId, body: RenameChat, user: CurrentUser):
    try:
        return runtime.db.rename(chat_id, body.title, owner=user.id)
    except storage.ChatNotFound:
        raise chat_gone()


@router.delete("/api/chats/{chat_id}", status_code=204)
def delete_chat(chat_id: ChatId, user: CurrentUser):
    try:
        runtime.db.delete_chat(chat_id, owner=user.id)
    except storage.ChatNotFound:
        raise chat_gone()
    # After the commit: a reply still streaming into this chat finds it gone and removes its own files.
    images.delete_chat_images(runtime.settings, chat_id)


ImageId = Annotated[str, PathParam(pattern=r"^[0-9a-f]{32}$")]


@router.get("/api/chats/{chat_id}/images/{image_id}")
def get_image(chat_id: ChatId, image_id: ImageId, user: CurrentUser):
    try:
        ref = runtime.db.find_image(chat_id, image_id, owner=user.id)
    except storage.ChatNotFound:
        raise chat_gone()
    if ref is None:
        raise HTTPException(404, "Image not found")
    path = images.image_path(runtime.settings, chat_id, ref)
    if not path.exists():
        raise HTTPException(410, "This image has expired")
    return FileResponse(path, media_type=ref.media_type, headers={"Cache-Control": "private, max-age=3600"})


@router.put("/api/chats/{chat_id}/story", response_model=Chat)
def update_story(chat_id: ChatId, body: StoryUpdate, user: CurrentUser):
    try:
        return runtime.db.update_story(chat_id, body.bible, body.lore, owner=user.id)
    except storage.ChatNotFound:
        raise chat_gone()


@router.put("/api/chats/{chat_id}/behavior", response_model=Chat)
def update_behavior(chat_id: ChatId, body: BehaviorUpdate, user: CurrentUser):
    load_chat(chat_id, user)
    if body.profile_id is not None:
        providers.find_profile(profile_store.load_store(runtime.settings, user), body.profile_id)
    values = body.model_dump(exclude={"profile_id"})
    try:
        return runtime.db.update_behavior(chat_id, values, "profile_id" in body.model_fields_set, body.profile_id, owner=user.id)
    except storage.ChatNotFound:
        raise chat_gone()


@router.put("/api/chats/{chat_id}/model", response_model=Chat)
def update_chat_model(chat_id: ChatId, body: ChatModelUpdate, user: CurrentUser):
    chat = load_chat(chat_id, user)
    # Pin the provider the model was picked on, so a later change of default can't send it elsewhere.
    pin = providers.profile_for(chat, user).id if body.model and chat.profile_id is None else None
    try:
        return runtime.db.update_model(chat_id, body.model, body.context_window, pin, owner=user.id)
    except storage.ChatNotFound:
        raise chat_gone()


@router.post("/api/chats/{chat_id}/summarize", response_model=SummaryProposal)
def summarize_chat(chat_id: ChatId, user: CurrentUser):
    """Proposes a summary without saving: the author edits it, then PUTs it to /summary."""
    chat = load_chat(chat_id, user)
    upto = len(chat.messages) - story.SUMMARY_KEEP
    if upto <= chat.summary_upto:
        raise HTTPException(409, "Not enough new messages to summarize yet")
    profile = providers.profile_for(chat, user)
    client = providers.get_client(profile, user)
    transcript = "\n\n".join(
        f"{m.role}: {web.clip(m.content.strip(), story.SUMMARY_MESSAGE_CHARS)}" for m in chat.messages[chat.summary_upto : upto]
    )
    previous = f"Previous summary:\n{chat.summary.strip()}\n\n" if chat.summary.strip() else ""
    try:
        res = client.chat.completions.create(
            model=profile.model,
            messages=[
                {"role": "system", "content": story.SUMMARY_PROMPT},
                {"role": "user", "content": f"{previous}New material:\n{transcript}"},
            ],
            stream=False,
        )
        text = (res.choices[0].message.content or "").strip()
    except OpenAIError as e:
        raise HTTPException(502, providers.error_text(e))
    if not text:
        raise HTTPException(502, "The model returned an empty summary")
    return SummaryProposal(summary=text[:MAX_SUMMARY_CHARS], summary_upto=upto)


@router.put("/api/chats/{chat_id}/summary", response_model=Chat)
def update_summary(chat_id: ChatId, body: SummaryUpdate, user: CurrentUser):
    try:
        return runtime.db.update_summary(chat_id, body.summary, body.summary_upto, owner=user.id)
    except storage.ChatNotFound:
        raise chat_gone()
    except storage.InvalidUpdate as e:
        raise HTTPException(422, str(e))


@router.get("/api/chats/{chat_id}/context", response_model=ContextInfo)
def get_context(chat_id: ChatId, user: CurrentUser):
    chat = load_chat(chat_id, user)
    return story.context_info(chat, providers.profile_window(chat, user))


@router.post("/api/chats/{chat_id}/messages")
def send_message(chat_id: ChatId, body: NewMessage, user: CurrentUser):
    # Taken before the chat is read, so the history sent is the one the previous reply left behind.
    try:
        lease = runtime.db.acquire(chat_id, owner=user.id)
    except storage.ChatNotFound:
        raise chat_gone()
    except storage.ChatBusy:
        raise HTTPException(409, "A reply is already being generated in this chat")
    try:
        chat, rev = runtime.db.get_chat_rev(chat_id, owner=user.id)
        profile = providers.profile_for(chat, user)
        if body.images and not profile.vision:
            raise HTTPException(422, f"{profile.name} can't read images. Switch to a vision-capable provider.")
        if body.illustrate and not profile.image_model:
            raise HTTPException(422, f"{profile.name} has no image model. Set one in Providers.")
        client = providers.get_client(profile, user)
        saved = None
        if body.transcript_id:  # checked before any outbound call, so a stale id costs nothing
            try:
                saved = runtime.db.get_transcript(chat_id, body.transcript_id, owner=user.id)
            except storage.TranscriptNotFound:
                raise HTTPException(404, "Transcript not found")

        # Gathered before the model call; the pages are plain prompt text, so any provider works.
        tavily_key = secret_store.get_key(profile_store.tavily_account(user)) if body.web else None
        query = None
        if tavily_key and body.content.strip():
            query = web.rewrite_query(client, profile.model, story.recent_for(chat), body.content)
        sources, notes = web.gather(body.content, body.web, tavily_key, query)
        history = story.history_for(chat, profile.vision)
        uploaded = [f"data:{i.media_type};base64,{i.data}" for i in body.images]
        prompt = web.with_context(body.content, sources, notes)
        if saved:
            prompt = story.with_transcript(prompt, saved.title, saved.url, saved.edited_text if saved.edited_text is not None else saved.original_text)
        message = story.content_for(prompt, uploaded, profile.vision)
        history.append({"role": "user", "content": message})
        try:
            stream = providers.open_stream(
                client,
                profile,
                [{"role": "system", "content": story.system_for(chat, body.content, body.illustrate)}, *history],
                providers.sampling_params(chat),
            )
        except OpenAIError as e:
            raise HTTPException(502, providers.error_text(e))
    except storage.ChatNotFound:
        lease.release()
        raise chat_gone()
    except BaseException:
        lease.release()
        raise

    reply = streaming.stream_reply(
        chat,
        body.content,
        stream,
        sources,
        notes,
        body.images,
        query,
        providers.window_for(chat, profile),
        (client, profile.image_model, providers.profile_key(profile, user)) if body.illustrate else None,
        lease=lease,
        rev=rev,
    )
    # A generator that never starts (client gone before the first byte) never reaches its own finally, and the
    # lease thread would keep renewing; release is idempotent, so these are only backstops.
    weakref.finalize(reply, lease.release)
    return StreamingResponse(
        reply,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        background=BackgroundTask(lease.release),
    )
