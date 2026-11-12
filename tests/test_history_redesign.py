"""Records design C and details design A (2026-11-11)."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QLabel

from tests.test_recognition_history import _app, _report_payload
from twobyteasr.recognition.history_diagnosis import (
    RESUME_ACTION, ai_view, local_view, normalize_action, structured_messages, view_text,
)
from twobyteasr.recognition.recognition_history import (
    HistoryGroup, RecognitionHistoryDetail, RecognitionHistoryPage, parse_recognition_report,
)


def _failed(name="8bqmF9XBd14.mp4", when="2026-11-11T10:34:00+08:00", task_id="t1", seconds=25.4):
    payload = _report_payload()
    payload["media"]["name"] = name
    payload["status"] = "failed"
    payload["started_at"] = payload["finished_at"] = when
    payload["task_id"] = task_id
    payload["result"]["elapsed_seconds"] = seconds
    payload["result"]["cue_count"] = 0
    payload["result"]["error"] = "MOSS Pro 云端任务未启动"
    payload["stages"] = []
    payload["task"] = {"current_stage": "等待启动", "last_error": "MOSS Pro 云端任务未启动", "remote_total": 0,
                       "remote_requests": {}}
    return payload


def test_ai_answer_json_becomes_a_card_and_unknown_actions_are_dropped():
    answer = "```json\n" + json.dumps({
        "conclusion": "API Key 没有通过验证", "confidence": "HIGH",
        "reasons": ["日志里有 401", ""], "log_lines": ["POST → 401"],
        "steps": [{"title": "重新填写 Key", "detail": "可能过期", "action": "cloud_asr_setup"},
                  {"title": "重试", "action": "retry"},
                  {"title": "做点别的", "action": "rm -rf"},
                  "直接一句"],
        "fallback": "回报问题",
    }, ensure_ascii=False) + "\n```"
    view = ai_view(answer)
    assert view.source == "ai" and view.confidence == "high" and view.confidence_label == "高"
    assert view.reasons == ("日志里有 401",)
    assert [step.action for step in view.steps] == ["cloud_asr_setup", RESUME_ACTION, "", ""]
    assert "重新填写 Key" in view_text(view)
    assert ai_view("这不是 JSON") is None
    assert normalize_action("studio") == "" and normalize_action("repair_runtime_moss") == "repair_runtime_moss"


def test_structured_request_keeps_the_diagnosis_messages_and_asks_for_json():
    messages = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
    shaped = structured_messages(messages)
    assert messages[1]["content"] == "U"
    assert shaped[0] == messages[0] and shaped[1]["content"].startswith("U\n\n") and '"conclusion"' in shaped[1]["content"]
    assert "resume" in shaped[1]["content"] and "cloud_asr_setup" in shaped[1]["content"]


def test_local_check_fills_the_card_for_a_failed_task(tmp_path):
    from twobyteasr.recognition.run_diagnosis import DiagnosisInput, diagnose_run
    view = local_view(diagnose_run(DiagnosisInput(report=_failed())))
    assert view.source == "local" and view.conclusion
    assert all(step.action in {"", RESUME_ACTION} or step.action for step in view.steps)


def test_attempts_at_one_media_share_a_group_newest_first(tmp_path):
    _app()
    reports = tmp_path / "reports"
    reports.mkdir()
    for index, when in enumerate(("2026-11-10T13:17:00+08:00", "2026-11-10T13:35:00+08:00", "2026-11-11T10:34:00+08:00")):
        (reports / f"r{index}_字幕任务报告.json").write_text(
            json.dumps(_failed(when=when, task_id=f"t{index}"), ensure_ascii=False), "utf-8")
    other = _report_payload()
    other["media"]["name"] = "其它.mp4"
    (reports / "ok_字幕任务报告.json").write_text(json.dumps(other, ensure_ascii=False), "utf-8")
    page = RecognitionHistoryPage(reports, index_path=tmp_path / "index.json")
    page._roots = lambda: [reports]
    page.refresh()
    groups = [group for group in page.findChildren(HistoryGroup) if not group.isHidden()]
    by_name = {group.records[0].media_name: group for group in groups}
    failed = by_name["8bqmF9XBd14.mp4"]
    assert len(failed.records) == 3 and "全部失败" in failed.verdict.text()
    assert [card.number.text() for card in page._cards if card.record.media_name == "8bqmF9XBd14.mp4"] == ["3", "2", "1"]
    assert failed.primary_button.isVisibleTo(failed)
    assert page.overview.failed_tile.value.text() == "3"
    assert page.overview.ai_card.isVisibleTo(page.overview)
    # 按时间: one list, no group headers, media names on the rows.
    page._set_view("time")
    visible = [group for group in page.findChildren(HistoryGroup) if not group.isHidden()]
    assert len(visible) == 1 and visible[0].header.isHidden()
    assert all(card.media_label.isVisibleTo(card) for card in page._cards)
    assert len(page._cards) == 4
    page.deleteLater()


def test_failed_detail_leads_with_diagnosis_and_hides_pending_rows(tmp_path):
    app = _app()
    path = tmp_path / "failed_字幕任务报告.json"
    path.write_text(json.dumps(_failed(), ensure_ascii=False), "utf-8")
    detail = RecognitionHistoryDetail(parse_recognition_report(path), closable=True)
    detail.resize(1120, 900)
    detail.show()
    app.processEvents()
    labels = [label.text() for label in detail.findChildren(QLabel)]
    assert detail.diagnosis_panel is not None and "结论" in labels
    assert detail.resume_button.isVisible() and detail.raw_button.isVisible()
    assert not any(text.endswith("待确认") for text in labels)
    detail.raw_button.click()
    app.processEvents()
    assert detail.raw_view.isVisible()
    actions = []
    detail.action_requested.connect(actions.append)
    detail.diagnosis_panel.action_requested.emit("ai_settings")
    assert actions == ["ai_settings"]
    detail.close()
    detail.deleteLater()


def test_moss_pro_cloud_accuracy_reference_is_ninety():
    from twobyteasr.local_models.model_benchmarks import reference_entry
    entry = reference_entry("mosi_moss_pro", "accuracy", "zh")
    assert entry["score"] == 90 and entry["approx"] is True
