import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

# Must be set before `server` is imported: Settings() is read at import time.
os.environ["DOLPHINLLM_API_KEY"] = "test-key"
os.environ["DOLPHINLLM_DATA_DIR"] = tempfile.mkdtemp(prefix="dolphin-test-")
os.environ["DOLPHINLLM_PROFILES_FILE"] = os.path.join(tempfile.mkdtemp(prefix="dolphin-profiles-"), "profiles.json")

import keyring  # noqa: E402
import server  # noqa: E402
from keyring.backend import KeyringBackend  # noqa: E402
from keyring.errors import PasswordDeleteError  # noqa: E402
from openai import OpenAIError  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class MemoryKeyring(KeyringBackend):
    """Keeps tests away from the real macOS Keychain."""

    priority = 1

    def __init__(self):
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        if self.store.pop((service, username), None) is None:
            raise PasswordDeleteError("not found")


@pytest.fixture(autouse=True)
def memory_keyring():
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend


@pytest.fixture(autouse=True)
def clean_data_dir():
    Path(os.environ["DOLPHINLLM_PROFILES_FILE"]).unlink(missing_ok=True)
    yield
    for f in Path(os.environ["DOLPHINLLM_DATA_DIR"]).glob("*.json"):
        f.unlink()


@pytest.fixture(scope="session", autouse=True)
def remove_tmp_dir():
    yield
    shutil.rmtree(os.environ["DOLPHINLLM_DATA_DIR"], ignore_errors=True)


REPLY_PIECES = ["Hi *waves* ", "[[key]]x[[/key]]"]


class FakeStream:
    """Stands in for the OpenAI stream: yields chunks, then optionally fails."""

    def __init__(self, pieces, error=None):
        self.pieces = list(pieces)
        self.error = error
        self.closed = False

    def __iter__(self):
        for text in self.pieces:
            delta = SimpleNamespace(content=text)
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])
        if self.error:
            raise OpenAIError(self.error)

    def close(self):
        self.closed = True


class FakeClient:
    def __init__(self, create=None, models=None):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))
        self.models = SimpleNamespace(list=models)


@pytest.fixture
def fake_client(monkeypatch):
    """Installs a FakeClient as the server's OpenAI client and returns it for tweaking."""
    client = FakeClient()
    monkeypatch.setattr(server, "get_client", lambda profile: client)
    return client


@pytest.fixture
def calls(fake_client):
    seen = []

    def fake_create(model, messages, stream):
        assert stream is True
        seen.append(messages)
        return FakeStream(REPLY_PIECES)

    fake_client.chat.completions.create = fake_create
    return seen


ORIGIN = "http://localhost:8000"


@pytest.fixture
def api():
    return TestClient(server.app, base_url=ORIGIN, headers={"Origin": ORIGIN})
