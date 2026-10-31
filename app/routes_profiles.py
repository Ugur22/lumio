"""Provider-profile and web-search-key routes, plus the origin check that guards every state-changing key route."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi import Path as PathParam
from fastapi.concurrency import run_in_threadpool
from openai import OpenAI, OpenAIError

import profile_store
import secret_store
from app import providers, runtime
from app.logs import log
from models import (
    LOCAL_HOSTS,
    EditProfile,
    ModelsQuery,
    ModelsResult,
    NewProfile,
    Profile,
    ProfileList,
    ProfileView,
    WebKey,
    WebStatus,
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
    if request.url.hostname not in LOCAL_HOSTS and request.url.hostname != runtime.settings.public_host:
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
    key, source = profile_store.resolve_key(runtime.settings, profile)
    configured = key is not None or not profile.needs_key
    last4 = key[-4:] if key and len(key) >= 12 else None
    return ProfileView(**profile.model_dump(), configured=configured, last4=last4, source=source, key_store=secret_store.store_kind())


def listing(store=None) -> ProfileList:
    store = store or profile_store.load_store(runtime.settings)
    return ProfileList(active=store.active, profiles=[view(p) for p in store.profiles])


def store_key(account: str, key: str | None) -> None:
    key = (key or "").strip()
    if not key:
        return
    if len(key) > 512:
        raise HTTPException(422, "Enter a valid API key")
    try:
        secret_store.set_key(key, account)
    except Exception:
        log.exception("Could not write the key to the keychain")
        raise HTTPException(503, "The system keychain is unavailable")


def refuse_key_redirect(profile: Profile, base_url: str | None) -> None:
    # With shared access to a server, "keep the saved key but use another URL" would hand the key to that URL.
    if base_url is not None and base_url != profile.base_url:
        raise HTTPException(403, "Changing the base URL needs the API key entered again")


@profiles.get("", response_model=ProfileList)
def list_profiles():
    return listing()


@profiles.post("", response_model=ProfileList, status_code=201)
def create_profile(body: NewProfile):
    store = profile_store.load_store(runtime.settings)
    profile = Profile(id=uuid.uuid4().hex[:8], **body.model_dump(exclude={"key"}))
    store_key(secret_store.profile_account(profile.id), body.key.get_secret_value() if body.key else None)
    store.profiles.append(profile)
    store.active = store.active or profile.id
    profile_store.save_store(runtime.settings, store)
    return listing(store)


@profiles.patch("/{profile_id}", response_model=ProfileList)
def edit_profile(profile_id: ProfileId, body: EditProfile):
    store = profile_store.load_store(runtime.settings)
    profile = providers.find_profile(store, profile_id)
    if runtime.settings.deployed and not body.key:
        refuse_key_redirect(profile, body.base_url)
    for field, value in body.model_dump(exclude={"key"}, exclude_none=True).items():
        setattr(profile, field, value)
    if "context_window" in body.model_fields_set:  # an explicit null clears it
        profile.context_window = body.context_window
    if "image_model" in body.model_fields_set:
        profile.image_model = body.image_model
    store_key(secret_store.profile_account(profile.id), body.key.get_secret_value() if body.key else None)
    profile_store.save_store(runtime.settings, store)
    return listing(store)


@profiles.delete("/{profile_id}", response_model=ProfileList)
def delete_profile(profile_id: ProfileId):
    store = profile_store.load_store(runtime.settings)
    providers.find_profile(store, profile_id)
    store.profiles = [p for p in store.profiles if p.id != profile_id]
    if store.active == profile_id:
        store.active = store.profiles[0].id if store.profiles else None
    secret_store.delete_key(secret_store.profile_account(profile_id))
    if profile_id == profile_store.DEFAULT_ID:
        secret_store.delete_key()
    profile_store.save_store(runtime.settings, store)
    return listing(store)


@profiles.post("/{profile_id}/activate", response_model=ProfileList)
def activate_profile(profile_id: ProfileId):
    store = profile_store.load_store(runtime.settings)
    providers.find_profile(store, profile_id)
    store.active = profile_id
    profile_store.save_store(runtime.settings, store)
    return listing(store)


def context_size(model) -> int | None:
    for field in ("context_length", "context_window"):
        n = getattr(model, field, None)
        if isinstance(n, int) and not isinstance(n, bool) and n > 0:
            return n
    return None


@profiles.post("/models", response_model=ModelsResult)
async def list_models(body: ModelsQuery):
    """Lists the provider's models; doubles as the key test. Works on unsaved profiles."""
    base_url, key, needs_key = body.base_url, None, body.needs_key
    if body.key:
        key = body.key.get_secret_value().strip() or None
    if body.profile_id:
        profile = providers.find_profile(profile_store.load_store(runtime.settings), body.profile_id)
        if runtime.settings.deployed and not body.key:
            refuse_key_redirect(profile, base_url)
        base_url = base_url or profile.base_url
        needs_key = profile.needs_key
        key = key or profile_store.resolve_key(runtime.settings, profile)[0]
    if not base_url:
        raise HTTPException(422, "Enter a base URL")
    if key is None and needs_key:
        raise HTTPException(409, "Enter an API key first")
    client = OpenAI(base_url=base_url, api_key=key or providers.NO_KEY)
    try:
        page = list(await run_in_threadpool(client.models.list))
        result: dict = {"models": sorted(m.id for m in page)}
        # OpenRouter reports sizes; most providers don't, so the key is only present when known.
        windows = {m.id: n for m in page if (n := context_size(m))}
        if windows:
            result["context_windows"] = windows
        return result
    except OpenAIError as e:
        raise HTTPException(502, providers.redact(getattr(e, "message", str(e)), key))
    finally:
        client.close()


web_settings = APIRouter(prefix="/api/web", dependencies=[Depends(require_local_origin)])


def web_status() -> WebStatus:
    key = secret_store.get_key(secret_store.TAVILY_ACCOUNT)
    return WebStatus(
        configured=key is not None,
        last4=key[-4:] if key and len(key) >= 12 else None,
        key_store=secret_store.store_kind(),
    )


@web_settings.get("", response_model=WebStatus)
def get_web_status():
    return web_status()


@web_settings.put("/key", response_model=WebStatus)
def set_web_key(body: WebKey):
    store_key(secret_store.TAVILY_ACCOUNT, body.key.get_secret_value())
    return web_status()


@web_settings.delete("/key", response_model=WebStatus)
def delete_web_key():
    secret_store.delete_key(secret_store.TAVILY_ACCOUNT)
    return web_status()
