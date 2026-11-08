import io
import json
import logging

import pytest
from app import logs



def _emit(tmp_path, **extra):
    path = tmp_path / "nested" / "app.jsonl"
    handler = logs.make_file_handler(path)
    logger = logging.getLogger("dolphinllm.test")
    logger.addHandler(handler)
    try:
        logger.warning("call Authorization: Bearer abc.def-123 done", extra=extra)
    finally:
        logger.removeHandler(handler)
        handler.close()
    return path


def test_lines_are_json_with_extras_and_dir_created_lazily(tmp_path):
    path = _emit(tmp_path, status=502, duration_ms=12.5, model="m")
    entry = json.loads(path.read_text().splitlines()[0])
    assert {"ts", "level", "msg"} <= entry.keys()
    assert entry["level"] == "WARNING"
    assert (entry["status"], entry["duration_ms"], entry["model"]) == (502, 12.5, "m")


def test_keys_and_bearer_tokens_are_redacted(tmp_path):
    path = _emit(tmp_path, api_key="sk-supersecret", headers={"Authorization": "Bearer zzz999"}, note="Bearer qqq111")
    text = path.read_text()
    for leaked in ("sk-supersecret", "abc.def-123", "zzz999", "qqq111"):
        assert leaked not in text
    assert json.loads(text)["api_key"] == "[redacted]"


def test_chat_bodies_are_not_written(tmp_path):
    path = _emit(tmp_path, content="my private question", messages=[{"role": "user", "content": "my private question"}], count=1)
    text = path.read_text()
    assert "my private question" not in text
    assert json.loads(text)["count"] == 1


def test_file_handler_is_off_under_pytest(monkeypatch):
    monkeypatch.delenv("DOLPHINLLM_LOG_FILE", raising=False)
    assert logs._log_path() is None
    monkeypatch.setenv("DOLPHINLLM_LOG_FILE", "/x/y.jsonl")
    assert str(logs._log_path()) == "/x/y.jsonl"


def test_info_reaches_file_but_not_console(tmp_path, monkeypatch):
    console = io.StringIO()
    monkeypatch.setattr(logs._console, "stream", console)
    assert logs.log.level == logging.INFO
    handler = logs.make_file_handler(tmp_path / "app.jsonl")
    logs.log.addHandler(handler)
    try:
        logs.log.info("just info")
        logs.log.warning("a warning")
    finally:
        logs.log.removeHandler(handler)
        handler.close()
    levels = [json.loads(line)["level"] for line in (tmp_path / "app.jsonl").read_text().splitlines()]
    assert levels == ["INFO", "WARNING"]
    assert "just info" not in console.getvalue() and "a warning" in console.getvalue()


def _access_record(target, status=200):
    # The shape uvicorn emits: a format string and a tuple of args, the target being one of them.
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', ("1.2.3.4:5", "GET", target, "1.1", status), None)


def _emit_access(record) -> str:
    from app import logs

    assert any(isinstance(f, logs.InviteRedactor) for f in logging.getLogger("uvicorn.access").filters)
    logging.getLogger("uvicorn.access").filter(record)
    return record.getMessage()


@pytest.mark.parametrize(
    "target,expected",
    [
        ("/api/auth/oauth/google/start?invite=SECRET-code_1", "/api/auth/oauth/google/start?invite=REDACTED"),
        ("/api/auth/oauth/google/start?client=app&invite=SECRET&challenge=abc", "/api/auth/oauth/google/start?client=app&invite=REDACTED&challenge=abc"),
        ("/api/auth/oauth/github/start?invite=SE%2FCR%3DET%20x&redirect=lumio%3A%2F%2Fauth", "/api/auth/oauth/github/start?invite=REDACTED&redirect=lumio%3A%2F%2Fauth"),
        ("/api/chats?limit=5", "/api/chats?limit=5"),
    ],
)
def test_the_access_log_never_carries_an_invite(target, expected):
    line = _emit_access(_access_record(target))

    assert "SECRET" not in line and "SE%2F" not in line
    assert line == f'1.2.3.4:5 - "GET {expected} HTTP/1.1" 200'


def test_the_access_log_redaction_also_covers_a_preformatted_message_and_a_dict_of_args():
    done = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "GET /x?a=1&invite=SECRET HTTP/1.1", None, None)
    named = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "%(t)s", ({"t": "/x?invite=SECRET"},), None)

    assert _emit_access(done) == "GET /x?a=1&invite=REDACTED HTTP/1.1"
    assert _emit_access(named) == "/x?invite=REDACTED"


def test_the_redaction_survives_uvicorns_logging_setup():
    import logging.config

    from uvicorn.config import LOGGING_CONFIG

    logging.config.dictConfig(LOGGING_CONFIG)

    assert "SECRET" not in _emit_access(_access_record("/start?invite=SECRET"))
