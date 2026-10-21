from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionViewItem,
    QTableView,
    QTableWidget,
    QWidget,
)

from twobyteasr.app.ui import (  # noqa: E402
    APP_QSS,
    MainWindow,
    ModalHost,
    SmartGlossaryDialog,
    SpringDialog,
    TermLibraryDialog,
    _CategoryPillDelegate,
)
from twobyteasr.glossary.main_ui_glossary import _TermMappingsModel  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def _window():
    import subtitle_core as legacy

    return MainWindow([], legacy, object(), None)


def test_workshop_navigation_has_four_unique_destinations():
    _app()
    win = _window()
    navigation = win.workshop_page.workspace_navigation
    assert [button.text() for button in navigation.buttons.values()] == [
        "返回字幕识别",
        "模型工坊",
        "术语库",
        "识别记录",
    ]
    assert win.workshop_page.ai_segmentation_button.text() == "AI 模型 / 智能断句"
    assert win.workshop_page.task_settings_button.text() == "高级设置 / 任务设置"
    win.close()


def test_header_mascot_is_complete_and_does_not_overlap_wordmark():
    app = _app()
    win = _window()
    win.show()

    rendered_sizes = []
    for height, page in (
        (740, win.settings_scroll),
        (880, win.workshop_page),
        (1000, win.studio_page),
    ):
        win.resize(1320, height)
        win.pages.setCurrentWidget(page)
        app.processEvents()
        mascot_rect = QRect(
            win.header_mascot.mapTo(win.app_header, QPoint(0, 0)),
            win.header_mascot.size(),
        )
        wordmark_rect = QRect(
            win.brand.mapTo(win.app_header, QPoint(0, 0)),
            win.brand.size(),
        )
        assert win.app_header.rect().contains(mascot_rect)
        assert not mascot_rect.intersects(wordmark_rect)
        assert win.header_mascot.pixmap().height() <= win.header_mascot.height()
        assert win.header_mascot.pixmap().width() <= win.header_mascot.width()
        gap = wordmark_rect.left() - mascot_rect.right() - 1
        assert 8 <= gap <= 16
        rendered_sizes.append(win.header_mascot.pixmap().height())

    assert min(rendered_sizes) >= 84
    assert max(rendered_sizes) == min(rendered_sizes)
    win.close()


def test_studio_focus_mode_hides_global_header_and_restores_it_on_exit():
    app = _app()
    win = _window()
    win.show()
    app.processEvents()

    win.pages.setCurrentWidget(win.studio_page)
    app.processEvents()
    assert not win.app_header.isVisible()

    for page in (win.settings_scroll, win.workshop_page, win.history_page, win.term_library_page):
        win.pages.setCurrentWidget(page)
        app.processEvents()
        assert win.app_header.isVisible()
    win.close()


def test_home_role_picker_does_not_navigate_to_workshop(monkeypatch):
    _app()
    win = _window()
    monkeypatch.setattr(SpringDialog, "exec", lambda _self: 0)
    win.pages.setCurrentIndex(0)
    win._open_model_picker("primary")
    assert win.pages.currentIndex() == 0
    assert win.workshop_page.browser_role == "primary"
    win.close()


def test_home_keeps_only_ai_smart_segmentation_tile(monkeypatch):
    _app()
    win = _window()
    assert list(win.setting_tiles) == ["ai"]
    assert win.setting_tiles["ai"].title_label.text() == "AI 智能断句"
    # Isolate from this machine's real key stores (provider-scoped and stage).
    for module in ("twobyteasr.app.ui", "twobyteasr.providers.endpoint_editor_ui"):
        monkeypatch.setattr(f"{module}.resolve_api_key", lambda _stage: ("", "missing"))
        monkeypatch.setattr(f"{module}.read_api_key", lambda *_args, **_kwargs: ("", "missing"))
    win._refresh_ai_summary()
    assert win.setting_tiles["ai"].summary_label.text() == "选择 API 厂商、模型并填写 API Key"
    win.close()


def test_home_recognition_cards_use_tall_window_space_without_moving_action_bar():
    app = _app()
    win = _window()
    win.show()
    win.resize(1320, 740)
    app.processEvents()
    compact_height = win.recognition_plan.cards["primary"].height()

    win.resize(1500, 1000)
    app.processEvents()
    tall_height = win.recognition_plan.cards["primary"].height()

    # Home C′ (2026-10-17): the row takes its size hint between the tier height
    # and +48 px (a wrapped recovery button); taller windows add a little.
    assert win.recognition_plan.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed
    assert all(
        card.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Preferred
        for card in win.recognition_plan.cards.values()
    )
    assert tall_height >= compact_height
    assert win.bottom_bar.isVisible()
    assert not win.settings_scroll.isAncestorOf(win.bottom_bar)
    win.close()


def test_home_content_profile_and_batch_glossary_share_tall_space():
    app = _app()
    win = _window()
    win.show()
    win.resize(1320, 740)
    app.processEvents()

    assert win.content_profile_card.objectName() == "homeContentProfile"
    assert win.batch_glossary_card.objectName() == "homeBatchGlossary"
    compact_profile_height = win.content_profile_card.height()
    compact_glossary_height = win.batch_glossary_card.height()
    assert win.content_profile_card.isAncestorOf(win.batch_glossary_card)
    assert win.batch_glossary_card.x() >= 0
    assert win.batch_glossary_card.y() >= 0

    win._enabled_glossary_ids = lambda: []
    win._refresh_glossary_chips()
    assert win.batch_glossary_status.text() == "术语增强 OFF"
    assert win.add_glossary_button.text() == "管理术语库"

    win._enabled_glossary_ids = lambda: ["genshin", "zzz"]
    win._glossary_display_name = lambda value: {"genshin": "原神", "zzz": "绝区零"}[value]
    win._refresh_glossary_chips()
    assert win.batch_glossary_status.text() == "术语增强 ON\n已绑定：原神、绝区零"
    assert win.add_glossary_button.text() == "管理术语库"

    win.resize(1500, 1000)
    app.processEvents()
    assert win.content_profile_card.height() > compact_profile_height
    assert win.batch_glossary_card.height() >= compact_glossary_height
    win.close()


def test_ai_settings_open_in_a_dialog_and_keep_home_in_place():
    # 2026-10-08 (user): AI segmentation settings open in a dialog with a
    # scrolling form; the home page keeps its scroll position, and Cancel
    # restores every control (previously the form expanded in the page).
    app = _app()
    win = _window()
    win.show()
    win.resize(1320, 740)
    app.processEvents()

    scroll_bar = win.settings_scroll.verticalScrollBar()
    scroll_bar.setValue(min(40, scroll_bar.maximum()))
    before = scroll_bar.value()
    polish_before = win.ai_polish.isChecked()
    QTest.mouseClick(win.ai_settings_button, Qt.MouseButton.LeftButton)
    app.processEvents()

    dialog = win._ai_settings_dialog
    assert dialog is not None and dialog.isVisible()
    assert dialog.isAncestorOf(win.polish_editor)
    assert not win.settings_page_widget.isAncestorOf(win.ai_panel)
    assert scroll_bar.value() == before

    win.ai_polish.setChecked(not polish_before)
    dialog.reject()
    # SpringDialog fades out before it finishes.
    for _ in range(100):
        if win._ai_settings_dialog is None:
            break
        QTest.qWait(20)
    assert win._ai_settings_dialog is None
    assert win.ai_polish.isChecked() == polish_before
    assert not win.ai_panel.isVisible()
    assert scroll_bar.value() == before
    assert win.bottom_bar.isVisible()
    win.close()


def test_history_navigation_reuses_resident_page_without_rescanning_reports():
    _app()
    win = _window()
    calls = []
    win.history_page.refresh = lambda: calls.append("refresh")

    win.pages.setCurrentIndex(0)
    win._open_recognition_history()

    assert win.pages.currentWidget() is win.history_page
    assert calls == []
    win.close()


def test_term_library_uses_structured_table_and_adaptive_category_badges():
    _app()
    win = _window()
    dialog = TermLibraryDialog(win)
    assert isinstance(dialog.listing, QTableView)
    assert not isinstance(dialog.listing, QTableWidget)
    model = dialog.listing.model()
    assert [
        model.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
        for i in range(model.columnCount())
    ] == [
        "术语 / 纠错",
        "分类",
        "来源",
        "状态",
        "操作",
    ]
    # 2026-10-17 redesign v2: categories are plain text; status is a dot and text.
    from twobyteasr.glossary.glossary_page_parts import StatusDotDelegate
    assert not isinstance(dialog.listing.itemDelegateForColumn(1), _CategoryPillDelegate)
    assert isinstance(dialog.listing.itemDelegateForColumn(3), StatusDotDelegate)
    assert dialog.listing.columnWidth(1) >= 72
    categories = ("其他", "角色", "Boss", "技能", "物品")
    model.set_data(
        [
            {
                "term_text": f"术语 {row}",
                "category": categories[row % len(categories)],
                "origin_labels": ["手动"],
                "status": "reference",
                "actions": ("确认", "隐藏"),
            }
            for row in range(650)
        ]
    )
    assert model.rowCount() == 650
    assert [model.index(row, 1).data() for row in range(5)] == [
        "其他",
        "角色",
        "Boss",
        "技能",
        "物品",
    ]
    assert model.index(0, 2).data() == "手动"
    assert model.index(0, 3).data() == "参考"
    assert all(
        dialog.listing.indexWidget(model.index(row, column)) is None
        for row in range(model.rowCount())
        for column in range(model.columnCount())
    )
    assert dialog.library_sidebar.objectName() == "termLibrarySidebar"
    assert dialog.library_content.objectName() == "termLibraryContent"
    assert dialog.library_footer.parentWidget() is dialog.library_content
    assert dialog.sidebar_new_button.text() == "新建"
    assert dialog.sidebar_search_button.toolTip() == "搜索我的词库"
    # 2026-10-17 redesign: 「我的词库」/「线上词库」 tabs; the duplicate sync line left the sidebar.
    assert dialog.hub_tab_button.text() == "线上词库"
    assert dialog.page_stack.currentWidget() is dialog.mine_page
    assert dialog.official_stats.text().endswith(("条参考", "references"))
    content_body_layout = dialog.learned_title.parentWidget().layout()
    tools_index = next(
        index
        for index in range(content_body_layout.count())
        if content_body_layout.itemAt(index).layout() is dialog.term_tools_layout
    )
    assert tools_index < content_body_layout.indexOf(dialog.listing)
    # 统一搜索常显 + 分类/状态筛选在表头上方
    assert not dialog.search.isHidden()
    assert dialog.filter_category.count() >= 1
    assert dialog.filter_status.count() == 4
    assert "QTableView#termMappingTable" in APP_QSS
    assert "QTableWidget#termMappingTable" not in APP_QSS
    dialog.close()
    win.close()


def test_term_library_category_delegate_paints_selected_and_hovered_rows():
    _app()
    model = _TermMappingsModel()
    model.set_data(
        [{"term_text": "测试术语", "category": "角色", "origin": "手动"}]
    )
    index = model.index(0, 1)
    delegate = _CategoryPillDelegate()

    for state in (
        QStyle.StateFlag.State_Selected,
        QStyle.StateFlag.State_MouseOver,
    ):
        image = QImage(140, 50, QImage.Format.Format_ARGB32)
        image.fill(0)
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 120, 34)
        option.state = state
        painter = QPainter(image)
        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()


def test_term_reference_picker_filters_selects_and_confirms_without_mutating_reference(monkeypatch):
    _app()
    win = _window()
    dialog = TermLibraryDialog(win)
    dialog.state["game"] = "洛克王国：世界"
    dialog.state["mappings"] = []
    dialog.state["builtin_names"] = ["抓挠", "迪莫", "水球球"]
    dialog.state["loaded"] = [("skill", 1, 1), ("spirit", 2, 2)]
    dialog._builtin_cache["洛克王国：世界"] = (
        list(dialog.state["builtin_names"]), list(dialog.state["loaded"]), []
    )
    dialog._builtin_entry_cache["洛克王国：世界"] = [
        {"name": "抓挠", "category": "技能", "source": "洛克王国 BWIKI", "aliases": [], "hidden": False},
        {"name": "迪莫", "category": "角色", "source": "洛克王国 BWIKI", "aliases": [], "hidden": False},
        {"name": "水球球", "category": "角色", "source": "洛克王国 BWIKI", "aliases": [], "hidden": False},
    ]
    captured = []
    monkeypatch.setattr(
        dialog.legacy,
        "add_learned_mapping",
        lambda game, source, target, **kwargs: captured.append((game, source, target, kwargs)) or True,
    )
    monkeypatch.setattr(dialog, "refresh_current_game", lambda: None)
    monkeypatch.setattr(dialog, "_refresh_game_item_counts", lambda: None)
    monkeypatch.setattr(dialog, "_show_toast", lambda *_args, **_kwargs: None)

    # 统一主列表：内置参考默认展示，不再是折叠区
    dialog.refresh_learned()
    assert dialog._term_model.rowCount() == 3
    statuses = {
        dialog._term_model.data_for_row(row)["source"]: dialog._term_model.index(row, 3).data()
        for row in range(3)
    }
    assert statuses == {"抓挠": "参考", "迪莫": "参考", "水球球": "参考"}

    # 分类筛选：只留"角色"
    dialog.filter_category.setCurrentIndex(dialog.filter_category.findData("角色"))
    assert dialog._term_model.rowCount() == 2
    visible_names = {
        dialog._term_model.data_for_row(row)["source"]
        for row in range(dialog._term_model.rowCount())
    }
    assert visible_names == {"迪莫", "水球球"}

    # 选中并确认参考词条
    dialog.listing.selectAll()
    dialog.confirm_selected_references()
    assert [item[1] for item in captured] == ["迪莫", "水球球"]
    assert all(item[3]["origin"] == "用户确认" for item in captured)
    assert dialog.state["builtin_names"] == ["抓挠", "迪莫", "水球球"]
    dialog.close()
    win.close()


def test_modal_host_uses_stable_direct_painted_backdrop():
    app = _app()
    # A plain widget is sufficient here and avoids constructing application/runtime state.
    parent = QWidget()
    parent.resize(1280, 800)
    parent.show()
    host = ModalHost(parent)
    host.resize_to_parent()
    first = QWidget()
    host.show_content(first, title="测试", size=(760, 560))
    initial_geometry = host.card.geometry()

    assert host.card.isVisible()
    assert host.card.graphicsEffect() is None
    assert host.backdrop.graphicsEffect() is None
    assert not hasattr(host, "_backdrop_animation")
    assert host.card.geometry() == initial_geometry
    assert abs(host.backdrop.alpha - 0.27) < 0.01

    host.hide_content()
    assert host.card.isHidden()
    assert first.parentWidget() is None
    assert host.isHidden()
    assert host.backdrop.isHidden()

    host.show_content(QWidget(), title="第二次", size=(760, 560))
    assert host.isVisible()
    assert host.card.isVisible()
    assert host.title_label.text() == "第二次"

    host.hide_content()
    parent.close()
    app.processEvents()


def test_term_library_is_resident_page_and_batch_picker_remains_modal():
    app = _app()
    win = _window()
    win.show()
    app.processEvents()

    assert win.term_library_page.library is None
    win._manage_terms()
    app.processEvents()
    host = win._modal_host
    dialog = win._term_library_dialog
    table_model = dialog.listing.model()

    assert win.pages.currentWidget() is win.term_library_page
    assert dialog is win.term_library_page.library
    assert dialog.parentWidget() is win.term_library_page
    assert host.isHidden()
    assert dialog.isVisible()

    win._return_to_settings()
    app.processEvents()
    win._manage_terms()
    app.processEvents()

    assert win._term_library_dialog is dialog
    assert win.pages.currentWidget() is win.term_library_page
    assert dialog.parentWidget() is win.term_library_page
    assert dialog.isVisible()
    assert dialog.listing.model() is table_model

    win._return_to_settings()
    win._pick_glossaries()
    app.processEvents()
    glossary_picker = host._current_content
    assert host.body.isVisible()
    assert glossary_picker.isVisible()
    assert host.body_lay.count() == 1
    assert host.body_lay.itemAt(0).widget() is glossary_picker

    host._request_close()
    win.close()
    app.processEvents()


def test_repeated_term_library_navigation_reuses_page_and_table_model():
    app = _app()
    win = _window()
    win.show()
    app.processEvents()
    host = win._modal_host

    win._manage_terms()
    app.processEvents()
    dialog = win._term_library_dialog
    table_model = dialog.listing.model()
    for _ in range(20):
        win._return_to_settings()
        win._manage_terms()
        app.processEvents()
        assert win.pages.currentWidget() is win.term_library_page
        assert win._term_library_dialog is dialog
        assert dialog.listing.model() is table_model
        assert host.isHidden()

    win._return_to_settings()
    win._open_model_picker("primary")
    app.processEvents()
    assert host._current_content is win._model_picker_primary_panel
    assert host.body_lay.itemAt(0).widget() is win._model_picker_primary_panel
    host._request_close()

    win._manage_terms()
    app.processEvents()
    assert win.pages.currentWidget() is win.term_library_page
    assert win._term_library_dialog.isVisible()
    assert host.isHidden()

    win.close()
    app.processEvents()


def test_smart_glossary_close_does_not_hide_shared_modal_body():
    app = _app()
    win = _window()
    win.show()
    app.processEvents()
    host = win._modal_host
    dialog = SmartGlossaryDialog(win, "我的世界", host.body)

    host.show_content(dialog, title="智能建词", size=(980, 720))
    app.processEvents()
    assert host.body.isVisible()
    assert dialog.isVisible()

    close_button = next(
        button for button in dialog.findChildren(QPushButton) if button.text() == "关闭"
    )
    close_button.click()
    app.processEvents()
    assert host.isHidden()
    assert not host.body.isHidden()

    win._manage_terms()
    app.processEvents()
    assert win.pages.currentWidget() is win.term_library_page
    assert win._term_library_dialog.isVisible()
    assert host.isHidden()

    win.close()
    app.processEvents()
