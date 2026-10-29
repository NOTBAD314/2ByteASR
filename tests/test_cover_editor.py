import io
import json
from pathlib import Path
import zipfile

import pytest
from PIL import Image
from PySide6.QtCore import QPoint, Qt, QCoreApplication, QEvent
from PySide6.QtGui import QFontDatabase, QImage, QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.cover.cover_document import CoverDocument
from twobyteasr.cover.cover_render import CoverRenderer, export_image, read_image_bytes, text_font


@pytest.fixture(scope='module')
def app():
    app = QApplication.instance() or QApplication([])
    for path in (Path(__file__).resolve().parents[1]/'assets/fonts').glob('*.otf'):
        QFontDatabase.addApplicationFont(str(path))
    yield app


def png(color=(20, 160, 80, 128), size=(180, 100)):
    output = io.BytesIO()
    Image.new('RGBA', size, color).save(output, format='PNG')
    return output.getvalue()


def test_portable_save_originals_restore_and_atomic_failure(tmp_path, app, monkeypatch):
    data = png()
    doc = CoverDocument(width=640, height=360)
    bottom = doc.add_image(data, '透明底图.png', (180, 100), background=True)
    title = doc.add_text('中文标题\n第二行仍可编辑')
    title.style.update(size=38, stroke=2, shadow_blur=3)
    doc.source = dict(milliseconds=74500, project_id='offline-fixture', subtitles=True)
    file = tmp_path/'可移动封面.2bytecover'
    doc.save(file)
    before = file.read_bytes()
    moved = tmp_path/'新目录';moved.mkdir()
    moved_file = moved/file.name
    file.rename(moved_file)
    loaded = CoverDocument.load(moved_file)
    assert loaded.assets[bottom.asset] == data
    assert loaded.layer(title.id).text == title.text
    assert loaded.source == doc.source
    assert loaded.signature() == doc.signature()
    import twobyteasr.cover.cover_document as module
    monkeypatch.setattr(module.os, 'replace', lambda *args: (_ for _ in ()).throw(PermissionError('readonly')))
    loaded.layer(title.id).text = '不能覆盖原件'
    with pytest.raises(PermissionError):
        loaded.save(moved_file)
    assert moved_file.read_bytes() == before
    assert not list(moved.glob('*.partial'))


def test_missing_asset_keeps_layers_and_refuses_destructive_save(tmp_path, app):
    doc = CoverDocument(width=640, height=360)
    layer = doc.add_image(png(), '贴图.png', (180, 100))
    title = doc.add_text('保留其他图层')
    broken = tmp_path/'missing.2bytecover'
    with zipfile.ZipFile(broken, 'w') as archive:
        archive.writestr('document.json', json.dumps(doc.manifest()))
    loaded = CoverDocument.load(broken)
    assert loaded.layer(title.id).text == title.text and loaded.layer(layer.id)
    assert loaded.warnings
    with pytest.raises(ValueError, match='重新定位'):
        loaded.save(broken)
    loaded.layer(layer.id).asset = loaded.add_asset(png(), '重新定位.png')
    loaded.save(broken)
    assert not CoverDocument.load(broken).warnings


def test_orientation_and_transparent_exports_share_pixels(tmp_path, app):
    source = Image.new('RGB', (80, 40), (230, 80, 30))
    exif = Image.Exif();exif[274] = 6
    stream = io.BytesIO();source.save(stream, format='JPEG', exif=exif)
    oriented = read_image_bytes(stream.getvalue())
    assert (oriented.width(), oriented.height()) == (40, 80)
    doc = CoverDocument(width=640, height=360)
    layer = doc.add_image(png(), '透明.png', (180, 100))
    layer.x, layer.y = 0, 0
    title = doc.add_text('真实中文\n阴影与描边')
    title.style.update(size=42, stroke=2, shadow_blur=4)
    renderer = CoverRenderer()
    expected = renderer.render(doc)
    output = tmp_path/'输出.png';export_image(doc, output)
    actual = QImage(str(output)).convertToFormat(expected.format())
    assert actual == expected
    assert actual.pixelColor(630, 350).alpha() == 0
    assert actual.pixelColor(5, 5).alpha() == 128
    doc.jpeg_background = '#ffffff'
    jpg = tmp_path/'输出.jpg';export_image(doc, jpg, quality=100)
    jpg_image = QImage(str(jpg))
    assert jpg_image.size() == actual.size()
    assert jpg_image.pixelColor(630, 350).red() > 250
    assert not jpg_image.hasAlphaChannel()


def test_canvas_ratio_and_replacing_background_keeps_layers(app):
    doc = CoverDocument(width=640, height=360)
    background = doc.add_image(png(), '底图.png', (180, 100), background=True)
    title = doc.add_text('始终保留')
    doc.width, doc.height = 360, 640
    doc.fit_background((180, 100))
    assert background.width/background.height == pytest.approx(1.8)
    doc.background_fit = 'fill';doc.fit_background((180, 100))
    assert background.x < 0 and background.height == 640
    doc.add_image(png(size=(100, 200)), '替换.png', (100, 200), background=True)
    assert doc.background_id == background.id and doc.layer(title.id).text == '始终保留'
    assert len(doc.layers) == 2


def test_missing_font_preserves_original_choice(app):
    doc = CoverDocument();layer = doc.add_text('不静默替换')
    layer.style.update(family='缺失字体测试xyz', weight=888, font_style='Unavailable')
    _, warning, face = text_font(layer.style)
    assert warning and face.family != layer.style['family']
    assert layer.style['family'] == '缺失字体测试xyz' and layer.style['weight'] == 888


def test_outline_does_not_eat_heavy_fill(app):
    from twobyteasr.cover.cover_render import render_text
    doc = CoverDocument(width=1200, height=600)
    layer = doc.add_text('重字重保持完整')
    layer.style.update(size=96, stroke=0, shadow=False)
    plain, _ = render_text(layer)
    layer.style['stroke'] = 10
    outlined, _ = render_text(layer)
    def white_pixels(image):
        import numpy as np
        rgba = image.convertToFormat(QImage.Format_RGBA8888)
        values = np.frombuffer(rgba.constBits(), dtype=np.uint8).reshape(rgba.height(), rgba.width(), 4)
        return int(((values[:, :, :3] > 245).all(axis=2) & (values[:, :, 3] > 245)).sum())
    assert white_pixels(outlined) >= white_pixels(plain)*.99


def test_real_drag_resize_zoom_and_independent_undo(app):
    from twobyteasr.cover.cover_canvas import CoverSession, CoverView
    doc = CoverDocument(width=640, height=360)
    layer = doc.add_image(png(), '贴图.png', (180, 100))
    session = CoverSession(doc)
    view = CoverView(session);view.resize(800, 540);view.show();app.processEvents();view.fit_canvas()
    item = view.items_by_id[layer.id]
    start = view.mapFromScene(item.sceneBoundingRect().center())
    QTest.mousePress(view.viewport(), Qt.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), start+QPoint(60, 30), delay=30)
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=start+QPoint(60, 30))
    assert session.undo.count() == 1
    moved = session.document.layer(layer.id)
    assert moved.x > layer.x+20
    session.undo.undo()
    assert session.document.layer(layer.id).x == layer.x
    session.undo.redo()
    item = view.items_by_id[layer.id]
    fixed = item.sceneBoundingRect().topLeft()
    corner = view.mapFromScene(item.sceneBoundingRect().bottomRight())
    QTest.mousePress(view.viewport(), Qt.LeftButton, pos=corner)
    QTest.mouseMove(view.viewport(), corner+QPoint(65, 45), delay=30)
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=corner+QPoint(65, 45))
    resized = session.document.layer(layer.id)
    assert resized.width > moved.width
    assert resized.width/resized.height == pytest.approx(1.8)
    assert resized.x == pytest.approx(fixed.x()) and resized.y == pytest.approx(fixed.y())
    signature = session.document.signature()
    view.set_zoom(.2);view.set_zoom(1);view.fit_canvas()
    assert session.document.signature() == signature
    view.close();view.deleteLater()


def test_ime_delete_select_all_and_text_undo_stay_in_cover(app):
    from twobyteasr.cover.cover_editor import CoverEditor
    editor = CoverEditor(CoverDocument(width=640, height=360))
    editor.show();app.processEvents();editor.add_text();app.processEvents()
    title_id = next(iter(editor.session.selected))
    editor.text_edit.selectAll()
    event = QInputMethodEvent();event.setCommitString('中文输入法\n第二行')
    QApplication.sendEvent(editor.text_edit, event)
    app.processEvents()
    assert editor.session.document.layer(title_id).text == '中文输入法\n第二行'
    QTest.keyClick(editor.text_edit, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClick(editor.text_edit, Qt.Key_Delete)
    app.processEvents()
    assert editor.session.document.layer(title_id).text == ''
    assert len(editor.session.document.layers) == 1
    QTest.keyClick(editor.text_edit, Qt.Key_Z, Qt.ControlModifier)
    assert len(editor.session.document.layers) == 1
    assert editor.session.document.layer(title_id).text
    editor.session.saved_signature = editor.session.document.signature()
    editor.close();QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_close_cancel_and_failed_save_preserve_document(app, tmp_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox
    from twobyteasr.cover.cover_editor import CoverEditor
    editor = CoverEditor(CoverDocument(width=640, height=360))
    editor.show();editor.add_text();app.processEvents()
    signature = editor.session.document.signature()
    def cancel():
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, QMessageBox):dialog.button(QMessageBox.Cancel).click()
    QTimer.singleShot(30, cancel)
    editor.close()
    assert editor.isVisible() and editor.session.dirty
    assert editor.session.document.signature() == signature
    editor.save_document(tmp_path/'missing'/'failure.2bytecover')
    import time
    deadline=time.monotonic()+3
    while editor.busy and time.monotonic()<deadline:
        app.processEvents();time.sleep(.005)
    assert not editor.busy and editor.session.dirty and not editor.session.filename
    assert editor.session.document.signature()==signature and '失败' in editor.status.text()
    assert editor.toolbar.isEnabled() and editor.splitter.isEnabled()
    editor.session.saved_signature=signature;editor.close()
    QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
