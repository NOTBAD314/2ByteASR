"""BunnyMascot resized before her new layers are ready (2026-11-27).

User: switching scenes (Home <-> Subtitle Studio, the chat, the tutorial) tore 兔白 apart: head,
hair, ears and body each drawn somewhere else. Studio makes her smaller; her layers for the new
height are prepared in the background (seconds, while a page motion plays), and meanwhile the
layers of the old height were drawn at positions worked out for the new one. Until the new set
arrives, the old set is now drawn as one picture scaled to her new height.
"""
import time

import pytest


def _wait_layers(widget, timeout=20.0):
    from PySide6.QtWidgets import QApplication
    deadline = time.monotonic() + timeout
    key = (widget.mascot_height, widget.devicePixelRatioF())
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if widget._layers() is not None and widget._scale_key == key:
            return True
        time.sleep(0.01)
    return False


def _alpha(widget):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    widget.render(image)
    bits = bytes(image.constBits())
    return image.width(), image.height(), bits[3::4]


@pytest.mark.parametrize("old, new", [(150, 83), (66, 117)])
def test_resized_before_ready_stays_in_one_piece(old, new):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.design.bunny_mascot import BunnyMascot
    QApplication.instance() or QApplication([])
    widget = BunnyMascot(height=old, motion="swing")
    if not widget.available:
        pytest.skip("mascot assets are not available")
    widget.clock = lambda: 100.0
    widget._started = 100.0
    widget.reduced_motion = True          # one still pose, nothing moving between the two frames
    widget.show()
    try:
        if not _wait_layers(widget):
            pytest.skip("mascot layers were not prepared")
        widget._timer.stop()
        assets = widget._assets
        assets.cache.pop((new, widget.devicePixelRatioF()), None)
        widget.set_mascot_height(new)
        # The new set is being prepared on a worker; nothing has been delivered to this thread yet.
        assert widget._scale_key[0] == old
        width, height, stale = _alpha(widget)
        assert _wait_layers(widget)
        assert widget._scale_key[0] == new
        _, _, fresh = _alpha(widget)
        covered = sum(1 for a in fresh if a > 128)
        assert covered > 200
        # Only resampling may differ: the outline matches to a thin rim, not whole parts moved.
        wrong = sum(1 for a, b in zip(stale, fresh) if (a > 128) != (b > 128))
        assert wrong / covered < 0.06, (wrong, covered)
    finally:
        widget.close()

