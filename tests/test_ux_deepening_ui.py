"""Offscreen PySide6 tests for slim ``专名与方案`` tab, 3-switch AutoPipelinePanel,
studio_finish_flow, Speaker cast memory, MicroUpgradePill, and QuickTermCaptureWidget."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QFrame, QTabWidget, QWidget

from twobyteasr.app.micro_upgrade import MicroUpgradeOffer
from twobyteasr.glossary.quick_term_dialog import QuickTermCaptureWidget
from twobyteasr.projects.auto_pipeline import AutoPipelineConfig
from twobyteasr.projects.mission_plan import build_mission_plan
from twobyteasr.projects.series_store import SeriesStore
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.studio.auto_pipeline_ui import AutoPipelinePanel
from twobyteasr.studio.mission_strip_ui import FinishChecklistPanel, MicroUpgradePill
from twobyteasr.studio.studio_finish_flow import (
    apply_series_cast_to_project,
    install_studio_finish_wiring,
    on_manual_text_edited,
    refresh_finish_checklist,
    remember_project_speakers,
    replace_all_and_add_term,
)


def _app():
    return QApplication.instance() or QApplication([])


def _clean_len(text: str) -> int:
    return len(text.replace("⚙", "").replace("✓", "").strip())


def test_slim_terms_and_plan_tab_has_no_banner_and_short_switches():
    _app()
    plan = build_mission_plan(
        term_candidates=[{"from": "杰风", "to": "捷风", "count": 9}],
        review_issues=[{"cue_id": "c1", "title": "一百四十 vs 140", "kind": "text"}],
        series_id="ser_1",
        series_name="瓦罗兰特双排",
        series_delta_count=2,
    )

    source_tabs = QTabWidget()
    source_tabs.setObjectName("studioSourceTabs")
    source_tabs.addTab(QWidget(), "字幕列表")
    source_tabs.addTab(QWidget(), "源素材")
    panel = FinishChecklistPanel(source_tabs)
    idx = source_tabs.addTab(panel, plan.tab_badge_label())
    assert idx == 2
    assert source_tabs.tabText(2) == "专名与方案 1"
    # 2026-11-26 (draft B): 自动开关 is folded into the scheme card; its ⚙ opens the full dialog.
    assert panel.pipeline_btn.text() == "" and "自动开关" in panel.pipeline_btn.toolTip()

    panel.set_plan(
        plan,
        save_items=[{"id": "k1", "label": "把「杰风 → 捷风」加入词库", "checked": True}],
        pipeline_config=AutoPipelineConfig(enabled=True, run_glossary=True, run_speakers=True, run_style_preset=False),
    )

    # Redundant top pipeline banner MUST be completely removed
    assert panel.findChild(QFrame, "finishPipelineBanner") is None

    # The scheme card's three upright stamps: a count over a short label (<= 6 chars), with tooltips
    assert set(panel._inline_switches.keys()) == {"run_glossary", "run_speakers", "run_style_preset"}
    for stamp in panel._inline_switches.values():
        assert _clean_len(stamp.accessibleName()) <= 6
        assert stamp.toolTip().strip()
    assert panel.pipeline_btn.isVisible() or panel.pipeline_btn.parent() is not panel

    toggled = []
    panel.pipeline_config_changed.connect(toggled.append)
    panel._inline_switches["run_style_preset"].setChecked(True)
    assert len(toggled) == 1 and toggled[0].run_style_preset is True and toggled[0].enabled is True

    saved = []
    panel.save_to_plan_requested.connect(saved.append)
    panel._emit_save()
    assert len(saved) == 1 and saved[0][0]["checked"] is True


def test_auto_pipeline_panel_three_switches_short_labels_and_live_preview():
    _app()
    panel = AutoPipelinePanel(
        scheme_name="韩V新星切片",
        config=AutoPipelineConfig(enabled=True, run_glossary=True, run_speakers=True, run_style_preset=True),
    )

    # Translation & draft SRT switches must be gone
    assert not hasattr(panel, "cb_translation")
    assert not hasattr(panel, "cb_srt")
    assert not hasattr(panel, "target_combo")
    assert not hasattr(panel, "display_combo")
    assert not hasattr(panel, "cb_stop_review")

    # All 3 switches + controls strictly <= 6 chars with detailed tooltips
    assert panel.cb_glossary.text() == "套常用词库"
    assert panel.cb_speakers.text() == "套常用人名"
    assert panel.cb_style.text() == "套常用样式"
    for widget in (panel.cb_enabled, panel.cb_glossary, panel.cb_speakers, panel.cb_style, panel.run_now_btn, panel.save_btn):
        assert _clean_len(widget.text()) <= 6
        assert widget.toolTip().strip()

    # Live flow preview reflects only checked items
    assert panel.flow_preview.text() == "识别 → 套常用词库 → 套常用人名 → 套常用样式"
    panel.cb_speakers.setChecked(False)
    assert panel.flow_preview.text() == "识别 → 套常用词库 → 套常用样式"

    captured = []
    panel.saved_requested.connect(captured.append)
    panel.save_btn.click()
    assert len(captured) == 1
    assert captured[0].enabled is True
    assert captured[0].run_glossary is True
    assert captured[0].run_speakers is False
    assert captured[0].run_style_preset is True


def test_live_finish_flow_replace_undo_inline_switch_and_friction_pill(tmp_path: Path, monkeypatch):
    _app()
    monkeypatch.setenv("2BYTEASR_USER_DATA_ROOT", str(tmp_path))
    project = SubtitleProject(
        media=StudioMedia(path="val_ep05.mp4", display_name="瓦罗兰特双排 EP05"),
        speakers=[
            StudioSpeaker(id="S00", name="S00", color="#7fb8c2"),
            StudioSpeaker(id="S01", name="S01", color="#e0809f"),
        ],
        cues=[
            StudioCue(id="c1", start_ms=0, end_ms=1000, speaker_id="S00", text="杰风起大招了"),
            StudioCue(id="c2", start_ms=1200, end_ms=2200, speaker_id="S01", text="杰风在A点"),
        ],
    )
    source_tabs = QTabWidget()
    source_tabs.setObjectName("studioSourceTabs")
    source_tabs.addTab(QWidget(), "字幕列表")
    source_tabs.addTab(QWidget(), "源素材")
    panel = FinishChecklistPanel(source_tabs)
    source_tabs.addTab(panel, "专名与方案")
    pill = MicroUpgradePill()
    undo_stack = QUndoStack()
    changed_hits = []
    page = SimpleNamespace(
        project=project,
        source_tabs=source_tabs,
        finish_checklist_panel=panel,
        micro_upgrade_pill=pill,
        undo_stack=undo_stack,
        _changed=lambda: changed_hits.append(1),
        _speaker_structure_changed=lambda: changed_hits.append(2),
    )
    install_studio_finish_wiring(page)
    refresh_finish_checklist(page)

    # A stamp toggle persists directly to SeriesStore; 「新片自动」 is its own switch (draft B)
    panel._inline_switches["run_style_preset"].setChecked(False)
    store = SeriesStore()
    saved_series = store.get(store.last_selected_id())
    assert saved_series is not None
    assert saved_series.pipeline["run_style_preset"] is False
    assert saved_series.pipeline["enabled"] is False

    hits = replace_all_and_add_term(page, "杰风", "捷风")
    assert hits == 2
    assert project.cues[0].text == "捷风起大招了"
    assert undo_stack.canUndo()
    undo_stack.undo()
    assert project.cues[0].text == "杰风起大招了"

    for _ in range(2):
        assert on_manual_text_edited(page, "他来了", "她来了") is None
    offer = on_manual_text_edited(page, "他走了", "她走了")
    assert offer is not None and offer.kind == "manual_pronoun"
    assert "Shift+F" in pill.action_button.text()


def test_speaker_cast_remember_and_undoable_apply(tmp_path: Path):
    _app()
    store = SeriesStore(tmp_path / "series")
    ep1 = SubtitleProject(
        media=StudioMedia(path="kv_ep01.mp4", display_name="韩V新星切片"),
        speakers=[
            StudioSpeaker(id="S00", name="小K", color="#4f8557", is_host=True),
            StudioSpeaker(id="S01", name="阿七", color="#e0809f"),
            StudioSpeaker(id="S02", name="S02", color="#999999"),
        ],
        cues=[StudioCue(id="c1", start_ms=0, end_ms=1000, speaker_id="S00", text="大家好")],
    )
    page1 = SimpleNamespace(project=ep1, undo_stack=QUndoStack(), _changed=lambda: None)
    scheme_name, saved = remember_project_speakers(page1, store=store)
    assert scheme_name == "韩V新星切片"
    assert saved == ["小K", "阿七"]

    rec = store.find_by_name("韩V新星切片")
    assert rec is not None and len(rec.cast) == 2

    ep2 = SubtitleProject(
        media=StudioMedia(path="kv_ep02.mp4", display_name="韩V新星切片 EP02"),
        speakers=[
            StudioSpeaker(id="S00", name="S00", color="#aaaaaa"),
            StudioSpeaker(id="S01", name="S01", color="#bbbbbb"),
            StudioSpeaker(id="S02", name="老王", color="#cccccc"),
        ],
        cues=[
            StudioCue(id="c1", start_ms=0, end_ms=1000, speaker_id="S00", text="第一句"),
            StudioCue(id="c2", start_ms=1000, end_ms=2000, speaker_id="S00", text="第二句"),
            StudioCue(id="c3", start_ms=2000, end_ms=3000, speaker_id="S01", text="第三句"),
        ],
    )
    stack2 = QUndoStack()
    page2 = SimpleNamespace(
        project=ep2,
        undo_stack=stack2,
        _changed=lambda: None,
        _speaker_structure_changed=lambda: None,
    )
    applied, msg = apply_series_cast_to_project(page2, rec.id, store=store)
    assert applied == [("S00", "小K"), ("S01", "阿七")]
    assert "Ctrl+Z" in msg
    assert ep2.speakers[2].name == "老王"
    stack2.undo()
    assert ep2.speakers[0].name == "S00"


def test_micro_upgrade_pill_and_quick_term_capture():
    _app()
    pill = MicroUpgradePill()
    offer = MicroUpgradeOffer(
        kind="repeated_typo",
        message="刚连改 2 次「元神 → 原神」",
        action_label="一键全片替换（11 处）",
        insight_after="已修完 11 处，以后可用 Ctrl+H。",
    )
    fired = []
    pill.action_clicked.connect(fired.append)
    pill.show_offer(offer)
    pill.action_button.click()
    assert len(fired) == 1 and pill.action_button.isHidden()

    widget = QuickTermCaptureWidget(library_name="瓦罗兰特")
    widget.input_box.setPlainText("杰风 -> 捷风\n大 -> 打\n深海明珠（深海明主）")
    assert len(widget._candidates) == 4
    dangerous = [c for c in widget._candidates if c.source == "大"]
    assert len(dangerous) == 1 and dangerous[0].dangerous is True and dangerous[0].checked is False


def test_merged_bilingual_and_rough_cut_coexist_cleanly():
    _app()
    from PySide6.QtCore import QEvent, QPointF, QRect, Qt
    from PySide6.QtGui import QImage, QMouseEvent, QPainter
    from PySide6.QtWidgets import QMenu, QStyleOptionViewItem

    from twobyteasr.design import theme_manager
    from twobyteasr.studio.ai_rough_cut import REASON_RETAKE, set_cue_cut_mark
    from twobyteasr.studio.studio_cue_table import CueReadingDelegate, CueTableModel
    from twobyteasr.studio.studio_translation_edit import build_cue_list_menu
    from twobyteasr.studio.studio_video_flow import StudioVideoFlowMixin

    project = SubtitleProject(
        media=StudioMedia(path="demo.mp4", duration_ms=15_000),
        speakers=[StudioSpeaker(id="S00", name="主播小蓝", color="#4f8557")],
        cues=[
            StudioCue(
                id="c1",
                start_ms=0,
                end_ms=2500,
                speaker_id="S00",
                text="잠깐 페이몬이 아니라 벤티였어",
                original_text="잠깐 페이몬이었어",
            ),
            StudioCue(
                id="c2",
                start_ms=3000,
                end_ms=5500,
                speaker_id="S00",
                text="그냥 넘어가자",
                original_text="그냥 넘어가자",
            ),
        ],
        generation_metadata={
            "translations": {
                "c1": "等等，原来刚才那是派蒙的声音",
                "c2": "这段直接跳过吧",
            },
            "translation_records": {
                "target": "zh-CN",
                "records": {
                    "c1": {
                        "text": "等等，原来刚才那是派蒙的声音",
                        "source_text": "잠깐 페이몬이었어",
                        "status": "needs_update",
                    },
                    "c2": {
                        "text": "这段直接跳过吧",
                        "source_text": "그냥 넘어가자",
                        "status": "ready",
                    },
                },
            },
        },
    )
    set_cue_cut_mark(project, "c1", marked=True, reason=REASON_RETAKE)

    model = CueTableModel(project)
    assert model.text_layer == "bilingual"
    delegate = CueReadingDelegate()
    orig_theme_key = theme_manager.theme_key
    try:
        for width in (380, 340, 268):
            for theme_name in ("warm", "grape"):
                theme_manager.theme_key = lambda _n=theme_name: _n
                img = QImage(width, 260, QImage.Format.Format_ARGB32)
                img.fill(Qt.GlobalColor.transparent)
                painter = QPainter(img)
                row_h = delegate.row_height(QApplication.font(), bilingual=True)
                opt0 = QStyleOptionViewItem()
                opt0.rect = QRect(0, 0, width, row_h)
                delegate.paint(painter, opt0, model.index(0, 3))
                painter.end()

                cut_rect = delegate._rough_cut_rects.get(0)
                retrans_rect = delegate._retranslate_rect(opt0, model, 0)
                assert cut_rect is not None
                assert cut_rect.width() >= 48, f"rough-cut pill crushed at width={width}: {cut_rect}"
                if 0 not in delegate._hidden_retranslate_rows:
                    assert not cut_rect.intersects(retrans_rect), (
                        f"rough-cut pill {cut_rect} overlaps retranslate pill {retrans_rect} at width={width}"
                    )
                else:
                    assert delegate.hit_action_button(opt0, model, 0, retrans_rect.center()) != "retranslate"
    finally:
        theme_manager.theme_key = orig_theme_key

    # Press + Release on rough-cut pill must emit exactly ONCE (no Press+Release double toggle)
    opt0 = QStyleOptionViewItem()
    opt0.rect = QRect(0, 0, 340, delegate.row_height(QApplication.font(), bilingual=True))
    toggled: list[str] = []
    delegate.rough_cut_toggle_requested.connect(toggled.append)
    center = delegate._rough_cut_rects[0].center()
    press_ev = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(center),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    release_ev = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(center),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert delegate.editorEvent(press_ev, model, opt0, model.index(0, 3)) is True
    assert toggled == []
    assert delegate.editorEvent(release_ev, model, opt0, model.index(0, 3)) is True
    assert toggled == ["c1"]

    # Unified right-click context menu carries BOTH bilingual & rough-cut actions
    class _StubPage(StudioVideoFlowMixin):
        def __init__(self):
            self.project = project
            self.cue_model = model
            self.cue_controller = SimpleNamespace(selected_cue_ids=lambda: ["c1"])

        def _open_caption_editor(self, *_args):
            pass

        def _refresh_rough_cut_ui(self, *_args):
            pass

        def _rough_cut_background_speaker(self, *_args):
            pass

        def _toggle_rough_cut_seam_preview(self, *_args):
            pass

        def _apply_rough_cut(self):
            pass

        def _clear_rough_cut_marks(self):
            pass

    stub = _StubPage()
    menu = QMenu()
    build_cue_list_menu(stub, menu, "c1")
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert "编辑译文" in labels and "编辑原文" in labels and "重翻此句" in labels
    assert "恢复保留" in labels and "剪此说话人" in labels and "应用裁剪" in labels
