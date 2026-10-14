"""2026-10-14 appearance picker: grouped theme cards, live preview, revert on
cancel; plus the theme-following ink and score bars it exposed."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import QRectF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.ui_theme import THEME_FAMILIES, THEMES, contrast_ratio


@pytest.fixture
def app(tmp_path, monkeypatch):
    instance = QApplication.instance() or QApplication([])
    from twobyteasr import theme_manager
    monkeypatch.setattr(theme_manager, "_settings",
                        lambda: QSettings(str(tmp_path / "theme.ini"), QSettings.Format.IniFormat))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    theme_manager.save_theme_key("grape")
    return instance


def _dialog(tmp_path):
    from twobyteasr.application_settings_ui import ApplicationSettingsDialog
    return ApplicationSettingsDialog(None, {}, tmp_path, browse=lambda *a: None, clear_recent=lambda: None,
                                     reset_layout=None)


def test_gallery_groups_every_theme_and_selects_the_active_one(app):
    from twobyteasr.theme_gallery import ThemeGallery
    gallery = ThemeGallery("frost")
    assert gallery.count() == len(THEMES)
    assert gallery.currentData() == "frost" and gallery.currentText() == "霜白引擎"
    assert [family for family, *_ in gallery._sections] == [family for family, _ in THEME_FAMILIES]
    for family, header, _grid, cards in gallery._sections:
        assert header.text() and cards
        assert all(card.theme.family == family for card in cards)
    assert sum(card.isChecked() for card in gallery._cards) == 1
    gallery.setCurrentIndex(gallery.findData("obsidian"))
    assert gallery.currentData() == "obsidian"
    assert gallery.card("frost").isChecked() is False
    gallery.deleteLater()


def test_gallery_reflows_columns_and_cards_fit_their_text(app):
    from twobyteasr.theme_gallery import ThemeGallery
    gallery = ThemeGallery("grape")
    gallery.resize(640, 800)
    gallery.show()
    app.processEvents()
    assert gallery._columns == 3
    gallery.resize(380, 800)
    app.processEvents()
    assert gallery._columns <= 2
    card = gallery.card("frost")
    assert card.sizeHint().height() >= card._preview_height() + card._text_height()
    gallery.close()


def test_card_click_previews_and_cancel_restores_the_opening_theme(app, tmp_path):
    from twobyteasr import theme_manager
    applied = []
    real_apply = theme_manager.apply_theme

    def spy(key, application=None):
        applied.append(key)
        return real_apply(key, application)

    from unittest import mock
    with mock.patch.object(theme_manager, "apply_theme", spy):
        dialog = _dialog(tmp_path)
        gallery = dialog.theme_gallery
        assert dialog.theme_combo is gallery  # name kept for settings save / audits
        QTest.mouseClick(gallery.card("obsidian"), Qt.MouseButton.LeftButton)
        assert applied[-1] == "obsidian" and theme_manager.theme_key() == "obsidian"
        assert "黑曜警戒" in dialog.theme_preview_hint.text() and "葡萄夜幕" in dialog.theme_preview_hint.text()
        dialog.done(0)
        assert applied[-1] == "grape" and theme_manager.theme_key() == "grape"
        dialog.deleteLater()

        dialog = _dialog(tmp_path)
        QTest.mouseClick(dialog.theme_gallery.card("frost"), Qt.MouseButton.LeftButton)
        dialog.done(1)  # accepted: the preview stays
        assert theme_manager.theme_key() == "frost"
        dialog.deleteLater()


def test_arrow_keys_move_focus_without_switching_themes(app, tmp_path):
    from twobyteasr import theme_manager
    from twobyteasr.theme_gallery import ThemeGallery
    chosen = []
    gallery = ThemeGallery("frost")
    gallery.themeChosen.connect(chosen.append)
    gallery.show()
    app.processEvents()
    first = gallery._cards[0]
    first.setFocus()
    QTest.keyClick(first, Qt.Key.Key_Right)
    assert gallery._cards[1].hasFocus() or not gallery.isActiveWindow()
    assert chosen == [] and gallery.currentData() == "frost"
    QTest.keyClick(gallery._cards[1], Qt.Key.Key_Space)
    assert chosen == [gallery._cards[1].theme.key]
    gallery.close()
    assert theme_manager.theme_key() == "grape"  # the bare gallery never applies themes itself


def test_miniature_paints_each_theme_distinctly(app):
    from twobyteasr.theme_gallery import paint_theme_miniature
    samples = set()
    for theme in THEMES.values():
        image = QImage(180, 110, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        paint_theme_miniature(painter, QRectF(0, 0, 180, 110), theme)
        painter.end()
        samples.add(tuple(image.pixelColor(x, y).name() for x, y in ((90, 60), (20, 40), (100, 5))))
    assert len(samples) == len(THEMES)


def test_white_text_on_accent_or_status_fill_takes_the_theme_ink():
    from twobyteasr.main_ui_theme import APP_QSS
    from twobyteasr.qss_retheme import retheme_qss
    for key in ("obsidian", "graphite", "contrast", "slate", "neon"):
        theme = THEMES[key]
        qss = retheme_qss(APP_QSS, theme)
        for body in re.findall(r"\{([^{}]*)\}", qss):
            fills = set(re.findall(r"(?<![-\w])background(?:-color)?:\s*(#[0-9a-fA-F]{6})", body))
            if fills & {theme.accent, theme.accent_hover, theme.accent_pressed}:
                assert not re.search(r"(?<![-\w])color:\s*(#ffffff|white)\b", body), (key, body[:120])
    warm = retheme_qss(APP_QSS, THEMES["warm"])
    assert warm.count("#ffffff") + warm.count("white") > 10  # light themes keep white on their dark accents


def test_workshop_score_bars_follow_the_theme(monkeypatch):
    from twobyteasr import model_workshop, theme_manager
    for key, theme in THEMES.items():
        monkeypatch.setattr(theme_manager, "theme_key", lambda key=key: key)
        track, low, mid, high = model_workshop._score_palette()
        assert contrast_ratio(track, theme.surface) < 4.0  # a groove, never the old ~13:1 beige stripe
        assert contrast_ratio(high, track) >= 1.6 and contrast_ratio(low, track) >= 1.4, key


def test_gallery_follows_language_switch(app, monkeypatch):
    from twobyteasr import i18n
    from twobyteasr.theme_gallery import ThemeGallery
    gallery = ThemeGallery("obsidian")
    assert gallery.currentText() == "黑曜警戒"
    for language, name, family in (("en", "Obsidian Signal", "Dark"), ("ja", "オブシディアン・シグナル", "ダーク"),
                                   ("ko", "옵시디언 시그널", "다크"), ("zh-Hant", "黑曜警戒", "深色")):
        monkeypatch.setattr(i18n, "current_language", lambda language=language: language)
        gallery.retranslate_ui()
        assert gallery.currentText() == name
        assert gallery.card("obsidian").text() == name and gallery.card("obsidian").accessibleDescription()
        assert any(header.text() == family for _f, header, _g, _c in gallery._sections)
    assert gallery.card("midnight").text() == "夜航藍圖"  # zh-Hant names are Traditional, not English
    gallery.deleteLater()
