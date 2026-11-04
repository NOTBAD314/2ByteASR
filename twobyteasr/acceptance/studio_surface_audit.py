"""Source audit of native lifecycle, recognition geometry and no-thumbnail clips."""
import ctypes
from ctypes import wintypes as W
import json
import os
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QAbstractNativeEventFilter, QEvent, QObject, QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QMessageBox, QWidget
    from twobyteasr.app import window_native_frame as frame
    from twobyteasr.app.window_constraints import native_frame
    from twobyteasr.design.theme_manager import apply_theme
    from twobyteasr.acceptance.blank_project_audit import _capture

    app = QApplication.instance(); page = window.built_page('studio')
    loading=getattr(window,'_studio_loading_session',None)
    (output/'startup-state.json').write_text(json.dumps(dict(page=page is not None,
        project=getattr(getattr(page,'project',None),'project_id',None),
        readiness=getattr(getattr(page,'_readiness',None),'active',None),
        loading=getattr(loading,'state',None),deliveries=getattr(loading,'deliveries',None),
        fresh=getattr(window,'_surface_fresh_step',0))), 'utf8')
    if (page is None or page.project is None or getattr(page,'_project_load_in_progress',False)
            or getattr(getattr(page,'_readiness',None),'active',False)
            or loading is not None and (loading.active or not loading.deliveries)):
        QTimer.singleShot(250,lambda:start(window,output))
        return
    spec = json.loads((output/'input.json').read_text('utf8'))
    if spec.get('wait_focus') and not (output/'visible-continue').exists():
        (output/'visible-ready.json').write_text(json.dumps(dict(hwnd=int(window.internalWinId()),pid=os.getpid())), 'utf8')
        QTimer.singleShot(250,lambda:start(window,output));return
    if spec.get('fresh_import'):
        step=getattr(window,'_surface_fresh_step',0)
        if step==0:
            cache=page.timeline._thumbnails;cache.set_paused(True);cache.memory.clear();cache.samples.clear()
            window._surface_fresh_step=2;page._begin_media_ingest(spec['import_source'])
            QTimer.singleShot(250,lambda:start(window,output));return
        if page._media_ingest_state!='READY':
            QTimer.singleShot(250,lambda:start(window,output));return
    result = dict(passed=False, failures=[], checks=[], frames=[], events=[], screenshots=[],
        platform=str(sys.getwindowsversion()), pid=os.getpid(), dpr=window.devicePixelRatioF(),
        pixel_source='Qt widget grabs and PrintWindow on private Windows desktop; not physical display scanout',
        native_dispatch={})
    from twobyteasr.diagnostics.build_identity import load_build_identity
    result.update(identity=load_build_identity().to_dict(),executable=sys.executable,
        frozen=bool(getattr(sys,'frozen',False)))
    t0 = time.perf_counter()
    result['started_at_perf']=t0
    class Phase(list):
        def __setitem__(self,key,value):
            super().__setitem__(key,value)
            if spec.get('visible'):
                (output/'probe-phase.json').write_text(json.dumps(dict(phase=value)), 'utf8')
    phase = Phase(['startup'])
    import faulthandler
    stack_file=(output/'audit-blocked.txt').open('w')
    faulthandler.dump_traceback_later(30,repeat=True,file=stack_file)
    def write():
        (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')
    def check(name, passed, detail=None):
        result['checks'].append(dict(name=name, passed=bool(passed), detail=detail))
        if not passed: result['failures'].append(name)
        write()
    def wait(predicate, seconds=50):
        end = time.monotonic()+seconds
        while not predicate() and time.monotonic()<end: QTest.qWait(25)
        if not predicate(): raise RuntimeError('wait timeout '+phase[0])
    def snapshot(name):
        state = native_frame(window)
        result['frames'].append(dict(t_ms=round((time.perf_counter()-t0)*1000,2), phase=phase[0],
            name=name, native=state, qt=list(window.geometry().getRect()), hwnd=int(window.internalWinId() or 0),
            visible=window.isVisible(), maximized=window.isMaximized(),
            margins=list(window.contentsMargins().toTuple()) if hasattr(window.contentsMargins(),'toTuple') else
                [window.contentsMargins().left(),window.contentsMargins().top(),window.contentsMargins().right(),window.contentsMargins().bottom()]))
    native_original = frame.handle_message
    def handled(w, message, *args, **kwargs):
        value = native_original(w, message, *args, **kwargs)
        if w is window:
            key = hex(message); result['native_dispatch'][key] = result['native_dispatch'].get(key,0)+1
        return value
    frame.handle_message = handled
    class NativeObserver(QAbstractNativeEventFilter):
        def nativeEventFilter(self, event_type, message):
            msg = W.MSG.from_address(int(message))
            if int(msg.hWnd or 0)==int(window.internalWinId() or 0) and msg.message in {
                0x0002,0x0082,0x0005,0x0046,0x0047,0x0083,0x0085,0x0086,0x0018,0x031A,0x02E0}:
                if len(result['events'])<4000:
                    result['events'].append(dict(t_ms=round((time.perf_counter()-t0)*1000,2),phase=phase[0],
                        message=hex(msg.message),hwnd=int(msg.hWnd),wparam=int(msg.wParam)))
            return False, 0
    observer = NativeObserver(); app.installNativeEventFilter(observer)
    class Keys(QObject):
        def eventFilter(self, obj, event):
            if event.type() in {QEvent.KeyPress,QEvent.Shortcut,QEvent.WindowActivate,QEvent.WindowDeactivate}:
                if len(result['events'])<4000:
                    result['events'].append(dict(t_ms=round((time.perf_counter()-t0)*1000,2),phase=phase[0],
                        event=event.type().name,target=obj.objectName(),key=event.key() if hasattr(event,'key') else None))
            return False
    keys = Keys(window); app.installEventFilter(keys)
    timer = QTimer(window); timer.timeout.connect(lambda:snapshot('sample')); timer.start(16)
    (output/'sequence').mkdir()
    capture_count = [0]
    def capture_tick():
        if spec.get('screen_only'):return
        if window.isVisible() and capture_count[0]<180:
            # PrintWindow asks Windows to draw the NC frame as well as the
            # client: a separate, explicitly labelled regression probe.
            file = f'{capture_count[0]:04d}-{phase[0]}.png'
            _capture(window, output/'sequence'/file)
            capture_count[0]+=1
    captures = QTimer(window); captures.timeout.connect(capture_tick)
    def shot(name, widget):
        widget.grab().save(str(output/(name+'.png'))); result['screenshots'].append(name)
    def answer(button):
        box=app.activeModalWidget()
        if isinstance(box,QMessageBox):
            target=box.button(button)
            if target is not None:
                result.setdefault('exit_answers',[]).append(int(button.value))
                QTest.keyClick(target,Qt.Key_Return);return
        QTimer.singleShot(20,lambda:answer(button))
    def perform():
        try:
            wait(lambda:page.project is not None and not getattr(page,'_project_load_in_progress',False))
            wait(lambda:page._media_ingest_state=='READY', 60)
            page.video.set_paused(True)
            apply_theme(spec['theme'], app); QTest.qWait(200)
            window._ui_zoom.request(spec['zoom']);QTest.qWait(150)
            if spec.get('fresh_import'):
                phase[0]='fresh-import'
                check('fresh import has zero captions and a valid clip',not page.project.cues and bool(page.project.video_tracks[0].clips))
                shot('fresh-import-no-thumbnails',page.timeline)
            phase[0]='no-thumbnails'
            shot('timeline-initial',page.timeline)
            cache=page.timeline._thumbnails;cache.close();cache.memory.clear();cache.samples.clear()
            page.timeline._invalidate_static_timeline('audit-empty-thumbnails') if hasattr(page.timeline,'_invalidate_static_timeline') else page.timeline.update()
            page.timeline.visible_start_ms=0;page.timeline.visible_duration_ms=round(page.project.media.duration_ms*1.25)
            page.timeline._static_timeline_dirty=True;page.timeline.update();QTest.qWait(150)
            shot('timeline-no-thumbnails',page.timeline)
            result['clip_baseline']=dict(segments=[s.to_dict() if hasattr(s,'to_dict') else vars(s) for s in page.timeline._sequence.segments]
                if hasattr(page.timeline,'_sequence') else [], empty_cache=len(cache.memory)==0)
            phase[0]='recognition-sheet';page._open_recognition_sheet();QTest.qWait(250)
            host=window._modal_host if hasattr(window,'_modal_host') else window.modal_host
            sheet=page._recognition_controls
            combo=sheet['plan'];header=combo.parentWidget()
            result['selector']=dict(combo=list(combo.geometry().getRect()),parent=list(header.rect().getRect()),
                minimum=combo.minimumHeight(),maximum=combo.maximumHeight(),size_hint=combo.sizeHint().height(),
                font=combo.font().pixelSize())
            check('selector fits title row',header.rect().contains(combo.geometry()),result['selector'])
            shot('recognition-dialog',host.card);shot('recognition-context',host)
            combo.showPopup();QTest.qWait(80)
            shot('recognition-popup',combo.view().window())
            view=combo.view();next_index=(combo.currentIndex()+1)%combo.count()
            index=combo.model().index(next_index,0);view.scrollTo(index);QTest.qWait(30)
            QTest.mouseClick(view.viewport(),Qt.LeftButton,pos=view.visualRect(index).center());QTest.qWait(80)
            check('popup item selects and closes',not view.isVisible() and combo.currentIndex()==next_index)
            for percent in (() if spec.get('skip_zoom_cycle') else (80,100,120)):
                window._ui_zoom.request(percent);QTest.qWait(450)
                check('selector fits at zoom '+str(percent),header.rect().contains(combo.geometry()),
                    dict(combo=list(combo.geometry().getRect()),parent=list(header.rect().getRect()),
                         header_type=type(header).__name__,minimum=header.minimumHeight(),hint=header.sizeHint().height()))
                shot('recognition-dialog-z'+str(percent),host.card)
            window._ui_zoom.request(spec['zoom']);QTest.qWait(100)
            host.hide_content();QTest.qWait(80)
            if spec.get('range_replay'):
                phase[0]='range-replay'
                from twobyteasr.acceptance.studio_surface_range_audit import verify
                result['range_replay']=verify(page,output,spec,check);write()
            if spec.get('layout_only'):
                result['passed']=not result['failures'];return
            if spec.get('visible'):
                import subprocess
                from pathlib import Path
                (output/'probe-config.json').write_text(json.dumps(dict(hwnd=int(window.internalWinId()))),'utf8')
                probe_python=os.environ.get('TWOBYTEASR_SCREEN_PROBE_PYTHON') or sys.executable
                if getattr(sys,'frozen',False) and probe_python==sys.executable:
                    raise RuntimeError('Frozen screen probe requires its explicit external Python')
                window._surface_probe=subprocess.Popen([probe_python,'-B',str(Path(__file__).resolve().parents[2]/'scripts/studio_surface_edge_probe.py'),str(output)],
                    creationflags=0x08000000)
                wait(lambda:(output/'probe-ready').exists(),10)
            for mode in ('normal','maximized'):
                phase[0]=mode+'-start'
                window.showNormal() if mode=='normal' else window.showMaximized();QTest.qWait(200)
                snapshot('before');captures.start(50)
                phase[0]=mode+'-page-enter';page.timeline.setFocus();QTest.keyClick(page.timeline,Qt.Key_Return);QTest.qWait(130)
                phase[0]=mode+'-input-enter'
                edit=page.cue_search;edit.setFocus();QTest.keyClick(edit,Qt.Key_Return);QTest.qWait(130)
                if page.project.cues:
                    phase[0]=mode+'-editor-open'
                    cue=page.project.cues[0];page.video.set_paused(True);page._seek((cue.start_ms+20)/1000)
                    page.select_cue(cue.id);page.timeline.setFocus();QTest.keyClick(page.timeline,Qt.Key_E)
                    wait(lambda:page.subtitle_edit_dock.isVisible())
                    edit=page.subtitle_edit_input;QTest.mouseClick(edit.viewport(),Qt.LeftButton)
                    before_count=page.undo_stack.index();old=cue.text;phase[0]=mode+'-editor-input';QTest.keyClicks(edit,'!')
                    phase[0]=mode+'-editor-enter'
                    QTest.keyClick(edit,Qt.Key_Return);QTest.qWait(100)
                    check(mode+' Enter submits once and closes',page.undo_stack.index()==before_count+1 and not page.subtitle_edit_dock.isVisible())
                    page.undo_stack.undo();page.save();QTest.qWait(100)
                phase[0]=mode+'-focus-away'
                peer=QWidget();peer.setWindowTitle('Owned focus probe');peer.resize(260,90);peer.show();peer.activateWindow();QTest.qWait(130)
                phase[0]=mode+'-focus-return';window.activateWindow();window.raise_();QTest.qWait(130);peer.close()
                phase[0]=mode+'-dialog';page._open_recognition_sheet();QTest.qWait(100)
                QTest.keyClick(page._recognition_controls['plan'],Qt.Key_Return);QTest.qWait(100)
                host.hide_content();QTest.qWait(100)
                if not spec.get('screen_only'):
                    phase[0]=mode+'-explicit-ncpaint'
                    u=ctypes.WinDLL('user32');u.SendMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM]
                    u.SendMessageW(W.HWND(int(window.internalWinId())),0x0085,1,0)
                    QTest.qWait(100)
                phase[0]=mode+'-resize-restore'
                window.showNormal();window.resize(1320,820);QTest.qWait(100)
                window.showMaximized() if mode=='maximized' else window.resize(1600,980)
                QTest.qWait(100)
                snapshot('after');captures.stop()
            for message in ('0x85','0x86'):
                received=sum(e.get('message')==message for e in result['events'])
                check('native frame dispatch '+message,received>0 and result['native_dispatch'].get(message,0)>0,
                    dict(received=received,dispatched=result['native_dispatch'].get(message,0)))
            phase[0]='return-home';page._request_return_home();QTest.qWait(150);snapshot('home')
            phase[0]='return-studio';window._switch_page(page);QTest.qWait(150)
            # The actual dirty-save gate: cancel once, then save and close.
            if page.project.cues:
                cue=page.project.cues[0];page.cue_controller.set_text(cue.id,cue.text+' · exit probe')
            else:
                page.undo_stack.setClean();page.project.studio_state['surface_audit_dirty']=True
                page.undo_stack.push(__import__('PySide6.QtGui',fromlist=['QUndoCommand']).QUndoCommand('owned exit probe'))
            phase[0]='cancel-exit';captures.start(50)
            QTimer.singleShot(60,lambda:answer(QMessageBox.Cancel));window.close();QTest.qWait(150)
            check('cancel exit keeps window visible',window.isVisible() and not getattr(window,'_studio_close_pending',False))
            result['passed']=not result['failures']
        except Exception:
            result['error']=traceback.format_exc()
        finally:
            write();phase[0]='save-confirm-exit'
            window.result_exit_code=0 if result['passed'] else 1
            QTimer.singleShot(60,lambda:answer(QMessageBox.Save))
            window.close()
    def closed():
        captures.stop();timer.stop();snapshot('about-to-quit')
        faulthandler.cancel_dump_traceback_later();stack_file.close()
        result['gui_shutdown']=True;frame.handle_message=native_original;write()
    app.aboutToQuit.connect(closed)
    window._surface_audit_refs=(observer,keys,timer,captures)
    QTimer.singleShot(500,perform)
