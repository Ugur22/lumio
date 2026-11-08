# ruff: noqa: F401, F811  (fixtures are imported from trial_support and re-declared as test arguments)
"""Free trial: the open and reserved pools, trial invites, and the pool-full log lines."""

import base64
import logging
from urllib.parse import parse_qs, urlparse

import pytest

import accounts
import storage
from app import providers, routes_oauth, runtime
from models import Settings
from trial_support import TRIAL_KEY, browser, clean, error_of, idp, model, net, new_chat, send, sign_in, trial_client, trial_on, trial_row


# --- reserved pool, trial invites -------------------------------------------------------------------------------------


def trial_invite(days=7) -> str:
    return accounts.create_invite(runtime.db, days, "trial")


def invited_sign_in(idp, code, invite, provider="google", client=None, **person):
    getattr(idp, provider)(code, **person)
    client = client or browser()
    res = client.get(f"/api/auth/oauth/{provider}/start", params={"invite": invite}, follow_redirects=False)
    assert res.status_code == 302
    if "auth_error" in res.headers["location"]:
        return client, res
    state = parse_qs(urlparse(res.headers["location"]).query)["state"][0]
    return client, client.get(f"/api/auth/oauth/{provider}/callback", params={"code": code, "state": state}, follow_redirects=False)


def invited_client(idp, name="vip", invite=None):
    client, res = invited_sign_in(idp, f"code-{name}", invite or trial_invite(), sub=f"sub-{name}", email=f"{name}@example.com")
    assert res.headers["location"] == "/", res.headers["location"]
    return client


def pool_of(client) -> str:
    uid = client.get("/api/auth/me").json()["id"]
    with runtime.db._read() as conn:
        return conn.execute("SELECT pool FROM trials WHERE user_id=?", (uid,)).fetchone()["pool"]


def small_pools(monkeypatch, daily=10, share=0.5):
    monkeypatch.setattr(runtime.settings, "trial_daily_calls", daily)
    monkeypatch.setattr(runtime.settings, "trial_reserved_share", share)


def test_the_pool_defaults_and_derived_limits():
    s = Settings(_env_file=None)

    assert s.trial_reserved_share == 0.7
    assert (s.reserved_calls, s.open_calls, s.open_signup_limit, s.reserved_signup_limit) == (105, 45, 9, 21)
    assert Settings(_env_file=None, trial_reserved_share=0).reserved_signup_limit == 0
    tiny = Settings(_env_file=None, trial_daily_calls=3, trial_reserved_share=0.1)
    assert (tiny.open_signup_limit, tiny.reserved_signup_limit) == (0, 0)  # a pool smaller than one trial allows no sign-ups
    assert Settings(_env_file=None, trial_reserved_share=1).open_signup_limit == 0
    with pytest.raises(ValueError):
        Settings(_env_file=None, trial_reserved_share=1.5)


def test_the_share_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("DOLPHINLLM_TRIAL_RESERVED_SHARE", "0.25")

    assert Settings(_env_file=None).trial_reserved_share == 0.25


def test_flooding_the_open_pool_leaves_the_reserved_pool_to_invited_users(idp, model, monkeypatch):
    flood, late, vip = trial_client(idp, "flood"), trial_client(idp, "late"), invited_client(idp)
    assert pool_of(flood) == pool_of(late) == "open" and pool_of(vip) == "reserved"
    small_pools(monkeypatch)  # 5 open calls a day, 5 reserved
    for _ in range(5):
        assert send(flood, new_chat(flood)).status_code == 200

    refused = send(late, new_chat(late))
    assert refused.status_code == 503 and refused.json()["detail"] == "Free trials are full today, try tomorrow"
    for _ in range(5):
        assert send(vip, new_chat(vip)).status_code == 200
    assert trial_row(vip).used == 5


def test_flooding_the_reserved_pool_leaves_the_open_pool(idp, model, monkeypatch):
    vip, other, plain = invited_client(idp), invited_client(idp, "vip2"), trial_client(idp, "plain")
    small_pools(monkeypatch)
    for _ in range(5):
        assert send(vip, new_chat(vip)).status_code == 200
    assert send(other, new_chat(other)).status_code == 503

    assert send(plain, new_chat(plain)).status_code == 200


def test_a_refund_goes_back_to_the_pool_it_came_from(idp, monkeypatch):
    vip, plain = invited_client(idp), trial_client(idp, "plain")
    small_pools(monkeypatch)
    caps = {"open": 5, "reserved": 5}
    vip_id, plain_id = vip.get("/api/auth/me").json()["id"], plain.get("/api/auth/me").json()["id"]
    a, b = runtime.db.reserve_trial_call(vip_id, caps), runtime.db.reserve_trial_call(plain_id, caps)

    a.refund()

    with runtime.db._read() as conn:
        usage = {r["pool"]: r["calls"] for r in conn.execute("SELECT pool, calls FROM trial_usage")}
    assert (a.pool, b.pool) == ("reserved", "open") and usage == {"reserved": 0, "open": 1}


def test_trial_full_says_which_pool(idp):
    uid = invited_client(idp).get("/api/auth/me").json()["id"]

    with pytest.raises(storage.TrialFull) as full:
        runtime.db.reserve_trial_call(uid, {"open": 99, "reserved": 0})

    assert (full.value.pool, full.value.cap) == ("reserved", 0)
    assert runtime.db.get_trial(uid).used == 0


def test_a_trial_invite_is_single_use(idp):
    code = trial_invite()
    invited_client(idp, "one", invite=code)

    _, res = invited_sign_in(idp, "code-two", code, sub="sub-two", email="two@example.com")

    assert error_of(res) == "invite"
    with runtime.db._read() as conn:
        assert conn.execute("SELECT used_by IS NOT NULL AS used FROM invites").fetchone()["used"] == 1


def test_an_expired_trial_invite_is_refused(idp):
    code = trial_invite(days=1)
    with runtime.db._tx() as conn:
        conn.execute("UPDATE invites SET expires='2000-01-01T00:00:00+00:00'")

    _, res = invited_sign_in(idp, "c", code, sub="s", email="p@example.com")

    assert error_of(res) == "invite"


def test_an_invite_that_dies_between_start_and_callback_ends_with_invite_and_makes_no_account(idp):
    code = trial_invite()
    idp.google("c", sub="s", email="p@example.com")
    client = browser()
    res = client.get("/api/auth/oauth/google/start", params={"invite": code}, follow_redirects=False)
    state = parse_qs(urlparse(res.headers["location"]).query)["state"][0]
    with runtime.db._tx() as conn:
        conn.execute("UPDATE invites SET used_by='someone', used_at='x'")

    cb = client.get("/api/auth/oauth/google/callback", params={"code": "c", "state": state}, follow_redirects=False)

    assert error_of(cb) == "invite"
    with runtime.db._read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_an_account_invite_does_not_work_for_oauth_signup(idp):
    code = accounts.create_invite(runtime.db)

    res = browser().get("/api/auth/oauth/google/start", params={"invite": code}, follow_redirects=False)

    assert res.headers["location"] == "/?auth_error=invite"
    assert runtime.db.invite_valid(accounts.sha256(code), "account")  # and it was not used up by the attempt


def test_a_trial_invite_does_not_work_for_password_registration(idp, monkeypatch):
    code = trial_invite()
    web = browser()

    res = web.post("/api/auth/register", json={"username": "mallory", "password": "a long enough password", "invite": code})

    assert res.status_code == 403
    assert runtime.db.get_account("mallory") is None
    assert runtime.db.invite_valid(accounts.sha256(code), "trial")


def test_storage_refuses_the_wrong_kind_in_both_directions(idp):
    trial, plain = trial_invite(), accounts.create_invite(runtime.db)
    kw = dict(trial_calls=5, ip_key="signup:ip:1.2.3.4")

    with pytest.raises(storage.InvalidInvite):
        runtime.db.enrol_oauth_user("google", "x", [], invite_hash=accounts.sha256(plain), **kw)
    with pytest.raises(storage.InvalidInvite):
        runtime.db.create_user("zed", "hash", invite_hash=accounts.sha256(trial))


def test_an_unknown_invite_is_refused_at_start_without_going_to_the_provider(idp):
    res = browser().get("/api/auth/oauth/google/start", params={"invite": "no-such-code"}, follow_redirects=False)

    assert res.headers["location"] == "/?auth_error=invite"
    assert "set-cookie" not in res.headers and not idp.requests


def test_an_oversized_invite_is_refused_at_start(idp):
    res = browser().get("/api/auth/oauth/google/start", params={"invite": "a" * 300}, follow_redirects=False)

    assert res.headers["location"] == "/?auth_error=invite"


def test_an_empty_invite_is_an_ordinary_signup(idp):
    res = browser().get("/api/auth/oauth/google/start", params={"invite": ""}, follow_redirects=False)

    assert urlparse(res.headers["location"]).netloc == "accounts.google.com"


def test_a_bad_invite_goes_back_to_the_app_address(idp):
    res = browser().get(
        "/api/auth/oauth/google/start",
        params={"invite": "nope", "client": "app", "redirect": "lumio://auth", "challenge": "A" * 43},
        follow_redirects=False,
    )

    assert res.headers["location"] == "lumio://auth?auth_error=invite"


def test_the_invite_is_in_no_redirect_cookie_value_or_log(idp, caplog):
    caplog.set_level(logging.DEBUG, logger="dolphinllm")
    code = trial_invite()
    idp.google("c", sub="s", email="p@example.com")
    client = browser()
    start = client.get("/api/auth/oauth/google/start", params={"invite": code}, follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    cb = client.get("/api/auth/oauth/google/callback", params={"code": "c", "state": state}, follow_redirects=False)
    _, refused = invited_sign_in(idp, "c2", code, sub="s2", email="p2@example.com")  # used up now

    cookie = start.headers["set-cookie"]
    payload = routes_oauth.unpack_state(cookie.split("lumio_oauth=")[1].split(";")[0])
    assert payload["i"] == accounts.sha256(code)
    seen = [start.headers["location"], cb.headers["location"], refused.headers["location"], cookie, caplog.text, repr([r.__dict__ for r in caplog.records])]
    assert all(code not in text for text in seen)
    assert base64.urlsafe_b64decode(cookie.split("lumio_oauth=")[1].split(".")[0] + "==").find(code.encode()) == -1


def test_signing_in_to_an_existing_account_with_an_invite_does_not_consume_it(idp):
    client = trial_client(idp, "alice")
    code = trial_invite()

    _, res = invited_sign_in(idp, "code-alice", code, sub="sub-alice", email="alice@example.com")

    assert res.headers["location"] == "/"
    assert runtime.db.invite_valid(accounts.sha256(code), "trial")
    assert pool_of(client) == "open"


def test_a_person_with_an_old_trial_keeps_the_invite(idp):
    client = trial_client(idp, "alice")
    me = client.get("/api/auth/me").json()["id"]
    with runtime.db._tx() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (me,))  # the tombstones stay
    code = trial_invite()

    _, res = invited_sign_in(idp, "code-alice", code, sub="sub-alice", email="alice@example.com")

    assert error_of(res) == "trial_used"
    assert runtime.db.invite_valid(accounts.sha256(code), "trial")


def test_the_per_address_limit_applies_to_open_signups_and_not_to_invited_ones(idp, net):
    net.ip = "203.0.113.50"
    for n in range(3):
        invited_client(idp, f"vip{n}")
    assert sign_in(idp, "o0", sub="so0", email="o0@example.com")[1].headers["location"] == "/"  # invited ones did not use the address up

    assert error_of(sign_in(idp, "o1", sub="so1", email="o1@example.com")[1]) == "throttled"
    assert invited_client(idp, "vip9")  # still not subject to it


def test_open_full_is_distinct_from_throttled(idp, net, monkeypatch):
    small_pools(monkeypatch, daily=10, share=0.5)  # 1 open sign-up a day
    net.ip = "203.0.113.60"
    assert sign_in(idp, "c0", sub="s0", email="p0@example.com")[1].headers["location"] == "/"

    same_address = sign_in(idp, "c1", sub="s1", email="p1@example.com")[1]
    net.ip = "203.0.113.61"
    other_address = sign_in(idp, "c2", sub="s2", email="p2@example.com")[1]

    assert error_of(other_address) == "open_full"
    assert error_of(same_address) == "open_full"  # the day's sign-ups are what the person is told about first
    net.ip = "203.0.113.62"
    assert invited_client(idp, "vip")  # and the invited pool has its own count


def test_throttled_is_what_a_per_address_refusal_still_says(idp, net):
    net.ip = "203.0.113.70"
    sign_in(idp, "c0", sub="s0", email="p0@example.com")

    assert error_of(sign_in(idp, "c1", sub="s1", email="p1@example.com")[1]) == "throttled"


def test_invited_signups_have_their_own_daily_limit(idp, monkeypatch):
    small_pools(monkeypatch, daily=10, share=0.5)  # 1 invited sign-up a day
    invited_client(idp, "vip0")

    _, res = invited_sign_in(idp, "code-vip1", trial_invite(), sub="sub-vip1", email="vip1@example.com")

    assert error_of(res) == "reserved_full"
    assert sign_in(idp, "o", sub="so", email="o@example.com")[1].headers["location"] == "/"


def test_no_reserved_pool_means_no_invited_signups(idp, monkeypatch):
    small_pools(monkeypatch, daily=10, share=0)

    _, res = invited_sign_in(idp, "c", trial_invite(), sub="s", email="p@example.com")

    assert error_of(res) == "reserved_full"


def test_reserved_full_leaves_the_invite_usable_and_goes_back_to_the_app(idp, monkeypatch):
    small_pools(monkeypatch, daily=10, share=0.5)  # 1 invited sign-up a day
    invited_client(idp, "vip0")
    code = trial_invite()
    idp.google("c", sub="s", email="p@example.com")
    client = browser()
    start = client.get(
        "/api/auth/oauth/google/start",
        params={"invite": code, "client": "app", "redirect": "lumio://auth", "challenge": "A" * 43},
        follow_redirects=False,
    )
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]

    cb = client.get("/api/auth/oauth/google/callback", params={"code": "c", "state": state}, follow_redirects=False)

    assert cb.headers["location"] == "lumio://auth?auth_error=reserved_full"
    assert runtime.db.invite_valid(accounts.sha256(code), "trial")


def test_an_open_pool_smaller_than_one_trial_is_open_full(idp, monkeypatch):
    small_pools(monkeypatch, daily=10, share=1)

    assert error_of(sign_in(idp, "c", sub="s", email="p@example.com")[1]) == "open_full"


def test_a_pool_that_fills_is_logged_once_per_day(idp, caplog, monkeypatch):
    providers._full_logged.clear()
    caplog.set_level(logging.WARNING, logger="dolphinllm")
    vip = invited_client(idp)
    plain = trial_client(idp, "plain")
    caps = {"open": 0, "reserved": 0}
    uids = [c.get("/api/auth/me").json()["id"] for c in (vip, plain)]

    for _ in range(3):
        for uid in uids:
            with pytest.raises(storage.TrialFull) as full:
                runtime.db.reserve_trial_call(uid, caps)
            providers._log_pool_full(full.value)

    lines = [r.getMessage() for r in caplog.records if "is full" in r.getMessage()]
    assert len(lines) == 2 and any("pool reserved" in m for m in lines) and any("pool open" in m for m in lines)
    assert all("@" not in m and TRIAL_KEY not in m for m in lines)
    providers._full_logged.clear()


def test_the_full_pool_log_comes_from_a_refused_send(idp, model, caplog, monkeypatch):
    providers._full_logged.clear()
    caplog.set_level(logging.WARNING, logger="dolphinllm")
    plain = trial_client(idp, "plain")
    small_pools(monkeypatch, daily=10, share=1)  # no open calls at all

    for _ in range(3):
        assert send(plain, new_chat(plain)).status_code == 503

    assert len([r for r in caplog.records if "is full" in r.getMessage()]) == 1
    providers._full_logged.clear()


def test_the_web_flow_notes_open_signups_but_not_invited_ones(idp, net, caplog):
    routes_oauth._cluster_seen.clear()
    routes_oauth._cluster_alerted.clear()
    caplog.set_level(logging.WARNING, logger="dolphinllm")
    for n in range(3):
        net.ip = f"198.51.100.{n + 1}"
        invited_client(idp, f"vip{n}")
    assert not routes_oauth._cluster_seen

    for n in range(3):
        net.ip = f"198.51.100.{n + 20}"
        sign_in(idp, f"c{n}", sub=f"s{n}", email=f"p{n}@example.com")

    assert len([r for r in caplog.records if "clustered" in r.getMessage()]) == 1
    assert not any("example.com" in r.getMessage() for r in caplog.records)
    routes_oauth._cluster_seen.clear()
    routes_oauth._cluster_alerted.clear()
