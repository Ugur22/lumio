"""Reply jobs: a reply runs as a task of its own, so a dropped connection (a phone going to the background) does not stop it.

The HTTP request only reads the job's event buffer. Every event gets a running integer id (SSE `id:`), the buffer is
kept until the job ends and for REPLAY_TTL after, and any number of readers can replay from an id and then follow live.
Jobs live in this process only: a restart drops them.
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator

from app.logs import log
from app.streaming import StopReport, sse

REPLAY_TTL = 600.0  # seconds a finished job's events stay available for a late resume
MAX_REASONING_BYTES = 256 * 1024  # reasoning is ephemeral UI text: past this it is no longer sent or kept, so the buffer stays small
STOP_WAIT = 30.0  # seconds a cancelled job waits for its save to report before closing its readers
FAILED = "The reply failed unexpectedly. Try again."


class Job:
    def __init__(self, chat_id: str, owner: str, report: StopReport | None = None):
        self.id = uuid.uuid4().hex  # lets a resuming client tell this reply from an earlier one in the same chat
        self.report = report
        self.chat_id = chat_id
        self.owner = owner
        self.frames: list[str] = []  # frames[i] carries `id: i`
        self.finished_at: float | None = None
        self.task: asyncio.Task | None = None
        self._started = False
        self._changed = asyncio.Event()
        self._reasoning_bytes = 0

    @property
    def running(self) -> bool:
        return self.finished_at is None

    def expired(self) -> bool:
        return self.finished_at is not None and time.monotonic() - self.finished_at > REPLAY_TTL

    def _notify(self) -> None:
        # Swapped rather than cleared, so a reader that is between two awaits can never miss a wake-up.
        old, self._changed = self._changed, asyncio.Event()
        old.set()

    def emit(self, frame: str) -> None:
        if frame.startswith("event: reasoning\n"):
            if self._reasoning_bytes >= MAX_REASONING_BYTES:
                return
            self._reasoning_bytes += len(frame)
        self.frames.append(f"id: {len(self.frames)}\n{frame}")
        self._notify()

    async def _run(self, source: AsyncIterator[str]) -> None:
        self._started = True
        try:
            async for frame in source:
                self.emit(frame)
        except asyncio.CancelledError:
            # cancel(): the generator saved the partial reply (or its save is still running); readers get its outcome as the last frame.
            if self.report:
                try:
                    await asyncio.wait_for(self.report.event.wait(), STOP_WAIT)
                except asyncio.TimeoutError:
                    pass
            ended = self.frames and self.frames[-1].split("\n", 2)[1] in ("event: done", "event: error")
            if not ended:
                self.emit((self.report and self.report.frame) or sse("error", {"detail": FAILED}))
            raise
        except Exception:
            log.exception("Reply job for chat %s failed", self.chat_id)
            self.emit(sse("error", {"detail": FAILED}))
        finally:
            self.finished_at = time.monotonic()
            self._notify()

    def cancel(self) -> None:
        """Stops the reply the way a Stop always has: the generator saves the text so far. No-op once it has ended."""
        if self.task is None or self.task.done():
            return
        if self._started:
            self.task.cancel()
        else:
            # A task cancelled before its first step never enters the generator, which would leave the lease held.
            asyncio.get_running_loop().call_soon(self.task.cancel)

    async def follow(self, after: int = -1) -> AsyncIterator[str]:
        """The frames with an id above `after`, then new ones as they arrive, until the job ends."""
        i = max(after + 1, 0)
        while True:
            while i < len(self.frames):
                yield self.frames[i]
                i += 1
            if not self.running:
                return
            await self._changed.wait()


_jobs: dict[str, Job] = {}  # by chat id: the lease allows one running job per chat


def _purge() -> None:
    for chat_id in [c for c, j in _jobs.items() if j.expired()]:
        del _jobs[chat_id]


def start(chat_id: str, owner: str, source: AsyncIterator[str], report: StopReport | None = None) -> Job:
    """Runs `source` (the frames of one reply) as a job. Must be called inside the event loop."""
    _purge()
    job = Job(chat_id, owner, report)
    job.task = asyncio.get_running_loop().create_task(job._run(source))
    _jobs[chat_id] = job  # the registry also keeps the task alive; the loop only holds weak references
    return job


def find(chat_id: str, owner: str) -> Job | None:
    """The chat's running or recently finished job, if it is this user's."""
    _purge()
    job = _jobs.get(chat_id)
    return job if job and job.owner == owner else None
