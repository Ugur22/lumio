"""Who is calling: the session cookie, the `current_user` dependency and the CSRF origin check."""

from fastapi import HTTPException, Request, Response

import accounts
from app import runtime
from models import LOCAL_USER, UserView

COOKIE = "lumio_session"
SESSION_SECONDS = 30 * 24 * 3600
# The Vite dev server (`npm run dev`) is a legitimate browser origin that proxies to us.
DEV_ORIGINS = frozenset({"http://localhost:5173", "http://127.0.0.1:5173"})


def check_origin(request: Request, allowed: frozenset[str] = frozenset()) -> None:
    """Rejects a browser request whose Origin is not this host (or one of `allowed`). Safe methods are exempt:
    browsers omit Origin on same-origin GETs and they change nothing."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    host_header = request.headers.get("host", "")
    origin = request.headers.get("origin")
    if origin is None:
        raise HTTPException(403, "Missing Origin header")
    # A proxy may rewrite Host, so `allowed` origins (the dev server) pass besides Origin == Host.
    same_host = origin.split("://", 1)[-1] == host_header
    if not (same_host or origin in allowed):
        raise HTTPException(403, f"Origin {origin!r} is not allowed for host {host_header!r}")


def require_same_origin(request: Request) -> None:
    """CSRF guard for state-changing routes. SameSite=Lax on the cookie is the first line; this is the second."""
    if runtime.settings.deployed:
        check_origin(request)


def set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE, token, max_age=SESSION_SECONDS, httponly=True, samesite="lax", path="/", secure=runtime.settings.deployed
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax", secure=runtime.settings.deployed)


def session_token_hash(request: Request) -> str | None:
    token = request.cookies.get(COOKIE)
    return accounts.sha256(token) if token else None


def current_user(request: Request, response: Response) -> UserView:
    if not runtime.settings.deployed:
        return LOCAL_USER
    token_hash = session_token_hash(request)
    found = runtime.db.session_account(token_hash) if token_hash else None
    if found is None:
        raise HTTPException(401, "Not signed in")
    account, refreshed = found
    if refreshed:  # the server-side expiry slid, so the browser's copy has to as well
        set_cookie(response, request.cookies[COOKIE])
    return UserView(id=account.id, username=account.username, is_admin=account.is_admin)
