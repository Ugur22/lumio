# ruff: noqa: F401, F811  (fixtures are imported from test_trial and re-declared as test arguments)
"""The native app signs in through the same server-side OAuth flow: the server brokers, the app gets a one-time code
bound to its PKCE challenge and trades it for a bearer token. Providers are faked (see test_trial.Idp); no network."""

import base64
import hashlib
import secrets
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from test_trial import HOST, ORIGIN, begin, browser, clean, error_of, idp, net, trial_on

import server
from app import routes_oauth, runtime

APP = "lumio://auth"
GENERIC = {"detail": "Invalid or expired code"}


def pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def app_start(client, challenge, redirect=APP, provider="google", **extra):
    params = {"client": "app", "redirect": redirect, "challenge": challenge, **extra}
    return client.get(f"/api/auth/oauth/{provider}/start", params=params, follow_redirects=False)


def app_sign_in(idp, code="c1", redirect=APP, provider="google", challenge=None, **person):
    """Start, provider, callback. Returns (client, callback response, verifier)."""
    verifier, made = pkce()
    getattr(idp, provider)(code, **person)
    client = browser()
    res = app_start(client, challenge or made, redirect, provider)
    assert res.status_code == 302, res.text
    state = parse_qs(urlparse(res.headers["location"]).query)["state"][0]
    cb = client.get(f"/api/auth/oauth/{provider}/callback", params={"code": code, "state": state}, follow_redirects=False)
    return client, cb, verifier


def native() -> TestClient:
    return TestClient(server.app, base_url=ORIGIN)  # no Origin header, no cookies: what an app sends


def app_code(res) -> str:
    assert res.status_code == 302 and res.headers["location"].startswith(f"{APP}?code="), res.headers.get("location")
    return parse_qs(urlparse(res.headers["location"]).query)["code"][0]


def exchange(code, verifier, client=None):
    return (client or native()).post("/api/auth/oauth/exchange", json={"code": code, "verifier": verifier})


# --- the redirect allowlist and the challenge ---------------------------------------------------------------


def test_the_app_redirect_is_accepted_and_kept_in_the_signed_state(idp):
    _, challenge = pkce()
    client = browser()

    res = app_start(client, challenge)

    assert res.status_code == 302 and res.headers["location"].startswith("https://accounts.google.com/")
    saved = routes_oauth.unpack_state(client.cookies.get("lumio_oauth"))
    assert saved["r"] == APP and saved["c"] == challenge
    assert challenge not in res.headers["location"] and APP not in res.headers["location"]  # the provider never sees them


@pytest.mark.parametrize(
    "redirect",
    [
        "lumio://auth.evil",
        "lumio://auth@evil.com",
        "lumio://auth/extra",
        "lumio://auth/",
        "lumio://auth?x=1",
        "lumio://auth#frag",
        "lumio://evil",
        "LUMIO://auth",
        "lumio:auth",
        " lumio://auth",
        "lumio://auth\n",
        "https://evil.example/auth",
        "//evil.example",
        "https://lumio.example.com/",
        "javascript:alert(1)",
        "exp://192.168.1.5:8081/--/auth",  # dev flag is off
        "",
    ],
)
def test_look_alike_redirects_are_a_400_and_never_a_redirect(idp, redirect):
    _, challenge = pkce()

    res = app_start(browser(), challenge, redirect)

    assert res.status_code == 400 and "location" not in res.headers and "set-cookie" not in res.headers


def test_a_missing_redirect_or_wrong_client_is_a_400(idp):
    _, challenge = pkce()
    c = browser()

    assert c.get("/api/auth/oauth/google/start", params={"client": "app", "challenge": challenge}, follow_redirects=False).status_code == 400
    assert c.get("/api/auth/oauth/google/start", params={"client": "ios", "redirect": APP, "challenge": challenge}, follow_redirects=False).status_code == 400


@pytest.mark.parametrize("challenge", [None, "", "short", "a" * 42, "a" * 44, "a" * 42 + "=", "a" * 42 + "+", "a" * 42 + "é", "a" * 42 + " "])
def test_a_missing_or_malformed_challenge_is_a_400(idp, challenge):
    params = {"client": "app", "redirect": APP}
    if challenge is not None:
        params["challenge"] = challenge

    res = browser().get("/api/auth/oauth/google/start", params=params, follow_redirects=False)

    assert res.status_code == 400 and "location" not in res.headers


DEV = [
    "exp://192.168.1.5:8081/--/auth",
    "exps://u.expo.dev/abc-123/--/auth",
    "exp://abc-anonymous-8081.exp.direct/--/auth",
    "exp://10.0.0.2:19000/some/path/--/auth",
]
DEV_BAD = [
    "exp://192.168.1.5:8081/--/auth/evil",
    "exp://192.168.1.5:8081/auth",
    "exp://192.168.1.5:8081/--/auth?x=1",
    "exp://192.168.1.5:8081/--/auth#x",
    "exp://user@192.168.1.5:8081/--/auth",
    "exp://evil.com\\@192.168.1.5/--/auth",
    "exp://192.168.1.5:8081/../--/auth",
    "exp:///--/auth",
    "exp://host:99999999/--/auth",
    "exp://host/--/auth\n",
    "exp://host /--/auth",
    "expo://host/--/auth",
    "http://192.168.1.5:8081/--/auth",
    "exp://hôst/--/auth",
    "exp://attacker.example/--/auth",
    "exp://8.8.8.8:8081/--/auth",
    "exp://evil.exp.direct.attacker.example/--/auth",
    "exp://u.expo.dev.attacker.example/--/auth",
]


@pytest.mark.parametrize("redirect", DEV)
def test_expo_go_redirects_work_only_with_the_dev_flag(idp, monkeypatch, redirect):
    _, challenge = pkce()
    assert app_start(browser(), challenge, redirect).status_code == 400
    monkeypatch.setattr(runtime.settings, "oauth_app_dev_redirects", True)

    assert app_start(browser(), challenge, redirect).status_code == 302


@pytest.mark.parametrize("redirect", DEV_BAD)
def test_expo_go_look_alikes_are_refused_even_with_the_dev_flag(idp, monkeypatch, redirect):
    monkeypatch.setattr(runtime.settings, "oauth_app_dev_redirects", True)
    _, challenge = pkce()

    assert app_start(browser(), challenge, redirect).status_code == 400


def test_the_dev_flag_still_accepts_the_production_redirect(idp, monkeypatch):
    monkeypatch.setattr(runtime.settings, "oauth_app_dev_redirects", True)

    assert app_start(browser(), pkce()[1]).status_code == 302


def test_the_dev_flag_defaults_to_off():
    from models import Settings

    assert Settings(_env_file=None).oauth_app_dev_redirects is False


def test_a_dev_redirect_is_revalidated_in_the_callback_when_the_flag_is_switched_off(idp, monkeypatch):
    monkeypatch.setattr(runtime.settings, "oauth_app_dev_redirects", True)
    idp.google("c2")
    c = browser()
    state = parse_qs(urlparse(app_start(c, pkce()[1], "exp://192.168.1.5:8081/--/auth").headers["location"]).query)["state"][0]
    monkeypatch.setattr(runtime.settings, "oauth_app_dev_redirects", False)

    res = c.get("/api/auth/oauth/google/callback", params={"code": "c2", "state": state}, follow_redirects=False)

    assert res.headers["location"] == "/"  # no trusted app redirect any more: the web path, never a bounce to exp://


# --- the happy path ---------------------------------------------------------------------------------------------


def test_start_callback_exchange_gives_a_bearer_that_works(idp):
    client, cb, verifier = app_sign_in(idp)

    code = app_code(cb)
    assert "lumio_session" not in cb.headers.get("set-cookie", "") and client.cookies.get("lumio_session") is None
    assert list(parse_qs(urlparse(cb.headers["location"]).query)) == ["code"]

    res = exchange(code, verifier)

    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"token", "user"} and body["user"]["is_admin"] is False
    api = TestClient(server.app, base_url=ORIGIN, headers={"Authorization": f"Bearer {body['token']}"})
    assert api.get("/api/auth/me").json()["id"] == body["user"]["id"]
    trial = api.get("/api/trial").json()
    assert trial["enrolled"] is True and trial["remaining"] == runtime.settings.trial_calls


def test_github_works_the_same(idp):
    _, cb, verifier = app_sign_in(idp, provider="github")

    assert exchange(app_code(cb), verifier).status_code == 200


def test_the_callback_clears_the_state_cookie_and_stores_only_the_code_hash(idp):
    _, cb, _ = app_sign_in(idp)
    code = app_code(cb)

    assert 'lumio_oauth=""' in cb.headers["set-cookie"] or "lumio_oauth=;" in cb.headers["set-cookie"] or "Max-Age=0" in cb.headers["set-cookie"]
    with sqlite3.connect(runtime.db.path) as conn:
        rows = conn.execute("SELECT code_hash, user_id, challenge, expires_at FROM app_login_codes").fetchall()
    assert [r[0] for r in rows] == [hashlib.sha256(code.encode()).hexdigest()]
    assert code not in repr(rows) and len(code) >= 43


def test_a_returning_user_signs_in_again_to_the_same_account(idp):
    _, cb, v = app_sign_in(idp)
    first = exchange(app_code(cb), v).json()["user"]["id"]
    _, cb, v = app_sign_in(idp, code="c2", sub="sub-alice")
    idp.google("c2")

    assert exchange(app_code(cb), v).json()["user"]["id"] == first


def test_trial_used_still_signs_the_person_in_without_a_trial(idp):
    _, cb, v = app_sign_in(idp, "c1", sub="sub-a", email="same@example.com")
    first = exchange(app_code(cb), v).json()["user"]["id"]
    _delete(first)

    _, cb, v = app_sign_in(idp, "c2", sub="sub-b", email="same@example.com")  # a new subject, the same person (email anchor)

    q = parse_qs(urlparse(cb.headers["location"]).query)
    assert q["auth_error"] == ["trial_used"] and "code" in q
    res = exchange(q["code"][0], v)
    assert res.status_code == 200
    api = TestClient(server.app, base_url=ORIGIN, headers={"Authorization": f"Bearer {res.json()['token']}"})
    assert api.get("/api/trial").json()["enrolled"] is False


def _delete(user_id):
    with runtime.db._tx() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))


# --- the exchange ------------------------------------------------------------------------------------------------


def test_a_code_is_single_use(idp):
    _, cb, v = app_sign_in(idp)
    code = app_code(cb)

    assert exchange(code, v).status_code == 200
    again = exchange(code, v)

    assert again.status_code == 400 and again.json() == GENERIC


def test_parallel_exchanges_of_one_code_let_exactly_one_through(idp):
    _, cb, v = app_sign_in(idp)
    code = app_code(cb)
    gate = threading.Barrier(6)

    def go(_):
        gate.wait()
        return exchange(code, v).status_code

    with ThreadPoolExecutor(6) as pool:
        statuses = list(pool.map(go, range(6)))

    assert sorted(statuses) == [200] + [400] * 5


def test_an_expired_code_is_refused_and_purged(idp, monkeypatch):
    monkeypatch.setattr(routes_oauth, "APP_CODE_SECONDS", -1)
    _, cb, v = app_sign_in(idp)

    res = exchange(app_code(cb), v)

    assert res.status_code == 400 and res.json() == GENERIC
    with sqlite3.connect(runtime.db.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM app_login_codes").fetchone()[0] == 0


def test_the_code_lives_sixty_seconds():
    assert routes_oauth.APP_CODE_SECONDS == 60


def test_expired_codes_are_purged_when_another_is_created_or_taken(idp):
    _, cb, v = app_sign_in(idp)
    exchange(app_code(cb), v)
    with sqlite3.connect(runtime.db.path) as conn:
        user_id = conn.execute("SELECT id FROM users").fetchone()[0]
    db = runtime.db

    db.create_app_login_code("old", user_id, "c" * 43, expires_at=100.0, now=50.0)
    db.create_app_login_code("new", user_id, "c" * 43, expires_at=1000.0, now=200.0)  # creating purges "old"
    assert db.take_app_login_code("old", now=201.0) is None
    db.create_app_login_code("stale", user_id, "c" * 43, expires_at=300.0, now=250.0)

    assert db.take_app_login_code("stale", now=300.0) is None  # expired exactly now
    assert db.take_app_login_code("new", now=301.0) == (user_id, "c" * 43)
    assert db.take_app_login_code("new", now=301.0) is None
    with sqlite3.connect(db.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM app_login_codes").fetchone()[0] == 0


def test_a_wrong_verifier_is_refused_and_burns_the_code(idp):
    _, cb, v = app_sign_in(idp)
    code = app_code(cb)

    wrong = exchange(code, pkce()[0])
    right = exchange(code, v)

    assert wrong.status_code == 400 and wrong.json() == GENERIC
    assert right.status_code == 400 and right.json() == GENERIC  # documented: a failed guess uses the code up


@pytest.mark.parametrize("verifier", ["é" * 50, "é", "𝔘" * 20, "\ud800", "a" * 300, ""])
def test_a_strange_verifier_is_a_400_not_a_500(idp, verifier):
    _, cb, _ = app_sign_in(idp)

    res = native().post("/api/auth/oauth/exchange", content=_json({"code": app_code(cb), "verifier": verifier}), headers={"content-type": "application/json"})

    assert res.status_code == 400 and res.json() == GENERIC


@pytest.mark.parametrize("code", ["é" * 43, "\ud800", "x" * 300, "", "not-a-code"])
def test_a_strange_code_is_a_400_not_a_500(idp, code):
    res = native().post("/api/auth/oauth/exchange", content=_json({"code": code, "verifier": pkce()[0]}), headers={"content-type": "application/json"})

    assert res.status_code == 400 and res.json() == GENERIC


def _json(data):
    import json

    return json.dumps(data).encode()  # ensure_ascii keeps a lone surrogate as the escape \ud800


def test_the_failures_are_indistinguishable(idp):
    _, cb, v = app_sign_in(idp)
    code = app_code(cb)

    unknown = exchange("nope", v)
    wrong = exchange(code, "not-the-verifier")

    assert unknown.status_code == wrong.status_code == 400 and unknown.text == wrong.text


def test_exchange_needs_no_origin_and_sets_no_cookie(idp):
    _, cb, v = app_sign_in(idp)

    res = native().post("/api/auth/oauth/exchange", json={"code": app_code(cb), "verifier": v}, headers={"Origin": "https://evil.example"})

    assert res.status_code == 200 and "set-cookie" not in res.headers


def test_exchange_is_throttled_like_login(idp, net):
    net.ip = "203.0.113.9"
    _, cb, v = app_sign_in(idp)
    code = app_code(cb)
    for _ in range(5):
        assert exchange(f"guess-{_}", v).status_code == 400

    blocked = exchange(code, v)

    assert blocked.status_code == 429 and "retry-after" in blocked.headers


def test_a_success_does_not_use_up_the_throttle(idp, net):
    net.ip = "203.0.113.10"
    for i in range(8):
        _, cb, v = app_sign_in(idp, code=f"c{i}")
        assert exchange(app_code(cb), v).status_code == 200


def test_a_disabled_account_cannot_exchange(idp):
    _, cb, v = app_sign_in(idp)
    code = app_code(cb)
    with runtime.db._tx() as conn:
        user_id = conn.execute("SELECT user_id FROM app_login_codes").fetchone()[0]
    runtime.db.disable_user(user_id)

    res = exchange(code, v)

    assert res.status_code == 400 and res.json() == GENERIC


def test_the_exchanged_session_dies_on_logout(idp):
    _, cb, v = app_sign_in(idp)
    token = exchange(app_code(cb), v).json()["token"]
    api = TestClient(server.app, base_url=ORIGIN, headers={"Authorization": f"Bearer {token}", "Origin": ORIGIN})

    assert api.post("/api/auth/logout").status_code == 204
    assert api.get("/api/auth/me").status_code == 401


# --- errors go back to the app ---------------------------------------------------------------------------------


def _error_redirect(res):
    assert res.status_code == 302
    loc = urlparse(res.headers["location"])
    return f"{loc.scheme}://{loc.netloc}{loc.path}", parse_qs(loc.query)


def test_a_provider_error_goes_back_to_the_app_redirect(idp):
    verifier, challenge = pkce()
    client = browser()
    state = parse_qs(urlparse(app_start(client, challenge).headers["location"]).query)["state"][0]

    res = client.get("/api/auth/oauth/google/callback", params={"error": "access_denied", "state": state}, follow_redirects=False)

    assert _error_redirect(res) == (APP, {"auth_error": ["denied"]})
    assert "set-cookie" in res.headers and "lumio_session" not in res.headers["set-cookie"]


@pytest.mark.parametrize(
    "setup,expected",
    [
        ({"verified": False}, "unverified"),
        ({"email": "x@mailinator.com"}, "disposable"),
    ],
)
def test_identity_failures_go_back_to_the_app_with_the_web_codes(idp, setup, expected):
    _, cb, _ = app_sign_in(idp, **setup)

    assert _error_redirect(cb) == (APP, {"auth_error": [expected]})


def test_a_disabled_account_goes_back_to_the_app_as_disabled(idp):
    _, cb, v = app_sign_in(idp)
    uid = exchange(app_code(cb), v).json()["user"]["id"]
    runtime.db.disable_user(uid)

    _, cb, _ = app_sign_in(idp, code="c2")

    assert _error_redirect(cb) == (APP, {"auth_error": ["disabled"]})


def test_a_throttled_signup_goes_back_to_the_app(idp, net):
    net.ip = "203.0.113.20"
    _, cb, _ = app_sign_in(idp, code="c0", sub="s0", email="p0@example.com")
    app_code(cb)

    _, cb, _ = app_sign_in(idp, code="c9", sub="s9", email="p9@example.com")

    assert _error_redirect(cb) == (APP, {"auth_error": ["throttled"]})


def test_a_wrong_state_still_goes_back_to_the_app_through_the_signed_cookie(idp):
    _, challenge = pkce()
    client = browser()
    app_start(client, challenge)

    res = client.get("/api/auth/oauth/google/callback", params={"code": "c1", "state": "forged"}, follow_redirects=False)

    assert _error_redirect(res) == (APP, {"auth_error": ["state"]})
    assert idp.requests == []


def test_without_a_valid_state_cookie_the_failure_is_the_web_one_never_a_bounce(idp):
    _, challenge = pkce()
    _, q = begin(browser())
    fresh = browser()  # no cookie
    forged = browser()
    forged.cookies.set("lumio_oauth", routes_oauth.pack_state({"p": "google", "s": "x", "v": "v", "exp": 9e12, "r": APP, "c": challenge})[:-3] + "abc", domain=HOST, path="/api/auth/oauth/")

    for c in (fresh, forged):
        res = c.get("/api/auth/oauth/google/callback", params={"code": "c1", "state": q["state"][0]}, follow_redirects=False)
        assert res.headers["location"] == "/?auth_error=state"


def test_unconfigured_app_start_reports_back_to_the_app(idp, monkeypatch):
    monkeypatch.setattr(runtime.settings, "open_signup", False)

    res = app_start(browser(), pkce()[1])

    assert res.status_code == 302 and res.headers["location"] == f"{APP}?auth_error=unavailable"


def test_unconfigured_app_start_still_validates_the_redirect_first(idp, monkeypatch):
    monkeypatch.setattr(runtime.settings, "open_signup", False)

    assert app_start(browser(), pkce()[1], "https://evil.example").status_code == 400


# --- the web flow is untouched ----------------------------------------------------------------------------------


def test_the_web_flow_still_sets_the_cookie_and_returns_to_the_site(idp):
    client = browser()
    idp.google("c1")
    _, q = begin(client)
    assert "r" not in routes_oauth.unpack_state(client.cookies.get("lumio_oauth"))

    res = client.get("/api/auth/oauth/google/callback", params={"code": "c1", "state": q["state"][0]}, follow_redirects=False)

    assert res.headers["location"] == "/" and client.cookies.get("lumio_session")
    with sqlite3.connect(runtime.db.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM app_login_codes").fetchone()[0] == 0


def test_a_web_state_cookie_cannot_be_turned_into_an_app_flow_by_query_parameters_on_the_callback(idp):
    client = browser()
    idp.google("c1")
    _, q = begin(client)

    res = client.get(
        "/api/auth/oauth/google/callback",
        params={"code": "c1", "state": q["state"][0], "client": "app", "redirect": "https://evil.example", "challenge": "a" * 43},
        follow_redirects=False,
    )

    assert res.headers["location"] == "/" and client.cookies.get("lumio_session")


# --- nothing sensitive is logged ---------------------------------------------------------------------------------


def test_codes_verifiers_tokens_and_redirects_are_not_logged(idp, caplog):
    caplog.set_level("DEBUG")
    _, cb, v = app_sign_in(idp)
    code = app_code(cb)
    token = exchange(code, v).json()["token"]
    exchange(code, v)

    # The server's own loggers; the TestClient's httpx2 line about its own request is not the server logging.
    ours = [r for r in caplog.records if not r.name.startswith(("httpx2", "asyncio"))]
    assert any("app code" in r.getMessage() for r in ours)
    text = " ".join(r.getMessage() + repr(r.__dict__) for r in ours)
    for secret in (code, v, token, "lumio://auth?"):
        assert secret not in text
