"""2026-11-19 (user picked options A and B for the start): the kept picture survives updates and
fades out over the real window; when the launcher draws Home's skeleton the app shows nothing of
its own and tells it when to fade. 2026-11-23 (draft B2 「音波時間軸」): every start draws the
wordmark over a waveform timeline on the theme's background - never Home's skeleton, the kept
picture or the bunny head."""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def lp(app, tmp_path, monkeypatch):
    from twobyteasr.app import launch_picture
    monkeypatch.setattr(launch_picture, '_directory', lambda: tmp_path)
    monkeypatch.setenv('TWOBYTEASR_LAUNCH_PICTURE', '1')
    monkeypatch.delenv('TWOBYTEASR_LAUNCH_COVER', raising=False)
    monkeypatch.setattr(launch_picture, '_COVER_EVENT', '')
    yield launch_picture
    launch_picture.dismiss(fade=False)


def _meta(lp, app, **changes):
    meta = dict(format=lp.FORMAT, program='ui.py|1|1', screens=lp.screens_signature(app), client=[100, 80, 1320, 880],
                scale=1.0, maximized=False, next_page='recognition', picture=True, background='#19151c',
                foreground='#a69ba6', theme='grape', language='zh', zoom=100)
    meta.update(changes)
    return meta


def test_a_picture_from_another_build_is_still_shown(lp, app, tmp_path):
    (tmp_path / 'home.bmp').write_bytes(b'BM')
    assert lp.usable(_meta(lp, app), app) == 'picture'
    assert 'program' not in lp._PICTURE_KEY            # a close elsewhere after an update keeps it too


def test_the_launch_screen_is_the_wordmark_over_a_timeline(lp, app, monkeypatch):
    from PySide6.QtGui import QImage
    monkeypatch.setenv('TWOBYTEASR_LAUNCH_MOTION', '0')                  # the still picture is the screen at rest
    meta = _meta(lp, app, picture=False, client=[100, 80, 1000, 640])
    shell = lp._make_shell(app, meta, 'plain')
    assert shell is not None and shell.windowOpacity() < 1.0          # layered from the start: it can fade
    assert not hasattr(shell, 'cover') and not hasattr(lp, '_bunny_pixmap')
    image = QImage(shell.size(), QImage.Format.Format_ARGB32)
    shell.render(image)
    assert image.pixelColor(10, 10).name() == '#19151c'                 # no header bar: the background
    screen = shell.screen
    cx, cy, cw, ch = screen.card
    assert image.pixelColor(int(cx + cw - 30), int(cy + 20)).name() == '#2f2935'   # the timeline card
    left, top, width, height = screen.wordmark_rect
    row = [image.pixelColor(int(left + i), int(top + height * 0.6)).name() for i in range(0, int(width), 3)]
    assert any(colour != '#19151c' for colour in row)                   # the wordmark is drawn
    shell.deleteLater()


def test_a_very_first_start_opens_where_the_window_will(lp, app):
    meta = lp._first_start_meta(app)
    assert meta is not None
    x, y, width, height = meta['geometry']
    avail = app.primaryScreen().availableGeometry()
    assert avail.contains(x + width // 2, y + height // 2) and width >= 320 and height >= 200
    assert meta['background'].startswith('#') and meta['theme']           # the skeleton's colours
    shell = lp._make_shell(app, meta, 'first')
    assert shell is not None and shell.background == meta['background']
    assert (shell.width(), shell.height()) == (width, height)
    shell.deleteLater()


def test_the_launchers_skeleton_replaces_our_picture_and_is_told_when_to_fade(lp, app, tmp_path, monkeypatch):
    (tmp_path / 'home.bmp').write_bytes(b'BM')
    (tmp_path / 'meta.json').write_text(json.dumps(_meta(lp, app)), 'utf8')
    monkeypatch.setenv('TWOBYTEASR_LAUNCH_COVER', 'Local\\2ByteASR-launch-cover-test')
    assert lp.show(app) is None
    import os
    assert 'TWOBYTEASR_LAUNCH_COVER' not in os.environ                 # not handed on to a restart
    assert lp._COVER_EVENT == 'Local\\2ByteASR-launch-cover-test'
    signalled = []
    monkeypatch.setattr(lp, 'release_cover', lambda: signalled.append(lp.__dict__.update(_COVER_EVENT='') or 1))
    lp.dismiss()
    assert signalled                                                     # first paint (or failure) ends it


@pytest.mark.skipif(__import__('sys').platform != 'win32', reason='Windows events')
def test_release_cover_sets_the_launchers_event(lp):
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32')
    kernel.CreateEventW.restype = wintypes.HANDLE
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    name = 'Local\\2ByteASR-launch-cover-unit-test'
    handle = kernel.CreateEventW(None, True, False, name)
    try:
        lp._COVER_EVENT = name
        lp.release_cover()
        assert kernel.WaitForSingleObject(handle, 0) == 0                 # signalled
        lp.release_cover()                                               # once; a second call is a no-op
    finally:
        kernel.CloseHandle(handle)


def test_homes_parts_are_written_for_the_launcher(lp, app):
    from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget
    window = QWidget()
    window.resize(900, 600)
    column = QVBoxLayout(window)
    window.app_header = QFrame()
    window.app_header.setFixedHeight(80)
    column.addWidget(window.app_header)
    window.header_mascot = QLabel('m', window.app_header)
    window.header_mascot.setGeometry(4, 4, 60, 60)
    window.header_content = QWidget(window.app_header)
    window.header_content.setGeometry(80, 10, 600, 50)
    QPushButton('设置', window.header_content).setGeometry(10, 5, 90, 40)
    window.settings_scroll = QWidget()
    column.addWidget(window.settings_scroll)
    card = QFrame(window.settings_scroll)
    card.setObjectName('homeSettingsCard')
    card.setGeometry(10, 10, 400, 300)
    role = QFrame(card)
    role.setObjectName('recognitionRoleCard')
    role.setGeometry(10, 10, 120, 90)
    window.bottom_bar = QFrame()
    window.bottom_bar.setFixedHeight(60)
    column.addWidget(window.bottom_bar)
    window.show()
    app.processEvents()
    try:
        parts = lp.cover_parts(window)
        kinds = [part[0] for part in parts]
        assert kinds[0] == 'bar' and 'mascot' not in kinds
        assert {'pill', 'panel', 'block'} <= set(kinds)
        assert kinds[-1] == 'bar'
        from twobyteasr.design.theme_manager import theme_definition
        text = lp._cover_text(dict(client=[0, 0, 900, 600], next_page='recognition', scale=1.25, maximized=False),
                              parts, theme_definition('grape'))
        lines = text.splitlines()
        assert lines[0] == f'format {lp.COVER_FORMAT}' and 'next_page recognition' in lines and 'scale 1.25' in lines
        assert sum(line.startswith('part ') for line in lines) == len(parts)
        assert any(line.startswith('colors #19151c ') for line in lines)
    finally:
        window.close()
        window.deleteLater()


# 2026-11-19 (user report on the packaged daily, Windows 10 at 175%: "I see my icon, not the loading
# screen"): the daily keeps its old root launcher, so the app draws Home's skeleton itself, and a
# picture is kept at fractional scales too.
_COVER = '''format 1
next_page recognition
client 100 80 1320 880
scale 1.0
maximized 0
colors #19151c #3a2f44 #252028 #2f2935 #574c60
part bar 0 0 1320 104
part mascot 14 8 86 86
part panel 18 167 234 294
part block 268 270 666 300
'''


def test_the_kept_skeleton_is_drawn_by_the_app_when_it_still_fits(lp, app, tmp_path):
    (tmp_path / 'home.bmp').write_bytes(b'BM')
    (tmp_path / 'cover.txt').write_text(_COVER, 'utf8')
    meta = _meta(lp, app)
    assert lp.usable(meta, app) == 'skeleton'
    assert lp.usable(dict(meta, client=[0, 0, 1280, 800]), app) == 'picture'      # another size: not this skeleton
    assert lp.usable(dict(meta, scale=1.75), app) == 'picture'
    (tmp_path / 'cover.txt').write_text(_COVER.replace('format 1', 'format 9'), 'utf8')
    assert lp.read_cover(meta) is None


def test_with_a_kept_skeleton_the_same_launch_screen_is_drawn(lp, app, tmp_path, monkeypatch):
    from PySide6.QtGui import QImage
    monkeypatch.setenv('TWOBYTEASR_LAUNCH_MOTION', '0')
    (tmp_path / 'cover.txt').write_text(_COVER, 'utf8')
    shell = lp._make_shell(app, _meta(lp, app, picture=False), 'skeleton')
    assert shell is not None and shell.kind == 'skeleton'
    image = QImage(shell.size(), QImage.Format.Format_ARGB32)
    shell.render(image)
    assert image.pixelColor(120, 300).name() == '#19151c'           # no skeleton panel any more
    assert image.pixelColor(40, 40).name() == '#19151c'
    shell.deleteLater()


def test_a_grab_a_pixel_off_at_a_fractional_scale_is_kept_at_the_windows_size(lp, app):
    from PySide6.QtGui import QColor, QPixmap
    grabbed = QPixmap(2400, 1351)
    grabbed.setDevicePixelRatio(1.75)
    grabbed.fill(QColor('#ff0000'))
    image = lp._fit_picture(grabbed, 2400, 1352, '#19151c')
    assert image is not None and (image.width(), image.height()) == (2400, 1352)
    assert image.pixelColor(1200, 600).name() == '#ff0000' and image.pixelColor(1200, 1351).name() == '#19151c'
    assert lp._fit_picture(grabbed, 2400, 1360, '#19151c') is None                 # a different window


def test_a_close_on_another_page_keeps_the_skeleton(lp, app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from twobyteasr.app import floating_anchor
    window = QWidget()
    meta = _meta(lp, app, picture=False)
    (tmp_path / 'meta.json').write_text(json.dumps(meta), 'utf8')
    (tmp_path / 'cover.txt').write_text(_COVER, 'utf8')
    monkeypatch.setattr(floating_anchor, 'client_pixels', lambda w: tuple(meta['client']))
    monkeypatch.setattr(lp, '_conditions', lambda w: dict(theme='grape', language='zh', zoom=100,
                                                          background='#19151c', foreground='#a69ba6'))
    monkeypatch.setattr(lp, 'screens_signature', lambda a: meta['screens'])
    monkeypatch.setattr(lp, '_home_is_clean', lambda w: False)
    monkeypatch.setattr(lp, '_next_page', lambda: 'recognition')
    window.devicePixelRatioF = lambda: 1.0
    assert lp.remember(window) is False
    lp.flush()
    assert (tmp_path / 'cover.txt').is_file()                           # same place, size, theme: kept
    monkeypatch.setattr(lp, '_conditions', lambda w: dict(theme='sand', language='zh', zoom=100,
                                                          background='#f4ecdf', foreground='#6b5d4f'))
    lp.remember(window)
    lp.flush()
    assert not (tmp_path / 'cover.txt').exists()                        # another theme: it would be wrong
    window.deleteLater()
