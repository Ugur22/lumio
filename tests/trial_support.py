"""Shared fakes, fixtures and helpers for the trial tests. Nothing here uses a real key: the "trial key" is a recognisable string that must never come back out of the server."""

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from argon2 import PasswordHasher
from conftest import FakeStream, REPLY_PIECES
from fastapi.testclient import TestClient
from pydantic import SecretStr

import accounts
import server
from app import providers, routes_auth, routes_oauth, runtime
from conftest import sse_blocks


HOST = "lumio.example.com"


ORIGIN = f"https://{HOST}"


TRIAL_KEY = "sk-trial-OPERATOR-SECRET-0123456789"


PEPPER = "a-long-test-pepper-0123456789"


GOOGLE_SECRET = "google-client-secret-XYZ"


GITHUB_SECRET = "github-client-secret-XYZ"


ENDED = "Your free trial has ended. Add your own provider to continue."


# --- fixtures -------------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(accounts, "hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))
    accounts._dummy_hash.cache_clear()
    providers._clients.clear()
    yield
    with runtime.db._tx() as conn:
        for table in ("users", "invites", "login_attempts", "trial_anchors", "trial_usage"):  # sessions, identities, trials cascade
            conn.execute(f"DELETE FROM {table}")
    accounts._dummy_hash.cache_clear()
    providers._clients.clear()


@pytest.fixture
def trial_on(monkeypatch):
    s = runtime.settings
    for name, value in {
        "public_host": HOST,
        "open_signup": True,
        "trial_api_key": SecretStr(TRIAL_KEY),
        "oauth_pepper": SecretStr(PEPPER),
        "oauth_google_client_id": "google-client-id",
        "oauth_google_client_secret": SecretStr(GOOGLE_SECRET),
        "oauth_github_client_id": "github-client-id",
        "oauth_github_client_secret": SecretStr(GITHUB_SECRET),
        "trial_base_url": "https://api.deepseek.com",
        "trial_model": "deepseek-flash",
        "trial_calls": 5,
        "trial_daily_calls": 150,
        "trial_reserved_share": 0.7,
        "public_base_url": None,
    }.items():
        monkeypatch.setattr(s, name, value)
    assert s.trial_enabled
    return s


class Idp:
    """Google and GitHub in one MockTransport. `people` maps an authorization code to what the provider would say."""

    HOSTS = {"oauth2.googleapis.com", "openidconnect.googleapis.com", "github.com", "api.github.com"}

    def __init__(self):
        self.people: dict[str, dict] = {}
        self.requests: list[httpx2.Request] = []
        self.token_forms: list[dict] = []
        self.redirect_token = False

    def google(self, code, sub="sub-alice", email="alice@example.com", verified=True):
        self.people[code] = {"userinfo": {"sub": sub, "email": email, "email_verified": verified}}

    def github(self, code, uid=4242, email="bob@example.com", created="2015-01-01T00:00:00Z", verified=True, primary=True):
        self.people[code] = {
            "user": {"id": uid, "created_at": created},
            "emails": [{"email": "noise@example.com", "primary": False, "verified": True}, {"email": email, "primary": primary, "verified": verified}],
        }

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        assert request.url.host in self.HOSTS, f"unexpected host {request.url.host}"
        path = request.url.path
        if request.method == "POST":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_forms.append(form)
            if self.redirect_token:
                return httpx2.Response(302, headers={"location": "https://evil.example/steal"})
            if form["code"] not in self.people:
                return httpx2.Response(400, json={"error": "bad_verification_code"})
            return httpx2.Response(200, json={"access_token": "at-" + form["code"]})
        code = request.headers["authorization"].removeprefix("Bearer at-")
        person = self.people[code]
        if path.endswith("/userinfo"):
            return httpx2.Response(200, json=person["userinfo"])
        if path == "/user":
            return httpx2.Response(200, json=person["user"])
        return httpx2.Response(200, json=person["emails"])


@pytest.fixture
def idp(monkeypatch, trial_on):
    fake = Idp()
    monkeypatch.setattr(routes_oauth, "http_client", lambda: httpx2.Client(transport=httpx2.MockTransport(fake), follow_redirects=False))
    return fake


class Net:
    """The caller's address as the app sees it; unique per sign-in unless a test sets `ip`."""

    def __init__(self):
        self.ip: str | None = None
        self.n = 0

    def __call__(self, request):
        if self.ip:
            return self.ip
        self.n += 1
        return f"10.1.{self.n // 250}.{self.n % 250 + 1}"


@pytest.fixture(autouse=True)
def net(monkeypatch):
    fake = Net()
    monkeypatch.setattr(routes_auth, "client_ip", fake)
    return fake


def browser(**kw) -> TestClient:
    return TestClient(server.app, base_url=ORIGIN, headers={"Origin": ORIGIN}, **kw)


def begin(client, provider="google"):
    res = client.get(f"/api/auth/oauth/{provider}/start", follow_redirects=False)
    assert res.status_code == 302
    return res, parse_qs(urlparse(res.headers["location"]).query)


def sign_in(idp, code, provider="google", client=None, **person):
    """The whole round trip. Returns (client, callback response)."""
    getattr(idp, provider)(code, **person)
    client = client or browser()
    _, query = begin(client, provider)
    res = client.get(f"/api/auth/oauth/{provider}/callback", params={"code": code, "state": query["state"][0]}, follow_redirects=False)
    return client, res


def error_of(res):
    assert res.status_code == 302
    return parse_qs(urlparse(res.headers["location"]).query).get("auth_error", [None])[0]


def session_of(client) -> str:
    return client.cookies.get("lumio_session")


def trial_client(idp, name="alice", **kw):
    client, res = sign_in(idp, f"code-{name}", sub=f"sub-{name}", email=f"{name}@example.com", **kw)
    assert res.headers["location"] == "/", res.headers["location"]
    return client


def events(res):
    out = []
    for block in sse_blocks(res.text):
        name, data = block.split("\n", 1)
        out.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def trial_row(client):
    me = client.get("/api/auth/me").json()
    return runtime.db.get_trial(me["id"])


@pytest.fixture
def model(fake_client):
    """A recording stand-in for the trial's model."""
    rec = SimpleNamespace(calls=[], pieces=list(REPLY_PIECES), open_error=None, stream_error=None)

    def create(model, messages, stream, **kw):
        rec.calls.append({"model": model, "messages": messages, **kw})
        if rec.open_error:
            raise rec.open_error
        return FakeStream(rec.pieces, error=rec.stream_error)

    fake_client.chat.completions.create = create
    return rec


def new_chat(client):
    res = client.post("/api/chats")
    assert res.status_code == 201
    return res.json()["id"]


def send(client, chat_id, content="hello", **extra):
    return client.post(f"/api/chats/{chat_id}/messages", json={"content": content, **extra})


def use_up(client, n=5):
    me = client.get("/api/auth/me").json()
    for _ in range(n):
        runtime.db.reserve_trial_call(me["id"], 10_000)
