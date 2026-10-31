"""Every chat belongs to one user, and every chat route is scoped to the caller.

Identity is faked by overriding the `auth.current_user` dependency from a request header. That keeps these tests about
ownership only: how a caller is identified (cookie, session, argon2, CSRF) is covered in test_accounts.py, and running it
here would add hashing time and deployed-mode side effects to every case without testing anything about chats.
`test_real_logins_are_scoped` is the one end-to-end check through the real login routes.
"""

import base64
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

import accounts
import images
import server
import storage
from app import auth, runtime
from conftest import ORIGIN, REPLY_PIECES
from models import Chat, ImageData, Message, UserView

ROOT = Path(__file__).resolve().parent.parent
A, B = "a" * 32, "b" * 32  # ids are uuid hex: profile files and secret accounts are named after them
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


@pytest.fixture(autouse=True)
def header_identity():
    def who(request: Request):
        return UserView(id=request.headers["x-test-user"], username=request.headers["x-test-user"], is_admin=False)

    server.app.dependency_overrides[auth.current_user] = who
    yield
    server.app.dependency_overrides.pop(auth.current_user, None)


def client_for(user: str) -> TestClient:
    return TestClient(server.app, base_url=ORIGIN, headers={"Origin": ORIGIN, "X-Test-User": user})


@pytest.fixture
def alice():
    return client_for(A)


@pytest.fixture
def bob():
    return client_for(B)


@pytest.fixture
def a_chat(alice):
    """A's chat with a message carrying an image, plus the image id."""
    # A non-local user starts with no provider (only the local user and the admin inherit the env key).
    alice.post("/api/profiles", json={"name": "P", "base_url": "https://x.example/v1", "model": "m", "key": "sk-alice-1234567890"})
    chat_id = alice.post("/api/chats").json()["id"]
    ref = images.save_images(runtime.settings, chat_id, [ImageData(media_type="image/png", data=PNG)])[0]
    runtime.db.append_messages(
        chat_id,
        [Message(role="user", content="secret plot", images=[ref]), Message(role="assistant", content="secret reply")],
        owner=A,
    )
    return chat_id, ref.id


MISSING = "0" * 32

# (method, path template, json body). Every route with {chat_id} must be listed; test_every_chat_route_is_covered enforces it.
CHAT_ROUTES = [
    ("GET", "/api/chats/{c}", None),
    ("PATCH", "/api/chats/{c}", {"title": "mine now"}),
    ("DELETE", "/api/chats/{c}", None),
    ("PUT", "/api/chats/{c}/story", {"bible": "stolen", "lore": []}),
    ("PUT", "/api/chats/{c}/behavior", {"system_prompt": "stolen"}),
    ("PUT", "/api/chats/{c}/model", {"model": "stolen"}),
    ("POST", "/api/chats/{c}/summarize", None),
    ("PUT", "/api/chats/{c}/summary", {"summary": "stolen", "summary_upto": 0}),
    ("GET", "/api/chats/{c}/context", None),
    ("GET", "/api/chats/{c}/images/{i}", None),
    ("POST", "/api/chats/{c}/messages", {"content": "stolen question"}),
]


def call(client, method, template, body, chat_id, image_id="f" * 32):
    return client.request(method, template.format(c=chat_id, i=image_id), json=body)


def test_every_chat_route_is_covered():
    actual = {
        (method.upper(), path.replace("{chat_id}", "{c}").replace("{image_id}", "{i}"))
        for path, ops in server.app.openapi()["paths"].items()
        if "{chat_id}" in path
        for method in ops
    }
    assert actual == {(m, t) for m, t, _ in CHAT_ROUTES}


@pytest.mark.parametrize("method,template,body", CHAT_ROUTES, ids=[f"{m} {t}" for m, t, _ in CHAT_ROUTES])
def test_another_users_chat_answers_exactly_like_a_missing_one(method, template, body, alice, bob, a_chat, calls):
    chat_id, image_id = a_chat

    theirs = call(bob, method, template, body, chat_id, image_id)
    missing = call(bob, method, template, body, MISSING, image_id)

    assert (theirs.status_code, theirs.json()) == (404, {"detail": "Chat not found"})
    assert (theirs.status_code, theirs.json()) == (missing.status_code, missing.json())
    assert calls == []  # the model is never called on someone else's behalf


def test_nothing_of_another_users_chat_changed(alice, bob, a_chat, calls):
    chat_id, image_id = a_chat
    before = alice.get(f"/api/chats/{chat_id}").json()

    for method, template, body in CHAT_ROUTES:
        call(bob, method, template, body, chat_id, image_id)

    assert alice.get(f"/api/chats/{chat_id}").json() == before
    assert (images.chat_dir(runtime.settings, chat_id) / f"{image_id}.png").exists()


def test_owner_sees_their_own_chat_and_image(alice, a_chat):
    chat_id, image_id = a_chat

    assert alice.get(f"/api/chats/{chat_id}").status_code == 200
    assert alice.get(f"/api/chats/{chat_id}/images/{image_id}").content.startswith(b"\x89PNG")
    assert alice.get(f"/api/chats/{chat_id}/context").status_code == 200


def test_lists_show_only_own_chats(alice, bob):
    a1, a2 = (alice.post("/api/chats").json()["id"] for _ in range(2))
    b1 = bob.post("/api/chats").json()["id"]

    assert {c["id"] for c in alice.get("/api/chats").json()} == {a1, a2}
    assert [c["id"] for c in bob.get("/api/chats").json()] == [b1]


def test_a_new_chat_belongs_to_its_creator(alice, bob):
    chat_id = bob.post("/api/chats").json()["id"]

    with runtime.db._read() as conn:
        assert conn.execute("SELECT owner FROM chats WHERE id=?", (chat_id,)).fetchone()["owner"] == B
    assert alice.get(f"/api/chats/{chat_id}").status_code == 404


def test_owner_is_not_part_of_the_api(alice, a_chat):
    chat_id, _ = a_chat

    assert "owner" not in alice.get(f"/api/chats/{chat_id}").json()
    assert all("owner" not in c for c in alice.get("/api/chats").json())


def test_the_owner_can_still_delete_and_rename(alice):
    chat_id = alice.post("/api/chats").json()["id"]

    assert alice.patch(f"/api/chats/{chat_id}", json={"title": "kept"}).json()["title"] == "kept"
    assert alice.delete(f"/api/chats/{chat_id}").status_code == 204
    assert alice.get(f"/api/chats/{chat_id}").status_code == 404


def test_a_chat_without_an_owner_is_invisible_to_everyone(alice):
    orphan = Chat(id="c" * 32)
    runtime.db.insert_chat(orphan)

    assert alice.get(f"/api/chats/{orphan.id}").status_code == 404
    assert alice.get("/api/chats").json() == []
    with pytest.raises(storage.ChatNotFound):
        runtime.db.get_chat(orphan.id, owner=None)
    assert runtime.db.list_chats(owner=None) == []


# --- generation and leases ---------------------------------------------------------------------


def test_another_user_cannot_tell_a_chat_is_busy(alice, bob, a_chat, calls):
    chat_id, _ = a_chat
    lease = runtime.db.acquire(chat_id, owner=A)
    try:
        assert alice.post(f"/api/chats/{chat_id}/messages", json={"content": "x"}).status_code == 409
        assert bob.post(f"/api/chats/{chat_id}/messages", json={"content": "x"}).status_code == 404  # not 409
        with pytest.raises(storage.ChatNotFound):
            runtime.db.acquire(chat_id, owner=B)
    finally:
        lease.release()


def test_sending_works_for_the_owner_and_saves_into_their_chat(alice, bob, a_chat, calls):
    chat_id, _ = a_chat

    res = alice.post(f"/api/chats/{chat_id}/messages", json={"content": "hello"})

    assert res.status_code == 200
    assert [m["content"] for m in alice.get(f"/api/chats/{chat_id}").json()["messages"]][-2:] == ["hello", "".join(REPLY_PIECES)]
    assert bob.get("/api/chats").json() == []


def test_a_lease_cannot_save_into_a_chat_of_another_owner():
    store = runtime.db
    chat = store.create_chat(None, owner=A)
    lease = store.acquire(chat.id, owner=A)
    try:
        # B holding A's live token would still not get in: the save is scoped to the lease's owner as well.
        forged = storage.Lease(store, chat.id, lease._token, B)
        with pytest.raises(storage.ChatNotFound):
            store.append_generated(forged, [Message(role="user", content="x"), Message(role="assistant", content="y")])
        assert store.get_chat(chat.id, owner=A).messages == []
    finally:
        lease.release()


def test_a_save_after_the_chat_changed_hands_is_refused():
    store = runtime.db
    chat = store.create_chat(None, owner=A)
    lease = store.acquire(chat.id, owner=A)
    try:
        with store._tx() as conn:
            conn.execute("UPDATE chats SET owner=? WHERE id=?", (B, chat.id))

        with pytest.raises(storage.ChatNotFound):
            store.append_generated(lease, [Message(role="user", content="x"), Message(role="assistant", content="y")])
        assert store.get_chat(chat.id, owner=B).messages == []
    finally:
        lease.release()


def test_store_methods_never_cross_owners(tmp_path):
    store = storage.Store(tmp_path / "t.db")
    chat = store.create_chat(None, owner=A)
    two = [Message(role="user", content="x"), Message(role="assistant", content="y")]
    attempts = [
        lambda: store.get_chat(chat.id, owner=B),
        lambda: store.get_chat_rev(chat.id, owner=B),
        lambda: store.rename(chat.id, "t", owner=B),
        lambda: store.delete_chat(chat.id, owner=B),
        lambda: store.update_story(chat.id, "b", [], owner=B),
        lambda: store.update_behavior(chat.id, {"system_prompt": "p"}, False, None, owner=B),
        lambda: store.update_model(chat.id, "m", None, None, owner=B),
        lambda: store.update_summary(chat.id, " ", 5, owner=B),  # would be a 422 for the owner: B must not learn that
        lambda: store.update_summary(chat.id, "s", 0, owner=B),
        lambda: store.append_messages(chat.id, two, owner=B),
        lambda: store.find_image(chat.id, "f" * 32, owner=B),
        lambda: store.acquire(chat.id, owner=B),
    ]
    for attempt in attempts:
        with pytest.raises(storage.ChatNotFound):
            attempt()
    assert store.get_chat(chat.id, owner=A).model_dump() == chat.model_dump() | {"updated": store.get_chat(chat.id, owner=A).updated}
    assert store.list_chats(owner=B) == []


def test_a_chat_cannot_be_created_without_an_owner(tmp_path):
    with pytest.raises(ValueError):
        storage.Store(tmp_path / "t.db").create_chat(None, owner="")


def test_stale_reply_across_two_stores_on_one_database(tmp_path):
    db = tmp_path / "shared.db"
    first = storage.Store(db, lease_ttl=0.2, lease_beat=60)
    second = storage.Store(db, lease_ttl=0.2, lease_beat=60)
    chat = first.create_chat(None, owner=A)
    two = lambda tag: [Message(role="user", content=f"q-{tag}"), Message(role="assistant", content=f"a-{tag}")]  # noqa: E731

    token_a = first.acquire(chat.id, owner=A)
    time.sleep(0.3)  # A's lease expires without a renewal (beat is 60s): its process stalled or died

    token_b = second.acquire(chat.id, owner=A)
    second.append_generated(token_b, two("b"))
    with pytest.raises(storage.LeaseLost):
        first.append_generated(token_a, two("a"))  # the late save of the first generation

    assert [m.content for m in first.get_chat(chat.id, owner=A).messages] == ["q-b", "a-b"]
    token_a.release()
    token_b.release()


def test_two_concurrent_sends_to_one_chat_give_exactly_one_busy(tmp_path):
    db = tmp_path / "shared.db"
    stores = [storage.Store(db), storage.Store(db)]
    chat = stores[0].create_chat(None, owner=A)

    for _ in range(15):
        barrier = threading.Barrier(2)
        outcomes: list = []

        def send(store):
            barrier.wait()
            try:
                outcomes.append(store.acquire(chat.id, owner=A))
            except storage.ChatBusy:
                outcomes.append("busy")

        threads = [threading.Thread(target=send, args=(s,)) for s in stores]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)

        leases = [o for o in outcomes if o != "busy"]
        assert len(outcomes) == 2 and len(leases) == 1 and outcomes.count("busy") == 1
        leases[0].release()


# --- startup claim -----------------------------------------------------------------------------


@pytest.fixture
def old_store(tmp_path, monkeypatch):
    """A fresh database holding one chat with no owner, as an upgraded or imported one would."""
    store = storage.Store(tmp_path / "claim.db")
    store.insert_chat(Chat(id="a" * 32))
    monkeypatch.setattr(runtime.settings, "admin_user", None)
    return store


def make_user(store, name="alice"):
    return accounts.create_user(store, name, "correct horse battery", admin=True)


def test_not_deployed_unowned_chats_go_to_the_local_user(old_store, monkeypatch):
    monkeypatch.setattr(runtime.settings, "public_host", None)

    runtime.claim_unowned_chats(old_store, runtime.settings)

    assert old_store.get_chat("a" * 32, owner="local").id == "a" * 32
    assert old_store.count_unowned() == 0


@pytest.mark.parametrize("signal", ["DOLPHINLLM_SECRETS_FILE", "DOLPHINLLM_SECRET_KEY", "DOLPHINLLM_SECRET_KEY_FILE", "DOLPHINLLM_ADMIN_USER"])
def test_server_setting_without_a_public_host_never_claims_chats_for_local(old_store, monkeypatch, signal):
    # A missing or misspelt DOLPHINLLM_PUBLIC_HOST must not turn a server into the no-login local app.
    monkeypatch.setattr(runtime.settings, "public_host", None)
    if signal == "DOLPHINLLM_ADMIN_USER":
        monkeypatch.setattr(runtime.settings, "admin_user", "alice")
    else:
        monkeypatch.setenv(signal, "/somewhere")

    with pytest.raises(SystemExit) as exit_:
        runtime.claim_unowned_chats(old_store, runtime.settings)

    assert "DOLPHINLLM_PUBLIC_HOST" in str(exit_.value) and signal in str(exit_.value)
    assert old_store.count_unowned() == 1
    with pytest.raises(storage.ChatNotFound):
        old_store.get_chat("a" * 32, owner="local")


def test_a_blank_server_setting_does_not_count(old_store, monkeypatch):
    monkeypatch.setattr(runtime.settings, "public_host", None)
    monkeypatch.setenv("DOLPHINLLM_SECRETS_FILE", "  ")
    monkeypatch.setattr(runtime.settings, "admin_user", " ")

    runtime.claim_unowned_chats(old_store, runtime.settings)

    assert old_store.count_unowned() == 0


def test_deployed_unowned_chats_go_to_the_admin_user(old_store, monkeypatch):
    admin = make_user(old_store)
    monkeypatch.setattr(runtime.settings, "public_host", "lumio.example.com")
    monkeypatch.setattr(runtime.settings, "admin_user", "Alice")  # case-insensitive, like logins

    runtime.claim_unowned_chats(old_store, runtime.settings)

    assert old_store.get_chat("a" * 32, owner=admin.id).id == "a" * 32
    with pytest.raises(storage.ChatNotFound):
        old_store.get_chat("a" * 32, owner="local")


@pytest.mark.parametrize("admin_user", [None, "", "nobody"])
def test_deployed_without_a_known_admin_refuses_to_start(old_store, monkeypatch, admin_user):
    make_user(old_store)
    monkeypatch.setattr(runtime.settings, "public_host", "lumio.example.com")
    monkeypatch.setattr(runtime.settings, "admin_user", admin_user)

    with pytest.raises(SystemExit) as exit_:
        runtime.claim_unowned_chats(old_store, runtime.settings)

    assert "DOLPHINLLM_ADMIN_USER" in str(exit_.value)
    assert old_store.count_unowned() == 1  # nothing was assigned
    with pytest.raises(storage.ChatNotFound):
        old_store.get_chat("a" * 32, owner="local")


def test_deployed_with_no_unowned_chats_needs_no_admin(tmp_path, monkeypatch):
    store = storage.Store(tmp_path / "clean.db")
    store.create_chat(None, owner=A)
    monkeypatch.setattr(runtime.settings, "public_host", "lumio.example.com")
    monkeypatch.setattr(runtime.settings, "admin_user", None)

    runtime.claim_unowned_chats(store, runtime.settings)

    assert [c.id for c in store.list_chats(owner=A)] != []


def test_claiming_never_takes_chats_that_have_an_owner(old_store, monkeypatch):
    mine = old_store.create_chat(None, owner=A)
    monkeypatch.setattr(runtime.settings, "public_host", None)

    runtime.claim_unowned_chats(old_store, runtime.settings)

    assert old_store.get_chat(mine.id, owner=A).id == mine.id
    with pytest.raises(storage.ChatNotFound):
        old_store.get_chat(mine.id, owner="local")


def write_legacy(data: Path) -> None:
    data.mkdir(exist_ok=True)
    (data / f"{'b' * 32}.json").write_text(Chat(id="b" * 32).model_dump_json())


def test_legacy_import_is_owned_on_arrival(tmp_path, monkeypatch):
    data = tmp_path / "data"
    write_legacy(data)
    store = storage.Store(tmp_path / "legacy.db")
    monkeypatch.setattr(runtime.settings, "data_dir", data)
    monkeypatch.setattr(runtime.settings, "public_host", None)

    runtime.import_legacy_chats(store, runtime.settings)

    assert store.count_unowned() == 0
    assert store.get_chat("b" * 32, owner="local").id == "b" * 32


def test_legacy_import_inserts_nothing_when_nobody_can_claim_it(tmp_path, monkeypatch):
    data = tmp_path / "data"
    write_legacy(data)
    store = storage.Store(tmp_path / "legacy.db")
    monkeypatch.setattr(runtime.settings, "data_dir", data)
    monkeypatch.setattr(runtime.settings, "public_host", "lumio.example.com")
    monkeypatch.setattr(runtime.settings, "admin_user", None)

    with pytest.raises(SystemExit):
        runtime.import_legacy_chats(store, runtime.settings)

    assert store.chat_ids() == set()
    assert store.get_meta("legacy_import") is None  # so the next start, with the setting, still imports


def test_manual_cli_import_is_claimed_by_the_next_start(tmp_path, monkeypatch):
    import chat_migration

    data = tmp_path / "data"
    write_legacy(data)
    store = storage.Store(tmp_path / "legacy.db")
    chat_migration.import_chats(data, store.path, apply=True)
    monkeypatch.setattr(runtime.settings, "public_host", None)
    assert store.count_unowned() == 1

    runtime.claim_unowned_chats(store, runtime.settings)

    assert store.get_chat("b" * 32, owner="local").id == "b" * 32


def run_server_import(tmp_path, **env):
    full = {
        **os.environ,
        "DOLPHINLLM_DATA_DIR": str(tmp_path),
        "DOLPHINLLM_PROFILES_FILE": str(tmp_path / "profiles.json"),
        "DOLPHINLLM_PUBLIC_HOST": "lumio.example.com",
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",  # never the real keychain
        **env,
    }
    full = {k: v for k, v in full.items() if v is not None}  # None removes a variable
    return subprocess.run([sys.executable, "-c", "import server"], cwd=ROOT, env=full, capture_output=True, text=True, timeout=60)


def test_the_server_module_refuses_to_start_and_then_starts_with_the_setting(tmp_path):
    store = storage.Store(tmp_path / "lumio.db")
    store.insert_chat(Chat(id="a" * 32))
    make_user(store)

    refused = run_server_import(tmp_path)
    assert refused.returncode != 0
    assert "DOLPHINLLM_ADMIN_USER" in refused.stderr
    assert store.count_unowned() == 1

    started = run_server_import(tmp_path, DOLPHINLLM_ADMIN_USER="alice")
    assert started.returncode == 0, started.stderr
    assert store.count_unowned() == 0


# --- upgrading an existing database ------------------------------------------------------------


def test_a_database_without_the_owner_column_is_upgraded_in_place(tmp_path):
    path = tmp_path / "old.db"
    legacy_chats = storage._SCHEMA[0].replace(",\n        owner TEXT", "")
    assert "owner" not in legacy_chats
    conn = sqlite3.connect(path)
    conn.execute(legacy_chats)
    conn.execute("INSERT INTO chats (id, title, created, updated) VALUES (?, 'Old', '2025-01-01T00:00:00+00:00', '2025-01-01T00:00:00+00:00')", ("d" * 32,))
    conn.execute("PRAGMA user_version=1")
    conn.commit()
    conn.close()

    store = storage.Store(path)
    storage.Store(path)  # opening again is a no-op, not a "duplicate column" error

    with store._read() as c:
        assert "owner" in {r["name"] for r in c.execute("PRAGMA table_info(chats)")}
        assert "chats_owner" in {r["name"] for r in c.execute("PRAGMA index_list(chats)")}
    assert store.count_unowned() == 1
    with pytest.raises(storage.ChatNotFound):
        store.get_chat("d" * 32, owner="local")  # unowned means unreadable until claimed
    assert store.claim_unowned("local") == 1
    assert store.get_chat("d" * 32, owner="local").title == "Old"


def test_a_new_database_has_the_owner_column_and_index(tmp_path):
    store = storage.Store(tmp_path / "new.db")

    with store._read() as c:
        assert "owner" in {r["name"] for r in c.execute("PRAGMA table_info(chats)")}
        assert "chats_owner" in {r["name"] for r in c.execute("PRAGMA index_list(chats)")}


# --- through the real login routes -------------------------------------------------------------


def test_real_logins_are_scoped(monkeypatch):
    from argon2 import PasswordHasher

    server.app.dependency_overrides.pop(auth.current_user, None)
    monkeypatch.setattr(accounts, "hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))
    accounts._dummy_hash.cache_clear()
    monkeypatch.setattr(runtime.settings, "public_host", "lumio.example.com")
    origin = "https://lumio.example.com"
    try:
        sessions = []
        for name in ("alice", "bobby"):
            c = TestClient(server.app, base_url=origin, headers={"Origin": origin})
            r = c.post("/api/auth/register", json={"username": name, "password": "correct horse battery", "invite": accounts.create_invite(runtime.db)})
            assert r.status_code == 201
            sessions.append(c)
        a, b = sessions

        chat_id = a.post("/api/chats").json()["id"]

        assert b.get(f"/api/chats/{chat_id}").status_code == 404
        assert b.get("/api/chats").json() == []
        assert [c["id"] for c in a.get("/api/chats").json()] == [chat_id]
        assert TestClient(server.app, base_url=origin).get("/api/chats").status_code == 401
    finally:
        with runtime.db._tx() as conn:
            for table in ("users", "invites", "login_attempts"):
                conn.execute(f"DELETE FROM {table}")
        accounts._dummy_hash.cache_clear()


@pytest.mark.parametrize("env", [{"DOLPHINLLM_SECRETS_FILE": "secrets.json"}, {"DOLPHINLLM_ADMIN_USER": "alice"}])
def test_the_server_module_refuses_to_start_when_a_server_setting_has_no_public_host(tmp_path, env):
    # Even with no chats to claim: the app would otherwise run without any login.
    res = run_server_import(tmp_path, DOLPHINLLM_PUBLIC_HOST=None, **env)

    assert res.returncode != 0
    assert "DOLPHINLLM_PUBLIC_HOST" in res.stderr


def test_the_server_module_starts_locally_without_any_server_setting(tmp_path):
    res = run_server_import(tmp_path, DOLPHINLLM_PUBLIC_HOST=None, DOLPHINLLM_SECRET_KEY=None, DOLPHINLLM_SECRET_KEY_FILE=None, DOLPHINLLM_SECRETS_FILE=None, DOLPHINLLM_ADMIN_USER=None)

    assert res.returncode == 0, res.stderr


# --- API docs ----------------------------------------------------------------------------------


def probe_docs(tmp_path, **env):
    code = (
        "import server; from fastapi.testclient import TestClient; c = TestClient(server.app); "
        "print([c.get(p).status_code for p in ('/docs', '/redoc', '/openapi.json')], len(server.app.openapi()['paths']) > 10)"
    )
    full = {**os.environ, "DOLPHINLLM_DATA_DIR": str(tmp_path), "DOLPHINLLM_PROFILES_FILE": str(tmp_path / "profiles.json"), "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring", **env}
    full = {k: v for k, v in full.items() if v is not None}
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=full, capture_output=True, text=True, timeout=60)


def test_the_docs_and_schema_routes_are_off_on_a_server_but_the_schema_can_still_be_built(tmp_path):
    res = probe_docs(tmp_path, DOLPHINLLM_PUBLIC_HOST="lumio.example.com")

    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "[404, 404, 404] True"


def test_the_docs_stay_on_for_local_development(tmp_path):
    res = probe_docs(tmp_path, DOLPHINLLM_PUBLIC_HOST=None)

    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "[200, 200, 200] True"


def test_the_schema_export_does_not_depend_on_the_deployed_flag(tmp_path):
    env = {**os.environ, "DOLPHINLLM_PUBLIC_HOST": "lumio.example.com", "DOLPHINLLM_SECRETS_FILE": str(tmp_path / "s.json"), "DOLPHINLLM_ADMIN_USER": "alice"}
    res = subprocess.run([sys.executable, "scripts/export_openapi.py"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)

    assert res.returncode == 0, res.stderr
    assert "/api/auth/login" in res.stdout
