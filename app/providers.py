"""Everything about talking to an upstream provider: which profile and key to use, the SDK client, requests and error text."""

import base64
import json

from fastapi import HTTPException
from openai import OpenAI, OpenAIError
from pydantic import ValidationError

import profile_store
from app import runtime
from models import Chat, ImageData, Profile

_clients: dict[tuple[str, str], OpenAI] = {}
NO_KEY = "not-needed"  # the OpenAI SDK insists on a non-empty key even for local servers


def active_profile() -> Profile:
    store = profile_store.load_store(runtime.settings)
    profile = next((p for p in store.profiles if p.id == store.active), None)
    if profile is None:
        raise HTTPException(409, "No provider configured. Add one in Providers.")
    return profile


def override_applies(chat: Chat, profile: Profile) -> bool:
    # A model ID belongs to the provider it was picked on; after a fallback to another provider it is stale.
    return bool(chat.model) and chat.profile_id == profile.id


def profile_for(chat: Chat) -> Profile:
    """The chat's own provider, falling back to the default when it has none or it was deleted."""
    store = profile_store.load_store(runtime.settings)
    wanted = chat.profile_id if chat.profile_id in {p.id for p in store.profiles} else store.active
    profile = next((p for p in store.profiles if p.id == wanted), None)
    if profile is None:
        raise HTTPException(409, "No provider configured. Add one in Providers.")
    # A copy, so the stored profile is never changed by a per-chat override.
    return profile.model_copy(update={"model": chat.model}) if override_applies(chat, profile) else profile


def profile_key(profile: Profile) -> str | None:
    if not profile.needs_key:
        return NO_KEY
    return profile_store.resolve_key(runtime.settings, profile)[0]


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
        return message
    raw = meta.get("raw")
    if not isinstance(raw, str):
        raw = json.dumps(raw) if raw else ""
    reason = " ".join(readable_reason(raw.strip()).split())[:500]
    provider = meta.get("provider_name")
    inner = body.get("message")
    head = inner if isinstance(inner, str) and inner else message
    detail = f"{provider}: {reason}" if provider and reason else reason or (provider or "")
    return f"{head} ({detail})" if detail else head


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


def profile_window(chat: Chat) -> int | None:
    try:
        return window_for(chat, profile_for(chat))
    except HTTPException:
        return None


# Base URLs whose server rejected stream_options, so later requests skip it.
_no_stream_options: set[str] = set()


def sampling_params(chat: Chat) -> dict:
    fields = ("temperature", "top_p", "frequency_penalty", "max_tokens")
    return {k: v for k in fields if (v := getattr(chat, k)) is not None}


def open_stream(client: OpenAI, profile: Profile, messages: list[dict], sampling: dict | None = None):
    kwargs = {"model": profile.model, "messages": messages, "stream": True, **(sampling or {})}
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
