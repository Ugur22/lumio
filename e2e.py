"""Opt-in end-to-end mode: one in-memory profile against a stub upstream, nothing read from or written to the
keychain, profiles.json or the real data dir. Read at call time so it can never be half-enabled."""

import os
from pathlib import Path

from models import Profile, ProfileStore

UPSTREAM_VAR = "LUMIO_E2E_UPSTREAM"
DATA_DIR_VAR = "LUMIO_E2E_DATA_DIR"
PROFILE_ID = "e2e"
DUMMY_KEY = "e2e-dummy-key"


def enabled() -> bool:
    return bool(os.environ.get(UPSTREAM_VAR))


def data_dir() -> Path:
    raw = os.environ.get(DATA_DIR_VAR)
    if not raw:
        raise RuntimeError(f"{DATA_DIR_VAR} must be set when {UPSTREAM_VAR} is set; refusing to use the real data dir.")
    return Path(raw)


def store() -> ProfileStore:
    profile = Profile(id=PROFILE_ID, name="E2E Stub", base_url=os.environ[UPSTREAM_VAR], model="fake-model", image_model="fake-image")
    return ProfileStore(active=PROFILE_ID, profiles=[profile])
