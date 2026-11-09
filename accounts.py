"""Accounts: password hashing, session and invite secrets, and the command line that bootstraps them.

    python -m accounts create-user alice [--admin]
    python -m accounts invite [--days N]
    python -m accounts trial-invite [--days N]
    python -m accounts set-password alice
    python -m accounts disable alice

Works against settings.database. Only hashes of tokens and invite codes are stored; the plain invite code is
printed once by `invite` and never again.
"""

import argparse
import contextlib
import functools
import getpass
import hashlib
import secrets
import sys
import threading

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from pydantic import SecretStr, TypeAdapter, ValidationError

import storage
from models import Password, Settings, Username

hasher = PasswordHasher()
# Each argon2 hash takes tens of megabytes; with open sign-in a burst of requests must not run them all at once.
_hashing = threading.BoundedSemaphore(2)
HASH_WAIT = 2.0
# Names a stranger must never get: they read as staff, and the admin's name inherits the pre-accounts key.
RESERVED_USERNAMES = frozenset({"admin", "root", "support", "local", "system"})
_username = TypeAdapter(Username)
_password = TypeAdapter(Password)


def sha256(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def is_reserved(username: str, admin_user: str | None) -> bool:
    name = username.strip().lower()
    return name in RESERVED_USERNAMES or (bool(admin_user) and name == admin_user.strip().lower())


class Busy(Exception):
    """All hashing slots stayed taken for HASH_WAIT seconds; the route answers 503 instead of holding a worker thread."""


@contextlib.contextmanager
def _slot():
    if not _hashing.acquire(timeout=HASH_WAIT):
        raise Busy()
    try:
        yield
    finally:
        _hashing.release()


def hash_password(password: str) -> str:
    with _slot():
        return hasher.hash(password)


@functools.cache
def _dummy_hash() -> str:
    with _slot():
        return hasher.hash(secrets.token_hex(8))


def verify_password(password_hash: str | None, password: str) -> bool:
    """Always costs one argon2 verification, so an unknown user cannot be told from a wrong password by timing."""
    if password_hash == storage.UNUSABLE_PASSWORD:
        password_hash = None  # an account that signs in with a provider: fail like an unknown user, at the same cost
    stored = password_hash or _dummy_hash()  # before taking a slot, so the dummy's own hash cannot wait on this one
    try:
        with _slot():
            return hasher.verify(stored, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def clean_username(raw: str) -> str:
    try:
        return _username.validate_python(raw)
    except ValidationError:
        raise ValueError("Username must be 3-32 characters: letters, digits, _ or -") from None


def check_password(raw: str) -> str:
    try:
        _password.validate_python(SecretStr(raw))
    except ValidationError:
        raise ValueError("Password must be 10-128 characters") from None
    return raw


def create_user(db: storage.Store, username: str, password: str, *, admin: bool = False) -> storage.Account:
    return db.create_user(clean_username(username), hash_password(check_password(password)), is_admin=admin)


def issue_invite(
    db: storage.Store, days: float = storage.INVITE_DAYS, kind: str = "account", *, note: str | None = None, created_by: str | None = None
) -> tuple[str, str]:
    """Returns (code, id). Only the code's hash is stored; the code is shown once and cannot be recovered."""
    code = secrets.token_urlsafe(16)
    return code, db.create_invite(sha256(code), days, kind=kind, note=note, created_by=created_by)


def create_invite(db: storage.Store, days: float = storage.INVITE_DAYS, kind: str = "account") -> str:
    return issue_invite(db, days, kind)[0]


def _find(db: storage.Store, username: str) -> storage.Account:
    account = db.get_account(username.strip().lower())
    if account is None:
        raise ValueError(f"No such user: {username}")
    return account


def set_password(db: storage.Store, username: str, password: str) -> None:
    account = _find(db, username)
    db.set_password(account.id, hash_password(check_password(password)))
    db.delete_other_sessions(account.id, None)


def disable_user(db: storage.Store, username: str) -> None:
    db.disable_user(_find(db, username).id)


def _ask_password() -> str:
    first = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != first:
        raise ValueError("The passwords do not match")
    return first


def main(argv: list[str] | None = None, db: storage.Store | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m accounts", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-user", help="create an account; the first one needs this, there is no open signup")
    p.add_argument("username")
    p.add_argument("--admin", action="store_true")
    p = sub.add_parser("invite", help="print a single-use invite code")
    p.add_argument("--days", type=float, default=storage.INVITE_DAYS)
    p = sub.add_parser("trial-invite", help="print a single-use invite for the reserved free-trial pool (Google/GitHub sign-in)")
    p.add_argument("--days", type=float, default=storage.INVITE_DAYS)
    sub.add_parser("set-password", help="set a new password and sign the user out everywhere").add_argument("username")
    sub.add_parser("disable", help="disable an account and end its sessions").add_argument("username")
    args = parser.parse_args(argv)

    db = db or storage.Store(Settings().database)
    try:
        if args.command == "create-user":
            account = create_user(db, args.username, _ask_password(), admin=args.admin)
            print(f"Created {'admin ' if args.admin else ''}user {account.username}")
        elif args.command in ("invite", "trial-invite"):
            if args.days <= 0:
                raise ValueError("--days must be positive")
            print(create_invite(db, args.days, "trial" if args.command == "trial-invite" else "account"))
            print(f"Single use, valid for {args.days:g} days. It is not stored in readable form and cannot be shown again.", file=sys.stderr)
        elif args.command == "set-password":
            _find(db, args.username)
            set_password(db, args.username, _ask_password())
            print(f"Password changed for {args.username}; all its sessions were ended")
        else:
            disable_user(db, args.username)
            print(f"Disabled {args.username}")
    except storage.UsernameTaken:
        print("That username is taken", file=sys.stderr)
        return 1
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
