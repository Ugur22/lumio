import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

import accounts
import server
import storage
from app import auth, runtime

HOST = "lumio.example.com"
ORIGIN = f"https://{HOST}"
PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def fresh_accounts(monkeypatch):
    # Cheap argon2 parameters keep the suite fast; the hashing code path is the same.
    monkeypatch.setattr(accounts, "hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))
    accounts._dummy_hash.cache_clear()
    yield
    with runtime.db._tx() as conn:
        for table in ("users", "invites", "login_attempts"):  # sessions cascade
            conn.execute(f"DELETE FROM {table}")
    accounts._dummy_hash.cache_clear()


@pytest.fixture
def web(monkeypatch):
    monkeypatch.setattr(runtime.settings, "public_host", HOST)
    return TestClient(server.app, base_url=ORIGIN, headers={"Origin": ORIGIN})


def invite(days=7):
    return accounts.create_invite(runtime.db, days)


def register(web, username="alice", password=PASSWORD, code=None):
    return web.post("/api/auth/register", json={"username": username, "password": password, "invite": code or invite()})


def session_count():
    with runtime.db._read() as conn:
        return conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]


# --- registration and sessions -------------------------------------------------------------

def test_register_creates_a_user_and_signs_them_in(web):
    r = register(web, "Alice")
    assert r.status_code == 201
    assert r.json() == {"id": r.json()["id"], "username": "alice", "is_admin": False}
    assert web.get("/api/auth/me").json() == r.json()


def test_register_needs_a_valid_invite(web):
    r = web.post("/api/auth/register", json={"username": "alice", "password": PASSWORD, "invite": "nope"})
    assert r.status_code == 403
    assert web.get("/api/auth/me").status_code == 401


def test_invite_is_single_use(web):
    code = invite()
    assert register(web, "alice", code=code).status_code == 201
    other = TestClient(server.app, base_url=ORIGIN, headers={"Origin": ORIGIN})
    second = register(other, "bob", code=code)
    assert second.status_code == 403
    assert second.json() == register(other, "bob", code="unknown").json()  # used and unknown read the same


def test_expired_invite_is_refused(web):
    code = accounts.create_invite(runtime.db, days=-1)
    assert register(web, code=code).status_code == 403


def test_a_taken_username_does_not_burn_the_invite(web):
    register(web, "alice")
    code = invite()
    assert register(TestClient(server.app, base_url=ORIGIN, headers={"Origin": ORIGIN}), "ALICE", code=code).status_code == 409
    assert register(web, "bob", code=code).status_code == 201


def test_invites_are_stored_hashed(web):
    code = invite()
    with runtime.db._read() as conn:
        assert [r["code_hash"] for r in conn.execute("SELECT code_hash FROM invites")] == [accounts.sha256(code)]


def test_concurrent_redemption_has_exactly_one_winner(tmp_path):
    db = storage.Store(tmp_path / "race.db")
    code = accounts.create_invite(db)
    results = []

    def go(name):
        try:
            db.create_user(name, "h", invite_hash=accounts.sha256(code))
            results.append("ok")
        except storage.InvalidInvite:
            results.append("refused")

    threads = [threading.Thread(target=go, args=(f"user{i}",)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["ok"] + ["refused"] * 5


@pytest.mark.parametrize("username", ["ab", "a" * 33, "has space", "dot.dot", ""])
def test_bad_usernames_are_rejected(web, username):
    assert register(web, username).status_code == 422


@pytest.mark.parametrize("password", ["tiny-pw9", "x" * 129])
def test_password_length_is_enforced_without_echoing_it(web, password):
    r = register(web, "alice", password)
    assert r.status_code == 422
    assert password not in r.text


def test_login_logout_and_me(web):
    register(web)
    web.cookies.clear()
    assert web.get("/api/auth/me").status_code == 401
    r = web.post("/api/auth/login", json={"username": "ALICE", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["username"] == "alice"
    assert web.get("/api/auth/me").status_code == 200
    out = web.post("/api/auth/logout")
    assert out.status_code == 204
    assert session_count() == 1  # only the registration session, which the cleared cookie left behind
    assert web.get("/api/auth/me").status_code == 401


def test_session_cookie_holds_a_token_and_only_its_hash_is_stored(web):
    r = register(web)
    token = web.cookies.get(auth.COOKIE)
    with runtime.db._read() as conn:
        assert [s["token_hash"] for s in conn.execute("SELECT token_hash FROM sessions")] == [accounts.sha256(token)]
    assert token not in r.text


def test_cookie_flags(web):
    header = register(web).headers["set-cookie"].lower()
    assert header.startswith(f"{auth.COOKIE}=")
    for flag in ("httponly", "samesite=lax", "path=/", "secure", f"max-age={30 * 24 * 3600}"):
        assert flag in header


def test_cookie_is_not_secure_when_not_deployed(monkeypatch):
    monkeypatch.setattr(runtime.settings, "public_host", None)
    local = TestClient(server.app)
    r = register(local)
    assert "secure" not in r.headers["set-cookie"].lower()


def test_logout_clears_the_cookie(web):
    register(web)
    header = web.post("/api/auth/logout").headers["set-cookie"].lower()
    assert 'max-age=0' in header and "httponly" in header


# --- indistinguishable failures, rate limit, disabled users ---------------------------------

def test_unknown_user_and_wrong_password_answer_identically(web):
    register(web)
    web.cookies.clear()
    wrong = web.post("/api/auth/login", json={"username": "alice", "password": "not the password"})
    unknown = web.post("/api/auth/login", json={"username": "nobody", "password": "not the password"})
    assert (wrong.status_code, wrong.json()) == (unknown.status_code, unknown.json()) == (401, {"detail": "Invalid username or password"})


def test_unknown_user_still_runs_a_verification(web, monkeypatch):
    calls = []
    real = accounts.hasher

    class Spy:
        def verify(self, h, p):
            calls.append(h)
            return real.verify(h, p)

        hash = staticmethod(real.hash)

    monkeypatch.setattr(accounts, "hasher", Spy())
    web.post("/api/auth/login", json={"username": "nobody", "password": "whatever-pass"})
    assert len(calls) == 1


def test_disabled_user_cannot_log_in_and_loses_sessions(web):
    register(web)
    assert session_count() == 1
    accounts.disable_user(runtime.db, "alice")
    assert session_count() == 0
    r = web.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
    assert (r.status_code, r.json()) == (401, {"detail": "Invalid username or password"})


def test_five_failures_lock_the_username_with_retry_after(web):
    register(web)
    for _ in range(5):
        assert web.post("/api/auth/login", json={"username": "alice", "password": "wrong-password"}).status_code == 401
    r = web.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
    assert r.status_code == 429
    assert 0 < int(r.headers["retry-after"]) <= 15 * 60


def test_failures_from_one_ip_lock_that_ip_across_usernames(web):
    for i in range(5):
        web.post("/api/auth/login", json={"username": f"user{i}", "password": "wrong-password"})
    assert web.post("/api/auth/login", json={"username": "fresh", "password": "wrong-password"}).status_code == 429


def test_failures_age_out_of_the_window():
    runtime.db.record_login_failure(["user:x"] * 5, now=1000.0)
    assert runtime.db.login_wait(["user:x"], now=1100.0) > 0
    assert runtime.db.login_wait(["user:x"], now=1000.0 + 15 * 60 + 1) == 0
    runtime.db.record_login_failure(["user:y"], now=1000.0 + 15 * 60 + 2)
    with runtime.db._read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM login_attempts WHERE key='user:x'").fetchone()[0] == 0  # pruned


def test_bad_invites_count_toward_the_ip_limit(web):
    for _ in range(5):
        assert register(web, "alice", code="guess").status_code == 403
    assert register(web, "alice", code="guess").status_code == 429


def test_parallel_wrong_guesses_cannot_all_get_through_the_limit(web, monkeypatch):
    # The password check is slow, so without counting up front every parallel guess would see zero failures.
    real = accounts.verify_password
    monkeypatch.setattr(accounts, "verify_password", lambda *a, **k: (time.sleep(0.4), real(*a, **k))[1])
    register(web)
    start = threading.Barrier(10)
    codes = []

    def guess():
        client = TestClient(server.app, base_url=ORIGIN, headers={"Origin": ORIGIN})
        start.wait(10)
        codes.append(client.post("/api/auth/login", json={"username": "alice", "password": "wrong-password"}).status_code)

    threads = [threading.Thread(target=guess) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    assert sorted(codes) == [401] * 5 + [429] * 5


def test_a_successful_login_does_not_use_up_the_limit(web):
    register(web)
    for _ in range(12):
        assert web.post("/api/auth/login", json={"username": "alice", "password": PASSWORD}).status_code == 200


def test_a_taken_username_counts_toward_the_ip_limit(web):
    register(web, "alice")
    for _ in range(5):
        assert register(web, "alice").status_code == 409
    assert register(web, "alice").status_code == 429
    assert register(web, "bob").status_code == 429


def test_registrations_that_succeed_do_not_use_up_the_limit(web):
    for i in range(8):
        assert register(web, f"writer{i}").status_code == 201


def test_wrong_current_password_attempts_are_counted_before_the_check(web):
    register(web)
    for _ in range(5):
        assert web.post("/api/auth/password", json={"current_password": "nope-nope-nope", "new_password": "another long password"}).status_code == 400
    assert web.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "another long password"}).status_code == 429


def test_forwarded_for_is_not_trusted(web):
    web.headers["X-Forwarded-For"] = "9.9.9.9"
    for _ in range(5):
        web.post("/api/auth/login", json={"username": "ghost", "password": "wrong-password"})
    web.headers["X-Forwarded-For"] = "8.8.8.8"
    assert web.post("/api/auth/login", json={"username": "other", "password": "wrong-password"}).status_code == 429


# --- session lifetime and password change ---------------------------------------------------

def test_expired_session_is_refused():
    user = accounts.create_user(runtime.db, "alice", PASSWORD)
    long_ago = datetime.now(timezone.utc) - timedelta(days=31)
    runtime.db.create_session(accounts.sha256("tok"), user.id, now=long_ago)
    assert runtime.db.session_account(accounts.sha256("tok")) is None


def test_session_slides_at_most_once_a_day():
    user = accounts.create_user(runtime.db, "alice", PASSWORD)
    now = datetime.now(timezone.utc)
    runtime.db.create_session("h", user.id, now=now)
    assert runtime.db.session_account("h", now=now + timedelta(hours=2))[1] is False
    found = runtime.db.session_account("h", now=now + timedelta(days=20))
    assert found[1] is True
    assert runtime.db.session_account("h", now=now + timedelta(days=40)) is not None  # would have expired without sliding


def test_sliding_refresh_resends_the_cookie(web):
    register(web)
    token_hash = accounts.sha256(web.cookies.get(auth.COOKIE))
    with runtime.db._tx() as conn:
        conn.execute("UPDATE sessions SET last_seen=?", ((datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),))
    r = web.get("/api/auth/me")
    assert r.status_code == 200 and auth.COOKIE in r.headers["set-cookie"]
    assert runtime.db.session_account(token_hash)[1] is False


def test_password_change_ends_other_sessions_only(web):
    register(web)
    other = TestClient(server.app, base_url=ORIGIN, headers={"Origin": ORIGIN})
    other.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
    assert other.get("/api/auth/me").status_code == 200

    r = web.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "a brand new secret"})
    assert r.status_code == 204
    assert web.get("/api/auth/me").status_code == 200
    assert other.get("/api/auth/me").status_code == 401
    web.cookies.clear()
    assert web.post("/api/auth/login", json={"username": "alice", "password": PASSWORD}).status_code == 401
    assert web.post("/api/auth/login", json={"username": "alice", "password": "a brand new secret"}).status_code == 200


def test_password_change_needs_the_current_password(web):
    register(web)
    r = web.post("/api/auth/password", json={"current_password": "wrong-password", "new_password": "a brand new secret"})
    assert r.status_code == 400
    assert web.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "short"}).status_code == 422


# --- CSRF, current_user, logging -------------------------------------------------------------

def test_deployed_post_needs_a_matching_origin(web):
    code = invite()
    body = {"username": "alice", "password": PASSWORD, "invite": code}
    plain = TestClient(server.app, base_url=ORIGIN)
    assert plain.post("/api/auth/register", json=body).status_code == 403
    foreign = TestClient(server.app, base_url=ORIGIN, headers={"Origin": "https://evil.example"})
    assert foreign.post("/api/auth/register", json=body).status_code == 403
    dev = TestClient(server.app, base_url=ORIGIN, headers={"Origin": "http://localhost:5173"})
    assert dev.post("/api/auth/register", json=body).status_code == 403  # the dev-server allowance is not for a deployment
    assert web.post("/api/auth/register", json=body).status_code == 201
    assert TestClient(server.app, base_url=ORIGIN).get("/api/auth/me").status_code == 401  # GET needs no Origin


def test_current_user_is_the_fixed_local_user_when_not_deployed(monkeypatch):
    monkeypatch.setattr(runtime.settings, "public_host", None)
    r = TestClient(server.app).get("/api/auth/me")
    assert r.json() == {"id": "local", "username": "local", "is_admin": True}


def test_local_user_has_no_password_to_change(monkeypatch):
    monkeypatch.setattr(runtime.settings, "public_host", None)
    r = TestClient(server.app).post("/api/auth/password", json={"current_password": "x", "new_password": "y" * 12})
    assert r.status_code == 404


def test_disabled_user_with_a_live_session_is_signed_out(web):
    register(web)
    runtime.db.disable_user(runtime.db.get_account("alice").id)
    assert web.get("/api/auth/me").status_code == 401


def test_secrets_never_reach_the_logs(web, caplog):
    code = invite()
    with caplog.at_level(logging.INFO, logger="dolphinllm"):
        register(web, "alice", code=code)
        web.post("/api/auth/login", json={"username": "alice", "password": "wrong-password-x"})
        web.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "another long secret"})
    token = web.cookies.get(auth.COOKIE)
    text = caplog.text + repr([r.__dict__ for r in caplog.records])
    for secret in (PASSWORD, "wrong-password-x", "another long secret", code, token):
        assert secret not in text


def test_validation_errors_on_auth_routes_do_not_echo_input(web):
    r = web.post("/api/auth/login", json={"username": "alice", "password": 12345})
    assert r.status_code == 422 and "input" not in r.text


# --- CLI and storage -------------------------------------------------------------------------

def test_cli_create_user_invite_set_password_disable(tmp_path, monkeypatch, capsys):
    db = storage.Store(tmp_path / "cli.db")
    passwords = iter([PASSWORD, PASSWORD, "second long password", "second long password"])
    monkeypatch.setattr(accounts.getpass, "getpass", lambda prompt="": next(passwords))

    assert accounts.main(["create-user", "Root", "--admin"], db=db) == 0
    root = db.get_account("root")
    assert root.is_admin and accounts.verify_password(root.password_hash, PASSWORD)

    assert accounts.main(["invite", "--days", "2"], db=db) == 0
    code = capsys.readouterr().out.strip().splitlines()[-1]
    assert db.create_user("bob", "h", invite_hash=accounts.sha256(code)).username == "bob"

    assert accounts.main(["set-password", "root"], db=db) == 0
    assert accounts.verify_password(db.get_account("root").password_hash, "second long password")

    assert accounts.main(["disable", "root"], db=db) == 0
    assert db.get_account("root").disabled


def test_cli_reports_bad_input_without_a_traceback(tmp_path, monkeypatch, capsys):
    db = storage.Store(tmp_path / "cli.db")
    monkeypatch.setattr(accounts.getpass, "getpass", lambda prompt="": PASSWORD)
    assert accounts.main(["create-user", "x"], db=db) == 1
    assert accounts.main(["disable", "ghost"], db=db) == 1
    assert accounts.main(["create-user", "alice"], db=db) == 0
    assert accounts.main(["create-user", "ALICE"], db=db) == 1
    assert "taken" in capsys.readouterr().err
    monkeypatch.setattr(accounts.getpass, "getpass", lambda prompt="": "short")
    assert accounts.main(["create-user", "carol"], db=db) == 1


def test_cli_password_mismatch(tmp_path, monkeypatch):
    db = storage.Store(tmp_path / "cli.db")
    answers = iter(["one long password", "different long password"])
    monkeypatch.setattr(accounts.getpass, "getpass", lambda prompt="": next(answers))
    assert accounts.main(["create-user", "alice"], db=db) == 1
    assert db.get_account("alice") is None


def test_a_database_without_the_account_tables_upgrades_in_place(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    for statement in storage._SCHEMA[:4]:  # chats, messages, meta, generations: what shipped before accounts
        conn.execute(statement)
    conn.execute("INSERT INTO chats (id, title, created, updated) VALUES ('a', 't', 'c', 'u')")
    conn.execute("PRAGMA user_version=1")
    conn.commit()
    conn.close()

    db = storage.Store(path)
    assert "a" in db.chat_ids()
    accounts.create_user(db, "alice", PASSWORD)
    assert db.get_account("ALICE").username == "alice"
