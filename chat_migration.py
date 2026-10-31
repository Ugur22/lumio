"""Moves chats between the legacy JSON files and the SQLite database.

    python -m chat_migration import [--from DIR] [--db FILE] [--apply]
    python -m chat_migration export --to DIR [--db FILE] [--force]

`import` is a dry run unless --apply is given. It never changes or deletes the JSON files, skips chats already
in the database (so it can be re-run), and compares every imported chat with its source afterwards.
`export` writes one JSON file per chat in the old format, for rolling back to a release that reads JSON.
"""

import argparse
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

import storage
from models import Chat, Settings, utcnow


LEGACY_IMPORT_KEY = "legacy_import"


@dataclass
class Report:
    imported: list[str] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)  # file name -> reason
    mismatched: list[str] = field(default_factory=list)  # imported but not identical on read-back

    @property
    def ok(self) -> bool:
        return not self.skipped and not self.mismatched


def read_chats(src: Path) -> tuple[list[Chat], dict[str, str]]:
    chats, skipped = [], {}
    for path in sorted(src.glob("*.json")):
        try:
            chat = Chat.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValidationError, UnicodeDecodeError, OSError) as e:
            skipped[path.name] = f"unreadable ({type(e).__name__})"
            continue
        if path.stem != chat.id:
            skipped[path.name] = "file name does not match the chat id"
            continue
        chats.append(chat)
    return chats, skipped


def import_chats(src: Path, db_path: Path, apply: bool = False) -> Report:
    chats, skipped = read_chats(src)
    report = Report(skipped=skipped)
    # A dry run must not create the database, so it only looks at one that already exists.
    store = storage.Store(db_path) if apply or db_path.exists() else None
    present = store.chat_ids() if store else set()
    for chat in chats:
        if chat.id in present:
            report.already_present.append(chat.id)
        elif not apply:
            report.imported.append(chat.id)
        elif store.insert_chat(chat):
            report.imported.append(chat.id)
            if store.get_chat(chat.id).model_dump(mode="json") != chat.model_dump(mode="json"):
                report.mismatched.append(chat.id)
        else:
            report.already_present.append(chat.id)  # created by a running app between the check and the insert
    if apply:
        # Tells the app's first-start import that this has been dealt with, so deleted chats never come back.
        store.set_meta(LEGACY_IMPORT_KEY, utcnow().isoformat())
    return report


def export_chats(db_path: Path, dest: Path, force: bool = False) -> int:
    if not db_path.exists():
        raise SystemExit(f"No database at {db_path}")
    store = storage.Store(db_path)
    dest.mkdir(parents=True, exist_ok=True)
    summaries = store.list_chats()
    clashes = [s.id for s in summaries if (dest / f"{s.id}.json").exists()]
    if clashes and not force:
        raise SystemExit(f"{len(clashes)} files already exist in {dest}; export to an empty directory, or pass --force")
    for summary in summaries:
        chat = store.get_chat(summary.id)
        # Written beside the target and renamed, so a crash never leaves a half-written chat file.
        fd, tmp = tempfile.mkstemp(dir=dest, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(chat.model_dump_json(indent=2))
        os.replace(tmp, dest / f"{chat.id}.json")
    return len(summaries)


def main(argv: list[str] | None = None) -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(prog="chat_migration", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import", help="JSON files -> database (dry run unless --apply)")
    imp.add_argument("--from", dest="src", type=Path, default=settings.data_dir, help="directory with <id>.json files")
    imp.add_argument("--db", type=Path, default=settings.database)
    imp.add_argument("--apply", action="store_true", help="write to the database")
    exp = sub.add_parser("export", help="database -> JSON files")
    exp.add_argument("--to", dest="dest", type=Path, required=True)
    exp.add_argument("--db", type=Path, default=settings.database)
    exp.add_argument("--force", action="store_true", help="overwrite files that already exist in --to")
    args = parser.parse_args(argv)

    if args.command == "export":
        print(f"Exported {export_chats(args.db, args.dest, args.force)} chats to {args.dest}")
        return 0

    report = import_chats(args.src, args.db, args.apply)
    verb = "Imported" if args.apply else "Would import"
    print(f"{verb} {len(report.imported)} chats; {len(report.already_present)} already in {args.db}; {len(report.skipped)} skipped")
    for name, reason in report.skipped.items():
        print(f"  skipped {name}: {reason}", file=sys.stderr)
    for chat_id in report.mismatched:
        print(f"  MISMATCH after import: {chat_id}", file=sys.stderr)
    if not args.apply:
        print("Dry run: nothing was written. Re-run with --apply.")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
