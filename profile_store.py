import logging

import e2e
import secret_store
from models import Profile, ProfileStore, Settings
from pydantic import ValidationError

log = logging.getLogger("dolphinllm")

# The profile created from a pre-profiles setup (one key, one base URL).
DEFAULT_ID = "default"


def load_store(settings: Settings) -> ProfileStore:
    if e2e.enabled():
        return e2e.store()
    path = settings.profiles_file
    if path.exists():
        try:
            return ProfileStore.model_validate_json(path.read_text())
        except ValidationError:
            # Set aside rather than overwritten, so a bad edit never destroys profiles.
            log.warning("Unreadable %s moved aside", path.name)
            path.replace(path.with_suffix(".corrupt"))
    # Only migrate when there is an old key to carry over; a fresh install starts empty.
    if secret_store.get_key() or settings.api_key:
        default = Profile(id=DEFAULT_ID, name="Dolphin", base_url=settings.base_url, model=settings.model)
        return ProfileStore(active=DEFAULT_ID, profiles=[default])
    return ProfileStore()


def save_store(settings: Settings, store: ProfileStore) -> None:
    if e2e.enabled():
        return
    path = settings.profiles_file
    tmp = path.with_suffix(".tmp")
    tmp.write_text(store.model_dump_json(indent=2))
    tmp.replace(path)


def resolve_key(settings: Settings, profile: Profile) -> tuple[str | None, str | None]:
    """Returns (key, source). The keychain wins so a saved key overrides a stale .env one."""
    if e2e.enabled():
        return e2e.DUMMY_KEY, "env"
    if key := secret_store.get_key(secret_store.profile_account(profile.id)):
        return key, "keychain"
    if profile.id == DEFAULT_ID:
        if key := secret_store.get_key():
            return key, "keychain"
        if settings.api_key:
            return settings.api_key, "env"
    return None, None
