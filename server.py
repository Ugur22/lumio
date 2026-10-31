from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import secret_store
from app import routes_auth, routes_chats, routes_profiles, runtime
from models import BASE_DIR

try:
    secret_store.migrate_to_encrypted()
except secret_store.SecretStoreError as e:
    raise SystemExit(str(e)) from None
runtime.claim_unowned_chats(runtime.db, runtime.settings)
runtime.import_legacy_chats(runtime.db, runtime.settings)
runtime.migrate_profiles_to_admin(runtime.db, runtime.settings)

# The frontend types are generated from this app's OpenAPI schema (make types, scripts/export_openapi.py).
# On a server the interactive docs and the schema would be public (the proxy no longer gates them), so they are off there.
# app.openapi() still works without the URL, which is all scripts/export_openapi.py needs.
_no_docs = {"docs_url": None, "redoc_url": None, "openapi_url": None} if runtime.settings.deployed else {}
app = FastAPI(**_no_docs)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if not request.url.path.startswith("/api/auth/"):
        return await request_validation_exception_handler(request, exc)
    # FastAPI echoes the offending input back; for passwords and invite codes that would put a secret in a response.
    errors = [{k: v for k, v in e.items() if k not in ("input", "ctx")} for e in exc.errors()]
    return JSONResponse({"detail": errors}, status_code=422)


app.include_router(routes_auth.router)
app.include_router(routes_chats.router)
app.include_router(routes_profiles.profiles)
app.include_router(routes_profiles.web_settings)

# Mounted only when built, so the API (and its tests) work before `make build` has run.
FRONTEND_DIR = BASE_DIR / "frontend" / "dist"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
