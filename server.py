import json
import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi import Path as PathParam
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI, OpenAIError
from pydantic import ValidationError

import profile_store
import secret_store
from models import (
    BASE_DIR,
    LOCAL_HOSTS,
    Chat,
    ChatSummary,
    EditProfile,
    Message,
    ModelsQuery,
    NewMessage,
    NewProfile,
    Profile,
    ProfileList,
    ProfileView,
    RenameChat,
    Settings,
    utcnow,
)

log = logging.getLogger("dolphinllm")

settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
_clients: dict[tuple[str, str], OpenAI] = {}
NO_KEY = "not-needed"  # the OpenAI SDK insists on a non-empty key even for local servers


def active_profile() -> Profile:
    store = profile_store.load_store(settings)
    profile = next((p for p in store.profiles if p.id == store.active), None)
    if profile is None:
        raise HTTPException(409, "No provider configured. Add one in Providers.")
    return profile


def profile_key(profile: Profile) -> str | None:
    if not profile.needs_key:
        return NO_KEY
    return profile_store.resolve_key(settings, profile)[0]


def get_client(profile: Profile) -> OpenAI:
    key = profile_key(profile)
    if key is None:
        raise HTTPException(409, f"No API key for {profile.name}. Add one in Providers.")
    cache_key = (profile.base_url, key)
    if cache_key not in _clients:
        _clients.clear()
        _clients[cache_key] = OpenAI(base_url=profile.base_url, api_key=key)
    return _clients[cache_key]


def redact(message: str, key: str | None) -> str:
    return message.replace(key, "…") if key else message


# Sent with every request but never stored, so changing it restyles old chats too.
SYSTEM_PROMPT = (
    "You may format replies with Markdown. For stories and roleplay, put spoken "
    'dialogue in "double quotes" and actions in *asterisks*. To make something stand '
    "out, use these tags, sparingly: [[key]]...[[/key]] for a key point or turning "
    "point, [[note]]...[[/note]] for an aside, [[warn]]...[[/warn]] for a warning."
)

# Hex-only ids keep user input from ever becoming a path outside data_dir.
ChatId = Annotated[str, PathParam(pattern=r"^[0-9a-f]{32}$")]

app = FastAPI()


def chat_path(chat_id: str) -> Path:
    return settings.data_dir / f"{chat_id}.json"


def load_chat(chat_id: str) -> Chat:
    path = chat_path(chat_id)
    if not path.exists():
        raise HTTPException(404, "Chat not found")
    return Chat.model_validate_json(path.read_text())


def save_chat(chat: Chat) -> None:
    chat.updated = utcnow()
    chat_path(chat.id).write_text(chat.model_dump_json(indent=2))


@app.get("/api/chats", response_model=list[ChatSummary])
def list_chats():
    summaries = []
    for path in settings.data_dir.glob("*.json"):
        try:
            chat = Chat.model_validate_json(path.read_text())
        except ValidationError:
            log.warning("Skipping unreadable chat file %s", path.name)
            continue
        summaries.append(
            ChatSummary(
                id=chat.id,
                title=chat.title,
                updated=chat.updated,
                message_count=len(chat.messages),
            )
        )
    return sorted(summaries, key=lambda c: c.updated, reverse=True)


@app.post("/api/chats", response_model=Chat, status_code=201)
def create_chat():
    chat = Chat(id=uuid.uuid4().hex)
    save_chat(chat)
    return chat


@app.get("/api/chats/{chat_id}", response_model=Chat)
def get_chat(chat_id: ChatId):
    return load_chat(chat_id)


@app.patch("/api/chats/{chat_id}", response_model=Chat)
def rename_chat(chat_id: ChatId, body: RenameChat):
    chat = load_chat(chat_id)
    chat.title = body.title
    save_chat(chat)
    return chat


@app.delete("/api/chats/{chat_id}", status_code=204)
def delete_chat(chat_id: ChatId):
    load_chat(chat_id)
    chat_path(chat_id).unlink()


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def append_turn(chat: Chat, content: str, reply: str) -> None:
    if not chat.messages:
        chat.title = content.strip()[:50]
    chat.messages.append(Message(role="user", content=content))
    chat.messages.append(Message(role="assistant", content=reply))
    save_chat(chat)


async def stream_reply(chat: Chat, content: str, stream) -> AsyncIterator[str]:
    parts: list[str] = []
    finished = False
    chunks = iter(stream)
    try:
        while True:
            # The OpenAI stream is blocking, so each read runs off the event loop.
            chunk = await run_in_threadpool(next, chunks, None)
            if chunk is None:
                break
            text = chunk.choices[0].delta.content if chunk.choices else None
            if text:
                parts.append(text)
                yield sse("delta", {"text": text})
        # Saved only after success so a failed request leaves no dangling question.
        append_turn(chat, content, "".join(parts))
        finished = True
        yield sse("done", chat.model_dump(mode="json"))
    except OpenAIError as e:
        finished = True
        yield sse("error", {"detail": getattr(e, "message", str(e))})
    finally:
        stream.close()
        # Reached unfinished when the client stops or disconnects: keep what it saw.
        if not finished and parts:
            append_turn(chat, content, "".join(parts))


@app.post("/api/chats/{chat_id}/messages")
def send_message(chat_id: ChatId, body: NewMessage):
    chat = load_chat(chat_id)
    history = [{"role": m.role, "content": m.content} for m in chat.messages]
    history.append({"role": "user", "content": body.content})

    profile = active_profile()
    client = get_client(profile)
    try:
        stream = client.chat.completions.create(
            model=profile.model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, *history],
            stream=True,
        )
    except OpenAIError as e:
        raise HTTPException(502, getattr(e, "message", str(e)))

    return StreamingResponse(
        stream_reply(chat, body.content, stream),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# The Vite dev server (`npm run dev`) is a legitimate browser origin that proxies to us.
DEV_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}


def require_local_origin(request: Request) -> None:
    # A page on another site can fire requests at localhost, so state-changing key
    # routes only accept a browser origin that is this very local server. Reads are
    # exempt: browsers omit Origin on same-origin GETs and the status holds no secret.
    if request.method in ("GET", "HEAD"):
        return
    host_header = request.headers.get("host", "")
    origin = request.headers.get("origin")
    if request.url.hostname not in LOCAL_HOSTS:
        raise HTTPException(403, f"Host {host_header!r} is not a local address")
    if origin is None:
        raise HTTPException(403, "Missing Origin header")
    # A proxy may rewrite Host, so the dev origins are allowed besides Origin == Host.
    same_host = origin.split("://", 1)[-1] == host_header
    if not (same_host or origin in DEV_ORIGINS):
        raise HTTPException(403, f"Origin {origin!r} is not allowed for host {host_header!r}")


profiles = APIRouter(prefix="/api/profiles", dependencies=[Depends(require_local_origin)])

ProfileId = Annotated[str, PathParam(pattern=r"^[0-9a-z]{1,32}$")]


def view(profile: Profile) -> ProfileView:
    key, source = profile_store.resolve_key(settings, profile)
    configured = key is not None or not profile.needs_key
    last4 = key[-4:] if key and len(key) >= 12 else None
    return ProfileView(**profile.model_dump(), configured=configured, last4=last4, source=source)


def listing(store=None) -> ProfileList:
    store = store or profile_store.load_store(settings)
    return ProfileList(active=store.active, profiles=[view(p) for p in store.profiles])


def store_key(profile_id: str, key: str | None) -> None:
    key = (key or "").strip()
    if not key:
        return
    if len(key) > 512:
        raise HTTPException(422, "Enter a valid API key")
    try:
        secret_store.set_key(key, secret_store.profile_account(profile_id))
    except Exception:
        log.exception("Could not write the key to the keychain")
        raise HTTPException(503, "The system keychain is unavailable")


def find(store, profile_id: str) -> Profile:
    profile = next((p for p in store.profiles if p.id == profile_id), None)
    if profile is None:
        raise HTTPException(404, "Provider not found")
    return profile


@profiles.get("", response_model=ProfileList)
def list_profiles():
    return listing()


@profiles.post("", response_model=ProfileList, status_code=201)
def create_profile(body: NewProfile):
    store = profile_store.load_store(settings)
    profile = Profile(id=uuid.uuid4().hex[:8], **body.model_dump(exclude={"key"}))
    store_key(profile.id, body.key.get_secret_value() if body.key else None)
    store.profiles.append(profile)
    store.active = store.active or profile.id
    profile_store.save_store(settings, store)
    return listing(store)


@profiles.patch("/{profile_id}", response_model=ProfileList)
def edit_profile(profile_id: ProfileId, body: EditProfile):
    store = profile_store.load_store(settings)
    profile = find(store, profile_id)
    for field, value in body.model_dump(exclude={"key"}, exclude_none=True).items():
        setattr(profile, field, value)
    store_key(profile.id, body.key.get_secret_value() if body.key else None)
    profile_store.save_store(settings, store)
    return listing(store)


@profiles.delete("/{profile_id}", response_model=ProfileList)
def delete_profile(profile_id: ProfileId):
    store = profile_store.load_store(settings)
    find(store, profile_id)
    store.profiles = [p for p in store.profiles if p.id != profile_id]
    if store.active == profile_id:
        store.active = store.profiles[0].id if store.profiles else None
    secret_store.delete_key(secret_store.profile_account(profile_id))
    if profile_id == profile_store.DEFAULT_ID:
        secret_store.delete_key()
    profile_store.save_store(settings, store)
    return listing(store)


@profiles.post("/{profile_id}/activate", response_model=ProfileList)
def activate_profile(profile_id: ProfileId):
    store = profile_store.load_store(settings)
    find(store, profile_id)
    store.active = profile_id
    profile_store.save_store(settings, store)
    return listing(store)


@profiles.post("/models")
async def list_models(body: ModelsQuery):
    """Lists the provider's models; doubles as the key test. Works on unsaved profiles."""
    base_url, key, needs_key = body.base_url, None, body.needs_key
    if body.key:
        key = body.key.get_secret_value().strip() or None
    if body.profile_id:
        profile = find(profile_store.load_store(settings), body.profile_id)
        base_url = base_url or profile.base_url
        needs_key = profile.needs_key
        key = key or profile_store.resolve_key(settings, profile)[0]
    if not base_url:
        raise HTTPException(422, "Enter a base URL")
    if key is None and needs_key:
        raise HTTPException(409, "Enter an API key first")
    client = OpenAI(base_url=base_url, api_key=key or NO_KEY)
    try:
        page = await run_in_threadpool(client.models.list)
        return {"models": sorted(m.id for m in page)}
    except OpenAIError as e:
        raise HTTPException(502, redact(getattr(e, "message", str(e)), key))
    finally:
        client.close()


app.include_router(profiles)

# Mounted only when built, so the API (and its tests) work before `make build` has run.
FRONTEND_DIR = BASE_DIR / "frontend" / "dist"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
