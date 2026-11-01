"""Local song transcription: availability, the transcription job of a chat, and its saved transcripts."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi import Path as PathParam

import storage
from app import auth, runtime, transcribe
from models import (
    TranscribeRequest,
    Transcript,
    TranscriptionJob,
    TranscriptionStatus,
    TranscriptSummary,
    TranscriptUpdate,
    UserView,
)

router = APIRouter(dependencies=[Depends(auth.require_same_origin)])
CurrentUser = Annotated[UserView, Depends(auth.current_user)]
ChatId = Annotated[str, PathParam(pattern=r"^[0-9a-f]{32}$")]
JobId = Annotated[str, PathParam(pattern=r"^[0-9a-f]{32}$")]
TranscriptId = Annotated[str, PathParam(pattern=r"^[0-9a-f]{32}$")]


def chat_gone() -> HTTPException:
    return HTTPException(404, "Chat not found")


def transcript_gone() -> HTTPException:
    return HTTPException(404, "Transcript not found")


def require_chat(chat_id: str, user: UserView) -> None:
    # Jobs are keyed by owner and chat, but the chat itself is checked here so another user's id answers like a missing one.
    if chat_id not in {c.id for c in runtime.db.list_chats(owner=user.id)}:
        raise chat_gone()


@router.get("/api/transcription", response_model=TranscriptionStatus)
def transcription_status(user: CurrentUser):
    available, reason = transcribe.availability(runtime.settings)
    s = runtime.settings
    return TranscriptionStatus(
        available=available,
        reason=reason,
        model=s.whisper_model_path.name if s.whisper_model_path else "",
        max_minutes=s.transcribe_max_minutes,
        max_download_mb=s.transcribe_max_download_mb,
    )


@router.post("/api/chats/{chat_id}/transcriptions", response_model=TranscriptionJob, status_code=202)
def start_transcription(chat_id: ChatId, body: TranscribeRequest, user: CurrentUser):
    require_chat(chat_id, user)
    available, reason = transcribe.availability(runtime.settings)
    if not available:
        raise HTTPException(503, reason)
    try:
        return runtime.jobs.submit(user.id, chat_id, body.url, body.language)
    except transcribe.TranscribeError as e:
        raise HTTPException(422, str(e))
    except transcribe.JobBusy:
        raise HTTPException(409, "A transcription is already running")


@router.get("/api/chats/{chat_id}/transcriptions", response_model=TranscriptionJob | None)
def active_transcription(chat_id: ChatId, user: CurrentUser):
    require_chat(chat_id, user)
    return runtime.jobs.active(user.id, chat_id)


@router.get("/api/chats/{chat_id}/transcriptions/{job_id}", response_model=TranscriptionJob)
def get_transcription(chat_id: ChatId, job_id: JobId, user: CurrentUser):
    require_chat(chat_id, user)
    job = runtime.jobs.get(job_id, user.id, chat_id)
    if job is None:
        raise HTTPException(404, "Transcription not found")
    return job


@router.delete("/api/chats/{chat_id}/transcriptions/{job_id}", response_model=TranscriptionJob)
def cancel_transcription(chat_id: ChatId, job_id: JobId, user: CurrentUser):
    require_chat(chat_id, user)
    job = runtime.jobs.cancel(job_id, user.id, chat_id)
    if job is None:
        raise HTTPException(404, "Transcription not found")
    return job


@router.get("/api/chats/{chat_id}/transcripts", response_model=list[TranscriptSummary])
def list_transcripts(chat_id: ChatId, user: CurrentUser):
    try:
        return runtime.db.list_transcripts(chat_id, owner=user.id)
    except storage.ChatNotFound:
        raise chat_gone()


@router.get("/api/chats/{chat_id}/transcripts/{transcript_id}", response_model=Transcript)
def get_transcript(chat_id: ChatId, transcript_id: TranscriptId, user: CurrentUser):
    try:
        return runtime.db.get_transcript(chat_id, transcript_id, owner=user.id)
    except storage.ChatNotFound:
        raise chat_gone()
    except storage.TranscriptNotFound:
        raise transcript_gone()


@router.put("/api/chats/{chat_id}/transcripts/{transcript_id}", response_model=Transcript)
def update_transcript(chat_id: ChatId, transcript_id: TranscriptId, body: TranscriptUpdate, user: CurrentUser):
    try:
        return runtime.db.update_transcript(chat_id, transcript_id, body.edited_text, owner=user.id)
    except storage.ChatNotFound:
        raise chat_gone()
    except storage.TranscriptNotFound:
        raise transcript_gone()


@router.delete("/api/chats/{chat_id}/transcripts/{transcript_id}", status_code=204)
def delete_transcript(chat_id: ChatId, transcript_id: TranscriptId, user: CurrentUser):
    try:
        runtime.db.delete_transcript(chat_id, transcript_id, owner=user.id)
    except storage.ChatNotFound:
        raise chat_gone()
    except storage.TranscriptNotFound:
        raise transcript_gone()
    return Response(status_code=204)
