import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

import storage

OWNER = "u1"
from models import LoreEntry, Message, Usage

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def store(tmp_path):
    return storage.Store(tmp_path / "chats.db")


def msg(role, text):
    return Message(role=role, content=text)


def run_threads(targets):
    errors = []

    def wrap(fn):
        def run():
            try:
                fn()
            except BaseException as e:  # surfaced below so a thread failure fails the test
                errors.append(e)

        return run

    threads = [threading.Thread(target=wrap(t)) for t in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not errors, errors


# --- concurrent updates -------------------------------------------------------------------------


def test_concurrent_appends_to_one_chat_lose_nothing(store):
    chat = store.create_chat(None, owner=OWNER)

    def worker(n):
        return lambda: [store.append_messages(chat.id, [msg("user", f"{n}-{i}"), msg("assistant", f"r{n}-{i}")], owner=OWNER) for i in range(10)]

    run_threads([worker(n) for n in range(8)])

    loaded = store.get_chat(chat.id, owner=OWNER)
    assert len(loaded.messages) == 160
    with store._read() as conn:
        seqs = [r[0] for r in conn.execute("SELECT seq FROM messages WHERE chat_id=? ORDER BY seq", (chat.id,))]
    assert seqs == list(range(160))
    # Each turn stays adjacent: the user message is always followed by its own reply.
    pairs = [(a.content, b.content) for a, b in zip(loaded.messages[::2], loaded.messages[1::2])]
    assert all(a.startswith(tuple("01234567")) and b == "r" + a for a, b in pairs)


def test_settings_edits_and_appends_in_parallel_all_survive(store):
    chat = store.create_chat(None, owner=OWNER)
    lore = [LoreEntry(id="a" * 32, name="Elara", keys=["elara"], content="ranger")]

    run_threads(
        [
            lambda: [store.append_messages(chat.id, [msg("user", "q"), msg("assistant", "a")], owner=OWNER) for _ in range(20)],
            lambda: [store.rename(chat.id, f"title {i}", owner=OWNER) for i in range(20)],
            lambda: [store.update_story(chat.id, f"bible {i}", lore, owner=OWNER) for i in range(20)],
            lambda: [store.update_behavior(chat.id, {"system_prompt": f"p{i}", "temperature": 0.5}, False, None, owner=OWNER) for i in range(20)],
        ]
    )

    loaded = store.get_chat(chat.id, owner=OWNER)
    assert len(loaded.messages) == 40
    assert (loaded.title, loaded.bible, loaded.system_prompt) == ("title 19", "bible 19", "p19")
    assert loaded.lore == lore and loaded.temperature == 0.5


def test_append_from_a_stale_snapshot_does_not_revert_settings(store):
    chat = store.create_chat(None, owner=OWNER)
    stale = store.get_chat(chat.id, owner=OWNER)

    store.update_story(chat.id, "new bible", [], owner=OWNER)
    store.rename(chat.id, "Renamed", owner=OWNER)
    store.append_messages(stale.id, [msg("user", "q"), msg("assistant", "a")], title="from the first message", owner=OWNER)

    loaded = store.get_chat(chat.id, owner=OWNER)
    assert (loaded.bible, loaded.title, len(loaded.messages)) == ("new bible", "Renamed", 2)


def test_settings_update_leaves_messages_and_other_settings_alone(store):
    chat = store.create_chat("p1", owner=OWNER)
    store.append_messages(chat.id, [msg("user", "q"), msg("assistant", "a")], owner=OWNER)
    store.update_story(chat.id, "bible", [], owner=OWNER)

    store.update_behavior(chat.id, {"system_prompt": "be brief", "temperature": 0.2}, False, None, owner=OWNER)

    loaded = store.get_chat(chat.id, owner=OWNER)
    assert (loaded.bible, loaded.profile_id, len(loaded.messages)) == ("bible", "p1", 2)


def test_usage_is_dropped_when_settings_changed_since_the_send(store):
    chat = store.create_chat(None, owner=OWNER)
    _, rev = store.get_chat_rev(chat.id, owner=OWNER)
    store.update_story(chat.id, "changed meanwhile", [], owner=OWNER)

    store.append_messages(chat.id, [msg("user", "q"), msg("assistant", "a")], usage=Usage(prompt_tokens=99), rev=rev, owner=OWNER)
    assert store.get_chat(chat.id, owner=OWNER).last_usage is None

    _, rev = store.get_chat_rev(chat.id, owner=OWNER)
    store.append_messages(chat.id, [msg("user", "q"), msg("assistant", "a")], usage=Usage(prompt_tokens=99), rev=rev, owner=OWNER)
    assert store.get_chat(chat.id, owner=OWNER).last_usage == Usage(prompt_tokens=99)


def test_append_to_a_deleted_chat_raises_and_does_not_recreate_it(store):
    chat = store.create_chat(None, owner=OWNER)
    store.delete_chat(chat.id, owner=OWNER)

    with pytest.raises(storage.ChatNotFound):
        store.append_messages(chat.id, [msg("user", "q"), msg("assistant", "a")], owner=OWNER)

    assert store.chat_ids() == set()
    with store._read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0


def test_delete_removes_messages_and_the_lease(store):
    chat = store.create_chat(None, owner=OWNER)
    store.append_messages(chat.id, [msg("user", "q"), msg("assistant", "a")], owner=OWNER)
    lease = store.acquire(chat.id, owner=OWNER)

    store.delete_chat(chat.id, owner=OWNER)
    lease.release()

    with store._read() as conn:
        assert [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("chats", "messages", "generations")] == [0, 0, 0]


def test_summary_is_checked_against_the_messages_in_the_same_transaction(store):
    chat = store.create_chat(None, owner=OWNER)
    store.append_messages(chat.id, [msg("user", "q"), msg("assistant", "a")], owner=OWNER)

    with pytest.raises(storage.InvalidUpdate, match="beyond"):
        store.update_summary(chat.id, "s", 3, owner=OWNER)
    with pytest.raises(storage.InvalidUpdate, match="Write a summary"):
        store.update_summary(chat.id, " ", 1, owner=OWNER)
    assert store.update_summary(chat.id, "s", 2, owner=OWNER).summary_upto == 2


def test_a_database_from_a_newer_build_is_refused(tmp_path):
    path = tmp_path / "future.db"
    storage.Store(path)
    with storage.Store(path)._tx() as conn:
        conn.execute(f"PRAGMA user_version={storage.SCHEMA_VERSION + 1}")

    with pytest.raises(RuntimeError, match="schema version"):
        storage.Store(path)


PRE_ACCOUNTS_SCHEMA_VERSION = 1  # what the release before accounts accepts: it refuses anything higher


def user_version(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def test_a_new_database_is_stamped_so_the_pre_accounts_release_refuses_it(tmp_path):
    path = tmp_path / "new.db"
    storage.Store(path)

    assert user_version(path) == storage.SCHEMA_VERSION > PRE_ACCOUNTS_SCHEMA_VERSION


def test_a_pre_accounts_database_is_upgraded_in_place_and_restamped(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    for statement in storage._SCHEMA[:4]:  # chats (with owner), messages, meta, generations
        conn.execute(statement)
    conn.execute("INSERT INTO chats (id, title, created, updated) VALUES ('a', 't', 'c', 'u')")
    conn.execute(f"PRAGMA user_version={PRE_ACCOUNTS_SCHEMA_VERSION}")
    conn.commit()
    conn.close()

    store = storage.Store(path)

    assert "a" in store.chat_ids()
    assert user_version(path) == storage.SCHEMA_VERSION


# --- generation leases --------------------------------------------------------------------------


def test_only_one_lease_per_chat_but_other_chats_are_free(store):
    a, b = store.create_chat(None, owner=OWNER), store.create_chat(None, owner=OWNER)
    lease = store.acquire(a.id, owner=OWNER)

    with pytest.raises(storage.ChatBusy):
        store.acquire(a.id, owner=OWNER)
    other = store.acquire(b.id, owner=OWNER)

    lease.release()
    store.acquire(a.id, owner=OWNER).release()
    other.release()


def test_acquire_on_a_missing_chat_is_not_found(store):
    with pytest.raises(storage.ChatNotFound):
        store.acquire("f" * 32, owner=OWNER)


def test_release_is_idempotent(store):
    chat = store.create_chat(None, owner=OWNER)
    lease = store.acquire(chat.id, owner=OWNER)
    lease.release()
    lease.release()
    store.acquire(chat.id, owner=OWNER).release()


def test_an_expired_lease_is_taken_over_and_the_old_owner_cannot_release_the_new_one(tmp_path):
    store = storage.Store(tmp_path / "t.db", lease_ttl=0.2, lease_beat=60)
    chat = store.create_chat(None, owner=OWNER)
    old = store.acquire(chat.id, owner=OWNER)
    time.sleep(0.3)

    new = store.acquire(chat.id, owner=OWNER)
    old.release()  # fenced by its token: the row now belongs to `new`

    with pytest.raises(storage.ChatBusy):
        store.acquire(chat.id, owner=OWNER)
    new.release()


def test_a_live_lease_is_renewed_past_its_ttl(tmp_path):
    store = storage.Store(tmp_path / "t.db", lease_ttl=0.4, lease_beat=0.1)
    chat = store.create_chat(None, owner=OWNER)
    lease = store.acquire(chat.id, owner=OWNER)

    time.sleep(1.0)

    with pytest.raises(storage.ChatBusy):
        store.acquire(chat.id, owner=OWNER)
    lease.release()


def holder_script(db, chat_id, ttl, then):
    return textwrap.dedent(
        f"""
        import os, signal, sys, time
        import storage
        store = storage.Store({str(db)!r}, lease_ttl={ttl}, lease_beat=0.2)
        try:
            store.acquire({chat_id!r}, owner={OWNER!r})
        except storage.ChatBusy:
            print("busy", flush=True)
            sys.exit(0)
        print("held", flush=True)
        {then}
        """
    )


def spawn(script):
    return subprocess.Popen([sys.executable, "-c", script], cwd=ROOT, stdout=subprocess.PIPE, text=True)


def test_lease_left_by_a_killed_process_expires_and_can_be_taken_over(tmp_path):
    store = storage.Store(tmp_path / "t.db", lease_ttl=1.0, lease_beat=0.2)
    chat = store.create_chat(None, owner=OWNER)
    proc = spawn(holder_script(store.path, chat.id, 1.0, "os.kill(os.getpid(), signal.SIGKILL)"))
    assert proc.stdout.readline().strip() == "held"
    proc.wait(10)

    with pytest.raises(storage.ChatBusy):  # not yet: we cannot know the owner is dead
        store.acquire(chat.id, owner=OWNER)
    time.sleep(1.2)

    store.acquire(chat.id, owner=OWNER).release()


def test_processes_racing_for_one_chat_produce_exactly_one_winner(tmp_path):
    store = storage.Store(tmp_path / "t.db")
    chat = store.create_chat(None, owner=OWNER)
    start = time.time() + 1.5
    script = holder_script(store.path, chat.id, 30, "time.sleep(2.5)").replace(
        "store = ", f"time.sleep(max(0, {start} - time.time()))\nstore = ", 1
    )
    procs = [spawn(script) for _ in range(4)]

    results = sorted(p.stdout.readline().strip() for p in procs)
    for p in procs:
        p.wait(15)

    assert results == ["busy", "busy", "busy", "held"]


def test_processes_appending_concurrently_lose_nothing(tmp_path):
    store = storage.Store(tmp_path / "t.db")
    chat = store.create_chat(None, owner=OWNER)
    script = textwrap.dedent(
        f"""
        import storage
        from models import Message
        store = storage.Store({str(store.path)!r})
        for i in range(25):
            store.append_messages({chat.id!r}, [Message(role="user", content="q"), Message(role="assistant", content="a")], owner={OWNER!r})
        """
    )
    procs = [subprocess.Popen([sys.executable, "-c", script], cwd=ROOT) for _ in range(4)]

    assert [p.wait(60) for p in procs] == [0, 0, 0, 0]
    assert len(store.get_chat(chat.id, owner=OWNER).messages) == 200


# --- a generation that lost its lease ------------------------------------------------------------


def expire(store, chat_id):
    """Makes the lease row look abandoned, without waiting for the TTL."""
    with store._tx() as conn:
        conn.execute("UPDATE generations SET expires=0 WHERE chat_id=?", (chat_id,))


def snapshot(store, chat_id):
    chat = store.get_chat(chat_id, owner=OWNER)
    return chat.model_dump(mode="json")


def test_a_live_lease_saves_through_append_generated(store):
    chat = store.create_chat(None, owner=OWNER)
    lease = store.acquire(chat.id, owner=OWNER)

    saved = store.append_generated(lease, [msg("user", "q"), msg("assistant", "a")], title="q", usage=Usage(prompt_tokens=7))

    assert [m.content for m in saved.messages] == ["q", "a"]
    assert (saved.title, saved.last_usage) == ("q", Usage(prompt_tokens=7))
    lease.release()


def test_an_expired_lease_without_a_replacement_cannot_save(store):
    chat = store.create_chat(None, owner=OWNER)
    lease = store.acquire(chat.id, owner=OWNER)
    expire(store, chat.id)
    before = snapshot(store, chat.id)

    with pytest.raises(storage.LeaseLost):
        store.append_generated(lease, [msg("user", "q"), msg("assistant", "a")], title="q", usage=Usage(prompt_tokens=7))

    assert snapshot(store, chat.id) == before  # no messages, title, usage or updated stamp changed
    lease.release()


def test_a_released_lease_cannot_save(store):
    chat = store.create_chat(None, owner=OWNER)
    lease = store.acquire(chat.id, owner=OWNER)
    lease.release()

    with pytest.raises(storage.LeaseLost):
        store.append_generated(lease, [msg("user", "q"), msg("assistant", "a")])


def test_a_stale_owner_is_rejected_while_the_replacement_saves_and_keeps_its_lease(store):
    chat = store.create_chat(None, owner=OWNER)
    a = store.acquire(chat.id, owner=OWNER)
    expire(store, chat.id)
    b = store.acquire(chat.id, owner=OWNER)
    before = snapshot(store, chat.id)

    with pytest.raises(storage.LeaseLost):
        store.append_generated(a, [msg("user", "from a"), msg("assistant", "from a")], title="a")
    a.release()  # A's cleanup runs after the rejection
    assert store._renew(chat.id, a._token) is False

    assert snapshot(store, chat.id) == before
    with pytest.raises(storage.ChatBusy):  # B still owns the lease
        store.acquire(chat.id, owner=OWNER)
    saved = store.append_generated(b, [msg("user", "from b"), msg("assistant", "from b")])
    assert [m.content for m in saved.messages] == ["from b", "from b"]
    b.release()


def test_an_expired_lease_cannot_be_renewed(store):
    chat = store.create_chat(None, owner=OWNER)
    lease = store.acquire(chat.id, owner=OWNER)
    expire(store, chat.id)

    assert store._renew(chat.id, lease._token) is False

    store.acquire(chat.id, owner=OWNER).release()  # it is free to take over, not revived behind the new owner's back
    lease.release()


def test_a_deleted_chat_is_not_found_rather_than_lease_lost(store):
    chat = store.create_chat(None, owner=OWNER)
    lease = store.acquire(chat.id, owner=OWNER)
    store.delete_chat(chat.id, owner=OWNER)

    with pytest.raises(storage.ChatNotFound):
        store.append_generated(lease, [msg("user", "q"), msg("assistant", "a")])


def test_a_stale_save_does_not_block_other_chats(store):
    a, b = store.create_chat(None, owner=OWNER), store.create_chat(None, owner=OWNER)
    stale, other = store.acquire(a.id, owner=OWNER), store.acquire(b.id, owner=OWNER)
    expire(store, a.id)

    with pytest.raises(storage.LeaseLost):
        store.append_generated(stale, [msg("user", "q"), msg("assistant", "a")])

    assert len(store.append_generated(other, [msg("user", "q"), msg("assistant", "a")]).messages) == 2
    other.release()
