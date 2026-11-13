"""Workshop list layout, 2026-11-13: tools beside the tabs, borderless rows,
no visible scroll bar (wheel or left-button drag), ten language badges."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, Qt, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QScrollArea

from twobyteasr.local_models.model_languages import (
    BADGE_LANGUAGES, LANGUAGE_SUPPORT, WORKSHOP_LANGUAGES, language_support,
)

ROOT = Path(__file__).parents[1]


@pytest.fixture(autouse=True)
def isolated_model_registry(tmp_path, monkeypatch):
    from twobyteasr.runtime_paths import reset_runtime_paths, MODEL_ROOT_ENV, USER_DATA_ENV
    monkeypatch.setenv('TWOBYTEASR_TEST_ROOT', str(tmp_path))
    monkeypatch.setenv(MODEL_ROOT_ENV, str(tmp_path / 'models'))
    monkeypatch.setenv(USER_DATA_ENV, str(tmp_path / 'local'))
    reset_runtime_paths()
    yield
    reset_runtime_paths()


def _settle(app, rounds=6):
    for _ in range(rounds):
        app.processEvents()


def _page(width, height=800):
    from twobyteasr.local_models.model_workshop import ModelWorkshopPage
    app = QApplication.instance() or QApplication([])
    page = ModelWorkshopPage(ROOT, {'models': {}})
    page.resize(width, height)
    page.show()
    _settle(app)
    return app, page


def _close(app, page):
    page.close()
    page.deleteLater()
    app.processEvents()


def _send(widget, kind, pos, buttons):
    local = QPointF(pos)
    global_pos = QPointF(widget.mapToGlobal(pos))
    button = Qt.MouseButton.LeftButton if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
    QApplication.sendEvent(widget, QMouseEvent(kind, local, global_pos, button, buttons, Qt.KeyboardModifier.NoModifier))


def test_every_record_rates_only_known_languages_and_extra_tiers_follow_sources():
    for key, record in LANGUAGE_SUPPORT.items():
        assert set(record.get("tiers", {})) <= set(WORKSHOP_LANGUAGES), key
    assert tuple(language_support("moss")["tiers"]) == BADGE_LANGUAGES  # six by default
    wide = language_support("qwen_local", WORKSHOP_LANGUAGES)["tiers"]
    assert tuple(wide) == WORKSHOP_LANGUAGES
    assert {wide[code] for code in ("fr", "de", "es", "ru")} == {"strong"}
    assert language_support("firered", WORKSHOP_LANGUAGES)["tiers"]["fr"] == "no"
    assert language_support("moss", WORKSHOP_LANGUAGES)["tiers"]["de"] == "usable"
    # GLM-ASR's 17-language list is not enumerated in our sources: not sure.
    assert language_support("glm_asr_nano", WORKSHOP_LANGUAGES)["tiers"]["es"] == "unknown"


def test_wide_list_has_tools_in_the_tab_row_and_ten_languages():
    app, page = _page(2400)
    try:
        assert page._tool_placer.inline
        assert page.tool_strip.parentWidget() is page.findChild(type(page.tool_strip.parentWidget()), "workshopTabBar")
        scroll = page.findChild(QScrollArea, "workshopScroll")
        assert scroll.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        card = page._cards['qwen_local']
        card = card.__dict__.get('_card') or card
        row = card.language_row
        shown = [code for code, badge in row.badges.items() if not badge.isHidden()]
        assert shown == list(WORKSHOP_LANGUAGES) and row.grid_columns == 5
        assert [row.badges[code].text() for code in ("fr", "de", "es", "ru")] == ["法语", "德语", "西语", "俄语"]
        assert page.list_header.wide_languages
    finally:
        _close(app, page)


def test_narrow_list_keeps_six_languages_and_moves_tools_below():
    app, page = _page(1100)
    try:
        page._tool_placer.place()
        assert not page._tool_placer.inline
        card = page._cards['qwen_local']
        card = card.__dict__.get('_card') or card
        shown = [code for code, badge in card.language_row.badges.items() if not badge.isHidden()]
        assert shown == list(BADGE_LANGUAGES) and card.language_row.grid_columns == 3
        assert not page.list_header.wide_languages
    finally:
        _close(app, page)


def test_left_button_drag_scrolls_the_list_and_a_still_click_still_clicks():
    app, page = _page(2400, 700)
    try:
        scroll = page.findChild(QScrollArea, "workshopScroll")
        bar = scroll.verticalScrollBar()
        assert bar.maximum() > 200
        bar.setValue(0)
        target = scroll.viewport()
        start = QPoint(target.width() // 2, target.height() - 20)
        _send(target, QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton)
        for step in range(1, 6):  # drag up 200 px
            _send(target, QEvent.Type.MouseMove, start - QPoint(0, 40 * step), Qt.MouseButton.LeftButton)
        _send(target, QEvent.Type.MouseButtonRelease, start - QPoint(0, 200), Qt.MouseButton.NoButton)
        assert bar.value() == 200  # content moved up: further models shown

        bar.setValue(0)
        _settle(app)
        wrapper = page._cards['mosi_moss_pro']
        card = wrapper.__dict__.get('_card') or wrapper
        button = card.action
        hits = []
        button.clicked.disconnect()
        button.clicked.connect(lambda *_: hits.append(1))
        centre = button.rect().center()
        # A press and release without moving is a normal click on a list button.
        _send(button, QEvent.Type.MouseButtonPress, centre, Qt.MouseButton.LeftButton)
        _send(button, QEvent.Type.MouseButtonRelease, centre, Qt.MouseButton.NoButton)
        assert hits == [1] and bar.value() == 0
        # A drag that starts on the button scrolls and does not click it.
        _send(button, QEvent.Type.MouseButtonPress, centre, Qt.MouseButton.LeftButton)
        _send(button, QEvent.Type.MouseMove, centre - QPoint(0, 60), Qt.MouseButton.LeftButton)
        _send(button, QEvent.Type.MouseButtonRelease, centre - QPoint(0, 60), Qt.MouseButton.NoButton)
        assert hits == [1] and bar.value() == 60
    finally:
        _close(app, page)
