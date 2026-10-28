from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).parent
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


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


class Source(BaseModel):
    url: str
    title: str = ""
    text: str


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created: datetime = Field(default_factory=utcnow)
    # Web pages the reply was based on; kept on the user message so later turns can reuse them.
    sources: list[Source] = []


class Chat(BaseModel):
    id: str
    title: str = "New chat"
    created: datetime = Field(default_factory=utcnow)
    updated: datetime = Field(default_factory=utcnow)
    messages: list[Message] = []


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
    key: SecretStr | None = None

    _url = field_validator("base_url")(lambda cls, v: clean_base_url(v))


class EditProfile(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    base_url: str | None = None
    model: str | None = Field(default=None, min_length=1, max_length=120)
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
    content: str = Field(min_length=1)
    web: bool = False


class WebKey(BaseModel):
    key: SecretStr = Field(min_length=1, max_length=512)


class WebStatus(BaseModel):
    configured: bool
    last4: str | None = None


class RenameChat(BaseModel):
    title: str = Field(min_length=1, max_length=100)
