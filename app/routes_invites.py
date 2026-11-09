"""Invites: an admin creates, lists and revokes them; anyone can ask whether a code still works (without using it up)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

import accounts
from app import auth, routes_auth, runtime
from app.logs import log
from models import InviteCheck, InviteCheckBody, InviteCreate, InviteCreated, InviteItem, UserView

NOT_FOUND = "Not found"
# Per IP per login window. Codes are 128-bit, so this only has to stop floods; a shared network or an admin testing links must fit.
INVITE_CHECK_LIMIT = 50


def require_admin(request: Request, response: Response) -> UserView:
    """The admin flag, never the fixed local user. Everyone else, a signed-out caller included, gets the answer a missing
    route would give, so the page's existence is not disclosed."""
    try:
        user = auth.current_user(request, response)
    except HTTPException:
        raise HTTPException(404, NOT_FOUND) from None
    if not user.is_admin or user.id == "local":
        raise HTTPException(404, NOT_FOUND)
    return user


admin = APIRouter(prefix="/api/admin/invites", dependencies=[Depends(auth.require_same_origin)])
public = APIRouter(prefix="/api/auth", dependencies=[Depends(auth.require_same_origin)])


@admin.post("", response_model=InviteCreated, status_code=201)
def create(body: InviteCreate, user: Annotated[UserView, Depends(require_admin)]):
    note = (body.note or "").strip() or None
    code, invite_id = accounts.issue_invite(runtime.db, kind=body.kind, note=note, created_by=user.id)
    created = runtime.db.get_invite(invite_id)
    log.info("Invite created", extra={"user_id": user.id, "invite_id": invite_id, "kind": body.kind})
    return InviteCreated(code=code, **{k: created[k] for k in ("id", "kind", "note", "created", "expires")})


@admin.get("", response_model=list[InviteItem])
def list_all(user: Annotated[UserView, Depends(require_admin)]):
    return runtime.db.list_invites()


@admin.delete("/{invite_id}", response_model=None, status_code=204)
def revoke(invite_id: str, user: Annotated[UserView, Depends(require_admin)]):
    result = runtime.db.revoke_invite(invite_id[:32])
    if result == "missing":
        raise HTTPException(404, NOT_FOUND)
    if result == "used":
        raise HTTPException(409, "That invite was already used")
    log.info("Invite revoked", extra={"user_id": user.id, "invite_id": invite_id[:32]})


@public.post("/invite-check", response_model=InviteCheck)
def invite_check(body: InviteCheckBody, request: Request):
    # Every call counts and none is credited back, so a right code costs the same as a wrong one and guessing stays slow.
    routes_auth.throttle([f"invite-check:{routes_auth.ip_key(request)}"], limit=INVITE_CHECK_LIMIT)
    found = runtime.db.invite_state(accounts.sha256(body.invite.get_secret_value().strip()))
    if found is None:
        return InviteCheck(valid=False, reason="unknown")
    kind, status = found
    if status == "unused":
        return InviteCheck(valid=True, kind=kind)
    return InviteCheck(valid=False, reason=status)
