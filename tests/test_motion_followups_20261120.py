# -*- coding: utf-8 -*-
"""2026-11-20 motion follow-ups: sidebar pages slide vertically, Home slides further, entering the
workbench moves left and grows, the launch screen keeps moving, Home's readiness chips are not
rebuilt for nothing, and the AI settings stop re-reading the key store hundreds of times."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, QRectF
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QWidget


def _app():
    return QApplication.instance() or QApplication([])


def _picture(color, size=(400, 300)):
    pixmap = QPixmap(*size)
    pixmap.fill(QColor(color))
    return pixmap


def test_sidebar_pages_slide_vertically_with_the_navigation():
    from twobyteasr.design.transitions import PageMotion
    from twobyteasr.design.ui_navigation import WORKSPACE_ORDER, workspace_motion
    _app()
    host = QWidget()
    host.resize(1000, 700)
    try:
        for source in WORKSPACE_ORDER:
            for target in WORKSPACE_ORDER:
                if source == target:
                    continue
                direction, axis = workspace_motion(source, target)
                motion = PageMotion(direction, axis=axis)
                motion.prepare(host)
                assert motion._offset(.5).x() == 0
                assert (motion._offset(.5).y() > 0) == (WORKSPACE_ORDER[target] > WORKSPACE_ORDER[source])
        assert workspace_motion(None, 'workshop') == (1, 'x')
        assert workspace_motion('workshop', None) == (-1, 'x')
    finally:
        host.deleteLater()


def test_workbench_grows_from_the_left_and_projects_grow_from_their_source():
    from twobyteasr.design import transitions
    _app()
    host = QWidget()
    host.resize(400, 300)
    host.show()
    overlay = transitions.PageCrossfade(host, _picture('#ff0000'))
    try:
        overlay.enter_workbench(_picture('#0000ff'), '#000000')
        image = QImage(overlay.size(), QImage.Format.Format_RGB32)

        def frame(k):
            overlay.progress = k
            image.fill(QColor('#00ff00'))
            overlay.render(image)
            return image

        assert overlay._entry_rect().center().x() < host.width() / 2
        for x in (15, 150, 280):
            origin = QRect(host.mapToGlobal(host.rect().topLeft()), host.size())
            origin = QRect(origin.x() + x, origin.y() + 75, 90, 80)
            overlay.enter_workbench(_picture('#0000ff'), '#000000', origin)
            assert overlay._entry_rect().center().x() == x + 45
            assert overlay._entry_rect().center().y() == 115
        start = frame(0.0)
        assert start.pixelColor(200, 150).red() == 255            # the page being left, whole
        middle = frame(0.5)
        assert middle.pixelColor(395, 150) != QColor('#00ff00')   # covered: nothing live shows twice
        assert middle.pixelColor(280, 150).blue() > 240
        end = frame(0.999)
        assert end.pixelColor(200, 150).blue() > 240             # the workbench in place
    finally:
        overlay.finish()
        host.deleteLater()


def test_the_launch_screen_frame_moves_over_time():
    from twobyteasr.app.launch_motion import LaunchMotion
    from twobyteasr.app.launch_screen import LaunchScreen, Sprites, palette
    _app()
    shell = QWidget()
    shell.resize(800, 600)
    base = QImage(800, 600, QImage.Format.Format_RGB32)
    colors = palette('grape')
    base.fill(QColor(colors['background']))
    screen = LaunchScreen(800, 600, colors, Sprites.build(colors, 'zh', 1.0), 'zh', 3.0)
    motion = LaunchMotion(shell, base, kind='first', scale=1.0, screen=screen, colors=colors)
    first = QImage(motion.frame)
    changed = motion._draw(0.3)
    assert changed and motion.frame != first
    later = QImage(motion.frame)
    motion._draw(0.9)
    assert motion.frame != later
    shell.deleteLater()


def test_home_readiness_chips_stay_when_nothing_changed():
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton
    from twobyteasr.app.ui import MainWindow
    _app()
    host = QWidget()
    host.resize(1800, 200)

    class Fake:
        _refresh_readiness_bar = MainWindow._refresh_readiness_bar
        _refresh_start_tooltip = MainWindow._refresh_start_tooltip

        def __init__(self):
            self.readiness_chips_layout = QHBoxLayout(host)
            self.media_paths = []
            self.start_hint = QLabel(host)
            self.start_button = QPushButton(host)
            self._ui_language = 'zh'

        def width(self):
            return host.width()

        def _choose_media(self):
            pass

        def _recognition_recovery(self, *_args):
            pass

    fake = Fake()
    fake._refresh_readiness_bar([('primary', '需要下载')])
    layout = fake.readiness_chips_layout
    first = [layout.itemAt(i).widget() for i in range(layout.count())]
    assert len(first) == 2
    for _ in range(5):
        fake._refresh_readiness_bar([('primary', '需要下载')])
    assert [layout.itemAt(i).widget() for i in range(layout.count())] == first   # the same chips
    fake.media_paths = ['clip.mp4']
    fake._refresh_readiness_bar([('primary', '需要下载')])
    assert layout.count() == 1                                                    # 选择素材 left
    host.deleteLater()


def test_the_key_store_is_read_once_per_burst_and_after_every_write(tmp_path, monkeypatch):
    from twobyteasr.providers import llm_config
    path = tmp_path / 'secrets.dat'
    monkeypatch.setattr(llm_config, 'secrets_path', lambda: path)
    monkeypatch.setattr(llm_config, 'keychain_storage_enabled', lambda: False)
    monkeypatch.setattr(llm_config, 'session_credentials_enabled', lambda: False)
    monkeypatch.setattr(llm_config, '_RECENT_SECRETS', None)
    reads = []
    original = llm_config._read_secret_file
    monkeypatch.setattr(llm_config, '_read_secret_file', lambda p: reads.append(p) or original(p))
    with llm_config.secrets_read_once():
        for _ in range(50):
            llm_config._read_secrets()
        assert len(reads) == 1
        if os.name == 'nt':                # DPAPI: a write of ours is seen at once
            llm_config._write_encrypted_secrets({'schema': 2, 'TEST_KEY': 'value'})
            assert llm_config._read_secrets().get('TEST_KEY') == 'value'
            assert len(reads) == 2
    before = len(reads)
    llm_config._read_secrets()
    llm_config._read_secrets()
    assert len(reads) == before + 2        # outside the block every read looks at the file
