# ruff: noqa: F401, F811  (fixtures are imported from trial_support and re-declared as test arguments)
"""Free trial: the OAuth sign-in round trip, state and cookie checks, and passwordless accounts."""

import base64
import hashlib
from datetime import datetime, timedelta, timezone

import pytest

import accounts
import storage
from app import routes_oauth, runtime
from trial_support import GOOGLE_SECRET, ORIGIN, begin, browser, clean, error_of, idp, net, sign_in, trial_on, use_up


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
