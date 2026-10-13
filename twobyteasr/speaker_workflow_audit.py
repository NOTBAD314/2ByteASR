"""Opt-in normal-app verification of toolbar routes and transient shuttle state."""
from __future__ import annotations
import json
import time
import traceback
import os
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def start(window, out):
    page = window.studio_page
    result = {'passed': False, 'checks': [], 'snapshots': [], 'playback_limit_seconds': 8, 'audio': 'silent source and volume=0'}
    playing_since=[None]
    watchdog=QTimer(window)
    watchdog.setInterval(25)
    def limit_playback():
        if page.video._paused:playing_since[0]=None
        elif playing_since[0] is None:playing_since[0]=time.monotonic()
        elif time.monotonic()-playing_since[0]>=7.8:
            page.video.set_paused(True)
            result['playback_watchdog_triggered']=True
    watchdog.timeout.connect(limit_playback)
    watchdog.start()
    def check(name, condition, detail=None):
        result['checks'].append({'name':name,'passed':bool(condition),'detail':detail})
        if not condition:
            raise AssertionError(name)
    def wait_for(predicate, seconds=4):
        deadline = time.monotonic()+seconds
        while not predicate() and time.monotonic()<deadline:
            QTest.qWait(20)
        return bool(predicate())
    def snapshot(name):
        clock = page.video.playback_position_snapshot()
        value = dict(name=name, paused=page.video._paused, shuttle=getattr(page,'_shuttle_rate',None),
            effective=getattr(page,'_shuttle_speed',1), ui=page.speed_box.currentData(), video=clock.playback_rate,
            startup=page.video._startup_state, buffered=page.video._buffered_play_pending,
            buffer_ready=page._playback_buffers_ready(), source_dead=page.video.playback_source_dead,
            compositor=page.video_compositor.performance_snapshot(),
            audio_request=dict(page.audio_engine._last_payload), audio=page.audio_engine.telemetry_snapshot())
        result['snapshots'].append(value)
        return value
    def rate_is(value):
        state = page.video.playback_position_snapshot()
        return (abs(float(state.playback_rate)-value)<.001 and page.speed_box.currentData()==value
                and abs(float(page.audio_engine._last_payload.get('transport_rate',1))-value)<.001)
    def focus():
        window.raise_(); window.activateWindow(); page.timeline.setFocus()
        QTest.qWait(30)
    def key(value):
        focus(); QTest.keyClick(page.timeline, value); QTest.qWait(50)
    def play_button():
        QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton); QTest.qWait(50)
    def dialog_action(button, kind, operation):
        errors = []
        def inspect():
            dialog = QApplication.activeModalWidget()
            try:
                check('existing '+kind.__name__+' opened', isinstance(dialog,kind))
                operation(dialog)
            except Exception:
                errors.append(traceback.format_exc())
            finally:
                if dialog is not None and dialog.isVisible(): dialog.reject()
        QTimer.singleShot(200, inspect)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        if errors: raise AssertionError(errors[0])

    def native_shot(name):
        from PIL import Image, ImageStat
        import ctypes
        # Windows may refuse focus activation by a process launched hidden.
        # Pin only this owned test HWND above other apps without recreating it.
        user32=ctypes.windll.user32
        hwnd=int(window.winId())
        user32.SetWindowPos.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_uint]
        user32.SetWindowPos(hwnd,ctypes.c_void_p(-1),0,0,0,0,0x0001|0x0002|0x0010)
        window.raise_(); window.activateWindow()
        QTest.qWait(60)
        # Client origin must belong to Studio, not whichever unrelated app is
        # currently foreground. Pixel brightness without ownership proves nothing.
        from ctypes import wintypes
        point=page.mapToGlobal(QPoint(24,24))
        ratio=page.devicePixelRatioF()
        user32.WindowFromPoint.argtypes=[wintypes.POINT]
        user32.WindowFromPoint.restype=ctypes.c_void_p
        user32.GetAncestor.argtypes=[ctypes.c_void_p,ctypes.c_uint]
        user32.GetAncestor.restype=ctypes.c_void_p
        owner=user32.WindowFromPoint(wintypes.POINT(round(point.x()*ratio),round(point.y()*ratio)))
        check(name+' screen belongs to Studio',int(user32.GetAncestor(owner,2) or 0)==hwnd,
              {'expected':hwnd,'root':int(user32.GetAncestor(owner,2) or 0),'point':[point.x(),point.y()],'dpr':ratio})
        pos = page.mapToGlobal(QPoint(0,0))
        pix = page.screen().grabWindow(0,pos.x(),pos.y(),page.width(),page.height())
        pix.save(str(out/(name+'.png')))
        video = page.video.mapTo(page,QPoint(0,0))
        scale = pix.width()/page.width()
        # The central 60% lies inside the actual letterboxed video, avoiding UI.
        rect=(round((video.x()+page.video.width()*.2)*scale),round((video.y()+page.video.height()*.2)*scale),
              round((video.x()+page.video.width()*.8)*scale),round((video.y()+page.video.height()*.8)*scale))
        stats=ImageStat.Stat(Image.open(out/(name+'.png')).convert('RGB').crop(rect))
        check(name+' actual video pixels nonblack',max(stats.mean)>18 and max(stats.stddev)>8,
              {'mean':stats.mean,'stddev':stats.stddev,'roi':rect})

    def identity():
        return (id(page.video), id(page.video.controller), int(page.video.winId()), id(page.video.parent()),
                id(page.video_compositor), id(page.video_compositor.parent()))

    def external_processes():
        import psutil
        names={'node.exe','chrome.exe','chromium.exe','cmd.exe','powershell.exe','pwsh.exe','agy.exe','codex.exe','grok.exe'}
        return {p.pid for p in psutil.Process().children(recursive=True) if p.is_running() and p.name().lower() in names}

    def taskbar_windows():
        import ctypes, os
        user32=ctypes.windll.user32
        found=[]
        callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
        @callback
        def record(hwnd,_):
            pid=ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            if pid.value==os.getpid() and user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd,4) and not (user32.GetWindowLongW(hwnd,-20)&0x80):
                found.append(int(hwnd))
            return True
        user32.EnumWindows(record,0)
        return sorted(found)

    def shortcut_matrix(lanes,playing):
        name=f'V{lanes}-shortcut-'+('playing' if playing else 'paused')
        page.video.set_paused(True)
        page._set_speed(1.)
        page._seek(2.)
        check(name+' buffers ready',wait_for(page._playback_buffers_ready,6))
        QTest.qWait(100)
        if playing:
            play_button()
            check(name+' playing',wait_for(lambda:not page.video._paused,3))
        began=time.monotonic()
        before_id=identity()
        before_windows=taskbar_windows()
        before_processes=external_processes()
        before_context=(page.context_drawer.currentIndex(),page.selected_cue_id,page.timeline.visible_start_ms,page.timeline.visible_duration_ms)
        before_head=page.timeline.playhead_ms
        native_shot(name+'-before')
        QTest.mouseClick(page.studio_shortcut_entry_button,Qt.MouseButton.LeftButton)
        QTest.qWait(80)
        panel=page._shortcut_settings_panel
        check(name+' embedded QWidget page',panel is not None and panel.isVisible() and not panel.isWindow() and panel.window() is window)
        check(name+' no modal window',QApplication.activeModalWidget() is None)
        check(name+' same command source',panel.values()['forward']==page._shortcut_values['forward'])
        check(name+' current play state retained',page.video._paused != playing)
        native_shot(name+'-open')
        check(name+' unchanged taskbar windows',bool(before_windows) and taskbar_windows()==before_windows)
        check(name+' no Node Chrome CLI',not (external_processes()-before_processes))
        QTest.mouseClick(panel.cancel_button,Qt.MouseButton.LeftButton)
        QTest.qWait(70)
        native_shot(name+'-closed')
        check(name+' same canvas controller compositor and parents',identity()==before_id)
        check(name+' selection tab zoom unchanged',before_context==(page.context_drawer.currentIndex(),page.selected_cue_id,page.timeline.visible_start_ms,page.timeline.visible_duration_ms))
        check(name+' state unchanged after close',page.video._paused != playing)
        if not playing: check(name+' paused playhead unchanged',abs(page.timeline.playhead_ms-before_head)<=20)
        check(name+' bounded muted playback',time.monotonic()-began<8 and page.volume_slider.value()==0)
        page.video.set_paused(True)

    def shortcut_editing():
        from PySide6.QtGui import QKeySequence
        original=dict(page._shortcut_values)
        QTest.mouseClick(page.studio_shortcut_entry_button,Qt.MouseButton.LeftButton)
        panel=page._shortcut_settings_panel
        editor=panel._editors['forward']
        panel.table.scrollToItem(panel.table.item(list(panel._editors).index('forward'),0))
        QTest.mouseClick(editor,Qt.MouseButton.LeftButton)
        QTest.keyClick(editor,Qt.Key.Key_Space)
        QTest.qWait(1100)
        check('shortcut conflict reported and save blocked','冲突' in panel.conflict_label.text() and not panel._save_button.isEnabled())
        QTest.mouseClick(panel.reset_button,Qt.MouseButton.LeftButton)
        check('restore defaults clears conflict',panel._save_button.isEnabled())
        QTest.mouseClick(editor,Qt.MouseButton.LeftButton)
        QTest.keyClick(editor,Qt.Key.Key_F8,Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.AltModifier)
        QTest.qWait(1100)
        changed=panel.values()['forward']
        check('shortcut key edited',changed=='Ctrl+Alt+F8',changed)
        QTest.mouseClick(panel._save_button,Qt.MouseButton.LeftButton)
        check('shortcut save applies',page._shortcut_values['forward']==changed)
        QTest.mouseClick(page.studio_shortcut_entry_button,Qt.MouseButton.LeftButton)
        panel=page._shortcut_settings_panel
        check('shortcut saved key reopens',panel.values()['forward']==changed)
        QTest.mouseClick(panel.reset_button,Qt.MouseButton.LeftButton)
        QTest.mouseClick(panel.cancel_button,Qt.MouseButton.LeftButton)
        check('shortcut cancel preserves saved map',page._shortcut_values['forward']==changed)
        QTest.mouseClick(page.studio_shortcut_entry_button,Qt.MouseButton.LeftButton)
        panel=page._shortcut_settings_panel
        QTest.mouseClick(panel.reset_button,Qt.MouseButton.LeftButton)
        QTest.mouseClick(panel._save_button,Qt.MouseButton.LeftButton)
        check('shortcut defaults saved for transport regression',page._shortcut_values['forward']=='L')
    def run():
        try:
            from .studio_find_replace import FindReplaceDialog
            check('startup media ready', wait_for(lambda: page.project is not None and page.video._startup_state=='READY',8))
            page.volume_slider.setValue(0)
            page.video.set_paused(True)
            from .window_audit import win32_top_level_windows
            windows=win32_top_level_windows(pids={os.getpid()})
            result['cold_start_windows']=windows
            visible=[row for row in windows if row['visible'] and not (row['exstyle']&0x80)]
            check('cold startup has only the Studio main window',[row['hwnd'] for row in visible]==[int(window.winId())],visible)
            check('shortcut page not constructed at startup',getattr(page,'_shortcut_settings_panel',None) is None)
            native_shot('cold-start')
            if os.environ.get('TWOBYTEASR_P0_COLD_ONLY')=='1':
                shortcut_editing()
                shortcut_matrix(1,False)
                check('watchdog not triggered',not result.get('playback_watchdog_triggered'))
                result['passed']=True
                return
            check('replacement entry visible', page.studio_find_replace_button.isVisible())
            check('shortcut entry visible', page.studio_shortcut_entry_button.isVisible())
            check('review and assistant retained in overflow', page.review_mode_button in page._studio_toolbar_overflow_widgets and page.studio_clip_assistant_button in page._studio_toolbar_overflow_widgets)
            check('new entries use library icons', not page.studio_find_replace_button.icon().isNull() and not page.studio_shortcut_entry_button.icon().isNull())
            result['toolbar_geometry'] = {button.text(): {'width': button.width(), 'size_hint': button.sizeHint().width(),
                'height': button.height(), 'font': button.font().toString(), 'focus_policy': int(button.focusPolicy())}
                for button in (page.studio_find_replace_button,page.studio_shortcut_entry_button,page.studio_export_button)}
            check('new toolbar labels fit', all(button.width()>=button.sizeHint().width()
                for button in (page.studio_find_replace_button,page.studio_shortcut_entry_button)))
            check('toolbar height font and focus match',all(button.height()==page.studio_export_button.height()
                and button.font()==page.studio_export_button.font() and button.focusPolicy()==page.studio_export_button.focusPolicy()
                for button in (page.studio_find_replace_button,page.studio_shortcut_entry_button)))
            toolbar_buttons=(page.studio_find_replace_button,page.studio_shortcut_entry_button,page.studio_export_button)
            check('adjacent toolbar buttons do not overlap', all(
                left.mapTo(page,QPoint(0,0)).x()+left.width()<=right.mapTo(page,QPoint(0,0)).x()
                for left,right in zip(toolbar_buttons,toolbar_buttons[1:])))
            page.grab().save(str(out/'toolbar.png'))
            def replace(dialog):
                dialog.find_edit.setFocus(); QTest.keyClicks(dialog.find_edit,'alpha')
                dialog.replace_edit.setFocus(); QTest.keyClicks(dialog.replace_edit,'beta')
                QTest.mouseClick(dialog.preview_button,Qt.MouseButton.LeftButton)
                QTest.mouseClick(dialog.all_button,Qt.MouseButton.LeftButton)
                check('existing batch replacement works', page.project.cues[0].text=='beta 回归字幕')
                dialog.grab().save(str(out/'batch-replace.png'))
            dialog_action(page.studio_find_replace_button,FindReplaceDialog,replace)
            page.undo_stack.undo()
            check('replacement undo',page.project.cues[0].text=='alpha 回归字幕')
            shortcut_editing()
            for lanes in (1,2):
                if lanes==2:
                    page.undo_stack.setClean()
                    page.open_project(out/'v2.2byteproj',skip_dirty_guard=True)
                    check('V2 project ready',wait_for(lambda:page.project_path==out/'v2.2byteproj' and page.video._startup_state=='READY'
                          and not getattr(getattr(page,'_readiness',None),'active',False),8))
                page.volume_slider.setValue(0)
                check(f'{lanes} video tracks loaded',len(page.project.video_tracks)==lanes)
                for playing in (False,True):
                    shortcut_matrix(lanes,playing)
                for scenario in ('buttons','space','repeat_L','eof','seek'):
                    page.video.set_paused(True)
                    page._set_speed(1.)
                    page._seek(29.6 if scenario=='eof' else 1.)
                    QTest.qWait(180)
                    check(f'V{lanes}/{scenario} paused buffers ready',wait_for(page._playback_buffers_ready,6))
                    began=time.monotonic()
                    key(Qt.Key.Key_L)
                    if scenario!='eof': key(Qt.Key.Key_L)
                    if scenario=='repeat_L': key(Qt.Key.Key_L);key(Qt.Key.Key_L)
                    check(f'V{lanes}/{scenario} started',wait_for(lambda:not page.video._paused,4))
                    expected_rate = 1. if scenario=='eof' else 8. if scenario=='repeat_L' else 2.
                    check(f'V{lanes}/{scenario} actual shuttle rate',wait_for(lambda:
                        rate_is(expected_rate) and getattr(page,'_shuttle_rate',None)==expected_rate and
                        abs(float(page.audio_engine.telemetry_snapshot().get('effective_rate',0))-expected_rate)<.001,2))
                    snapshot(f'V{lanes}/{scenario}/shuttle')
                    if scenario=='eof':
                        check(f'V{lanes}/eof reached',wait_for(lambda:page.video.at_eof,3))
                    elif scenario=='space': key(Qt.Key.Key_Space)
                    else: play_button()
                    check(f'V{lanes}/{scenario} pause reset',wait_for(lambda:page.video._paused and rate_is(1.)))
                    check(f'V{lanes}/{scenario} transient cleared',getattr(page,'_shuttle_rate',None) is None)
                    ack_started=time.monotonic()
                    check(f'V{lanes}/{scenario} audio process acknowledged 1x',wait_for(lambda:
                        abs(float(page.audio_engine.telemetry_snapshot().get('effective_rate',0))-1.)<.001,1))
                    result.setdefault('audio_rate_ack_ms',{})[f'V{lanes}/{scenario}']=round((time.monotonic()-ack_started)*1000,3)
                    snapshot(f'V{lanes}/{scenario}/paused')
                    if scenario=='seek':
                        page._seek(8.); QTest.qWait(100)
                    if scenario=='space': key(Qt.Key.Key_Space)
                    else: play_button()
                    check(f'V{lanes}/{scenario} normal replay at 1x',wait_for(lambda:not page.video._paused and rate_is(1.),2))
                    QTest.qWait(120)
                    snapshot(f'V{lanes}/{scenario}/replayed')
                    play_button()
                    elapsed = time.monotonic()-began
                    check(f'V{lanes}/{scenario} short silent test',elapsed<8 and page.volume_slider.value()==0,round(elapsed,3))
                for speed in (2.,4.):
                    page.video.set_paused(True)
                    page._seek(1.)
                    box=page.speed_box
                    QTest.mouseClick(box,Qt.MouseButton.LeftButton);QTest.qWait(40)
                    view=box.view()
                    QTest.keyClick(view,Qt.Key.Key_Home)
                    for _ in range(box.findData(speed)):QTest.keyClick(view,Qt.Key.Key_Down)
                    QTest.keyClick(view,Qt.Key.Key_Return)
                    check(f'V{lanes}/manual {speed}x selected',wait_for(lambda:rate_is(speed)))
                    play_button();QTest.qWait(100);play_button()
                    check(f'V{lanes}/manual {speed}x persists on pause',wait_for(lambda:page.video._paused and rate_is(speed)))
            result['passed']=True
        except Exception:
            result['error']=traceback.format_exc()
            try: page.grab().save(str(out/'failure.png'));snapshot('failure')
            except Exception: pass
        finally:
            watchdog.stop()
            page.video.set_paused(True)
            page.undo_stack.setClean()
            (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
            QTimer.singleShot(200,window.close)
    QTimer.singleShot(150,run)
