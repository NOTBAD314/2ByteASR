"""Failure reasons and logged commands stay readable; only their paths and secrets are redacted (2026-10-21)."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from twobyteasr.diagnostics.event_log import Sanitizer
from twobyteasr.diagnostics.runtime_trace import GLOBAL_STUDIO_TRACE
from twobyteasr.system.processes import popen_hidden_subprocess


def _last(event, before):
    return [item for item in GLOBAL_STUDIO_TRACE.recent()[before:] if item.get("event") == event][-1]


def test_failure_reason_keeps_plain_text():
    before = len(GLOBAL_STUDIO_TRACE.recent())
    GLOBAL_STUDIO_TRACE.emit("STUDIO_OPEN_FAILED", {"stage": "读取工程", "error": "工程文件不是有效的 JSON"})
    assert _last("STUDIO_OPEN_FAILED", before)["error"] == "工程文件不是有效的 JSON"


def test_failure_reason_redacts_paths_and_user_names():
    before = len(GLOBAL_STUDIO_TRACE.recent())
    reason = r"无法读取工程文件：C:\Users\someone\私人剪辑\第8话.2byteproj"
    GLOBAL_STUDIO_TRACE.emit("STUDIO_OPEN_FAILED", {"stage": "读取工程", "error": reason})
    error = _last("STUDIO_OPEN_FAILED", before)["error"]
    assert error.startswith("无法读取工程文件：path-") and error.endswith(".2byteproj")
    assert "someone" not in error and "私人剪辑" not in error and "C:\\" not in error
    # The unified log carries the same text as failure_reason (error stays omitted there).
    cleaned = Sanitizer().clean({"failure_reason": error, "error": reason})
    assert cleaned["failure_reason"] == error and cleaned["error"] == "<omitted>"


def test_other_trace_fields_are_still_omitted():
    before = len(GLOBAL_STUDIO_TRACE.recent())
    GLOBAL_STUDIO_TRACE.emit("STUDIO_STATE", {"error": "boom", "message": "字幕原文秘密"})
    record = _last("STUDIO_STATE", before)
    assert record["error"] == "<omitted>" and record["message"] == "<omitted>"


def test_logged_command_redacts_paths_and_user_names(tmp_path, monkeypatch):
    log_path = tmp_path / "children.jsonl"
    monkeypatch.setenv("TWOBYTEASR_CHILD_PROCESS_LOG", str(log_path))
    media = r"C:\Users\someone\私人剪辑\clip.mp4"
    process = popen_hidden_subprocess(
        [sys.executable, "-c", "print('ok')", "TOP_SECRET_PROMPT", media],
        purpose="path redaction fixture",
        log_command=[sys.executable, "-c", "print('ok')", "<redacted-prompt>", media],
        stdout=-1,
        stderr=-1,
        text=True,
    )
    process.communicate(timeout=5.0)
    payload = log_path.read_text(encoding="utf-8")
    assert "TOP_SECRET_PROMPT" not in payload and "<redacted-prompt>" in payload
    assert "someone" not in payload and "私人剪辑" not in payload and "clip.mp4" not in payload
    assert ".mp4" in payload  # the alias keeps the extension
