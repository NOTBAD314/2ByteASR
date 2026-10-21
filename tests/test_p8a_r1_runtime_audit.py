from pathlib import Path

from PIL import Image
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from twobyteasr.acceptance.p8a_r1_runtime_audit import image_metrics


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_mpv_screenshot_metrics_require_real_nonblack_pixels(tmp_path: Path):
    target = tmp_path / "frame.png"
    Image.new("RGB", (32, 18), (128, 64, 32)).save(target)

    metrics = image_metrics(target)

    assert metrics["sha256"]
    assert metrics["width"] == 32
    assert metrics["height"] == 18
    assert metrics["nonblack_ratio"] == 1.0
    assert metrics["mean_luma"] > 5.0


def test_real_qt_drag_and_drop_events_are_constructible():
    _app()
    mime = QMimeData()
    drag = QDragEnterEvent(
        QPoint(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    drop = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    assert drag.type() == QDragEnterEvent.Type.DragEnter
    assert drop.type() == QDropEvent.Type.Drop
