import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

import storage
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
    chat = store.create_chat(None)

    def worker(n):
        return lambda: [store.append_messages(chat.id, [msg("user", f"{n}-{i}"), msg("assistant", f"r{n}-{i}")]) for i in range(10)]

    run_threads([worker(n) for n in range(8)])

    loaded = store.get_chat(chat.id)
    assert len(loaded.messages) == 160
    with store._read() as conn:
        seqs = [r[0] for r in conn.execute("SELECT seq FROM messages WHERE chat_id=? ORDER BY seq", (chat.id,))]
    assert seqs == list(range(160))
    # Each turn stays adjacent: the user message is always followed by its own reply.
    pairs = [(a.content, b.content) for a, b in zip(loaded.messages[::2], loaded.messages[1::2])]
    assert all(a.startswith(tuple("01234567")) and b == "r" + a for a, b in pairs)


def test_settings_edits_and_appends_in_parallel_all_survive(store):
    chat = store.create_chat(None)
    lore = [LoreEntry(id="a" * 32, name="Elara", keys=["elara"], content="ranger")]

    run_threads(
        [
            lambda: [store.append_messages(chat.id, [msg("user", "q"), msg("assistant", "a")]) for _ in range(20)],
            lambda: [store.rename(chat.id, f"title {i}") for i in range(20)],
            lambda: [store.update_story(chat.id, f"bible {i}", lore) for i in range(20)],
            lambda: [store.update_behavior(chat.id, {"system_prompt": f"p{i}", "temperature": 0.5}, False, None) for i in range(20)],
        ]
    )

    loaded = store.get_chat(chat.id)
    assert len(loaded.messages) == 40
    assert (loaded.title, loaded.bible, loaded.system_prompt) == ("title 19", "bible 19", "p19")
    assert loaded.lore == lore and loaded.temperature == 0.5


def test_append_from_a_stale_snapshot_does_not_revert_settings(store):
    chat = store.create_chat(None)
    stale = store.get_chat(chat.id)

    store.update_story(chat.id, "new bible", [])
    store.rename(chat.id, "Renamed")
    store.append_messages(stale.id, [msg("user", "q"), msg("assistant", "a")], title="from the first message")

    loaded = store.get_chat(chat.id)
    assert (loaded.bible, loaded.title, len(loaded.messages)) == ("new bible", "Renamed", 2)


def test_settings_update_leaves_messages_and_other_settings_alone(store):
    chat = store.create_chat("p1")
    store.append_messages(chat.id, [msg("user", "q"), msg("assistant", "a")])
    store.update_story(chat.id, "bible", [])

    store.update_behavior(chat.id, {"system_prompt": "be brief", "temperature": 0.2}, False, None)

    loaded = store.get_chat(chat.id)
    assert (loaded.bible, loaded.profile_id, len(loaded.messages)) == ("bible", "p1", 2)


def test_usage_is_dropped_when_settings_changed_since_the_send(store):
    chat = store.create_chat(None)
    _, rev = store.get_chat_rev(chat.id)
    store.update_story(chat.id, "changed meanwhile", [])

    store.append_messages(chat.id, [msg("user", "q"), msg("assistant", "a")], usage=Usage(prompt_tokens=99), rev=rev)
    assert store.get_chat(chat.id).last_usage is None

    _, rev = store.get_chat_rev(chat.id)
    store.append_messages(chat.id, [msg("user", "q"), msg("assistant", "a")], usage=Usage(prompt_tokens=99), rev=rev)
    assert store.get_chat(chat.id).last_usage == Usage(prompt_tokens=99)


def test_append_to_a_deleted_chat_raises_and_does_not_recreate_it(store):
    chat = store.create_chat(None)
    store.delete_chat(chat.id)

    with pytest.raises(storage.ChatNotFound):
        store.append_messages(chat.id, [msg("user", "q"), msg("assistant", "a")])

    assert store.chat_ids() == set()
    with store._read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0


def test_delete_removes_messages_and_the_lease(store):
    chat = store.create_chat(None)
    store.append_messages(chat.id, [msg("user", "q"), msg("assistant", "a")])
    lease = store.acquire(chat.id)

    store.delete_chat(chat.id)
    lease.release()

    with store._read() as conn:
        assert [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("chats", "messages", "generations")] == [0, 0, 0]


def test_summary_is_checked_against_the_messages_in_the_same_transaction(store):
    chat = store.create_chat(None)
    store.append_messages(chat.id, [msg("user", "q"), msg("assistant", "a")])

    with pytest.raises(storage.InvalidUpdate, match="beyond"):
        store.update_summary(chat.id, "s", 3)
    with pytest.raises(storage.InvalidUpdate, match="Write a summary"):
        store.update_summary(chat.id, " ", 1)
    assert store.update_summary(chat.id, "s", 2).summary_upto == 2


def test_a_database_from_a_newer_build_is_refused(tmp_path):
    path = tmp_path / "future.db"
    storage.Store(path)
    with storage.Store(path)._tx() as conn:
        conn.execute(f"PRAGMA user_version={storage.SCHEMA_VERSION + 1}")

    with pytest.raises(RuntimeError, match="schema version"):
        storage.Store(path)


# --- generation leases --------------------------------------------------------------------------


def test_only_one_lease_per_chat_but_other_chats_are_free(store):
    a, b = store.create_chat(None), store.create_chat(None)
    lease = store.acquire(a.id)

    with pytest.raises(storage.ChatBusy):
        store.acquire(a.id)
    other = store.acquire(b.id)

    lease.release()
    store.acquire(a.id).release()
    other.release()


def test_acquire_on_a_missing_chat_is_not_found(store):
    with pytest.raises(storage.ChatNotFound):
        store.acquire("f" * 32)


def test_release_is_idempotent(store):
    chat = store.create_chat(None)
    lease = store.acquire(chat.id)
    lease.release()
    lease.release()
    store.acquire(chat.id).release()


def test_an_expired_lease_is_taken_over_and_the_old_owner_cannot_release_the_new_one(tmp_path):
    store = storage.Store(tmp_path / "t.db", lease_ttl=0.2, lease_beat=60)
    chat = store.create_chat(None)
    old = store.acquire(chat.id)
    time.sleep(0.3)

    new = store.acquire(chat.id)
    old.release()  # fenced by its token: the row now belongs to `new`

    with pytest.raises(storage.ChatBusy):
        store.acquire(chat.id)
    new.release()


def test_a_live_lease_is_renewed_past_its_ttl(tmp_path):
    store = storage.Store(tmp_path / "t.db", lease_ttl=0.4, lease_beat=0.1)
    chat = store.create_chat(None)
    lease = store.acquire(chat.id)

    time.sleep(1.0)

    with pytest.raises(storage.ChatBusy):
        store.acquire(chat.id)
    lease.release()


def holder_script(db, chat_id, ttl, then):
    return textwrap.dedent(
        f"""
        import os, signal, sys, time
        import storage
        store = storage.Store({str(db)!r}, lease_ttl={ttl}, lease_beat=0.2)
        try:
            store.acquire({chat_id!r})
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
    chat = store.create_chat(None)
    proc = spawn(holder_script(store.path, chat.id, 1.0, "os.kill(os.getpid(), signal.SIGKILL)"))
    assert proc.stdout.readline().strip() == "held"
    proc.wait(10)

    with pytest.raises(storage.ChatBusy):  # not yet: we cannot know the owner is dead
        store.acquire(chat.id)
    time.sleep(1.2)

    store.acquire(chat.id).release()


def test_processes_racing_for_one_chat_produce_exactly_one_winner(tmp_path):
    store = storage.Store(tmp_path / "t.db")
    chat = store.create_chat(None)
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
    chat = store.create_chat(None)
    script = textwrap.dedent(
        f"""
        import storage
        from models import Message
        store = storage.Store({str(store.path)!r})
        for i in range(25):
            store.append_messages({chat.id!r}, [Message(role="user", content="q"), Message(role="assistant", content="a")])
        """
    )
    procs = [subprocess.Popen([sys.executable, "-c", script], cwd=ROOT) for _ in range(4)]

    assert [p.wait(60) for p in procs] == [0, 0, 0, 0]
    assert len(store.get_chat(chat.id).messages) == 200
