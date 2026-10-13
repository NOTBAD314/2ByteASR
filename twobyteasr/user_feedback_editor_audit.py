"""Opt-in UI acceptance; admission is owned by studio_acceptance_audit."""
import copy
import json
import os
from pathlib import Path
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QObject, QEvent, QPointF, QTimer, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox, QMenu
    from .blank_project_audit import _capture
    from .build_identity import launch_identity_payload
    from .studio_project import load_project, studio_settings_path, load_library_index

    app = QApplication.instance()
    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = dict(passed=True, checks=[], shots=[], build=launch_identity_payload(), pid=os.getpid(),
                               real_user_click=False, dpr=window.devicePixelRatioF())
            self.started = time.monotonic()
            self.gen = self.run()
            self.until = time.monotonic() + 1
            self.timer = QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(40)

        def check(self, name, value, detail=None):
            self.result['checks'].append(dict(name=name, passed=bool(value), detail=detail))
            if not value: raise AssertionError(name)

        def write(self):
            (output/'result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2, default=str), 'utf8')

        def shot(self, name, widget=None):
            path = output/(name+'.png'); _capture(widget or window, path)
            self.result['shots'].append(str(path)); self.write()

        def mouse(self, widget, kind, point, modifiers):
            event = QMouseEvent(kind, point, widget.mapToGlobal(point.toPoint()).toPointF(),
                                Qt.NoButton if kind == QEvent.MouseMove else Qt.LeftButton,
                                Qt.NoButton if kind == QEvent.MouseButtonRelease else Qt.LeftButton, modifiers)
            app.sendEvent(widget, event)

        def gesture(self, timeline, modifier, dx):
            cue = next(c for c in timeline.visible_cues() if c.id == 'a')
            y = timeline._track_layout()[0][cue.speaker_id].center().y()
            origin = QPointF(timeline._time_to_x((cue.start_ms+cue.end_ms)//2), y)
            self.mouse(timeline, QEvent.MouseButtonPress, origin, modifier)
            self.mouse(timeline, QEvent.MouseMove, origin+QPointF(dx,0), modifier)
            timeline._flush_timing_preview()
            self.shot('ctrl-preview' if modifier == Qt.ControlModifier else 'alt-preview')
            self.mouse(timeline, QEvent.MouseButtonRelease, origin+QPointF(dx,0), modifier)

        def run(self):
            page = window.studio_page
            deadline = time.monotonic()+45
            while page.project is None or getattr(page._readiness, 'active', False):
                self.check('startup deadline', time.monotonic()<deadline)
                yield .1
            self.check('owned fixture opened', Path(page.project_path).resolve() == output/'fixture.2byteproj')
            yield .4
            for maximized in (False, True):
                window.showMaximized() if maximized else window.showNormal()
                yield .3
                before = window.geometry().getRect()
                QTest.mouseClick(page.studio_minimize_button, Qt.LeftButton) if hasattr(page,'studio_minimize_button') else window.showMinimized()
                yield .3
                window._desktop_intake.receive_external([]) if hasattr(window,'_desktop_intake') else __import__('twobyteasr.window_constraints', fromlist=['restore_minimized_window']).restore_minimized_window(window)
                yield .4
                self.check('restored maximized='+str(maximized), not window.isMinimized() and window.isMaximized()==maximized,
                           dict(before=before, after=window.geometry().getRect()))
                if maximized:
                    bounds=window.screen().availableGeometry()
                    self.check('maximized fills available screen', window.geometry() == bounds,
                               dict(window=window.geometry().getRect(), available=bounds.getRect()))
                self.shot('restored-max' if maximized else 'restored-normal')
            window.showNormal(); window.resize(1600,950)
            yield .3
            timeline=page.timeline; timeline.set_visible_window(0,10000); timeline.set_snap_enabled(False)
            page.video.set_paused(True)
            page._set_timeline_tool('selection'); page.cue_controller.select_cue('a')
            yield .2
            before=copy.deepcopy(page.project.to_dict()); count=page.undo_stack.count()
            self.gesture(timeline,Qt.ControlModifier,70)
            yield .3
            cue=next(c for c in page.project.cues if c.id=='a')
            self.check('Ctrl keeps start and extends end',cue.start_ms==1000 and cue.end_ms>3000)
            self.check('Ctrl one undo',page.undo_stack.count()==count+1)
            page.undo_stack.undo(); yield .2
            self.check('Ctrl undo restores project',page.project.to_dict()==before)
            page.cue_controller.select_cue('a')
            self.gesture(timeline,Qt.AltModifier,100)
            yield .3
            self.check('Alt copies and preserves originals',len(page.project.cues)==3 and
                       next(c for c in page.project.cues if c.id=='a').start_ms==1000)
            self.check('fresh IDs',len({c.id for c in page.project.cues})==3)
            page.undo_stack.undo();yield .2
            self.check('Alt undo restores project',page.project.to_dict()==before)
            page._seek(7.5)
            yield .6
            actual_playhead = int(timeline.playhead_ms)
            self.check('add subtitle button visible',page.add_subtitle_button.isVisible())
            QTest.mouseClick(page.add_subtitle_button,Qt.LeftButton)
            yield .3
            self.check('add creates block',len(page.project.cues)==3)
            created = next(c for c in page.project.cues if c.id not in {'a','b'})
            self.check('manual block begins at playhead',created.start_ms == actual_playhead,
                       dict(playhead=actual_playhead, start=created.start_ms))
            editor=getattr(page,'_canvas_editor',None)
            self.check('add opens text editor',editor is not None and editor.isVisible())
            editor.setPlainText('手动添加字幕')
            QTest.keyClick(editor,Qt.Key_Return)
            yield .3
            self.check('manual text committed',any(c.text=='手动添加字幕' for c in page.project.cues))
            self.shot('added-subtitle')
            page.project_controller.save();yield .2
            saved=load_project(output/'fixture.2byteproj')
            self.check('manual subtitle saved',any(c.text=='手动添加字幕' for c in saved.cues))

            # Open the actual settings dialog through its shared entry. A timer
            # supplies typed path input and clicks its real Save button.
            newroot=output/'other-disk'/'Models'
            def settings():
                from .application_settings_ui import ApplicationSettingsDialog
                dialog=next((w for w in app.topLevelWidgets() if isinstance(w,ApplicationSettingsDialog) and w.isVisible()),None)
                if dialog is None:return
                timer.stop();dialog.model_root_edit.setText(str(newroot));self.shot('model-directory-settings',dialog)
                QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.Save),Qt.LeftButton)
            timer=QTimer(self);timer.timeout.connect(settings);timer.start(150)
            window._open_application_settings(initial_section='存储与缓存')
            from .runtime_paths import get_runtime_paths
            self.check('model directory saved',get_runtime_paths().model_root==newroot)
            self.check('new model directory writable',newroot.is_dir())
            self.check('saved runtime model destination',json.loads((get_runtime_paths().config_root/'runtime_paths.json').read_text('utf8'))['model_root']==str(newroot))
            QTest.mouseClick(page.studio_back_button,Qt.LeftButton);yield .5
            self.check('back to library',page.project is None)
            # Exercise the production popup action and production confirmation.
            def menus():
                popup=app.activePopupWidget()
                if isinstance(popup,QMenu):
                    action=next((a for a in popup.actions() if a.text()=='删除工程'),None)
                    if action:QTest.mouseClick(popup,Qt.LeftButton,pos=popup.actionGeometry(action).center())
                modal=app.activeModalWidget()
                if isinstance(modal,QMessageBox) and modal.windowTitle()=='删除工程':
                    QTest.mouseClick(modal.button(QMessageBox.Yes),Qt.LeftButton)
            timer=QTimer(self);timer.timeout.connect(menus);timer.start(100)
            page._recent_project_menu(str(output/'fixture.2byteproj'));timer.stop()
            yield 1.5
            self.check('last file deleted',not (output/'fixture.2byteproj').exists())
            self.check('last recent cleared',not json.loads(studio_settings_path().read_text('utf8')).get('recent_projects'))
            self.check('last index cleared',str(output/'fixture.2byteproj') not in load_library_index())
            self.shot('last-project-deleted')
            self.check('empty library visible',page.project_library_empty.isVisible(),
                       dict(records=getattr(page,'_hub_library_records',None),
                            error=page.hub_loading_label.text(), hub=page.studio_empty.isVisible()))

        def tick(self):
            if time.monotonic()<self.until:return
            try:
                delay=next(self.gen);self.until=time.monotonic()+float(delay or 0)
            except StopIteration:self.finish()
            except Exception:
                self.result['passed']=False;self.result['error']=traceback.format_exc()
                try:self.shot('failure')
                except Exception:pass
                self.finish()

        def finish(self):
            self.timer.stop();self.result['elapsed_seconds']=time.monotonic()-self.started
            window.result_exit_code=0 if self.result['passed'] else 1
            self.write()
            def stopped():self.result['gui_shutdown']=True;self.write()
            app.aboutToQuit.connect(stopped)
            # A failed edit must not leave a save prompt in unattended QA.
            if window.studio_page.project is not None:window.studio_page.undo_stack.setClean()
            window.close()
    window._user_feedback_audit=Audit()
