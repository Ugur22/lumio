import logging
import os
import re
from pathlib import Path

import e2e
import secret_store
from models import LOCAL_USER, Profile, ProfileStore, Settings, UserView
from pydantic import ValidationError

log = logging.getLogger("dolphinllm")

# The profile created from a pre-profiles setup (one key, one base URL).
DEFAULT_ID = "default"
# User ids are uuid hex; this is the only thing that may ever become part of a path or a secret account.
_SAFE_USER_ID = re.compile(r"^[0-9a-f-]{8,64}$")
MIGRATION_KEY = "profiles_migrated_to_admin"


def is_local(user: UserView) -> bool:
    return user.id == LOCAL_USER.id


def is_admin_user(settings: Settings, user: UserView) -> bool:
    """The account named by DOLPHINLLM_ADMIN_USER, which inherits the pre-accounts global profiles and env key."""
    name = (settings.admin_user or "").strip().lower()
    return settings.deployed and bool(name) and user.username == name


def _safe_id(user: UserView) -> str:
    assert _SAFE_USER_ID.fullmatch(user.id), "unsafe user id"
    return user.id


def store_path(settings: Settings, user: UserView) -> Path:
    if is_local(user):
        return settings.profiles_file
    return settings.profiles_file.parent / "profiles" / f"{_safe_id(user)}.json"


def profile_account(user: UserView, profile_id: str) -> str:
    if is_local(user):
        return secret_store.profile_account(profile_id)
    return secret_store.user_profile_account(_safe_id(user), profile_id)


def tavily_account(user: UserView) -> str:
    if is_local(user):
        return secret_store.TAVILY_ACCOUNT
    return secret_store.user_tavily_account(_safe_id(user))


def _inherits_legacy(settings: Settings, user: UserView) -> bool:
    """Whether the pre-profiles single key and the e2e stub are this user's: the local user, or the admin on a server."""
    return is_local(user) or is_admin_user(settings, user)


def _read(path: Path) -> ProfileStore | None:
    if not path.exists():
        return None
    try:
        return ProfileStore.model_validate_json(path.read_text())
    except ValidationError:
        # Set aside rather than overwritten, so a bad edit never destroys profiles.
        log.warning("Unreadable %s moved aside", path.name)
        path.replace(path.with_suffix(".corrupt"))
        return None


def load_store(settings: Settings, user: UserView) -> ProfileStore:
    if e2e.enabled() and _inherits_legacy(settings, user):
        return e2e.store()
    store = _read(store_path(settings, user))
    if store is not None:
        return store
    # Only migrate when there is an old key to carry over; a fresh install starts empty.
    if _inherits_legacy(settings, user) and ((is_local(user) and secret_store.get_key()) or settings.api_key):
        default = Profile(id=DEFAULT_ID, name="Dolphin", base_url=settings.base_url, model=settings.model)
        return ProfileStore(active=DEFAULT_ID, profiles=[default])
    return ProfileStore()


def save_store(settings: Settings, user: UserView, store: ProfileStore) -> None:
    if e2e.enabled() and _inherits_legacy(settings, user):
        return
    path = store_path(settings, user)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = secret_store.atomic_tmp(path)  # unique per writer, so two saves never share a half-written file
    with os.fdopen(fd, "w") as f:
        f.write(store.model_dump_json(indent=2))
    tmp.replace(path)


def resolve_key(settings: Settings, user: UserView, profile: Profile) -> tuple[str | None, str | None]:
    """Returns (key, source). The keychain wins so a saved key overrides a stale .env one.

    `profile` must come from this user's own store: the account is derived from it, never from request input."""
    if e2e.enabled() and _inherits_legacy(settings, user):
        return e2e.DUMMY_KEY, "env"
    if key := secret_store.get_key(profile_account(user, profile.id)):
        return key, "keychain"
    if profile.id == DEFAULT_ID:
        if is_local(user) and (key := secret_store.get_key()):
            return key, "keychain"
        if _inherits_legacy(settings, user) and settings.api_key:
            return settings.api_key, "env"
    return None, None


class MigrationConflict(Exception):
    pass


def migrate_global_to_user(settings: Settings, admin: UserView) -> list[str]:
    """Moves the single global profiles file and its keys (legacy account names) to `admin`'s per-user file and
    namespaced accounts. Copy, verify, then delete, so a failure at any step leaves the originals in place; safe to
    re-run. Returns what was moved (profile ids and "tavily"), never a key."""
    if e2e.enabled():
        return []
    # One migration at a time across workers; the secrets file has its own lock inside set_key/delete_key (always taken after this one).
    with secret_store.file_lock(settings.profiles_file):
        return _migrate_global_to_user(settings, admin)


def _migrate_global_to_user(settings: Settings, admin: UserView) -> list[str]:
    global_file = settings.profiles_file
    source = _read(global_file)
    legacy_key = secret_store.get_key()
    profiles = list(source.profiles) if source else []
    if source is None and legacy_key:
        # A pre-profiles setup: the one old key becomes the "default" profile, as load_store does for the local user.
        profiles = [Profile(id=DEFAULT_ID, name="Dolphin", base_url=settings.base_url, model=settings.model)]
        source = ProfileStore(active=DEFAULT_ID, profiles=profiles)

    secrets: dict[str, tuple[str, str]] = {}  # new account -> (key, old account)
    for p in profiles:
        old = secret_store.profile_account(p.id)
        key = secret_store.get_key(old)
        if key is None and p.id == DEFAULT_ID and legacy_key:
            key, old = legacy_key, secret_store.LEGACY_ACCOUNT
        if key is not None:
            secrets[profile_account(admin, p.id)] = (key, old)
    tavily = secret_store.get_key(secret_store.TAVILY_ACCOUNT)
    if tavily:
        secrets[tavily_account(admin)] = (tavily, secret_store.TAVILY_ACCOUNT)
    if not profiles and not secrets:
        return []

    target_path = store_path(settings, admin)
    target = _read(target_path) or ProfileStore()
    existing = {p.id: p for p in target.profiles}
    merged = list(target.profiles)
    for p in profiles:
        if p.id in existing and existing[p.id] != p:
            raise MigrationConflict("the admin already has a different profile with the same id")
        if p.id not in existing:
            merged.append(p)
    for account, (key, _) in secrets.items():
        have = secret_store.get_key(account)
        if have is not None and have != key:
            raise MigrationConflict("the admin already has a different key in a target account")

    for account, (key, _) in secrets.items():
        secret_store.set_key(key, account)
    wanted = target.active or (source.active if source else None)
    active = wanted if wanted in {p.id for p in merged} else (merged[0].id if merged else None)
    save_store(settings, admin, ProfileStore(active=active, profiles=merged))

    # Verified from what a reader would now see, before anything is removed.
    check = _read(target_path)
    if check is None or {p.id for p in profiles} - {p.id for p in check.profiles}:
        raise MigrationConflict("the admin's profile file does not hold the migrated profiles")
    for account, (key, _) in secrets.items():
        if secret_store.get_key(account) != key:
            raise MigrationConflict("a migrated key did not read back")

    # Secrets first and the profile file last, so an interrupted run is picked up again by the next start.
    for _, old in secrets.values():
        secret_store.delete_key(old)
    global_file.unlink(missing_ok=True)
    return [p.id for p in profiles] + (["tavily"] if tavily else [])
