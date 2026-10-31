"""Accounts: invite-only registration, login, logout and password change."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

import accounts
import storage
from app import auth, runtime
from app.logs import log
from models import LoginBody, PasswordChange, RegisterBody, UserView

router = APIRouter(prefix="/api/auth", dependencies=[Depends(auth.require_same_origin)])

INVALID_LOGIN = "Invalid username or password"
INVALID_INVITE = "That invite is not valid"


def client_ip(request: Request) -> str:
    # uvicorn --proxy-headers (behind Caddy on 127.0.0.1) already resolved this; X-Forwarded-For is never read here.
    return request.client.host if request.client else "unknown"


def ip_key(request: Request) -> str:
    return f"ip:{client_ip(request)}"


def user_key(username: str) -> str:
    return f"user:{username[:64]}"


def throttle(keys: list[str]) -> list[int]:
    """Counts this attempt as a failure up front and returns what to hand to `credit` if it succeeds. Recording after the
    password check would let parallel guesses (each slow to hash) all see an empty record."""
    wait, attempts = runtime.db.take_login_attempt(keys)
    if wait:
        raise HTTPException(429, "Too many failed attempts; try again later", headers={"Retry-After": str(wait)})
    return attempts


def credit(attempts: list[int]) -> None:
    runtime.db.forget_login_attempts(attempts)


def start_session(response: Response, user_id: str) -> None:
    token = accounts.new_token()
    runtime.db.create_session(accounts.sha256(token), user_id)
    auth.set_cookie(response, token)


def view(account: storage.Account) -> UserView:
    return UserView(id=account.id, username=account.username, is_admin=account.is_admin)


@router.post("/register", response_model=UserView, status_code=201)
def register(body: RegisterBody, request: Request, response: Response):
    # Every refusal counts (a bad invite, and a taken name, which would otherwise list the users that exist). Only the IP is
    # keyed: a per-name key would just let a stranger lock a name out.
    attempts = throttle([ip_key(request)])
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


@router.post("/login", response_model=UserView)
def login(body: LoginBody, request: Request, response: Response):
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
    start_session(response, account.id)
    log.info("User logged in", extra={"user_id": account.id})
    return view(account)


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
