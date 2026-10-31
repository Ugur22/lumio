"""Every /api route answers 401 without a session cookie when deployed. The real current_user runs here (no override)."""

import pytest
from fastapi.testclient import TestClient

import server
from app import auth, runtime

HOST = "lumio.example.com"
ORIGIN = f"https://{HOST}"
METHODS = {"get", "post", "put", "patch", "delete"}
# The only routes a stranger may call: they create or end a session, so they cannot require one.
OPEN = {("POST", "/api/auth/register"), ("POST", "/api/auth/login"), ("POST", "/api/auth/logout")}


def api_routes():
    schema = server.app.openapi()
    return sorted((m.upper(), path) for path, item in schema["paths"].items() if path.startswith("/api/") for m in item if m in METHODS)


@pytest.fixture
def stranger(monkeypatch):
    assert auth.current_user not in server.app.dependency_overrides
    monkeypatch.setattr(runtime.settings, "public_host", HOST)
    return TestClient(server.app, base_url=ORIGIN, headers={"Origin": ORIGIN})


def fill(path):
    # 32 hex characters satisfies the chat id and the profile id patterns alike.
    return path.replace("{chat_id}", "a" * 32).replace("{profile_id}", "a" * 8).replace("{image_id}", "a" * 32)


def test_the_sweep_sees_the_whole_api():
    routes = api_routes()

    assert len(routes) >= 25
    assert OPEN <= set(routes)  # a renamed open route must not silently leave the allow-list
    for needle in ("/api/profiles", "/api/profiles/models", "/api/web/key", "/api/chats", "/api/auth/me", "/api/auth/password"):
        assert any(p == needle for _, p in routes), needle


@pytest.mark.parametrize("method,path", api_routes())
def test_every_api_route_needs_a_session(stranger, method, path):
    assert "{" not in fill(path), f"unfilled path parameter in {path}"

    res = stranger.request(method, fill(path), json={} if method not in ("GET", "DELETE") else None)

    if (method, path) in OPEN:
        assert res.status_code != 401
    else:
        assert res.status_code == 401, f"{method} {path} answered {res.status_code} without a session"
