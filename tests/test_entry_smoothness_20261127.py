"""2026-11-27 fixes: a real blur behind the loading card, a library that does not rebuild for cover stamps,
and Studio modules loaded back to back while someone waits."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


def test_gaussian_backdrop_fills_the_size_without_fading_edges():
    from twobyteasr.design.soft_blur import gaussian_backdrop
    image = QImage(640, 360, QImage.Format.Format_RGB32)
    image.fill(QColor('#3050a0'))
    for x in range(0, 640, 40):                 # sharp stripes: a blur must soften them
        for y in range(360):
            image.setPixelColor(x, y, QColor('#ffffff'))
    result = gaussian_backdrop(QPixmap.fromImage(image), QSize(1600, 900)).toImage()
    assert result.size() == QSize(1600, 900)
    for x, y in ((0, 0), (1599, 0), (0, 899), (1599, 899), (800, 450)):
        color = result.pixelColor(x, y)
        assert color.alpha() == 255, (x, y)                      # the edges did not fade to transparent
        assert color.blue() > 120 and color.red() < 200, (x, y)  # still the picture's blue, stripes blurred away


def test_gaussian_backdrop_of_nothing_is_empty():
    from twobyteasr.design.soft_blur import gaussian_backdrop
    assert gaussian_backdrop(QPixmap(), QSize(10, 10)).isNull()


def test_library_signature_ignores_the_cover_file_stamp():
    from twobyteasr.studio.studio_hub import _library_display_signature
    seeded = {'path': 'a.2byteasr', 'name': 'A', 'cover_path': 'preview/project-cover.jpg', 'cue_count': 3}
    scanned = dict(seeded, cover_mtime_ns=1794242693208860100, cover_size=27650)
    assert _library_display_signature([seeded]) == _library_display_signature([scanned])
    assert _library_display_signature([seeded]) != _library_display_signature([dict(seeded, name='B')])


def test_preloader_loads_back_to_back_while_someone_waits():
    from twobyteasr.app.studio_module_preload import StudioModulePreloader
    calls, turns = [], []
    loader = StudioModulePreloader(importer=calls.append, modules=[f'qa_{i}' for i in range(6)],
                                   urgent=lambda: True)
    original = loader._step

    def counted():
        turns.append(len(calls))
        original()
    loader.timer.timeout.disconnect()
    loader.timer.timeout.connect(counted)
    done = []
    loader.ready.connect(lambda: done.append(True))
    loader.start()
    QTest.qWait(80)
    assert calls == [f'qa_{i}' for i in range(6)] and done == [True]
    assert len(turns) <= 3                      # several modules per turn, not one per 16 ms
    loader.deleteLater()
