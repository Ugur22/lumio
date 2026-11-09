"""Accounts: invite-only registration, login, logout and password change."""

import base64
import hashlib
import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

import accounts
import storage
from app import auth, runtime
from app.logs import log
from models import ExchangeBody, LoginBody, PasswordChange, RegisterBody, TokenLogin, UserView

router = APIRouter(prefix="/api/auth", dependencies=[Depends(auth.require_same_origin)])

# A native client sends no Origin and has no cookie to protect, so its login cannot sit behind the Origin check. A forged
# cross-site call gains nothing: no cookie is set and the token is in a response the other site cannot read.
token_router = APIRouter(prefix="/api/auth")

INVALID_LOGIN = "Invalid username or password"
INVALID_INVITE = "That invite is not valid"


def client_ip(request: Request) -> str:
    # uvicorn --proxy-headers (behind Caddy on 127.0.0.1) already resolved this; X-Forwarded-For is never read here.
    return request.client.host if request.client else "unknown"


def ip_key(request: Request) -> str:
    return f"ip:{client_ip(request)}"


def user_key(username: str) -> str:
    return f"user:{username[:64]}"


def throttle(keys: list[str], limit: int | None = None) -> list[int]:
    """Counts this attempt as a failure up front and returns what to hand to `credit` if it succeeds. Recording after the
    password check would let parallel guesses (each slow to hash) all see an empty record."""
    wait, attempts = runtime.db.take_login_attempt(keys, **({"limit": limit} if limit else {}))
    if wait:
        raise HTTPException(429, "Too many failed attempts; try again later", headers={"Retry-After": str(wait)})
    return attempts


def credit(attempts: list[int]) -> None:
    runtime.db.forget_login_attempts(attempts)


def new_session(user_id: str) -> str:
    token = accounts.new_token()
    runtime.db.create_session(accounts.sha256(token), user_id)
    return token


def start_session(response: Response, user_id: str) -> None:
    auth.set_cookie(response, new_session(user_id))


def view(account: storage.Account) -> UserView:
    return UserView(id=account.id, username=account.username, is_admin=account.is_admin)


@router.post("/register", response_model=UserView, status_code=201)
def register(body: RegisterBody, request: Request, response: Response):
    # Every refusal counts (a bad invite, and a taken name, which would otherwise list the users that exist). Only the IP is
    # keyed: a per-name key would just let a stranger lock a name out.
    attempts = throttle([ip_key(request)])
    if accounts.is_reserved(body.username, runtime.settings.admin_user):
        raise HTTPException(409, "That username is taken")  # said like any taken name; the invite is not used up
    password_hash = accounts.hash_password(body.password.get_secret_value())
    try:
        account = runtime.db.create_user(
            body.username, password_hash, invite_hash=accounts.sha256(body.invite.get_secret_value().strip())
        )
    except storage.InvalidInvite:
        log.warning("Registration refused: invalid invite", extra={"ip": client_ip(request)})
        raise HTTPException(403, INVALID_INVITE)
    except storage.UsernameTaken:  # the invite is not used up: create_user rolled the redemption back
        raise HTTPException(409, "That username is taken")
    credit(attempts)
    start_session(response, account.id)
    log.info("User registered", extra={"user_id": account.id})
    return view(account)


def authenticate(body: LoginBody, request: Request) -> storage.Account:
    """Shared by the cookie and the token login: throttling, identical-cost failures, credit on success."""
    keys = [user_key(body.username), ip_key(request)]
    attempts = throttle(keys)
    account = runtime.db.get_account(body.username)
    # Verified even for an unknown or disabled user, so all three failures cost the same and read the same.
    verified = accounts.verify_password(account.password_hash if account else None, body.password.get_secret_value())
    if account is None or account.disabled or not verified:
        log.warning("Login failed", extra={"ip": client_ip(request)})
        raise HTTPException(401, INVALID_LOGIN)
    credit(attempts)
    runtime.db.clear_login_failures(keys[0])
    return account


@router.post("/login", response_model=UserView)
def login(body: LoginBody, request: Request, response: Response):
    account = authenticate(body, request)
    start_session(response, account.id)
    log.info("User logged in", extra={"user_id": account.id})
    return view(account)


@token_router.post("/token", response_model=TokenLogin)
def token_login(body: LoginBody, request: Request):
    """Login for a native client: the same session as the cookie one, handed back in the body instead of a cookie."""
    account = authenticate(body, request)
    token = new_session(account.id)
    log.info("User logged in with a token", extra={"user_id": account.id})
    return TokenLogin(token=token, user=view(account))


GENERIC_EXCHANGE = "Invalid or expired code"
MAX_EXCHANGE_FIELD = 256


@token_router.post("/oauth/exchange", response_model=TokenLogin)
def oauth_exchange(body: ExchangeBody, request: Request):
    """Trades the one-time code the OAuth callback gave the native app, plus its PKCE verifier, for a session token.

    The code is consumed before the verifier is checked, so a wrong verifier burns it: a guess costs the attacker the code,
    and the app just starts the sign-in again. Which check failed is never said."""
    attempts = throttle([f"exchange:{ip_key(request)}"])
    refused = HTTPException(400, GENERIC_EXCHANGE)
    if not (0 < len(body.code) <= MAX_EXCHANGE_FIELD and 0 < len(body.verifier) <= MAX_EXCHANGE_FIELD):
        raise refused
    try:
        code_hash = hashlib.sha256(body.code.encode()).hexdigest()
        verifier_digest = base64.urlsafe_b64encode(hashlib.sha256(body.verifier.encode()).digest()).rstrip(b"=")
    except UnicodeEncodeError:  # a lone surrogate from a JSON escape
        raise refused from None
    taken = runtime.db.take_app_login_code(code_hash)
    if taken is None:
        raise refused
    user_id, challenge = taken
    # Bytes on both sides: compare_digest raises on a non-ASCII str.
    if not hmac.compare_digest(verifier_digest, challenge.encode()):
        raise refused
    account = runtime.db.get_account_by_id(user_id)
    if account is None or account.disabled:
        raise refused
    credit(attempts)
    token = new_session(account.id)
    log.info("User logged in with an app code", extra={"user_id": account.id})
    return TokenLogin(token=token, user=view(account))


@router.post("/logout", response_model=None, status_code=204)
def logout(request: Request, response: Response):
    token_hash = auth.session_token_hash(request)
    if token_hash:
        runtime.db.delete_session(token_hash)
    auth.clear_cookie(response)


@router.get("/me", response_model=UserView)
def me(user: Annotated[UserView, Depends(auth.current_user)]):
    return user


@router.post("/password", response_model=None, status_code=204)
def change_password(body: PasswordChange, request: Request, user: Annotated[UserView, Depends(auth.current_user)]):
    account = runtime.db.get_account_by_id(user.id)
    if account is None:
        raise HTTPException(404, "This server has no accounts")  # the fixed local user outside a deployment
    keys = [user_key(account.username), ip_key(request)]
    attempts = throttle(keys)
    if not accounts.verify_password(account.password_hash, body.current_password.get_secret_value()):
        raise HTTPException(400, "Current password is incorrect")
    credit(attempts)
    runtime.db.set_password(account.id, accounts.hash_password(body.new_password.get_secret_value()))
    runtime.db.delete_other_sessions(account.id, auth.session_token_hash(request))
    log.info("Password changed", extra={"user_id": account.id})
