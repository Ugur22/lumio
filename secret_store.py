import e2e
import keyring
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE = "dolphinllm-client"
# The pre-profiles single key; still read so existing setups keep working.
LEGACY_ACCOUNT = "api-key"
TAVILY_ACCOUNT = "tavily"


def profile_account(profile_id: str) -> str:
    return f"profile:{profile_id}"


def get_key(account: str = LEGACY_ACCOUNT) -> str | None:
    if e2e.enabled():
        return None
    # A missing or locked keychain must not stop the server: fall back to the env key.
    try:
        return keyring.get_password(SERVICE, account) or None
    except KeyringError:
        return None


def set_key(key: str, account: str = LEGACY_ACCOUNT) -> None:
    if e2e.enabled():
        return
    keyring.set_password(SERVICE, account, key)


def delete_key(account: str = LEGACY_ACCOUNT) -> None:
    if e2e.enabled():
        return
    try:
        keyring.delete_password(SERVICE, account)
    except PasswordDeleteError:
        pass
