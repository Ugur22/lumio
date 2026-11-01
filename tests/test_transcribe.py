import json
import subprocess
import threading
import time
from pathlib import Path

import pytest

from app import transcribe
from app.transcribe import Cancelled, JobBusy, Jobs, TranscribeError
from models import Settings

VID = "dQw4w9WgXcQ"
URL = f"https://www.youtube.com/watch?v={VID}"


class FakeProc:
    def __init__(self, rc=0, out=b"", err=b"", hang=False, pid=4242):
        self.rc, self.out, self.err, self.hang, self.pid = rc, out, err, hang, pid
        self.returncode = None
        self.killed = []

    def communicate(self, timeout=None):
        if self.hang and not self.killed:
            time.sleep(min(timeout or 0.05, 0.05))
            raise subprocess.TimeoutExpired("x", timeout)
        self.returncode = self.rc if not self.killed else -15
        return self.out, self.err

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = self.returncode if self.returncode is not None else -15
        return self.returncode


class Env:
    """Routes each tool name to a canned FakeProc and records every call."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.procs: list[FakeProc] = []
        self.probe = {"title": "Song", "duration": 200, "is_live": False, "live_status": "not_live"}
        self.fail: dict[str, tuple[int, bytes]] = {}
        self.hang: str | None = None
        self.segments = [{"offsets": {"from": 0, "to": 1500}, "text": " Hello "}, {"offsets": {"from": 1500, "to": 2000}, "text": "  "},
                         {"offsets": {"from": 2000, "to": 3000}, "text": "world"}]
        self.language = "en"
        self.dirs: list[Path] = []
        self.started = threading.Event()

    def spawn(self, args, **kw):
        self.calls.append(args)
        tool = Path(args[0]).name
        if tool in self.fail:
            rc, err = self.fail[tool]
            proc = FakeProc(rc=rc, err=err)
        elif tool == "ytdlp" and "--dump-single-json" in args:
            proc = FakeProc(out=json.dumps(self.probe).encode())
        elif tool == "ytdlp":
            d = Path(args[args.index("-P") + 1])
            self.dirs.append(d)
            (d / "audio.webm").write_bytes(b"a")
            proc = FakeProc()
        elif tool == "ffmpeg":
            Path(args[-1]).write_bytes(b"w")
            proc = FakeProc()
        else:
            Path(args[args.index("-of") + 1] + ".json").write_text(
                json.dumps({"result": {"language": self.language}, "transcription": self.segments}))
            proc = FakeProc()
        if tool == self.hang:
            proc.hang = True
        self.procs.append(proc)
        self.started.set()
        return proc


@pytest.fixture
def env(monkeypatch):
    e = Env()
    monkeypatch.setattr(transcribe, "spawn", e.spawn)
    monkeypatch.setattr(transcribe, "_resolve", lambda t: t)
    monkeypatch.setattr(transcribe, "_signal_group", lambda proc, sig: proc.killed.append(sig))
    monkeypatch.setattr(transcribe, "_POLL", 0.01)
    return e


@pytest.fixture
def settings(tmp_path):
    model = tmp_path / "ggml-small.bin"
    model.write_bytes(b"m")
    return Settings(data_dir=tmp_path / "data", yt_dlp_path="ytdlp", ffmpeg_path="ffmpeg",
                    whisper_cli_path=tmp_path / "whisper", whisper_model_path=model)


def run(settings, language="auto", cancelled=None, stages=None, titles=None):
    return transcribe.run_pipeline(settings, URL, language, (stages if stages is not None else []).append,
                                   cancelled or threading.Event(), (titles if titles is not None else []).append)


def tmp_left(settings):
    d = settings.data_dir / "tmp"
    return list(d.iterdir()) if d.exists() else []


@pytest.mark.parametrize("raw", [
    URL, f"http://youtube.com/watch?v={VID}", f"https://m.youtube.com/watch?v={VID}&t=5",
    f"https://music.youtube.com/watch?v={VID}", f"https://youtu.be/{VID}?si=abc",
    f"https://www.youtube.com/shorts/{VID}", f"https://www.youtube.com/watch?v={VID}&list=PLabc&index=2", f"  {URL}  ",
])
def test_url_accepted(raw):
    assert transcribe.parse_youtube_url(raw) == (VID, URL)


@pytest.mark.parametrize("raw", [
    "", "not a url", "ftp://www.youtube.com/watch?v=" + VID, "https://www.youtube.com/playlist?list=PLabcdefgh",
    "https://www.youtube.com/watch?list=PLabcdefgh", f"https://www.youtube.com/live/{VID}",
    f"https://user:pw@www.youtube.com/watch?v={VID}", f"https://evil.com/watch?v={VID}",
    f"https://www.youtube.com.evil.com/watch?v={VID}", f"https://youtube.com@evil.com/watch?v={VID}",
    "https://www.youtube.com/watch?v=short", f"https://youtu.be/{VID}/extra", f"https://www.youtube.com/watch?v={VID}\nx",
    f"https://www.youtube.com:8443/watch?v={VID}",
])
def test_url_rejected(raw):
    with pytest.raises(TranscribeError):
        transcribe.parse_youtube_url(raw)


def test_availability(settings, monkeypatch):
    monkeypatch.setattr(transcribe, "_resolve", lambda t: t)
    (settings.whisper_cli_path).write_bytes(b"x")
    assert transcribe.availability(settings) == (True, "")
    monkeypatch.setattr(transcribe, "_resolve", lambda t: None if t == "ffmpeg" else t)
    ok, reason = transcribe.availability(settings)
    assert not ok and "ffmpeg" in reason and "docs/transcription.md" in reason
    monkeypatch.setattr(transcribe, "_resolve", lambda t: t)
    assert not transcribe.availability(settings.model_copy(update={"whisper_model_path": None}))[0]
    assert not transcribe.availability(settings.model_copy(update={"whisper_cli_path": settings.data_dir / "nope"}))[0]
    ok, reason = transcribe.availability(settings.model_copy(update={"public_host": "example.com"}))
    assert not ok and "docs/transcription.md" in reason


def test_success(settings, env):
    stages, titles = [], []
    r = run(settings, "auto", stages=stages, titles=titles)
    assert stages == ["checking", "downloading", "converting", "transcribing"] and titles == ["Song"]
    assert (r.title, r.video_id, r.url, r.language, r.model) == ("Song", VID, URL, "en", "ggml-small.bin")
    assert r.original_text == "Hello\nworld"
    assert r.segments == [{"start": 0.0, "end": 1.5, "text": "Hello"}, {"start": 2.0, "end": 3.0, "text": "world"}]
    assert tmp_left(settings) == []


def test_requested_language_kept(settings, env):
    assert run(settings, "nl").language == "nl"
    assert env.calls[-1][env.calls[-1].index("-l") + 1] == "nl"


def test_args_are_lists_with_url_after_double_dash(settings, env):
    run(settings)
    ytdlp = [c for c in env.calls if c[0] == "ytdlp"]
    assert len(ytdlp) == 2
    for c in ytdlp:
        assert isinstance(c, list) and c[c.index("--") + 1] == URL and c[-1] == URL
        assert "--ignore-config" in c and "--no-playlist" in c
    assert "-nostdin" in env.calls[2] and "-np" in env.calls[3]


@pytest.mark.parametrize("update,msg", [
    ({"is_live": True}, "Live"), ({"live_status": "was_live"}, "Live"), ({"live_status": "is_upcoming"}, "Live"),
    ({"duration": 20 * 60 + 1}, "limit"), ({"duration": None}, "duration"),
])
def test_probe_rejections(settings, env, update, msg):
    env.probe.update(update)
    with pytest.raises(TranscribeError, match=msg):
        run(settings)
    assert len(env.calls) == 1 and tmp_left(settings) == []


@pytest.mark.parametrize("tool,stage", [("ytdlp", "check"), ("ffmpeg", "conversion"), ("whisper", "transcription")])
def test_nonzero_exit_is_reported(settings, env, tool, stage):
    env.fail[tool] = (1, b"x" * 1000 + b" boom")
    with pytest.raises(TranscribeError) as e:
        run(settings)
    assert stage in str(e.value) and "boom" in str(e.value) and len(str(e.value)) < 450
    assert tmp_left(settings) == []


def test_download_failure_message(settings, env, monkeypatch):
    orig = env.spawn

    def spawn(args, **kw):
        if args[0] == "ytdlp" and "--dump-single-json" not in args:
            return FakeProc(rc=1, err=b"HTTP Error 403")
        return orig(args, **kw)

    monkeypatch.setattr(transcribe, "spawn", spawn)
    with pytest.raises(TranscribeError, match="download.*403"):
        run(settings)


def test_empty_transcript(settings, env):
    env.segments = [{"offsets": {"from": 0, "to": 1}, "text": "  "}]
    with pytest.raises(TranscribeError, match="No speech was recognised"):
        run(settings)
    assert tmp_left(settings) == []


def test_one_phrase_repeated_is_refused_not_saved(settings, env):
    env.segments = [{"offsets": {"from": i * 30000, "to": i * 30000 + 29980}, "text": " المترجم للقناة"} for i in range(4)]
    with pytest.raises(TranscribeError, match="one phrase, repeated"):
        run(settings)
    assert tmp_left(settings) == []


def test_whisper_runs_without_context_carry_over(settings, env):
    run(settings)
    call = env.calls[-1]
    assert call[call.index("-mc") + 1] == "0"  # the default context makes Whisper loop on music


def test_cancel_mid_process_kills_group(settings, env):
    env.hang = "ffmpeg"
    cancelled = threading.Event()
    t = threading.Timer(0.1, cancelled.set)
    t.start()
    with pytest.raises(Cancelled):
        run(settings, cancelled=cancelled)
    assert env.procs[-1].killed and env.procs[-1].killed[0] == transcribe.signal.SIGTERM
    assert tmp_left(settings) == []


def test_timeout_kills_and_raises(settings, env, monkeypatch):
    env.hang = "ytdlp"
    s = settings.model_copy()
    orig_init = transcribe._Run.__init__

    def init(self, st, ev):
        orig_init(self, st, ev)
        self.deadline = time.monotonic() + 0.1

    monkeypatch.setattr(transcribe._Run, "__init__", init)
    with pytest.raises(TranscribeError, match="too long"):
        run(s)
    assert env.procs[0].killed and tmp_left(s) == []


def test_sweep_tmp(settings):
    (settings.data_dir / "tmp" / "tr-old").mkdir(parents=True)
    transcribe.sweep_tmp(settings)
    assert tmp_left(settings) == []


def wait_state(jobs, job, owner, chat, states, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        j = jobs.get(job.id, owner, chat)
        if j.state in states:
            return j
        time.sleep(0.01)
    raise AssertionError(f"stuck in {j.state}")


def test_jobs_success_save_and_busy(settings, env):
    saved = []
    env.hang = "ytdlp"
    jobs = Jobs(settings, lambda o, c, r: saved.append((o, c, r)) or "tid1")
    job = jobs.submit("alice", "c" * 32, URL, "auto")
    assert job.state == "queued" and len(job.id) == 32
    with pytest.raises(JobBusy):
        jobs.submit("bob", "d" * 32, URL, "auto")
    jobs.cancel(job.id, "alice", "c" * 32)
    assert wait_state(jobs, job, "alice", "c" * 32, {"cancelled"}).state == "cancelled"

    env.hang = None
    job = jobs.submit("alice", "c" * 32, URL, "auto")
    done = wait_state(jobs, job, "alice", "c" * 32, {"done", "failed"})
    assert done.state == "done" and done.transcript_id == "tid1" and done.title == "Song"
    assert saved[0][:2] == ("alice", "c" * 32) and saved[0][2].original_text == "Hello\nworld"
    assert jobs.cancel(job.id, "alice", "c" * 32).state == "done"
    jobs.shutdown()


def test_jobs_active_finds_the_running_job_for_its_owner_only(settings, env):
    env.hang = "ytdlp"
    jobs = Jobs(settings, lambda *a: "x")
    chat = "c" * 32
    assert jobs.active("alice", chat) is None
    job = jobs.submit("alice", chat, URL, "auto")
    assert jobs.active("alice", chat).id == job.id
    assert jobs.active("bob", chat) is None and jobs.active("alice", "d" * 32) is None
    jobs.cancel(job.id, "alice", chat)
    wait_state(jobs, job, "alice", chat, {"cancelled"})
    assert jobs.active("alice", chat) is None
    jobs.shutdown()


def test_jobs_bad_url_raises_immediately(settings, env):
    jobs = Jobs(settings, lambda *a: "x")
    with pytest.raises(TranscribeError):
        jobs.submit("alice", "c" * 32, "https://evil.com/x", "auto")
    assert env.calls == []


def test_jobs_ownership(settings, env):
    env.hang = "ytdlp"
    jobs = Jobs(settings, lambda *a: "x")
    job = jobs.submit("alice", "c" * 32, URL, "auto")
    assert jobs.get(job.id, "mallory", "c" * 32) is None
    assert jobs.get(job.id, "alice", "other") is None
    assert jobs.get("nope", "alice", "c" * 32) is None
    assert jobs.cancel(job.id, "mallory", "c" * 32) is None
    assert jobs.cancel(job.id, "alice", "other") is None
    assert jobs.get(job.id, "alice", "c" * 32).state in {"queued", "checking"}
    jobs.shutdown()
    assert wait_state(jobs, job, "alice", "c" * 32, {"cancelled"}).state == "cancelled"


def test_jobs_failure_states(settings, env):
    env.fail["ytdlp"] = (1, b"nope")
    jobs = Jobs(settings, lambda *a: "x")
    job = jobs.submit("alice", "c" * 32, URL, "auto")
    j = wait_state(jobs, job, "alice", "c" * 32, {"failed"})
    assert "nope" in j.error

    def boom(*a):
        raise RuntimeError("secret internals")

    env.fail.clear()
    jobs = Jobs(settings, boom)
    job = jobs.submit("alice", "c" * 32, URL, "auto")
    j = wait_state(jobs, job, "alice", "c" * 32, {"failed"})
    assert j.error == "Transcription failed"
