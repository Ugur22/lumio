# ruff: noqa: F401, F811  (fixtures are imported from trial_support and re-declared as test arguments)
"""Free trial: reserved names, configuration, the database upgrade path and the command line."""

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import SecretStr

import accounts
import profile_store
import server
import storage
from app import anchors, providers, runtime
from models import Settings, UserView
from trial_support import HOST, PEPPER, TRIAL_KEY, browser, clean, model, net, trial_on


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
        assert c.execute("PRAGMA user_version").fetchone()[0] == storage.SCHEMA_VERSION
    assert {"identities", "trial_anchors", "trials", "trial_usage"} <= tables
    storage.Store(path)  # idempotent


def test_a_newer_database_is_still_refused(tmp_path):
    path = tmp_path / "new.db"
    storage.Store(path)
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version={storage.SCHEMA_VERSION + 1}")
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


def test_a_version_3_database_keeps_its_trials_in_the_open_pool(tmp_path):
    path = tmp_path / "v3.db"
    conn = sqlite3.connect(path)
    for statement in storage._SCHEMA:
        if "trial_usage" in statement:
            conn.execute("CREATE TABLE trial_usage (day TEXT PRIMARY KEY, calls INTEGER NOT NULL DEFAULT 0)")
        elif "CREATE TABLE IF NOT EXISTS trials" in statement:
            conn.execute(statement.replace(",\n        pool TEXT NOT NULL DEFAULT 'open'", ""))
        elif "CREATE TABLE IF NOT EXISTS invites" in statement:
            conn.execute(statement.replace(",\n        kind TEXT NOT NULL DEFAULT 'account'", ""))
        else:
            conn.execute(statement)
    conn.execute("INSERT INTO users (id, username, password_hash, created) VALUES ('u1', 'alice', 'h', 't')")
    conn.execute("INSERT INTO trials (user_id, call_limit, used, created) VALUES ('u1', 5, 2, 't')")
    conn.execute("INSERT INTO trial_usage (day, calls) VALUES ('2030-01-01', 7)")
    conn.execute("INSERT INTO invites (code_hash, created, expires) VALUES ('h1', 't', '2999-01-01T00:00:00+00:00')")
    assert "pool" not in {r[1] for r in conn.execute("PRAGMA table_info(trials)")}
    conn.execute("PRAGMA user_version=3")
    conn.commit()
    conn.close()

    store = storage.Store(path)

    with store._read() as c:
        assert c.execute("SELECT pool FROM trials WHERE user_id='u1'").fetchone()["pool"] == "open"
        assert [tuple(r) for r in c.execute("SELECT day, pool, calls FROM trial_usage")] == [("2030-01-01", "open", 7)]
        assert c.execute("SELECT kind FROM invites").fetchone()["kind"] == "account"
        assert c.execute("PRAGMA user_version").fetchone()[0] == storage.SCHEMA_VERSION
    assert store.get_trial("u1").used == 2
    assert store.create_user("bob", "hash", invite_hash="h1").username == "bob"  # the old invite still registers an account
    storage.Store(path)  # idempotent


def test_the_cli_prints_a_trial_invite(capsys):
    assert accounts.main(["trial-invite", "--days", "2"], db=runtime.db) == 0
    code = capsys.readouterr().out.strip().splitlines()[-1]

    assert runtime.db.invite_valid(accounts.sha256(code), "trial")
    assert not runtime.db.invite_valid(accounts.sha256(code), "account")
    assert accounts.main(["trial-invite", "--days", "0"], db=runtime.db) == 1
