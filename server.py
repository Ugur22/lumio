from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import routes_chats, routes_profiles, runtime
from models import BASE_DIR

runtime.import_legacy_chats(runtime.db, runtime.settings)

# The frontend types are generated from this app's OpenAPI schema (make types, scripts/export_openapi.py).
app = FastAPI()
app.include_router(routes_chats.router)
app.include_router(routes_profiles.profiles)
app.include_router(routes_profiles.web_settings)

# Mounted only when built, so the API (and its tests) work before `make build` has run.
FRONTEND_DIR = BASE_DIR / "frontend" / "dist"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
