"""Provider-profile and web-search-key routes, plus the origin check that guards every state-changing key route."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi import Path as PathParam
from fastapi.concurrency import run_in_threadpool
from openai import OpenAI, OpenAIError

import profile_store
import secret_store
from app import auth, providers, runtime
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
    UserView,
    WebStatus,
)

def require_local_origin(request: Request) -> None:
    # A page on another site can fire requests at localhost, so state-changing key
    # routes only accept a browser origin that is this very local server.
    if request.method in ("GET", "HEAD"):
        return
    if request.url.hostname not in LOCAL_HOSTS and request.url.hostname != runtime.settings.public_host:
        raise HTTPException(403, f"Host {request.headers.get('host', '')!r} is not a local address")
    auth.check_origin(request, auth.DEV_ORIGINS)


profiles = APIRouter(prefix="/api/profiles", dependencies=[Depends(require_local_origin)])

ProfileId = Annotated[str, PathParam(pattern=r"^[0-9a-z]{1,32}$")]
# Every route works on the caller's own store and secret accounts; a profile id is only ever trusted after it was
# found in that store, so another user's profile answers 404 exactly like a missing one.
CurrentUser = Annotated[UserView, Depends(auth.current_user)]


def new_profile_id() -> str:
    return uuid.uuid4().hex[:8]


def view(profile: Profile, user: UserView) -> ProfileView:
    key, source = profile_store.resolve_key(runtime.settings, user, profile)
    configured = key is not None or not profile.needs_key
    last4 = key[-4:] if key and len(key) >= 12 else None
    return ProfileView(**profile.model_dump(), configured=configured, last4=last4, source=source, key_store=secret_store.store_kind())


def listing(user: UserView, store=None) -> ProfileList:
    store = store or profile_store.load_store(runtime.settings, user)
    return ProfileList(active=store.active, profiles=[view(p, user) for p in store.profiles])


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


def has_key(key) -> bool:
    """A key counts only if something is left after stripping: store_key drops a blank one and keeps the saved key."""
    return bool(key and key.get_secret_value().strip())


def refuse_key_redirect(profile: Profile, base_url: str | None) -> None:
    # With shared access to a server, "keep the saved key but use another URL" would hand the key to that URL.
    if base_url is not None and base_url != profile.base_url:
        raise HTTPException(403, "Changing the base URL needs the API key entered again")


@profiles.get("", response_model=ProfileList)
def list_profiles(user: CurrentUser):
    return listing(user)


@profiles.post("", response_model=ProfileList, status_code=201)
def create_profile(body: NewProfile, user: CurrentUser):
    store = profile_store.load_store(runtime.settings, user)
    taken = {p.id for p in store.profiles}
    profile_id = new_profile_id()
    while profile_id in taken:
        profile_id = new_profile_id()
    providers.ensure_public_url(body.base_url)
    profile = Profile(id=profile_id, **body.model_dump(exclude={"key"}))
    store_key(profile_store.profile_account(user, profile.id), body.key.get_secret_value() if body.key else None)
    store.profiles.append(profile)
    store.active = store.active or profile.id
    profile_store.save_store(runtime.settings, user, store)
    return listing(user, store)


@profiles.patch("/{profile_id}", response_model=ProfileList)
def edit_profile(profile_id: ProfileId, body: EditProfile, user: CurrentUser):
    store = profile_store.load_store(runtime.settings, user)
    profile = providers.find_profile(store, profile_id)
    if runtime.settings.deployed and not has_key(body.key):
        refuse_key_redirect(profile, body.base_url)
    if body.base_url is not None:
        providers.ensure_public_url(body.base_url)
    for field, value in body.model_dump(exclude={"key"}, exclude_none=True).items():
        setattr(profile, field, value)
    if "context_window" in body.model_fields_set:  # an explicit null clears it
        profile.context_window = body.context_window
    if "image_model" in body.model_fields_set:
        profile.image_model = body.image_model
    store_key(profile_store.profile_account(user, profile.id), body.key.get_secret_value() if body.key else None)
    profile_store.save_store(runtime.settings, user, store)
    return listing(user, store)


@profiles.delete("/{profile_id}", response_model=ProfileList)
def delete_profile(profile_id: ProfileId, user: CurrentUser):
    store = profile_store.load_store(runtime.settings, user)
    providers.find_profile(store, profile_id)
    store.profiles = [p for p in store.profiles if p.id != profile_id]
    if store.active == profile_id:
        store.active = store.profiles[0].id if store.profiles else None
    secret_store.delete_key(profile_store.profile_account(user, profile_id))
    if profile_id == profile_store.DEFAULT_ID and profile_store.is_local(user):
        secret_store.delete_key()
    profile_store.save_store(runtime.settings, user, store)
    return listing(user, store)


@profiles.post("/{profile_id}/activate", response_model=ProfileList)
def activate_profile(profile_id: ProfileId, user: CurrentUser):
    store = profile_store.load_store(runtime.settings, user)
    providers.find_profile(store, profile_id)
    store.active = profile_id
    profile_store.save_store(runtime.settings, user, store)
    return listing(user, store)


def context_size(model) -> int | None:
    for field in ("context_length", "context_window"):
        n = getattr(model, field, None)
        if isinstance(n, int) and not isinstance(n, bool) and n > 0:
            return n
    return None


@profiles.post("/models", response_model=ModelsResult)
async def list_models(body: ModelsQuery, user: CurrentUser):
    """Lists the provider's models; doubles as the key test. Works on unsaved profiles."""
    base_url, key, needs_key = body.base_url, None, body.needs_key
    if body.key:
        key = body.key.get_secret_value().strip() or None
    if body.profile_id:
        profile = providers.find_profile(profile_store.load_store(runtime.settings, user), body.profile_id)
        if runtime.settings.deployed and not has_key(body.key):
            refuse_key_redirect(profile, base_url)
        base_url = base_url or profile.base_url
        needs_key = profile.needs_key
        key = key or profile_store.resolve_key(runtime.settings, user, profile)[0]
    if not base_url:
        raise HTTPException(422, "Enter a base URL")
    if key is None and needs_key:
        raise HTTPException(409, "Enter an API key first")
    await run_in_threadpool(providers.ensure_public_url, base_url)  # DNS lookup, so off the event loop
    client = OpenAI(base_url=base_url, api_key=key or providers.NO_KEY, **providers.client_options())
    try:
        page = list(await run_in_threadpool(client.models.list))
        result: dict = {"models": sorted(m.id for m in page)}
        # OpenRouter reports sizes; most providers don't, so the key is only present when known.
        windows = {m.id: n for m in page if (n := context_size(m))}
        if windows:
            result["context_windows"] = windows
        return result
    except OpenAIError as e:
        # If the name now resolves somewhere internal (DNS rebinding), the error text is that service's, not a provider's.
        if runtime.settings.deployed and not await run_in_threadpool(providers.is_public_url, base_url):
            raise HTTPException(502, "Could not reach the provider")
        raise HTTPException(502, providers.redact(getattr(e, "message", str(e)), key))
    finally:
        client.close()


web_settings = APIRouter(prefix="/api/web", dependencies=[Depends(require_local_origin)])


def web_status(user: UserView) -> WebStatus:
    key = secret_store.get_key(profile_store.tavily_account(user))
    return WebStatus(
        configured=key is not None,
        last4=key[-4:] if key and len(key) >= 12 else None,
        key_store=secret_store.store_kind(),
    )


@web_settings.get("", response_model=WebStatus)
def get_web_status(user: CurrentUser):
    return web_status(user)


@web_settings.put("/key", response_model=WebStatus)
def set_web_key(body: WebKey, user: CurrentUser):
    store_key(profile_store.tavily_account(user), body.key.get_secret_value())
    return web_status(user)


@web_settings.delete("/key", response_model=WebStatus)
def delete_web_key(user: CurrentUser):
    secret_store.delete_key(profile_store.tavily_account(user))
    return web_status(user)
