# -*- coding: utf-8 -*-
"""2026-11-22 page switches (a day of rounds with the user).

Sideways switches are the iOS push the user picked: going forward the new page slides over the old
one from the edge with a soft shadow, the page underneath moves a third of the way and darkens a
little; going back runs in reverse; nothing fades. Starting recognition grows the recognition page
out of the start button and going back shrinks it into it, correct at 125/150/175 % too. Going
forward (recognition, results) comes from the right."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QVBoxLayout, QWidget

GROUND = QColor('#f0f0f0')
OLD = QColor('#c02020')
NEW = QColor('#2040c0')


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


class _Hold(QWidget):
    def __init__(self, old, new, size=(1000, 600)):
        super().__init__()
        self.resize(*size)
        self.old, self.new = old, new


def _page(colour, ratio=1.0, size=(1000, 600)):
    pixmap = QPixmap(round(size[0] * ratio), round(size[1] * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(GROUND)
    painter = QPainter(pixmap)
    painter.fillRect(QRect(40, 40, size[0] - 80, size[1] - 80), QColor(colour))
    painter.end()
    return pixmap


def _frame(motion, hold, ms, ratio=1.0):
    image = QImage(round(hold.width() * ratio), round(hold.height() * ratio), QImage.Format.Format_RGB32)
    image.setDevicePixelRatio(ratio)
    image.fill(QColor('#000000'))
    painter = QPainter(image)
    motion.paint(painter, hold, ms)
    painter.end()
    return image


def _push(direction=1, ratio=1.0):
    from twobyteasr.design.transitions import PageMotion
    hold = _Hold(_page(OLD, ratio), _page(NEW, ratio))
    motion = PageMotion(direction, axis='x', background=QColor('#101010'))
    motion.prepare(hold)
    motion.picture_ready(hold.new)
    return motion, hold


def test_forward_the_new_page_slides_over_the_old_one(app):
    from twobyteasr.design import motion_tokens as tokens
    motion, hold = _push()
    assert motion.total_ms == tokens.PAGE_PUSH.ms
    start = motion.layout_at(0)
    assert start['top'] == ('new', 1000.0) and start['under'] == ('old', 0.0) and start['dim'] == 0
    mid = motion.layout_at(200)
    assert 0 < mid['top'][1] < 1000                                    # on its way in from the right
    assert -1000 * tokens.PAGE_PUSH_PARALLAX < mid['under'][1] < 0     # the old page: a third, the other way
    end = motion.layout_at(motion.total_ms)
    assert end['top'] == ('new', 0.0)
    assert end['under'][1] == pytest.approx(-1000 * tokens.PAGE_PUSH_PARALLAX)
    assert end['dim'] == pytest.approx(tokens.PAGE_PUSH_DIM)
    assert _frame(motion, hold, 0).pixelColor(500, 300) == OLD
    assert _frame(motion, hold, motion.total_ms).pixelColor(500, 300) == NEW


def test_the_page_on_top_never_fades(app):
    motion, hold = _push()
    for ms in (40, 120, 200, 280, 360):
        x = motion.layout_at(ms)['top'][1]
        image = _frame(motion, hold, ms)
        sample = int(min(hold.width() - 60, x + 60))
        assert image.pixelColor(sample, 300) == NEW, ms                 # solid wherever it has arrived


def test_going_back_the_page_on_top_slides_away_and_the_one_underneath_returns(app):
    motion, hold = _push(-1)
    start = motion.layout_at(0)
    assert start['top'] == ('old', 0.0) and start['under'][0] == 'new'
    mid = motion.layout_at(200)
    assert 0 < mid['top'][1] < 1000
    image = _frame(motion, hold, 200)
    assert image.pixelColor(int(mid['top'][1]) + 80, 300) == OLD       # the leaving page stays solid
    end = motion.layout_at(motion.total_ms)
    assert end['under'] == ('new', 0.0) and end['dim'] == 0
    assert _frame(motion, hold, motion.total_ms).pixelColor(500, 300) == NEW


def test_the_push_is_drawn_1_to_1_on_high_dpi_screens(app):
    motion, hold = _push(ratio=1.75)
    image = _frame(motion, hold, 160, 1.75)
    x = motion.layout_at(160)['top'][1]
    assert image.pixelColor(round((x + 80) * 1.75), round(300 * 1.75)) == NEW


def test_gaps_show_the_new_pages_background(app):
    motion, _hold = _push()
    assert motion.ground == GROUND


def test_page_layers_take_whole_cards_through_single_containers(app):
    from twobyteasr.design.transitions import page_layers
    stack = QWidget()
    stack.resize(1000, 600)
    page = QWidget(stack)
    page.setGeometry(0, 0, 1000, 600)
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    panel = QWidget()                                      # one panel filling the page: looked through
    outer.addWidget(panel)
    row = QHBoxLayout(panel)
    cards = []
    for _ in range(2):
        card = QFrame()
        inner = QVBoxLayout(card)
        for _ in range(4):
            inner.addWidget(QFrame())                      # contents: never separate layers
        row.addWidget(card)
        cards.append(card)
    stack.show()
    app.processEvents()
    try:
        layers = page_layers(page, stack)
        assert len(layers) == 2
        for card, layer in zip(cards, layers):
            assert layer == QRect(card.mapTo(stack, card.rect().topLeft()), card.size())
    finally:
        stack.deleteLater()


class _Pages:
    def __init__(self, widgets):
        self.widgets = widgets

    def widget(self, index):
        return self.widgets[index]


def test_forward_pages_come_from_the_right():
    from twobyteasr.app.ui import MainWindow
    home, progress, results, workshop = object(), object(), object(), object()
    fake = type('Fake', (), {})()
    fake.settings_scroll = home
    fake.pages = _Pages([home, progress, results])
    depth = lambda page: MainWindow._page_depth(fake, page)  # noqa: E731
    assert depth(home) == 0 and depth(progress) == 1 and depth(workshop) == 1 and depth(results) == 2


def test_recognition_grows_out_of_the_start_button_and_shrinks_back(app):
    from twobyteasr.design import motion_tokens as tokens
    from twobyteasr.design.transitions import PageZoom
    home = QPixmap(1000, 600)
    home.fill(GROUND)
    recognition = QPixmap(1000, 600)
    recognition.fill(NEW)
    button = QRect(800, 540, 160, 40)
    enter = PageZoom(True, button)
    hold = _Hold(home, recognition)
    enter.prepare(hold)
    small = enter.page_rect(0.0)
    assert small.contains(QRectF(button).center()) and small.width() < 300
    assert enter.page_rect(1.0) == QRectF(hold.rect())
    first = _frame(enter, hold, 0)
    assert first.pixelColor(100, 100) == GROUND                         # Home as it was
    assert first.pixelColor(880, 560) == NEW                            # solid on the button from the start
    end = _frame(enter, hold, enter.total_ms)
    assert end.pixelColor(100, 100) == NEW and end.pixelColor(990, 590) == NEW
    back = PageZoom(False, button)
    hold_back = _Hold(recognition, home)
    back.prepare(hold_back)
    assert _frame(back, hold_back, 0).pixelColor(500, 300) == NEW
    assert _frame(back, hold_back, back.total_ms).pixelColor(500, 300) == GROUND
    assert enter.total_ms == tokens.PAGE_ZOOM_IN.ms and back.total_ms == tokens.PAGE_ZOOM_OUT.ms


def test_the_growing_page_keeps_its_scale_on_high_dpi_screens(app):
    """Qt maps a high-DPI texture by its own ratio; dividing by it again drew the recognition page
    shrunken and tiled at 125/150/175 % (2026-11-22)."""
    from twobyteasr.design.transitions import PageZoom
    ratio = 1.75

    def halves(left, right):
        pixmap = QPixmap(round(1000 * ratio), round(600 * ratio))
        pixmap.setDevicePixelRatio(ratio)
        painter = QPainter(pixmap)
        painter.fillRect(QRect(0, 0, 500, 600), QColor(left))
        painter.fillRect(QRect(500, 0, 500, 600), QColor(right))
        painter.end()
        return pixmap

    hold = _Hold(halves('#f0f0f0', '#f0f0f0'), halves('#2040c0', '#20a040'))
    zoom = PageZoom(True, QRect(450, 280, 100, 40))
    zoom.prepare(hold)
    image = _frame(zoom, hold, zoom.total_ms * 0.99, ratio)
    assert image.pixelColor(round(250 * ratio), round(300 * ratio)).blue() > 150      # left half blue
    assert image.pixelColor(round(750 * ratio), round(300 * ratio)).green() > 120     # right half green


def test_starting_recognition_and_going_back_zoom(app):
    from twobyteasr.app.ui import MainWindow
    from twobyteasr.design.transitions import PageMotion, PageZoom
    home, progress, results, workshop = object(), object(), object(), object()
    fake = type('Fake', (), {})()
    fake.settings_scroll = home
    fake.pages = _Pages([home, progress, results])
    fake._nav_key = lambda page: 'workshop' if page is workshop else None
    fake._page_depth = lambda page: MainWindow._page_depth(fake, page)
    fake._start_button_rect = lambda: QRect(10, 10, 100, 30)
    leaving = {'origin': QRect(800, 540, 160, 40), 'parts': [QRect(0, 0, 100, 100)]}
    into = MainWindow._page_motion(fake, home, progress, leaving)()
    assert isinstance(into, PageZoom) and into.entering and into.origin == leaving['origin']
    out = MainWindow._page_motion(fake, progress, home, {})()
    assert isinstance(out, PageZoom) and not out.entering and out.origin == QRect(10, 10, 100, 30)
    assert PageMotion is not None
