import io
import json
import logging
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
