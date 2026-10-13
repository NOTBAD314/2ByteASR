"""Opt-in normal entry verification of window restore and Studio proofreading."""
import ctypes
import json
import os
import time
import traceback
from ctypes import wintypes as W


def start(window, out):
    from PySide6.QtCore import QEvent, QObject, Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity

    def run():
        page=window.studio_page
        result=dict(passed=False,checks=[],events=[],build=load_build_identity().to_dict())
        def save(): (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        def check(name, ok, detail=None):
            result['checks'].append(dict(name=name,passed=bool(ok),detail=detail));save()
        def pump(seconds=.25):
            end=time.monotonic()+seconds
            while time.monotonic()<end: QApplication.processEvents();time.sleep(.005)
        def wait(test,seconds=75):
            end=time.monotonic()+seconds
            while time.monotonic()<end:
                pump(.025)
                if test():return True
            return False
        def rect(r):return [r.x(),r.y(),r.width(),r.height()]
        def geometry():
            native=W.RECT();u.GetWindowRect(hwnd,ctypes.byref(native))
            return dict(state=window.windowState().value,geometry=rect(window.geometry()),
                available=rect(window.screen().availableGeometry()),screen=rect(window.screen().geometry()),
                native=[native.left,native.top,native.right-native.left,native.bottom-native.top],
                zoomed=bool(u.IsZoomed(hwnd)),resume=str(window._window_bounds.resume_state))
        class Events(QObject):
            def eventFilter(self,obj,event):
                if event.type()==QEvent.WindowStateChange:
                    result['events'].append(dict(old=event.oldState().value,new=window.windowState().value))
                return False
        u=ctypes.WinDLL('user32',use_last_error=True)
        u.ShowWindow.argtypes=[W.HWND,ctypes.c_int]
        u.SendMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM]
        u.GetWindowRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)]
        u.IsZoomed.argtypes=[W.HWND]
        hwnd=W.HWND(int(window.winId()));spy=Events(window);window.installEventFilter(spy)
        from . import window_constraints
        original_constrain=window_constraints.constrain
        def traced_constrain(widget,**kwargs):
            before=geometry() if widget is window else None
            original_constrain(widget,**kwargs)
            if before is not None:
                result.setdefault('bounds_calls',[]).append(dict(before=before,after=geometry()))
        window_constraints.constrain=traced_constrain
        try:
            ready=wait(lambda:page.project and page._readiness.ready and page.video._startup_state=='READY')
            check('media ready',ready)
            if not ready:raise RuntimeError('media did not become ready')
            page.volume_slider.setValue(0);page.video.set_paused(True)
            for mode in ('maximized','fullscreen','normal'):
                for path in ('qt-native','system-native','qt-external','native-external','immediate'):
                    window.showNormal();pump(.15)
                    if mode=='maximized':window.showMaximized()
                    elif mode=='fullscreen':window.showFullScreen()
                    else:window.resize(1600,950);window.move(40,35)
                    wait(lambda: (window.isMaximized() and u.IsZoomed(hwnd)) if mode=='maximized'
                         else window.isFullScreen() if mode=='fullscreen'
                         else window.windowState()==Qt.WindowNoState,3)
                    pump(.25);before=geometry()
                    if mode!='normal':
                        expected=before['available'] if mode=='maximized' else before['screen']
                        check(mode+' fills screen before '+path,before['geometry']==expected,before)
                    for cycle in range(3):
                        if path in ('qt-native','qt-external','immediate'):
                            QTest.mouseClick(page.studio_minimize_button,Qt.LeftButton)
                        else:u.SendMessageW(hwnd,0x112,0xF020,0)
                        if path!='immediate':pump(.12)
                        if path.endswith('external'):
                            from .window_constraints import restore_minimized_window
                            restore_minimized_window(window)
                        else:u.ShowWindow(hwnd,9)
                        wait(lambda:window.windowState().value==before['state'] and
                             rect(window.geometry())==before['geometry'],3)
                        pump(.25)
                        after=geometry()
                        same=before['state']==after['state'] and before['geometry']==after['geometry']
                        if mode!='normal':same=same and after['geometry']==expected
                        check(f'{mode} {path} cycle {cycle}',same,dict(before=before,after=after))
                        if not same:_capture(window,out/f'failure-{mode}-{path}-{cycle}.png')
                    _capture(window,out/f'restore-{mode}-{path}.png')
            window.showMaximized();pump()
            # Drive the new visible entry on the real, currently open document.
            import subtitle_core as legacy
            from .studio_commands import SetCueFieldsCommand
            from .studio_project import load_project
            legacy.add_learned_mapping('验收词库','校对甲','校对乙',origin='手动')
            identity=next(row['id'] for row in legacy.glossary_catalog() if row['name']=='验收词库')
            original_ids=list(page.project.glossary_ids)
            page.project.glossary_ids=[identity]
            cue=page.project.cues[0];original_text=cue.text
            page.undo_stack.push(SetCueFieldsCommand(page.project,cue.id,{'text':original_text+' 校对甲'},'audit unsaved text'))
            check('AI entry visible',page.cue_proofread_button.isVisible())
            _capture(window,out/'01-studio-entry.png')
            QTest.mouseClick(page.cue_proofread_button,Qt.LeftButton)
            check('opens existing proofreading workspace',wait(lambda:
                getattr(window,'glossary_proofread_page',None) is window.pages.currentWidget(),10))
            review=window.glossary_proofread_page
            check('local suggestions finish',wait(lambda:review._worker is None and review._queued is None
                and any(e.get('after')==original_text+' 校对乙' for e in review._entries),30))
            check('binds current document',review._live_project()==(page.project,page))
            check('unsaved text used',any(e.get('after')==original_text+' 校对乙' for e in review._entries),
                dict(text=cue.text,status=review.status_label.text(),entries=str(review._entries),
                     generation=review._generation,queued=review._queued))
            check('AI request remains user initiated',review.ai_button.isVisible())
            pump(.4)
            _capture(window,out/'02-proofread-current.png')
            before=page.undo_stack.index()
            QTest.mouseClick(review.apply_button,Qt.LeftButton)
            check('proofread applied',wait(lambda:cue.text==original_text+' 校对乙',10))
            check('applied to current saved path',load_project(page.project_path).cues[0].text==cue.text)
            check('one undo command',page.undo_stack.index()==before+1)
            check('follow-up match finishes',wait(lambda:review._worker is None,30))
            QTest.mouseClick(review.back_button,Qt.LeftButton);pump()
            check('returns to editor',window.pages.currentWidget() is page)
            page.undo_stack.undo();pump()
            check('undo keeps prior unsaved edit',cue.text==original_text+' 校对甲')
            page.undo_stack.undo();page.project.glossary_ids=original_ids;pump()
            check('prior text restored',cue.text==original_text)
            check('page round trip stays maximized',window.isMaximized() and window.geometry()==window.screen().availableGeometry())
            _capture(window,out/'03-returned-studio.png')
            result['passed']=all(x['passed'] for x in result['checks'])
        except BaseException:result['error']=traceback.format_exc()
        finally:
            window_constraints.constrain=original_constrain
            page.project_dirty=False;page.undo_stack.setClean();save()
            window.close();result['gui_shutdown']=True;save();QApplication.quit()
    QTimer.singleShot(1800,run)
