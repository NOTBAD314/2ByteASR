"""2026-11-03 term library card wall (plan 2026-11-03-glossary-card-wall).

One table model row is one card; a plain click on a confirmed card opens the
edit box on that card, Ctrl+click selects (the selection bar floats over the
cards), the painted 收下 button confirms a reference, the status segment drives
the old status filter and the first-use strip is remembered once dismissed.
"""
import os
from collections import Counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QItemSelectionModel, QModelIndex, QPoint, Qt
from PySide6.QtGui import QHelpEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QStyleOptionViewItem, QToolTip, QWidget

import subtitle_core as legacy
from twobyteasr.glossary import glossary_hub as hub
from twobyteasr.glossary.glossary_term_cards import TermCardView, card_parts, category_colors
from twobyteasr.glossary.main_ui_glossary import TermLibraryDialog, _TermMappingsModel

APP = QApplication.instance() or QApplication([])


class Owner(QWidget):
    def __init__(self):
        super().__init__()
        self.legacy = legacy
        self.game_box = QComboBox()
        self.game_box.setEditable(True)
        self.terms = QCheckBox()
        self.term_hint = QLabel()

    def _enabled_glossary_ids(self):
        return list(legacy.RUNTIME_SETTINGS.setdefault("glossary", {}).get("enabled_glossary_ids", []))

    def _save_glossary_settings(self):
        pass

    def _refresh_content_choices(self):
        pass


@pytest.fixture
def page(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, "LEARNED_TERMS_PATH", str(tmp_path / "2ByteASR" / "terms.json"))
    monkeypatch.setattr(legacy, "load_game_profiles", lambda: {})
    monkeypatch.setattr(legacy, "save_runtime_game_history", lambda _name: None, raising=False)
    monkeypatch.setattr(legacy, "RUNTIME_SETTINGS", {"glossary": {}})
    monkeypatch.setattr(hub, "fetch_catalog", lambda **_kwargs: (_ for _ in ()).throw(hub.HubError("offline")))
    owner = Owner()
    owner.resize(1300, 920)
    dialog = TermLibraryDialog(owner, page_mode=True)
    dialog.setGeometry(0, 0, 1280, 900)
    owner.show()
    dialog.show()
    owner.activateWindow()
    APP.processEvents()
    dialog.sidebar_new_button.click()
    dialog.game_input.setText("洛克王国：世界")
    dialog.add_game_button.click()
    APP.processEvents()
    key = dialog._library_key()
    for source, target, category in (("倾泻", "倾泻", "技能"), ("倾斜", "倾泻", "技能"), ("迪莫", "迪莫", "角色"),
                                     ("冰点", "冰点", "技能"), ("火花", "火花", "角色"), ("星辰岛", "星辰岛", "地点")):
        legacy.add_learned_mapping(key, source, target, category=category)
    dialog._notify_library_changed()
    dialog.refresh_current_game()
    APP.processEvents()
    yield dialog
    if dialog._task_manager:
        dialog._task_manager.shutdown(wait_ms=300)
    dialog.close()
    owner.close()


def _row_index(page, source, target):
    for row in range(page._term_model.rowCount()):
        data = page._term_model.data_for_row(row)
        if data.get("source") == source and data.get("target") == target:
            return page._term_model.index(row, 0)
    raise AssertionError((source, target))


def test_card_parts_describe_mapping_alias_and_reference_rows():
    mapping = card_parts({"status": "confirmed", "source": "倾斜", "target": "倾泻", "category": "技能"})
    assert (mapping["word"], mapping["label"], mapping["chips"], mapping["action"]) == ("倾泻", "听成", ["倾斜"], "")
    plain = card_parts({"status": "confirmed", "source": "迪莫", "target": "迪莫"})
    assert plain["chips"] == [] and plain["note"] == ""
    reference = card_parts({"status": "reference", "source": "火神", "target": "火神",
                            "reference": {"aliases": ["火神", "伙神"]}})
    assert (reference["label"], reference["chips"], reference["action"]) == ("", [], "收下")
    assert card_parts({"status": "hidden", "source": "冷点", "target": "冷点"})["action"] == "恢复"


def test_category_colors_are_stable_and_neutral_for_other():
    first = [color.name() for color in category_colors("技能")]
    assert first == [color.name() for color in category_colors("技能")]
    assert first != [color.name() for color in category_colors("角色")]
    from twobyteasr.glossary.glossary_term_cards import _theme
    fill, ink, dot = category_colors("其他")
    assert (ink.name(), dot.name()) == (_theme().text_secondary.lower(), _theme().text_muted.lower())
    assert category_colors("一个新分类")[2].isValid()


def test_cards_wrap_into_several_columns_without_row_widgets(page):
    assert isinstance(page.listing, TermCardView)
    assert page.listing.columns() >= 4
    assert page._term_model.rowCount() == 5  # 倾泻 and 倾斜 → 倾泻 share one card
    assert all(page.listing.indexWidget(page._term_model.index(row, 0)) is None
               for row in range(page._term_model.rowCount()))
    first, second = (page.listing.visualRect(page._term_model.index(row, 0)) for row in (0, 1))
    assert first.top() == second.top() and second.left() > first.right()


def test_fixed_height_cards_fill_the_width_and_scroll(page):
    """2026-11-13 (plan 2026-11-13-glossary-library-redesign-c): cards keep one
    compact height instead of stretching to a quarter of the viewport; the
    width decides the columns (at most eight)."""
    from twobyteasr.glossary.glossary_term_cards import TermCardDelegate
    view = page.listing
    original = page._term_model.data_for_row(0)
    rows = [dict(original, target=f"词条{i}") for i in range(90)]
    page._term_model.set_data(rows)
    for width, height in ((1280, 900), (1680, 1080), (1440, 960)):
        page.resize(width, height)
        QTest.qWait(30)
        margins = view.viewportMargins()
        budget = view.contentsRect().width() - margins.left() - margins.right() - view.verticalScrollBar().sizeHint().width() - 1
        columns = max(1, min(view.COLUMNS, budget // (view.MIN_CARD_WIDTH + view.GAP)))
        assert view.columns() == columns and columns >= 4
        rects = [view.visualRect(page._term_model.index(i, 0)) for i in range(columns * 2)]
        assert len({r.size().toTuple() for r in rects}) == 1
        assert rects[0].height() == TermCardDelegate.CARD_HEIGHT
        assert len({r.left() for r in rects[:columns]}) == columns
        assert rects[columns].top() - rects[0].bottom() <= view.GAP + 2
        assert view.viewport().width() - rects[columns - 1].right() <= view.GAP + 6
        assert view.verticalScrollBar().maximum() > 0
    view.set_translation_line(True)
    QTest.qWait(30)
    assert view.visualRect(page._term_model.index(0, 0)).height() == TermCardDelegate.TRANSLATION_HEIGHT
    view.set_translation_line(False)
    QTest.qWait(30)
    view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
    APP.processEvents()
    assert view.viewport().rect().contains(view.visualRect(page._term_model.index(89, 0)))
    # Removing the scroll bar after filtering must recompute actual widths.
    page._term_model.set_data(rows[:3])
    QTest.qWait(30)
    assert not view.verticalScrollBar().isVisible()
    margins = view.viewportMargins()
    budget = view.contentsRect().width() - margins.left() - margins.right() - view.verticalScrollBar().sizeHint().width() - 1
    assert view.gridSize().width() == budget // view.columns()


def test_filtered_cards_settle_at_scrollbar_boundary(page, monkeypatch):
    monkeypatch.setattr(page.listing, '_diagnostics', Counter())
    rows = [dict(target=f'鸣{i}', source=f'鸣{i}', status='confirmed') for i in range(16)]
    page._term_model.set_data(rows)
    page.resize(980, 650)
    QTest.qWait(150)
    before = page.listing.layout_diagnostics()
    QTest.qWait(350)
    assert page.listing.layout_diagnostics() == before
    assert page.listing.columns() >= 3


def test_unchanged_refresh_keeps_model_selection_scroll_and_search_cursor(page):
    page.search.setText('角色')
    page.search.setFocus()
    page.search.setCursorPosition(1)
    QTest.qWait(50)
    resets = []
    page._term_model.modelReset.connect(lambda: resets.append(True))
    first = page._term_model.index(0, 0)
    page.listing.selectionModel().select(first, QItemSelectionModel.SelectionFlag.Select)
    for _ in range(5):
        page.apply_filter()
        page.refresh_current_game()
    assert resets == []
    assert page.search.hasFocus() and page.search.cursorPosition() == 1
    assert page.listing.selectionModel().selectedIndexes()


def test_model_same_rows_skip_reset_but_changed_payload_updates(page):
    from copy import deepcopy
    rows = deepcopy(page._term_model._rows)
    resets, updates = [], []
    page._term_model.modelReset.connect(lambda: resets.append(True))
    page._term_model.dataChanged.connect(lambda *args: updates.append(True))
    assert not page._term_model.set_data(rows)
    rows[0]['category'] = '新分类'
    assert page._term_model.set_data(rows)
    assert updates == [True] and not resets
    rows[0]['category'] = '再次修改'
    assert page._term_model.data_for_row(0)['category'] == '新分类'
    assert page._term_model.set_data(rows)


def test_refresh_during_result_application_keeps_latest_query(page):
    changed = []
    def newer_query():
        if not changed:
            changed.append(True)
            page.search.setText('迪莫')
    page._term_model.modelReset.connect(newer_query)
    page.search.setText('冰点')
    QTest.qWait(50)
    assert page.search.text() == '迪莫'
    assert [row['target'] for row in page._term_model._rows] == ['迪莫']


@pytest.mark.parametrize('width,count', [(640, 16), (670, 16), (690, 24), (690, 25), (720, 674)])
def test_grid_converges_across_column_and_scrollbar_boundaries(width, count):
    view = TermCardView()
    view._diagnostics = Counter()
    model = _TermMappingsModel(view)
    view.setModel(model)
    model.set_data([dict(source=str(i), target=str(i)) for i in range(count)])
    view.resize(width, 310)
    view.show()
    QTest.qWait(100)
    before = view.layout_diagnostics()
    QTest.qWait(200)
    assert view.layout_diagnostics() == before
    assert view.columns() in (3, 4)
    view.close()


def test_data_changed_in_place_rebuilds_same_query(page):
    page.search.setText('新名字')
    assert page._term_model.rowCount() == 0
    page.state['mappings'][0]['to'] = '新名字'
    page.refresh_learned()
    assert page._term_model.rowCount() == 1


def test_card_slots_stay_inside_uniform_geometry_for_long_content(page):
    delegate = page.listing.card_delegate
    row = {"status": "confirmed", "target": "长词条" * 40, "heard": ["误识别" * 30] * 30}
    parts = card_parts(row)
    from PySide6.QtCore import QRect
    for width, height in ((100, 74), (120, 90), (132, 108), (180, 128), (280, 180)):
        rect = QRect(0, 0, width, height)
        header, word, footer = delegate.content_rects(rect, parts)
        assert all(rect.contains(slot) for slot in (header, word, footer))
        assert header.bottom() < word.top() and word.bottom() < footer.top()


def test_card_text_keeps_readable_fixed_sizes_and_translation_line(page):
    """Wider cells do not inflate the text (the old cards grew with the cell)."""
    from PySide6.QtCore import QRect
    delegate = page.listing.card_delegate
    small, large = QRect(0, 0, 170, 62), QRect(0, 0, 320, 62)
    assert [delegate.metrics(r).px(15) for r in (small, large)] == [15, 15]
    parts = card_parts({"status": "reference", "target": "参考词"})
    assert [slot.height() for slot in delegate.content_rects(small, parts)][::2] == \
        [slot.height() for slot in delegate.content_rects(large, parts)][::2]
    page._term_model.set_data([{"status": "reference", "target": "参考词"}])
    index = page._term_model.index(0, 0)
    assert delegate.button_rect(small, index).size() == delegate.button_rect(large, index).size()
    translated = card_parts({"status": "confirmed", "target": "玳龟", "translation_code": "EN",
                             "translation": "Daigui", "translation_state": "pending", "heard": ["带龟"]})
    assert (translated["translation"], translated["translation_state"], translated["chips"]) == ("Daigui", "pending", ["带龟"])
    top, middle, bottom = delegate.content_rects(QRect(0, 0, 200, 84), translated)
    assert top.bottom() < middle.top() and middle.bottom() < bottom.top() and middle.height() > 10


def test_hover_contains_full_word_category_and_every_heard_spelling(page):
    word = '<超长词条&完整名称>' * 6
    heard = [f"误识别词{i}" for i in range(30)]
    page._term_model.set_data([{"target": word, "heard": heard, "category": "角色", "status": "confirmed"}])
    APP.processEvents()
    index = page._term_model.index(0, 0)
    event = QHelpEvent(QEvent.Type.ToolTip, QPoint(20, 20), page.listing.viewport().mapToGlobal(QPoint(20, 20)))
    assert page.listing.card_delegate.helpEvent(event, page.listing, QStyleOptionViewItem(), index)
    from html import escape
    assert escape(word) in QToolTip.text()
    assert "角色" in QToolTip.text() and all(text in QToolTip.text() for text in heard)
    QToolTip.hideText()


def test_one_card_per_correct_spelling_lists_every_heard_spelling(page):
    key = page._library_key()
    legacy.add_learned_mapping(key, "清线", "倾泻", category="技能")
    page._notify_library_changed()
    page.refresh_current_game()
    card = page._term_model.data_for_row(_row_index(page, "倾泻", "倾泻").row())
    assert card["heard"] == ["倾斜", "清线"] and len(card["members"]) == 3
    assert card_parts(card)["chips"] == ["倾斜", "清线"]
    assert sum(page._term_model.data_for_row(r)["target"] == "倾泻" for r in range(page._term_model.rowCount())) == 1
    # selecting the card and deleting removes every mapping of that term
    page.listing.selectionModel().select(_row_index(page, "倾泻", "倾泻"),
                                         __import__("PySide6.QtCore", fromlist=["QItemSelectionModel"]).QItemSelectionModel.SelectionFlag.Select
                                         | __import__("PySide6.QtCore", fromlist=["QItemSelectionModel"]).QItemSelectionModel.SelectionFlag.Rows)
    page.remove_selected_terms()
    assert not [row for row in legacy.learned_mappings_for_game(key) if row["to"] == "倾泻"]


def test_card_edit_renames_and_rewrites_heard_spellings_together(page):
    key = page._library_key()
    legacy.add_learned_mapping(key, "清线", "倾泻", category="技能")
    page._notify_library_changed()
    page.refresh_current_game()
    page.listing.edit_requested.emit(_row_index(page, "倾泻", "倾泻"))
    assert page.edit_alias.text() == "倾斜、清线"
    page.edit_canonical.setText("倾泄")
    page.edit_alias.setText("清线、青谢")
    page.edit_save_button.click()
    APP.processEvents()
    stored = {(row["from"], row["to"]) for row in legacy.learned_mappings_for_game(key)}
    assert {("倾泄", "倾泄"), ("清线", "倾泄"), ("青谢", "倾泄")} <= stored
    assert not {pair for pair in stored if pair[1] == "倾泻"} and ("倾斜", "倾泄") not in stored
    assert all(row["category"] == "技能" for row in legacy.learned_mappings_for_game(key) if row["to"] == "倾泄")


def test_plain_click_edits_in_place_without_selecting(page):
    index = _row_index(page, "倾泻", "倾泻")
    rect = page.listing.visualRect(index)
    QTest.mouseClick(page.listing.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect.center())
    APP.processEvents()
    sheet = page._edit_sheet
    assert sheet is not None and sheet.isVisible()
    assert not page.listing.selectionModel().hasSelection() and not page.selection_bar.isVisibleTo(page)
    top_left = page.listing.viewport().mapTo(page, rect.topLeft())
    assert sheet.geometry().contains(top_left) or abs(sheet.y() - top_left.y()) <= 2
    assert page.edit_canonical.text() == "倾泻" and page.edit_alias.text() == "倾斜"
    page.edit_canonical.setText("倾泻")
    page.edit_alias.setText("清线")
    QTest.keyClick(page.edit_alias, Qt.Key.Key_Return)
    APP.processEvents()
    assert page._edit_sheet is None
    stored = {(row["from"], row["to"]) for row in legacy.learned_mappings_for_game(page._library_key())}
    assert ("清线", "倾泻") in stored and ("倾斜", "倾泻") not in stored


def test_escape_and_outside_press_close_the_edit_box(page, monkeypatch):
    index = _row_index(page, "迪莫", "迪莫")
    page.listing.edit_requested.emit(index)
    assert page._edit_sheet is not None
    QTest.keyClick(page.edit_canonical, Qt.Key.Key_Escape)
    APP.processEvents()
    assert page._edit_sheet is None
    page.listing.edit_requested.emit(index)
    monkeypatch.setattr(QApplication, "doubleClickInterval", staticmethod(lambda: 0))
    page._edit_dim.pressed.emit()
    APP.processEvents()
    assert page._edit_sheet is None


def test_ctrl_click_selects_and_the_bar_floats_over_the_cards(page):
    before = page.listing.geometry()
    for source, target in (("迪莫", "迪莫"), ("冰点", "冰点")):
        rect = page.listing.visualRect(_row_index(page, source, target))
        QTest.mouseClick(page.listing.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, rect.center())
    APP.processEvents()
    assert page.selection_bar.isVisibleTo(page) and "2" in page.selection_label.text()
    assert page.selection_bar.parentWidget() is page.listing
    assert page.listing.geometry() == before
    assert page._edit_sheet is None if hasattr(page, "_edit_sheet") else True


def test_painted_keep_button_confirms_a_reference(page, monkeypatch):
    rows = page._unified_term_rows()
    rows.append({"term_text": "火神", "category": "角色", "origin_labels": ["内置参考"], "status": "reference",
                 "raw": None, "source": "火神", "target": "火神", "reference": {"name": "火神", "category": "角色"}})
    page._term_model.set_data(rows)
    APP.processEvents()
    index = page._term_model.index(len(rows) - 1, 0)
    page.listing.scrollTo(index)
    APP.processEvents()
    button = page.listing.card_delegate.button_rect(page.listing.visualRect(index), index)
    assert button is not None
    added = []
    monkeypatch.setattr(page.legacy, "confirm_reference_terms",
                        lambda game, references: added.extend(references) or 1)
    monkeypatch.setattr(page, "refresh_current_game", lambda: None)
    QTest.mouseClick(page.listing.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, button.center())
    APP.processEvents()
    assert added and added[0]['name'] == '火神' and added[0]['category'] == '角色'
    assert not page.listing.selectionModel().hasSelection()


def test_status_segment_drives_the_status_filter(page):
    page.status_buttons["confirmed"].click()
    assert page.filter_status.currentData() == "confirmed"
    page.filter_status.setCurrentIndex(page.filter_status.findData("hidden"))
    assert page.status_buttons["hidden"].isChecked()
    assert page._term_model.rowCount() == 0
    page.status_buttons[""].click()
    assert page._term_model.rowCount() == 5
    assert page.status_buttons["confirmed"].text().endswith("5")


def test_search_matches_category_names(page):
    page.search.setText("角色")
    APP.processEvents()
    assert {page._term_model.data_for_row(row)["target"] for row in range(page._term_model.rowCount())} == {"迪莫", "火花"}


def test_add_row_reads_correct_spelling_first(page):
    page.term_editor.setFocus()
    QTest.keyClick(page.term_editor, Qt.Key.Key_Tab)
    assert page.term_alias_editor.hasFocus()
    page.term_editor.setText("圣羽翼王")
    page.term_alias_editor.setText("圣雨翼王")
    page.add_term_button.click()
    stored = {(row["from"], row["to"]) for row in legacy.learned_mappings_for_game(page._library_key())}
    assert {("圣羽翼王", "圣羽翼王"), ("圣雨翼王", "圣羽翼王")} <= stored


def test_first_use_strip_is_remembered(page):
    assert page.term_guide.isVisibleTo(page)
    page.term_guide_close.click()
    assert not page.term_guide.isVisibleTo(page)
    assert hub.term_guide_done(legacy=page.legacy)
    page.refresh_current_game()
    assert not page.term_guide.isVisibleTo(page)
    hub.mark_share_prompt_done("lib-x", legacy=page.legacy)
    assert hub.term_guide_done(legacy=page.legacy) and hub.share_prompt_done("lib-x", legacy=page.legacy)


def test_batch_switch_sits_in_the_title_row_and_marks_the_library_in_use(page):
    assert page.use_game.parentWidget() is page.selected_title.parentWidget()
    page.use_game.click()
    item = page.game_list.currentItem()
    row = page.game_list.itemWidget(item)
    assert row.in_use_label.isVisibleTo(row)
    page.use_game.click()
    assert not row.in_use_label.isVisibleTo(row)


def test_name_keeps_priority_over_the_category_tag():
    """2026-11-13 (user): names like 彩虹独角兽 and tags like game_term were cut
    off. The tag stays on the name's line only when both fit whole; otherwise
    it moves to the line with room, and a long name shrinks before eliding."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QFontMetrics, QStandardItem, QStandardItemModel
    from twobyteasr.glossary.glossary_term_cards import TermCardDelegate

    class Model(QStandardItemModel):
        def __init__(self, rows):
            super().__init__()
            self.rows = rows
            for _row in rows:
                self.appendRow(QStandardItem())

        def data_for_row(self, row):
            return self.rows[row]

    rows = [dict(target="倾泻", category="game_term", status="confirmed", translation_code="EN",
                 translation_state="missing"),
            dict(target="彩虹独角兽", category="game_term", status="confirmed", translation_code="EN",
                 translation_state="missing", heard=["抽之", "抽支"]),
            dict(target="彩虹独角兽", category="game_term", status="confirmed", heard=["抽之", "抽支"])]
    model = Model(rows)
    delegate = TermCardDelegate(None)
    font = APP.font()
    wide = QRect(0, 0, 400, TermCardDelegate.TRANSLATION_HEIGHT)
    short = delegate.category_rect(wide, model.index(0, 0), font)
    assert delegate.tag_on_top(wide, card_parts(rows[0]), font)
    assert delegate.content_rects(wide, card_parts(rows[0]))[0].contains(short)
    assert short.width() == delegate._tag_width(font, card_parts(rows[0]))
    card = QRect(0, 0, 170, TermCardDelegate.TRANSLATION_HEIGHT)
    top, middle, bottom = delegate.content_rects(card, card_parts(rows[1]))
    long = delegate.category_rect(card, model.index(1, 0), font)
    assert not delegate.tag_on_top(card, card_parts(rows[1]), font) and middle.contains(long.center())
    assert long.width() == min(delegate._tag_width(font, card_parts(rows[1])), (middle.right() - middle.x()) * 2 // 3)
    plain = QRect(0, 0, 170, TermCardDelegate.CARD_HEIGHT)
    moved = delegate.category_rect(plain, model.index(2, 0), font)
    assert delegate.content_rects(plain, card_parts(rows[2]))[2].contains(moved.center())
    word = delegate.word_font(font, 60, "彩虹独角兽长名字")
    assert word.pixelSize() == TermCardDelegate.WORD_SIZES[-1]
    assert delegate.word_font(font, 400, "倾泻").pixelSize() == TermCardDelegate.WORD_SIZES[0]
    assert QFontMetrics(delegate.word_font(font, 146, "彩虹独角兽")).horizontalAdvance("彩虹独角兽") <= 146
