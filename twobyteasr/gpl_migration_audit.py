# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in license-entry checks through the real home and Studio settings."""
import hashlib, json, os, traceback
from pathlib import Path


def expected_release(path):
    """Read the independent release receipt; never infer expected version from the app."""
    raw = Path(path).read_bytes()
    manifest = json.loads(raw.decode('utf-8-sig'))
    identity = manifest['identity']
    keys = ('app_version', 'build_channel', 'source_sha256', 'git_sha')
    if any(not isinstance(identity.get(k), str) or not identity[k] for k in keys):
        raise ValueError('Release manifest has incomplete identity')
    return {k: identity[k] for k in keys}, hashlib.sha256(raw).hexdigest()

def start(window, output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QTextBrowser, QLabel, QLineEdit
    from PySide6.QtTest import QTest
    from .build_identity import load_build_identity
    from .license_documents import document_root
    from .studio_acceptance_audit import require
    app=QApplication.instance()
    result={'passed':False,'identity':load_build_identity().to_dict(),'checks':{},
        'limits':['Qt IME commit-event delivery only; physical Windows IME not exercised','No model inference or external network']}
    expected, manifest_sha = expected_release(os.environ['TWOBYTEASR_ACCEPTANCE_MANIFEST'])
    result['expected_identity'] = expected
    result['independent_manifest_sha256'] = manifest_sha
    def check(name,value):
        result['checks'][name]=bool(value);require(value,name)
    def inspect_settings(context):
        try:
            dialog=next(w for w in app.topLevelWidgets() if w.isVisible() and w.objectName()=='applicationSettings')
            dialog.navigation.setCurrentRow(dialog.navigation.count()-1)
            QTest.qWait(200)
            check(context+'_GPL_label','GPL-3.0-only' in dialog.findChild(QLabel,'projectLicenseLabel').text())
            for name,phrase in [('openProjectLicense','GNU GENERAL PUBLIC LICENSE'),('openThirdPartyNotices','Remotion'),('openCorrespondingSource',expected['app_version'])]:
                def inspect_document(n=name,expected=phrase):
                    try:
                        viewer=next(w for w in app.topLevelWidgets() if w.isVisible() and w.objectName()=='licenseDocumentDialog')
                        text=viewer.findChild(QTextBrowser,'licenseDocumentText')
                        check(context+'_'+n,expected in text.toPlainText())
                        check(context+'_'+n+'_offline',not text.openExternalLinks() and not text.openLinks())
                        if context=='home': viewer.grab().save(str(output/(n+'.png')))
                        viewer.close()
                    except Exception:
                        result['error']=traceback.format_exc()
                        for w in app.topLevelWidgets():
                            if w.objectName()=='licenseDocumentDialog':w.close()
                button=dialog.findChild(QPushButton,name)
                scroll=dialog.pages.currentWidget();scroll.ensureWidgetVisible(button);QTest.qWait(80)
                QTimer.singleShot(250,inspect_document)
                QTest.mouseClick(button,Qt.MouseButton.LeftButton)
                check(context+'_'+name+'_visited',context+'_'+name in result['checks'])
            dialog.grab().save(str(output/(context+'-about.png')))
            # Chinese text delivery with the retained native Qt input machinery.
            dialog.navigation.setCurrentRow(0)
            field=dialog.root_edit;original=field.text();field.setFocus()
            event=QInputMethodEvent();event.setCommitString('中文许可验收');app.sendEvent(field,event)
            check(context+'_Chinese_input_event','中文许可验收' in field.text());field.setText(original)
            QDialog.done(dialog,QDialog.DialogCode.Rejected)
        except Exception:
            result['error']=traceback.format_exc()
            for w in app.topLevelWidgets():
                if isinstance(w,QDialog):QDialog.done(w,QDialog.DialogCode.Rejected)
    def run():
        try:
            for key, value in expected.items():
                check('release_identity_' + key, result['identity'].get(key) == value)
            root=document_root()
            check('official_GPL_sha',hashlib.sha256((root/'LICENSE').read_bytes()).hexdigest()=='3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986')
            for language in ('en','ja','zh'):
                window.language_combo.setCurrentIndex(window.language_combo.findData(language));QTest.qWait(150)
                from .i18n import tr
                check('translated_license_'+language,'GPL' in tr('GPL 许可全文'))
            QTimer.singleShot(300,lambda:inspect_settings('home'))
            QTest.mouseClick(window.app_settings_button,Qt.MouseButton.LeftButton)
            QTest.mouseClick(window.subtitle_studio_button,Qt.MouseButton.LeftButton);QTest.qWait(1600)
            check('Studio_entered',window.pages.currentWidget() is window.studio_page)
            QTimer.singleShot(300,lambda:inspect_settings('studio'))
            QTest.mouseClick(window.studio_page.studio_hub_settings_button,Qt.MouseButton.LeftButton)
            check('both_actual_entries_visited','studio_openCorrespondingSource' in result['checks'] and 'home_openCorrespondingSource' in result['checks'])
            result['passed']='error' not in result and all(result['checks'].values())
        except Exception:result['error']=traceback.format_exc()
        finally:
            (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
            window.close()
    QTimer.singleShot(1800,run)
