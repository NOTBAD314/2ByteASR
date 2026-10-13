"""Opt-in normal settings entry acceptance, using small isolated cache files."""
from __future__ import annotations
from dataclasses import asdict
import json
import os
from pathlib import Path
import time
import traceback
import hashlib
import shutil


def start(window,output):
    from PySide6.QtCore import QObject,QTimer,Qt
    from PySide6.QtWidgets import QApplication,QDialogButtonBox,QMessageBox,QFileDialog,QScrollArea,QLineEdit
    from PySide6.QtTest import QTest
    from . import application_settings_ui,blank_project_audit
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .storage_service import StorageService
    original=application_settings_ui.ApplicationSettingsDialog.__init__

    class Audit(QObject):
        def __init__(self):
            super().__init__(window);self.dialog=None;self.waiting=0;self.in_tick=False;self.deadline=time.monotonic()+45
            self.result=dict(passed=False,checks=[],screenshots=[],provider_calls=0,pid=os.getpid(),identity=load_build_identity().to_dict())
            self.steps=self.run();self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(30)
            QTimer.singleShot(400,self.open_settings)
        def check(self,name,value,detail=None):
            self.result['checks'].append(dict(name=name,passed=bool(value),detail=detail))
            if not value:raise AssertionError(name+': '+str(detail))
        def open_settings(self):
            window._return_to_settings()
            QTest.mouseClick(window.app_settings_button,Qt.LeftButton)
        def tick(self):
            if self.in_tick:return
            self.in_tick=True
            try:
                now=time.monotonic()
                if callable(self.waiting):
                    if not self.waiting():
                        if now>self.deadline:raise TimeoutError('Storage GUI condition')
                        return
                elif now<self.waiting:return
                step=next(self.steps);self.waiting=step if callable(step) else time.monotonic()+float(step)
                self.deadline=time.monotonic()+45
            except StopIteration:self.result['passed']=True;self.finish()
            except Exception:
                self.result['error']=traceback.format_exc();self.finish()
            finally:self.in_tick=False
        def shot(self,name):
            _capture(window,output/(name+'-whole-window.png'));self.result['screenshots'].append(name+'-whole-window.png')
            if self.dialog and self.dialog.isVisible():
                _capture(self.dialog,output/(name+'.png'));self.result['screenshots'].append(name+'.png')
        def confirm(self):
            modal=QApplication.activeModalWidget()
            if isinstance(modal,QMessageBox):
                self.result['confirmation']=modal.text()
                QTest.mouseClick(modal.button(QMessageBox.StandardButton.Yes),Qt.LeftButton)
            else:
                # The app may host its message card inside its modal surface.
                from PySide6.QtWidgets import QPushButton,QLabel
                for host in QApplication.topLevelWidgets():
                    for button in host.findChildren(QPushButton):
                        if button.isVisible() and button.text() in {'是','Yes','是(&Y)'}:
                            self.result['confirmation']=' / '.join(l.text() for l in host.findChildren(QLabel) if l.isVisible())
                            QTest.mouseClick(button,Qt.LeftButton);return
                raise RuntimeError('Actual cleanup confirmation not found')
        def run(self):
            yield lambda:self.dialog is not None and self.dialog.isVisible()
            dialog=self.dialog;panel=dialog.storage_panel;service=panel.service
            self.check('normal settings contains storage navigation',dialog.navigation.item(2).text()=='存储与缓存')
            rect=dialog.navigation.visualItemRect(dialog.navigation.item(2));QTest.mouseClick(dialog.navigation.viewport(),Qt.LeftButton,pos=rect.center());yield .15
            self.check('storage page is visible',panel.isVisible())
            root=service.paths.cache_root;root.mkdir(parents=True,exist_ok=True)
            removable=root/'preview-fixture.png';removable.write_bytes(b'local cache'*2048)
            evidence=root/'original-asr.json';evidence.write_text('{"text":"keep raw evidence"}','utf8')
            service.register(removable,'preview',producer='headed_controlled_fixture')
            service.register(evidence,'evidence',producer='headed_raw_evidence',rebuild='remote')
            with service._db() as db:db.execute('UPDATE entries SET used=? WHERE path=?',(time.time()-8*86400,str(removable)))
            self.before=sum(p.stat().st_size for p in root.iterdir() if p.is_file())
            self.check('before scan is unknown not zero',panel.scan_result is None and '尚未' in panel.summary.text())
            self.shot('01-storage-unscanned')
            QTest.mouseClick(panel.scan_button,Qt.LeftButton)
            self.check('scan returns immediately with cancellation',panel.cancel_button.isEnabled())
            yield lambda:panel.worker is None and panel.scan_result is not None
            self.check('completed actual file inventory',panel.scan_result.complete and panel.scan_result.cleanable_bytes==removable.stat().st_size,asdict(panel.scan_result))
            self.shot('02-storage-scanned')
            QTimer.singleShot(150,self.confirm);QTest.mouseClick(panel.recommended,Qt.LeftButton)
            yield lambda:panel.worker is None and not removable.exists()
            self.check('actual cache gone, original evidence remains',not removable.exists() and evidence.read_text('utf8')=='{"text":"keep raw evidence"}')
            receipt=json.loads((service.state_root/'last-cleanup.json').read_text('utf8'));self.result['cleanup_receipt']=receipt
            self.check('logical removal distinct from observed volume free',receipt['logical_removed_bytes']==len(b'local cache'*2048) and 'observed_free_delta' in receipt)
            self.shot('03-storage-cleaned')
            self.result['after_cleanup_bytes']=sum(p.stat().st_size for p in root.iterdir() if p.is_file())
            proxy=root/'sole-proxy.mp4';shutil.copyfile(output/'sole-proxy-fixture.mp4',proxy)
            service.register(proxy,'media',producer='headed_controlled_media',source=str(output/'missing-original.flv'))
            QTest.mouseClick(panel.scan_button,Qt.LeftButton)
            yield lambda:panel.worker is None and panel.scan_result is not None
            leaf=next(panel.tree.topLevelItem(n).child(k)
                for n in range(panel.tree.topLevelItemCount())
                for k in range(panel.tree.topLevelItem(n).childCount())
                if panel.tree.topLevelItem(n).child(k).data(0,Qt.ItemDataRole.UserRole)==str(proxy))
            panel.tree.setCurrentItem(leaf);yield .1
            self.check('sole cached media protected with visible preserve action',
                panel.save_media.isEnabled() and panel.relink_media.isEnabled()
                and not next(i for i in panel.scan_result.items if i.path==str(proxy)).cleanable)
            assets=output/'projects'/'assets';assets.mkdir(parents=True)
            destination=assets/'preserved-proxy.mp4'
            original_save=QFileDialog.getSaveFileName
            # Keep the actual save chooser visible to Qt on the private desktop.
            def visible_save(*args,**kwargs):
                kwargs['options']=kwargs.get('options',QFileDialog.Option(0))|QFileDialog.Option.DontUseNativeDialog
                return original_save(*args,**kwargs)
            def choose_destination():
                modal=QApplication.activeModalWidget()
                if not isinstance(modal,QFileDialog):raise AssertionError('Actual media asset save chooser absent')
                modal.setDirectory(str(assets))
                QApplication.processEvents();QTest.qWait(100)
                filename=modal.findChild(QLineEdit,'fileNameEdit')
                if filename is None:raise AssertionError('Save chooser filename field absent')
                filename.setFocus();QTest.keyClick(filename,Qt.Key_A,Qt.ControlModifier)
                QTest.keyClicks(filename,destination.name);QTest.qWait(100)
                _capture(modal,output/'05-asset-save-dialog.png')
                buttons=modal.findChild(QDialogButtonBox)
                QTest.mouseClick(buttons.button(QDialogButtonBox.StandardButton.Save),Qt.LeftButton)
            scroller=panel.save_media.parentWidget()
            while scroller is not None and not isinstance(scroller,QScrollArea):scroller=scroller.parentWidget()
            if scroller is not None:scroller.ensureWidgetVisible(panel.save_media,0,12)
            yield .1
            QFileDialog.getSaveFileName=visible_save
            try:
                QTimer.singleShot(180,choose_destination)
                QTest.mouseClick(panel.save_media,Qt.LeftButton)
            finally:QFileDialog.getSaveFileName=original_save
            yield lambda:panel.worker is None and destination.exists()
            digest=hashlib.sha256(proxy.read_bytes()).hexdigest()
            self.check('normal asset save preserves actual media bytes and original cache',
                destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest()==digest and proxy.is_file())
            self.check('saved asset outside cache index and ordinary cleanup',
                str(destination) not in service._registered()[0] and not service.clean([next(i for i in panel.scan_result.items if i.path==str(proxy))]).deleted)
            self.result['preserved_asset']=dict(source=str(proxy),destination=str(destination),sha256=digest,logical_bytes=destination.stat().st_size)
            self.shot('06-asset-preserved')
            spin=panel.policy_controls['retention_days'][0]
            spin.setFocus();QTest.keyClick(spin,Qt.Key_A,Qt.ControlModifier);QTest.keyClicks(spin,'9');QTest.keyClick(spin,Qt.Key_Tab)
            QTest.mouseClick(panel.enabled,Qt.LeftButton)
            QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Save),Qt.LeftButton);yield .2
            self.check('normal settings saves storage policy',StorageService().policy()['retention_days']==9 and StorageService().policy()['enabled'] is False)
            self.dialog=None;QTimer.singleShot(50,self.open_settings)
            yield lambda:self.dialog is not None and self.dialog.isVisible()
            self.check('settings reopen restores policy',self.dialog.storage_panel.policy_controls['retention_days'][0].value()==9 and not self.dialog.storage_panel.enabled.isChecked())
            self.shot('04-storage-reopened')
            self.dialog.reject();yield .2
            self.result['files_after']=[str(p) for p in root.iterdir() if p.is_file()]
            self.result['before_bytes']=self.before;self.result['after_bytes']=sum(p.stat().st_size for p in root.iterdir() if p.is_file())
        def finish(self):
            self.timer.stop();application_settings_ui.ApplicationSettingsDialog.__init__=original
            if self.dialog and self.dialog.isVisible():self.dialog._saved_values=self.dialog._values();self.dialog.reject()
            self.result['provider_calls']=blank_project_audit._provider_calls
            self.result['gui_shutdown']=True
            (output/'result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),'utf8')
            window.close();QTimer.singleShot(100,QApplication.instance().quit)
    audit=Audit();window._storage_settings_audit=audit
    def observed(dialog,*args,**kwargs):
        original(dialog,*args,**kwargs);audit.dialog=dialog
    application_settings_ui.ApplicationSettingsDialog.__init__=observed
