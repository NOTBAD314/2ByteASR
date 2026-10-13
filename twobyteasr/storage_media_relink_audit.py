"""Opt-in tiny fixture through normal Settings asset save and Studio relink."""
from __future__ import annotations
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFileDialog, QDialogButtonBox, QMessageBox, QScrollArea
    from . import application_settings_ui, blank_project_audit
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .storage_media_preservation import verified_relinked_asset
    from .modal_acceptance_driver import ModalAcceptanceDriver, cancel_without_settings_save_prompt
    output = Path(output); plan = json.loads((output / 'media-relink-input.json').read_text('utf8'))
    original_init = application_settings_ui.ApplicationSettingsDialog.__init__

    class Audit(ModalAcceptanceDriver):
        def __init__(self):
            super().__init__(window,output,'media-relink',timeout=60)
            self.page=window.studio_page
            self.result.update(provider_calls=0,identity=load_build_identity().to_dict(),pid=os.getpid(),inputs=plan)
        def click(self,widget):
            self.check('visible normal control before mouse input',widget is not None and widget.isVisible(),widget.objectName() if widget else None)
            self.check('normal control enabled before mouse input',widget.isEnabled(),widget.objectName())
            QTest.mouseClick(widget,Qt.LeftButton)
        def shot(self,name):
            self.progress('capture-enter',name)
            _capture(window,output/(name+'-whole-window.png'));self.result['screenshots'].append(name+'-whole-window.png')
            if self.dialog and self.dialog.isVisible():
                _capture(self.dialog,output/(name+'-settings.png'));self.result['screenshots'].append(name+'-settings.png')
            self.progress('capture-return',name);self.checkpoint()
        def storage(self):
            # The settings button enters exec(). Open it outside this generator
            # tick so the existing timer can drive its normal modal UI.
            self.queue_action('open normal Studio Settings',lambda:self.click(self.page.studio_hub_settings_button))
        def cancel_settings(self):
            dialog=self.dialog
            # The filename adapter is the only altered UI input in this audit.
            # Cancel must remain a cancellation; no settings save is authorized.
            dialog._saved_values=dialog._values()
            self.queue_action('normal Settings Cancel',lambda:self.click(dialog.buttons.button(QDialogButtonBox.Cancel)))
        def storage_nav(self):
            d=self.dialog;row=d.navigation.item(2)
            self.check('normal storage navigation',row.text()=='存储与缓存')
            QTest.mouseClick(d.navigation.viewport(),Qt.LeftButton,pos=d.navigation.visualItemRect(row).center())
        def ensure(self,widget):
            parent=widget.parentWidget()
            while parent is not None and not isinstance(parent,QScrollArea):parent=parent.parentWidget()
            if parent:parent.ensureWidgetVisible(widget,0,12)
        def row(self,panel):
            return next(panel.tree.topLevelItem(n).child(k) for n in range(panel.tree.topLevelItemCount())
                for k in range(panel.tree.topLevelItem(n).childCount())
                if panel.tree.topLevelItem(n).child(k).data(0,Qt.UserRole)==plan['cache'])
        def confirm(self):
            modal=QApplication.activeModalWidget()
            if isinstance(modal,QMessageBox):
                self.result['confirmation']=modal.text();self.click(modal.button(QMessageBox.Yes));return
            from PySide6.QtWidgets import QPushButton,QLabel
            for host in QApplication.topLevelWidgets():
                for button in host.findChildren(QPushButton):
                    if button.isVisible() and button.text() in {'是','Yes','是(&Y)'}:
                        self.result['confirmation']=' / '.join(label.text() for label in host.findChildren(QLabel) if label.isVisible())
                        self.click(button);return
            raise AssertionError('Actual cleanup confirmation absent')
        def run(self):
            self.phase('normal Home to project library')
            p=self.page;window.showNormal();window.resize(1600,1000);yield .15
            self.click(window.subtitle_studio_button)
            yield lambda:window.pages.currentWidget() is p and p.project_import_button.isVisible()
            original=QFileDialog.getOpenFileName;QFileDialog.getOpenFileName=lambda *a,**k:(plan['project'],'')
            try:self.click(p.project_import_button)
            finally:QFileDialog.getOpenFileName=original
            yield lambda:p.project and p._readiness.ready and not p._readiness.active
            self.check('normal library import uses owned missing-source project',p.project.project_id==plan['project_id'] and p.project.media.path==plan['source'])
            self.phase('initial offline project and normal Settings open')
            self.shot('01-offline-edited-project');self.storage()
            yield lambda:self.dialog is not None and self.dialog.isVisible()
            self.storage_nav();yield .15
            self.phase('initial sole-source protected scan')
            panel=self.dialog.storage_panel;self.click(panel.scan_button)
            yield lambda:panel.worker is None and panel.scan_result is not None
            item=next(i for i in panel.scan_result.items if i.path==plan['cache'])
            self.check('sole cache protected before asset save',not item.cleanable and '原素材' in item.reason,item.reason)
            self.phase('normal explicit media asset save')
            panel.tree.setCurrentItem(self.row(panel));self.ensure(panel.save_media);yield .1
            original=QFileDialog.getSaveFileName;QFileDialog.getSaveFileName=lambda *a,**k:(plan['destination'],'Media')
            try:self.click(panel.save_media)
            finally:QFileDialog.getSaveFileName=original
            yield lambda:panel.worker is None and Path(plan['destination']).is_file()
            proof=verified_relinked_asset(item,panel.service.paths)
            self.check('copy alone keeps original cache protected',not proof.verified and Path(plan['cache']).is_file(),asdict(proof))
            self.check('normal save copied complete real media',hashlib.sha256(Path(plan['destination']).read_bytes()).hexdigest()==plan['fixture_sha256'])
            self.shot('02-explicit-asset-saved')
            self.cancel_settings();yield lambda:not self.dialog.isVisible();self.dialog=None
            self.phase('normal Studio relink and save')
            yield lambda:p.isVisible() and p.relink_button.isVisible()
            original=QFileDialog.getOpenFileName;QFileDialog.getOpenFileName=lambda *a,**k:(plan['destination'],'Media')
            try:self.click(p.relink_button)
            finally:QFileDialog.getOpenFileName=original
            yield lambda:p.project.media.path==plan['destination'] and p._readiness.ready and not p._readiness.active
            self.click(p.save_button);yield .2
            saved=json.loads(Path(plan['project']).read_text('utf8'))
            self.check('normal relink and save keeps stable project/asset identity',saved['project_id']==plan['project_id'] and saved['media_pool'][0]['asset_id']==plan['asset_id'])
            for field in ('video_tracks','audio_tracks','av_track_groups'):
                self.check('normal relink preserves '+field,saved[field]==plan['before'][field])
            self.check('normal relink preserves edited timestamps and speed',
                [{k:v for k,v in row.items() if k!='source_path'} for row in saved['edit_sequence']['segments']]==
                [{k:v for k,v in row.items() if k!='source_path'} for row in plan['before']['edit_sequence']['segments']])
            self.shot('03-relinked-saved-project')
            self.phase('native player preserved trim and speed seek')
            # Native renderer proof after production relink; no generated pixels.
            self.click(p.timecode_input);QTest.keyClick(p.timecode_input,Qt.Key_A,Qt.ControlModifier)
            QTest.keyClicks(p.timecode_input,'00:00:00.700');QTest.keyClick(p.timecode_input,Qt.Key_Return)
            yield lambda:p.video.controller and p.video.controller.running
            if not p.video.playback_position_snapshot().paused or p.video._buffered_play_pending:self.click(p.play_button)
            yield lambda:p.video.controller.observed_property('pause',None) is True
            self.click(p.timecode_input);QTest.keyClick(p.timecode_input,Qt.Key_A,Qt.ControlModifier)
            QTest.keyClicks(p.timecode_input,'00:00:00.700');QTest.keyClick(p.timecode_input,Qt.Key_Return)
            yield lambda:abs(float(p.video.controller.observed_property('time-pos',-100))-.9)<.15
            self.check('actual seek uses preserved trim/rate timestamp mapping',abs(float(p.video.controller.observed_property('time-pos',-100))-.9)<.15)
            p.video.controller.screenshot_to_file(output/'03-relinked-native-frame.png',mode='video')
            yield lambda:(output/'03-relinked-native-frame.png').is_file()
            self.result['screenshots'].append('03-relinked-native-frame.png')
            self.phase('second normal Settings and saved-relink verification')
            self.storage();yield lambda:self.dialog is not None and self.dialog.isVisible()
            self.storage_nav();yield .15;panel=self.dialog.storage_panel;self.click(panel.scan_button)
            yield lambda:panel.worker is None and panel.scan_result is not None
            item=next(i for i in panel.scan_result.items if i.path==plan['cache']);proof=verified_relinked_asset(item,panel.service.paths)
            self.result['verified_relinked_asset']=asdict(proof)
            self.check('saved relink permits manual confirmation only',proof.verified and item.manual_cleanable
                and all(i.path!=item.path for i in panel.service.recommended(panel.scan_result)),asdict(item))
            self.shot('04-old-cache-manual-plan')
            self.phase('normal explicit old-cache cleanup confirmation')
            row=self.row(panel);row.parent().setCheckState(0,Qt.Checked);yield .1
            QTimer.singleShot(150,lambda:self.queue_action('confirm owned fixture cleanup',self.confirm))
            self.queue_action('request normal selected cleanup',lambda:self.click(panel.selected))
            yield lambda:panel.worker is None and not Path(plan['cache']).exists()
            self.check('normal confirmed cleanup deletes old cache and keeps asset/project',Path(plan['destination']).is_file() and Path(plan['project']).is_file())
            self.result['cleanup_receipt']=json.loads((panel.service.state_root/'last-cleanup.json').read_text('utf8'))
            self.check('cleanup logical bytes match full small fixture',self.result['cleanup_receipt']['logical_removed_bytes']==plan['logical_bytes'])
            self.shot('05-old-cache-cleared')
            self.cancel_settings();yield lambda:not self.dialog.isVisible();self.dialog=None
        def finish(self):
            if self.finished:return
            self.stop();application_settings_ui.ApplicationSettingsDialog.__init__=original_init
            self.result['provider_calls']=blank_project_audit._provider_calls;self.result['gui_shutdown']=True
            self.checkpoint()
            def shutdown():
                try:
                    modal=QApplication.activeModalWidget()
                    if modal is not None and modal is not self.dialog:modal.reject()
                    if self.dialog and self.dialog.isVisible():cancel_without_settings_save_prompt(self.dialog)
                    self.page.close_page();window.close()
                except Exception:self.result['shutdown_error']=traceback.format_exc();self.result['passed']=False
                finally:self.checkpoint();self.close_diagnostics();QApplication.instance().quit()
            QTimer.singleShot(0,shutdown)
    audit=Audit();window._storage_media_relink_audit=audit
    def observed(dialog,*args,**kwargs):
        audit.progress('settings-init-enter',dict(parent=audit._widget(args[0]) if args else None,
            advanced_owner=audit._widget(kwargs.get('advanced_owner'))))
        original_init(dialog,*args,**kwargs);audit.dialog=dialog
        audit.progress('settings-init-return')
    application_settings_ui.ApplicationSettingsDialog.__init__=observed
    audit.progress('settings-observer-installed')
    audit.begin(audit.run())
