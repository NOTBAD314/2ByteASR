"""Task 2 tests: bilingual dual-line cue list, switcher, and single-cue 「重翻此句」."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, QRect, Qt
from PySide6.QtGui import QFont, QFontMetrics, QImage, QMouseEvent, QPainter, QUndoStack
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QStyle, QStyleOptionViewItem, QTableView

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.studio.studio_bilingual import (
    CUE_LIST_LAYERS,
    build_cue_layer_switcher,
    set_cue_list_text_layer,
    sync_cue_list_layer_controls,
)
from twobyteasr.studio.studio_cue_table import (
    CueReadingDelegate,
    CueTableModel,
    cue_translation_needs_update,
    project_has_translations,
)
from twobyteasr.studio.studio_translation_edit import build_cue_list_menu
from twobyteasr.studio.translation_actions import translate_selected
from twobyteasr.subtitle_rules import subtitle_translation as st


APP = QApplication.instance() or QApplication([])


def _bilingual_project(*, with_records: bool = True, language: str = "ko") -> SubtitleProject:
    cues = [
        StudioCue("c1", 0, 2200, "페이몬, 저기 보물 상자가 있어!", speaker_id="S01", original_text="페이몬, 저기 보물 상자가 있어!"),
        StudioCue("c2", 2400, 4800, "진짜네? 빨리 열어보자!", speaker_id="S02", original_text="진짜네? 빨리 열어보자!"),
        StudioCue("c3", 5000, 7600, "잠깐만, 함정일 수도 있으니까 조심해.", speaker_id="S01", original_text="잠깐만, 함정일 수도 있으니까 조심해."),
        StudioCue("c4", 7800, 10200, "아직 번역되지 않은 문장이야.", speaker_id="S02", original_text="아직 번역되지 않은 문장이야."),
    ]
    translations = {
        "c1": "派蒙，那边有个宝箱！",
        "c2": "真的耶？快去打开看看吧！",
        "c3": "等一下，可能是陷阱，小心点。",
    }
    meta: dict = {
        "language": language,
        "translations": dict(translations),
    }
    if with_records:
        meta["translation_records"] = {
            "version": 1,
            "target": "zh-Hans",
            "records": {
                cue.id: st._record(translations[cue.id], cue.text, origin=st.ORIGIN_AI, target="zh-Hans")
                for cue in cues
                if cue.id in translations
            },
            "history": [],
        }
    return SubtitleProject(
        media=StudioMedia(path="demo_kr.mp4", duration_ms=12000),
        speakers=[
            StudioSpeaker(id="S01", name="旅行者", color="#6186b0"),
            StudioSpeaker(id="S02", name="派蒙", color="#9b7180"),
        ],
        cues=cues,
        generation_metadata=meta,
        studio_state={"bilingual": {"mode": "bilingual"}},
    )


def _monolingual_project() -> SubtitleProject:
    return SubtitleProject(
        media=StudioMedia(path="mono.mp4", duration_ms=6000),
        cues=[
            StudioCue("m1", 0, 2500, "这是一条纯单语中文字幕", speaker_id="S01"),
            StudioCue("m2", 2600, 5000, "这里没有任何译文记录", speaker_id="S01"),
        ],
    )


class _MockProvider:
    provider_id = "mock"
    model = "mock-translate"

    def __init__(self, reply_map: dict[str, str]):
        self.reply_map = dict(reply_map)
        self.requested_ids: list[list[str]] = []

    def structured_complete(self, messages, schema=None, **kwargs):
        payload = json.loads(messages[-1]["content"])
        items = payload.get("items") or payload.get("cues") or payload.get("lines") or []
        targets = [item for item in items if item.get("translate", True)]
        self.requested_ids.append([str(item["id"]) for item in targets])
        return {
            "items": [
                {"id": str(item["id"]), "translation": self.reply_map.get(str(item["id"]), "新译文")}
                for item in targets
            ]
        }

    complete = structured_complete


def test_default_bilingual_mode_for_translated_projects_and_single_line_for_mono():
    bi_project = _bilingual_project()
    bi_model = CueTableModel(bi_project)
    assert project_has_translations(bi_project) is True
    assert bi_model.text_layer == "bilingual"
    assert bi_model.bilingual_cards is True
    assert "派蒙，那边有个宝箱" in bi_model.data(bi_model.index(0, 3))
    assert bi_model.data(bi_model.index(0, 3), Qt.ItemDataRole.EditRole) == "派蒙，那边有个宝箱！"
    assert "페이몬, 저기 보물 상자가 있어" in bi_model.data(bi_model.index(0, 3), CueTableModel.OriginalTextRole)
    assert bi_model.original_text(bi_project.cues[0], styled=False) == "페이몬, 저기 보물 상자가 있어!"
    # Untranslated row falls back to original on DisplayRole while keeping TranslationTextRole empty
    assert "아직 번역되지 않은 문장이야" in bi_model.data(bi_model.index(3, 3))
    assert bi_model.data(bi_model.index(3, 3), CueTableModel.TranslationTextRole) == ""

    # Pure monolingual project stays single-line original with zero height change
    mono_project = _monolingual_project()
    mono_model = CueTableModel(mono_project)
    assert project_has_translations(mono_project) is False
    assert mono_model.text_layer == "original"
    assert mono_model.bilingual_cards is False

    # set_project switches automatically between bilingual and monolingual
    changed: list[str] = []
    mono_model.text_layer_changed.connect(changed.append)
    mono_model.set_project(bi_project)
    assert mono_model.text_layer == "bilingual"
    assert changed == ["bilingual"]

    # refresh auto-enables bilingual when translations arrive on a previously monolingual project
    fresh_mono = _monolingual_project()
    fresh_model = CueTableModel(fresh_mono)
    assert fresh_model.text_layer == "original"
    fresh_mono.generation_metadata["translations"] = {"m1": "This is a monolingual subtitle"}
    fresh_model.refresh()
    assert fresh_model.text_layer == "bilingual"

    # Legacy project with translation_records only (no render dict yet) also defaults to bilingual
    records_only = _bilingual_project(with_records=True)
    records_only.generation_metadata.pop("translations", None)
    assert project_has_translations(records_only) is True
    assert CueTableModel(records_only).text_layer == "bilingual"


def test_bilingual_search_matches_both_translation_and_original():
    project = _bilingual_project()
    model = CueTableModel(project)
    assert model.bilingual_cards is True

    # Match Chinese translation
    model.set_query("宝箱")
    assert [model.cue_at(r).id for r in range(model.rowCount())] == ["c1"]

    # Match Korean original
    model.set_query("함정일")
    assert [model.cue_at(r).id for r in range(model.rowCount())] == ["c3"]

    # Match untranslated Korean cue
    model.set_query("번역되지")
    assert [model.cue_at(r).id for r in range(model.rowCount())] == ["c4"]

    # Match speaker name
    model.set_query("派蒙")
    assert set(model.cue_at(r).id for r in range(model.rowCount())) == {"c1", "c2", "c4"}

    model.set_query("")
    assert model.rowCount() == 4


def test_switcher_short_labels_height_and_mode_toggles():
    assert all(len(caption) <= 6 for _key, caption, _tip in CUE_LIST_LAYERS)
    assert [caption for _key, caption, _tip in CUE_LIST_LAYERS] == ["双行", "原文", "译文"]

    project = _bilingual_project()
    table = QTableView()
    table.reading = True
    model = CueTableModel(project, parent=table)
    delegate = CueReadingDelegate(table)
    table.setModel(model)
    table.setItemDelegateForColumn(3, delegate)
    page = SimpleNamespace(project=project, cue_model=model, cue_table=table)
    track = build_cue_layer_switcher(page)
    sync_cue_list_layer_controls(page)

    assert not track.isHidden()
    assert page.cue_layer_buttons["bilingual"].isChecked()
    bi_height = CueReadingDelegate.row_height(table.font(), bilingual=True)
    mono_height = CueReadingDelegate.row_height(table.font(), bilingual=False)
    assert bi_height > mono_height
    assert table.verticalHeader().defaultSectionSize() == bi_height

    # Switch to 原文
    set_cue_list_text_layer(page, "original", explicit=True)
    assert model.text_layer == "original"
    assert page.cue_layer_buttons["original"].isChecked()
    assert project.studio_state["cue_list_text_layer"] == "original"
    assert project.schema_version == 1
    assert table.verticalHeader().defaultSectionSize() == mono_height

    # Switch to 译文
    set_cue_list_text_layer(page, "translation", explicit=True)
    assert model.text_layer == "translation"
    assert page.cue_layer_buttons["translation"].isChecked()

    # Switch back to 双行
    set_cue_list_text_layer(page, "bilingual", explicit=True)
    assert model.text_layer == "bilingual"
    assert table.verticalHeader().defaultSectionSize() == bi_height

    # Monolingual project hides the switcher
    mono = _monolingual_project()
    page.project = mono
    model.set_project(mono)
    sync_cue_list_layer_controls(page)
    assert track.isHidden()

    track.deleteLater()
    table.deleteLater()


def test_delegate_bilingual_layout_dpi_hit_test_and_setdata_routing():
    project = _bilingual_project()
    model = CueTableModel(project)
    delegate = CueReadingDelegate()

    # Check 100% and 150% DPI-equivalent font sizes never clip or overlap
    for px in (12, 18):
        base = QFont()
        base.setPixelSize(px)
        row_h = CueReadingDelegate.row_height(base, bilingual=True)
        option = QStyleOptionViewItem()
        option.font = base
        option.rect = QRect(0, 0, 340, row_h)
        layout = delegate._bilingual_layout(option, model, project.cues[0])
        p_bottom = layout["primary_top"] + len(layout["primary_lines"]) * layout["primary_spacing"]
        s_top = layout["secondary_top"]
        s_bottom = s_top + len(layout["secondary_lines"]) * layout["secondary_spacing"]
        assert p_bottom < s_top
        assert s_bottom <= option.rect.bottom() - delegate.CARD_INSET_Y

        # Hit test primary line -> translation; secondary line -> original
        idx = model.index(0, 3)
        assert delegate.hit_edit_layer(option, idx, QPointF(40, layout["primary_top"] + 4)) == "translation"
        assert delegate.hit_edit_layer(option, idx, QPointF(40, s_top + 4)) == "original"

        # Untranslated row renders original on primary and 「未翻译」 placeholder on secondary
        untrans_layout = delegate._bilingual_layout(option, model, project.cues[3])
        assert untrans_layout["has_translation"] is False
        assert "아직 번역되지" in "".join(untrans_layout["primary_lines"])
        assert "未翻译" in "".join(untrans_layout["secondary_lines"])

    # setData routes translation edits in bilingual mode, original edits in original mode
    orig_edits: list[tuple[str, str]] = []
    trans_edits: list[tuple[str, str]] = []
    model.text_edit_requested.connect(lambda cid, txt: orig_edits.append((cid, txt)))
    model.translation_edit_requested.connect(lambda cid, txt: trans_edits.append((cid, txt)))

    assert model.setData(model.index(0, 3), "派蒙，那边有个大宝箱！")
    assert trans_edits == [("c1", "派蒙，那边有个大宝箱！")]
    assert orig_edits == []

    model.set_text_layer("original", explicit=True)
    assert model.setData(model.index(0, 3), "페이몬, 저기 큰 보물 상자가 있어!")
    assert orig_edits == [("c1", "페이몬, 저기 큰 보물 상자가 있어!")]


def test_edit_original_triggers_needs_update_and_retranslate_button_signal():
    project = _bilingual_project(with_records=True)
    model = CueTableModel(project)
    delegate = CueReadingDelegate()

    # Initially clean
    assert not model.needs_retranslate(project.cues[0])
    assert not model.needs_retranslate(project.cues[1])

    # Edit original text of c1 -> triggers needs_update only for c1
    project.cues[0].text = "페이몬, 저기 전설의 보물 상자가 있어!"
    assert st.cue_status(project, "c1") == st.NEEDS_UPDATE
    assert model.needs_retranslate(project.cues[0]) is True
    assert model.data(model.index(0, 3), CueTableModel.NeedsRetranslateRole) is True
    assert model.needs_retranslate(project.cues[1]) is False

    # Delegate paints cleanly with the 「重翻此句」 pill and emits retranslate_requested on click
    option = QStyleOptionViewItem()
    option.font = QFont()
    option.rect = QRect(0, 0, 360, CueReadingDelegate.row_height(option.font, bilingual=True))
    option.state = QStyle.StateFlag.State_Selected
    canvas = QImage(360, option.rect.height(), QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(0)
    painter = QPainter(canvas)
    delegate.paint(painter, option, model.index(0, 3))
    painter.end()

    btn_rect = delegate._retranslate_rect(option, model, 0)
    assert btn_rect.isValid() and btn_rect.width() >= 48
    assert delegate.hit_action_button(option, model, 0, btn_rect.center()) == "retranslate"

    emitted: list[str] = []
    delegate.retranslate_requested.connect(emitted.append)
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        btn_rect.center(),
        btn_rect.center(),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert delegate.editorEvent(release, model, option, model.index(0, 3)) is True
    assert emitted == ["c1"]

    # Explicit status=='needs_update' in record is also honored
    project.generation_metadata["translation_records"]["records"]["c2"]["status"] = st.NEEDS_UPDATE
    assert cue_translation_needs_update(project, project.cues[1]) is True

    # Legacy project without translation_records also detects edit via original_text fallback
    legacy = _bilingual_project(with_records=False)
    assert cue_translation_needs_update(legacy, legacy.cues[0]) is False
    legacy.cues[0].text = "페이몬, 저기 새로운 상자가 있어!"
    assert cue_translation_needs_update(legacy, legacy.cues[0]) is True


def test_single_cue_retranslate_updates_only_target_and_supports_undo_redo():
    project = _bilingual_project(with_records=True)
    # Modify c1 original so it enters needs_update
    project.cues[0].text = "페이몬, 저기 전설의 보물 상자가 있어!"
    assert cue_translation_needs_update(project, project.cues[0]) is True

    undo_stack = QUndoStack()
    save_state = QLabel()
    model = CueTableModel(project)
    page = SimpleNamespace(
        project=project,
        undo_stack=undo_stack,
        save_state=save_state,
        cue_model=model,
        session=SimpleNamespace(generation=1),
    )
    provider = _MockProvider({"c1": "派蒙，那边有个传说中的宝箱！"})

    ok = translate_selected(page, cue_id="c1", provider=provider, sync=True)
    assert ok is True
    # Only c1 was sent to the translator; c2/c3 untouched
    assert provider.requested_ids == [["c1"]]
    assert project.generation_metadata["translations"]["c1"] == "派蒙，那边有个传说中的宝箱！"
    assert project.generation_metadata["translations"]["c2"] == "真的耶？快去打开看看吧！"
    assert project.generation_metadata["translations"]["c3"] == "等一下，可能是陷阱，小心点。"
    # Dirty state is cleared
    assert st.cue_status(project, "c1") == st.DONE
    assert cue_translation_needs_update(project, project.cues[0]) is False
    assert "撤销" in save_state.text()

    # Ctrl+Z (QUndoStack.undo) restores exact previous translation AND needs_update state
    assert undo_stack.count() == 1
    undo_stack.undo()
    assert project.generation_metadata["translations"]["c1"] == "派蒙，那边有个宝箱！"
    assert st.cue_status(project, "c1") == st.NEEDS_UPDATE
    assert cue_translation_needs_update(project, project.cues[0]) is True

    # Redo cleanly reapplies
    undo_stack.redo()
    assert project.generation_metadata["translations"]["c1"] == "派蒙，那边有个传说中的宝箱！"
    assert cue_translation_needs_update(project, project.cues[0]) is False

    save_state.deleteLater()


def test_single_cue_retranslate_async_thread_commits_on_ui_thread():
    project = _bilingual_project(with_records=True)
    project.cues[1].text = "진짜네? 지금 당장 열어보자!"
    undo_stack = QUndoStack()
    save_state = QLabel()
    model = CueTableModel(project)
    page = SimpleNamespace(
        project=project,
        undo_stack=undo_stack,
        save_state=save_state,
        cue_model=model,
        session=SimpleNamespace(generation=1),
    )
    provider = _MockProvider({"c2": "真的耶？现在立刻打开看看吧！"})

    started = translate_selected(page, cue_id="c2", provider=provider, sync=False)
    assert started is True

    # Pump Qt events until the background worker delivers its signal to the main thread
    for _ in range(80):
        APP.processEvents()
        if project.generation_metadata["translations"]["c2"] == "真的耶？现在立刻打开看看吧！":
            break
        QTest.qWait(15)

    assert project.generation_metadata["translations"]["c2"] == "真的耶？现在立刻打开看看吧！"
    assert cue_translation_needs_update(project, project.cues[1]) is False
    assert undo_stack.count() == 1
    undo_stack.undo()
    assert project.generation_metadata["translations"]["c2"] == "真的耶？快去打开看看吧！"
    assert cue_translation_needs_update(project, project.cues[1]) is True

    save_state.deleteLater()


def test_single_cue_retranslate_missing_api_key_shows_calm_status_without_modifying_source(monkeypatch):
    from twobyteasr.caption_design import studio_ai
    from twobyteasr.providers import llm_config

    project = _bilingual_project(with_records=True)
    project.cues[0].text = "페이몬, 여기 숨겨진 보물 상자가 있어!"
    original_before = project.cues[0].text
    translation_before = project.generation_metadata["translations"]["c1"]

    monkeypatch.setattr(studio_ai.GLOBAL_PROVIDER_REGISTRY, "settings", lambda: {"polish": {}})
    monkeypatch.setattr(llm_config, "text_ai_key_missing", lambda _settings, _stage="polish": True)

    undo_stack = QUndoStack()
    save_state = QLabel()
    page = SimpleNamespace(
        project=project,
        undo_stack=undo_stack,
        save_state=save_state,
        cue_model=CueTableModel(project),
        session=SimpleNamespace(generation=1),
    )

    ok = translate_selected(page, cue_id="c1")
    assert ok is False
    assert "API Key" in save_state.text() or "设置" in save_state.text()
    assert project.cues[0].text == original_before
    assert project.generation_metadata["translations"]["c1"] == translation_before
    assert undo_stack.count() == 0

    save_state.deleteLater()


def test_context_menu_exposes_edit_original_edit_translation_and_retranslate():
    project = _bilingual_project(with_records=True)
    opened: list[tuple[str, str]] = []
    page = SimpleNamespace(
        project=project,
        cue_model=CueTableModel(project),
        _open_caption_editor=lambda cid, layer: opened.append((cid, layer)),
    )
    menu = QMenu()
    build_cue_list_menu(page, menu, "c1")
    texts = [action.text() for action in menu.actions() if not action.isSeparator()]
    assert "编辑译文" in texts
    assert "编辑原文" in texts
    assert "重翻此句" in texts
    retranslate_action = next(action for action in menu.actions() if action.text() == "重翻此句")
    assert "Ctrl+Z" in retranslate_action.toolTip()

    edit_orig = next(action for action in menu.actions() if action.text() == "编辑原文")
    edit_orig.trigger()
    edit_trans = next(action for action in menu.actions() if action.text() == "编辑译文")
    edit_trans.trigger()
    assert opened == [("c1", "original"), ("c1", "translation")]
    menu.deleteLater()


def test_real_studio_page_opens_bilingual_default_and_supports_dual_line_editing(tmp_path, monkeypatch):
    from tests.test_review_replay_and_window_bounds import _page

    monkeypatch.setenv("2BYTEASR_USER_DATA_ROOT", str(tmp_path / "user_data"))
    cues = [
        StudioCue("c1", 0, 2200, "페이몬, 저기 보물 상자가 있어!", speaker_id="S01"),
        StudioCue("c2", 2400, 4800, "진짜네? 빨리 열어보자!", speaker_id="S02"),
    ]
    app, page = _page(tmp_path, monkeypatch, cues)
    try:
        # Install translations and reload into cue_model as a bilingual project
        page.project.generation_metadata["language"] = "ko"
        page.project.generation_metadata["translations"] = {
            "c1": "派蒙，那边有个宝箱！",
            "c2": "真的耶？快去打开看看吧！",
        }
        st.migrate(page.project)
        page.cue_model.set_project(page.project)
        page._set_cue_list_view("reading", remember=False)
        sync_cue_list_layer_controls(page)
        page.resize(1360, 820)
        page.show()
        app.processEvents()

        # Default bilingual dual-line mode active & switcher visible
        assert page.cue_model.text_layer == "bilingual"
        assert page.cue_model.bilingual_cards is True
        assert not page.cue_layer_track.isHidden()

        # Clicking a row in bilingual mode preserves bilingual mode (no accidental collapse)
        page.select_cue("c1")
        app.processEvents()
        assert page.cue_model.text_layer == "bilingual"

        # Editing original text through cue_controller marks c1 as needs_update
        assert page.cue_controller.set_text("c1", "페이몬, 저기 황금 보물 상자가 있어!") is True
        assert page.cue_model.needs_retranslate(page.project.cues[0]) is True
        assert page.cue_model.needs_retranslate(page.project.cues[1]) is False

        # Double-clicking primary line opens translation editor; double-clicking secondary line opens original editor
        QTest.qWait(250)
        idx = page.cue_model.index(0, 3)
        page.cue_table.scrollTo(idx)
        app.processEvents()
        rect = page.cue_table.visualRect(idx)
        assert rect.isValid() and rect.height() == CueReadingDelegate.row_height(page.cue_table.font(), bilingual=True)
        option = QStyleOptionViewItem()
        option.rect = rect
        option.font = page.cue_table.font()
        layout = page.cue_reading_delegate._bilingual_layout(option, page.cue_model, page.project.cues[0])

        primary_pt = QPointF(rect.left() + 40, layout["primary_top"] + 4).toPoint()
        QTest.mouseClick(page.cue_table.viewport(), Qt.MouseButton.LeftButton, pos=primary_pt)
        QTest.mouseDClick(page.cue_table.viewport(), Qt.MouseButton.LeftButton, pos=primary_pt)
        QTest.qWait(80)
        assert getattr(page, "_caption_draft", None) is not None
        assert page._caption_draft.target.layer == "translation"
        QTest.mouseClick(page.caption_cancel_button, Qt.MouseButton.LeftButton)
        QTest.qWait(80)

        secondary_pt = QPointF(rect.left() + 40, layout["secondary_top"] + 4).toPoint()
        QTest.mouseClick(page.cue_table.viewport(), Qt.MouseButton.LeftButton, pos=secondary_pt)
        QTest.mouseDClick(page.cue_table.viewport(), Qt.MouseButton.LeftButton, pos=secondary_pt)
        QTest.qWait(80)
        assert getattr(page, "_caption_draft", None) is not None
        assert page._caption_draft.target.layer == "original"
        QTest.mouseClick(page.caption_cancel_button, Qt.MouseButton.LeftButton)
        QTest.qWait(80)

        # Pressing Enter on a bilingual card directly edits translation
        page.cue_table.setCurrentIndex(idx)
        page.cue_table.setFocus()
        app.processEvents()
        QTest.keyClick(page.cue_table, Qt.Key.Key_Return)
        QTest.qWait(80)
        assert getattr(page, "_caption_draft", None) is not None
        assert page._caption_draft.target.layer == "translation"
        QTest.mouseClick(page.caption_cancel_button, Qt.MouseButton.LeftButton)
        QTest.qWait(80)
    finally:
        page.close_page()
        page.deleteLater()
        app.processEvents()
