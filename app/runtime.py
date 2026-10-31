"""Process-wide configuration and the chat database, built once at import. Everything else reaches them through here."""

import chat_migration
import e2e
import images
import storage
from app.logs import log
from models import Settings

settings = Settings()
if e2e.enabled():
    settings.data_dir = e2e.data_dir()
    settings.db_file = None  # never the real database
settings.data_dir.mkdir(parents=True, exist_ok=True)
images.prune(settings)
db = storage.Store(settings.database, acquire_wait=2.0)


def import_legacy_chats(db: storage.Store, settings: Settings) -> None:
    """On the first start with a database, brings in chats saved as JSON by earlier releases.

    Runs once (chat_migration records it), so a chat deleted later is not restored by the leftover file. It only
    reads the files; the manual command in deploy/README.md does the same and can be run beforehand to see the report.
    """
    if db.get_meta(chat_migration.LEGACY_IMPORT_KEY):
        return
    if not any(settings.data_dir.glob("*.json")):
        db.set_meta(chat_migration.LEGACY_IMPORT_KEY, "no files")
        return
    report = chat_migration.import_chats(settings.data_dir, db.path, apply=True)
    log.info("Imported %d legacy chats (%d already present)", len(report.imported), len(report.already_present))
    if not report.ok:
        log.warning("%d legacy chat files were skipped or differed after import; run python -m chat_migration import", len(report.skipped) + len(report.mismatched))
