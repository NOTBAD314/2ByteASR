# SPDX-License-Identifier: GPL-3.0-only
"""Run the unchanged frozen license viewer, with external release expectations.

Component verification only: not a rerun of the sealed application's home/Studio
navigation, and not independent-machine verification. Does not modify the EXE.
Use the same Python minor and PySide version as the sealed application.
"""
import argparse
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--exe', type=Path, required=True)
    ap.add_argument('--manifest', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output.resolve()
    if not out.is_relative_to(root / 'tmp') or out.exists():
        raise ValueError('A new repository tmp directory is required')
    raw = args.manifest.read_bytes()
    manifest = json.loads(raw.decode('utf-8-sig'))
    exe = args.exe.resolve()
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    if digest != manifest['application_exe_sha256']:
        raise ValueError('Executable identity mismatch')
    payload = exe.parent
    identity = json.loads((payload / '2byteasr_build.json').read_text('utf-8-sig'))
    for key in ('app_version', 'build_channel', 'source_sha256', 'git_sha'):
        if identity[key] != manifest['identity'][key]:
            raise ValueError('Independent release identity mismatch: ' + key)
    out.mkdir(parents=True)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(out), QT_QPA_PLATFORM='offscreen',
                      LOCALAPPDATA=str(out / 'local'), APPDATA=str(out / 'roaming'))
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(exe)).open_embedded_archive('PYZ.pyz')

    class FrozenApplication(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, name, path=None, target=None):
            if name.startswith('twobyteasr') and name in archive.toc:
                return importlib.util.spec_from_loader(name, self, is_package=archive.toc[name][0] == 1)
        def create_module(self, spec):
            return None
        def exec_module(self, module):
            module.__file__ = str(payload / (module.__name__.replace('.', '/') + '.py'))
            exec(archive.extract(module.__name__), module.__dict__)

    sys.meta_path.insert(0, FrozenApplication())
    sys._MEIPASS = str(payload)
    sys.frozen = True
    import PySide6
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtGui import QFontDatabase, QFont
    from PySide6.QtWidgets import QApplication, QTextBrowser, QLabel
    from twobyteasr import license_documents
    app = QApplication([])
    # This component harness does not run quick_start's font initialization.
    # Supply the same bundled font, instead of accepting an unreadable offscreen fallback.
    font_id = QFontDatabase.addApplicationFont(str(payload / 'assets/fonts/SourceHanSansSC-Medium.otf'))
    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        raise RuntimeError('Bundled CJK font could not be loaded')
    app.setFont(QFont(families[0], 10))
    result = dict(passed=False, exe_sha256=digest,
                  independent_manifest_sha256=hashlib.sha256(raw).hexdigest(),
                  identity=identity, pyside_version=PySide6.__version__, checks={},
                  scope='Unmodified frozen license_documents code + sealed payload documents; component UI on host, not full EXE navigation or VM')
    def check(name, value):
        result['checks'][name] = bool(value)
        if not value:
            raise AssertionError(name)
    def inspect():
        dialog = None
        try:
            dialog = next(x for x in app.topLevelWidgets() if x.objectName() == 'licenseDocumentDialog')
            browser = dialog.findChild(QTextBrowser, 'licenseDocumentText')
            label = dialog.findChild(QLabel, 'licenseDocumentLocation')
            check('version_from_independent_manifest', manifest['identity']['app_version'] in browser.toPlainText())
            check('source_document_openLinks_false', not browser.openLinks())
            check('source_document_openExternalLinks_false', not browser.openExternalLinks())
            check('actual_SOURCE_DELIVERY_loaded', label.text() == 'SOURCE_DELIVERY.md')
            dialog.grab().save(str(out / 'source-document.png'))
            before = browser.toPlainText()
            browser.anchorClicked.emit(QUrl('https://example.invalid/license-audit-no-request'))
            check('external_navigation_rejected', browser.toPlainText() == before and label.text() != 'SOURCE_DELIVERY.md')
            browser.anchorClicked.emit(QUrl.fromLocalFile(str(payload / 'BUILD_FROM_SOURCE.md')))
            check('local_build_instructions_loaded', label.text() == 'BUILD_FROM_SOURCE.md' and bool(browser.toPlainText()))
            check('external_resources_disabled', browser.loadResource(2, QUrl('https://example.invalid/no-request.png')) is None)
            result['passed'] = True
        except Exception:
            result['error'] = traceback.format_exc()
        finally:
            if dialog is not None:
                dialog.close()
    QTimer.singleShot(300, inspect)
    license_documents.show_document(None, 'SOURCE_DELIVERY.md')
    check('sealed_executable_unchanged', hashlib.sha256(exe.read_bytes()).hexdigest() == digest)
    (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(dict(passed=result['passed'], checks=result['checks'], scope=result['scope'])))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
