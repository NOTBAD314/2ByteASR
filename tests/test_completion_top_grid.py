"""Current completion geometry contract; native screenshots are audited separately."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication, QToolButton, QWidget, QVBoxLayout, QStackedWidget
from twobyteasr.i18n import apply_ui_language
from twobyteasr.app.ui import MainWindow

APP = QApplication.instance() or QApplication([])


def completion_page():
    shell = MainWindow.__new__(MainWindow)
    QWidget.__init__(shell)
    shell._completion_log_generation = 0
    page = shell._result_page()
    shell.result_task_selector.hide()
    shell.result_icon.hide()
    shell.result_summary.setText('识别成功 · 43 条字幕 · 存在待审核项')
    return shell, page


def test_top_alignment_todo_section_and_fold_growth():
    shell, page = completion_page()
    page.resize(1240, 940)
    page.show()
    apply_ui_language(page, 'zh')
    APP.processEvents()
    viewport = page.viewport()
    assert shell.result_summary_card.mapTo(viewport, QPoint()).y() == 28
    assert shell.result_action_grid.columns == 3
    cards = shell.result_action_grid.cards
    assert max(card.width() for card in cards)-min(card.width() for card in cards) <= 1
    # 2026-10-30 (design B): the 52px operation bar sits between the summary and the
    # main actions; 「开始优先审核」 is gone and no supporting row remains.
    assert not hasattr(shell, 'open_priority_review_button')
    assert shell.result_action_grid.secondary_actions == ()
    todo = shell.result_todo
    summary_bottom = shell.result_summary_card.mapTo(viewport, QPoint()).y() + shell.result_summary_card.height()
    assert summary_bottom < todo.mapTo(viewport, QPoint()).y() < cards[0].mapTo(viewport, QPoint()).y()
    assert shell.repolish_current_glossary_button is todo.ai_card.action
    assert todo.ai_card.isVisible() and todo.ai_card.badge.isVisible()
    assert not todo.review_card.isVisible() and not todo.retry_card.isVisible()
    assert todo.height() >= todo.ai_card.height() + 6
    assert shell.result_more_button.parentWidget() is todo
    # Both summaries start open and have the same natural height.
    files, log = shell.result_files_panel, shell.result_log_panel
    assert shell.result_folds.columns == 2 and abs(files.y()-log.y()) <= 1 and files.x() < log.x()
    assert files.mapTo(viewport, QPoint()).y() > cards[0].mapTo(viewport, QPoint()).y()
    assert shell.result_files_toggle.isChecked() and shell.result_log_toggle.isChecked()
    assert files.mode == 'summary' and log.mode == 'summary'
    assert files.height() == log.height()
    before = shell.result_folds.height()
    QTest.mouseClick(shell.result_files_toggle, Qt.MouseButton.LeftButton)
    APP.processEvents()
    assert files.mode == 'collapsed' and log.mode == 'summary'
    assert shell.result_folds.height() == before
    title, arrow = shell.result_more_button.content_rects()
    assert arrow.center().y() == shell.result_more_button.height()/2
    assert title.width() > 0
    page.close(); page.deleteLater(); shell.deleteLater(); APP.processEvents()


def test_preview_fills_viewport_and_absorbs_resize_fold_and_task_changes():
    shell, page = completion_page()
    preview = shell.result_preview
    rows = [('00:01.0', 'S00', '#c9a227', f'字幕 {index}') for index in range(60)]
    preview.set_rows(rows, len(rows))
    shell.result_files_panel.set_summary_lines(['素材', '字幕', '场景', '词库'])
    shell.result_log_panel.set_summary_lines(['完成', '检查', '记录', '提示', '待检查'])
    page.resize(1460, 940); page.show()

    def settle():
        for _ in range(8):
            APP.processEvents()

    def assert_bottom():
        viewport = page.viewport()
        bottom = preview.mapTo(viewport, QPoint()).y() + preview.height()
        assert abs(viewport.height() - bottom - 28) <= 1
        assert preview.list.height() >= 6 * 36
        assert page.verticalScrollBar().maximum() == 0

    settle(); assert_bottom()
    first_height = preview.list.height()
    page.resize(1460, 1300); settle(); assert_bottom()
    assert abs(preview.list.height() - first_height - 360) <= 1
    before = preview.list.height()
    for panel in (shell.result_files_panel, shell.result_log_panel):
        panel.set_mode('collapsed')
    settle(); assert_bottom()
    assert preview.list.height() > before
    preview.set_rows(rows[:5], 5); settle(); assert_bottom()
    assert preview.list.bar.isHidden() and preview.note.text() == '共 5 条'
    # No accumulated height or pending adapt loop on an unchanged page.
    stable = (shell.result_content.height(), preview.height())
    for _ in range(30):
        APP.processEvents()
    assert stable == (shell.result_content.height(), preview.height())
    assert not shell.result_content._adapt_pending
    page.resize(1460, 400); settle()
    assert preview.list.height() == 6 * 36
    assert page.verticalScrollBar().maximum() > 0
    page.ensureWidgetVisible(preview.list); settle()
    assert page.horizontalScrollBar().maximum() == 0
    page.close(); page.deleteLater(); shell.deleteLater(); settle()


@pytest.mark.parametrize('language', ['zh', 'en', 'ja'])
def test_readable_fonts_and_short_window_keeps_card_sizes(language, monkeypatch):
    monkeypatch.setattr('twobyteasr.i18n._CURRENT_LANGUAGE_CACHE', language)
    shell, page = completion_page()
    page.resize(1440, 940)
    page.show()
    apply_ui_language(page, language)
    APP.processEvents()
    cards = shell.result_action_grid.cards
    heights = [card.height() for card in cards]
    from twobyteasr.app.completion_widgets import COMPLETION_MAIN_HEIGHT
    assert len(set(heights)) == 1 and COMPLETION_MAIN_HEIGHT <= heights[0] <= max(card.desired_height(card.width()) for card in cards)+24
    # 2026-10-07 type scale: display title 24-28, card title 18-22, body 13-16.
    assert 24 <= shell.result_title.head_font().pixelSize() <= 28
    assert 14 <= shell.result_summary.font().pixelSize() <= 16
    for card in cards:
        assert 18 <= card.title_font().pixelSize() <= 22
        assert 13 <= card.description_font().pixelSize() <= 15
        icon, title, description = (rect.toRect() for rect in card.content_rects())
        flags = Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap
        from twobyteasr.i18n import translate
        assert QFontMetrics(card.title_font()).boundingRect(title, flags, card.text()).height() <= title.height()
        assert QFontMetrics(card.description_font()).boundingRect(description, flags,
            translate(card.description, language)).height() <= description.height()
        assert all(card.rect().contains(rect) for rect in (icon, title, description))
        # Icon chip + text group is centered in the card, icon and text block
        # each vertically centered.
        group_right = max(title.right(), description.right())
        assert abs((icon.left()+group_right)/2-card.rect().center().x()) <= 2
        assert abs(icon.center().y()-card.rect().center().y()) <= 1
        assert abs((title.top()+description.bottom())/2-card.rect().center().y()) <= 1
    assert all(44 <= header.height() <= 52 for header in (shell.result_files_toggle, shell.result_log_toggle))
    page.resize(1440, 400)
    APP.processEvents()
    assert [card.height() for card in cards] == heights
    assert page.verticalScrollBar().maximum() > 0
    assert page.horizontalScrollBar().maximum() == 0
    page.close(); page.deleteLater(); shell.deleteLater(); APP.processEvents()


@pytest.mark.parametrize('width', [1320, 1440, 1920, 2560, 3840])
def test_common_desktop_width_uses_85_to_90_percent_of_viewport(width):
    shell, page = completion_page()
    page.resize(width, 940)
    page.show()
    APP.processEvents()
    ratio = shell.result_content.width() / page.viewport().width()
    assert .85 <= ratio <= .90
    assert shell.result_action_grid.columns == 3
    page.close(); page.deleteLater(); shell.deleteLater(); APP.processEvents()


@pytest.mark.parametrize('language', ['zh', 'en', 'ja'])
def test_intermediate_width_wraps_before_translated_supporting_labels_overflow(language):
    shell, page = completion_page()
    page.resize(1100, 620); page.show(); apply_ui_language(page, language); APP.processEvents()
    for button in (shell.result_todo.ai_card.action, shell.result_more_button):
        assert button.fontMetrics().horizontalAdvance(button.text())+24 <= button.width()
        assert button.width() <= shell.result_content.width()
    assert page.horizontalScrollBar().maximum() == 0
    assert .85 <= shell.result_content.width()/page.viewport().width() <= .90
    page.close(); page.deleteLater(); shell.deleteLater(); APP.processEvents()


def test_actual_navigation_gap_uses_parent_chain_and_leaves_other_pages_padding_intact():
    shell, completion = completion_page()
    root = QVBoxLayout(shell); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
    shell.app_header = QWidget(); shell.app_header.setFixedHeight(104); root.addWidget(shell.app_header)
    host = QWidget(); root.addWidget(host, 1)
    shell.content_layout = QVBoxLayout(host); shell.content_layout.setContentsMargins(18, 12, 18, 14)
    shell.pages = QStackedWidget(); shell.content_layout.addWidget(shell.pages)
    shell.settings_scroll = QWidget(); shell.studio_page = QWidget()
    shell.workshop_page = QWidget(); shell.term_library_page = QWidget(); shell.history_page = QWidget()
    for page in (shell.settings_scroll, QWidget(), completion, shell.studio_page): shell.pages.addWidget(page)
    for name in ('model_workshop_button', 'subtitle_studio_button', 'return_recognition_button'):
        setattr(shell, name, QToolButton(shell.app_header))
    shell.pages.currentChanged.connect(shell._page_changed)
    shell.resize(1440, 900); shell.show(); shell.pages.setCurrentIndex(2); APP.processEvents()
    summary_top = shell.result_summary_card.mapTo(shell, QPoint()).y()
    header_bottom = shell.app_header.mapTo(shell, QPoint()).y() + shell.app_header.height()
    assert 24 <= summary_top-header_bottom <= 32
    assert summary_top-header_bottom == 28
    shell.pages.setCurrentIndex(0); APP.processEvents()
    assert shell.content_layout.contentsMargins().top() == 12
    shell.close(); shell.deleteLater(); APP.processEvents()


def test_narrow_page_stacks_all_operations_and_scrolls_without_horizontal_overflow():
    shell, page = completion_page()
    page.resize(580, 420)
    page.show()
    APP.processEvents()
    assert shell.result_action_grid.columns == 1
    assert page.verticalScrollBar().maximum() > 0
    assert page.horizontalScrollBar().maximum() == 0
    controls = shell.result_action_grid.cards
    assert all(earlier.geometry().bottom() < later.geometry().top() for earlier, later in zip(controls, controls[1:]))
    assert all(control.width() <= page.viewport().width() for control in controls)
    assert len({control.x() for control in controls}) == 1
    assert shell.result_todo.columns == 1 and shell.result_folds.columns == 1
    files, log = shell.result_files_panel, shell.result_log_panel
    assert files.geometry().bottom() < log.geometry().top() and files.x() == log.x()
    page.close()
    page.deleteLater()
    shell.deleteLater()
    APP.processEvents()
