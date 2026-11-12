"""Translation dialog 方案 A layout (2026-11-11, user picked design A).

Three numbered steps whose badges line up, range cards whose numbers drive
the start button, coloured tones (待处理 orange, 全部 green), and the
idle / running / finished faces around the same controls.
"""
from types import SimpleNamespace

from PySide6.QtCore import QPoint
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QLabel

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.studio.studio_translation_dialog import SubtitleTranslationDialog
from twobyteasr.studio.translation_dialog_parts import StatusBar
from twobyteasr.subtitle_rules import subtitle_translation as st


def _project(count=8):
    project = SubtitleProject(media=StudioMedia(path="synthetic.mp4", duration_ms=60_000),
        cues=[StudioCue(f"c{i}", i * 1000, i * 1000 + 900, f"Line {i} where we open the big door.")
              for i in range(count)])
    project.generation_metadata["language"] = {"code": "en"}
    return project


def _page(project, selected=()):
    return SimpleNamespace(project=project, selected_cue_ids=lambda: list(selected), undo_stack=QUndoStack(),
                           _cue_jump_order=list(project.cues),
                           _cue_jump_index={cue.id: i for i, cue in enumerate(project.cues)}, _review_mode=False)


def _fail(project, ids):
    st.apply_translation_result(project, st.TranslationResult(
        target="zh-Hans", model="fixture", provider="fixture", failed={cue_id: "missing" for cue_id in ids},
        sources={cue.id: cue.text for cue in project.cues}))


def test_three_step_badges_share_one_left_edge():
    app = QApplication.instance() or QApplication([])
    dialog = SubtitleTranslationDialog(_page(_project()))
    try:
        dialog.show()
        app.processEvents()
        badges = [label for label in dialog.findChildren(QLabel) if label.objectName() == "translationStep"]
        assert sorted(label.text() for label in badges) == ["1", "2", "3"]
        assert len({label.mapTo(dialog, QPoint(0, 0)).x() for label in badges}) == 1
        dialog.advanced_toggle.click()           # opening step 2 does not move its badge
        app.processEvents()
        assert not dialog.advanced.isHidden()
        assert len({label.mapTo(dialog, QPoint(0, 0)).x() for label in badges}) == 1
    finally:
        dialog.close()
        dialog.deleteLater()


def test_range_cards_stay_compact_when_the_window_is_taller():
    """2026-11-11 (user, daily screenshot): spare height had stretched the cards far past 方案 A."""
    app = QApplication.instance() or QApplication([])
    dialog = SubtitleTranslationDialog(_page(_project()))
    try:
        dialog.show()
        app.processEvents()
        compact = {key: card.height() for key, card in dialog.scope_buttons.items()}
        dialog.resize(dialog.width(), dialog.height() + 400)
        app.processEvents()
        assert {key: card.height() for key, card in dialog.scope_buttons.items()} == compact
        tallest = max(card.sizeHint().height() for card in dialog.scope_buttons.values())
        assert set(compact.values()) == {tallest}                             # one row, one height
        # 方案 A: “需更新 0” sits on its own line and never splits.
        assert dialog.scope_buttons["pending"].detail.text().split("\n")[-1] == "需更新\u00a00"
    finally:
        dialog.close()
        dialog.deleteLater()


def test_range_cards_carry_counts_tones_and_the_start_label():
    QApplication.instance() or QApplication([])
    project = _project()
    _fail(project, ["c2", "c5"])
    dialog = SubtitleTranslationDialog(_page(project, selected=["c1", "c3", "c4"]))
    try:
        cards = dialog.scope_buttons
        assert {key: card.property("tone") for key, card in cards.items()} == {
            "pending": "pending", "all": "all", "selected": "selected"}
        assert cards["selected"].isChecked() and dialog.start_button.text() == "开始翻译 · 3 条"
        assert cards["pending"].count() == 8 and cards["all"].count() == 8   # 6 untranslated + 2 failed
        assert "失败\u00a02" in cards["pending"].detail.text()
        cards["all"].click()
        assert cards["all"].isChecked() and not cards["selected"].isChecked()
        assert dialog.start_button.text() == "开始翻译 · 8 条"
        assert dialog._scope_ids() is None
        cards["pending"].click()
        assert dialog._scope_ids() == [cue.id for cue in project.cues]
        assert "未翻译" in dialog.counts.text() and not dialog.failed_box.isHidden()
        assert "2" in dialog.failed_title.text()
    finally:
        dialog.deleteLater()


def test_selected_card_is_disabled_without_a_selection_and_failures_hide_when_none():
    QApplication.instance() or QApplication([])
    dialog = SubtitleTranslationDialog(_page(_project()))
    try:
        assert not dialog.scope_buttons["selected"].isEnabled()
        assert dialog.scope_buttons["pending"].isChecked()
        assert dialog.failed_box.isHidden() and dialog.failed_note.isHidden()
        assert dialog.advanced.isHidden() and dialog.log_panel.isHidden()
    finally:
        dialog.deleteLater()


def test_running_and_finished_faces():
    app = QApplication.instance() or QApplication([])
    project = _project()
    dialog = SubtitleTranslationDialog(_page(project))
    try:
        dialog.show()
        dialog._set_phase("run")
        dialog._on_progress(3, 6, "")
        app.processEvents()
        assert not dialog.run_box.isHidden() and dialog.scope_section.isHidden() and dialog.overview.isHidden()
        assert dialog.start_button.isHidden() and dialog.cancel_button.text() == "停止"
        assert dialog.run_percent.text() == "50%" and dialog.progress.value() == 50
        result = st.TranslationResult(target="zh-Hans", model="fixture", provider="fixture",
                                      failed={"c0": "number_mismatch"},
                                      sources={cue.id: cue.text for cue in project.cues})
        dialog._on_finished(result)
        app.processEvents()
        assert dialog.run_box.isHidden() and not dialog.scope_section.isHidden()
        assert not dialog.start_button.isHidden() and dialog.cancel_button.text() == "关闭"
        assert not dialog.result_card.isHidden() and dialog.result_card.property("tone") == "bad"
        assert dialog.result_title.text() == "这一次没翻成功"
        assert "number_mismatch" in dialog.status.text() and "没有通过检查" in dialog.status.text()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_status_bar_keeps_small_states_visible():
    QApplication.instance() or QApplication([])
    bar = StatusBar()
    bar.set_segments([(1649, "#00ff00"), (0, "#0000ff"), (23, "#ff0000")], "#333333")
    widths = bar.segment_widths(500.0)
    assert len(widths) == 2 and widths[1] >= StatusBar.MIN_SEGMENT
    assert abs(sum(widths) + StatusBar.GAP - 500.0) < 0.01
