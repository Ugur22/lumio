import json
import os
from pathlib import Path
from typing import Literal

import e2e
import keyring
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE = "dolphinllm-client"
# The pre-profiles single key; still read so existing setups keep working.
LEGACY_ACCOUNT = "api-key"
TAVILY_ACCOUNT = "tavily"
# A server has no OS keychain: when this points at a file, keys live there instead (mode 0600).
SECRETS_FILE_ENV = "DOLPHINLLM_SECRETS_FILE"


def store_kind() -> Literal["keychain", "file"]:
    return "file" if _secrets_file() else "keychain"


def profile_account(profile_id: str) -> str:
    return f"profile:{profile_id}"


def _secrets_file() -> Path | None:
    path = os.environ.get(SECRETS_FILE_ENV)
    return Path(path) if path else None


def _read(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: Path, secrets: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    # Created 0600 so the key is never briefly world-readable; chmod covers a leftover tmp file.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(secrets, f)
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def get_key(account: str = LEGACY_ACCOUNT) -> str | None:
    if e2e.enabled():
        return None
    if path := _secrets_file():
        return _read(path).get(account) or None
    # A missing or locked keychain must not stop the server: fall back to the env key.
    try:
        return keyring.get_password(SERVICE, account) or None
    except KeyringError:
        return None


def set_key(key: str, account: str = LEGACY_ACCOUNT) -> None:
    if e2e.enabled():
        return
    if path := _secrets_file():
        _write(path, {**_read(path), account: key})
        return
    keyring.set_password(SERVICE, account, key)


def delete_key(account: str = LEGACY_ACCOUNT) -> None:
    if e2e.enabled():
        return
    if path := _secrets_file():
        secrets = _read(path)
        if secrets.pop(account, None) is not None:
            _write(path, secrets)
        return
    try:
        keyring.delete_password(SERVICE, account)
    except PasswordDeleteError:
        pass
