"""Local-only cover workflow, self-contained templates and scale controls."""
from dataclasses import asdict
import hashlib
import io
from pathlib import Path
import time
from types import SimpleNamespace

from PIL import Image
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QVBoxLayout, QWidget

from twobyteasr.cover.cover_document import CoverDocument
from twobyteasr.cover.cover_editor import CoverEditor
from twobyteasr.cover.cover_local_library import LocalCoverLibrary
from twobyteasr.cover.cover_studio import install_cover_button


@pytest.fixture(scope='module')
def app():
    instance = QApplication.instance() or QApplication([])
    for path in (Path(__file__).resolve().parents[1] / 'assets/fonts').glob('*.otf'):
        QFontDatabase.addApplicationFont(str(path))
    return instance


def png(color='green'):
    stream = io.BytesIO()
    Image.new('RGBA', (320, 180), color).save(stream, format='PNG')
    return stream.getvalue()


def document():
    doc = CoverDocument(width=640, height=360)
    doc.add_image(png(), '当前截图.png', (320, 180), background=True)
    image = doc.add_image(png('orange'), '贴图.png', (320, 180))
    image.x, image.y, image.width, image.height = 81.25, 46.5, 160, 90
    image.opacity, image.keep_aspect = .7, False
    title = doc.add_text('模板标题\n第二行')
    title.x, title.y = 37.5, 33.25
    title.style.update(size=28, stroke=2, shadow=False)
    title.locked = True
    doc.source = dict(milliseconds=232333, captured_at='fixture')
    return doc


def wait_job(app, editor):
    deadline = time.monotonic() + 8
    while editor.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert not editor.busy, editor.status.text()


def test_template_roundtrip_without_originals_and_no_master_overwrite(tmp_path, app):
    original_file = tmp_path / '原始素材.png'
    original_file.write_bytes(png('blue'))
    doc = document()
    hidden = doc.add_image(original_file.read_bytes(), original_file.name, (320, 180))
    hidden.visible = False
    library = LocalCoverLibrary(tmp_path / 'library')
    entry = library.save_native('系列模板', doc, png())
    master = library.asset(entry, 'cover')
    digest = hashlib.sha256(master.read_bytes()).hexdigest()
    original_file.unlink()
    library = LocalCoverLibrary(tmp_path / 'library')
    copy = library.load_copy(library.get(entry['id']))
    assert copy.id != doc.id
    assert copy.assets == doc.assets
    assert [asdict(layer) for layer in copy.layers] == [asdict(layer) for layer in doc.layers]
    copy.layers[1].x += 100
    copy.layers[-2].text = '副本修改'
    copy.save(tmp_path / '成品.2bytecover')
    library.mark_used(entry)
    assert hashlib.sha256(master.read_bytes()).hexdigest() == digest
    assert library.load_copy(entry).layers[1].x == 81.25
    duplicate = library.duplicate(entry)
    assert duplicate['id'] != entry['id'] and duplicate['cover'] != entry['cover']
    assert library.load_copy(duplicate).assets == doc.assets


def test_failed_template_pointer_keeps_existing_templates(tmp_path, app, monkeypatch):
    library = LocalCoverLibrary(tmp_path)
    first = library.save_native('保留模板', document(), png())
    before = library.get(first['id'])
    def fail(entry): raise PermissionError('read only')
    monkeypatch.setattr(library, 'metadata', fail)
    with pytest.raises(PermissionError):
        library.save_native('失败模板', document(), png())
    assert library.get(first['id']) == before
    assert all(entry['name'] != '失败模板' for entry in library.entries())


def test_template_current_frame_replacement_preserves_layer_geometry(tmp_path, app):
    doc, frame = document(), document()
    source = frame.layer(frame.background_id)
    source.asset = frame.add_asset(png('blue'), '新截图.png')
    layers = [asdict(layer) for layer in doc.layers]
    LocalCoverLibrary.replace_frame(doc, frame)
    background = doc.layer(doc.background_id)
    assert doc.assets[background.asset] == png('blue')
    after = [asdict(layer) for layer in doc.layers]
    for before_layer, after_layer in zip(layers, after):
        before_layer.pop('asset'); after_layer.pop('asset')
        assert before_layer == after_layer


def test_editor_templates_are_native_and_restore_copy_filename(tmp_path, app):
    editor = CoverEditor(document())
    editor.library = LocalCoverLibrary(tmp_path / 'library')
    assert 'gimp' not in editor.cover_actions
    assert editor.cover_actions['save_template'].text() == '保存为模板'
    signature = editor.session.document.signature()
    editor.save_template('本地标题模板')
    wait_job(app, editor)
    assert '模板已保存' in editor.status.text()
    entry = next(row for row in editor.library.entries() if row['name'] == '本地标题模板')
    assert editor.session.document.signature() == signature
    assert editor.session.dirty  # template save is not a normal document save
    expected = [asdict(layer) for layer in editor.session.document.layers]
    editor.apply_template(entry)
    wait_job(app, editor)
    assert editor.session.filename == '' and editor.session.dirty
    assert [asdict(layer) for layer in editor.session.document.layers] == expected
    target = tmp_path / '普通保存.2bytecover'
    master = editor.library.asset(entry, 'cover').read_bytes()
    editor.save_document(target)
    wait_job(app, editor)
    assert target.exists() and editor.library.asset(entry, 'cover').read_bytes() == master


def test_studio_has_only_three_local_entries_without_runtime_or_browser(app, monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('no external editor or browser')
    monkeypatch.setattr('subprocess.Popen', forbidden)
    from PySide6.QtGui import QDesktopServices
    monkeypatch.setattr(QDesktopServices, 'openUrl', forbidden)
    page = QWidget();page.save_state = QLabel(page);page.project = None
    install_cover_button(page, QVBoxLayout(page))
    actions = page.make_cover_button.menu().actions()
    assert [action.text() for action in actions] == ['当前截图', '新建封面', '选择模板']
    actions[0].trigger()
    assert page.cover_controller.editor is None
    actions[1].trigger()
    first = page.cover_controller.editor
    assert isinstance(first, CoverEditor) and not first.session.document.layers
    first.session.document.add_text('未保存内容')
    second = page.cover_controller.show_editor(document())
    assert second is not first and first.session.document.layers[-1].text == '未保存内容'
    assert not any('GIMP' in action.text() for action in second.cover_actions.values())
    from twobyteasr.cover.cover_workbench import CoverWorkbench
    assert CoverWorkbench is CoverEditor


def test_studio_template_selection_opens_full_local_copy(tmp_path, app, monkeypatch):
    from twobyteasr.cover.cover_templates_ui import TemplatePicker
    from twobyteasr.cover import cover_local_library
    library = LocalCoverLibrary(tmp_path / 'library')
    doc = document(); entry = library.save_native('可选模板', doc, png())
    monkeypatch.setattr(cover_local_library, 'LocalCoverLibrary', lambda: library)
    def select(dialog): dialog.selected = entry; return QDialog.Accepted
    monkeypatch.setattr(TemplatePicker, 'exec', select)
    page = QWidget(); page.save_state = QLabel(page)
    install_cover_button(page, QVBoxLayout(page))
    page.make_cover_button.menu().actions()[2].trigger()
    editor = page.cover_controller.editor
    wait_job(app, editor)
    assert [asdict(layer) for layer in editor.session.document.layers] == [asdict(layer) for layer in doc.layers]
    assert editor.session.filename == ''


def test_current_screenshot_enters_local_editor_without_choice_page(app, monkeypatch):
    from twobyteasr.exports import export_timeline, video_export, frame_export
    page = QWidget(); page.save_state = QLabel(page)
    page.project = SimpleNamespace(media=SimpleNamespace(path='fixture.mp4'))
    page.timeline = SimpleNamespace(playhead_ms=8250)
    page.video = SimpleNamespace(set_paused=lambda value: None)
    monkeypatch.setattr(export_timeline, 'export_project_snapshot', lambda project: SimpleNamespace(project_id='test-video'))
    monkeypatch.setattr(video_export, 'capture_video_graph', lambda project: {})
    def capture(project, graph, milliseconds, directory, *args, **kwargs):
        path = Path(directory) / 'frame.png'; path.write_bytes(png())
        return dict(path=str(path), width=320, height=180, decode=[], milliseconds=milliseconds)
    monkeypatch.setattr(frame_export, 'save_project_frame', capture)
    install_cover_button(page, QVBoxLayout(page))
    page.make_cover_button.menu().actions()[0].trigger()
    deadline = time.monotonic() + 8
    while page.cover_controller.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.005)
    editor = page.cover_controller.editor
    assert isinstance(editor, CoverEditor)
    assert editor.frame_document.source['milliseconds'] == 8250
    assert editor.session.document.assets[editor.session.document.layers[0].asset] == png()


def test_scale_checkbox_controls_numeric_aspect_and_persists(tmp_path, app):
    editor = CoverEditor(document())
    key = editor.session.document.layers[1].id
    editor.session.selected = {key}
    editor.view.sync_document(); editor.refresh()
    assert editor.aspect.text() == '等比缩放'
    editor.aspect.setChecked(True)
    editor.change_geometry('width', 320)
    layer = editor.session.document.layer(key)
    assert (layer.width, layer.height) == (320, 180)
    editor.aspect.setChecked(False)
    editor.change_geometry('width', 400)
    layer = editor.session.document.layer(key)
    assert (layer.width, layer.height) == (400, 180)
    path = tmp_path / '保留比例设置.2bytecover'
    editor.session.document.save(path)
    assert CoverDocument.load(path).layer(key).keep_aspect is False
