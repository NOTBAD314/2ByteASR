"""Normal-entry export checks; inputs and all writes belong to an isolated tmp run."""
from __future__ import annotations
import json
import os
import time
import traceback
import sys
from dataclasses import asdict


def start(window, out):
    from PySide6.QtCore import QObject, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from ..projects.studio_project import load_project, save_project
    from ..exports.studio_export_ui import SubtitleExportDialog
    from ..exports.studio_subtitle_export import export_language_layers, export_subtitle_artifacts, SubtitleExportOptions
    from ..diagnostics.build_identity import load_build_identity

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = None
            self.result = dict(passed=False,checks={},events=[],error='',gui_shutdown=False,
                frozen=bool(getattr(sys,'frozen',False)),pid=os.getpid(),executable=sys.executable,
                build_identity=asdict(load_build_identity()),synthetic_media=True,cloud_requests=0)
            self.started = time.monotonic()
            self.waiting = 0.
            self.steps = self.run()
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(30)

        def check(self, key, value):
            self.result['checks'][key] = bool(value)
            if not value:
                raise AssertionError(key)

        def tick(self):
            if time.monotonic() < self.waiting:
                return
            try:
                if time.monotonic()-self.started > 180:
                    raise TimeoutError('old project export audit')
                self.waiting = time.monotonic()+next(self.steps)
            except StopIteration:
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                self.finish()

        def finish(self):
            self.timer.stop()
            self.result['passed']=not self.result['error'] and bool(self.result['checks']) and all(self.result['checks'].values())
            def write():
                (out/'result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),'utf8')
            def done():
                self.result['gui_shutdown']=True
                write()
            write()
            window.result_exit_code=0 if self.result['passed'] else 1
            QApplication.instance().aboutToQuit.connect(done)
            window.close()
            QTimer.singleShot(200,QApplication.instance().quit)

        def setup_failure(self):
            from ..studio import studio_ui
            from PySide6.QtWidgets import QMessageBox
            p=self.page
            constructor=studio_ui.StudioExportWorkspace
            message=studio_ui.studio_message_box
            observed=[]
            def fail(*args,**kwargs):
                raise RuntimeError('controlled frozen export workspace setup failure')
            def close_message():
                box=QApplication.activeModalWidget()
                if isinstance(box,QMessageBox):
                    observed.append(box.text())
                    _capture(box,out/'setup-failure-message.png')
                    box.accept()
            def explain(*args,**kwargs):
                QTimer.singleShot(300,close_message)
                return message(*args,**kwargs)
            self.timer.stop()  # the modal dialog has its own event loop
            studio_ui.StudioExportWorkspace=fail
            studio_ui.studio_message_box=explain
            try:
                QTest.mouseClick(p.studio_render_button,Qt.LeftButton)
            finally:
                studio_ui.StudioExportWorkspace=constructor
                studio_ui.studio_message_box=message
                self.timer.start(30)
            self.check('setup-failure-visible-message',bool(observed) and 'controlled frozen' in observed[0])
            self.check('setup-failure-workspace-cleared',p.export_workspace is None)
            self.check('setup-failure-interaction-restored',p.video_compositor._interaction_enabled)
            self.check('setup-failure-return-state-cleared',p._export_return_ui is None)
            self.check('setup-failure-entry-retry-enabled',p.studio_render_button.isEnabled())

        def subtitle_files(self, label):
            p=self.page
            # This is the real export dialog and its write/read-back path.
            d=SubtitleExportDialog(p.project,p.project_path,p,export_on_accept=True)
            d.show()
            d.destination_modes['project'].click()
            for name,card in d.format_checks.items():
                card.setChecked(name=='srt')
            d.speaker_modes['both'].click()
            if hasattr(d,'language_checks'):
                for name,box in d.language_checks.items():
                    box.setChecked(name=='original')
            d._refresh_preview()
            self.check(label+'-subtitle-button',d.export_button.isEnabled())
            QTest.mouseClick(d.export_button,Qt.LeftButton)
            self.check(label+'-subtitle-files',bool(d.artifacts) and all(a.path.stat().st_size>0 for a in d.artifacts))
            self.result['events'].append(dict(label=label,subtitle_files=[str(a.path) for a in d.artifacts],
                cue_counts=[a.cue_count for a in d.artifacts],warning=d.warning.text()))
            _capture(d,out/(label+'-subtitles.png'))
            d.close()
            d.deleteLater()

        def video(self,label,action='success'):
            p=self.page
            held=os.environ.get('OLD_EXPORT_HELD')=='1'
            hit=window.childAt(p.studio_render_button.mapTo(window,p.studio_render_button.rect().center()))
            if not held:
                self.check(label+'-entry-unobstructed',hit is p.studio_render_button or (hit is not None and p.studio_render_button.isAncestorOf(hit)))
            self.result['events'].append(dict(label=label,preview=str(p._preview_path),
                enabled=p.studio_render_button.isEnabled(),schema=p.project.schema_version,cues=len(p.project.cues),
                controlled_dispatch=held,loading_overlay=p._readiness.overlay.isVisible()))
            QTest.mouseClick(p.studio_render_button,Qt.LeftButton)
            yield .2
            _capture(window,out/(label+'-entry.png'))
            self.check(label+'-workspace',p.export_workspace is not None)
            ui=p.export_workspace
            ui.directory.setText(str(out))
            ui.filename_prefix.setText('')
            ui.filename_suffix.setText('')
            ui.filename.setText(label)
            ui.resolution.setCurrentIndex(0)
            i=ui.encoder.findData('libx264')
            if i>=0: ui.encoder.setCurrentIndex(i)
            from ..projects.project_range import set_range
            start=min(c.start_ms for c in p.project.cues)
            set_range(p.project,start,start+2000)
            ui._update_range()
            if action=='failure':
                target=ui.export_target().full_path
                target.write_bytes(b'protected existing output')
            QTest.mouseClick(ui.export_button,Qt.LeftButton)
            if action=='cancel':
                ui._cancel_export()
            while ui._running:
                yield .1
            yield .2
            if action=='success':
                target=ui.export_target().full_path
                self.result['events'].append(dict(label=label,failure=ui.failure_reason.text(),details=getattr(ui,'_last_failure','')))
                _capture(window,out/(label+'-terminal.png'))
                self.check(label+'-video-published',target.is_file() and target.stat().st_size>1000)
                self.result['events'].append(dict(label=label,video=str(target)))
            elif action=='failure':
                self.check(label+'-failure-explained',ui.pages.currentWidget() is ui.failure_page)
                self.check(label+'-existing-preserved',target.read_bytes()==b'protected existing output')
            else:
                self.check(label+'-cancel-cleared',not ui._running)
            _capture(window,out/(label+'-terminal.png'))
            p._close_export_workspace()
            self.check(label+'-entry-restored',p.studio_render_button.isEnabled())
            yield .2

        def open(self,path):
            self.page.open_project(path)
            for _ in range(600):
                if self.page.project_path and self.page.project_path.resolve()==path.resolve() and self.page._project_view_state=='open':
                    break
                yield .05
            if os.environ.get('OLD_EXPORT_HELD')!='1':
                while self.page._readiness.overlay.isVisible():yield .05
            yield 1.
            self.check(path.stem+'-loaded',self.page.project_path.resolve()==path.resolve())

        def run(self):
            while window.built_page('studio') is None:
                yield .05
            self.page=window.built_page('studio')
            p=self.page
            while p.project is None or p._project_view_state!='open':
                yield .05
            if os.environ.get('OLD_EXPORT_HELD')!='1':
                while p._readiness.overlay.isVisible():yield .05
            if os.environ.get('OLD_EXPORT_OFFLINE_ONLY')=='1':
                yield from self.offline()
                return
            if os.environ.get('OLD_EXPORT_COLD_NEW')=='1':
                self.subtitle_files('new-cold')
                yield from self.video('new-cold')
                yield from self.open(out/'old.2byteproj')
            if os.environ.get('OLD_EXPORT_HELD')!='1':
                self.setup_failure()
            self.subtitle_files('old-cold')
            p._preview_path=None
            self.check('video-entry-without-disposable-preview',p._preview_path is None)
            yield from self.video('old-cold')
            if os.environ.get('OLD_EXPORT_BASELINE')=='1':
                return
            yield from self.video('old-failure','failure')
            yield from self.video('old-retry')
            yield from self.video('old-cancel','cancel')
            yield from self.video('old-after-cancel')
            # Save a copy through the product's atomic saver; compare user fields
            # to the in-memory data, then close/reopen the actual saved file.
            saved=out/'saved.2byteproj'
            before=p.project.to_dict()
            save_project(p.project,saved)
            reread=load_project(saved).to_dict()
            self.check('saved-data-roundtrip',all(before[k]==reread[k] for k in ('cues','speakers','styles','style_recipes','generation_metadata','edit_sequence')))
            yield from self.open(out/'new.2byteproj')
            self.subtitle_files('new')
            yield from self.video('new')
            yield from self.open(saved)
            self.subtitle_files('saved-reopened')
            yield from self.video('saved-reopened')
            yield from self.open(out/'offline.2byteproj')
            yield from self.offline()
            yield from self.open(out/'new.2byteproj')
            yield from self.video('new-after-offline')

        def offline(self):
            p=self.page
            self.subtitle_files('offline')
            QTest.mouseClick(p.studio_render_button,Qt.LeftButton)
            yield .2
            ui=p.export_workspace
            self.check('offline-workspace',ui is not None)
            ui.filename.setText('offline-video')
            QTest.mouseClick(ui.export_button,Qt.LeftButton)
            while ui._running: yield .1
            self.check('offline-video-explained',ui.pages.currentWidget() is ui.failure_page)
            self.result['events'].append(dict(label='offline',message=ui.failure_reason.text() if hasattr(ui,'failure_reason') else str(ui._last_job)))
            yield .3
            _capture(window,out/'offline-reason.png')
            p._close_export_workspace()

    window._old_project_export_audit=Audit()
