import pytest
from fastapi.testclient import TestClient

import e2e
import profile_store
import secret_store
import server
from app import runtime, providers


@pytest.fixture
def e2e_env(monkeypatch, tmp_path):
    monkeypatch.setenv(e2e.UPSTREAM_VAR, "http://127.0.0.1:8765/v1")
    monkeypatch.setenv(e2e.DATA_DIR_VAR, str(tmp_path))

    def boom(*a, **k):
        raise AssertionError("keychain touched in e2e mode")

    for name in ("get_password", "set_password", "delete_password"):
        monkeypatch.setattr(secret_store.keyring, name, boom)
    return tmp_path


def test_uses_stub_profile_with_dummy_key(e2e_env):
    profile = providers.active_profile()
    assert profile.base_url == "http://127.0.0.1:8765/v1"
    assert providers.profile_key(profile) == e2e.DUMMY_KEY
    assert providers.get_client(profile).base_url.host == "127.0.0.1"


def test_profiles_api_never_touches_keychain_or_profiles_file(e2e_env, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("profiles.json accessed in e2e mode")

    monkeypatch.setattr(runtime.settings, "profiles_file", e2e_env / "profiles.json")
    for name in ("read_text", "write_text", "replace"):
        monkeypatch.setattr(type(e2e_env), name, boom)
    client = TestClient(server.app, base_url="http://localhost:8000", headers={"Origin": "http://localhost:8000"})
    listed = client.get("/api/profiles")
    assert listed.status_code == 200 and listed.json()["active"] == e2e.PROFILE_ID
    assert client.post("/api/profiles", json={"name": "x", "base_url": "https://a.example/v1", "model": "m", "key": "sk-secret"}).status_code == 201
    profile_store.save_store(runtime.settings, profile_store.load_store(runtime.settings))
    assert secret_store.get_key() is None
    assert not (e2e_env / "profiles.json").exists()


def test_data_dir_required(monkeypatch):
    monkeypatch.setenv(e2e.UPSTREAM_VAR, "http://127.0.0.1:8765/v1")
    monkeypatch.delenv(e2e.DATA_DIR_VAR, raising=False)
    with pytest.raises(RuntimeError, match="LUMIO_E2E_DATA_DIR"):
        e2e.data_dir()


def test_import_refuses_without_data_dir(monkeypatch):
    import subprocess, sys
    from pathlib import Path

    env = {"PATH": "/usr/bin", "LUMIO_E2E_UPSTREAM": "http://x/v1", "DOLPHINLLM_DATA_DIR": "/nonexistent-ignored"}
    r = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {str(Path(server.__file__).parent)!r}); import server"], cwd=Path(server.__file__).parent, env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "LUMIO_E2E_DATA_DIR" in r.stderr


def test_off_by_default(monkeypatch):
    monkeypatch.delenv(e2e.UPSTREAM_VAR, raising=False)
    assert not e2e.enabled()
