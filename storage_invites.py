"""Invites, as Store methods: creating, checking, listing and revoking. Redeeming one happens inside the sign-up transactions in
storage_accounts.py, which refuse a revoked invite the same way they refuse a used one."""

import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from storage_accounts import INVITE_DAYS
from storage_common import _ts

MAX_LISTED = 500

# `id` is a random handle for the admin list and for revoking; it has no relation to the code, whose hash is the key.
INVITES_TABLE = """CREATE TABLE IF NOT EXISTS invites (
        code_hash TEXT PRIMARY KEY,
        created TEXT,
        expires TEXT,
        used_by TEXT,
        used_at TEXT,
        kind TEXT NOT NULL DEFAULT 'account',
        id TEXT,
        note TEXT,
        created_by TEXT,
        revoked_at TEXT
    )"""

# revoked beats used beats expired: the strongest reason is the one reported.
_STATUS = "CASE WHEN revoked_at IS NOT NULL THEN 'revoked' WHEN used_by IS NOT NULL THEN 'used' WHEN expires<=? THEN 'expired' ELSE 'unused' END"


def upgrade_invites(conn: sqlite3.Connection) -> None:
    """Version 5. Older rows get a random id here, so they can be listed and revoked like new ones; note and creator stay NULL."""
    have = {r["name"] for r in conn.execute("PRAGMA table_info(invites)")}
    for column in ("id", "note", "created_by", "revoked_at"):
        if column not in have:
            conn.execute(f"ALTER TABLE invites ADD COLUMN {column} TEXT")
    conn.execute("UPDATE invites SET id=lower(hex(randomblob(8))) WHERE id IS NULL")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS invites_id ON invites(id)")


class InvitesMixin:
    """Store methods for invites. Relies on the Store's _tx and _read. Codes arrive hashed."""

    def create_invite(
        self,
        code_hash: str,
        days: float = INVITE_DAYS,
        now: datetime | None = None,
        kind: str = "account",
        *,
        note: str | None = None,
        created_by: str | None = None,
    ) -> str:
        """kind 'account' is for password registration, 'trial' for the OAuth sign-up that draws on the reserved trial pool.
        Returns the invite's id."""
        now = now or datetime.now(timezone.utc)
        invite_id = secrets.token_hex(8)
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO invites (code_hash, created, expires, kind, id, note, created_by) VALUES (?,?,?,?,?,?,?)",
                (code_hash, _ts(now), _ts(now + timedelta(days=days)), kind, invite_id, note, created_by),
            )
        return invite_id

    def invite_valid(self, code_hash: str, kind: str, now: datetime | None = None) -> bool:
        """Whether the invite could be redeemed right now. Does not redeem it."""
        now = now or datetime.now(timezone.utc)
        with self._read() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM invites WHERE code_hash=? AND kind=? AND used_by IS NULL AND revoked_at IS NULL AND expires>?",
                    (code_hash, kind, _ts(now)),
                ).fetchone()
                is not None
            )

    def invite_state(self, code_hash: str, now: datetime | None = None) -> tuple[str, str] | None:
        """(kind, status) of the invite, status being unused, used, expired or revoked; None for a code that does not exist."""
        now = now or datetime.now(timezone.utc)
        with self._read() as conn:
            row = conn.execute(f"SELECT kind, {_STATUS} AS status FROM invites WHERE code_hash=?", (_ts(now), code_hash)).fetchone()
        return (row["kind"], row["status"]) if row else None

    def list_invites(self, now: datetime | None = None) -> list[dict]:
        """Newest first. Never includes the code or its hash."""
        now = now or datetime.now(timezone.utc)
        with self._read() as conn:
            rows = conn.execute(
                f"SELECT id, kind, note, created, expires, used_at, {_STATUS} AS status FROM invites"
                " ORDER BY created DESC, rowid DESC LIMIT ?",
                (_ts(now), MAX_LISTED),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_invite(self, invite_id: str, now: datetime | None = None) -> dict | None:
        now = now or datetime.now(timezone.utc)
        with self._read() as conn:
            row = conn.execute(
                f"SELECT id, kind, note, created, expires, used_at, {_STATUS} AS status FROM invites WHERE id=?", (_ts(now), invite_id)
            ).fetchone()
        return dict(row) if row else None

    def revoke_invite(self, invite_id: str, now: datetime | None = None) -> str:
        """'revoked' (also when it already was), 'used' (a used invite stays as history) or 'missing'."""
        now = now or datetime.now(timezone.utc)
        with self._tx() as conn:
            row = conn.execute("SELECT used_by, revoked_at FROM invites WHERE id=?", (invite_id,)).fetchone()
            if row is None:
                return "missing"
            if row["used_by"] is not None:
                return "used"
            if row["revoked_at"] is None:
                conn.execute("UPDATE invites SET revoked_at=? WHERE id=?", (_ts(now), invite_id))
            return "revoked"
