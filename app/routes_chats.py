"""Chat routes: CRUD, images, story/behavior/model/summary settings, context size, and sending a message."""

import asyncio
import re
import weakref
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi import Path as PathParam
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response, StreamingResponse
from openai import OpenAIError

import images
import profile_store
import secret_store
import storage
import web
from app import auth, jobs, providers, runtime, story, streaming
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
    cap = providers.TRIAL_MAX_CHATS if providers.trial_active(user) else None
    try:
        return runtime.db.create_chat(providers.user_store(user).active, owner=user.id, max_chats=cap)
    except storage.ChatLimit:
        raise HTTPException(403, f"The free trial is limited to {providers.TRIAL_MAX_CHATS} chats.")


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
        providers.find_profile(providers.user_store(user), body.profile_id)
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
    if providers.is_trial(profile):
        raise HTTPException(403, "Summaries are not available during the free trial.")
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
        raise HTTPException(502, providers.client_error(e, providers.profile_key(profile, user)))
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


def sse_headers(job: jobs.Job) -> dict[str, str]:
    return {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Job-Id": job.id}


@router.post("/api/chats/{chat_id}/messages")
async def send_message(chat_id: ChatId, body: NewMessage, user: CurrentUser):
    """Starts the reply as a job and streams its events. The job outlives this request: see app/jobs.py."""

    async def begin() -> jobs.Job:
        report = streaming.StopReport()
        reply = await run_in_threadpool(prepare_reply, chat_id, body, user, report)
        # No await between here and the job owning the lease and the trial call.
        return jobs.start(chat_id, user.id, reply, report)

    # Shielded: if the client goes away while the reply is being prepared, begin() still finishes and the job runs on,
    # instead of leaving a held lease and a spent trial call behind with nobody to release them.
    job = await asyncio.shield(asyncio.ensure_future(begin()))
    return StreamingResponse(job.follow(-1), media_type="text/event-stream", headers=sse_headers(job))


@router.get("/api/chats/{chat_id}/messages/stream", response_model=None)
def resume_stream(
    chat_id: ChatId,
    user: CurrentUser,
    after: Annotated[int | None, Query(ge=-1)] = None,
    job: Annotated[str | None, Query(max_length=64)] = None,
    last_event_id: Annotated[str | None, Header()] = None,
):
    """Replays the events after `Last-Event-ID` (or `?after=`) and follows the reply live.

    204 when no reply is buffered, or when `?job=` names a reply that is no longer the chat's current one (the cursor is stale)."""
    load_chat(chat_id, user)
    current = jobs.find(chat_id, user.id)
    if current is None or (job is not None and job != current.id):
        return Response(status_code=204)
    if last_event_id is not None:
        if not re.fullmatch(r"-?[0-9]{1,12}", last_event_id.strip()):
            raise HTTPException(422, "Last-Event-ID must be an event number")
        after = max(int(last_event_id), -1)
    return StreamingResponse(current.follow(after if after is not None else -1), media_type="text/event-stream", headers=sse_headers(current))


@router.post("/api/chats/{chat_id}/messages/cancel", status_code=204)
def cancel_reply(chat_id: ChatId, user: CurrentUser):
    """The only way to stop a reply: the text so far is saved. Does nothing when no reply is running."""
    load_chat(chat_id, user)
    if job := jobs.find(chat_id, user.id):
        job.cancel()


def prepare_reply(chat_id: str, body: NewMessage, user: UserView, report: streaming.StopReport | None = None):
    """Everything up to the first byte of the model's answer. Returns the reply's frame generator, which owns the lease and the trial call from here on."""
    # Taken before the chat is read, so the history sent is the one the previous reply left behind.
    try:
        lease = runtime.db.acquire(chat_id, owner=user.id)
    except storage.ChatNotFound:
        raise chat_gone()
    except storage.ChatBusy:
        raise HTTPException(409, "A reply is already being generated in this chat")
    call = None
    try:
        chat, rev = runtime.db.get_chat_rev(chat_id, owner=user.id)
        profile = providers.profile_for(chat, user)
        trial = providers.is_trial(profile)
        if trial:
            system, history = providers.trial_prompt(chat, body)
        if body.images and not profile.vision:
            raise HTTPException(422, f"{profile.name} can't read images. Switch to a vision-capable provider.")
        illustrate = body.illustrate and not trial
        if illustrate and not profile.image_model:
            raise HTTPException(422, f"{profile.name} has no image model. Set one in Providers.")
        client = providers.get_client(profile, user)
        key = providers.profile_key(profile, user)

        if trial:
            # Every 422 above is behind us, so a refused request has taken nothing; from here the call is paid for.
            call = providers.reserve_trial(user)
            sources, notes, query = [], [], None
            messages = [{"role": "system", "content": system}, *history, {"role": "user", "content": body.content}]
            sampling = providers.trial_sampling(chat)
        else:
            # Gathered before the model call; the pages are plain prompt text, so any provider works.
            tavily_key = secret_store.get_key(profile_store.tavily_account(user)) if body.web else None
            query = None
            if tavily_key and body.content.strip():
                query = web.rewrite_query(client, profile.model, story.recent_for(chat), body.content)
            sources, notes = web.gather(body.content, body.web, tavily_key, query)
            history = story.history_for(chat, profile.vision)
            uploaded = [f"data:{i.media_type};base64,{i.data}" for i in body.images]
            message = story.content_for(web.with_context(body.content, sources, notes), uploaded, profile.vision)
            history.append({"role": "user", "content": message})
            messages = [{"role": "system", "content": story.system_for(chat, body.content, illustrate)}, *history]
            sampling = providers.sampling_params(chat)
        try:
            stream = providers.open_stream(client, profile, messages, sampling)
        except OpenAIError as e:
            raise HTTPException(502, providers.client_error(e, key))
    except storage.ChatNotFound:
        lease.release()
        if call:
            call.refund()
        raise chat_gone()
    except BaseException:
        lease.release()
        if call:
            call.refund()  # nothing reached the model's reply, so the call is not spent
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
        (client, profile.image_model, key) if illustrate else None,
        lease=lease,
        rev=rev,
        trial_call=call,
        key=key,
        report=report,
    )
    # Backstop for a generator that is dropped without ever starting (its own finally never runs); release is idempotent.
    weakref.finalize(reply, lease.release)
    return reply
