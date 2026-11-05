"""Free trial: OAuth sign-in, the identity tombstones, the quota and every restriction that comes with it.

The identity providers are faked by an httpx2 MockTransport (no network), the model by FakeStream or the fake upstream.
Nothing here uses a real key: the "trial key" is a recognisable string that must never come back out of the server."""

import asyncio
import base64
import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from argon2 import PasswordHasher
from conftest import FakeStream, REPLY_PIECES
from fake_upstream import app as upstream_app
from fastapi.testclient import TestClient
from openai import OpenAIError
from pydantic import SecretStr

import accounts
import profile_store
import server
import storage
from app import anchors, providers, routes_auth, routes_oauth, routes_profiles, runtime, story, streaming
from models import ProfileView, Settings, UserView

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
    for block in res.text.strip().split("\n\n"):
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


# --- sign-in -------------------------------------------------------------------------------------------------


def test_start_redirects_to_google_with_pkce_state_and_a_signed_httponly_cookie(idp):
    client = browser()
    res, q = begin(client)

    assert res.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert q["response_type"] == ["code"] and q["code_challenge_method"] == ["S256"]
    assert q["client_id"] == ["google-client-id"]
    assert q["redirect_uri"] == [f"{ORIGIN}/api/auth/oauth/google/callback"]
    assert GOOGLE_SECRET not in res.headers["location"]
    cookie = res.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "secure" in cookie
    assert routes_oauth.unpack_state(client.cookies.get("lumio_oauth"))["s"] == q["state"][0]


def test_github_start_requests_the_email_scope(idp):
    _, q = begin(browser(), "github")

    assert q["scope"] == ["read:user user:email"] and q["code_challenge_method"] == ["S256"]


def test_the_code_is_exchanged_with_the_verifier_that_matches_the_challenge(idp):
    client = browser()
    idp.google("c1")
    _, q = begin(client)
    client.get("/api/auth/oauth/google/callback", params={"code": "c1", "state": q["state"][0]}, follow_redirects=False)

    (form,) = idp.token_forms
    digest = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert digest == q["code_challenge"][0]
    assert form["client_secret"] == GOOGLE_SECRET and form["redirect_uri"] == q["redirect_uri"][0]


def test_a_new_google_sign_in_creates_a_passwordless_account_with_a_trial(idp):
    client, res = sign_in(idp, "c1")

    assert res.status_code == 302 and res.headers["location"] == "/"
    me = client.get("/api/auth/me").json()
    assert me["username"].startswith("user-") and me["is_admin"] is False
    assert client.get("/api/trial").json() == {"enrolled": True, "limit": 5, "used": 0, "remaining": 5, "ended": False}
    assert runtime.db.get_account(me["username"]).password_hash == storage.UNUSABLE_PASSWORD
    with runtime.db._read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM identities").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM trial_anchors").fetchone()[0] == 2
        dump = "\n".join(conn.iterdump())
    assert "alice@example.com" not in dump and "sub-alice" not in dump  # only keyed hashes are stored


def test_signing_in_again_logs_into_the_same_account_without_a_second_trial(idp):
    first, _ = sign_in(idp, "c1")
    uid = first.get("/api/auth/me").json()["id"]
    use_up(first, 2)

    second, res = sign_in(idp, "c1")

    assert res.headers["location"] == "/"
    assert second.get("/api/auth/me").json()["id"] == uid
    assert second.get("/api/trial").json()["used"] == 2
    with runtime.db._read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_same_email_through_github_after_google_gets_no_second_trial(idp):
    sign_in(idp, "c1", email="Alice@Example.com")

    client, res = sign_in(idp, "c2", provider="github", uid=77, email="alice@example.com")

    assert error_of(res) == "trial_used"
    assert client.get("/api/auth/me").status_code == 200  # signed in, only without a trial
    assert client.get("/api/trial").json()["enrolled"] is False


@pytest.mark.parametrize("second", ["a.l.i.c.e@gmail.com", "alice+news@gmail.com", "ALICE@googlemail.com"])
def test_gmail_dots_tags_and_googlemail_are_one_mailbox(idp, second):
    sign_in(idp, "c1", sub="s1", email="alice@gmail.com")

    _, res = sign_in(idp, "c2", sub="s2", email=second)

    assert error_of(res) == "trial_used"


def test_a_different_person_still_gets_a_trial(idp):
    sign_in(idp, "c1")
    client, res = sign_in(idp, "c2", sub="sub-carol", email="carol@example.com")

    assert res.headers["location"] == "/" and client.get("/api/trial").json()["enrolled"] is True


def test_the_tombstone_outlives_the_account(idp):
    first, _ = sign_in(idp, "c1")
    uid = first.get("/api/auth/me").json()["id"]
    with runtime.db._tx() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (uid,))  # what deleting an account does
    with runtime.db._read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM identities").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM trials").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM trial_anchors").fetchone()[0] == 2
        assert "user_id" not in [r["name"] for r in conn.execute("PRAGMA table_info(trial_anchors)")]

    again, res = sign_in(idp, "c1")

    assert error_of(res) == "trial_used"
    assert again.get("/api/auth/me").json()["id"] != uid
    assert again.get("/api/trial").json()["enrolled"] is False


def test_anchors_are_purged_after_eighteen_months():
    db = runtime.db
    old = datetime.now(timezone.utc) - timedelta(days=storage.ANCHOR_DAYS + 1)
    kw = {"trial_calls": 5, "ip_key": "signup:ip:t", "ip_limit": 100, "day_limit": 1000}
    a = [("email", "anchor-1")]
    _, granted = db.enrol_oauth_user("google", "s-old", a, now=old, **kw)
    assert granted is True
    _, again = db.enrol_oauth_user("google", "s-new", a, now=old + timedelta(days=1), **kw)
    assert again is False

    _, later = db.enrol_oauth_user("google", "s-later", a, **kw)  # the first sighting has expired by now

    assert later is True


def test_disposable_email_domains_are_refused_and_create_nothing(idp):
    client, res = sign_in(idp, "c1", email="x@Mailinator.com")

    assert error_of(res) == "disposable"
    assert client.get("/api/auth/me").status_code == 401
    with runtime.db._read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_google_needs_a_verified_email(idp):
    client, res = sign_in(idp, "c1", verified=False)

    assert error_of(res) == "unverified" and client.get("/api/auth/me").status_code == 401


def test_github_needs_an_old_enough_account_and_a_primary_verified_email(idp):
    young = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    assert error_of(sign_in(idp, "c1", "github", uid=1, created=young)[1]) == "too_new"
    assert error_of(sign_in(idp, "c2", "github", uid=2, verified=False)[1]) == "unverified"
    assert error_of(sign_in(idp, "c3", "github", uid=3, primary=False)[1]) == "unverified"
    ok, res = sign_in(idp, "c4", "github", uid=4)
    assert res.headers["location"] == "/" and ok.get("/api/trial").json()["enrolled"] is True
    with runtime.db._read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_github_ids_must_be_numbers(idp):
    idp.github("c1")
    idp.people["c1"]["user"]["id"] = "4242"
    client = browser()
    _, q = begin(client, "github")

    res = client.get("/api/auth/oauth/github/callback", params={"code": "c1", "state": q["state"][0]}, follow_redirects=False)

    assert error_of(res) == "provider"


def test_a_state_that_does_not_match_is_rejected_before_the_code_is_used(idp):
    idp.google("c1")
    client = browser()
    begin(client)

    res = client.get("/api/auth/oauth/google/callback", params={"code": "c1", "state": "not-the-state"}, follow_redirects=False)

    assert error_of(res) == "state" and idp.requests == []


def test_a_callback_without_the_cookie_is_rejected(idp):
    idp.google("c1")
    _, q = begin(browser())

    res = browser().get("/api/auth/oauth/google/callback", params={"code": "c1", "state": q["state"][0]}, follow_redirects=False)

    assert error_of(res) == "state" and idp.requests == []


def test_a_state_cookie_from_the_other_provider_or_forged_or_expired_is_rejected(idp):
    idp.google("c1")
    client = browser()
    _, q = begin(client, "github")  # started at GitHub, finished at Google

    res = client.get("/api/auth/oauth/google/callback", params={"code": "c1", "state": q["state"][0]}, follow_redirects=False)
    assert error_of(res) == "state"

    good = routes_oauth.pack_state({"p": "google", "s": "x", "v": "v", "exp": 9e12})
    assert routes_oauth.unpack_state(good)["s"] == "x"
    assert routes_oauth.unpack_state(good[:-1] + ("0" if good[-1] != "0" else "1")) is None
    assert routes_oauth.unpack_state(routes_oauth.pack_state({"p": "google", "s": "x", "v": "v", "exp": 1})) is None
    assert routes_oauth.unpack_state("garbage") is None and routes_oauth.unpack_state(None) is None


def test_a_provider_error_or_missing_code_ends_cleanly(idp):
    client = browser()
    _, q = begin(client)

    res = client.get("/api/auth/oauth/google/callback", params={"error": "access_denied", "state": q["state"][0]}, follow_redirects=False)

    assert error_of(res) == "denied"


def test_the_token_endpoint_redirecting_is_not_followed(idp):
    idp.redirect_token = True
    idp.google("c1")
    client = browser()
    _, q = begin(client)

    res = client.get("/api/auth/oauth/google/callback", params={"code": "c1", "state": q["state"][0]}, follow_redirects=False)

    assert error_of(res) == "provider"
    assert {r.url.host for r in idp.requests} == {"oauth2.googleapis.com"}


def test_provider_calls_have_timeouts_and_never_follow_redirects():
    client = routes_oauth.http_client()
    assert client.follow_redirects is False and client.timeout.read is not None and client.timeout.connect is not None


def test_a_rejected_code_is_a_provider_error(idp):
    client = browser()
    _, q = begin(client)

    res = client.get("/api/auth/oauth/google/callback", params={"code": "unknown", "state": q["state"][0]}, follow_redirects=False)

    assert error_of(res) == "provider"


def test_sign_in_is_unavailable_until_trials_are_configured(monkeypatch, idp):
    monkeypatch.setattr(runtime.settings, "open_signup", False)

    assert error_of(browser().get("/api/auth/oauth/google/start", follow_redirects=False)) == "unavailable"
    assert error_of(browser().get("/api/auth/oauth/google/callback", params={"code": "x", "state": "y"}, follow_redirects=False)) == "unavailable"
    monkeypatch.setattr(runtime.settings, "open_signup", True)
    monkeypatch.setattr(runtime.settings, "oauth_github_client_secret", None)
    assert error_of(browser().get("/api/auth/oauth/github/start", follow_redirects=False)) == "unavailable"


def test_an_unknown_provider_is_a_422(idp):
    assert browser().get("/api/auth/oauth/facebook/start", follow_redirects=False).status_code == 422


def test_a_disabled_account_cannot_sign_in_again(idp):
    first, _ = sign_in(idp, "c1")
    runtime.db.disable_user(first.get("/api/auth/me").json()["id"])

    client, res = sign_in(idp, "c1")

    assert error_of(res) == "disabled" and client.get("/api/auth/me").status_code == 401


def test_a_parallel_sign_in_that_loses_the_race_still_logs_in(idp, monkeypatch):
    sign_in(idp, "c1")
    real = runtime.db.find_identity
    calls = []

    def stale(provider, subject):
        calls.append(1)
        return None if len(calls) == 1 else real(provider, subject)  # the first look misses, as if the other request had not committed yet

    monkeypatch.setattr(runtime.db, "find_identity", stale)

    client, res = sign_in(idp, "c1")

    assert res.headers["location"] == "/" and client.get("/api/auth/me").status_code == 200
    with runtime.db._read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


# --- passwordless accounts --------------------------------------------------------------------------------------


@pytest.mark.parametrize("password", ["!", "x", "correct horse battery", "$argon2id$v=19$m=8,t=1,p=1$AAAA$AAAA"])
def test_a_provider_account_cannot_log_in_with_a_password(idp, password):
    client, _ = sign_in(idp, "c1")
    username = client.get("/api/auth/me").json()["username"]

    for route in ("/api/auth/login", "/api/auth/token"):
        res = browser().post(route, json={"username": username, "password": password})
        assert res.status_code == 401, route
    assert not accounts.verify_password(storage.UNUSABLE_PASSWORD, password)
    assert not accounts.verify_password(storage.UNUSABLE_PASSWORD, storage.UNUSABLE_PASSWORD)


def test_a_provider_account_cannot_change_a_password_it_does_not_have(idp):
    client, _ = sign_in(idp, "c1")

    res = client.post("/api/auth/password", json={"current_password": "!", "new_password": "a brand new password"})

    assert res.status_code == 400


# --- signup throttle -----------------------------------------------------------------------------------------------


def test_three_signups_per_address_then_throttled_and_successes_are_not_credited(idp, net):
    net.ip = "203.0.113.9"
    for n in range(3):
        _, res = sign_in(idp, f"c{n}", sub=f"s{n}", email=f"p{n}@example.com")
        assert res.headers["location"] == "/"

    _, res = sign_in(idp, "c3", sub="s3", email="p3@example.com")

    assert error_of(res) == "throttled"
    net.ip = "203.0.113.10"  # another address is its own bucket
    assert sign_in(idp, "c4", sub="s4", email="p4@example.com")[1].headers["location"] == "/"
    with runtime.db._read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 4


def test_refused_attempts_do_not_use_up_the_signup_allowance(idp, net):
    net.ip = "203.0.113.20"
    for n in range(5):
        assert error_of(sign_in(idp, f"d{n}", sub=f"d{n}", email=f"x{n}@mailinator.com")[1]) == "disposable"

    assert sign_in(idp, "ok", sub="ok", email="ok@example.com")[1].headers["location"] == "/"


def test_existing_accounts_signing_in_are_not_counted_as_signups(idp, net):
    net.ip = "203.0.113.30"
    sign_in(idp, "c1")
    for _ in range(6):
        assert sign_in(idp, "c1")[1].headers["location"] == "/"


def test_ipv6_addresses_share_a_bucket_per_64(idp, net):
    for n in range(3):
        net.ip = f"2001:db8:1:2::{n + 1}"
        assert sign_in(idp, f"c{n}", sub=f"s{n}", email=f"p{n}@example.com")[1].headers["location"] == "/"

    net.ip = "2001:db8:1:2:ffff::1"  # same /64, different address
    assert error_of(sign_in(idp, "c3", sub="s3", email="p3@example.com")[1]) == "throttled"
    net.ip = "2001:db8:1:3::1"  # next /64
    assert sign_in(idp, "c4", sub="s4", email="p4@example.com")[1].headers["location"] == "/"


@pytest.mark.parametrize(
    "ip,key",
    [
        ("198.51.100.7", "signup:ip:198.51.100.7"),
        ("2001:db8:aaaa:bbbb:1:2:3:4", "signup:ip:2001:db8:aaaa:bbbb::/64"),
        ("::ffff:198.51.100.7", "signup:ip:198.51.100.7"),
    ],
)
def test_signup_ip_keys(ip, key):
    assert routes_oauth.signup_ip_key(ip) == key


def test_a_global_daily_cap_on_signups(idp, monkeypatch):
    monkeypatch.setattr(storage, "SIGNUP_PER_DAY", 2)
    assert sign_in(idp, "c0", sub="s0", email="p0@example.com")[1].headers["location"] == "/"
    assert sign_in(idp, "c1", sub="s1", email="p1@example.com")[1].headers["location"] == "/"

    assert error_of(sign_in(idp, "c2", sub="s2", email="p2@example.com")[1]) == "throttled"


def test_login_attempt_limits_take_their_own_window(idp):
    db = runtime.db
    assert db.take_login_attempt(["w"], limit=2, window=1000)[0] == 0
    assert db.take_login_attempt(["w"], limit=2, window=1000)[0] == 0
    wait, ids = db.take_login_attempt(["w"], limit=2, window=1000)
    assert 0 < wait <= 1001 and ids == []
    # A signup row (a day long) survives the 15-minute purge that login failures get.
    db.record_login_failure(["signup:keep"], now=0)
    db.take_login_attempt(["other"], now=3600)
    with db._read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM login_attempts WHERE key='signup:keep'").fetchone()[0] == 1


# --- quota ---------------------------------------------------------------------------------------------------------


def test_the_trial_profile_is_listed_as_managed_and_keyless(idp):
    client = trial_client(idp)

    res = client.get("/api/profiles")

    assert res.json()["active"] == "trial"
    (p,) = res.json()["profiles"]
    assert p | {"context_window": None} == {
        "id": "trial", "name": "Free trial", "base_url": "https://api.deepseek.com", "model": "deepseek-flash", "needs_key": True,
        "vision": False, "context_window": None, "image_model": None, "configured": True, "last4": None, "source": "server",
        "managed": True, "key_store": p["key_store"],
    }  # fmt: skip
    assert TRIAL_KEY not in res.text and not (TRIAL_KEY[-4:] in res.text)


def test_the_profile_model_has_the_managed_flag():
    assert ProfileView.model_fields["managed"].default is False
    assert "server" in json.dumps(ProfileView.model_json_schema())


def test_a_send_spends_one_call_and_reports_what_is_left(idp, model):
    client = trial_client(idp)
    chat_id = new_chat(client)
    assert client.get(f"/api/chats/{chat_id}").json()["profile_id"] == "trial"

    evs = events(send(client, chat_id))

    assert evs[-1][0] == "done" and evs[-1][1]["trial"] == {"remaining": 4}
    assert client.get("/api/trial").json() == {"enrolled": True, "limit": 5, "used": 1, "remaining": 4, "ended": False}
    assert [m["role"] for m in client.get(f"/api/chats/{chat_id}").json()["messages"]] == ["user", "assistant"]


def test_the_sixth_send_is_a_402_and_the_profile_is_gone(idp, model):
    client = trial_client(idp)
    chat_id = new_chat(client)
    for _ in range(5):
        assert send(client, chat_id).status_code == 200

    res = send(client, chat_id)

    assert res.status_code == 402 and res.json()["detail"] == ENDED
    assert len(model.calls) == 5
    assert client.get("/api/profiles").json() == {"active": None, "profiles": []}
    assert client.get("/api/trial").json() == {"enrolled": True, "limit": 5, "used": 5, "remaining": 0, "ended": True}


def test_twenty_parallel_sends_across_chats_get_exactly_five_replies(idp, model):
    client = trial_client(idp)
    token = session_of(client)
    chats = [new_chat(client) for _ in range(20)]
    barrier = threading.Barrier(20)

    def go(chat_id):
        c = TestClient(server.app, base_url=ORIGIN, headers={"Authorization": f"Bearer {token}"})
        barrier.wait()
        return c.post(f"/api/chats/{chat_id}/messages", json={"content": "hi"}).status_code

    with ThreadPoolExecutor(20) as pool:
        codes = list(pool.map(go, chats))

    assert sorted(codes) == [200] * 5 + [402] * 15
    assert len(model.calls) == 5
    assert trial_row(client).used == 5


def test_a_refused_request_consumes_nothing(idp, model):
    client = trial_client(idp)
    chat_id = new_chat(client)
    png = {"media_type": "image/png", "data": base64.b64encode(b"\x89PNG\r\n\x1a\nxx").decode()}

    assert send(client, chat_id, "x" * 4001).status_code == 422
    assert send(client, chat_id, "hi", web=True).status_code == 422
    assert send(client, chat_id, "hi", images=[png]).status_code == 422
    assert send(client, chat_id, "   ").status_code == 422

    assert trial_row(client).used == 0 and model.calls == []
    assert send(client, chat_id, "x" * 4000).status_code == 200  # the lease was released each time


def test_an_unreachable_provider_before_any_text_refunds_the_call(idp, model):
    client = trial_client(idp)
    chat_id = new_chat(client)
    model.open_error = OpenAIError("upstream is down")

    res = send(client, chat_id)

    assert res.status_code == 502 and trial_row(client).used == 0
    assert client.get(f"/api/chats/{chat_id}").json()["messages"] == []


def test_a_stream_that_fails_before_any_text_refunds_the_call(idp, model):
    client = trial_client(idp)
    model.pieces, model.stream_error = [], "connection lost"

    evs = events(send(client, new_chat(client)))

    assert evs[-1][0] == "error" and trial_row(client).used == 0


def test_a_stream_that_fails_after_text_keeps_the_call_spent(idp, model):
    client = trial_client(idp)
    model.pieces, model.stream_error = ["part of a reply"], "connection lost"

    evs = events(send(client, new_chat(client)))

    assert [n for n, _ in evs] == ["delta", "error"] and trial_row(client).used == 1


def test_an_unexpected_error_before_the_reply_refunds_the_call(idp, model, monkeypatch):
    client = trial_client(idp)

    def boom(*a, **k):
        raise RuntimeError("bug")

    monkeypatch.setattr(providers, "open_stream", boom)
    with pytest.raises(RuntimeError):
        send(client, new_chat(client))

    assert trial_row(client).used == 0


def test_stopping_a_reply_does_not_refund_it(idp):
    client = trial_client(idp)
    uid = client.get("/api/auth/me").json()["id"]
    chat = runtime.db.create_chat("trial", owner=uid)
    lease = runtime.db.acquire(chat.id, owner=uid)
    call = runtime.db.reserve_trial_call(uid, 100)

    async def run():
        gen = streaming.stream_reply(chat, "q", FakeStream(["a", "b", "c"]), [], [], lease=lease, trial_call=call)
        first = await gen.__anext__()
        await gen.aclose()  # what a disconnect or Stop does
        return first

    assert "delta" in asyncio.run(run())
    assert runtime.db.get_trial(uid).used == 1


def test_a_refund_is_given_back_once(idp):
    client = trial_client(idp)
    uid = client.get("/api/auth/me").json()["id"]
    call = runtime.db.reserve_trial_call(uid, 100)
    other = runtime.db.reserve_trial_call(uid, 100)
    assert runtime.db.get_trial(uid).used == 2

    call.refund()
    call.refund()

    assert runtime.db.get_trial(uid).used == 1 and call.refunded and not other.refunded


def test_the_daily_cap_is_shared_and_a_refund_frees_a_slot(idp, model, monkeypatch):
    monkeypatch.setattr(runtime.settings, "trial_daily_calls", 1)
    a, b = trial_client(idp, "alice"), trial_client(idp, "bob")
    model.open_error = OpenAIError("down")
    assert send(a, new_chat(a)).status_code == 502  # reserved, then refunded
    model.open_error = None

    assert send(a, new_chat(a)).status_code == 200
    full = send(b, new_chat(b))

    assert full.status_code == 503 and full.json()["detail"] == "Free trials are full today, try tomorrow"
    assert int(full.headers["retry-after"]) > 0
    assert trial_row(b).used == 0  # the refused send took nothing from bob either


def test_the_daily_cap_counts_per_utc_day(idp):
    client = trial_client(idp)
    uid = client.get("/api/auth/me").json()["id"]
    day1 = datetime(2030, 1, 1, 23, 59, tzinfo=timezone.utc)

    runtime.db.reserve_trial_call(uid, 1, now=day1)
    with pytest.raises(storage.TrialFull) as full:
        runtime.db.reserve_trial_call(uid, 1, now=day1)
    assert full.value.retry_after == 60
    runtime.db.reserve_trial_call(uid, 1, now=day1 + timedelta(minutes=2))  # past midnight UTC
    with runtime.db._read() as conn:
        assert [r["day"] for r in conn.execute("SELECT day FROM trial_usage")] == ["2030-01-02"]


def test_reserving_without_a_trial_is_refused(idp):
    with pytest.raises(storage.TrialExhausted):
        runtime.db.reserve_trial_call("nobody", 100)


# --- restrictions ----------------------------------------------------------------------------------------------------


def test_the_model_is_pinned_and_max_tokens_clamped_whatever_the_client_asks(idp, model):
    client = trial_client(idp)
    chat_id = new_chat(client)
    assert client.put(f"/api/chats/{chat_id}/model", json={"model": "gpt-expensive", "context_window": 128000}).status_code == 200
    client.put(f"/api/chats/{chat_id}/behavior", json={"max_tokens": 900_000})
    send(client, chat_id)
    client.put(f"/api/chats/{chat_id}/behavior", json={"max_tokens": 100})
    send(client, chat_id)
    client.put(f"/api/chats/{chat_id}/behavior", json={})
    send(client, chat_id)

    assert {c["model"] for c in model.calls} == {"deepseek-flash"}
    assert [c["max_tokens"] for c in model.calls] == [1500, 100, 1500]


def test_illustrate_is_ignored_for_the_trial(idp, model):
    client = trial_client(idp)

    res = send(client, new_chat(client), illustrate=True)

    assert res.status_code == 200
    assert story.ILLUSTRATE_NOTE not in model.calls[0]["messages"][0]["content"]


def test_a_long_history_is_cut_to_twenty_messages_and_the_prompt_budget(idp, model):
    client = trial_client(idp)
    uid = client.get("/api/auth/me").json()["id"]
    chat_id = new_chat(client)
    from models import Message

    runtime.db.append_messages(chat_id, [Message(role=("user" if i % 2 == 0 else "assistant"), content=f"{i}:" + "w" * 500) for i in range(60)], owner=uid)
    send(client, chat_id, "newest")

    sent = model.calls[0]["messages"]
    history = sent[1:-1]
    assert len(history) <= providers.TRIAL_HISTORY_MESSAGES and history[0]["role"] == "user"
    assert history[-1]["content"].startswith("59:") and sent[-1]["content"] == "newest"
    assert sum(len(m["content"]) for m in sent) <= providers.TRIAL_PROMPT_CHARS + 10


def test_a_prompt_over_the_budget_is_trimmed_oldest_first_and_refused_when_the_story_alone_is_too_big(idp, model, monkeypatch):
    client = trial_client(idp)
    chat_id = new_chat(client)
    send(client, chat_id, "first")
    monkeypatch.setattr(providers, "TRIAL_PROMPT_CHARS", 20_000)
    big = {"bible": "b" * 19_000, "lore": []}
    assert client.put(f"/api/chats/{chat_id}/story", json=big).status_code == 200

    res = send(client, chat_id, "x" * 3000)

    assert res.status_code == 422 and trial_row(client).used == 1


def test_summaries_are_blocked(idp, model):
    client = trial_client(idp)
    uid = client.get("/api/auth/me").json()["id"]
    chat_id = new_chat(client)
    from models import Message

    runtime.db.append_messages(chat_id, [Message(role="user", content="m") for _ in range(12)], owner=uid)

    assert client.post(f"/api/chats/{chat_id}/summarize").status_code == 403


def test_at_most_fifty_chats(idp):
    client = trial_client(idp)
    for _ in range(providers.TRIAL_MAX_CHATS):
        new_chat(client)

    assert client.post("/api/chats").status_code == 403


def test_own_providers_unlock_only_after_the_trial(idp, model, monkeypatch):
    client = trial_client(idp)
    body = {"name": "Mine", "base_url": "https://api.example.com/v1", "model": "m", "key": "sk-mine-0123456789ab"}

    assert client.post("/api/profiles", json=body).json()["detail"] == "Adding your own provider unlocks when your free trial ends"
    assert client.post("/api/profiles/models", json={"base_url": "https://api.example.com/v1", "key": "k"}).status_code == 403
    assert client.put("/api/web/key", json={"key": "tvly-0123456789abcdef"}).status_code == 403
    assert client.delete("/api/web/key").status_code == 200  # removing is harmless

    use_up(client)

    class FakeSdk:
        def __init__(self, **kw):
            self.models = SimpleNamespace(list=lambda: [SimpleNamespace(id="m1")])

        def close(self):
            pass

    monkeypatch.setattr(routes_profiles, "OpenAI", FakeSdk)
    assert client.post("/api/profiles", json=body).status_code == 201
    assert client.post("/api/profiles/models", json={"base_url": "https://api.example.com/v1", "key": "k"}).json() == {"models": ["m1"], "context_windows": None}
    assert client.put("/api/web/key", json={"key": "tvly-0123456789abcdef"}).status_code == 200


def test_a_trial_that_was_switched_off_unlocks_providers_and_hides_the_profile(idp, monkeypatch):
    client = trial_client(idp)
    monkeypatch.setattr(runtime.settings, "open_signup", False)

    assert client.get("/api/profiles").json()["profiles"] == []
    assert client.get("/api/trial").json()["ended"] is True
    assert client.put("/api/web/key", json={"key": "tvly-0123456789abcdef"}).status_code == 200


def test_a_chat_pinned_to_the_trial_falls_back_to_the_users_own_provider_afterwards(idp, model, monkeypatch):
    client = trial_client(idp)
    chat_id = new_chat(client)
    send(client, chat_id)
    use_up(client, 4)
    assert send(client, chat_id).status_code == 402 and ENDED in send(client, chat_id).text
    monkeypatch.setattr(routes_profiles, "OpenAI", lambda **kw: SimpleNamespace(close=lambda: None))
    client.post("/api/profiles", json={"name": "Mine", "base_url": "https://api.example.com/v1", "model": "my-model", "key": "sk-mine-0123456789ab"})

    res = send(client, chat_id)

    assert res.status_code == 200
    assert model.calls[-1]["model"] == "my-model"


def test_the_trial_cannot_be_forged_by_a_user_without_one(idp, model):
    client = trial_client(idp)
    stranger = browser()
    assert stranger.get("/api/trial").status_code == 401
    other, _ = sign_in(idp, "c-other", sub="sub-other", email="other@example.com")
    use_up(other)
    chat_id = new_chat(other)
    other.put(f"/api/chats/{chat_id}/behavior", json={"profile_id": "trial"})  # not in their store any more: 404

    assert other.put(f"/api/chats/{chat_id}/behavior", json={"profile_id": "trial"}).status_code == 404
    assert send(other, chat_id).status_code == 402
    assert client.get("/api/trial").json()["used"] == 0


def test_a_stored_profile_called_trial_gets_no_server_key(idp, monkeypatch):
    from models import Profile

    plain = Profile(id="trial", name="Mine", base_url="https://api.example.com/v1", model="m")

    assert not providers.is_trial(plain)
    assert providers.profile_key(plain, UserView(id="a" * 32, username="x", is_admin=False)) is None


# --- the key never leaves ----------------------------------------------------------------------------------------------


def test_the_client_talks_to_the_provider_with_the_trial_key_and_nothing_else_carries_it(idp, caplog, monkeypatch):
    import logging

    seen = []

    class Spy:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            body = []

            async def tap():
                message = await receive()
                body.append(message.get("body", b""))
                return message

            if scope["type"] == "http":
                seen.append({"auth": dict(scope["headers"]).get(b"authorization", b"").decode(), "body": body})
            await self.app(scope, tap, send)

    monkeypatch.setattr(runtime.settings, "trial_base_url", "https://fake-upstream.test/v1")
    monkeypatch.setattr(providers, "client_options", lambda: {"http_client": TestClient(Spy(upstream_app)), "max_retries": 0})
    caplog.set_level(logging.DEBUG, logger="dolphinllm")
    client = trial_client(idp)
    chat_id = new_chat(client)

    collected = [send(client, chat_id, "hello").text]
    collected += [send(client, chat_id, "boom [[fake:error]]").text]
    for path in ("/api/profiles", "/api/trial", "/api/auth/me", "/api/chats", f"/api/chats/{chat_id}", f"/api/chats/{chat_id}/context"):
        collected.append(client.get(path).text)
    collected.append(client.post("/api/profiles", json={"name": "x", "base_url": "https://a.example/v1", "model": "m"}).text)

    assert seen[0]["auth"] == f"Bearer {TRIAL_KEY}"
    sent = json.loads(b"".join(seen[0]["body"]))
    assert sent["model"] == "deepseek-flash" and sent["max_tokens"] == 1500
    blob = "\n".join(collected) + caplog.text
    for secret in (TRIAL_KEY, PEPPER, GOOGLE_SECRET, GITHUB_SECRET, "at-code-alice", "code-alice"):
        assert secret not in blob, secret


def test_error_text_from_the_provider_is_redacted(idp, model):
    client = trial_client(idp)
    chat_id = new_chat(client)
    model.open_error = OpenAIError(f"Incorrect API key provided: {TRIAL_KEY}")
    refused = send(client, chat_id)
    model.open_error = None
    model.pieces, model.stream_error = [], f"401 for Bearer {TRIAL_KEY}"
    streamed = send(client, chat_id)

    assert refused.status_code == 502 and TRIAL_KEY not in refused.text and "Incorrect API key" in refused.text
    assert TRIAL_KEY not in streamed.text and "error" in streamed.text


def test_get_client_builds_the_sdk_client_from_the_server_key(idp, monkeypatch):
    built = {}

    class Sdk:
        def __init__(self, **kw):
            built.update(kw)

    monkeypatch.setattr(providers, "OpenAI", Sdk)
    client = trial_client(idp)
    uid = client.get("/api/auth/me").json()["id"]
    profile = providers.active_profile(UserView(id=uid, username="u", is_admin=False))

    providers.get_client(profile, UserView(id=uid, username="u", is_admin=False))

    assert (built["api_key"], built["base_url"]) == (TRIAL_KEY, "https://api.deepseek.com")


# --- reserved names, the admin and hashing ---------------------------------------------------------------------------


@pytest.fixture
def web(monkeypatch):
    monkeypatch.setattr(runtime.settings, "public_host", HOST)
    return browser()


@pytest.mark.parametrize("name", ["admin", "Admin", "root", "support", "local", "system", "boss"])
def test_password_registration_refuses_reserved_names_without_using_the_invite(web, monkeypatch, name):
    monkeypatch.setattr(runtime.settings, "admin_user", "boss")
    code = accounts.create_invite(runtime.db)

    res = web.post("/api/auth/register", json={"username": name, "password": "correct horse battery", "invite": code})

    assert res.status_code == 409
    assert web.post("/api/auth/register", json={"username": "friend", "password": "correct horse battery", "invite": code}).status_code == 201


def test_the_command_line_can_still_create_the_admin(tmp_path, monkeypatch):
    db = storage.Store(tmp_path / "x.db")
    monkeypatch.setattr(accounts, "_ask_password", lambda: "correct horse battery")

    assert accounts.main(["create-user", "admin", "--admin"], db=db) == 0
    assert db.get_account("admin").is_admin


def test_the_admin_name_alone_no_longer_inherits_the_operators_key(monkeypatch):
    monkeypatch.setattr(runtime.settings, "public_host", HOST)
    monkeypatch.setattr(runtime.settings, "admin_user", "boss")
    impostor = UserView(id="c" * 32, username="boss", is_admin=False)
    real = UserView(id="d" * 32, username="boss", is_admin=True)

    assert not profile_store.is_admin_user(runtime.settings, impostor)
    assert profile_store.is_admin_user(runtime.settings, real)


def test_at_most_two_password_hashes_run_at_once(monkeypatch):
    running, peak, lock = 0, 0, threading.Lock()
    gate = threading.Event()

    class Slow:
        def hash(self, password):
            nonlocal running, peak
            with lock:
                running += 1
                peak = max(peak, running)
            gate.wait(0.2)
            with lock:
                running -= 1
            return "$h"

    monkeypatch.setattr(accounts, "hasher", Slow())
    with ThreadPoolExecutor(6) as pool:
        list(pool.map(lambda _: accounts.hash_password("pw"), range(6)))

    assert peak == 2


# --- configuration, storage and the contract ------------------------------------------------------------------------


def settings_with(**over):
    base = {
        "public_host": HOST, "open_signup": True, "trial_api_key": SecretStr(TRIAL_KEY), "oauth_pepper": SecretStr(PEPPER),
        "oauth_google_client_id": "id", "oauth_google_client_secret": SecretStr("secret"),
    }  # fmt: skip
    return Settings(_env_file=None, **{**base, **over})


def test_a_complete_trial_configuration_starts():
    runtime.refuse_bad_trial_config(settings_with())
    runtime.refuse_bad_trial_config(settings_with(open_signup=False, trial_api_key=None, oauth_pepper=None))


@pytest.mark.parametrize(
    "over,needle",
    [
        ({"trial_api_key": None}, "DOLPHINLLM_TRIAL_API_KEY"),
        ({"oauth_pepper": None}, "DOLPHINLLM_OAUTH_PEPPER"),
        ({"oauth_pepper": SecretStr("short")}, "DOLPHINLLM_OAUTH_PEPPER"),
        ({"oauth_google_client_id": None, "oauth_google_client_secret": None}, "OAuth client"),
        ({"oauth_google_client_secret": None}, "only one is set"),
        ({"public_host": None}, "DOLPHINLLM_PUBLIC_HOST"),
        ({"trial_base_url": "http://api.example.com"}, "DOLPHINLLM_TRIAL_BASE_URL"),
    ],
)
def test_open_signup_with_something_missing_refuses_to_start_and_prints_no_value(over, needle):
    with pytest.raises(SystemExit) as e:
        runtime.refuse_bad_trial_config(settings_with(**over))

    assert needle in str(e.value) and TRIAL_KEY not in str(e.value) and PEPPER not in str(e.value)


def test_the_trial_defaults():
    s = Settings(_env_file=None)

    assert (s.trial_base_url, s.trial_model, s.trial_calls, s.trial_daily_calls, s.open_signup) == ("https://api.deepseek.com", "deepseek-flash", 5, 150, False)
    assert not s.trial_enabled


def test_a_version_2_database_is_upgraded_in_place(tmp_path):
    path = tmp_path / "old.db"
    old = [s for s in storage._SCHEMA if not any(n in s for n in ("identities", "trial_anchors", "trials", "trial_usage"))]
    conn = sqlite3.connect(path)
    for statement in old:
        conn.execute(statement)
    conn.execute("INSERT INTO users (id, username, password_hash, created) VALUES ('u1', 'alice', 'h', 't')")
    conn.execute("PRAGMA user_version=2")
    conn.commit()
    conn.close()

    store = storage.Store(path)

    assert store.get_account("alice").id == "u1"
    with store._read() as c:
        tables = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert c.execute("PRAGMA user_version").fetchone()[0] == 3
    assert {"identities", "trial_anchors", "trials", "trial_usage"} <= tables
    storage.Store(path)  # idempotent


def test_a_newer_database_is_still_refused(tmp_path):
    path = tmp_path / "new.db"
    storage.Store(path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version=4")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError):
        storage.Store(path)


@pytest.mark.parametrize(
    "raw,normal",
    [
        ("Alice@Example.COM", "alice@example.com"),
        ("alice+tag@example.com", "alice@example.com"),
        ("a.l.i.c.e+x@gmail.com", "alice@gmail.com"),
        ("al.ice@googlemail.com", "alice@gmail.com"),
        ("a.lice@example.com", "a.lice@example.com"),
        ("nonsense", None),
        ("@example.com", None),
        ("a b@example.com", None),
    ],
)
def test_email_normalisation(raw, normal):
    assert anchors.normalize_email(raw) == normal


def test_disposable_domains_include_subdomains():
    assert anchors.is_disposable("x@mailinator.com") and anchors.is_disposable("x@mx.yopmail.com")
    assert not anchors.is_disposable("x@gmail.com")


def test_anchors_are_keyed_by_kind_and_pepper():
    a = anchors.anchor("pepper-one-pepper-one", "email", "a@b.c")
    assert a != anchors.anchor("pepper-two-pepper-two", "email", "a@b.c")
    assert a != anchors.anchor("pepper-one-pepper-one", "oauth:google", "a@b.c")
    assert a == anchors.anchor("pepper-one-pepper-one", "email", "a@b.c") and len(a) == 64


def test_trial_status_outside_a_deployment(api):
    assert api.get("/api/trial").json() == {"enrolled": False, "limit": 0, "used": 0, "remaining": 0, "ended": False}


def test_the_api_documents_the_new_routes(trial_on):
    schema = server.app.openapi()
    assert "/api/trial" in schema["paths"] and "/api/auth/oauth/{provider}/start" in schema["paths"]
    assert schema["paths"]["/api/trial"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("TrialStatus")
    assert "trial_api_key" not in json.dumps(schema)


def test_a_provider_list_is_capped_at_five(api):
    have = len(api.get("/api/profiles").json()["profiles"])  # the env key's legacy profile counts
    for n in range(providers.MAX_PROFILES - have):
        assert api.post("/api/profiles", json={"name": f"P{n}", "base_url": "https://api.example.com/v1", "model": "m"}).status_code == 201

    assert api.post("/api/profiles", json={"name": "P6", "base_url": "https://api.example.com/v1", "model": "m"}).status_code == 409


# --- review fixes -----------------------------------------------------------------------------------------------


def test_non_ascii_state_or_cookie_is_a_normal_state_redirect(idp):
    client = browser()
    begin(client)

    res = client.get("/api/auth/oauth/google/callback", params={"code": "c", "state": "\u00e9"}, follow_redirects=False)
    assert error_of(res) == "state"

    forged = browser()
    res = forged.get(
        "/api/auth/oauth/google/callback",
        params={"code": "c", "state": "x"},
        headers=[(b"cookie", "lumio_oauth=\u00e9.\u00e9".encode())],
        follow_redirects=False,
    )
    assert error_of(res) == "state"


def test_an_overlong_code_or_state_redirects_instead_of_a_422(idp):
    client = browser()
    _, q = begin(client)

    res = client.get("/api/auth/oauth/google/callback", params={"code": "x" * 2049, "state": q["state"][0]}, follow_redirects=False)
    assert error_of(res) == "provider" and idp.requests == []

    res = client.get("/api/auth/oauth/google/callback", params={"code": "c", "state": "s" * 600}, follow_redirects=False)
    assert error_of(res) == "state"


def test_a_busy_hasher_answers_503_without_saying_whether_the_user_exists(monkeypatch):
    accounts.create_user(runtime.db, "carol", "correct-horse-battery")
    monkeypatch.setattr(accounts, "HASH_WAIT", 0.05)
    held = [accounts._hashing.acquire() for _ in range(2)]
    try:
        client = browser()
        known = client.post("/api/auth/login", json={"username": "carol", "password": "correct-horse-battery"})
        unknown = client.post("/api/auth/login", json={"username": "nobody", "password": "correct-horse-battery"})
        token = client.post("/api/auth/token", json={"username": "carol", "password": "correct-horse-battery"})
        assert known.status_code == unknown.status_code == token.status_code == 503
        assert known.json() == unknown.json() == {"detail": "Busy, try again shortly"}
        assert known.headers["retry-after"] == "2"
    finally:
        for _ in held:
            accounts._hashing.release()
    ok = client.post("/api/auth/login", json={"username": "carol", "password": "correct-horse-battery"})
    assert ok.status_code == 200


def test_reasoning_only_tokens_count_as_delivered_and_are_not_refunded(idp):
    client = trial_client(idp)
    uid = client.get("/api/auth/me").json()["id"]
    chat = runtime.db.create_chat("trial", owner=uid)
    lease = runtime.db.acquire(chat.id, owner=uid)
    call = runtime.db.reserve_trial_call(uid, 100)

    class Thinking(FakeStream):
        def __iter__(self):
            delta = SimpleNamespace(content=None, reasoning_content="hmm")
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])
            raise OpenAIError("connection lost")

    async def run():
        return [e async for e in streaming.stream_reply(chat, "q", Thinking([]), [], [], lease=lease, trial_call=call)]

    asyncio.run(run())
    assert runtime.db.get_trial(uid).used == 1 and not call.refunded


def test_parallel_chat_creation_cannot_pass_the_trial_cap(idp):
    client = trial_client(idp)
    uid = client.get("/api/auth/me").json()["id"]
    cap = 5
    results = []

    def make():
        try:
            runtime.db.create_chat("trial", owner=uid, max_chats=cap)
            results.append(True)
        except storage.ChatLimit:
            results.append(False)

    threads = [threading.Thread(target=make) for _ in range(16)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert results.count(True) == cap and runtime.db.count_chats(owner=uid) == cap
