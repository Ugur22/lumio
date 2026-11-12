"""Creates the admin account that lumio-mobile's visual check signs in with, in the e2e server's throwaway database.

Run by `make e2e-mobile-server` with the same LUMIO_E2E_DATA_DIR the server uses. The settings are given explicitly so a
developer's .env cannot point it at the real database.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import accounts  # noqa: E402
import storage  # noqa: E402
from models import Settings  # noqa: E402

USERNAME = "demo"
PASSWORD = os.environ.get("E2E_DEMO_PASSWORD", "demo-visual-pass-1")

settings = Settings(data_dir=Path(os.environ["LUMIO_E2E_DATA_DIR"]), db_file=None)
settings.data_dir.mkdir(parents=True, exist_ok=True)
db = storage.Store(settings.database)
try:
    accounts.create_user(db, USERNAME, PASSWORD, admin=True)
except storage.UsernameTaken:
    pass
print(f"e2e account ready: {USERNAME}")
