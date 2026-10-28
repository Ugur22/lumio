import base64
import binascii
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_prefix="DOLPHINLLM_", extra="ignore"
    )

    api_key: str | None = None
    base_url: str = "https://api.dolphinllm.com/v1"
    model: str = "uncensored"
    data_dir: Path = BASE_DIR / "data" / "chats"
    profiles_file: Path = BASE_DIR / "profiles.json"
    # Images are only kept so follow-up questions keep working; they are pruned after this.
    image_retention_days: int = Field(default=30, ge=1)

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"


class Source(BaseModel):
    url: str
    title: str = ""
    text: str


class ImageData(BaseModel):
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


class ImageRef(BaseModel):
    """A stored image. The bytes live in `images_dir`, so chat files stay small."""

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    media_type: MediaType


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImageUrl(BaseModel):
    url: str


class ImagePart(BaseModel):
    type: Literal["image_url"] = "image_url"
    image_url: ImageUrl


# The OpenAI-compatible `content` array: a discriminated union keeps provider payloads typed.
ContentPart = Annotated[TextPart | ImagePart, Field(discriminator="type")]


class Message(BaseModel):
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
MAX_LORE_ENTRIES = 200
LORE_ID = r"^[0-9a-f]{32}$"


class LoreEntry(BaseModel):
    id: str = Field(pattern=LORE_ID)
    name: str = Field(min_length=1, max_length=80)
    # Any one of these words appearing in recent messages pulls the entry into the prompt.
    keys: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(default=[], max_length=20)
    content: str = Field(default="", max_length=5000)
    enabled: bool = True


class Usage(BaseModel):
    prompt_tokens: int = Field(ge=0)


class Chat(BaseModel):
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


class ChatSummary(BaseModel):
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


class Profile(BaseModel):
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

    @model_validator(mode="before")
    @classmethod
    def _default_vision(cls, data):
        # Profiles saved before this field existed: Grok models read images, so an
        # existing xAI profile should not need switching on by hand.
        if isinstance(data, dict) and "vision" not in data:
            host = urlsplit(str(data.get("base_url", ""))).hostname
            if host == "api.x.ai":
                return {**data, "vision": True}
        return data


class ProfileStore(BaseModel):
    active: str | None = None
    profiles: list[Profile] = []


class ProfileView(Profile):
    configured: bool
    last4: str | None = None
    source: Literal["keychain", "env"] | None = None


class ProfileList(BaseModel):
    active: str | None
    profiles: list[ProfileView]


class NewProfile(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    base_url: str
    model: str = Field(min_length=1, max_length=120)
    needs_key: bool = True
    vision: bool = False
    context_window: int | None = Field(default=None, ge=1000)
    key: SecretStr | None = None

    _url = field_validator("base_url")(lambda cls, v: clean_base_url(v))


class EditProfile(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    base_url: str | None = None
    model: str | None = Field(default=None, min_length=1, max_length=120)
    vision: bool | None = None
    context_window: int | None = Field(default=None, ge=1000)
    key: SecretStr | None = None

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return None if v is None else clean_base_url(v)


class ModelsQuery(BaseModel):
    profile_id: str | None = None
    base_url: str | None = None
    key: SecretStr | None = None
    needs_key: bool = True

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return None if v is None else clean_base_url(v)


class NewMessage(BaseModel):
    content: str = ""
    images: list[ImageData] = Field(default=[], max_length=MAX_IMAGES)
    web: bool = False

    @model_validator(mode="after")
    def _not_empty(self) -> "NewMessage":
        if not self.content.strip() and not self.images:
            raise ValueError("Write a message or attach an image")
        return self


class WebKey(BaseModel):
    key: SecretStr = Field(min_length=1, max_length=512)


class WebStatus(BaseModel):
    configured: bool
    last4: str | None = None


class RenameChat(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class StoryUpdate(BaseModel):
    bible: str = Field(default="", max_length=MAX_BIBLE_CHARS)
    lore: list[LoreEntry] = Field(default=[], max_length=MAX_LORE_ENTRIES)


class SummaryUpdate(BaseModel):
    summary: str = Field(max_length=MAX_SUMMARY_CHARS)
    summary_upto: int = Field(ge=0)


class SummaryProposal(BaseModel):
    summary: str
    summary_upto: int


class ContextParts(BaseModel):
    system: int
    bible: int
    lore: int
    summary: int
    history: int


class ContextInfo(BaseModel):
    used: int
    window: int | None
    source: Literal["provider", "estimate"]
    parts: ContextParts
