"""Compare mascot frames before and after the bitmap drawing change."""
import time

import pytest


@pytest.fixture
def mascot():
    from PySide6.QtWidgets import QApplication
    from twobyteasr.design.bunny_mascot import BunnyMascot
    app = QApplication.instance() or QApplication([])
    widget = BunnyMascot(height=120, motion="swing")
    assert widget.available, "mascot assets are not available"
    clock = [100.0]
    widget.clock = lambda: clock[0]
    widget._started = clock[0]
    widget._next_blink = float("inf")
    widget.show()
    deadline = time.monotonic() + 20
    while widget._layers() is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert widget._layers() is not None, "mascot layers were not prepared"
    widget._timer.stop()
    try:
        yield widget, clock
    finally:
        widget.close()


def _frame(widget):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QImage, QRegion
    from PySide6.QtWidgets import QWidget
    image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    widget.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    return bytes(image.constBits())


def test_layers_without_antialiasing_look_the_same(mascot, monkeypatch):
    import twobyteasr.design.bunny_mascot as module
    from PySide6.QtGui import QPainter
    from PySide6.QtWidgets import QWidget
    from twobyteasr.design.bunny_moves import MOVES, STICKERS
    from twobyteasr.design.bunny_props import PROPS

    class AntialiasedPainter(QPainter):     # what paintEvent did before
        def __init__(self, *args):
            super().__init__(*args)
            if args and isinstance(args[0], QWidget):
                self.setRenderHint(QPainter.RenderHint.Antialiasing)

    widget, clock = mascot
    plain = module.QPainter
    frames = differing = worst = 0
    names = (list(MOVES)[:12], list(STICKERS), list(PROPS))
    for index, name in enumerate(names[0]):
        clock[0] = 100.0 + index
        widget.unstick()
        assert widget.play(name)
        assert widget.stick(names[1][index % len(names[1])])
        assert widget.hold(names[2][index % len(names[2])])
        for step in (5, 17, 29):
            clock[0] = 100.0 + index + step / 60.0
            monkeypatch.setattr(module, "QPainter", AntialiasedPainter)
            before = _frame(widget)
            monkeypatch.setattr(module, "QPainter", plain)
            after = _frame(widget)
            assert any(after[3::4])
            frames += 1
            for px in range(0, len(before), 4):
                if before[px:px + 4] != after[px:px + 4]:
                    differing += 1
                    worst = max(worst, max(abs(before[px + c] - after[px + c]) for c in range(4)))
    assert worst <= 32
    assert differing / frames <= 12


def test_every_move_sticker_and_prop_still_paints(mascot):
    from twobyteasr.design.bunny_moves import MOVES, STICKERS
    from twobyteasr.design.bunny_props import PROPS
    widget, clock = mascot
    for activate, deactivate, names in (
        (widget.play, widget.stop_move, MOVES),
        (widget.stick, widget.unstick, STICKERS),
        (widget.hold, widget.drop_prop, PROPS),
    ):
        for name in names:
            assert activate(name)
            clock[0] += 0.12
            assert any(_frame(widget)[3::4]), name
            deactivate()
