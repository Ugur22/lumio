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
    # A bearer token is no ambient credential (a browser never attaches it by itself), so CSRF does not apply. current_user
    # reads only the bearer when the header is present, so a cookie cannot ride along on such a request.
    if bearer_token(request):
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


def bearer_token(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip()
    return token if scheme.lower() == "bearer" and token else None


def request_token(request: Request) -> tuple[str | None, bool]:
    """The session token of this request and whether it came by cookie. Why the bearer wins when both are present: the
    Origin check is skipped for bearer requests, so the cookie must never be what authenticates one."""
    bearer = bearer_token(request)
    if bearer:
        return bearer, False
    return request.cookies.get(COOKIE), True


def session_token_hash(request: Request) -> str | None:
    token, _ = request_token(request)
    return accounts.sha256(token) if token else None


def current_user(request: Request, response: Response) -> UserView:
    if not runtime.settings.deployed:
        return LOCAL_USER
    token, by_cookie = request_token(request)
    found = runtime.db.session_account(accounts.sha256(token)) if token else None
    if found is None:
        raise HTTPException(401, "Not signed in")
    account, refreshed = found
    if refreshed and by_cookie:  # the server-side expiry slid, so the browser's copy has to as well
        set_cookie(response, token)
    return UserView(id=account.id, username=account.username, is_admin=account.is_admin)
