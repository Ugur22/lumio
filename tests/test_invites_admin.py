# ruff: noqa: F401, F811  (fixtures are imported from trial_support and re-declared as test arguments)
"""Admin invites: who may use the routes, what they return and never return, revoking, and the public invite-check."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import accounts
import storage
from app import runtime
from app.routes_invites import INVITE_CHECK_LIMIT
from trial_support import begin, browser, clean, error_of, idp, net, trial_on

ADMIN_ROUTES = [("post", "/api/admin/invites", {"kind": "trial"}), ("get", "/api/admin/invites", None), ("delete", "/api/admin/invites/abc", None)]


def make(client, kind="trial", note=None):
    r = client.post("/api/admin/invites", json={"kind": kind, **({"note": note} if note is not None else {})})
    assert r.status_code == 201, r.text
    return r.json()


def check(client, code):
    return client.post("/api/auth/invite-check", json={"invite": code})


def register(client, code, username="newbie"):
    return client.post("/api/auth/register", json={"username": username, "password": "correct horse battery", "invite": code})


# --- who may call ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
def test_a_member_and_a_signed_out_caller_get_not_found(signed_in, clean, method, path, body):
    for client in (signed_in("member"), signed_in()):
        r = getattr(client, method)(path, **({"json": body} if body else {}))
        assert r.status_code == 404
    assert runtime.db.list_invites() == []


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
def test_the_local_user_is_not_an_admin_here(clean, api, method, path, body):
    assert getattr(api, method)(path, **({"json": body} if body else {})).status_code == 404


def test_an_admin_request_from_another_origin_is_refused(signed_in, clean):
    client = signed_in("boss", admin=True)
    assert client.post("/api/admin/invites", json={"kind": "trial"}, headers={"Origin": "https://evil.example"}).status_code == 403


# --- create and list ------------------------------------------------------------------------------------------


def test_create_returns_the_code_once_and_the_list_never_does(signed_in, clean):
    admin = signed_in("boss", admin=True)
    made = make(admin, "account", "  Sam from work ")
    assert made["note"] == "Sam from work" and made["kind"] == "account" and len(made["code"]) >= 20
    listing = admin.get("/api/admin/invites")
    assert listing.status_code == 200
    assert made["code"] not in listing.text and accounts.sha256(made["code"]) not in listing.text
    assert listing.json() == [
        {"id": made["id"], "kind": "account", "note": "Sam from work", "created": made["created"], "expires": made["expires"], "status": "unused", "used_at": None}
    ]
    assert made["id"] not in made["code"] and made["id"] != accounts.sha256(made["code"])[:16]


def test_the_invite_lasts_the_server_default_and_stores_who_made_it(signed_in, clean):
    admin = signed_in("boss", admin=True)
    made = make(admin)
    span = datetime.fromisoformat(made["expires"]) - datetime.fromisoformat(made["created"])
    assert span == timedelta(days=storage.INVITE_DAYS)
    with runtime.db._read() as c:
        creator = c.execute("SELECT created_by FROM invites WHERE id=?", (made["id"],)).fetchone()[0]
    assert creator == runtime.db.get_account("boss").id


def test_a_blank_note_is_stored_as_none_and_a_long_one_is_refused(signed_in, clean):
    admin = signed_in("boss", admin=True)
    assert make(admin, note="   ")["note"] is None
    assert admin.post("/api/admin/invites", json={"kind": "trial", "note": "x" * 81}).status_code == 422
    assert admin.post("/api/admin/invites", json={"kind": "other"}).status_code == 422


def test_the_list_is_newest_first_with_each_status(signed_in, clean):
    admin = signed_in("boss", admin=True)
    now = datetime.now(timezone.utc)
    runtime.db.create_invite("h-old", 7, now=now - timedelta(days=30))  # expired
    used = make(admin, "account", "used")
    assert register(signed_in(), used["code"]).status_code == 201
    revoked = make(admin, note="revoked")
    assert admin.delete(f"/api/admin/invites/{revoked['id']}").status_code == 204
    fresh = make(admin, note="fresh")
    items = admin.get("/api/admin/invites").json()
    assert [i["status"] for i in items] == ["unused", "revoked", "used", "expired"]
    assert items[0]["id"] == fresh["id"] and items[2]["used_at"] is not None


# --- revoke ---------------------------------------------------------------------------------------------------


def test_a_revoked_invite_no_longer_registers(signed_in, clean):
    admin = signed_in("boss", admin=True)
    made = make(admin, "account")
    assert admin.delete(f"/api/admin/invites/{made['id']}").status_code == 204
    assert register(signed_in(), made["code"]).status_code == 403
    assert runtime.db.get_account("newbie") is None


def test_a_revoked_trial_invite_is_refused_at_oauth_start_and_at_enrolment(signed_in, clean, idp, net):
    admin = signed_in("boss", admin=True)
    made = make(admin, "trial")
    started = browser().get(f"/api/auth/oauth/google/start?invite={made['code']}", follow_redirects=False)
    assert "auth_error" not in started.headers["location"]  # valid before the revoke
    admin.delete(f"/api/admin/invites/{made['id']}")
    assert error_of(browser().get(f"/api/auth/oauth/google/start?invite={made['code']}", follow_redirects=False)) == "invite"
    with pytest.raises(storage.InvalidInvite):  # someone already past /start is stopped too
        runtime.db.enrol_oauth_user("google", "subj", [], trial_calls=5, ip_key="ip:1", invite_hash=accounts.sha256(made["code"]))


def test_revoking_twice_is_fine_but_a_used_invite_answers_409(signed_in, clean):
    admin = signed_in("boss", admin=True)
    one, two = make(admin, "account"), make(admin, "account")
    assert admin.delete(f"/api/admin/invites/{one['id']}").status_code == 204
    assert admin.delete(f"/api/admin/invites/{one['id']}").status_code == 204
    register(signed_in(), two["code"])
    assert admin.delete(f"/api/admin/invites/{two['id']}").status_code == 409
    assert admin.get("/api/admin/invites").json()[0]["status"] == "used"
    assert admin.delete("/api/admin/invites/nope").status_code == 404


# --- invite-check ---------------------------------------------------------------------------------------------


def test_invite_check_reports_validity_without_using_the_invite_up(signed_in, clean, net):
    admin, visitor = signed_in("boss", admin=True), signed_in()
    made = make(admin, "account")
    for _ in range(3):
        assert check(visitor, made["code"]).json() == {"valid": True, "kind": "account", "reason": None}
    assert register(visitor, made["code"]).status_code == 201


@pytest.mark.parametrize("state", ["used", "expired", "revoked", "unknown"])
def test_invite_check_says_why_an_invite_is_not_valid(signed_in, clean, net, state):
    admin, visitor = signed_in("boss", admin=True), signed_in()
    made = make(admin, "account")
    code = made["code"]
    if state == "used":
        register(visitor, code)
    elif state == "expired":
        with runtime.db._tx() as c:
            c.execute("UPDATE invites SET expires=? WHERE id=?", ("2000-01-01T00:00:00+00:00", made["id"]))
    elif state == "revoked":
        admin.delete(f"/api/admin/invites/{made['id']}")
    else:
        code = "not-a-code-we-made"
    assert check(visitor, code).json() == {"valid": False, "kind": None, "reason": state}


def test_invite_check_is_throttled_by_address_whatever_the_code(signed_in, clean, net):
    admin, visitor = signed_in("boss", admin=True), signed_in()
    good = make(admin)["code"]
    net.ip = "203.0.113.9"
    limit = INVITE_CHECK_LIMIT
    statuses = [check(visitor, good if i % 2 else f"guess-{i}").status_code for i in range(limit + 3)]
    assert statuses[:limit] == [200] * limit and set(statuses[limit:]) == {429}
    net.ip = "203.0.113.10"
    assert check(visitor, good).status_code == 200


def test_invite_check_validation_errors_do_not_echo_the_code(signed_in, clean):
    r = signed_in().post("/api/auth/invite-check", json={"invite": "x" * 300})
    assert r.status_code == 422 and "x" * 20 not in r.text


def test_invite_check_never_logs_the_code(signed_in, clean, net, caplog):
    admin = signed_in("boss", admin=True)
    code = make(admin)["code"]
    with caplog.at_level("DEBUG"):
        check(signed_in(), code)
        check(signed_in(), "wrong-wrong-wrong")
    assert code not in caplog.text and "wrong-wrong-wrong" not in caplog.text


# --- storage ---------------------------------------------------------------------------------------------------


def test_older_invites_get_an_id_and_stay_valid(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE invites (code_hash TEXT PRIMARY KEY, created TEXT, expires TEXT, used_by TEXT, used_at TEXT, kind TEXT NOT NULL DEFAULT 'account')")
    conn.execute("INSERT INTO invites (code_hash, created, expires) VALUES ('h1', 't', '2999-01-01T00:00:00+00:00')")
    conn.execute("INSERT INTO invites (code_hash, created, expires) VALUES ('h2', 't', '2999-01-01T00:00:00+00:00')")
    conn.execute("PRAGMA user_version=4")
    conn.commit()
    conn.close()

    store = storage.Store(path)

    items = store.list_invites()
    assert len(items) == 2 and all(i["id"] and i["note"] is None and i["status"] == "unused" for i in items)
    assert items[0]["id"] != items[1]["id"]
    assert store.revoke_invite(items[0]["id"]) == "revoked"
    assert store.invite_valid("h1", "account") != store.invite_valid("h2", "account")
    ids = [i["id"] for i in storage.Store(path).list_invites()]  # a second start keeps them
    assert sorted(ids) == sorted(i["id"] for i in items)
