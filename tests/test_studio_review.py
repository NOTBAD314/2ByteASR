import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.studio_review import (
    analyze_review_risks,
    review_evidence_coverage,
    review_hypotheses_from_project,
)
from twobyteasr.studio_ui import SubtitleStudioPage


def _app():
    return QApplication.instance() or QApplication([])


def _drain_chunked_qc(page, timeout_s: float = 5.0) -> None:
    """分片 QC（2026-09-18）异步完成：泵事件直到本工程扫描结束。"""
    import time as _time
    app = QApplication.instance()
    deadline = _time.monotonic() + timeout_s
    project = page.project
    while _time.monotonic() < deadline:
        app.processEvents()
        if project is not None and getattr(project, "_qc_result", None) is not None:
            if getattr(page, "_qc_scan_timer", None) is not None and not page._qc_scan_timer.isActive():
                app.processEvents()
                return
        _time.sleep(0.01)


def test_review_risk_combines_timing_readability_confidence_and_disagreement():
    project = SubtitleProject(
        media=StudioMedia(path="D:/review.mp4", duration_ms=10_000),
        cues=[
            StudioCue("high", 0, 300, "这是一条在极短时间里根本读不完的字幕", evidence_refs=["e:1"]),
            StudioCue("safe", 2000, 4000, "正常字幕", evidence_refs=["e:2"]),
        ],
        asr_evidence={
            "e:1": {"moss_text": "天平", "qwen_asr_text": "甜品", "confidence": 0.31},
            "e:2": {"moss_text": "正常字幕", "qwen_asr_text": "正常字幕", "confidence": 0.97},
        },
    )

    risks = analyze_review_risks(project)

    assert risks["high"].level == "high"
    assert "多模型文本不一致" in risks["high"].reasons
    assert any(reason.startswith("低置信度") for reason in risks["high"].reasons)
    assert risks["safe"].level == "confident"


def test_review_hypotheses_keep_firered_and_qwen_when_primary_text_exists():
    project = SubtitleProject(
        media=StudioMedia(path="D:/review.mp4", duration_ms=10_000),
        cues=[StudioCue("cue", 0, 1200, "当前字幕", evidence_refs=["e:1"])],
        asr_evidence={
            "e:1": {
                "start_ms": 0,
                "end_ms": 1200,
                "text": "当前字幕",
                "moss_text": "当前字幕",
                "firered_text": "天平",
                "qwen_asr_text": "甜品",
                "primary_source": "moss",
            }
        },
    )
    rows = review_hypotheses_from_project(project, project.cues[0])
    models = {str(row.get("model") or "").casefold() for row in rows}
    assert any("moss" in model for model in models)
    assert any("firered" in model for model in models)
    assert any("qwen" in model for model in models)
    coverage = review_evidence_coverage(project)
    assert coverage["TOTAL"] == 1
    assert coverage["MOSS_COUNT"] == 1
    assert coverage["FIRERED_COUNT"] == 1
    assert coverage["QWEN_COUNT"] == 1
    assert coverage["3_SOURCE_OVERLAP"] == 1


def test_priority_review_confirmation_advances_and_persists_state(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "review.mp4"), duration_ms=10_000),
        cues=[
            StudioCue("a", 0, 250, "第一条非常快的字幕"),
            StudioCue("b", 1000, 1250, "第二条非常快的字幕"),
            StudioCue("c", 3000, 5000, "正常"),
        ],
    )
    path = save_project(project, tmp_path / "review.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(path)
    _drain_chunked_qc(page)
    page._activate_filter("priority")
    page._set_review_mode(True)

    assert page.cue_model.rowCount() == 2
    assert page.cue_model.data(page.cue_model.index(0, 4)) == "需要检查"
    page.select_cue("a")
    page._confirm_current_review()

    assert page.project.studio_state["cue_statuses"]["a"] == "done"
    assert "a" in page.project.studio_state["review_confirmations"]
    # The review session freezes the two visible cue IDs instead of shrinking
    # the queue when a cue becomes confirmed.
    assert page.cue_model.rowCount() == 2
    assert page.selected_cue_id == "b"
    page.close_page()
    page.deleteLater()


def test_priority_review_keeps_chronological_order(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "review.mp4"), duration_ms=10_000),
        cues=[
            StudioCue("suggested", 0, 100, "普通偏快字幕"),
            StudioCue("high", 1200, 1300, "这是一条极短且完全读不完的高风险字幕"),
        ],
    )
    path = save_project(project, tmp_path / "review-order.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(path)
    _drain_chunked_qc(page)
    page._activate_filter("priority")

    assert [page.cue_model.cue_at(row).id for row in range(page.cue_model.rowCount())] == [
        "suggested",
        "high",
    ]
    page.select_cue("suggested")
    page._step_priority(1)
    assert page.selected_cue_id == "high"
    page.close_page()
    page.deleteLater()


def test_priority_review_real_key_events_and_editor_focus_safety(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "review.mp4"), duration_ms=10_000),
        cues=[
            StudioCue("a", 0, 250, "第一条非常快的字幕"),
            StudioCue("b", 1000, 1250, "第二条非常快的字幕"),
        ],
    )
    path = save_project(project, tmp_path / "review-keys.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.resize(1400, 850)
    page.show()
    page.activateWindow()
    page.open_project(path)
    page._set_review_mode(True)
    page.select_cue("a")
    app.processEvents()

    calls = {"space": 0, "r": 0}
    monkeypatch.setattr(
        page,
        "_play_review_context",
        lambda: calls.__setitem__("space", calls["space"] + 1),
    )
    page._command_callbacks["reasr_review"] = lambda: calls.__setitem__(
        "r", calls["r"] + 1
    )
    QTest.keyClick(page, Qt.Key.Key_Space)
    QTest.keyClick(page, Qt.Key.Key_R)
    assert not page._review_mode
    QTest.keyClick(page, Qt.Key.Key_R)
    QTest.keyClick(page, Qt.Key.Key_R, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClick(page, Qt.Key.Key_E)
    app.processEvents()
    assert calls == {"space": 1, "r": 1}
    assert page._canvas_editor is not None
    assert page._canvas_editor.hasFocus()

    QTest.keyClick(page._canvas_editor, Qt.Key.Key_R)
    QTest.keyClick(page._canvas_editor, Qt.Key.Key_Space)
    assert calls == {"space": 1, "r": 1}
    QTest.keyClick(page._canvas_editor, Qt.Key.Key_Escape)

    page.timeline.setFocus()
    QTest.keyClick(page, Qt.Key.Key_Return)
    app.processEvents()
    assert page.project.studio_state["cue_statuses"]["a"] == "done"
    assert page.selected_cue_id == "b"
    QTest.keyClick(page, Qt.Key.Key_Escape)
    assert page.cue_model.filter_status == "all"
    page.close_page()
    page.deleteLater()


def test_removed_checks_page_does_not_implicitly_rewrite_project(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "review.mp4"), duration_ms=10_000),
        cues=[StudioCue("a", 0, 1_000, "  第一条 １２！！  ")],
    )
    path = save_project(project, tmp_path / "safe-fix.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(path)
    # Full QC runs as a deferred singleShot so the first playable state reaches
    # the event loop first; pump once before asserting on the safe-fix card.
    app.processEvents()

    assert not hasattr(page, 'safe_fix_card')
    assert not hasattr(page, '_apply_safe_fixes')
    # AI设计 / 样式 / 动效 / 视频 / 剪辑助手 / 素材 — no 检查 page.
    assert page.context_drawer.count() == 6
    assert '检查' not in [page.context_drawer.tabToolTip(i) for i in range(page.context_drawer.count())]
    assert page.undo_stack.count() == 0
    assert page.project.cues[0].text == "  第一条 １２！！  "
    page.close_page()
    page.deleteLater()


def test_model_evidence_adoption_uses_undo_and_then_manual_learning_baseline(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "review.mp4"), duration_ms=10_000),
        cues=[StudioCue("a", 0, 1_500, "星见鸦", evidence_refs=["e:1"])],
        asr_evidence={"e:1": {"moss_text": "星见鸦", "qwen_asr_text": "星见雅"}},
    )
    path = save_project(project, tmp_path / "model-adopt.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(path)
    page.select_cue("a")

    page._adopt_model_text("星见雅", "Qwen")
    assert page.project.cues[0].text == "星见雅"
    assert page.undo_stack.count() == 1
    assert page._manual_text_baselines["a"] == "星见雅"
    page.undo_stack.undo()
    assert page.project.cues[0].text == "星见鸦"
    assert page._manual_text_baselines["a"] == "星见鸦"
    page.close_page()
    page.deleteLater()
