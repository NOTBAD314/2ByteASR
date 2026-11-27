"""Cover picker B 大圖預覽 + editor A 圓角工具箱 (2026-11-27)."""
import time

import pytest
from PySide6.QtCore import QBuffer, QIODevice, QSettings
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from twobyteasr.cover.cover_document import CoverDocument
from twobyteasr.cover.cover_editor import CoverEditor
from twobyteasr.cover.cover_local_library import LocalCoverLibrary
from twobyteasr.cover.cover_templates_ui import TemplatePicker


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def png():
    image = QImage(64, 36, QImage.Format_RGB32)
    image.fill(0x335544)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, 'PNG')
    return bytes(buffer.data())


def template_document():
    document = CoverDocument(width=640, height=360)
    background = document.add_image(png(), '底图', (64, 36), background=True)
    document.background_id = background.id
    title = document.add_text('原来的主标题')
    title.style['size'] = 60
    subtitle = document.add_text('原来的副标题')
    subtitle.style['size'] = 24
    tag = document.add_text('固定标记')
    tag.locked = True
    return document, title, subtitle, tag


def wait(app, editor):
    deadline = time.monotonic() + 8
    while editor.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)


def test_titles_typed_in_the_picker_open_in_the_editor(app, tmp_path):
    library = LocalCoverLibrary(tmp_path / 'library')
    document, title, subtitle, tag = template_document()
    entry = library.save_native('测试模板', document, png())
    settings = QSettings(str(tmp_path / 's.ini'), QSettings.IniFormat)
    picker = TemplatePicker(library, settings, local=True)
    for row in range(picker.cards.count()):
        if picker.cards.item(row).data(256)['id'] == entry['id']:
            picker.cards.setCurrentRow(row)
    # the two biggest unlocked text layers become fields, the locked tag does not
    assert [key for key, _box in picker._fields] == [title.id, subtitle.id]
    picker._fields[0][1].setPlainText('新的主标题')
    picker.use()
    assert picker.selected['id'] == entry['id']
    assert picker.selected_texts == {title.id: '新的主标题'}

    editor = CoverEditor(CoverDocument(width=640, height=360))
    editor.library = library
    editor.apply_template(entry, texts=picker.selected_texts)
    wait(app, editor)
    texts = {layer.id: layer.text for layer in editor.session.document.layers if layer.kind == 'text'}
    assert texts[title.id] == '新的主标题' and texts[subtitle.id] == '原来的副标题' and texts[tag.id] == '固定标记'
    editor.session.saved_signature = editor.session.document.signature()
    editor.close()


def test_delete_asks_inside_the_window_and_rename_happens_in_place(app, tmp_path):
    library = LocalCoverLibrary(tmp_path / 'library')
    entry = library.save_native('要改名的模板', template_document()[0], png())
    picker = TemplatePicker(library, QSettings(str(tmp_path / 's.ini'), QSettings.IniFormat), local=True)
    for row in range(picker.cards.count()):
        if picker.cards.item(row).data(256)['id'] == entry['id']:
            picker.cards.setCurrentRow(row)
    picker.rename()
    picker.name_edit.setText('新名字')
    picker._finish_rename()
    assert any(item['name'] == '新名字' for item in library.entries())
    picker.delete()
    assert not picker.confirm.isHidden()
    picker._delete_confirmed()
    assert all(item['id'] != entry['id'] for item in library.entries())


def test_shadow_presets_slider_merge_and_one_tap_canvas_size(app):
    document = CoverDocument(width=1920, height=1080)
    title = document.add_text('标题')
    editor = CoverEditor(document)
    editor.session.selected = {title.id}
    editor.view.sync_document()
    editor.refresh()
    for kind in ('hard', 'glow', 'none', 'soft'):
        editor.apply_shadow_preset(kind)
        assert editor.shadow_kind(editor.session.document.layer(title.id).style) == kind
    before = editor.session.undo.count()
    for value in (120, 130, 140):
        editor.text_numbers['size'].moved.emit(float(value))
    editor.text_numbers['size'].committed.emit(150.0)
    assert editor.session.document.layer(title.id).style['size'] == 150
    assert editor.session.undo.count() == before + 1   # one drag, one undo step
    editor.session.selected = set()
    editor.refresh()
    editor.preset.set_value((1080, 1920))
    editor.canvas_preset()
    assert (editor.session.document.width, editor.session.document.height) == (1080, 1920)
    editor.session.saved_signature = editor.session.document.signature()
    editor.close()
