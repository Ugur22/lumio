"""Song transcripts: the routes, owner scoping, editing, and their use as context for a question."""

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

import server
from app import auth, runtime, story, transcribe
from conftest import ORIGIN
from models import TranscriptionJob, UserView

A, B = "a" * 32, "b" * 32
JOB = "c" * 32


@pytest.fixture(autouse=True)
def header_identity():
    def who(request: Request):
        return UserView(id=request.headers["x-test-user"], username=request.headers["x-test-user"], is_admin=False)

    server.app.dependency_overrides[auth.current_user] = who
    yield
    server.app.dependency_overrides.pop(auth.current_user, None)


def client_for(user: str) -> TestClient:
    return TestClient(server.app, base_url=ORIGIN, headers={"Origin": ORIGIN, "X-Test-User": user})


@pytest.fixture
def alice():
    client = client_for(A)
    # A non-local user starts with no provider, and sending a message needs one.
    client.post("/api/profiles", json={"name": "P", "base_url": "https://x.example/v1", "model": "m", "key": "sk-alice-1234567890"})
    return client


@pytest.fixture
def bob():
    return client_for(B)


class StubJobs:
    """Stands in for transcribe.Jobs: no thread, no subprocess."""

    def __init__(self):
        self.error: Exception | None = None
        self.submitted = []
        self.running = None  # the job active() reports

    def job(self, chat_id, state="queued", transcript_id=None):
        return TranscriptionJob(id=JOB, chat_id=chat_id, url="https://youtu.be/x", state=state, title="", error="", transcript_id=transcript_id)

    def active(self, owner, chat_id):
        return self.running

    def submit(self, owner, chat_id, url, language):
        if self.error:
            raise self.error
        self.submitted.append((owner, chat_id, url, language))
        # What the real worker does when it finishes: hand the result to the save callback.
        result = transcribe.Result(
            title="Song", video_id="vid", url=url, language="en", model="m.bin",
            original_text="la la la", segments=[{"start": 0.0, "end": 1.5, "text": "la la la"}],
        )  # fmt: skip
        return self.job(chat_id, "done", runtime._save_transcript(owner, chat_id, result))

    def get(self, job_id, owner, chat_id):
        return self.job(chat_id) if job_id == JOB and owner == A else None

    def cancel(self, job_id, owner, chat_id):
        return self.job(chat_id, "cancelled") if job_id == JOB and owner == A else None


@pytest.fixture
def jobs(monkeypatch):
    stub = StubJobs()
    monkeypatch.setattr(runtime, "jobs", stub)
    monkeypatch.setattr(transcribe, "availability", lambda settings: (True, ""))
    return stub


@pytest.fixture
def chat_id(alice):
    return alice.post("/api/chats").json()["id"]


@pytest.fixture
def transcript_id(alice, chat_id, jobs):
    return alice.post(f"/api/chats/{chat_id}/transcriptions", json={"url": "https://youtu.be/x"}).json()["transcript_id"]


def test_status_reports_availability(alice, monkeypatch):
    monkeypatch.setattr(runtime.settings, "whisper_model_path", None)  # the developer's local settings may set it
    monkeypatch.setattr(transcribe, "availability", lambda settings: (False, "install whisper"))
    off = alice.get("/api/transcription").json()
    assert off["available"] is False and off["reason"] == "install whisper" and off["model"] == ""
    monkeypatch.setattr(transcribe, "availability", lambda settings: (True, ""))
    assert alice.get("/api/transcription").json()["available"] is True


def test_finished_job_saves_a_listed_transcript(alice, chat_id, transcript_id):
    listed = alice.get(f"/api/chats/{chat_id}/transcripts").json()
    assert [t["id"] for t in listed] == [transcript_id]
    assert listed[0]["title"] == "Song" and listed[0]["edited"] is False
    full = alice.get(f"/api/chats/{chat_id}/transcripts/{transcript_id}").json()
    assert full["original_text"] == "la la la" and full["segments"][0]["end"] == 1.5


def test_job_start_errors(alice, chat_id, jobs, monkeypatch):
    url = {"url": "https://youtu.be/x"}
    jobs.error = transcribe.TranscribeError("Enter a link to a single YouTube video")
    assert alice.post(f"/api/chats/{chat_id}/transcriptions", json={"url": "nope"}).status_code == 422
    jobs.error = transcribe.JobBusy()
    assert alice.post(f"/api/chats/{chat_id}/transcriptions", json=url).status_code == 409
    monkeypatch.setattr(transcribe, "availability", lambda settings: (False, "not set up"))
    res = alice.post(f"/api/chats/{chat_id}/transcriptions", json=url)
    assert res.status_code == 503 and res.json()["detail"] == "not set up"


def test_job_poll_and_cancel(alice, chat_id, jobs):
    assert alice.get(f"/api/chats/{chat_id}/transcriptions/{JOB}").json()["state"] == "queued"
    assert alice.delete(f"/api/chats/{chat_id}/transcriptions/{JOB}").json()["state"] == "cancelled"
    assert alice.get(f"/api/chats/{chat_id}/transcriptions/{'d' * 32}").status_code == 404


def test_active_job_is_reported_so_a_closed_dialog_can_find_it(alice, chat_id, jobs):
    assert alice.get(f"/api/chats/{chat_id}/transcriptions").json() is None
    jobs.running = jobs.job(chat_id, state="downloading")
    assert alice.get(f"/api/chats/{chat_id}/transcriptions").json()["state"] == "downloading"


def test_an_empty_edit_is_refused(alice, chat_id, transcript_id):
    res = alice.put(f"/api/chats/{chat_id}/transcripts/{transcript_id}", json={"edited_text": ""})
    assert res.status_code == 422


def test_edit_keeps_the_original_and_null_resets(alice, chat_id, transcript_id):
    path = f"/api/chats/{chat_id}/transcripts/{transcript_id}"
    edited = alice.put(path, json={"edited_text": "la la la!"}).json()
    assert edited["original_text"] == "la la la" and edited["edited_text"] == "la la la!" and edited["edited"] is True
    reset = alice.put(path, json={"edited_text": None}).json()
    assert reset["edited_text"] is None and reset["edited"] is False and reset["original_text"] == "la la la"


def test_delete_transcript(alice, chat_id, transcript_id):
    path = f"/api/chats/{chat_id}/transcripts/{transcript_id}"
    assert alice.delete(path).status_code == 204
    assert alice.get(path).status_code == 404


def test_deleting_the_chat_deletes_its_transcripts(alice, chat_id, transcript_id):
    alice.delete(f"/api/chats/{chat_id}")
    with runtime.db._read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 0


def test_another_user_gets_404_everywhere(alice, bob, chat_id, transcript_id, jobs, calls):
    t = f"/api/chats/{chat_id}/transcripts"
    seen = [
        bob.get(t),
        bob.get(f"{t}/{transcript_id}"),
        bob.put(f"{t}/{transcript_id}", json={"edited_text": "mine"}),
        bob.delete(f"{t}/{transcript_id}"),
        bob.post(f"/api/chats/{chat_id}/transcriptions", json={"url": "https://youtu.be/x"}),
        bob.get(f"/api/chats/{chat_id}/transcriptions/{JOB}"),
        bob.delete(f"/api/chats/{chat_id}/transcriptions/{JOB}"),
        bob.post(f"/api/chats/{chat_id}/messages", json={"content": "q", "transcript_id": transcript_id}),
    ]
    assert [r.status_code for r in seen] == [404] * len(seen)
    assert alice.get(f"{t}/{transcript_id}").json()["edited_text"] is None


def test_a_transcript_of_another_chat_is_not_found(alice, transcript_id, calls):
    other = alice.post("/api/chats").json()["id"]
    res = alice.post(f"/api/chats/{other}/messages", json={"content": "q", "transcript_id": transcript_id})
    assert res.status_code == 404 and res.json()["detail"] == "Transcript not found"
    assert alice.get(f"/api/chats/{other}/transcripts/{transcript_id}").status_code == 404


def sent_text(messages):
    content = messages[-1]["content"]
    return content if isinstance(content, str) else "".join(p.get("text", "") for p in content)


def test_question_with_transcript_prompts_with_it_but_stores_only_the_question(alice, chat_id, transcript_id, calls):
    alice.put(f"/api/chats/{chat_id}/transcripts/{transcript_id}", json={"edited_text": "fixed lyrics"})
    res = alice.post(f"/api/chats/{chat_id}/messages", json={"content": "what is it about?", "transcript_id": transcript_id})
    assert res.status_code == 200, res.text
    sent = sent_text(calls[0])
    assert story.TRANSCRIPT_NOTE in sent and "fixed lyrics" in sent and "la la la" not in sent and sent.endswith("what is it about?")
    stored = alice.get(f"/api/chats/{chat_id}").json()["messages"]
    assert stored[0]["content"] == "what is it about?"


def test_question_without_transcript_is_unchanged(alice, chat_id, calls):
    alice.post(f"/api/chats/{chat_id}/messages", json={"content": "hello"})
    assert sent_text(calls[0]) == "hello"
