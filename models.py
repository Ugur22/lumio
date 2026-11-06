import base64
import binascii
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, SecretStr, StringConstraints, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).parent
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

MAX_IMAGES = 4
# The browser downscales first, so this is a ceiling for misbehaving clients, not a target.
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MediaType = Literal["image/png", "image/jpeg", "image/webp", "image/gif"]
IMAGE_EXTENSIONS: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ApiModel(BaseModel):
    # Responses always carry every field, so the generated TypeScript must not mark defaulted ones optional.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_prefix="DOLPHINLLM_", extra="ignore"
    )

    api_key: str | None = None
    base_url: str = "https://api.dolphinllm.com/v1"
    model: str = "uncensored"
    data_dir: Path = BASE_DIR / "data" / "chats"
    # Where chats live. Unset, it sits next to the chat images; on a server point it at persistent storage
    # that a release (rsync into /opt/lumio) never replaces.
    db_file: Path | None = None
    profiles_file: Path = BASE_DIR / "profiles.json"
    # Set on a server: the hostname browsers use. It is also accepted by require_local_origin and
    # switches on the checks that stop a stored key being sent to a different base URL.
    public_host: str | None = None
    # Env DOLPHINLLM_ADMIN_USER. On a server (public_host set): the username that takes over chats saved before
    # accounts existed. It must already exist (python -m accounts create-user NAME --admin); needed only while
    # such chats exist, and the app refuses to start without it rather than leave them readable by anyone.
    admin_user: str | None = None
    # Images are only kept so follow-up questions keep working; they are pruned after this.
    image_retention_days: int = Field(default=30, ge=1)

    # Free trial: new users sign in with Google or GitHub and get a few text-only replies on a key the operator owns.
    # Off unless every piece below is configured (see trial_enabled); open_signup is the kill switch.
    open_signup: bool = False
    trial_api_key: SecretStr | None = None  # never the same setting as api_key: that one belongs to the admin
    trial_base_url: str = "https://api.deepseek.com"
    trial_model: str = "deepseek-flash"
    trial_calls: int = Field(default=5, ge=1)
    trial_daily_calls: int = Field(default=150, ge=1)  # all trials together, per UTC day
    # The part of trial_daily_calls kept for users who sign up with a trial invite, so a flood of open sign-ups cannot use it up.
    trial_reserved_share: float = Field(default=0.7, ge=0, le=1)
    oauth_google_client_id: str | None = None
    oauth_google_client_secret: SecretStr | None = None
    oauth_github_client_id: str | None = None
    oauth_github_client_secret: SecretStr | None = None
    # Keys the HMACs that identify a person across account deletion; changing it forgets every earlier trial.
    oauth_pepper: SecretStr | None = None
    # Origin used to build the OAuth redirect URIs; defaults to https://<public_host>.
    public_base_url: str | None = None
    # Lets the native app's sign-in come back to an Expo Go address (exp://<host>/--/auth), which changes per network. For
    # testing only; the only redirect accepted when it is off is lumio://auth.
    oauth_app_dev_redirects: bool = False

    @property
    def deployed(self) -> bool:
        return self.public_host is not None

    def oauth_providers(self) -> list[str]:
        """Providers with both a client id and a secret."""
        found = []
        for name in ("google", "github"):
            if getattr(self, f"oauth_{name}_client_id") and getattr(self, f"oauth_{name}_client_secret"):
                found.append(name)
        return found

    @property
    def trial_enabled(self) -> bool:
        return bool(
            self.deployed and self.open_signup and self.trial_api_key and self.oauth_pepper and self.oauth_providers()
        )

    @property
    def reserved_calls(self) -> int:
        return round(self.trial_daily_calls * self.trial_reserved_share)

    @property
    def open_calls(self) -> int:
        return self.trial_daily_calls - self.reserved_calls

    # Sign-ups are tied to each pool's call cap so a rush ends at sign-up, with a clear message, not as a 503 on the first
    # message of an account that was just created. A pool smaller than one trial allows no sign-ups at all.
    @property
    def open_signup_limit(self) -> int:
        return self.open_calls // self.trial_calls

    @property
    def reserved_signup_limit(self) -> int:
        return self.reserved_calls // self.trial_calls

    def pool_calls(self, pool: str) -> int:
        return self.reserved_calls if pool == "reserved" else self.open_calls

    @property
    def origin(self) -> str:
        return (self.public_base_url or f"https://{self.public_host}").rstrip("/")

    @property
    def database(self) -> Path:
        return self.db_file or self.data_dir / "lumio.db"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"


class Source(ApiModel):
    url: str
    title: str = ""
    text: str


class ImageData(ApiModel):
    """An image as uploaded by the browser: raw base64 without the `data:` prefix."""

    media_type: MediaType
    data: str = Field(min_length=1, max_length=MAX_IMAGE_BYTES * 4 // 3 + 4)

    @field_validator("data")
    @classmethod
    def _base64(cls, v: str) -> str:
        try:
            raw = base64.b64decode(v, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("Image data is not valid base64")
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError(f"Image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
        return v


class ImageRef(ApiModel):
    """A stored image. The bytes live in `images_dir`, so chat files stay small."""

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    media_type: MediaType
    # What a generated illustration was asked to show: alt text, and its stand-in in history.
    prompt: str | None = None


class TextPart(ApiModel):
    type: Literal["text"] = "text"
    text: str


class ImageUrl(ApiModel):
    url: str


class ImagePart(ApiModel):
    type: Literal["image_url"] = "image_url"
    image_url: ImageUrl


# The OpenAI-compatible `content` array: a discriminated union keeps provider payloads typed.
ContentPart = Annotated[TextPart | ImagePart, Field(discriminator="type")]


class Message(ApiModel):
    role: Literal["user", "assistant"]
    content: str
    created: datetime = Field(default_factory=utcnow)
    images: list[ImageRef] = []
    # Web pages the reply was based on; kept on the user message so later turns can reuse them.
    sources: list[Source] = []
    # The search query actually used for this turn (may differ from the text typed).
    query: str | None = None


MAX_BIBLE_CHARS = 20_000
MAX_SUMMARY_CHARS = 20_000
MAX_SYSTEM_PROMPT_CHARS = 10_000
MAX_LORE_ENTRIES = 200
LORE_ID = r"^[0-9a-f]{32}$"


class LoreEntry(ApiModel):
    id: str = Field(pattern=LORE_ID)
    name: str = Field(min_length=1, max_length=80)
    # Any one of these words appearing in recent messages pulls the entry into the prompt.
    keys: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(default=[], max_length=20)
    content: str = Field(default="", max_length=5000)
    enabled: bool = True


class Usage(ApiModel):
    prompt_tokens: int = Field(ge=0)


class Chat(ApiModel):
    id: str
    title: str = "New chat"
    created: datetime = Field(default_factory=utcnow)
    updated: datetime = Field(default_factory=utcnow)
    messages: list[Message] = []
    # Story context. Defaults keep chat files saved before this existed loadable.
    # The bible's size is capped on StoryUpdate, not here, so an old oversized file still opens.
    bible: str = ""
    lore: list[LoreEntry] = []
    summary: str = ""
    # How many leading messages the summary stands in for; they stay stored but are not sent.
    summary_upto: int = Field(default=0, ge=0)
    # Provider-reported size of the last prompt; cleared when the story or summary changes.
    last_usage: Usage | None = None
    # How the model should behave in this chat. None means "don't send it", so the provider's default applies.
    system_prompt: str = ""
    temperature: float | None = None
    top_p: float | None = None
    frequency_penalty: float | None = None
    max_tokens: int | None = None
    # None follows the global default provider, so chats saved before this existed keep working.
    profile_id: str | None = None
    # Why: the pair overrides the profile's model and window for this chat only, so editing the
    # profile never moves it. Both default to None so chat files saved before this still load.
    model: str | None = Field(default=None, min_length=1, max_length=120)
    context_window: int | None = Field(default=None, ge=1000)


class ChatSummary(ApiModel):
    id: str
    title: str
    updated: datetime
    message_count: int


def clean_base_url(url: str) -> str:
    url = url.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("Enter a full URL such as https://api.example.com/v1")
    # The key is sent to this URL, so plain http is only acceptable for this machine.
    if parts.scheme == "http" and parts.hostname not in LOCAL_HOSTS:
        raise ValueError("Use https (plain http is only allowed for localhost)")
    return url


XAI_IMAGE_MODEL = "grok-imagine-image-2.0"


def blank_to_none(v):
    return None if isinstance(v, str) and not v.strip() else v.strip() if isinstance(v, str) else v


class Profile(ApiModel):
    id: str
    name: str = Field(min_length=1, max_length=60)
    base_url: str
    model: str = Field(min_length=1, max_length=120)
    # Local servers such as Ollama accept requests without a key.
    needs_key: bool = True
    # Set by the user: /models does not report capabilities, so it cannot be detected.
    vision: bool = False
    # Set by the user (OpenRouter's model list can prefill it): used only for the usage meter.
    context_window: int | None = Field(default=None, ge=1000)
    # Model for POST /images/generations; None means the provider can't illustrate replies.
    image_model: str | None = Field(default=None, max_length=120)

    _blank_image_model = field_validator("image_model", mode="before")(lambda cls, v: blank_to_none(v))

    @model_validator(mode="before")
    @classmethod
    def _xai_defaults(cls, data):
        # Profiles saved before these fields existed: Grok models read images and xAI
        # offers an image model, so an existing xAI profile should not need setting up by hand.
        if isinstance(data, dict):
            host = urlsplit(str(data.get("base_url", ""))).hostname
            if host == "api.x.ai":
                defaults = {"vision": True, "image_model": XAI_IMAGE_MODEL}
                return {**{k: v for k, v in defaults.items() if k not in data}, **data}
        return data


class ProfileStore(ApiModel):
    active: str | None = None
    profiles: list[Profile] = []


class ProfileView(Profile):
    configured: bool
    last4: str | None = None
    # "server": the free-trial profile, whose key belongs to the operator and is never shown.
    source: Literal["keychain", "env", "server"] | None = None
    # A profile the server provides and the user can neither edit nor delete.
    managed: bool = False
    # Where saved keys live: the OS keychain locally, a file on a server.
    key_store: Literal["keychain", "file"] = "keychain"


class ProfileList(ApiModel):
    active: str | None
    profiles: list[ProfileView]


class NewProfile(ApiModel):
    name: str = Field(min_length=1, max_length=60)
    base_url: str
    model: str = Field(min_length=1, max_length=120)
    needs_key: bool = True
    vision: bool = False
    context_window: int | None = Field(default=None, ge=1000)
    image_model: str | None = Field(default=None, max_length=120)
    key: SecretStr | None = None

    _url = field_validator("base_url")(lambda cls, v: clean_base_url(v))
    _blank_image_model = field_validator("image_model", mode="before")(lambda cls, v: blank_to_none(v))


class EditProfile(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    base_url: str | None = None
    model: str | None = Field(default=None, min_length=1, max_length=120)
    vision: bool | None = None
    context_window: int | None = Field(default=None, ge=1000)
    # Nullable like context_window: an explicit null clears it (see edit_profile).
    image_model: str | None = Field(default=None, max_length=120)
    key: SecretStr | None = None

    _blank_image_model = field_validator("image_model", mode="before")(lambda cls, v: blank_to_none(v))

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return None if v is None else clean_base_url(v)


class ModelsQuery(ApiModel):
    profile_id: str | None = None
    base_url: str | None = None
    key: SecretStr | None = None
    needs_key: bool = True

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return None if v is None else clean_base_url(v)


class ModelsResult(ApiModel):
    models: list[str]
    # Only present when the provider reports sizes (OpenRouter does); most don't.
    context_windows: dict[str, int] | None = None


class NewMessage(ApiModel):
    content: str = ""
    images: list[ImageData] = Field(default=[], max_length=MAX_IMAGES)
    web: bool = False
    illustrate: bool = False

    @model_validator(mode="after")
    def _not_empty(self) -> "NewMessage":
        if not self.content.strip() and not self.images:
            raise ValueError("Write a message or attach an image")
        return self


def _lower(value):
    return value.lower() if isinstance(value, str) else value


# Stored lowercased; uniqueness is case-insensitive.
Username = Annotated[str, BeforeValidator(_lower), StringConstraints(pattern=r"^[a-z0-9_-]{3,32}$")]
Password = Annotated[SecretStr, Field(min_length=10, max_length=128)]


class UserView(ApiModel):
    id: str
    username: str
    is_admin: bool


# Without a deployment (local dev, main.py, tests) there is one fixed user and no login.
LOCAL_USER = UserView(id="local", username="local", is_admin=True)


class RegisterBody(ApiModel):
    username: Username
    password: Password
    invite: SecretStr = Field(min_length=1, max_length=256)


class LoginBody(ApiModel):
    # No format rules here: a malformed name must fail like a wrong one, not with a different status.
    username: Annotated[str, BeforeValidator(_lower), Field(min_length=1, max_length=128)]
    password: SecretStr = Field(min_length=1, max_length=1024)


class TokenLogin(ApiModel):
    token: str
    user: UserView


class ExchangeBody(ApiModel):
    # No length rules here: any bad code or verifier must fail with the one generic 400, not a validation error.
    code: str
    verifier: str


class PasswordChange(ApiModel):
    current_password: SecretStr = Field(min_length=1, max_length=1024)
    new_password: Password


class TrialStatus(ApiModel):
    enrolled: bool
    limit: int
    used: int
    remaining: int
    # Used up, or the operator switched trials off: either way the user's own provider is what is left.
    ended: bool


class WebKey(ApiModel):
    key: SecretStr = Field(min_length=1, max_length=512)


class WebStatus(ApiModel):
    configured: bool
    last4: str | None = None
    key_store: Literal["keychain", "file"] = "keychain"


class RenameChat(ApiModel):
    title: str = Field(min_length=1, max_length=100)


class StoryUpdate(ApiModel):
    bible: str = Field(default="", max_length=MAX_BIBLE_CHARS)
    lore: list[LoreEntry] = Field(default=[], max_length=MAX_LORE_ENTRIES)


class BehaviorUpdate(ApiModel):
    system_prompt: str = Field(default="", max_length=MAX_SYSTEM_PROMPT_CHARS)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    # Only applied when sent (see update_behavior), so a client that predates it can't clear the chat's provider.
    profile_id: str | None = Field(default=None, pattern=r"^[0-9a-z]{1,32}$")


class ChatModelUpdate(ApiModel):
    # null model clears the override (and the window with it).
    model: str | None = Field(default=None, min_length=1, max_length=120)
    context_window: int | None = Field(default=None, ge=1000)


class SummaryUpdate(ApiModel):
    summary: str = Field(max_length=MAX_SUMMARY_CHARS)
    summary_upto: int = Field(ge=0)


class SummaryProposal(ApiModel):
    summary: str
    summary_upto: int


class ContextParts(ApiModel):
    system: int
    bible: int
    lore: int
    summary: int
    history: int


class ContextInfo(ApiModel):
    used: int
    window: int | None
    source: Literal["provider", "estimate"]
    parts: ContextParts
