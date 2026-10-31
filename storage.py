"""SQLite storage for chats.

Every operation opens its own connection and runs one short transaction, so nothing here is ever held
open across an LLM call or a stream. Writers touch only the columns they mean to change and messages are
appended, so concurrent requests (threads or Uvicorn workers) cannot overwrite each other's work.
"""

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from models import Chat, ChatSummary, ImageRef, LoreEntry, Message, Usage, utcnow

log = logging.getLogger("dolphinllm")

# 2: accounts (users, sessions, invites, login_attempts tables and chats.owner). The release before accounts understands 1
# and refuses a newer file, so rolling back onto this database fails loudly instead of serving every user's chats unscoped.
SCHEMA_VERSION = 2
DEFAULT_TITLE = "New chat"
BUSY_SECONDS = 10.0
# A generation lease that is not renewed for this long is treated as left behind by a crashed process.
LEASE_TTL = 60.0
LEASE_BEAT = 15.0

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS chats (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        created TEXT NOT NULL,
        updated TEXT NOT NULL,
        bible TEXT NOT NULL DEFAULT '',
        lore TEXT NOT NULL DEFAULT '[]',
        summary TEXT NOT NULL DEFAULT '',
        summary_upto INTEGER NOT NULL DEFAULT 0,
        last_usage INTEGER,
        system_prompt TEXT NOT NULL DEFAULT '',
        temperature REAL,
        top_p REAL,
        frequency_penalty REAL,
        max_tokens INTEGER,
        profile_id TEXT,
        model TEXT,
        context_window INTEGER,
        settings_rev INTEGER NOT NULL DEFAULT 0,
        owner TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS messages (
        chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
        seq INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created TEXT NOT NULL,
        images TEXT NOT NULL DEFAULT '[]',
        sources TEXT NOT NULL DEFAULT '[]',
        query TEXT,
        PRIMARY KEY (chat_id, seq)
    ) WITHOUT ROWID""",
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS generations (
        chat_id TEXT PRIMARY KEY REFERENCES chats(id) ON DELETE CASCADE,
        token TEXT NOT NULL,
        pid INTEGER NOT NULL,
        expires REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash TEXT NOT NULL,
        created TEXT NOT NULL,
        disabled INTEGER NOT NULL DEFAULT 0,
        is_admin INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created TEXT,
        last_seen TEXT,
        expires TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id)",
    """CREATE TABLE IF NOT EXISTS invites (
        code_hash TEXT PRIMARY KEY,
        created TEXT,
        expires TEXT,
        used_by TEXT,
        used_at TEXT
    )""",
    "CREATE TABLE IF NOT EXISTS login_attempts (key TEXT, at REAL)",
    "CREATE INDEX IF NOT EXISTS login_attempts_key ON login_attempts(key, at)",
]

# Run after the column upgrade in _init: on a database that predates `owner` the index cannot exist before the column does.
_INDEXES = ["CREATE INDEX IF NOT EXISTS chats_owner ON chats(owner)"]

SESSION_DAYS = 30
SESSION_REFRESH = timedelta(days=1)
INVITE_DAYS = 7
LOGIN_WINDOW = 15 * 60.0
LOGIN_MAX_FAILURES = 5


_UPDATABLE = {
    "title", "updated", "bible", "lore", "summary", "summary_upto", "last_usage", "system_prompt",
    "temperature", "top_p", "frequency_penalty", "max_tokens", "profile_id", "model", "context_window",
}  # fmt: skip


class ChatNotFound(Exception):
    pass


class ChatBusy(Exception):
    """A reply is already being generated in this chat."""


class LeaseLost(Exception):
    """The generation no longer holds its chat's lease (it expired or another request took over), so its reply is not saved."""


class UsernameTaken(Exception):
    pass


class InvalidInvite(Exception):
    """Unknown, used or expired; callers must not say which."""


@dataclass(frozen=True)
class Account:
    id: str
    username: str
    password_hash: str
    is_admin: bool
    disabled: bool


class InvalidUpdate(Exception):
    """The update is not valid for the chat as it is now; the message is shown to the user."""


def _ts(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)  # the app only ever wrote UTC; never guess the machine's zone
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


class Lease:
    """The right to generate in one chat. Renewed by a thread until released, so a slow web lookup,
    a long stream or a stalled event loop cannot let it lapse; a crashed process stops renewing and it expires."""

    def __init__(self, store: "Store", chat_id: str, token: str, owner: str):
        self.chat_id = chat_id
        self.owner = owner  # whoever acquired it; the save re-checks that this user still owns the chat
        self._store = store
        self._token = token
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._beat, name=f"lease-{chat_id[:8]}", daemon=True)

    def _beat(self) -> None:
        while not self._stop.wait(self._store.lease_beat):
            try:
                if not self._store._renew(self.chat_id, self._token):
                    log.warning("Generation lease for chat %s was lost", self.chat_id)
                    return
            except sqlite3.Error:
                log.warning("Could not renew the generation lease for chat %s", self.chat_id)

    def holds(self, conn: sqlite3.Connection) -> bool:
        """Whether this lease is still the chat's live one. Only meaningful inside the transaction that acts on it."""
        row = conn.execute("SELECT token, expires FROM generations WHERE chat_id=?", (self.chat_id,)).fetchone()
        return row is not None and row["token"] == self._token and row["expires"] > time.time()

    def release(self) -> None:
        """Idempotent and safe after the lease expired or was taken over: only deletes its own row."""
        if self._stop.is_set():
            return
        self._stop.set()
        try:
            self._store._release(self.chat_id, self._token)
        except sqlite3.Error:
            log.warning("Could not release the generation lease for chat %s; it expires on its own", self.chat_id)


class Store:
    def __init__(self, path: Path, lease_ttl: float = LEASE_TTL, lease_beat: float = LEASE_BEAT, acquire_wait: float = 0.0):
        self.path = Path(path)
        # How long acquire() waits for a held lease before giving up: Stop followed by an instant resend
        # reaches the server while the stopped request is still saving its partial reply.
        self.acquire_wait = acquire_wait
        self.lease_ttl = lease_ttl
        self.lease_beat = lease_beat
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    # --- connections ------------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=BUSY_SECONDS, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """One write transaction. IMMEDIATE takes the write lock up front, so a read-then-write never deadlocks."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        """A snapshot, so a chat and its messages are read consistently."""
        conn = self._connect()
        try:
            conn.execute("BEGIN")
            yield conn
        finally:
            conn.close()

    def _init(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")  # persistent: readers never block the writer
            conn.execute("BEGIN IMMEDIATE")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                conn.execute("ROLLBACK")
                raise RuntimeError(f"{self.path} has schema version {version}; this build understands {SCHEMA_VERSION}")
            for statement in _SCHEMA:
                conn.execute(statement)
            if "owner" not in {r["name"] for r in conn.execute("PRAGMA table_info(chats)")}:
                conn.execute("ALTER TABLE chats ADD COLUMN owner TEXT")  # chats from before accounts stay NULL until claimed at startup
            for statement in _INDEXES:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            conn.execute("COMMIT")
        finally:
            conn.close()

    # --- reading ----------------------------------------------------------------------------

    @staticmethod
    def _load(conn: sqlite3.Connection, chat_id: str, owner: str | None) -> tuple[Chat, int]:
        """`owner` None matches nothing (SQL NULL never equals), so a missing owner can never read another user's chat.
        Another user's chat is reported exactly like a missing one."""
        row = conn.execute("SELECT * FROM chats WHERE id=? AND owner=?", (chat_id, owner)).fetchone()
        if row is None:
            raise ChatNotFound(chat_id)
        return Store._build(conn, row)

    @staticmethod
    def _build(conn: sqlite3.Connection, row: sqlite3.Row) -> tuple[Chat, int]:
        chat_id = row["id"]
        messages = [
            Message(
                role=m["role"],
                content=m["content"],
                created=m["created"],
                images=json.loads(m["images"]),
                sources=json.loads(m["sources"]),
                query=m["query"],
            )
            for m in conn.execute("SELECT * FROM messages WHERE chat_id=? ORDER BY seq", (chat_id,))
        ]
        chat = Chat(
            id=row["id"],
            title=row["title"],
            created=row["created"],
            updated=row["updated"],
            messages=messages,
            bible=row["bible"],
            lore=json.loads(row["lore"]),
            summary=row["summary"],
            summary_upto=row["summary_upto"],
            last_usage=None if row["last_usage"] is None else Usage(prompt_tokens=row["last_usage"]),
            system_prompt=row["system_prompt"],
            temperature=row["temperature"],
            top_p=row["top_p"],
            frequency_penalty=row["frequency_penalty"],
            max_tokens=row["max_tokens"],
            profile_id=row["profile_id"],
            model=row["model"],
            context_window=row["context_window"],
        )
        return chat, row["settings_rev"]

    def get_chat(self, chat_id: str, *, owner: str) -> Chat:
        return self.get_chat_rev(chat_id, owner=owner)[0]

    def get_chat_rev(self, chat_id: str, *, owner: str) -> tuple[Chat, int]:
        """The chat plus its settings revision, which a generation keeps to tell later settings edits from its own."""
        with self._read() as conn:
            return self._load(conn, chat_id, owner)

    def list_chats(self, *, owner: str) -> list[ChatSummary]:
        with self._read() as conn:
            rows = conn.execute(
                "SELECT c.id, c.title, c.updated, (SELECT COUNT(*) FROM messages m WHERE m.chat_id = c.id) AS n "
                "FROM chats c WHERE c.owner=? ORDER BY c.updated DESC",
                (owner,),
            ).fetchall()
        return [ChatSummary(id=r["id"], title=r["title"], updated=r["updated"], message_count=r["n"]) for r in rows]

    # --- unscoped, internal ---------------------------------------------------------------------
    # Never reachable from a route. Callers: chat_migration (import's "already present" check, the read-back
    # comparison and export) and tests. Routes and streaming only use the owner-scoped methods above and below.

    def chat_ids(self) -> set[str]:
        with self._read() as conn:
            return {r["id"] for r in conn.execute("SELECT id FROM chats")}

    def get_chat_unscoped(self, chat_id: str) -> Chat:
        with self._read() as conn:
            row = conn.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
            if row is None:
                raise ChatNotFound(chat_id)
            return self._build(conn, row)[0]

    def count_unowned(self) -> int:
        with self._read() as conn:
            return conn.execute("SELECT COUNT(*) FROM chats WHERE owner IS NULL").fetchone()[0]

    def claim_unowned(self, owner: str) -> int:
        """Gives every chat that has no owner to `owner`; the only way a NULL owner is ever replaced."""
        with self._tx() as conn:
            return conn.execute("UPDATE chats SET owner=? WHERE owner IS NULL", (owner,)).rowcount

    def find_image(self, chat_id: str, image_id: str, *, owner: str) -> ImageRef | None:
        with self._read() as conn:
            if conn.execute("SELECT 1 FROM chats WHERE id=? AND owner=?", (chat_id, owner)).fetchone() is None:
                raise ChatNotFound(chat_id)
            rows = conn.execute("SELECT images FROM messages WHERE chat_id=? AND instr(images, ?) > 0", (chat_id, image_id))
            for row in rows:
                for ref in json.loads(row["images"]):
                    if ref["id"] == image_id:
                        return ImageRef(**ref)
        return None

    # --- writing ----------------------------------------------------------------------------

    @staticmethod
    def _insert_message(conn: sqlite3.Connection, chat_id: str, seq: int, m: Message) -> None:
        conn.execute(
            "INSERT INTO messages (chat_id, seq, role, content, created, images, sources, query) VALUES (?,?,?,?,?,?,?,?)",
            (
                chat_id,
                seq,
                m.role,
                m.content,
                _ts(m.created),
                json.dumps([i.model_dump(mode="json") for i in m.images], ensure_ascii=False),
                json.dumps([s.model_dump(mode="json") for s in m.sources], ensure_ascii=False),
                m.query,
            ),
        )

    def insert_chat(self, chat: Chat, *, owner: str | None = None) -> bool:
        """Stores a chat exactly as given (timestamps included). False when the id already exists, so imports can be re-run.

        `owner` is None only for imports, whose chats stay invisible to everyone until the startup claim gives them one."""
        with self._tx() as conn:
            try:
                conn.execute(
                    "INSERT INTO chats (id, title, created, updated, bible, lore, summary, summary_upto, last_usage, system_prompt, "
                    "temperature, top_p, frequency_penalty, max_tokens, profile_id, model, context_window, owner) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        chat.id,
                        chat.title,
                        _ts(chat.created),
                        _ts(chat.updated),
                        chat.bible,
                        json.dumps([e.model_dump(mode="json") for e in chat.lore], ensure_ascii=False),
                        chat.summary,
                        chat.summary_upto,
                        chat.last_usage.prompt_tokens if chat.last_usage else None,
                        chat.system_prompt,
                        chat.temperature,
                        chat.top_p,
                        chat.frequency_penalty,
                        chat.max_tokens,
                        chat.profile_id,
                        chat.model,
                        chat.context_window,
                        owner,
                    ),
                )
            except sqlite3.IntegrityError:
                return False
            for seq, message in enumerate(chat.messages):
                self._insert_message(conn, chat.id, seq, message)
        return True

    @staticmethod
    def _update(conn: sqlite3.Connection, chat_id: str, owner: str, values: dict, bump: bool = False) -> None:
        """Sets only the given columns (names come from this module, never from a request)."""
        values = {**values, "updated": _ts(utcnow())}
        assert values.keys() <= _UPDATABLE, values.keys() - _UPDATABLE
        sets = ", ".join(f"{column}=?" for column in values) + (", settings_rev=settings_rev+1" if bump else "")
        if conn.execute(f"UPDATE chats SET {sets} WHERE id=? AND owner=?", [*values.values(), chat_id, owner]).rowcount == 0:
            raise ChatNotFound(chat_id)

    def create_chat(self, profile_id: str | None, *, owner: str) -> Chat:
        if not owner:
            raise ValueError("a chat needs an owner")
        chat = Chat(id=uuid.uuid4().hex, profile_id=profile_id)
        self.insert_chat(chat, owner=owner)
        return chat

    def delete_chat(self, chat_id: str, *, owner: str) -> None:
        with self._tx() as conn:
            if conn.execute("DELETE FROM chats WHERE id=? AND owner=?", (chat_id, owner)).rowcount == 0:
                raise ChatNotFound(chat_id)

    def rename(self, chat_id: str, title: str, *, owner: str) -> Chat:
        with self._tx() as conn:
            self._update(conn, chat_id, owner, {"title": title})
            return self._load(conn, chat_id, owner)[0]

    def append_messages(
        self,
        chat_id: str,
        messages: list[Message],
        *,
        owner: str,
        title: str | None = None,
        usage: Usage | None = None,
        rev: int | None = None,
    ) -> Chat:
        """Adds messages at the end for callers that are not generating a reply (imports, seeding); a reply is saved with append_generated.

        `title` only applies to a still-empty chat that has its default title, so it never replaces a rename.
        `usage` is recorded only if no settings changed since `rev`: it was measured against an older prompt otherwise.
        Raises ChatNotFound when the chat was deleted meanwhile, so a finished reply cannot bring it back.
        """
        with self._tx() as conn:
            return self._append(conn, chat_id, owner, messages, title, usage, rev)

    def append_generated(
        self,
        lease: Lease,
        messages: list[Message],
        *,
        title: str | None = None,
        usage: Usage | None = None,
        rev: int | None = None,
    ) -> Chat:
        """append_messages for a generation: the same transaction checks that `lease` is still the chat's live lease.

        Raises LeaseLost before writing anything when it expired or another request took over, and ChatNotFound
        when the chat is gone or no longer belongs to the lease's owner (a deleted chat takes its lease row with it,
        so that is checked first).
        """
        with self._tx() as conn:
            return self._append(conn, lease.chat_id, lease.owner, messages, title, usage, rev, lease)

    def _append(
        self,
        conn: sqlite3.Connection,
        chat_id: str,
        owner: str,
        messages: list[Message],
        title: str | None,
        usage: Usage | None,
        rev: int | None,
        lease: Lease | None = None,
    ) -> Chat:
        row = conn.execute(
            "SELECT title, settings_rev, (SELECT COALESCE(MAX(seq), -1) + 1 FROM messages WHERE chat_id = ?) AS next_seq "
            "FROM chats WHERE id = ? AND owner = ?",
            (chat_id, chat_id, owner),
        ).fetchone()
        if row is None:
            raise ChatNotFound(chat_id)
        if lease is not None and not lease.holds(conn):
            raise LeaseLost(chat_id)
        for offset, message in enumerate(messages):
            self._insert_message(conn, chat_id, row["next_seq"] + offset, message)
        values: dict = {}
        if title and row["next_seq"] == 0 and row["title"] == DEFAULT_TITLE:
            values["title"] = title
        if usage is not None and (rev is None or rev == row["settings_rev"]):
            values["last_usage"] = usage.prompt_tokens
        self._update(conn, chat_id, owner, values)
        return self._load(conn, chat_id, owner)[0]

    def update_story(self, chat_id: str, bible: str, lore: list[LoreEntry], *, owner: str) -> Chat:
        values = {
            "bible": bible,
            "lore": json.dumps([e.model_dump(mode="json") for e in lore], ensure_ascii=False),
            "last_usage": None,  # measured against the old prompt
        }
        with self._tx() as conn:
            self._update(conn, chat_id, owner, values, bump=True)
            return self._load(conn, chat_id, owner)[0]

    def update_behavior(self, chat_id: str, values: dict, set_profile: bool, profile_id: str | None, *, owner: str) -> Chat:
        """`values` are the sampling and prompt fields; the provider changes only when `set_profile`."""
        with self._tx() as conn:
            current = conn.execute("SELECT profile_id FROM chats WHERE id=? AND owner=?", (chat_id, owner)).fetchone()
            if current is None:
                raise ChatNotFound(chat_id)
            values = {**values, "last_usage": None}
            if set_profile:
                if profile_id != current["profile_id"]:
                    values["model"] = values["context_window"] = None  # a model ID only makes sense on its own provider
                values["profile_id"] = profile_id
            self._update(conn, chat_id, owner, values, bump=True)
            return self._load(conn, chat_id, owner)[0]

    def update_model(self, chat_id: str, model: str | None, context_window: int | None, pin_profile: str | None, *, owner: str) -> Chat:
        """`pin_profile` is stored only if the chat still follows the default provider."""
        with self._tx() as conn:
            current = conn.execute("SELECT profile_id FROM chats WHERE id=? AND owner=?", (chat_id, owner)).fetchone()
            if current is None:
                raise ChatNotFound(chat_id)
            values = {"model": model, "context_window": context_window if model else None, "last_usage": None}
            if model and pin_profile and current["profile_id"] is None:
                values["profile_id"] = pin_profile
            self._update(conn, chat_id, owner, values, bump=True)
            return self._load(conn, chat_id, owner)[0]

    def update_summary(self, chat_id: str, summary: str, upto: int, *, owner: str) -> Chat:
        with self._tx() as conn:
            # First, so a validation error never tells another user that the chat exists.
            if conn.execute("SELECT 1 FROM chats WHERE id=? AND owner=?", (chat_id, owner)).fetchone() is None:
                raise ChatNotFound(chat_id)
            count = conn.execute("SELECT COUNT(*) FROM messages WHERE chat_id=?", (chat_id,)).fetchone()[0]
            if upto > count:
                raise InvalidUpdate("summary_upto is beyond the end of the chat")
            if upto and not summary.strip():
                raise InvalidUpdate("Write a summary before hiding earlier messages")
            self._update(conn, chat_id, owner, {"summary": summary, "summary_upto": upto, "last_usage": None}, bump=True)
            return self._load(conn, chat_id, owner)[0]

    # --- generation leases ------------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        with self._read() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._tx() as conn:
            conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    def acquire(self, chat_id: str, *, owner: str) -> Lease:
        """Takes the chat's generation lease, waiting up to `acquire_wait` seconds, or raises ChatBusy.
        Another user's chat raises ChatNotFound, before anything about its lease is revealed."""
        deadline = time.monotonic() + self.acquire_wait
        while True:
            try:
                return self._try_acquire(chat_id, owner)
            except ChatBusy:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)

    def _try_acquire(self, chat_id: str, owner: str) -> Lease:
        """One attempt. An expired lease (crashed owner) is taken over."""
        token = uuid.uuid4().hex
        with self._tx() as conn:
            if conn.execute("SELECT 1 FROM chats WHERE id=? AND owner=?", (chat_id, owner)).fetchone() is None:
                raise ChatNotFound(chat_id)
            now = time.time()
            held = conn.execute("SELECT expires FROM generations WHERE chat_id=?", (chat_id,)).fetchone()
            if held is not None and held["expires"] > now:
                raise ChatBusy(chat_id)
            conn.execute(
                "INSERT OR REPLACE INTO generations (chat_id, token, pid, expires) VALUES (?,?,?,?)",
                (chat_id, token, os.getpid(), now + self.lease_ttl),
            )
        lease = Lease(self, chat_id, token, owner)
        lease._thread.start()
        return lease

    def _renew(self, chat_id: str, token: str) -> bool:
        # An expired lease stays expired: another request may already be deciding to take it over.
        with self._tx() as conn:
            now = time.time()
            cursor = conn.execute(
                "UPDATE generations SET expires=? WHERE chat_id=? AND token=? AND expires>?",
                (now + self.lease_ttl, chat_id, token, now),
            )
            return cursor.rowcount > 0

    def _release(self, chat_id: str, token: str) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM generations WHERE chat_id=? AND token=?", (chat_id, token))

    # --- accounts ---------------------------------------------------------------------------
    # Tokens and invite codes arrive here already hashed; this class never sees a plain secret.

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
                    "UPDATE invites SET used_by=?, used_at=? WHERE code_hash=? AND used_by IS NULL AND expires>?",
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

    def create_invite(self, code_hash: str, days: float = INVITE_DAYS, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO invites (code_hash, created, expires) VALUES (?,?,?)",
                (code_hash, _ts(now), _ts(now + timedelta(days=days))),
            )

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
    def _login_wait(conn: sqlite3.Connection, keys: list[str], now: float) -> int:
        wait = 0.0
        for key in keys:
            row = conn.execute(
                "SELECT at FROM login_attempts WHERE key=? AND at>? ORDER BY at DESC LIMIT 1 OFFSET ?",
                (key, now - LOGIN_WINDOW, LOGIN_MAX_FAILURES - 1),
            ).fetchone()
            if row is not None:  # the failure that, once it ages out, brings the count back under the limit
                wait = max(wait, row["at"] + LOGIN_WINDOW - now)
        return max(1, int(wait) + 1) if wait > 0 else 0

    def login_wait(self, keys: list[str], now: float | None = None) -> int:
        """Seconds until a login for these keys may be tried again; 0 when none is over the failure limit."""
        now = time.time() if now is None else now
        with self._read() as conn:
            return self._login_wait(conn, keys, now)

    def take_login_attempt(self, keys: list[str], now: float | None = None) -> tuple[int, list[int]]:
        """Checks the limit and records an attempt in one transaction, so parallel guesses cannot all see zero failures.
        Returns (seconds to wait, []) when over the limit and nothing is recorded, else (0, ids of the recorded
        attempts). The caller hands the ids to forget_login_attempts when the attempt turns out to be legitimate."""
        now = time.time() if now is None else now
        with self._tx() as conn:
            conn.execute("DELETE FROM login_attempts WHERE at<?", (now - LOGIN_WINDOW,))
            wait = self._login_wait(conn, keys, now)
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
            conn.execute("DELETE FROM login_attempts WHERE at<?", (now - LOGIN_WINDOW,))
            conn.executemany("INSERT INTO login_attempts (key, at) VALUES (?,?)", [(k, now) for k in keys])

    def clear_login_failures(self, key: str) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM login_attempts WHERE key=?", (key,))
