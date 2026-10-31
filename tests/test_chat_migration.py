import hashlib
import json

import pytest

import chat_migration
import storage
from models import Chat, ImageRef, LoreEntry, Message, Source, Usage


def digest(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir()) if p.is_file()}


def rich_chat(cid="a" * 32):
    return Chat(
        id=cid,
        title="Rich",
        messages=[
            Message(role="user", content="Où est le château? ✨", sources=[Source(url="https://x.example", title="X", text="page")], query="q"),
            Message(role="assistant", content="Là-bas [[img:" + "b" * 32 + "]]", images=[ImageRef(id="b" * 32, media_type="image/png", prompt="a castle")]),
        ],
        bible="canon",
        lore=[LoreEntry(id="c" * 32, name="Elara", keys=["elara"], content="ranger", enabled=False)],
        summary="so far",
        summary_upto=1,
        last_usage=Usage(prompt_tokens=77),
        system_prompt="be brief",
        temperature=0.4,
        top_p=0.9,
        frequency_penalty=-1.5,
        max_tokens=500,
        profile_id="p1",
        model="m",
        context_window=8000,
    )


@pytest.fixture
def src(tmp_path):
    folder = tmp_path / "chats"
    folder.mkdir()
    return folder


def write(folder, chat):
    (folder / f"{chat.id}.json").write_text(chat.model_dump_json(indent=2))


def test_import_keeps_every_field_and_the_original_files(src, tmp_path):
    chat = rich_chat()
    write(src, chat)
    before = digest(src)
    db = tmp_path / "lumio.db"

    report = chat_migration.import_chats(src, db, apply=True)

    assert (report.imported, report.ok) == ([chat.id], True)
    assert storage.Store(db).get_chat(chat.id).model_dump(mode="json") == chat.model_dump(mode="json")
    assert digest(src) == before


def test_dry_run_reports_but_writes_nothing(src, tmp_path):
    write(src, rich_chat())
    db = tmp_path / "lumio.db"

    report = chat_migration.import_chats(src, db)

    assert len(report.imported) == 1
    assert not db.exists()


def test_import_can_be_repeated(src, tmp_path):
    write(src, rich_chat())
    db = tmp_path / "lumio.db"
    chat_migration.import_chats(src, db, apply=True)
    storage.Store(db).append_messages("a" * 32, [Message(role="user", content="new"), Message(role="assistant", content="new")])

    report = chat_migration.import_chats(src, db, apply=True)

    assert (report.imported, report.already_present) == ([], ["a" * 32])
    assert len(storage.Store(db).get_chat("a" * 32).messages) == 4  # a re-run never reverts newer chats


def test_unreadable_and_misnamed_files_are_skipped_and_reported_without_blocking_the_rest(src, tmp_path):
    write(src, rich_chat())
    (src / ("e" * 32 + ".json")).write_text("{not json")
    (src / ("f" * 32 + ".json")).write_text(rich_chat("d" * 32).model_dump_json())
    (src / "images").mkdir()

    report = chat_migration.import_chats(src, tmp_path / "lumio.db", apply=True)

    assert report.imported == ["a" * 32]
    assert sorted(report.skipped) == ["e" * 32 + ".json", "f" * 32 + ".json"]
    assert not report.ok


def test_chats_saved_before_newer_fields_existed_import(src, tmp_path):
    old = {"id": "a" * 32, "title": "Old", "created": "2025-01-01T00:00:00Z", "updated": "2025-01-02T00:00:00Z",
           "messages": [{"role": "user", "content": "hi", "created": "2025-01-01T00:00:00Z"}]}
    (src / f"{'a' * 32}.json").write_text(json.dumps(old))

    report = chat_migration.import_chats(src, tmp_path / "lumio.db", apply=True)

    assert report.ok
    loaded = storage.Store(tmp_path / "lumio.db").get_chat("a" * 32)
    assert (loaded.profile_id, loaded.bible, loaded.updated.isoformat()) == (None, "", "2025-01-02T00:00:00+00:00")


def test_listing_order_follows_the_original_updated_times(src, tmp_path):
    for cid, updated in (("1" * 32, "2025-01-01T00:00:00Z"), ("2" * 32, "2025-03-01T00:00:00Z"), ("3" * 32, "2025-02-01T00:00:00Z")):
        write(src, Chat(id=cid, updated=updated))
    chat_migration.import_chats(src, tmp_path / "lumio.db", apply=True)

    assert [c.id[0] for c in storage.Store(tmp_path / "lumio.db").list_chats()] == ["2", "3", "1"]


def test_cli_exit_code_reflects_skipped_files(src, tmp_path, capsys):
    write(src, rich_chat())
    db = tmp_path / "lumio.db"

    assert chat_migration.main(["import", "--from", str(src), "--db", str(db)]) == 0
    assert "Dry run" in capsys.readouterr().out
    (src / ("e" * 32 + ".json")).write_text("{not json")
    assert chat_migration.main(["import", "--from", str(src), "--db", str(db), "--apply"]) == 1


# --- export (rollback) --------------------------------------------------------------------------


def test_export_round_trips_chats_including_ones_changed_after_the_cutover(src, tmp_path):
    write(src, rich_chat())
    db = tmp_path / "lumio.db"
    chat_migration.import_chats(src, db, apply=True)
    store = storage.Store(db)
    store.append_messages("a" * 32, [Message(role="user", content="after"), Message(role="assistant", content="cutover")])
    fresh = store.create_chat("p1")
    out = tmp_path / "export"

    assert chat_migration.export_chats(db, out) == 2

    for cid in ("a" * 32, fresh.id):
        assert Chat.model_validate_json((out / f"{cid}.json").read_text()).model_dump(mode="json") == store.get_chat(cid).model_dump(mode="json")
    assert not list(out.glob("*.tmp"))


def test_export_does_not_overwrite_existing_files_unless_forced(src, tmp_path):
    write(src, rich_chat())
    db = tmp_path / "lumio.db"
    chat_migration.import_chats(src, db, apply=True)
    before = digest(src)

    with pytest.raises(SystemExit):
        chat_migration.export_chats(db, src)

    assert digest(src) == before
    chat_migration.export_chats(db, src, force=True)


def test_export_without_a_database_fails_cleanly(tmp_path):
    with pytest.raises(SystemExit):
        chat_migration.export_chats(tmp_path / "missing.db", tmp_path / "out")


# --- first-start import in the app --------------------------------------------------------------


@pytest.fixture
def app_with(tmp_path, monkeypatch):
    import server

    data = tmp_path / "data"
    data.mkdir()
    store = storage.Store(tmp_path / "app.db")
    monkeypatch.setattr(server.settings, "data_dir", data)
    monkeypatch.setattr(server, "db", store)
    return server, data, store


def test_first_start_imports_json_chats_and_leaves_the_files(app_with):
    server, data, store = app_with
    write(data, rich_chat())
    before = digest(data)

    server.import_legacy_chats()

    assert store.chat_ids() == {"a" * 32}
    assert digest(data) == before


def test_a_chat_deleted_later_is_not_restored_from_its_leftover_file(app_with):
    server, data, store = app_with
    write(data, rich_chat())
    server.import_legacy_chats()
    store.delete_chat("a" * 32)

    server.import_legacy_chats()

    assert store.chat_ids() == set()


def test_a_manual_import_counts_as_done(app_with):
    server, data, store = app_with
    write(data, rich_chat())
    chat_migration.import_chats(data, store.path, apply=True)
    store.delete_chat("a" * 32)

    server.import_legacy_chats()

    assert store.chat_ids() == set()


def test_a_fresh_install_records_that_there_was_nothing_to_import(app_with):
    server, data, store = app_with
    server.import_legacy_chats()
    write(data, rich_chat())  # e.g. files exported for a rollback

    server.import_legacy_chats()

    assert store.chat_ids() == set()


def test_a_dry_run_does_not_count_as_done(app_with):
    server, data, store = app_with
    write(data, rich_chat())

    chat_migration.import_chats(data, store.path)
    server.import_legacy_chats()

    assert store.chat_ids() == {"a" * 32}
