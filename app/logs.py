import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from models import BASE_DIR

log = logging.getLogger("dolphinllm")
log.setLevel(logging.INFO)  # handlers filter: console stays at WARNING, the file takes INFO


class RedWarnings(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = f"{record.levelname}: {super().format(record)}"
        return f"\033[31m{line}\033[0m" if record.levelno >= logging.WARNING and sys.stderr.isatty() and "NO_COLOR" not in os.environ else line


_console = logging.StreamHandler()
_console.setFormatter(RedWarnings("%(message)s"))
_console.setLevel(logging.WARNING)  # pins today's console output so a lower logger level never floods the terminal
log.addHandler(_console)


_SECRET_KEY = re.compile(r"api[_-]?key|authorization|secret|token|password|(^|[_-])key($|[_-])", re.I)
_BODY_KEY = re.compile(r"^(content|messages?|text|body|prompt|reply|completion|story|summary|raw)$", re.I)
_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.I)
_STD_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "taskName"}


def _scrub(value, key: str = ""):
    if _SECRET_KEY.search(key) or _BODY_KEY.match(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(k): _scrub(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v, key) for v in value]
    if isinstance(value, str):
        return _BEARER.sub(r"\1[redacted]", value)
    return value if value is None or isinstance(value, (bool, int, float)) else _BEARER.sub(r"\1[redacted]", str(value))


class Redactor(logging.Filter):
    """Keeps keys and chat bodies out of the log file: metadata only."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _BEARER.sub(r"\1[redacted]", record.getMessage())
        record.args = None
        for name in set(record.__dict__) - _STD_ATTRS:
            setattr(record, name, _scrub(getattr(record, name), name))
        return True


class JsonLines(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {"ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(), "level": record.levelname, "msg": record.getMessage()}
        entry.update({k: v for k, v in record.__dict__.items() if k not in _STD_ATTRS})
        if record.exc_info:
            entry["exc"] = type(record.exc_info[1]).__name__  # the message could echo content
        return json.dumps(entry, default=str)


class LazyFileHandler(logging.FileHandler):
    def _open(self):
        Path(self.baseFilename).parent.mkdir(parents=True, exist_ok=True)
        return super()._open()


def make_file_handler(path: Path) -> logging.Handler:
    handler = LazyFileHandler(path, encoding="utf-8", delay=True)
    handler.setLevel(logging.INFO)
    handler.addFilter(Redactor())
    handler.setFormatter(JsonLines())
    return handler


def _log_path() -> Path | None:
    explicit = os.environ.get("DOLPHINLLM_LOG_FILE")
    if explicit:
        return Path(explicit)
    # Under pytest the file log stays off unless DOLPHINLLM_LOG_FILE opts in, so the suite writes nothing into the repo.
    return None if "pytest" in sys.modules else BASE_DIR / "logs" / "app.jsonl"


if (_path := _log_path()) is not None:
    log.addHandler(make_file_handler(_path))
