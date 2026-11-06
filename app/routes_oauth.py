"""Sign-in with Google or GitHub (authorization code + PKCE) that opens a free trial, and the trial's status.

The browser is only ever redirected; the code is exchanged and the identity read server to server, from fixed provider
hosts, without following redirects. Nothing the provider returns is logged, and neither are codes or tokens."""

import base64
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import urlencode

import httpx2
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi import Path as PathParam
from fastapi.responses import RedirectResponse

import accounts
import storage
from app import anchors, auth, routes_auth, runtime
from app.logs import log
from models import TrialStatus, UserView

router = APIRouter(prefix="/api/auth/oauth")
trial_router = APIRouter(prefix="/api")

COOKIE = "lumio_oauth"
COOKIE_PATH = "/api/auth/oauth/"
STATE_SECONDS = 600
MIN_GITHUB_ACCOUNT_AGE = timedelta(days=30)
MAX_CODE = 2048
MAX_STATE = 512
APP_CODE_SECONDS = 60
APP_REDIRECT = "lumio://auth"
MAX_INVITE = 256
_INVITE_HASH = re.compile(r"[0-9a-f]{64}")
CLUSTER_SIZE = 3  # open sign-ups from one network within CLUSTER_SECONDS are worth a log line
CLUSTER_SECONDS = 600
MAX_BODY = 200_000  # a provider's identity reply is a few hundred bytes

ProviderName = Annotated[str, PathParam(pattern=r"^(google|github)$")]
CurrentUser = Annotated[UserView, Depends(auth.current_user)]

ENDPOINTS = {
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "scope": "openid email",
    },
    "github": {
        "authorize": "https://github.com/login/oauth/authorize",
        "token": "https://github.com/login/oauth/access_token",
        "scope": "read:user user:email",
    },
}
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
GITHUB_USER = "https://api.github.com/user"
GITHUB_EMAILS = "https://api.github.com/user/emails"


class AuthError(Exception):
    """Ends the flow with a redirect to /?auth_error=<code>. The codes are the contract with the UI."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Identity:
    subject: str
    email: str  # verified


def http_client() -> httpx2.Client:
    # No redirects: an endpoint that answers with one is treated as a failure instead of being followed to another host.
    return httpx2.Client(
        timeout=httpx2.Timeout(10.0, connect=5.0), follow_redirects=False, headers={"User-Agent": "Lumio", "Accept": "application/json"}
    )


def _pepper() -> str:
    return runtime.settings.oauth_pepper.get_secret_value()  # type: ignore[union-attr]  # trial_enabled guarantees it


# --- the state cookie: signed, httponly, short-lived ----------------------------------------------------


def _sign(payload: str) -> str:
    key = hmac.new(_pepper().encode(), b"oauth-state-cookie", hashlib.sha256).digest()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def _same(a: str, b: str) -> bool:
    # compare_digest raises on a non-ASCII str, which would turn a forged cookie or state into a 500.
    return hmac.compare_digest(a.encode(), b.encode())


def pack_state(data: dict) -> str:
    # No "=" padding: it would make the cookie value need quoting.
    payload = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return f"{payload}.{_sign(payload)}"


def unpack_state(value: str | None) -> dict | None:
    payload, _, signature = (value or "").partition(".")
    if not payload or not _same(signature, _sign(payload)):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except ValueError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("exp"), (int, float)) and data["exp"] > time.time() else None


# --- the native app's return address and PKCE challenge ----------------------------------------------------

# Expo Go's address changes per network, so these are only accepted while the operator has switched the dev flag on. Every
# character is whitelisted (no userinfo, query, fragment, whitespace or backslash), and the path must end in /--/auth.
_DEV_REDIRECT = re.compile(r"exps?://[A-Za-z0-9.\-]{1,253}(:[0-9]{1,5})?(/[A-Za-z0-9._~\-]+)*/--/auth")
_CHALLENGE = re.compile(r"[A-Za-z0-9_\-]{43}")  # base64url of a SHA-256 digest, unpadded


_DEV_HOST_SUFFIXES = (".local", ".exp.direct")
_DEV_HOSTS = frozenset({"localhost", "u.expo.dev"})


def _dev_host_allowed(host: str) -> bool:
    # The one-time code goes to this address, so an arbitrary hostname would hand it to whoever owns that host.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host in _DEV_HOSTS or host.endswith(_DEV_HOST_SUFFIXES)
    return ip.is_private or ip.is_loopback


def valid_app_redirect(url: object) -> str | None:
    if not isinstance(url, str) or len(url) > 512:
        return None
    if url == APP_REDIRECT:
        return url
    if runtime.settings.oauth_app_dev_redirects and _DEV_REDIRECT.fullmatch(url) and not {".", ".."} & set(url.split("/")):
        authority = url.split("/", 3)[2]
        if _dev_host_allowed(authority.partition(":")[0].lower()):
            return url
    return None


def valid_challenge(value: object) -> str | None:
    return value if isinstance(value, str) and _CHALLENGE.fullmatch(value) else None


def _redirect(target: str, request: Request) -> RedirectResponse:
    response = RedirectResponse(target, status_code=302)
    response.delete_cookie(COOKIE, path=COOKIE_PATH, httponly=True, samesite="lax", secure=runtime.settings.deployed)
    return response


def _failure(code: str, request: Request, app_redirect: str | None = None) -> RedirectResponse:
    # The app's address comes only from the signed state cookie, validated again here; without it the web path is used.
    return _redirect(f"{app_redirect or '/'}?{urlencode({'auth_error': code})}", request)


def redirect_uri(provider: str) -> str:
    return f"{runtime.settings.origin}/api/auth/oauth/{provider}/callback"


def _configured(provider: str) -> bool:
    return runtime.settings.trial_enabled and provider in runtime.settings.oauth_providers()


def _credentials(provider: str) -> tuple[str, str]:
    s = runtime.settings
    return getattr(s, f"oauth_{provider}_client_id"), getattr(s, f"oauth_{provider}_client_secret").get_secret_value()


# --- the provider calls --------------------------------------------------------------------------------


def _json(res: httpx2.Response):
    if res.status_code != 200 or len(res.content) > MAX_BODY:
        raise AuthError("provider")
    try:
        return res.json()
    except ValueError:
        raise AuthError("provider") from None


def exchange_code(client: httpx2.Client, provider: str, code: str, verifier: str) -> str:
    client_id, secret = _credentials(provider)
    res = client.post(
        ENDPOINTS[provider]["token"],
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(provider),
            "client_id": client_id,
            "client_secret": secret,
            "code_verifier": verifier,
        },
    )
    data = _json(res)
    token = data.get("access_token") if isinstance(data, dict) else None
    if not isinstance(token, str) or not token:
        raise AuthError("provider")
    return token


def google_identity(client: httpx2.Client, token: str) -> Identity:
    data = _json(client.get(GOOGLE_USERINFO, headers={"Authorization": f"Bearer {token}"}))
    if not isinstance(data, dict):
        raise AuthError("provider")
    subject, email = data.get("sub"), data.get("email")
    if not isinstance(subject, str) or not subject or not isinstance(email, str):
        raise AuthError("provider")
    if data.get("email_verified") is not True:
        raise AuthError("unverified")
    return Identity(subject, email)


def github_identity(client: httpx2.Client, token: str, now: datetime | None = None) -> Identity:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    user = _json(client.get(GITHUB_USER, headers=headers))
    if not isinstance(user, dict):
        raise AuthError("provider")
    subject, created = user.get("id"), user.get("created_at")
    if not isinstance(subject, int) or isinstance(subject, bool) or not isinstance(created, str):
        raise AuthError("provider")
    try:
        born = datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError:
        raise AuthError("provider") from None
    if (now or datetime.now(timezone.utc)) - born < MIN_GITHUB_ACCOUNT_AGE:
        raise AuthError("too_new")
    emails = _json(client.get(GITHUB_EMAILS, headers=headers))
    primary = next(
        (e["email"] for e in emails if isinstance(e, dict) and e.get("primary") is True and e.get("verified") is True and isinstance(e.get("email"), str)),
        None,
    ) if isinstance(emails, list) else None
    if primary is None:
        raise AuthError("unverified")
    return Identity(str(subject), primary)


def fetch_identity(provider: str, code: str, verifier: str) -> Identity:
    try:
        with http_client() as client:
            token = exchange_code(client, provider, code, verifier)
            return google_identity(client, token) if provider == "google" else github_identity(client, token)
    except httpx2.HTTPError as e:
        log.warning("OAuth provider call failed", extra={"provider": provider, "error": type(e).__name__})
        raise AuthError("provider") from None


# --- signup throttle key ---------------------------------------------------------------------------------


def signup_ip_key(ip: str) -> str:
    """One bucket per IPv4 address and per IPv6 /64: a single customer holds that many addresses, so per-address keys are no limit."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return f"signup:ip:{ip[:64]}"
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped:
            return f"signup:ip:{addr.ipv4_mapped}"
        return f"signup:ip:{ipaddress.ip_network((addr, 64), strict=False)}"
    return f"signup:ip:{addr}"


_cluster_lock = threading.Lock()
_cluster_seen: dict[str, list[float]] = {}
_cluster_alerted: dict[str, float] = {}


def signup_network(ip_key: str) -> str | None:
    """The /24 (IPv4) or /48 (IPv6) a signup_ip_key falls in, for spotting one customer spread over many addresses."""
    try:
        net = ipaddress.ip_network(ip_key.removeprefix("signup:ip:"), strict=False)
    except ValueError:
        return None
    return str(net.supernet(new_prefix=24 if net.version == 4 else 48))


def note_open_signup(ip_key: str, now: float | None = None) -> None:
    """Warns once per window when CLUSTER_SIZE open sign-ups arrive from one network. In memory and per process: a
    signal for the operator, not a limit."""
    network = signup_network(ip_key)
    if network is None:
        return
    now = time.time() if now is None else now
    with _cluster_lock:
        seen = [t for t in _cluster_seen.get(network, []) if t > now - CLUSTER_SECONDS] + [now]
        _cluster_seen[network] = seen
        for key in [k for k, t in _cluster_alerted.items() if t <= now - CLUSTER_SECONDS]:
            del _cluster_alerted[key]
        if len(seen) < CLUSTER_SIZE or network in _cluster_alerted:
            return
        _cluster_alerted[network] = now
    log.warning(
        "Open sign-ups clustered on one network: %d from %s within %d minutes",
        len(seen), network, CLUSTER_SECONDS // 60,
        extra={"network": network, "count": len(seen), "window_seconds": CLUSTER_SECONDS},
    )


# --- routes -------------------------------------------------------------------------------------------------


@router.get("/{provider}/start", response_model=None, response_class=RedirectResponse, status_code=302)
def start(
    provider: ProviderName,
    client: str | None = None,
    redirect: str | None = None,
    challenge: str | None = None,
    invite: str | None = None,
):
    app_state: dict = {}
    if client is not None:
        # Nothing is redirected to until both are known good: a bad request is an error page, never a bounce to a stranger's URL.
        target, pkce = valid_app_redirect(redirect), valid_challenge(challenge)
        if client != "app" or target is None or pkce is None:
            return JSONResponse({"detail": "Invalid app sign-in request"}, status_code=400)
        app_state = {"r": target, "c": pkce}
    if not _configured(provider):
        return RedirectResponse(f"{app_state['r']}?auth_error=unavailable" if app_state else "/?auth_error=unavailable", status_code=302)
    # Only the invite's hash goes into the cookie, and nothing about it into a URL or a log line.
    invite_hash = None
    if invite is not None and invite.strip():
        invite_hash = accounts.sha256(invite.strip())
        if len(invite) > MAX_INVITE or not runtime.db.invite_valid(invite_hash, "trial"):
            return RedirectResponse(f"{app_state['r']}?auth_error=invite" if app_state else "/?auth_error=invite", status_code=302)
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query = {
        "client_id": _credentials(provider)[0],
        "redirect_uri": redirect_uri(provider),
        "response_type": "code",
        "scope": ENDPOINTS[provider]["scope"],
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if provider == "google":
        query["prompt"] = "select_account"
    response = RedirectResponse(f"{ENDPOINTS[provider]['authorize']}?{urlencode(query)}", status_code=302)
    response.set_cookie(
        COOKIE,
        pack_state({"p": provider, "s": state, "v": verifier, "exp": time.time() + STATE_SECONDS, **app_state, **({"i": invite_hash} if invite_hash else {})}),
        max_age=STATE_SECONDS,
        httponly=True,
        samesite="lax",  # the provider sends the browser back with a top-level GET, which Strict would not carry the cookie on
        path=COOKIE_PATH,
        secure=runtime.settings.deployed,
    )
    return response


@router.get("/{provider}/callback", response_model=None, response_class=RedirectResponse, status_code=302)
def callback(
    provider: ProviderName,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    saved = unpack_state(request.cookies.get(COOKIE))
    app_redirect = valid_app_redirect(saved.get("r")) if saved else None
    if not _configured(provider):
        return _failure("unavailable", request, app_redirect)
    try:
        account, granted = _identify(provider, request, saved, code, state, error)
        if app_redirect:
            challenge = valid_challenge(saved.get("c"))
            if challenge is None:
                raise AuthError("state")
            return _app_success(request, provider, app_redirect, challenge, account, granted)
        response = _redirect("/?auth_error=trial_used" if granted is False else "/", request)
        routes_auth.start_session(response, account.id)
        _log_sign_in(account, provider, granted, "web")
        return response
    except AuthError as e:
        return _failure(e.code, request, app_redirect)


def _log_sign_in(account: storage.Account, provider: str, granted: bool | None, client: str) -> None:
    log.info(
        "User signed in with OAuth",
        extra={"user_id": account.id, "provider": provider, "new": granted is not None, "trial": bool(granted), "client": client},
    )


def _app_success(
    request: Request, provider: str, app_redirect: str, challenge: str, account: storage.Account, granted: bool | None
) -> RedirectResponse:
    """The app gets a one-time code instead of a cookie; it trades the code plus its PKCE verifier for a session."""
    login_code = secrets.token_urlsafe(32)
    runtime.db.create_app_login_code(
        hashlib.sha256(login_code.encode()).hexdigest(), account.id, challenge, time.time() + APP_CODE_SECONDS
    )
    query = {"code": login_code}
    if granted is False:
        query["auth_error"] = "trial_used"  # still signed in, just without a trial
    _log_sign_in(account, provider, granted, "app")
    return _redirect(f"{app_redirect}?{urlencode(query)}", request)


def _identify(
    provider: str, request: Request, saved: dict | None, code: str | None, state: str | None, error: str | None
) -> tuple[storage.Account, bool | None]:
    """Checks the state, asks the provider who this is and finds or enrols the account. Shared by the web and the app flow."""
    state = state if state is None or len(state) <= MAX_STATE else None
    # State first: a callback that this browser did not start gets nothing further, not even an answer about the provider's error.
    if saved is None or saved.get("p") != provider or not state or not isinstance(saved.get("s"), str) or not _same(saved["s"], state):
        raise AuthError("state")
    if error or not code:
        raise AuthError("denied")
    if len(code) > MAX_CODE:
        raise AuthError("provider")
    verifier = saved.get("v")
    if not isinstance(verifier, str) or not verifier:
        raise AuthError("state")

    identity = fetch_identity(provider, code, verifier)
    subject = anchors.anchor(_pepper(), f"oauth:{provider}", identity.subject)
    account = runtime.db.find_identity(provider, subject)
    granted = None
    if account is None:
        email = anchors.normalize_email(identity.email)
        if email is None:
            raise AuthError("unverified")
        if anchors.is_disposable(email):
            raise AuthError("disposable")
        invite_hash = saved.get("i") if saved else None
        invite_hash = invite_hash if isinstance(invite_hash, str) and _INVITE_HASH.fullmatch(invite_hash) else None
        ip_key = signup_ip_key(routes_auth.client_ip(request))
        if invite_hash is None:
            note_open_signup(ip_key)
        settings = runtime.settings
        try:
            account, granted = runtime.db.enrol_oauth_user(
                provider,
                subject,
                [(f"oauth:{provider}", subject), ("email", anchors.anchor(_pepper(), "email", email))],
                trial_calls=runtime.settings.trial_calls,
                day_limit=settings.reserved_signup_limit if invite_hash else settings.open_signup_limit,
                ip_key=ip_key,
                invite_hash=invite_hash,
            )
        except storage.SignupFull as e:
            log.warning("Sign-up refused: pool full", extra={"pool": e.pool, "wait": e.wait})
            raise AuthError("open_full" if e.pool == "open" else "reserved_full") from None
        except storage.SignupThrottled as e:
            log.warning("Sign-up refused: throttled", extra={"ip": routes_auth.client_ip(request), "wait": e.wait})
            raise AuthError("throttled") from None
        except storage.InvalidInvite:
            log.warning("Sign-up refused: invalid invite", extra={"ip": routes_auth.client_ip(request)})
            raise AuthError("invite") from None
        except storage.IdentityExists:
            account = runtime.db.find_identity(provider, subject)  # a parallel request linked it first
            if account is None:
                raise AuthError("provider") from None
    if account.disabled:
        raise AuthError("disabled")
    return account, granted


@trial_router.get("/trial", response_model=TrialStatus)
def get_trial(user: CurrentUser):
    trial = None if user.id == "local" else runtime.db.get_trial(user.id)
    if trial is None:
        return TrialStatus(enrolled=False, limit=0, used=0, remaining=0, ended=False)
    return TrialStatus(
        enrolled=True,
        limit=trial.limit,
        used=trial.used,
        remaining=trial.remaining,
        ended=trial.exhausted or not runtime.settings.trial_enabled,
    )
