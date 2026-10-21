"""Real Qt events with the repository's isolated user-data profile."""
import builtins

import pytest
from PySide6.QtCore import QByteArray, QBuffer, QEvent, QIODevice, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QFocusEvent, QImage, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget

from twobyteasr.cover.cover_canvas import CoverSession, CoverView
from twobyteasr.cover.cover_document import CoverDocument
from twobyteasr.cover.cover_render import CoverRenderer, export_image
from twobyteasr.cover.cover_snap.qt import install


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def document():
    image = QImage(80, 60, QImage.Format_ARGB32)
    image.fill(QColor('#d08070'))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    assert image.save(buffer, 'PNG')
    doc = CoverDocument(width=320, height=180)
    layer = doc.add_image(bytes(data), 'fixture.png', (80, 60))
    layer.x, layer.y, layer.width, layer.height = 70, 40, 80, 60
    return doc


@pytest.fixture
def canvas(app):
    host = QWidget()
    layout = QVBoxLayout(host)
    session = CoverSession(document())
    view = CoverView(session)
    layout.addWidget(view)
    controls = QHBoxLayout()
    layout.addLayout(controls)
    controller = install(view, controls)
    host.resize(900, 600)
    host.show()
    app.processEvents()
    view.set_zoom(1)
    yield session, view, controller, controls
    host.close()
    host.deleteLater()
    app.processEvents()


def drag(canvas, x, y, *, alt=False, release=True):
    session, view, controller, _ = canvas
    layer = session.document.layers[0]
    item = view.items_by_id[layer.id]
    # The large-image case may put its centre outside the viewport.
    visible = view.mapFromScene(item.sceneBoundingRect()).boundingRect().intersected(view.viewport().rect())
    start = visible.center()
    end = start+QPoint(round((x-layer.x)*view.transform().m11()),
                      round((y-layer.y)*view.transform().m22()))
    QTest.mousePress(view.viewport(), Qt.LeftButton, pos=start)
    modifiers = Qt.AltModifier if alt else Qt.NoModifier
    move = QMouseEvent(QEvent.MouseMove, QPointF(end), QPointF(view.viewport().mapToGlobal(end)),
                       Qt.NoButton, Qt.LeftButton, modifiers)
    QApplication.sendEvent(view.viewport(), move)
    if release:
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=end)
    return end


def test_disabled_uses_original_drag(canvas):
    session, _, controller, _ = canvas
    assert not controller.button.isChecked()
    drag(canvas, 235, 115)
    layer = session.document.layers[0]
    assert (layer.x, layer.y) == pytest.approx((235, 115))
    assert session.undo.count() == 1


@pytest.mark.parametrize('zoom', [.5, 1, 2])
def test_drag_snap_guides_and_one_undo(canvas, zoom):
    session, view, controller, _ = canvas
    view.set_zoom(zoom)
    controller.button.setChecked(True)
    end = drag(canvas, 240-4/zoom, 120-4/zoom, release=False)
    assert (session.document.layers[0].x, session.document.layers[0].y) == (240, 120)
    assert controller.horizontal and controller.vertical
    assert session.undo.count() == 0
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=end)
    assert controller.horizontal is None and controller.vertical is None
    assert session.undo.count() == 1
    session.undo.undo()
    assert (session.document.layers[0].x, session.document.layers[0].y) == (70, 40)
    session.undo.redo()
    assert (session.document.layers[0].x, session.document.layers[0].y) == (240, 120)


def test_alt_and_overshoot_are_free(canvas):
    session, _, controller, _ = canvas
    controller.button.setChecked(True)
    drag(canvas, 235, 115, alt=True)
    assert (session.document.layers[0].x, session.document.layers[0].y) == (235, 115)
    drag(canvas, -40, -30)
    assert (session.document.layers[0].x, session.document.layers[0].y) == (-40, -30)


def test_same_gesture_can_leave_and_reacquire_edge(canvas):
    session, view, controller, _ = canvas
    controller.button.setChecked(True)
    end = drag(canvas, 235, 115, release=False)
    for delta, expected in [(QPoint(-6, 0), 240), (QPoint(-25, 0), 210), (QPoint(0, 0), 240)]:
        point = end+delta
        event = QMouseEvent(QEvent.MouseMove, QPointF(point), QPointF(view.viewport().mapToGlobal(point)),
                            Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(view.viewport(), event)
        assert session.document.layers[0].x == expected
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=end)
    assert session.undo.count() == 1


def test_enabled_does_not_snap_resize_or_text(canvas):
    session, view, controller, _ = canvas
    controller.button.setChecked(True)
    layer = session.document.layers[0]
    layer.x, layer.y = 5, 5
    session.selected = {layer.id}
    session.changed.emit()
    start = view.mapFromScene(view.items_by_id[layer.id].sceneBoundingRect().bottomRight())
    QTest.mousePress(view.viewport(), Qt.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), start+QPoint(20, 15))
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=start+QPoint(20, 15))
    resized = session.document.layers[0]
    assert (resized.x, resized.y) == (5, 5) and resized.width > 80
    title = session.document.add_text('Text')
    title.x, title.y, title.width = 70, 40, 80
    title.style.update(size=20, stroke=0, shadow=False)
    session.document.layers = [title]
    session.selected.clear()
    session.changed.emit()
    drag(canvas, 5, 5)
    assert (session.document.layers[0].x, session.document.layers[0].y) == pytest.approx((5, 5), abs=1)


def test_big_image_snaps_at_negative_position(canvas):
    session, _, controller, _ = canvas
    layer = session.document.layers[0]
    layer.width, layer.height = 400, 240
    layer.x, layer.y = -20, -20
    session.changed.emit()
    controller.button.setChecked(True)
    drag(canvas, -75, -55)
    assert (session.document.layers[0].x, session.document.layers[0].y) == (-80, -60)


def test_keyboard_numeric_sync_and_detach_do_not_snap(canvas, app):
    session, view, controller, controls = canvas
    controller.button.setChecked(True)
    drag(canvas, 235, 115)
    QTest.keyClick(view, Qt.Key_Left)
    assert session.document.layers[0].x == 239
    session.edit('numeric', lambda doc: setattr(doc.layers[0], 'x', 237))
    assert session.document.layers[0].x == 237
    assert install(view, controls) is controller
    before = session.document.signature()
    controller.detach()
    assert view.drag_constraint is None
    assert session.document.signature() == before
    drag(canvas, 235, 115)
    assert (session.document.layers[0].x, session.document.layers[0].y) == (235, 115)


def test_locked_and_multi_selected_are_unchanged(canvas):
    session, view, controller, _ = canvas
    controller.button.setChecked(True)
    layer = session.document.layers[0]
    layer.locked = True
    session.changed.emit()
    drag(canvas, 235, 115)
    assert session.document.layers[0].x == 70
    layer.locked = False
    second = session.document.add_image(next(iter(session.document.assets.values())), 'second.png', (80, 60))
    second.x, second.y = 180, 40
    session.selected = {layer.id, second.id}
    session.changed.emit()
    drag(canvas, 235, 115)
    assert session.document.layers[0].x == 235
    assert session.document.layers[1].x-session.document.layers[0].x == 110


def test_export_excludes_guides_and_focus_loss_clears(canvas, tmp_path):
    session, view, controller, _ = canvas
    controller.button.setChecked(True)
    end = drag(canvas, 235, 115, release=False)
    expected = CoverRenderer().render(session.document)
    output = tmp_path/'cover.png'
    export_image(session.document, output)
    assert QImage(str(output)).convertToFormat(expected.format()) == expected
    QApplication.sendEvent(view, QFocusEvent(QEvent.FocusOut))
    assert controller.active_id is None
    assert controller.horizontal is None and controller.vertical is None
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=end)


def test_editor_toggle_is_session_only_and_missing_module_falls_back(app, monkeypatch):
    from twobyteasr.cover.cover_editor import CoverEditor
    editor = CoverEditor(document())
    signature = editor.session.document.signature()
    editor._cover_snap.button.click()
    assert editor._cover_snap.enabled
    assert editor.session.document.signature() == signature and editor.session.undo.count() == 0
    editor.session.saved_signature = signature
    editor.close()
    original_import = builtins.__import__

    def without_optional_module(name, *args, **kwargs):
        if name == 'cover_snap.qt':
            raise ModuleNotFoundError('optional package not installed', name='twobyteasr.cover.cover_snap')
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', without_optional_module)
    fallback = CoverEditor(document())
    assert fallback.view.drag_constraint is None
    assert not hasattr(fallback, '_cover_snap')
    fallback.session.saved_signature = fallback.session.document.signature()
    fallback.close()
