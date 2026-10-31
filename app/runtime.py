"""Process-wide configuration and the chat database, built once at import. Everything else reaches them through here."""

import os

import chat_migration
import e2e
import images
import profile_store
import secret_store
import storage
from app.logs import log
from models import Settings, UserView

# Settings that only make sense on a server. Local development, main.py and the tests never set them, so seeing one
# without DOLPHINLLM_PUBLIC_HOST means the host name is missing or misspelt rather than that this is a local run.
# Deliberately not included: DOLPHINLLM_DB_FILE, DATA_DIR, PROFILES_FILE and LOG_FILE, which are also used for
# local runs and for the chat_migration commands.
SERVER_ENV = (secret_store.SECRETS_FILE_ENV, secret_store.SECRET_KEY_ENV, secret_store.SECRET_KEY_FILE_ENV)


def server_signals(settings: Settings) -> list[str]:
    """Names of the settings that say this is a server. Never values."""
    found = [name for name in SERVER_ENV if os.environ.get(name, "").strip()]
    if (settings.admin_user or "").strip():
        found.append("DOLPHINLLM_ADMIN_USER")
    return found


def refuse_half_configured_server(settings: Settings) -> None:
    """Exits when a server-only setting is present but DOLPHINLLM_PUBLIC_HOST is not. Without the host the app treats
    every request as the fixed local user with no login, and the startup claim would hand the saved chats to it."""
    if settings.deployed:
        return
    if signals := server_signals(settings):
        raise SystemExit(
            f"{', '.join(signals)} {'is' if len(signals) == 1 else 'are'} set, which means this is a server, but DOLPHINLLM_PUBLIC_HOST is not. "
            "Refusing to start: without it every visitor would be the local user, with no login. "
            "Set DOLPHINLLM_PUBLIC_HOST to the public host name (check its spelling), or remove the server settings for a local run."
        )


settings = Settings()
refuse_half_configured_server(settings)
if e2e.enabled():
    settings.data_dir = e2e.data_dir()
    settings.db_file = None  # never the real database
settings.data_dir.mkdir(parents=True, exist_ok=True)
images.prune(settings)
db = storage.Store(settings.database, acquire_wait=2.0)


def claim_owner(db: storage.Store, settings: Settings) -> str:
    """Who takes chats that have no owner: the fixed local user, or on a server the user named by DOLPHINLLM_ADMIN_USER.

    Exits with a message when that is unset or unknown, because the alternative is leaving the chats readable by
    everyone or silently giving them to someone."""
    if not settings.deployed:
        refuse_half_configured_server(settings)  # also guards a caller that did not go through startup
        return "local"
    name = (settings.admin_user or "").strip().lower()
    if not name:
        raise SystemExit("Chats without an owner exist. Set DOLPHINLLM_ADMIN_USER to the account that should own them (create it with: python -m accounts create-user NAME --admin).")
    account = db.get_account(name)
    if account is None:
        raise SystemExit(f"DOLPHINLLM_ADMIN_USER is {name!r}, but no such account exists. Create it with: python -m accounts create-user {name} --admin")
    return account.id


def claim_unowned_chats(db: storage.Store, settings: Settings) -> None:
    """Gives chats from before accounts existed to claim_owner(); does nothing (and needs no setting) when there are none."""
    if db.count_unowned() == 0:
        return
    owner = claim_owner(db, settings)
    log.info("Gave %d chats without an owner to %s", db.claim_unowned(owner), owner)


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
    # Resolved before anything is inserted, so a refusal to start leaves no unclaimed chats behind.
    report = chat_migration.import_chats(settings.data_dir, db.path, apply=True, owner=claim_owner(db, settings))
    log.info("Imported %d legacy chats (%d already present)", len(report.imported), len(report.already_present))
    if not report.ok:
        log.warning("%d legacy chat files were skipped or differed after import; run python -m chat_migration import", len(report.skipped) + len(report.mismatched))


def migrate_profiles_to_admin(db: storage.Store, settings: Settings) -> None:
    """Once, on a server: hands the global profiles file and keys from before accounts to the admin account.

    Does nothing (and records nothing) until DOLPHINLLM_ADMIN_USER names an existing account, and never stops startup:
    on any failure the originals stay where they are and the next start tries again."""
    if not settings.deployed or db.get_meta(profile_store.MIGRATION_KEY):
        return
    name = (settings.admin_user or "").strip().lower()
    account = db.get_account(name) if name else None
    if account is None:
        return
    admin = UserView(id=account.id, username=account.username, is_admin=account.is_admin)
    try:
        moved = profile_store.migrate_global_to_user(settings, admin)
    except Exception as e:
        # Only the exception type: a keychain error message could echo more than we want in a log.
        log.warning("Could not move the global profiles to the admin; they stay where they are", extra={"error": type(e).__name__})
        return
    db.set_meta(profile_store.MIGRATION_KEY, account.id)
    log.info("Moved %d provider profiles and keys to the admin account", len(moved), extra={"moved": moved})
