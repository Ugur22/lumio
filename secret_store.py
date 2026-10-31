import fcntl
import json
import logging
import os
import re
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

import e2e
import keyring
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE = "dolphinllm-client"
# The pre-profiles single key; still read so existing setups keep working.
LEGACY_ACCOUNT = "api-key"
TAVILY_ACCOUNT = "tavily"
# A server has no OS keychain: when this points at a file, keys live there instead (mode 0600).
SECRETS_FILE_ENV = "DOLPHINLLM_SECRETS_FILE"
# Master key(s) for that file, comma-separated: the first encrypts, all decrypt (so a key can be rotated). The key file is the fallback.
SECRET_KEY_ENV = "DOLPHINLLM_SECRET_KEY"
SECRET_KEY_FILE_ENV = "DOLPHINLLM_SECRET_KEY_FILE"
FORMAT_VERSION = 2

log = logging.getLogger("dolphinllm")


def store_kind() -> Literal["keychain", "file"]:
    return "file" if _secrets_file() else "keychain"


def profile_account(profile_id: str) -> str:
    return f"profile:{profile_id}"


_SAFE_PART = re.compile(r"^[0-9A-Za-z_-]{1,64}$")


def _safe(part: str) -> str:
    # Accounts are "u:<user>:..." strings: a colon or other separator in an id could forge another user's account.
    if not _SAFE_PART.fullmatch(part):
        raise ValueError("unsafe id for a secret account")
    return part


def user_profile_account(user_id: str, profile_id: str) -> str:
    return f"u:{_safe(user_id)}:profile:{_safe(profile_id)}"


def user_tavily_account(user_id: str) -> str:
    return f"u:{_safe(user_id)}:tavily"


def _secrets_file() -> Path | None:
    path = os.environ.get(SECRETS_FILE_ENV)
    return Path(path) if path else None


class SecretStoreError(RuntimeError):
    """The secrets file cannot be used safely. Messages never contain keys, tokens or secret values."""


def _master_keys() -> list[str]:
    raw = os.environ.get(SECRET_KEY_ENV, "")
    if not raw.strip() and (key_file := os.environ.get(SECRET_KEY_FILE_ENV)):
        try:
            raw = Path(key_file).read_text()
        except OSError:
            raise SecretStoreError(f"{SECRET_KEY_FILE_ENV} is set but the file cannot be read.") from None
    keys = [k for k in re.split(r"[,\s]+", raw) if k]
    if not keys:
        raise SecretStoreError(
            f"The secrets file is in use but no master key is configured. Set {SECRET_KEY_ENV} (or {SECRET_KEY_FILE_ENV} "
            "to a file containing it); create one with: python -m secret_store new-key"
        )
    return keys


def _fernets() -> MultiFernet:
    try:
        return MultiFernet([Fernet(k) for k in _master_keys()])
    except ValueError:
        raise SecretStoreError(f"A master key in {SECRET_KEY_ENV}/{SECRET_KEY_FILE_ENV} is not a valid Fernet key; create one with: python -m secret_store new-key") from None


@contextmanager
def file_lock(target: Path) -> Iterator[None]:
    """Holds an exclusive flock on a sibling `<name>.lock` file. Several uvicorn workers (and threads, each with its own
    open file) share one secrets file, and a read-modify-write without this loses whichever write came first."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target.with_name(target.name + ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)  # closing releases the lock


def atomic_tmp(target: Path) -> tuple[int, Path]:
    """A new 0600 temp file next to `target` with a name no other writer can share."""
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".", suffix=".tmp")
    return fd, Path(name)


def _load(path: Path, fernet: MultiFernet) -> tuple[dict[str, str], dict[str, str]]:
    """Returns (tokens, upgraded): the file's entries as Fernet tokens, and the plaintext values of the entries that were
    plaintext in the old format and have just been encrypted (empty for a current file). Raises rather than returning {}
    for a file it cannot parse, because the next write would replace whatever is in it."""
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}, {}
    except (OSError, ValueError):
        raise SecretStoreError("The secrets file cannot be parsed; it was left untouched.") from None
    if isinstance(data, dict) and data.get("v") == FORMAT_VERSION and isinstance(data.get("secrets"), dict):
        return {a: t for a, t in data["secrets"].items() if isinstance(a, str) and isinstance(t, str)}, {}
    if not isinstance(data, dict):
        raise SecretStoreError("The secrets file has an unknown format; it was left untouched.")
    plain = {a: v for a, v in data.items() if isinstance(a, str) and isinstance(v, str) and v}
    return {a: fernet.encrypt(v.encode()).decode() for a, v in plain.items()}, plain


def _write(path: Path, tokens: dict[str, str], fernet: MultiFernet, expect: dict[str, str]) -> None:
    """Writes tmp, checks that it parses to exactly `tokens` and that every entry in `expect` decrypts to its value,
    then replaces. A failure before the replace leaves the original file as the only copy."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # mkstemp creates it 0600, so the file is never briefly world-readable, and its name is unique per writer.
    fd, tmp = atomic_tmp(path)
    with os.fdopen(fd, "w") as f:
        json.dump({"v": FORMAT_VERSION, "secrets": tokens}, f)
        f.flush()
        os.fsync(f.fileno())
    try:
        written = json.loads(tmp.read_text())
        ok = written == {"v": FORMAT_VERSION, "secrets": tokens} and all(fernet.decrypt(tokens[a].encode()).decode() == v for a, v in expect.items())
    except (OSError, ValueError, InvalidToken, KeyError):
        ok = False
    if not ok:
        tmp.unlink(missing_ok=True)
        raise SecretStoreError("The re-encrypted secrets file did not verify; the original was left untouched.")
    try:
        tmp.replace(path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def migrate_to_encrypted() -> None:
    """At startup: refuses (SecretStoreError) when the file backend has no usable master key, and rewrites an old
    plaintext secrets file encrypted. Does nothing for the keychain backend or in e2e mode."""
    if e2e.enabled() or not (path := _secrets_file()):
        return
    fernet = _fernets()
    with file_lock(path):
        tokens, upgraded = _load(path, fernet)
        if upgraded:
            _write(path, tokens, fernet, upgraded)


def _get_from_file(path: Path, account: str) -> str | None:
    fernet = _fernets()
    try:
        tokens, _ = _load(path, fernet)
    except SecretStoreError:
        log.warning("Secrets file unreadable", extra={"account": account})
        return None
    if not (token := tokens.get(account)):
        return None
    try:
        return fernet.decrypt(token.encode()).decode() or None
    except InvalidToken:
        # Wrong master key or a tampered token; only the account id is logged.
        log.warning("Could not decrypt a stored key", extra={"account": account})
        return None


def get_key(account: str = LEGACY_ACCOUNT) -> str | None:
    if e2e.enabled():
        return None
    if path := _secrets_file():
        return _get_from_file(path, account)
    # A missing or locked keychain must not stop the server: fall back to the env key.
    try:
        return keyring.get_password(SERVICE, account) or None
    except KeyringError:
        return None


def set_key(key: str, account: str = LEGACY_ACCOUNT) -> None:
    if e2e.enabled():
        return
    if path := _secrets_file():
        fernet = _fernets()
        with file_lock(path):
            tokens, upgraded = _load(path, fernet)
            # Entries this key cannot read stay as they are: only this account's token changes.
            tokens[account] = fernet.encrypt(key.encode()).decode()
            _write(path, tokens, fernet, {**upgraded, account: key})
        return
    keyring.set_password(SERVICE, account, key)


def delete_key(account: str = LEGACY_ACCOUNT) -> None:
    if e2e.enabled():
        return
    if path := _secrets_file():
        fernet = _fernets()
        with file_lock(path):
            tokens, upgraded = _load(path, fernet)
            if tokens.pop(account, None) is not None:
                _write(path, tokens, fernet, {a: v for a, v in upgraded.items() if a != account})
        return
    try:
        keyring.delete_password(SERVICE, account)
    except PasswordDeleteError:
        pass


def rotate() -> int:
    """Re-encrypts every entry with the first master key. Decrypts all of them first and changes nothing if any fails."""
    path = _secrets_file()
    if not path:
        raise SecretStoreError(f"{SECRETS_FILE_ENV} is not set; there is no secrets file to rotate.")
    fernet = _fernets()
    with file_lock(path):
        tokens, upgraded = _load(path, fernet)
        plain: dict[str, str] = {}
        unreadable = []
        for account, token in tokens.items():
            try:
                plain[account] = fernet.decrypt(token.encode()).decode()
            except InvalidToken:
                unreadable.append(account)
        if unreadable:
            raise SecretStoreError(f"Not rotated: no configured master key decrypts {len(unreadable)} entries ({', '.join(sorted(unreadable))}). Add the old key after the new one.")
        rotated = {a: fernet.rotate(t.encode()).decode() for a, t in tokens.items()}
        _write(path, rotated, fernet, plain)
        return len(rotated)


def main(argv: list[str]) -> int:
    if argv == ["new-key"]:
        print(Fernet.generate_key().decode())
        return 0
    if argv == ["rotate"]:
        try:
            print(f"Re-encrypted {rotate()} entries with the first master key.")
        except SecretStoreError as e:
            print(e, file=sys.stderr)
            return 1
        return 0
    print("usage: python -m secret_store new-key | rotate", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
