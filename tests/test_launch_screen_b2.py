# -*- coding: utf-8 -*-
"""2026-11-23 (user picked draft B2 「音波時間軸」 for the launch screen): the wordmark comes in glyph
by glyph over a timeline card whose playhead follows the start's stages, the waveform lights up
where it has passed and a cue drops in per completed stage; at the end the wordmark flies onto
Home's title while Home appears under it. Timed only by design/motion_tokens.py."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QImage, QPainter


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(app):
    from twobyteasr.app.launch_screen import LaunchScreen, Sprites, palette
    colors = palette('sand')
    return LaunchScreen(1000, 660, colors, Sprites.build(colors, 'zh-Hant', 1.0), 'zh-Hant', 3.0)


def _frame(screen, t, width=1000, height=660):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(screen.colors['background']))
    painter = QPainter(image)
    screen.draw(painter, t)
    painter.end()
    return image


def _differs(image, x, y, w, h, colour, step=3):
    return any(image.pixelColor(int(x + i), int(y + j)) != colour
               for i in range(0, int(w), step) for j in range(0, int(h), step))


def test_the_playhead_follows_the_stages_without_overshoot():
    from twobyteasr.app.launch_motion import STAGE_VALUE, progress_at
    values = [progress_at(t / 100, 3.0) for t in range(0, 1200)]
    assert values[0] == 0.0
    assert all(b >= a - 1e-9 for a, b in zip(values, values[1:]))       # never goes back
    assert max(values) <= STAGE_VALUE[-1] + 1e-9                         # waits below the end (no bounce)
    assert values[-1] == pytest.approx(STAGE_VALUE[-1], abs=1e-3)
    assert progress_at(1.0, 2.0) > progress_at(1.0, 6.0)                 # a quicker last start moves on sooner


def test_a_kept_start_time_sets_the_stages(app):
    from twobyteasr.app import launch_picture as lp
    assert lp._expected_load_s({'launch_s': 2.4}) == 2.4
    assert lp._expected_load_s({'launch_s': 0}) is None and lp._expected_load_s({}) is None
    assert lp._expected_load_s({'launch_s': 'x'}) is None and lp._expected_load_s({'launch_s': 99}) is None


def test_the_wordmark_comes_in_glyph_by_glyph(screen):
    background = screen.colors['background']
    first = screen.glyphs[0]
    last = screen.glyphs[-1]
    early = _frame(screen, 0.06)
    assert _differs(early, first[1], first[2], 24, 40, background)       # the first glyph has begun
    assert not _differs(early, last[1], last[2], 30, 40, background)     # the last not yet
    later = _frame(screen, 1.0)
    assert _differs(later, last[1], last[2], 30, 40, background)


def test_the_waveform_lights_up_where_the_playhead_has_passed(screen):
    accent = screen.colors['accent']
    image = _frame(screen, 1.4)
    _cx, cy, _cw, _ch = screen.card
    middle = int(cy + (48 + 26) * screen.unit)
    head = screen.inner_x + screen.progress(1.4) * screen.inner_w
    behind = [image.pixelColor(int(x), middle) for x in range(int(screen.inner_x) + 2, int(head) - 6)]
    ahead = [image.pixelColor(int(x), middle) for x in range(int(head) + 8, int(screen.inner_x + screen.inner_w) - 2)]
    assert sum(colour == accent for colour in behind) > len(behind) // 4
    assert not any(colour == accent for colour in ahead)


def test_a_cue_drops_in_for_each_completed_stage(screen):
    assert len(screen.cues) == 3
    lefts = [x for _name, _at, x, _w in screen.cues]
    assert lefts == sorted(lefts)
    for (_n, _a, x, w), (_n2, _a2, x2, _w2) in zip(screen.cues, screen.cues[1:]):
        assert x + w <= x2                                                # never on top of each other
    name, at, x, width = screen.cues[0]
    _cx, cy, _cw, _ch = screen.card
    lane = cy + 12 * screen.unit
    before = _frame(screen, at - 0.05)
    after = _frame(screen, at + 0.5)
    card = screen.colors['card']
    # Its left quarter (the playhead stands in its middle when it drops in).
    assert not _differs(before, x + 4, lane + 6, width / 4, 12, card)
    assert _differs(after, x + 4, lane + 6, width / 4, 12, card)
    assert screen.stage(0.0) == 0 and screen.stage(at + 0.01) == 1


def test_sprites_travel_to_the_helper_process(screen, tmp_path):
    from twobyteasr.app.launch_screen import LaunchScreen, Sprites
    screen.sprites.save(str(tmp_path))
    loaded = Sprites.load(str(tmp_path))
    assert loaded.items == screen.sprites.items and loaded.atlas.size() == screen.sprites.atlas.size()
    copy = LaunchScreen(1000, 660, {k: v.name() for k, v in screen.colors.items()}, loaded, 'zh-Hant', 3.0)
    assert _frame(copy, 1.2) == _frame(screen, 1.2)                      # both drawers draw the same picture


def test_every_frame_stays_inside_its_area(screen):
    area = screen.area().toAlignedRect()
    background = screen.colors['background']
    for t in (0.1, 0.5, 1.3, 2.6, 4.0):
        image = _frame(screen, t)
        for x in range(0, 1000, 9):
            for y in range(0, 660, 9):
                if not area.contains(x, y):
                    assert image.pixelColor(x, y) == background, (t, x, y)


def test_languages_and_small_windows(app):
    from twobyteasr.app.launch_screen import LaunchScreen, Sprites, language_key, palette
    assert language_key('zh') == 'zh' and language_key('zh-Hant') == 'zh-Hant' and language_key('ko') == 'en'
    colors = palette('grape')
    small = LaunchScreen(420, 300, colors, Sprites.build(colors, 'en', 1.0), 'en', 2.0)
    left, top, width, height = small.wordmark_rect
    assert small.unit < 1.0 and left >= 0 and left + width <= 420
    cx, cy, cw, ch = small.card
    assert cx >= 0 and cx + cw <= 420 and small.text_y < 300


def test_the_motion_draws_only_its_area(app, screen):
    from PySide6.QtWidgets import QWidget
    from twobyteasr.app.launch_motion import LaunchMotion
    shell = QWidget()
    base = QImage(1000, 660, QImage.Format.Format_RGB32)
    base.fill(QColor(screen.colors['background']))
    motion = LaunchMotion(shell, base, kind='first', scale=1.0, screen=screen,
                          colors={k: v.name() for k, v in screen.colors.items()})
    rects = motion._draw(1.0)
    assert rects == [screen.area()]
    assert motion.frame.pixelColor(5, 5) == screen.colors['background']
    shell.deleteLater()


def test_the_end_flies_each_half_onto_its_label_and_ends_on_home(app, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QLabel, QWidget
    from twobyteasr.app import launch_picture as lp
    from twobyteasr.app.launch_motion import LaunchMotion
    from twobyteasr.design import motion_tokens as tokens
    monkeypatch.setattr(lp, '_directory', lambda: tmp_path)
    window = QWidget()
    window.setStyleSheet('background: #2060c0;')
    window.setGeometry(120, 90, 1000, 660)
    window.brand = QLabel('2ByteASR', window)
    window.brand.setGeometry(110, 20, 150, 40)
    window.header_subtitle = QLabel('兔白字幕', window)
    window.header_subtitle.setGeometry(262, 20, 110, 40)
    window.show()
    app.processEvents()
    meta = dict(geometry=(120, 90, 1000, 660), theme='grape', background='#19151c', language='zh')
    shell = lp._make_shell(app, meta, 'first')
    shell.setGeometry(window.geometry())
    shell.show()
    app.processEvents()
    targets = lp._brand_targets(shell, window)
    assert targets is not None
    assert abs(targets['en'][0] - 110) <= 2 and abs(targets['zh'][0] - 262) <= 2
    screen = shell.ensure_screen()
    picture = window.grab().toImage()
    base = QImage(1000, 660, QImage.Format.Format_RGB32)
    base.fill(QColor('#19151c'))
    motion = LaunchMotion(shell, base, kind='first', scale=1.0, screen=screen, colors=shell.colors)
    motion.begin_landing(picture, (0.0, 0.0), targets, 1.5)
    motion._landing['began'] -= 0.002
    rects = motion._draw(0.0)
    assert len(rects) == 1 and rects[0].width() == 1000 and not motion.landed()   # the whole window
    start = motion.frame.pixelColor(900, 600)
    assert abs(start.blue() - 0x1c) < abs(start.blue() - 0xc0)           # at first the launch screen
    motion._landing['began'] -= tokens.PAGE_IN.ms / 1000
    motion._draw(0.0)
    assert motion.landed()
    assert motion.frame.pixelColor(900, 600) == QColor('#2060c0')        # the last frame is Home alone
    assert motion.frame.pixelColor(500, 330) == QColor('#2060c0')
    # Each half is its own part of the wordmark: 2ByteASR left of 兔白字幕.
    assert screen.spans['en'][0] + screen.spans['en'][1] < screen.spans['zh'][0]
    shell.deleteLater()
    window.deleteLater()


def test_without_both_labels_the_end_fades_as_before(app, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QLabel, QWidget
    from twobyteasr.app import launch_picture as lp
    monkeypatch.setattr(lp, '_directory', lambda: tmp_path)
    window = QWidget()
    window.setGeometry(120, 90, 1000, 660)
    window.brand = QLabel('2ByteASR', window)
    window.brand.setGeometry(110, 20, 150, 40)
    window.show()
    app.processEvents()
    meta = dict(geometry=(120, 90, 1000, 660), theme='grape', background='#19151c', language='zh')
    shell = lp._make_shell(app, meta, 'first')
    shell.show()
    app.processEvents()
    assert lp._brand_targets(shell, window) is None
    assert not lp._land(shell, window)                                    # no motion, no title: the old fade
    shell.deleteLater()
    window.deleteLater()


def test_the_group_is_centred_and_grows_with_big_windows(app):
    # 2026-11-23 (user: the launch screen sat high and small in a big window).
    from twobyteasr.app.launch_screen import LaunchScreen, STATUS_HEIGHT, Sprites, palette, unit_for
    colors = palette('sand')
    for width, height in ((1320, 880), (2194, 1234)):
        screen = LaunchScreen(width, height, colors, Sprites.build(colors, 'zh-Hant', 1.0), 'zh-Hant', 3.0)
        _left, top, _w, _h = screen.wordmark_rect
        bottom = screen.text_y + STATUS_HEIGHT * screen.unit
        assert abs((top + bottom) / 2 - height / 2) < height * 0.05
        assert screen.unit == unit_for(width, height) > 1.2
    assert unit_for(620, 470) == 1.0 and unit_for(4000, 3000) == 1.6 and unit_for(310, 235) == 0.5
