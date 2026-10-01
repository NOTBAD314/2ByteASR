"""Bounded offscreen check of the packaged cover font path; no desktop input."""
import json
import os
from pathlib import Path


def main(output):
    from .test_isolation import isolation_root
    out = Path(output).resolve()
    if isolation_root() != out:
        raise ValueError('font self-test requires matching TWOBYTEASR_TEST_ROOT under tmp')
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase, QImage, QRawFont
    from .build_identity import load_build_identity
    from .cover_document import CoverDocument
    from .cover_editor import CoverEditor
    from .cover_render import text_font, export_image, CoverRenderer
    from .cover_local_library import LocalCoverLibrary
    from .font_metadata import local_faces
    from .theme_manager import apply_application_theme
    app = QApplication.instance() or QApplication([])
    # Match normal startup's bundled UI faces before checking layout.
    directory = Path(__file__).resolve().parents[1]/'assets/fonts'
    for path in sorted((*directory.glob('*.otf'), *directory.glob('*.ttf'))):
        QFontDatabase.addApplicationFont(str(path))
    from .typography import application_font
    app.setFont(application_font())
    doc = CoverDocument(width=960, height=540)
    title = doc.add_text('中文字体 · 游戏封面')
    title.width = 840; title.style.update(size=64, stroke=2)
    editor = CoverEditor(doc)
    editor.resize(1280, 820); editor.session.selected = {title.id}
    editor.view.sync_document(); editor.refresh()
    checks = {'chinese_default': editor.font_family.currentText() == '思源黑体',
              'all_families_listed': editor.font_family.count() == len({f.family for f in local_faces()})}
    before = editor.session.document.signature()
    editor.font_family.setEditText(''); editor.choose_font()
    checks['blank_search_safe'] = editor.session.document.signature() == before
    for name in ('Source Han Sans SC', '思源黑体', '站酷庆科黄油体'):
        editor.choose_font_completion(name)
        font, warning, face = text_font(editor.session.document.layer(title.id).style)
        raw, expected = QRawFont.fromFont(font), QRawFont(face.file, 64)
        checks['real_face_' + name] = (not warning and raw.isValid() and expected.isValid() and
                                      raw.fontTable('head') == expected.fontTable('head') and
                                      raw.fontTable('name') == expected.fontTable('name'))
    image = out/'title.png'; export_image(editor.session.document, image)
    library = LocalCoverLibrary(out/'library')
    entry = library.save_native('中文字体模板', editor.session.document.snapshot(), image.read_bytes())
    copy = library.load_copy(entry)
    checks['template_identity'] = copy.layer(title.id).style == editor.session.document.layer(title.id).style
    rendered = CoverRenderer().render(copy)
    checks['export_reopen_pixels'] = QImage(str(image)).convertToFormat(rendered.format()) == rendered
    for theme in ('warm', 'plum'):
        apply_application_theme(app, theme)
        editor.show(); app.processEvents()
        editor.grab().save(str(out/f'fonts-{theme}.png'))
        editor.font_family.showPopup(); app.processEvents()
        editor.font_family.view().window().grab().save(str(out/f'font-list-{theme}.png'))
        editor.font_family.hidePopup()
    result = dict(passed=all(checks.values()), checks=checks, identity=load_build_identity().to_dict(),
                  families=editor.font_family.count(),
                  chinese_names=sorted({f.display_family for f in local_faces() if f.display_family != f.family}))
    (out/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    editor.session.saved_signature = editor.session.document.signature(); editor.close()
    return 0 if result['passed'] else 1
