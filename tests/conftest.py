import ipaddress
import os
import shutil
import socket
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

# Must be set before `server` is imported: Settings() is read at import time.
os.environ["DOLPHINLLM_API_KEY"] = "test-key"
os.environ["DOLPHINLLM_DATA_DIR"] = tempfile.mkdtemp(prefix="dolphin-test-")
os.environ["DOLPHINLLM_PROFILES_FILE"] = os.path.join(tempfile.mkdtemp(prefix="dolphin-profiles-"), "profiles.json")

# Tests that point DOLPHINLLM_SECRETS_FILE at a file set the master key themselves (see MASTER_KEY): a server-only
# setting in the global environment would make the app refuse to start without DOLPHINLLM_PUBLIC_HOST.
MASTER_KEY = "dGVzdC1tYXN0ZXIta2V5LXRlc3QtbWFzdGVyLWtleTA="

import keyring  # noqa: E402
import server  # noqa: E402
from app import runtime, providers
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


PUBLIC_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    """Offline DNS for the checks that resolve provider and page URLs: names map to this table (default: a public
    address); IP literals resolve to themselves. Tests add entries to point a name somewhere internal."""
    table = {"localhost": "127.0.0.1"}
    real = socket.getaddrinfo

    def getaddrinfo(host, port, *args, **kwargs):
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table.get(host, PUBLIC_IP), port or 0))]
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return table


@pytest.fixture
def master_key(monkeypatch):
    monkeypatch.setenv("DOLPHINLLM_SECRET_KEY", MASTER_KEY)
    return MASTER_KEY


@pytest.fixture(autouse=True)
def memory_keyring():
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend


@pytest.fixture(autouse=True)
def clean_data_dir():
    profiles_file = Path(os.environ["DOLPHINLLM_PROFILES_FILE"])
    profiles_file.unlink(missing_ok=True)
    shutil.rmtree(profiles_file.parent / "profiles", ignore_errors=True)  # other users' stores
    yield
    data = Path(os.environ["DOLPHINLLM_DATA_DIR"])
    with runtime.db._tx() as conn:
        conn.execute("DELETE FROM chats")  # messages and generation leases cascade
    shutil.rmtree(data / "images", ignore_errors=True)


@pytest.fixture(autouse=True)
def reset_stream_options():
    providers._no_stream_options.clear()
    yield
    providers._no_stream_options.clear()


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
    def __init__(self, create=None, models=None, generate=None):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))
        self.models = SimpleNamespace(list=models)
        self.images = SimpleNamespace(generate=generate)


@pytest.fixture
def fake_client(monkeypatch):
    """Installs a FakeClient as the server's OpenAI client and returns it for tweaking."""
    client = FakeClient()
    monkeypatch.setattr(providers, "get_client", lambda profile, user: client)
    return client


@pytest.fixture
def calls(fake_client):
    seen = []

    def fake_create(model, messages, stream, **kw):
        assert stream is True
        seen.append(messages)
        return FakeStream(REPLY_PIECES)

    fake_client.chat.completions.create = fake_create
    return seen


ORIGIN = "http://localhost:8000"


@pytest.fixture
def api():
    return TestClient(server.app, base_url=ORIGIN, headers={"Origin": ORIGIN})
