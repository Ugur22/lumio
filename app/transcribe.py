"""Local YouTube song transcription: yt-dlp -> ffmpeg -> whisper.cpp, one job at a time (docs/transcription.md)."""
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app.logs import log
from models import Settings, TranscriptionJob

DOCS_HINT = "See docs/transcription.md for setup."
_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_LANG = re.compile(r"^(auto|[a-z]{2,3})$")
_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR")
_KILL_GRACE = 2.0
_POLL = 0.2
_ACTIVE = {"queued", "checking", "downloading", "converting", "transcribing"}
_KEEP_FINISHED = 20


class TranscribeError(Exception):
    """Message is safe to show to the user."""


class JobBusy(Exception):
    pass


class Cancelled(Exception):
    pass


@dataclass
class Result:
    title: str
    video_id: str
    url: str
    language: str
    model: str
    original_text: str
    segments: list[dict]


def availability(settings: Settings) -> tuple[bool, str]:
    try:
        if settings.deployed:
            return False, f"Transcription runs only on a local install. {DOCS_HINT}"
        cli, model = settings.whisper_cli_path, settings.whisper_model_path
        if not cli or not model:
            return False, f"whisper.cpp is not configured (set whisper_cli_path and whisper_model_path). {DOCS_HINT}"
        if not Path(cli).is_file():
            return False, f"whisper-cli was not found at the configured path. {DOCS_HINT}"
        if not Path(model).is_file():
            return False, f"The whisper model file was not found at the configured path. {DOCS_HINT}"
        for name, value in (("yt-dlp", settings.yt_dlp_path), ("ffmpeg", settings.ffmpeg_path)):
            if not _resolve(value):
                return False, f"{name} was not found. {DOCS_HINT}"
        return True, ""
    except Exception:
        log.exception("transcription availability check failed")
        return False, f"Transcription is unavailable. {DOCS_HINT}"


def _resolve(tool: str) -> str | None:
    return shutil.which(tool)


def parse_youtube_url(raw: str) -> tuple[str, str]:
    bad = TranscribeError("Enter a link to a single YouTube video (youtube.com or youtu.be).")
    raw = (raw or "").strip()
    if not raw or len(raw) > 500 or re.search(r"[\s\x00-\x1f\\]", raw):
        raise bad
    try:
        parts = urlsplit(raw)
        host, port = (parts.hostname or "").lower(), parts.port
    except ValueError:
        raise bad from None
    if parts.scheme not in ("http", "https") or "@" in parts.netloc or port not in (None, 80, 443):
        raise bad
    query = parse_qs(parts.query)
    segs = [s for s in parts.path.split("/") if s]
    video_id = None
    if host == "youtu.be":
        video_id = segs[0] if len(segs) == 1 else None
    elif host in _HOSTS:
        if parts.path == "/watch":
            video_id = (query.get("v") or [None])[0]
        elif len(segs) == 2 and segs[0] == "shorts":
            video_id = segs[1]
    if not video_id or not _ID.match(video_id):
        raise bad
    return video_id, f"https://www.youtube.com/watch?v={video_id}"


def spawn(args: list[str], **kw) -> subprocess.Popen:
    """The only place a subprocess starts; tests replace it."""
    env = {k: os.environ[k] for k in _ENV_KEYS if k in os.environ}
    return subprocess.Popen(
        args, shell=False, start_new_session=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, **kw,
    )


def _signal_group(proc, sig: int) -> None:
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _kill(proc) -> None:
    _signal_group(proc, signal.SIGTERM)
    try:
        proc.wait(timeout=_KILL_GRACE)
    except subprocess.TimeoutExpired:
        _signal_group(proc, signal.SIGKILL)
        proc.wait()


def _tail(data: bytes | str | None) -> str:
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else (data or "")
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text).strip()
    return text[-300:]


class _Run:
    """Per-run budget shared by every step."""

    def __init__(self, settings: Settings, cancelled: threading.Event):
        self.cancelled = cancelled
        self.deadline = time.monotonic() + settings.transcribe_timeout_minutes * 60

    def exec(self, args: list[str], label: str, step_timeout: float) -> str:
        if self.cancelled.is_set():
            raise Cancelled()
        proc = spawn(args)
        limit = min(time.monotonic() + step_timeout, self.deadline)
        out = err = b""
        try:
            while True:
                try:
                    out, err = proc.communicate(timeout=_POLL)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if self.cancelled.is_set():
                    _kill(proc)
                    raise Cancelled()
                if time.monotonic() >= limit:
                    _kill(proc)
                    whole = time.monotonic() >= self.deadline
                    raise TranscribeError("Transcription took too long and was stopped." if whole else f"The {label} step took too long and was stopped.")
        except BaseException:
            if proc.poll() is None:
                _kill(proc)
            raise
        if proc.returncode != 0:
            raise TranscribeError(f"The {label} step failed: {_tail(err) or 'no details'}")
        return out.decode("utf-8", "replace") if isinstance(out, bytes) else out or ""


def run_pipeline(
    settings: Settings, url: str, language: str, on_stage: Callable[[str], None],
    cancelled: threading.Event, on_title: Callable[[str], None] = lambda _t: None,
) -> Result:
    if not _LANG.match(language or ""):
        raise TranscribeError("Unsupported language code.")
    video_id, canonical = parse_youtube_url(url)
    ytdlp = _resolve(settings.yt_dlp_path) or settings.yt_dlp_path
    ffmpeg = _resolve(settings.ffmpeg_path) or settings.ffmpeg_path
    cli, model = str(settings.whisper_cli_path), Path(str(settings.whisper_model_path))
    max_s = settings.transcribe_max_minutes * 60
    run = _Run(settings, cancelled)
    base = settings.data_dir / "tmp"
    base.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="tr-", dir=base))
    try:
        on_stage("checking")
        raw = run.exec([ytdlp, "--ignore-config", "--no-playlist", "--skip-download", "--dump-single-json",
                        "--no-warnings", "--socket-timeout", "15", "--", canonical], "video check", 90)
        try:
            info = json.loads(raw)
        except ValueError:
            raise TranscribeError("Could not read the video information.") from None
        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming", "was_live"):
            raise TranscribeError("Live streams and live replays cannot be transcribed.")
        duration = info.get("duration")
        if not isinstance(duration, (int, float)) or duration <= 0:
            raise TranscribeError("The video has no known duration, so it cannot be transcribed.")
        if duration > max_s:
            raise TranscribeError(f"The video is longer than the {settings.transcribe_max_minutes} minute limit.")
        title = str(info.get("title") or "")
        on_title(title)

        on_stage("downloading")
        run.exec([ytdlp, "--ignore-config", "--no-playlist", "--no-warnings", "-f", "ba",
                  "--max-filesize", f"{settings.transcribe_max_download_mb}M", "--socket-timeout", "15",
                  "--no-part", "-P", str(tmp), "-o", "audio.%(ext)s", "--", canonical], "download", 900)
        src = next((p for p in sorted(tmp.glob("audio.*")) if p.suffix not in (".json", ".part")), None)
        if src is None:
            raise TranscribeError(f"No audio was downloaded (the file may exceed {settings.transcribe_max_download_mb} MB).")

        on_stage("converting")
        wav = tmp / "out.wav"
        run.exec([ffmpeg, "-nostdin", "-y", "-i", str(src), "-t", str(max_s), "-ar", "16000", "-ac", "1",
                  "-c:a", "pcm_s16le", str(wav)], "audio conversion", 600)

        on_stage("transcribing")
        run.exec([cli, "-m", str(model), "-f", str(wav), "-l", language, "-mc", "0", "-oj", "-of", str(tmp / "out"), "-np"],
                 "transcription", max(60.0, run.deadline - time.monotonic()))
        try:
            data = json.loads((tmp / "out.json").read_text("utf-8"))
        except (OSError, ValueError):
            raise TranscribeError("The transcription produced no readable output.") from None
        segments = []
        for item in data.get("transcription") or []:
            text = str(item.get("text") or "").strip()
            if text:
                off = item.get("offsets") or {}
                segments.append({"start": float(off.get("from", 0)) / 1000, "end": float(off.get("to", 0)) / 1000, "text": text})
        if not segments:
            raise TranscribeError("No speech was recognised in this video.")
        # -mc 0 stops the usual loop, but a track that still loops must not be saved as if it were lyrics.
        if len(segments) >= 3 and len({s["text"] for s in segments}) == 1:
            raise TranscribeError("Whisper only produced one phrase, repeated. The vocals were probably not picked up; try naming the language or another track.")
        lang = language
        if language == "auto":
            lang = str((data.get("result") or {}).get("language") or "auto")
        return Result(title=title, video_id=video_id, url=canonical, language=lang, model=model.name,
                      original_text="\n".join(s["text"] for s in segments), segments=segments)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def sweep_tmp(settings: Settings) -> None:
    shutil.rmtree(settings.data_dir / "tmp", ignore_errors=True)


class Jobs:
    def __init__(self, settings: Settings, save: Callable[[str, str, Result], str]):
        self._settings, self._save = settings, save
        self._lock = threading.Lock()
        self._jobs: OrderedDict[str, dict] = OrderedDict()
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._stopped = False

    def submit(self, owner: str, chat_id: str, url: str, language: str) -> TranscriptionJob:
        _, canonical = parse_youtube_url(url)
        if not _LANG.match(language or ""):
            raise TranscribeError("Unsupported language code.")
        with self._lock:
            if self._stopped or any(j["job"].state in _ACTIVE for j in self._jobs.values()):
                raise JobBusy()
            job = TranscriptionJob(id=uuid.uuid4().hex, chat_id=chat_id, url=canonical, state="queued",
                                   title="", error="", transcript_id=None)
            rec = {"job": job, "owner": owner, "language": language, "cancel": threading.Event()}
            self._jobs[job.id] = rec
            if self._worker is None:
                self._worker = threading.Thread(target=self._loop, name="transcribe", daemon=True)
                self._worker.start()
            self._queue.put(job.id)
            return job.model_copy()

    def _own(self, job_id: str, owner: str, chat_id: str) -> dict | None:
        rec = self._jobs.get(job_id)
        return rec if rec and rec["owner"] == owner and rec["job"].chat_id == chat_id else None

    def get(self, job_id: str, owner: str, chat_id: str) -> TranscriptionJob | None:
        with self._lock:
            rec = self._own(job_id, owner, chat_id)
            return rec["job"].model_copy() if rec else None

    def active(self, owner: str, chat_id: str) -> TranscriptionJob | None:
        """The running job of this chat, so a reopened dialog (or a reload) can find it again instead of hitting 409."""
        with self._lock:
            for rec in self._jobs.values():
                if rec["job"].state in _ACTIVE and rec["owner"] == owner and rec["job"].chat_id == chat_id:
                    return rec["job"].model_copy()
        return None

    def cancel(self, job_id: str, owner: str, chat_id: str) -> TranscriptionJob | None:
        with self._lock:
            rec = self._own(job_id, owner, chat_id)
            if rec is None:
                return None
            if rec["job"].state in _ACTIVE:
                rec["cancel"].set()
            return rec["job"].model_copy()

    def shutdown(self) -> None:
        with self._lock:
            self._stopped = True
            for rec in self._jobs.values():
                if rec["job"].state in _ACTIVE:
                    rec["cancel"].set()
            worker = self._worker
        self._queue.put(None)
        if worker:
            worker.join(timeout=10)

    def _set(self, rec: dict, **changes) -> None:
        with self._lock:
            for k, v in changes.items():
                setattr(rec["job"], k, v)

    def _loop(self) -> None:
        while (job_id := self._queue.get()) is not None:
            with self._lock:
                rec = self._jobs[job_id]
            self._run(rec)
            self._trim()

    def _run(self, rec: dict) -> None:
        job_id = rec["job"].id
        try:
            if rec["cancel"].is_set():
                raise Cancelled()
            result = run_pipeline(self._settings, rec["job"].url, rec["language"],
                                  lambda s: self._set(rec, state=s), rec["cancel"],
                                  lambda t: self._set(rec, title=t))
            if rec["cancel"].is_set():
                raise Cancelled()
            self._set(rec, transcript_id=self._save(rec["owner"], rec["job"].chat_id, result), state="done")
        except Cancelled:
            self._set(rec, state="cancelled")
        except TranscribeError as e:
            self._set(rec, state="failed", error=str(e))
        except Exception:
            log.exception("transcription job crashed", extra={"job_id": job_id})
            self._set(rec, state="failed", error="Transcription failed")

    def _trim(self) -> None:
        with self._lock:
            finished = [k for k, r in self._jobs.items() if r["job"].state not in _ACTIVE]
            for k in finished[:-_KEEP_FINISHED]:
                del self._jobs[k]
