"""Prints the API's OpenAPI schema; the frontend types are generated from it (`make types`).

Runs against throwaway data and profile paths so importing `server` never touches `data/` or the keychain.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must be set before `server` is imported: Settings() is read at import time.
# A developer's e2e or log-file settings must not change what gets generated.
for var in ("LUMIO_E2E_UPSTREAM", "LUMIO_E2E_DATA_DIR", "DOLPHINLLM_LOG_FILE"):
    os.environ.pop(var, None)
# Server-only settings from a developer's shell or dotfile would make importing `server` refuse to start (no public host).
for var in ("DOLPHINLLM_SECRETS_FILE", "DOLPHINLLM_SECRET_KEY", "DOLPHINLLM_SECRET_KEY_FILE"):
    os.environ.pop(var, None)
os.environ["DOLPHINLLM_ADMIN_USER"] = ""
scratch = tempfile.mkdtemp(prefix="lumio-openapi-")
os.environ["DOLPHINLLM_API_KEY"] = "schema-only"
os.environ["DOLPHINLLM_DATA_DIR"] = os.path.join(scratch, "chats")
os.environ["DOLPHINLLM_PROFILES_FILE"] = os.path.join(scratch, "profiles.json")

import server  # noqa: E402

json.dump(server.app.openapi(), sys.stdout, indent=2, sort_keys=True)
