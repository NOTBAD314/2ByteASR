from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QRawFont
from PySide6.QtWidgets import QApplication

from twobyteasr.caption_style import font_metadata as metadata
from twobyteasr.cover.cover_document import CoverDocument
from twobyteasr.cover.cover_editor import CoverEditor
from twobyteasr.cover.cover_render import text_font, CoverRenderer, export_image


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def test_chinese_name_is_localized_family_not_full_style_or_japanese():
    records = [(1, 0x804, '思源黑体 Heavy'), (16, 0x804, '思源黑体'),
               (16, 0x404, '思源黑體'), (16, 0x411, '源ノ角ゴシック')]
    assert metadata._chinese_name(records, (16, 1)) == '思源黑体'
    assert metadata._chinese_name([(1, 0x411, '游ゴシック')], (16, 1)) == ''
    root = Path(__file__).resolve().parents[1]
    face = metadata.read_faces(str(root/'assets/fonts/SourceHanSansSC-Heavy.otf'))[0]
    assert (face.family, face.display_family, face.style, face.weight) == ('Source Han Sans SC', '思源黑体', 'Heavy', 900)


def test_font_directories_collections_and_user_relative_registration(tmp_path, monkeypatch):
    import winreg
    root = tmp_path/'app'; module = root/'twobyteasr/caption_style/font_metadata.py'
    module.parent.mkdir(parents=True)
    asset = root/'assets/fonts/a.otf'; asset.parent.mkdir(parents=True); asset.touch()
    tools = root/'tools/fonts/b.ttc'; tools.parent.mkdir(parents=True); tools.touch()
    local = tmp_path/'local'; user = local/'Microsoft/Windows/Fonts'
    user.mkdir(parents=True); font = user/'已安装.otc'; font.touch()
    windir = tmp_path/'Windows'; system = windir/'Fonts'
    system.mkdir(parents=True); (system/'system.TTF').touch()
    class Key:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(metadata, '__file__', str(module))
    monkeypatch.setenv('LOCALAPPDATA', str(local)); monkeypatch.setenv('WINDIR', str(windir))
    monkeypatch.setattr(winreg, 'OpenKey', lambda *args: Key())
    monkeypatch.setattr(winreg, 'QueryInfoKey', lambda key: (0, 1, 0))
    monkeypatch.setattr(winreg, 'EnumValue', lambda *args: ('test', font.name, 1))
    paths = metadata.local_font_paths()
    assert all(path in paths for path in [asset, tools, font, system/'system.TTF'])
    assert paths.count(font) == 1


def test_bad_font_does_not_hide_other_files_or_collection_faces(tmp_path, monkeypatch):
    files = [tmp_path/'bad.ttf', tmp_path/'collection.ttc']
    monkeypatch.setattr(metadata, 'local_font_paths', lambda: files)
    first, second = SimpleNamespace(family='A'), SimpleNamespace(family='B')
    def read(path):
        if path.endswith('bad.ttf'): raise ValueError('bad font')
        return (first, second)
    monkeypatch.setattr(metadata, 'read_faces', read)
    # Call the uncached implementation so the app inventory is not contaminated.
    assert metadata.local_faces.__wrapped__() == (first, second)


def test_picker_localizes_searches_and_empty_input_preserves_identity(app, tmp_path):
    doc = CoverDocument(width=640, height=360); title = doc.add_text('字体测试')
    editor = CoverEditor(doc); editor.session.selected = {title.id}
    editor.view.sync_document(); editor.refresh()
    combo = editor.font_family
    assert combo.currentText() == '思源黑体'
    assert combo.currentData() == 'Source Han Sans SC'
    for query in ('思源', 'Source Han'):
        combo.completer().setCompletionPrefix(query)
        assert combo.completer().completionCount() > 0
    before = editor.session.document.signature()
    combo.setEditText(''); editor.choose_font()
    assert editor.session.document.signature() == before
    assert combo.currentText() == '思源黑体'
    editor.choose_font_completion('Source Han Sans SC')
    assert combo.currentText() == '思源黑体'
    assert editor.session.document.layer(title.id).style['family'] == 'Source Han Sans SC'
    assert not text_font(editor.session.document.layer(title.id).style)[1]
    editor.session.saved_signature = editor.session.document.signature(); editor.close()


def test_localized_selection_real_face_template_and_png(app, tmp_path):
    from twobyteasr.cover.cover_local_library import LocalCoverLibrary
    from PySide6.QtGui import QImage
    doc = CoverDocument(width=640, height=360); title = doc.add_text('中文标题 · Aa')
    editor = CoverEditor(doc); editor.session.selected = {title.id}
    editor.view.sync_document(); editor.refresh()
    editor.choose_font_completion('站酷庆科黄油体')
    style = editor.session.document.layer(title.id).style
    assert style['family'] == 'ZCOOL QingKe HuangYou' and style['weight'] == 400
    font, warning, face = text_font(style)
    assert not warning
    actual, expected = QRawFont.fromFont(font), QRawFont(face.file, 96)
    assert actual.isValid() and expected.isValid()
    assert actual.fontTable('head') == expected.fontTable('head')
    assert actual.fontTable('name') == expected.fontTable('name')
    output = tmp_path/'title.png'; export_image(editor.session.document, output)
    library = LocalCoverLibrary(tmp_path/'library')
    entry = library.save_native('字体模板', editor.session.document.snapshot(), output.read_bytes())
    copy = library.load_copy(entry)
    assert copy.layer(title.id).style == style
    render = CoverRenderer().render(copy)
    assert QImage(str(output)).convertToFormat(render.format()) == render
    editor.session.saved_signature = editor.session.document.signature(); editor.close()
