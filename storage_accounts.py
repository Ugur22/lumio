"""Accounts, sessions, invites, login throttling, app login codes and OAuth identities, as Store methods."""

import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from storage_common import _ts

SESSION_DAYS = 30
SESSION_REFRESH = timedelta(days=1)
INVITE_DAYS = 7
LOGIN_WINDOW = 15 * 60.0
LOGIN_MAX_FAILURES = 5
# New accounts are counted when they are created and never credited back, so success is what is limited.
SIGNUP_WINDOW = 24 * 3600.0
SIGNUP_PER_IP = 1
SIGNUP_PER_DAY = 100
SIGNUP_ALL_KEY = "signup:all"  # open sign-ups of the day
SIGNUP_INVITED_KEY = "signup:invited"  # sign-ups with a trial invite
POOLS = ("open", "reserved")
ANCHOR_DAYS = 548  # about 18 months
# Stored as an account's password_hash when it has no password: not an argon2 string, so nothing verifies against it.
UNUSABLE_PASSWORD = "!"


class UsernameTaken(Exception):
    pass


class InvalidInvite(Exception):
    """Unknown, used, expired or revoked; callers must not say which."""


@dataclass(frozen=True)
class Account:
    id: str
    username: str
    password_hash: str
    is_admin: bool
    disabled: bool


class SignupThrottled(Exception):
    def __init__(self, wait: int):
        super().__init__(wait)
        self.wait = wait


class IdentityExists(Exception):
    """Another request linked this sign-in to an account first."""


class SignupFull(SignupThrottled):
    """Not a rate: the pool's sign-ups for today are all taken (the open ones, or the invited ones)."""

    def __init__(self, wait: int, pool: str):
        super().__init__(wait)
        self.pool = pool


class AccountsMixin:
    """Store methods for accounts. Relies on the Store's _tx and _read."""

    # Tokens and invite codes arrive here already hashed; this mixin never sees a plain secret.

    @staticmethod
    def _account(row: sqlite3.Row | None) -> Account | None:
        if row is None:
            return None
        return Account(row["id"], row["username"], row["password_hash"], bool(row["is_admin"]), bool(row["disabled"]))

    def create_user(
        self, username: str, password_hash: str, *, is_admin: bool = False, invite_hash: str | None = None, now: datetime | None = None
    ) -> Account:
        """Redeems the invite (when given) and inserts the user in one transaction: of two registrations with the same code, one wins."""
        now = now or datetime.now(timezone.utc)
        user_id = uuid.uuid4().hex
        with self._tx() as conn:
            if invite_hash is not None:
                used = conn.execute(
                    "UPDATE invites SET used_by=?, used_at=? WHERE code_hash=? AND kind='account' AND used_by IS NULL AND revoked_at IS NULL AND expires>?",
                    (user_id, _ts(now), invite_hash, _ts(now)),
                )
                if used.rowcount == 0:
                    raise InvalidInvite
            try:
                conn.execute(
                    "INSERT INTO users (id, username, password_hash, created, is_admin) VALUES (?,?,?,?,?)",
                    (user_id, username, password_hash, _ts(now), int(is_admin)),
                )
            except sqlite3.IntegrityError:
                raise UsernameTaken(username) from None  # the rollback also un-redeems the invite
        return Account(user_id, username, password_hash, is_admin, False)

    def get_account(self, username: str) -> Account | None:
        with self._read() as conn:
            return self._account(conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone())

    def get_account_by_id(self, user_id: str) -> Account | None:
        with self._read() as conn:
            return self._account(conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())

    def set_password(self, user_id: str, password_hash: str) -> bool:
        with self._tx() as conn:
            return conn.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, user_id)).rowcount > 0

    def disable_user(self, user_id: str) -> bool:
        with self._tx() as conn:
            changed = conn.execute("UPDATE users SET disabled=1 WHERE id=?", (user_id,)).rowcount > 0
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            return changed

    def create_session(self, token_hash: str, user_id: str, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        with self._tx() as conn:
            conn.execute("DELETE FROM sessions WHERE expires<?", (_ts(now),))
            conn.execute(
                "INSERT INTO sessions (token_hash, user_id, created, last_seen, expires) VALUES (?,?,?,?,?)",
                (token_hash, user_id, _ts(now), _ts(now), _ts(now + timedelta(days=SESSION_DAYS))),
            )

    def session_account(self, token_hash: str, now: datetime | None = None) -> tuple[Account, bool] | None:
        """The enabled user behind a live session, and whether its expiry was just pushed out (the cookie should be re-sent).

        Sliding expiry: last_seen and expires are rewritten at most once a day, so a busy session is not a write per request.
        """
        now = now or datetime.now(timezone.utc)
        with self._read() as conn:
            row = conn.execute(
                "SELECT u.*, s.last_seen, s.expires FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash=?",
                (token_hash,),
            ).fetchone()
        if row is None or row["disabled"] or row["expires"] <= _ts(now):
            return None
        refresh = row["last_seen"] is None or row["last_seen"] < _ts(now - SESSION_REFRESH)
        if refresh:
            with self._tx() as conn:
                conn.execute(
                    "UPDATE sessions SET last_seen=?, expires=? WHERE token_hash=?",
                    (_ts(now), _ts(now + timedelta(days=SESSION_DAYS)), token_hash),
                )
        return self._account(row), refresh

    def delete_session(self, token_hash: str) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))

    def delete_other_sessions(self, user_id: str, keep_token_hash: str | None) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM sessions WHERE user_id=? AND token_hash IS NOT ?", (user_id, keep_token_hash))

    # --- login rate limit (in SQLite: several workers share the file) -------------------------

    @staticmethod
    def _login_wait(
        conn: sqlite3.Connection, keys: list[str], now: float, limit: int = LOGIN_MAX_FAILURES, window: float = LOGIN_WINDOW
    ) -> int:
        wait = 0.0
        for key in keys:
            row = conn.execute(
                "SELECT at FROM login_attempts WHERE key=? AND at>? ORDER BY at DESC LIMIT 1 OFFSET ?",
                (key, now - window, limit - 1),
            ).fetchone()
            if row is not None:  # the failure that, once it ages out, brings the count back under the limit
                wait = max(wait, row["at"] + window - now)
        return max(1, int(wait) + 1) if wait > 0 else 0

    @staticmethod
    def _purge_attempts(conn: sqlite3.Connection, now: float) -> None:
        """Signup rows live for a day, login failures for fifteen minutes; each is purged by its own age."""
        conn.execute("DELETE FROM login_attempts WHERE key NOT LIKE 'signup:%' AND at<?", (now - LOGIN_WINDOW,))
        conn.execute("DELETE FROM login_attempts WHERE key LIKE 'signup:%' AND at<?", (now - SIGNUP_WINDOW,))

    def login_wait(self, keys: list[str], now: float | None = None) -> int:
        """Seconds until a login for these keys may be tried again; 0 when none is over the failure limit."""
        now = time.time() if now is None else now
        with self._read() as conn:
            return self._login_wait(conn, keys, now)

    def take_login_attempt(
        self, keys: list[str], now: float | None = None, limit: int = LOGIN_MAX_FAILURES, window: float = LOGIN_WINDOW
    ) -> tuple[int, list[int]]:
        """Checks the limit and records an attempt in one transaction, so parallel guesses cannot all see zero failures.
        Returns (seconds to wait, []) when over the limit and nothing is recorded, else (0, ids of the recorded
        attempts). The caller hands the ids to forget_login_attempts when the attempt turns out to be legitimate."""
        now = time.time() if now is None else now
        with self._tx() as conn:
            self._purge_attempts(conn, now)
            wait = self._login_wait(conn, keys, now, limit, window)
            if wait:
                return wait, []
            ids = [conn.execute("INSERT INTO login_attempts (key, at) VALUES (?,?)", (k, now)).lastrowid for k in keys]
            return 0, ids

    def forget_login_attempts(self, ids: list[int]) -> None:
        with self._tx() as conn:
            conn.executemany("DELETE FROM login_attempts WHERE rowid=?", [(i,) for i in ids])

    def record_login_failure(self, keys: list[str], now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._tx() as conn:
            self._purge_attempts(conn, now)
            conn.executemany("INSERT INTO login_attempts (key, at) VALUES (?,?)", [(k, now) for k in keys])

    def clear_login_failures(self, key: str) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM login_attempts WHERE key=?", (key,))

    # --- sign-in identities and trial tombstones ----------------------------------
    # Only keyed hashes arrive here (see app/routes_oauth.py); a subject id or an email address never touches the database.

    def create_app_login_code(self, code_hash: str, user_id: str, challenge: str, expires_at: float, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._tx() as conn:
            conn.execute("DELETE FROM app_login_codes WHERE expires_at<=?", (now,))
            conn.execute(
                "INSERT INTO app_login_codes (code_hash, user_id, challenge, expires_at) VALUES (?,?,?,?)",
                (code_hash, user_id, challenge, expires_at),
            )

    def take_app_login_code(self, code_hash: str, now: float | None = None) -> tuple[str, str] | None:
        """Deletes the code and returns (user_id, challenge) if it existed and had not expired. The write lock is taken up
        front, so of two parallel calls with the same code exactly one sees the row."""
        now = time.time() if now is None else now
        with self._tx() as conn:
            conn.execute("DELETE FROM app_login_codes WHERE expires_at<=?", (now,))
            row = conn.execute("SELECT user_id, challenge FROM app_login_codes WHERE code_hash=?", (code_hash,)).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM app_login_codes WHERE code_hash=?", (code_hash,))
            return row["user_id"], row["challenge"]

    def find_identity(self, provider: str, subject_hmac: str) -> Account | None:
        with self._read() as conn:
            return self._account(
                conn.execute(
                    "SELECT u.* FROM identities i JOIN users u ON u.id = i.user_id WHERE i.provider=? AND i.subject_hmac=?",
                    (provider, subject_hmac),
                ).fetchone()
            )

    def enrol_oauth_user(
        self,
        provider: str,
        subject_hmac: str,
        anchors: list[tuple[str, str]],
        *,
        trial_calls: int,
        ip_key: str,
        ip_limit: int | None = None,
        day_limit: int | None = None,
        invite_hash: str | None = None,
        now: datetime | None = None,
    ) -> tuple[Account, bool]:
        """Creates a passwordless account for a sign-in that is new, and returns it with whether it got a trial.

        `anchors` are (kind, hmac) pairs. The trial is granted only if none of them is already a tombstone. The throttle
        check and its record, the account, its identity, the tombstones and the trial all commit together or not at all.

        Without an invite this is an open sign-up: one per address per day, and `day_limit` of them per day, and the trial
        draws on the open pool. With a trial invite there is no per-address limit, `day_limit` is the invited sign-ups of
        the day, the trial draws on the reserved pool, and the invite is redeemed here in the same transaction. A person who
        already had a trial gets the account without one and keeps the invite.
        Raises SignupThrottled, SignupFull, InvalidInvite and IdentityExists."""
        now = now or datetime.now(timezone.utc)
        stamp = now.timestamp()
        user_id = uuid.uuid4().hex
        invited = invite_hash is not None
        pool = "reserved" if invited else "open"
        all_key = SIGNUP_INVITED_KEY if invited else SIGNUP_ALL_KEY
        with self._tx() as conn:
            self._purge_attempts(conn, stamp)
            # Today's sign-ups first: when the pool is full that is what the person should be told, whatever their address.
            limit = SIGNUP_PER_DAY if day_limit is None else day_limit
            if limit <= 0:  # a pool too small for one trial (its share is 0, or the daily cap is tiny)
                raise SignupFull(int(SIGNUP_WINDOW), pool)
            if wait := self._login_wait(conn, [all_key], stamp, limit, SIGNUP_WINDOW):
                raise SignupFull(wait, pool)
            if not invited and (wait := self._login_wait(conn, [ip_key], stamp, ip_limit or SIGNUP_PER_IP, SIGNUP_WINDOW)):
                raise SignupThrottled(wait)
            if invited and not conn.execute(
                "SELECT 1 FROM invites WHERE code_hash=? AND kind='trial' AND used_by IS NULL AND revoked_at IS NULL AND expires>?", (invite_hash, _ts(now))
            ).fetchone():
                raise InvalidInvite
            conn.executemany(
                "INSERT INTO login_attempts (key, at) VALUES (?,?)", [(all_key, stamp)] if invited else [(ip_key, stamp), (all_key, stamp)]
            )

            conn.execute("DELETE FROM trial_anchors WHERE expires_at<=?", (_ts(now),))
            hashes = [h for _, h in anchors]
            marks = ",".join("?" * len(hashes))
            seen = bool(hashes) and conn.execute(f"SELECT 1 FROM trial_anchors WHERE anchor_hmac IN ({marks}) LIMIT 1", hashes).fetchone()
            grant = not seen

            for _ in range(10):
                username = f"user-{secrets.token_hex(3)}"
                try:
                    conn.execute(
                        "INSERT INTO users (id, username, password_hash, created, is_admin) VALUES (?,?,?,?,0)",
                        (user_id, username, UNUSABLE_PASSWORD, _ts(now)),
                    )
                    break
                except sqlite3.IntegrityError:
                    continue  # a taken name; the id is fresh, so only the username can collide
            else:
                raise RuntimeError("could not find a free generated username")
            try:
                conn.execute("INSERT INTO identities (user_id, provider, subject_hmac) VALUES (?,?,?)", (user_id, provider, subject_hmac))
            except sqlite3.IntegrityError:
                raise IdentityExists from None  # the rollback also keeps the invite
            expires = _ts(now + timedelta(days=ANCHOR_DAYS))
            conn.executemany(
                "INSERT OR IGNORE INTO trial_anchors (anchor_hmac, kind, first_at, expires_at) VALUES (?,?,?,?)",
                [(h, kind, _ts(now), expires) for kind, h in anchors],
            )
            if grant:
                if invited and not conn.execute(
                    "UPDATE invites SET used_by=?, used_at=? WHERE code_hash=? AND kind='trial' AND used_by IS NULL AND revoked_at IS NULL AND expires>?",
                    (user_id, _ts(now), invite_hash, _ts(now)),
                ).rowcount:
                    raise InvalidInvite
                conn.execute(
                    "INSERT INTO trials (user_id, call_limit, used, created, pool) VALUES (?,?,0,?,?)", (user_id, trial_calls, _ts(now), pool)
                )
        return Account(user_id, username, UNUSABLE_PASSWORD, False, False), grant
