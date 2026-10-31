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
from datetime import datetime, timezone
from pathlib import Path

from models import Chat, ChatSummary, ImageRef, LoreEntry, Message, Usage, utcnow

log = logging.getLogger("dolphinllm")

SCHEMA_VERSION = 1
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
        settings_rev INTEGER NOT NULL DEFAULT 0
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
]


_UPDATABLE = {
    "title", "updated", "bible", "lore", "summary", "summary_upto", "last_usage", "system_prompt",
    "temperature", "top_p", "frequency_penalty", "max_tokens", "profile_id", "model", "context_window",
}  # fmt: skip


class ChatNotFound(Exception):
    pass


class ChatBusy(Exception):
    """A reply is already being generated in this chat."""


class InvalidUpdate(Exception):
    """The update is not valid for the chat as it is now; the message is shown to the user."""


def _ts(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)  # the app only ever wrote UTC; never guess the machine's zone
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


class Lease:
    """The right to generate in one chat. Renewed by a thread until released, so a slow web lookup,
    a long stream or a stalled event loop cannot let it lapse; a crashed process stops renewing and it expires."""

    def __init__(self, store: "Store", chat_id: str, token: str):
        self.chat_id = chat_id
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
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            conn.execute("COMMIT")
        finally:
            conn.close()

    # --- reading ----------------------------------------------------------------------------

    @staticmethod
    def _load(conn: sqlite3.Connection, chat_id: str) -> tuple[Chat, int]:
        row = conn.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        if row is None:
            raise ChatNotFound(chat_id)
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

    def get_chat(self, chat_id: str) -> Chat:
        return self.get_chat_rev(chat_id)[0]

    def get_chat_rev(self, chat_id: str) -> tuple[Chat, int]:
        """The chat plus its settings revision, which a generation keeps to tell later settings edits from its own."""
        with self._read() as conn:
            return self._load(conn, chat_id)

    def list_chats(self) -> list[ChatSummary]:
        with self._read() as conn:
            rows = conn.execute(
                "SELECT c.id, c.title, c.updated, (SELECT COUNT(*) FROM messages m WHERE m.chat_id = c.id) AS n "
                "FROM chats c ORDER BY c.updated DESC"
            ).fetchall()
        return [ChatSummary(id=r["id"], title=r["title"], updated=r["updated"], message_count=r["n"]) for r in rows]

    def chat_ids(self) -> set[str]:
        with self._read() as conn:
            return {r["id"] for r in conn.execute("SELECT id FROM chats")}

    def find_image(self, chat_id: str, image_id: str) -> ImageRef | None:
        with self._read() as conn:
            if conn.execute("SELECT 1 FROM chats WHERE id=?", (chat_id,)).fetchone() is None:
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

    def insert_chat(self, chat: Chat) -> bool:
        """Stores a chat exactly as given (timestamps included). False when the id already exists, so imports can be re-run."""
        with self._tx() as conn:
            try:
                conn.execute(
                    "INSERT INTO chats (id, title, created, updated, bible, lore, summary, summary_upto, last_usage, system_prompt, "
                    "temperature, top_p, frequency_penalty, max_tokens, profile_id, model, context_window) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                    ),
                )
            except sqlite3.IntegrityError:
                return False
            for seq, message in enumerate(chat.messages):
                self._insert_message(conn, chat.id, seq, message)
        return True

    @staticmethod
    def _update(conn: sqlite3.Connection, chat_id: str, values: dict, bump: bool = False) -> None:
        """Sets only the given columns (names come from this module, never from a request)."""
        values = {**values, "updated": _ts(utcnow())}
        assert values.keys() <= _UPDATABLE, values.keys() - _UPDATABLE
        sets = ", ".join(f"{column}=?" for column in values) + (", settings_rev=settings_rev+1" if bump else "")
        if conn.execute(f"UPDATE chats SET {sets} WHERE id=?", [*values.values(), chat_id]).rowcount == 0:
            raise ChatNotFound(chat_id)

    def create_chat(self, profile_id: str | None) -> Chat:
        chat = Chat(id=uuid.uuid4().hex, profile_id=profile_id)
        self.insert_chat(chat)
        return chat

    def delete_chat(self, chat_id: str) -> None:
        with self._tx() as conn:
            if conn.execute("DELETE FROM chats WHERE id=?", (chat_id,)).rowcount == 0:
                raise ChatNotFound(chat_id)

    def rename(self, chat_id: str, title: str) -> Chat:
        with self._tx() as conn:
            self._update(conn, chat_id, {"title": title})
            return self._load(conn, chat_id)[0]

    def append_messages(
        self,
        chat_id: str,
        messages: list[Message],
        *,
        title: str | None = None,
        usage: Usage | None = None,
        rev: int | None = None,
    ) -> Chat:
        """Adds messages at the end and touches nothing else about the chat except what is named here.

        `title` only applies to a still-empty chat that has its default title, so it never replaces a rename.
        `usage` is recorded only if no settings changed since `rev`: it was measured against an older prompt otherwise.
        Raises ChatNotFound when the chat was deleted meanwhile, so a finished reply cannot bring it back.
        """
        with self._tx() as conn:
            row = conn.execute(
                "SELECT title, settings_rev, (SELECT COALESCE(MAX(seq), -1) + 1 FROM messages WHERE chat_id = ?) AS next_seq "
                "FROM chats WHERE id = ?",
                (chat_id, chat_id),
            ).fetchone()
            if row is None:
                raise ChatNotFound(chat_id)
            for offset, message in enumerate(messages):
                self._insert_message(conn, chat_id, row["next_seq"] + offset, message)
            values: dict = {}
            if title and row["next_seq"] == 0 and row["title"] == DEFAULT_TITLE:
                values["title"] = title
            if usage is not None and (rev is None or rev == row["settings_rev"]):
                values["last_usage"] = usage.prompt_tokens
            self._update(conn, chat_id, values)
            return self._load(conn, chat_id)[0]

    def update_story(self, chat_id: str, bible: str, lore: list[LoreEntry]) -> Chat:
        values = {
            "bible": bible,
            "lore": json.dumps([e.model_dump(mode="json") for e in lore], ensure_ascii=False),
            "last_usage": None,  # measured against the old prompt
        }
        with self._tx() as conn:
            self._update(conn, chat_id, values, bump=True)
            return self._load(conn, chat_id)[0]

    def update_behavior(self, chat_id: str, values: dict, set_profile: bool, profile_id: str | None) -> Chat:
        """`values` are the sampling and prompt fields; the provider changes only when `set_profile`."""
        with self._tx() as conn:
            current = conn.execute("SELECT profile_id FROM chats WHERE id=?", (chat_id,)).fetchone()
            if current is None:
                raise ChatNotFound(chat_id)
            values = {**values, "last_usage": None}
            if set_profile:
                if profile_id != current["profile_id"]:
                    values["model"] = values["context_window"] = None  # a model ID only makes sense on its own provider
                values["profile_id"] = profile_id
            self._update(conn, chat_id, values, bump=True)
            return self._load(conn, chat_id)[0]

    def update_model(self, chat_id: str, model: str | None, context_window: int | None, pin_profile: str | None) -> Chat:
        """`pin_profile` is stored only if the chat still follows the default provider."""
        with self._tx() as conn:
            current = conn.execute("SELECT profile_id FROM chats WHERE id=?", (chat_id,)).fetchone()
            if current is None:
                raise ChatNotFound(chat_id)
            values = {"model": model, "context_window": context_window if model else None, "last_usage": None}
            if model and pin_profile and current["profile_id"] is None:
                values["profile_id"] = pin_profile
            self._update(conn, chat_id, values, bump=True)
            return self._load(conn, chat_id)[0]

    def update_summary(self, chat_id: str, summary: str, upto: int) -> Chat:
        with self._tx() as conn:
            count = conn.execute("SELECT COUNT(*) FROM messages WHERE chat_id=?", (chat_id,)).fetchone()[0]
            if upto > count:
                if conn.execute("SELECT 1 FROM chats WHERE id=?", (chat_id,)).fetchone() is None:
                    raise ChatNotFound(chat_id)
                raise InvalidUpdate("summary_upto is beyond the end of the chat")
            if upto and not summary.strip():
                raise InvalidUpdate("Write a summary before hiding earlier messages")
            self._update(conn, chat_id, {"summary": summary, "summary_upto": upto, "last_usage": None}, bump=True)
            return self._load(conn, chat_id)[0]

    # --- generation leases ------------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        with self._read() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._tx() as conn:
            conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    def acquire(self, chat_id: str) -> Lease:
        """Takes the chat's generation lease, waiting up to `acquire_wait` seconds, or raises ChatBusy."""
        deadline = time.monotonic() + self.acquire_wait
        while True:
            try:
                return self._try_acquire(chat_id)
            except ChatBusy:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)

    def _try_acquire(self, chat_id: str) -> Lease:
        """One attempt. An expired lease (crashed owner) is taken over."""
        token = uuid.uuid4().hex
        with self._tx() as conn:
            if conn.execute("SELECT 1 FROM chats WHERE id=?", (chat_id,)).fetchone() is None:
                raise ChatNotFound(chat_id)
            now = time.time()
            held = conn.execute("SELECT expires FROM generations WHERE chat_id=?", (chat_id,)).fetchone()
            if held is not None and held["expires"] > now:
                raise ChatBusy(chat_id)
            conn.execute(
                "INSERT OR REPLACE INTO generations (chat_id, token, pid, expires) VALUES (?,?,?,?)",
                (chat_id, token, os.getpid(), now + self.lease_ttl),
            )
        lease = Lease(self, chat_id, token)
        lease._thread.start()
        return lease

    def _renew(self, chat_id: str, token: str) -> bool:
        with self._tx() as conn:
            cursor = conn.execute(
                "UPDATE generations SET expires=? WHERE chat_id=? AND token=?", (time.time() + self.lease_ttl, chat_id, token)
            )
            return cursor.rowcount > 0

    def _release(self, chat_id: str, token: str) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM generations WHERE chat_id=? AND token=?", (chat_id, token))
