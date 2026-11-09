"""Everything about talking to an upstream provider: which profile and key to use, the SDK client, requests and error text."""

import base64
import json
import threading

import web
from fastapi import HTTPException
from openai import APIStatusError, DefaultHttpxClient, OpenAI, OpenAIError
from pydantic import ValidationError

import profile_store
import storage
from app import runtime, story
from app.logs import log
from models import Chat, ImageData, NewMessage, Profile, ProfileStore, UserView

_clients: dict[tuple[str, str], OpenAI] = {}
_clients_lock = threading.Lock()
PRIVATE_URL = "That address is not allowed: this server only connects to public hosts."
NO_KEY = "not-needed"  # the OpenAI SDK insists on a non-empty key even for local servers


TRIAL_ENDED = "Your free trial has ended. Add your own provider to continue."
TRIAL_FULL = "Free trials are full today, try tomorrow"
TRIAL_LOCKED = "Adding your own provider unlocks when your free trial ends"
# Enforced on the server whatever the client sends.
TRIAL_MAX_TOKENS = 1500
TRIAL_MESSAGE_CHARS = 4000
TRIAL_HISTORY_MESSAGES = 20
TRIAL_PROMPT_CHARS = 60_000
# DeepSeek thinks unless told not to, and hidden reasoning eats the clamped max_tokens, leaving an empty reply.
TRIAL_EXTRA_BODY = {"thinking": {"type": "disabled"}}
TRIAL_MAX_CHATS = 50
MAX_PROFILES = 5


def trial_state(user: UserView) -> storage.Trial | None:
    """The user's trial while it can still be used, else None (no trial, used up, or trials switched off)."""
    if not runtime.settings.trial_enabled or profile_store.is_local(user):
        return None
    trial = runtime.db.get_trial(user.id)
    return None if trial is None or trial.exhausted else trial


def trial_active(user: UserView) -> bool:
    return trial_state(user) is not None


def user_store(user: UserView, store: ProfileStore | None = None) -> ProfileStore:
    """The user's saved profiles plus, while their trial is live, the synthetic trial profile. Never write this to disk:
    saving goes through profile_store.load_store, which does not know the trial profile."""
    store = store or profile_store.load_store(runtime.settings, user)
    if trial_state(user) is None:
        return store
    own = [p for p in store.profiles if p.id != profile_store.TRIAL_ID]
    active = store.active if store.active in {p.id for p in own} else profile_store.TRIAL_ID
    return store.model_copy(update={"profiles": [*own, profile_store.trial_profile(runtime.settings)], "active": active})


def no_provider(user: UserView) -> HTTPException:
    # A user whose trial has run out is told to add a provider; anyone else sees the original message.
    if not profile_store.is_local(user) and runtime.db.get_trial(user.id) is not None:
        return HTTPException(402, TRIAL_ENDED)
    return HTTPException(409, "No provider configured. Add one in Providers.")


def is_trial(profile: Profile) -> bool:
    return isinstance(profile, profile_store.TrialProfile)


def active_profile(user: UserView) -> Profile:
    store = user_store(user)
    profile = next((p for p in store.profiles if p.id == store.active), None)
    if profile is None:
        raise no_provider(user)
    return profile


def override_applies(chat: Chat, profile: Profile) -> bool:
    # A model ID belongs to the provider it was picked on; after a fallback to another provider it is stale.
    # The trial's model is fixed by the server, whatever the chat says.
    return bool(chat.model) and chat.profile_id == profile.id and not is_trial(profile)


def profile_for(chat: Chat, user: UserView) -> Profile:
    """The chat's own provider, falling back to the caller's default when it has none, it was deleted, or it is not in
    the caller's store (indistinguishable from deleted, so another user's profile id is never confirmed)."""
    store = user_store(user)
    wanted = chat.profile_id if chat.profile_id in {p.id for p in store.profiles} else store.active
    profile = next((p for p in store.profiles if p.id == wanted), None)
    if profile is None:
        raise no_provider(user)
    # A copy, so the stored profile is never changed by a per-chat override.
    return profile.model_copy(update={"model": chat.model}) if override_applies(chat, profile) else profile


def profile_key(profile: Profile, user: UserView) -> str | None:
    if is_trial(profile):
        # Only profile_for/user_store build a TrialProfile, and only for a user with a live trial.
        key = runtime.settings.trial_api_key
        return key.get_secret_value() if key else None
    if not profile.needs_key:
        return NO_KEY
    return profile_store.resolve_key(runtime.settings, user, profile)[0]


def trial_prompt(chat: Chat, body: NewMessage) -> tuple[str, list[dict]]:
    """The system prompt and history for a trial reply, within the trial's limits. Raises 422 before anything is reserved."""
    if body.web:
        raise HTTPException(422, "Web search is not available during the free trial.")
    if len(body.content) > TRIAL_MESSAGE_CHARS:
        raise HTTPException(422, f"Messages are limited to {TRIAL_MESSAGE_CHARS} characters during the free trial.")
    system = story.system_for(chat, body.content, False)
    history = drop_blank_replies(story.history_for(chat, False, False))[-TRIAL_HISTORY_MESSAGES:]
    while history and history[0]["role"] != "user":
        history.pop(0)
    # Oldest first out: a long chat keeps working, only its far past stops being sent.
    while history and len(system) + len(body.content) + sum(len(m["content"]) for m in history) > TRIAL_PROMPT_CHARS:
        history.pop(0)
    if len(system) + len(body.content) > TRIAL_PROMPT_CHARS:
        raise HTTPException(422, "This chat's instructions and story notes are too long for the free trial.")
    return system, history


def drop_blank_replies(history: list[dict]) -> list[dict]:
    """Blank assistant turns stored by older chats are not sent upstream; the question they answered goes with them so
    user and assistant keep alternating."""
    out: list[dict] = []
    for m in history:
        if m["role"] == "assistant" and not str(m["content"]).strip():
            if out and out[-1]["role"] == "user":
                out.pop()
            continue
        out.append(m)
    return out


def trial_sampling(chat: Chat) -> dict:
    sampling = sampling_params(chat)
    sampling["max_tokens"] = min(sampling.get("max_tokens") or TRIAL_MAX_TOKENS, TRIAL_MAX_TOKENS)
    return sampling


_full_logged: set[tuple[str, str]] = set()  # (pool, UTC day) already reported; per process, which is enough for a signal


def _log_pool_full(e: storage.TrialFull) -> None:
    """Once per pool per day: the first refusal is the news, the thousand after it are not."""
    key = (e.pool, e.day)
    if key in _full_logged:
        return
    _full_logged.difference_update({k for k in _full_logged if k[1] != e.day})
    _full_logged.add(key)
    log.warning(
        "Trial pool %s is full for %s: %d of %d calls used", e.pool, e.day, e.cap, e.cap, extra={"pool": e.pool, "day": e.day, "calls": e.cap, "cap": e.cap}
    )


def reserve_trial(user: UserView) -> storage.TrialCall:
    try:
        return runtime.db.reserve_trial_call(
            user.id, {pool: runtime.settings.pool_calls(pool) for pool in storage.POOLS}
        )
    except storage.TrialExhausted:
        raise HTTPException(402, TRIAL_ENDED)
    except storage.TrialFull as e:
        _log_pool_full(e)
        raise HTTPException(503, TRIAL_FULL, headers={"Retry-After": str(e.retry_after)})


def require_no_trial(user: UserView) -> None:
    """Adding a provider of your own waits until the trial is over."""
    if trial_active(user):
        raise HTTPException(403, TRIAL_LOCKED)


def is_public_url(url: str) -> bool:
    try:
        web.check_public(url)
    except (web.WebError, ValueError):  # ValueError: a port outside 0-65535 reaches check_public unvalidated
        return False
    return True


def ensure_public_url(url: str) -> None:
    """On a server, a provider URL may not point at loopback, link-local, private or unspecified addresses (resolving
    names like web.check_public does): the server would otherwise fetch internal services, such as the cloud metadata
    endpoint, for any signed-in user. Locally the URL is the user's own business (Ollama on 127.0.0.1)."""
    if runtime.settings.deployed and not is_public_url(url):
        raise HTTPException(422, PRIVATE_URL)


def client_options() -> dict:
    if runtime.settings.deployed:
        # The SDK follows redirects by default; a public URL could otherwise bounce the request to an internal one.
        return {"http_client": DefaultHttpxClient(follow_redirects=False)}
    return {}


def get_client(profile: Profile, user: UserView) -> OpenAI:
    key = profile_key(profile, user)
    if key is None:
        raise HTTPException(409, f"No API key for {profile.name}. Add one in Providers.")
    # On every call, not only when a client is built: a name can start resolving to an internal address later (DNS rebinding).
    ensure_public_url(profile.base_url)
    cache_key = (profile.base_url, key)
    with _clients_lock:
        # Returned from the local: another thread's clear() can run right after this block.
        client = _clients.get(cache_key)
        if client is None:
            _clients.clear()
            client = _clients[cache_key] = OpenAI(base_url=profile.base_url, api_key=key, **client_options())
        return client


def redact(message: str, key: str | None) -> str:
    return message.replace(key, "…") if key else message


def client_error(e: Exception, key: str | None) -> str:
    """error_text for a client: the key of the call and the operator's trial key are both removed, since a provider's
    error body can echo the Authorization it was sent."""
    trial = runtime.settings.trial_api_key
    return redact(redact(friendly_error(e, error_text(e)), key), trial.get_secret_value() if trial else None)


def sniff_media_type(raw: bytes) -> str | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw[:4] == b"GIF8":
        return "image/gif"
    return None


def generate_image(client: OpenAI, model: str, prompt: str) -> ImageData:
    res = client.images.generate(model=model, prompt=prompt, n=1, response_format="b64_json")
    encoded = res.data[0].b64_json
    if not encoded:
        raise ValueError("the provider returned no image data")
    media_type = sniff_media_type(base64.b64decode(encoded, validate=True)[:12])
    if media_type is None:
        raise ValueError("the provider returned an unsupported image format")
    return ImageData(media_type=media_type, data=encoded)


def provider_error_parts(e: Exception, key: str | None, limit: int = 500) -> tuple[int | None, str]:
    """HTTP status and whitespace-collapsed, redacted body of a failed provider call: the SDK's own message drops both when the body is not OpenAI-shaped."""
    status = getattr(e, "status_code", None)
    if not isinstance(status, int) or isinstance(status, bool):
        status = None
    if isinstance(e, ValueError) and not isinstance(e, ValidationError):
        body = str(e)
    elif isinstance(e, OpenAIError):
        body = getattr(getattr(e, "response", None), "text", "") or getattr(e, "message", str(e))
    else:
        # Parsing errors can echo the provider payload; give a fixed reason instead.
        body = "the provider returned an unusable image response"
    return status, redact(" ".join(str(body).split()), key)[:limit]


def error_text(e: Exception) -> str:
    """The message for a failed chat call, with the upstream reason OpenRouter nests under metadata.raw ("Provider returned error" alone hides it)."""
    message = getattr(e, "message", str(e))
    body = getattr(e, "body", None)
    meta = body.get("metadata") if isinstance(body, dict) else None
    if not isinstance(meta, dict):
        return upstream_reason(e, message)
    raw = meta.get("raw")
    if not isinstance(raw, str):
        raw = json.dumps(raw) if raw else ""
    reason = " ".join(readable_reason(raw.strip()).split())[:500]
    provider = meta.get("provider_name")
    inner = body.get("message")
    head = inner if isinstance(inner, str) and inner else message
    detail = f"{provider}: {reason}" if provider and reason else reason or (provider or "")
    return f"{head} ({detail})" if detail else head


def upstream_reason(e: Exception, message: str) -> str:
    """The SDK message is a bare "Error code: 403" when the body is not OpenAI-shaped (xAI sends {"code": ..., "error": "..."}); the response text has the reason."""
    if not isinstance(e, APIStatusError) or " - " in message:
        return message
    reason = readable_reason(" ".join((e.response.text or "").split()))[:500]
    return f"{message}: {reason}" if reason else message


HINTS = {
    401: "The provider rejected the API key. Check the key in the Providers dialog.",
    402: "The provider account is out of credits.",
    403: "The provider refused the request. This usually means a spending limit or used-up credits, or a key without access to this model.",
    429: "The provider is rate limiting or the usage limit is reached. Wait a while or switch to another provider.",
}


def friendly_error(e: Exception, text: str) -> str:
    """The provider's own reason when it gave one (it is clearer than any hint); a hint only for a bare status."""
    if not isinstance(e, APIStatusError):
        return text
    bare = f"Error code: {e.status_code}"
    if text.startswith(f"{bare}: "):
        return f"{e.status_code}: {text[len(bare) + 2:]}"
    hint = HINTS.get(e.status_code)
    return f"{hint} ({e.status_code})" if hint and text == bare else text


def describe_provider_error(e: Exception, key: str | None) -> str:
    status, detail = provider_error_parts(e, key)
    return f"{status or type(e).__name__}: {detail}"


def readable_reason(detail: str) -> str:
    """The message inside a JSON error body ({"error": "..."} or {"error": {"message": "..."}}), else the text as is."""
    try:
        body = json.loads(detail)
    except ValueError:
        return detail
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        err = err.get("message")
    return " ".join(err.split()) if isinstance(err, str) and err.strip() else detail


def window_for(chat: Chat, profile: Profile) -> int | None:
    # An overridden model has its own window; the profile's belongs to a different model.
    return chat.context_window if override_applies(chat, profile) else profile.context_window


def profile_window(chat: Chat, user: UserView) -> int | None:
    try:
        return window_for(chat, profile_for(chat, user))
    except HTTPException:
        return None


# Base URLs whose server rejected stream_options, so later requests skip it.
_no_stream_options: set[str] = set()


def sampling_params(chat: Chat) -> dict:
    fields = ("temperature", "top_p", "frequency_penalty", "max_tokens")
    return {k: v for k in fields if (v := getattr(chat, k)) is not None}


def open_stream(client: OpenAI, profile: Profile, messages: list[dict], sampling: dict | None = None):
    kwargs = {"model": profile.model, "messages": messages, "stream": True, **(sampling or {})}
    if is_trial(profile):
        # Operator-chosen provider, so a rejection of this field is a configuration error. Both attempts below keep it:
        # dropping it would silently turn thinking back on, and the retry only ever sheds stream_options.
        kwargs["extra_body"] = TRIAL_EXTRA_BODY
    if profile.base_url in _no_stream_options:
        return client.chat.completions.create(**kwargs)
    try:
        return client.chat.completions.create(**kwargs, stream_options={"include_usage": True})
    except OpenAIError as e:
        # Only a client error can mean "unknown parameter"; anything else is a real failure.
        if getattr(e, "status_code", None) not in (400, 422):
            raise
    stream = client.chat.completions.create(**kwargs)
    # Remembered only once the retry works, so an unrelated 400 doesn't disable usage reporting.
    _no_stream_options.add(profile.base_url)
    return stream


def find_profile(store, profile_id: str) -> Profile:
    profile = next((p for p in store.profiles if p.id == profile_id), None)
    if profile is None:
        raise HTTPException(404, "Provider not found")
    return profile
