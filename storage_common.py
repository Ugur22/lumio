"""Helpers shared by the storage modules."""

from datetime import datetime, timezone


def _ts(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)  # the app only ever wrote UTC; never guess the machine's zone
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
