"""Free-trial quotas: a per-user call allowance and a per-pool daily cap, both taken in one transaction."""

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage import Store

log = logging.getLogger("dolphinllm")

class TrialExhausted(Exception):
    """No trial, or all of its calls are used."""


class TrialFull(Exception):
    """One pool reached today's call cap."""

    def __init__(self, retry_after: int, pool: str = "open", day: str = "", cap: int = 0):
        super().__init__(retry_after)
        self.retry_after = retry_after
        self.pool = pool
        self.day = day
        self.cap = cap


@dataclass(frozen=True)
class Trial:
    limit: int
    used: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit


class TrialCall:
    """One reserved trial call. refund() gives it back at most once, however many paths ask."""

    def __init__(self, store: "Store", user_id: str, day: str, remaining: int, pool: str = "open"):
        self.user_id = user_id
        self.day = day
        self.pool = pool
        self.remaining = remaining
        self.refunded = False
        self._store = store
        self._lock = threading.Lock()

    def refund(self) -> None:
        try:
            self._store.refund_trial_call(self)
        except sqlite3.Error:
            log.warning("Could not refund a trial call for user %s", self.user_id)


class TrialsMixin:
    """Store methods for trials. Relies on the Store's _tx and _read."""

    def get_trial(self, user_id: str) -> Trial | None:
        with self._read() as conn:
            row = conn.execute("SELECT call_limit, used FROM trials WHERE user_id=?", (user_id,)).fetchone()
        return None if row is None else Trial(row["call_limit"], row["used"])

    def reserve_trial_call(self, user_id: str, daily_cap: int | dict[str, int], now: datetime | None = None) -> TrialCall:
        """Takes one call from the user's trial and from today's cap of the user's own pool in one transaction, so parallel
        sends cannot overshoot either. `daily_cap` is the cap per pool, or one number for whichever pool the user is in.
        Raises TrialExhausted or TrialFull and then takes nothing."""
        now = now or datetime.now(timezone.utc)
        day = now.astimezone(timezone.utc).date().isoformat()
        with self._tx() as conn:
            took = conn.execute("UPDATE trials SET used=used+1 WHERE user_id=? AND used<call_limit", (user_id,))
            if took.rowcount == 0:
                raise TrialExhausted(user_id)
            row = conn.execute("SELECT pool FROM trials WHERE user_id=?", (user_id,)).fetchone()
            pool = row["pool"]
            cap = daily_cap[pool] if isinstance(daily_cap, dict) else daily_cap
            conn.execute("INSERT OR IGNORE INTO trial_usage (day, pool, calls) VALUES (?,?,0)", (day, pool))
            if conn.execute("UPDATE trial_usage SET calls=calls+1 WHERE day=? AND pool=? AND calls<?", (day, pool, cap)).rowcount == 0:
                midnight = datetime.combine(now.astimezone(timezone.utc).date() + timedelta(days=1), datetime.min.time(), timezone.utc)
                raise TrialFull(max(1, int((midnight - now).total_seconds())), pool, day, cap)
            conn.execute("DELETE FROM trial_usage WHERE day<?", (day,))
            row = conn.execute("SELECT call_limit - used AS left FROM trials WHERE user_id=?", (user_id,)).fetchone()
        return TrialCall(self, user_id, day, row["left"], pool)

    def refund_trial_call(self, call: TrialCall) -> None:
        with call._lock:
            if call.refunded:
                return
            with self._tx() as conn:
                conn.execute("UPDATE trials SET used=used-1 WHERE user_id=? AND used>0", (call.user_id,))
                conn.execute("UPDATE trial_usage SET calls=calls-1 WHERE day=? AND pool=? AND calls>0", (call.day, call.pool))
            call.refunded = True
            call.remaining += 1
