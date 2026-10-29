"""Real provider boundary, offline transport; no account key/network required."""
import copy
import json
from types import SimpleNamespace

import pytest

from twobyteasr.providers.ai_providers import OpenAICompatibleProvider
from twobyteasr.providers.llm_adapter import LLMRequestError, _gemini_fast_reasoning
from twobyteasr.providers.provider_service import ProviderService
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.subtitle_rules import subtitle_translation as st
from twobyteasr.subtitle_rules.translation_diagnostics import TranslationLog, provider_evidence

BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
SETTINGS = {"models": {"polish_provider": "gemini", "polish_base_url": BASE,
                       "polish_model": "gemini-3.8-flash", "polish_api_key": "fixture"}}


def project(count=3):
    p = SubtitleProject(media=StudioMedia(path="synthetic.mp4", duration_ms=200000),
        cues=[StudioCue(f"c{i}", i * 1000, i * 1000 + 900, "We need to open the door.") for i in range(count)])
    p.generation_metadata["language"] = {"code": "en"}
    return p


class Response:
    status_code, headers, text = 200, {}, ""
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): pass
    def json(self): return self.payload


def answer(messages):
    request = json.loads(messages[-1]["content"])
    return {"items": [{"id": row["id"], "translation": "我们得把门打开。"}
                       for row in request["lines"] if row["translate"]]}


def test_real_broker_translates_91_and_logs_request_answer_and_usage(monkeypatch, tmp_path):
    requests = []
    def post(url, **kwargs):
        body = kwargs["json"]
        requests.append(body)
        assert body["reasoning_effort"] == "low"
        return Response({"choices": [{"message": {"content": json.dumps(answer(body["messages"]))}, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}})
    monkeypatch.setattr("twobyteasr.providers.network_policy.post", post)
    p, log, service = project(91), TranslationLog(tmp_path), ProviderService()
    original = copy.deepcopy(p.cues)
    try:
        result = st.translate(p, None, service.client_for_stage(SETTINGS, "polish"), target="zh-Hans", event=log)
        assert len(result.translations) == 91 and not result.failed
        st.apply_translation_result(p, result)
        assert p.cues == original
        assert len(requests) == 3
        rows = [json.loads(line) for line in log.path.read_text(encoding="utf8").splitlines()]
        assert rows[0]["event"] == "started" and rows[-1]["summary"]["succeeded"] == 91
        response = next(r for r in rows if r["event"] == "response")
        assert response["usage"]["total_tokens"] == 300
        assert next(r for r in rows if r["event"] == "request")["messages_included"] is False
    finally:
        service.shutdown()


@pytest.mark.parametrize("category", ["structured_output_truncated", "structured_output_truncated_before_answer"])
def test_truncation_retry_expands_reserve_and_keeps_same_model(category):
    attempts = []
    def sender(messages, **kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise LLMRequestError("output exhausted", category=category)
        return json.dumps(answer(messages))
    provider = OpenAICompatibleProvider(dict(provider="gemini", model="gemini-3.8-flash",
        api_key="fixture", base_url=BASE, url=BASE + "/chat/completions"), sender=sender)
    events = []
    result = st.translate(project(), None, provider, target="zh-Hans", event=events.append)
    assert len(result.translations) == 3 and not result.failed
    assert all(row["max_tokens"] >= max(4096, attempts[0]["max_tokens"] * 2) for row in attempts[1:])
    assert {row["model"] for row in attempts} == {"gemini-3.8-flash"}
    assert any(row["event"] == "retry" for row in events)


def test_truncation_does_not_poison_following_batches():
    service = ProviderService()
    calls = []
    def sender(messages, **kwargs):
        calls.append(1)
        if len(calls) <= 4:
            raise LLMRequestError("output exhausted", category="structured_output_truncated")
        return json.dumps(answer(messages))
    try:
        client = service.client_for_stage(SETTINGS, "polish", sender=sender)
        result = st.translate(project(3), None, client, target="zh-Hans", max_items=1)
        assert len(calls) == 5 and len(result.failed) == 2 and len(result.translations) == 1
    finally:
        service.shutdown()


@pytest.mark.parametrize("base,model,thinking,expected", [
    (BASE, "gemini-3.8-flash", False, {"reasoning_effort": "low"}),
    (BASE, "gemini-3-pro-preview", False, {"reasoning_effort": "low"}),
    (BASE, "gemini-2.5-flash", False, {}),
    (BASE, "gemini-4-future", False, {}),
    (BASE, "gemini-3.8-flash", None, {}),
    (BASE, "gemini-3.8-flash", True, {}),
    ("https://relay.example/v1", "gemini-3.8-flash", False, {}),
])
def test_gemini_reasoning_scope(base, model, thinking, expected):
    assert _gemini_fast_reasoning("gemini", base, model, thinking) == expected


def test_log_redacts_secrets_and_never_collects_thoughts(tmp_path):
    log = TranslationLog(tmp_path)
    secret = "AIza" + "x" * 30
    log({"event": "error", "error": "Bearer abc-secret " + secret, "api_key": secret})
    provider = SimpleNamespace(last_invocation_trace={"response_boundary": {
        "reasoning_content": "private thought", "raw_response_preview": "private thought",
        "final_content_preview": "final answer", "finish_reason": "stop"}})
    log(provider_evidence(provider))
    text = log.path.read_text(encoding="utf8")
    assert secret not in text and "abc-secret" not in text and "private thought" not in text
    assert "final answer" not in text
    assert "final_content_preview_characters" in text


def test_logging_failure_never_discards_translations(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("file")
    log = TranslationLog(blocked)
    provider = SimpleNamespace(structured_complete=lambda messages, schema, **kw: answer(messages))
    result = st.translate(project(), None, provider, target="zh-Hans", event=log)
    assert len(result.translations) == 3 and log.error


def test_dialog_shows_redacted_reason_and_copies_log(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QUndoStack
    from twobyteasr.caption_design.studio_ai import GLOBAL_PROVIDER_REGISTRY
    from twobyteasr.studio.studio_translation_dialog import SubtitleTranslationDialog
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(GLOBAL_PROVIDER_REGISTRY, "settings", lambda: SETTINGS)
    p = project()
    page = SimpleNamespace(project=p, selected_cue_ids=lambda: ["c0"], undo_stack=QUndoStack())
    dialog = SubtitleTranslationDialog(page)
    try:
        def sender(*args, **kwargs):
            raise LLMRequestError("HTTP 400 invalid model Bearer abc-secret", category="configuration_error")
        provider = OpenAICompatibleProvider(dict(provider="gemini", model="gemini-3.8-flash",
            api_key="fixture", base_url=BASE, url=BASE + "/chat/completions"), sender=sender)
        log = dialog._log = TranslationLog(tmp_path)
        def event(row): log(row); dialog._on_event(row)
        result = st.translate(p, None, provider, target="zh-Hans", event=event)
        dialog._on_finished(result)
        assert "HTTP 400" in dialog.status.text()
        assert "abc-secret" not in dialog.request_log.toPlainText()
        dialog._copy_log()
        assert '"messages_included": false' in app.clipboard().text() and "abc-secret" not in app.clipboard().text()
    finally:
        dialog.deleteLater()
