"""排查原因 window: local findings, AI streaming, stop, failures, actions (2026-10-23)."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QTextEdit, QWidget

from twobyteasr.app import run_diagnosis_dialog as dialog_module
from twobyteasr.app.run_diagnosis_dialog import (AiAnalysisPanel, RunDiagnosisDialog, TASK_ACTIONS,
                                                 diagnosis_strings, run_diagnosis_action)
from twobyteasr.recognition.diagnosis_catalog import ACTION_LABELS
from twobyteasr.recognition.run_diagnosis import DiagnosisInput, diagnose_run
from twobyteasr.recognition.service import MediaResult, QueueResult

APP = QApplication.instance() or QApplication([])

FAILED_REPORT = {
    "status": "failed",
    "settings": {"models": {"primary_asr_backend": "sensevoice", "firered_asr_backend": "off"},
                 "switches": {"enable_ai_polish": False, "use_ai_grouping": False}},
    "stages": [{"label": "锁定最终字幕时间轴", "status": "failed", "error": "字幕保真检查未通过：S00 1167.880s；原文和阶段记录已保留"}],
    "events": [{"event": "final_content_conservation_recovery", "speaker": "S00", "start": 1167.88, "end": 1191.56,
                "expected_numbers": [], "actual_numbers": ["2"]},
               {"event": "TASK_LANGUAGE", "language": "ja", "requested": "ja", "decided_by": "manual",
                "disagrees_with_transcript": "zh", "kana": 0, "han": 971}],
    "review_items": [],
    "result": {"elapsed_seconds": 21.7, "error": "字幕保真检查未通过：S00 1167.880s；原文和阶段记录已保留"},
}
READY = (True, "DeepSeek · deepseek-chat", "ready")


def wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def make_dialog(monkeypatch, *, ready=READY, available=None):
    monkeypatch.setattr(AiAnalysisPanel, "_readiness", staticmethod(lambda settings: ready))
    diagnosis = diagnose_run(DiagnosisInput(report=FAILED_REPORT, ai_ready=ready[0]))
    dialog = RunDiagnosisDialog(diagnosis, task_name="录播.mp4", settings={"models": {}}, app_version="0.8.2",
                                available_actions=available)
    dialog.show()
    APP.processEvents()
    return dialog


class FakeProvider:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.messages = None

    def complete(self, messages, **kwargs):
        self.messages = messages
        self.kwargs = kwargs
        return self.behaviour(kwargs)


def install_provider(monkeypatch, behaviour):
    provider = FakeProvider(behaviour)
    import twobyteasr.providers.ai_providers as ai_providers
    monkeypatch.setattr(ai_providers, "provider_for_stage", lambda settings, stage, **kwargs: provider)
    return provider


def test_local_findings_and_no_key_offer(monkeypatch):
    dialog = make_dialog(monkeypatch, ready=(False, "", "no_key"))
    try:
        assert [card.finding.rule_id for card in dialog.cards][:2] == ["fidelity_numbers", "language_mismatch"]
        assert "19:27" in dialog.cards[0].specific_label.text()
        panel = dialog.ai_panel
        assert panel.run_button is None and panel.setup_button.isVisible()
        panel.setup_button.click()
        assert dialog.chosen_action == "ai_settings"
        assert wait_until(lambda: not dialog.isVisible())  # the dialog's exit motion ends it
    finally:
        dialog.deleteLater()


def test_ai_answer_streams_in_and_goes_into_the_copied_report(monkeypatch):
    def behaviour(kwargs):
        stream = kwargs["on_stream_event"]
        stream("request_identity", json.dumps({"attempt": 1}))
        for part in ("**结论**：", "数字被切开。", "\n\n**怎么做**：打开字幕时间轴。"):
            stream("delta", part)
            time.sleep(0.02)
        return "**结论**：数字被切开。\n\n**怎么做**：打开字幕时间轴。"
    provider = install_provider(monkeypatch, behaviour)
    dialog = make_dialog(monkeypatch)
    try:
        panel = dialog.ai_panel
        assert "DeepSeek" in panel.intro.text()
        panel.run_button.click()
        assert panel.stop_button.isVisible()
        assert wait_until(lambda: not panel.running)
        assert "打开字幕时间轴" in panel.output.toPlainText()
        assert panel.answer.startswith("**结论**")
        assert provider.kwargs["stage"] == "recognition_diagnosis" and provider.kwargs["operation_kind"] == "general"
        system, user = provider.messages
        assert "[fidelity_numbers]" in system["content"] and "```json" in user["content"]
        assert "fidelity_numbers" in user["content"]  # the local findings go along
        text = dialog.report_text()
        assert "AI 分析" in text and "打开字幕时间轴" in text and "fidelity_numbers" in text
        dialog.copy_button.click()
        assert "fidelity_numbers" in QApplication.clipboard().text()
    finally:
        dialog.deleteLater()


def test_retry_attempt_clears_the_partial_answer(monkeypatch):
    def behaviour(kwargs):
        stream = kwargs["on_stream_event"]
        stream("request_identity", json.dumps({"attempt": 1}))
        stream("delta", "半截")
        stream("request_identity", json.dumps({"attempt": 2}))
        stream("delta", "完整回答")
        return ""
    install_provider(monkeypatch, behaviour)
    dialog = make_dialog(monkeypatch)
    try:
        dialog.ai_panel.start()
        assert wait_until(lambda: not dialog.ai_panel.running)
        assert dialog.ai_panel.answer == "完整回答"
    finally:
        dialog.deleteLater()


def test_stop_cancels_and_a_late_answer_is_dropped(monkeypatch):
    release = threading.Event()

    def behaviour(kwargs):
        while not kwargs["cancel_check"]():
            time.sleep(0.01)
        release.wait(2)
        kwargs["on_stream_event"]("delta", "迟到的内容")
        return "迟到的内容"
    install_provider(monkeypatch, behaviour)
    dialog = make_dialog(monkeypatch)
    try:
        panel = dialog.ai_panel
        panel.start()
        assert panel.running
        panel.stop_button.click()
        assert not panel.running and panel.run_button.isEnabled()
        assert panel.status.text() == "已停止。"
        release.set()
        assert wait_until(lambda: not dialog_module._LIVE_WORKERS)
        APP.processEvents()
        assert "迟到" not in panel.output.toPlainText()
    finally:
        dialog.deleteLater()


def test_closing_mid_request_leaves_no_running_thread(monkeypatch):
    def behaviour(kwargs):
        while not kwargs["cancel_check"]():
            time.sleep(0.01)
        from twobyteasr.providers.ai_providers import AIProviderError
        raise AIProviderError("cancelled", category="cancelled")
    install_provider(monkeypatch, behaviour)
    dialog = make_dialog(monkeypatch)
    dialog.ai_panel.start()
    dialog.reject()
    dialog.deleteLater()
    APP.processEvents()
    assert wait_until(lambda: not dialog_module._LIVE_WORKERS)


@pytest.mark.parametrize("category, expected", [
    ("quota_exhausted", "余额"), ("auth_error", "API Key 不对"), ("timeout", "太久没有回应"), ("", "boom"),
])
def test_ai_failures_say_what_to_do(monkeypatch, category, expected):
    from twobyteasr.providers.ai_providers import AIProviderError

    def behaviour(kwargs):
        raise AIProviderError("boom", category=category or "unknown")
    install_provider(monkeypatch, behaviour)
    dialog = make_dialog(monkeypatch)
    try:
        dialog.ai_panel.start()
        assert wait_until(lambda: not dialog.ai_panel.running)
        assert expected in dialog.ai_panel.status.text()
        assert dialog.ai_panel.run_button.isEnabled()
    finally:
        dialog.deleteLater()


def test_finding_buttons_respect_available_actions(monkeypatch):
    dialog = make_dialog(monkeypatch, available=set(ACTION_LABELS) - TASK_ACTIONS)
    try:
        buttons = {action for card in dialog.cards for action in card.action_buttons}
        assert buttons and not buttons & TASK_ACTIONS
        card = dialog.cards[0]
        action = next(iter(card.action_buttons))
        card.action_buttons[action].click()
        assert dialog.chosen_action == action
    finally:
        dialog.deleteLater()


def test_actions_reach_the_existing_window_entries():
    calls = []
    window = SimpleNamespace(
        _open_ai_settings_dialog=lambda on_finished=None: calls.append(("ai", on_finished is not None)),
        _open_model_picker=lambda role: calls.append(("picker", role)),
        _next_step_action=lambda action: calls.append(("next", action)),
        _open_model_workshop=lambda: calls.append(("workshop",)),
        _check_updates=lambda: calls.append(("update",)),
    )
    assert run_diagnosis_action(window, "ai_settings", reopen=lambda: None)
    assert run_diagnosis_action(window, "pick_timeline")
    assert run_diagnosis_action(window, "choose_plan")
    assert run_diagnosis_action(window, "model_workshop")
    assert run_diagnosis_action(window, "update")
    assert not run_diagnosis_action(window, "support")  # this window has no such entry
    assert calls == [("ai", True), ("picker", "timeline"), ("next", "choose_plan"), ("workshop",), ("update",)]


def test_every_diagnosis_string_has_english_and_japanese():
    from twobyteasr import i18n
    missing = [(language, text) for text in diagnosis_strings() for language in ("en", "ja")
               if text not in i18n._TRANSLATIONS[language]]
    assert not missing, missing[:10]


def test_window_text_goes_through_tr_so_the_localization_test_sees_it():
    """_label / _pill take tr(...) for literal text (a bare literal escaped translation, 2026-10-23)."""
    import ast
    import re
    from pathlib import Path
    tree = ast.parse(Path(dialog_module.__file__).read_text("utf-8"))
    bare = [node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("_label", "_pill")
            and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
            and re.search("[一-鿿]", node.args[0].value)]
    assert not bare, bare


def test_long_english_buttons_wrap_inside_the_card(monkeypatch):
    from twobyteasr import i18n
    monkeypatch.setattr(i18n, "_CURRENT_LANGUAGE_CACHE", "en")
    dialog = make_dialog(monkeypatch)
    try:
        dialog.resize(900, 700)  # offscreen metrics are wider than the real fonts
        APP.processEvents()
        card = dialog.cards[0]
        buttons = list(card.action_buttons.values())
        assert len(buttons) >= 3
        assert all(button.geometry().right() <= card.width() for button in buttons)
        assert len({button.y() for button in buttons}) > 1  # wrapped onto another row
        viewport = dialog.scroll.viewport().width()
        assert card.width() <= viewport
    finally:
        dialog.deleteLater()


def test_locate_task_report_finds_a_failed_task_by_job(monkeypatch, tmp_path):
    from twobyteasr.recognition import reporting
    monkeypatch.setattr(reporting, "REPORT_ROOT", tmp_path)
    media = tmp_path / "录播 [1].mp4"
    report = dict(FAILED_REPORT, media={"path": str(media)})
    (tmp_path / "录播 [1]__abc123_1_字幕任务报告.json").write_text(json.dumps(report, ensure_ascii=False), "utf-8")
    (tmp_path / "录播 [1]__other_1_字幕任务报告.json").write_text("{}", "utf-8")
    found = dialog_module.locate_task_report(str(media), "abc123")
    assert found and found["result"]["error"].startswith("字幕保真检查未通过")
    assert dialog_module.locate_task_report(str(media), "missing") is None


# ---- completion page ------------------------------------------------------------------

@pytest.fixture
def completion_shell(monkeypatch):
    from twobyteasr.app.ui import MainWindow
    shell = MainWindow.__new__(MainWindow)
    QWidget.__init__(shell)
    shell._run_in_progress = False
    shell._ui_language = "zh"
    shell._active_stages = set()
    shell._progress_timer = QTimer(shell)
    shell.workflow = SimpleNamespace(set_active=lambda *args, **kwargs: None)
    shell.console_log = QTextEdit(shell)
    shell._console_lines = ["retained task log"]
    shell._console_fragments = []
    shell.legacy = SimpleNamespace(RUNTIME_SETTINGS={"models": {}, "switches": {}})
    monkeypatch.setattr(shell, "_release_run_state", lambda: None)
    monkeypatch.setattr(shell, "_refresh_progress_cards", lambda: None)
    monkeypatch.setattr(shell, "_switch_page", lambda *args: None)
    monkeypatch.setattr(shell, "_show_task_notification", lambda *args: None)
    monkeypatch.setattr(shell, "_text_ai_ready", lambda: False)
    page = shell._result_page()
    page.setParent(shell)
    yield shell
    shell.deleteLater()


def test_failed_task_shows_the_likely_cause_and_opens_the_window(completion_shell, monkeypatch, tmp_path):
    from twobyteasr.recognition import reporting
    monkeypatch.setattr(reporting, "REPORT_ROOT", tmp_path)
    media = tmp_path / "录播.mp4"
    (tmp_path / "录播__job1_1_字幕任务报告.json").write_text(
        json.dumps(dict(FAILED_REPORT, media={"path": str(media)}), ensure_ascii=False), "utf-8")
    shell = completion_shell
    notes = []
    monkeypatch.setattr(shell, "_show_task_notification", lambda *args: notes.append(args))
    # A failed MediaResult carries no report path (service.py), only the job id.
    shell._handle_result(QueueResult((MediaResult(str(media), "failed", error=FAILED_REPORT["result"]["error"],
                                                  job_id="job1"),), 1.0, job_id="job1"))
    # The end-of-run note names the cause too.
    assert notes and "可能原因：数字在断句时被切开" in str(notes[0][3])
    hint = shell.result_diagnosis_hint
    assert not hint.isHidden()
    assert hint.finding.rule_id == "fidelity_numbers"
    assert "数字在断句时被切开" in hint.text_label.text()
    assert hint.property("tone") == "danger"
    assert shell.diagnose_result_action.isEnabled()
    opened = []
    monkeypatch.setattr(dialog_module, "open_run_diagnosis",
                        lambda window, report, **kwargs: opened.append((report, kwargs)))
    hint.clicked.emit()
    report, kwargs = opened[0]
    assert report["events"] and kwargs["task_name"] == "录播.mp4"
    assert "recover" in kwargs["available_actions"] and "studio" not in kwargs["available_actions"]


def test_healthy_task_has_no_hint_but_the_menu_entry(completion_shell, tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({"status": "success", "result": {"cue_count": 2},
                                       "settings": {"models": {"firered_asr_backend": "local"},
                                                    "switches": {"use_ai_grouping": True, "enable_ai_polish": True}}}),
                           "utf-8")
    shell = completion_shell
    shell._handle_result(QueueResult((MediaResult("a.mp4", "success", report_json_path=str(report_path)),), 1.0))
    assert shell.result_diagnosis_hint.isHidden()
    assert shell.diagnose_result_action.isEnabled()
