"""Issue #11 real mpv/Qt/native key and numbered-picture acceptance."""
import ctypes
from fractions import Fraction
import json
import os
import time
import traceback


def start(window,output):
    from PySide6.QtCore import QEvent,QTimer,Qt
    from PySide6.QtGui import QKeyEvent,QTextCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QDialog,QLineEdit
    from PIL import Image
    import hashlib
    import sys
    from pathlib import Path
    from .blank_project_audit import _capture
    from ..studio.studio_helpers import format_timeline_timecode
    result={'passed':False,'checks':[],'samples':[],'input_kind':'Qt events and native WM_KEYDOWN repeat on private desktop'}
    result['code']={name:{'path':str(Path(sys.modules[name].__file__).resolve()),
        'sha256':hashlib.sha256(Path(sys.modules[name].__file__).read_bytes()).hexdigest()}
        for name in ('twobyteasr.studio.studio_ui','twobyteasr.studio.studio_shortcuts',
                     'twobyteasr.studio.studio_playback_flow','twobyteasr.studio.studio_video_canvas',
                     'twobyteasr.playback.studio_mpv','twobyteasr.studio.shortcut_registry')}
    fps=float(Fraction(os.environ['ISSUE_FRAME_FPS']));trim=int(os.environ['ISSUE_FRAME_TRIM_MS'])
    def save():(output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,value,detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail));save()
        return bool(value)
    def pump(seconds=.03):
        end=time.perf_counter()+seconds
        while time.perf_counter()<end:QApplication.processEvents();time.sleep(.003)
    def wait(predicate,seconds=8):
        end=time.perf_counter()+seconds
        while time.perf_counter()<end:
            pump()
            if predicate():return True
        return False
    def run():
        page=getattr(window,'_studio_page_instance',None)
        if page is None:
            QTimer.singleShot(100,run)
            return
        try:
            if not wait(lambda:page.project is not None and page.video.controller is not None
                    and page.video._startup_state=='READY' and page._project_view_state=='open'
                    and not page._native_keys_blocked() and page.video._initial_player_request is None,45):
                raise RuntimeError('normal app/player startup did not become ready')
            window._switch_page(page);window.activateWindow();QApplication.setActiveWindow(window)
            controller=page.video.controller
            def actual():return float(controller.observed_position().get('position') or 0)
            def seek_settled(target):
                request=getattr(getattr(page,'_caption_seek_preparation',None),'pending',None)
                return (request is None and not page.video._playback_clock.exact_seek_pending
                    and abs(actual()*1000-trim-target*1000)<100)
            page.video.set_paused(True);page._seek(1.5)
            if not wait(lambda:seek_settled(1.5),20):raise RuntimeError('initial real media seek did not settle')
            page.video.setFocus();pump(.1)
            def settled():return getattr(page.video,'_frame_step_pending',None) is None
            def sample(name):
                pump(.05)
                target=output/(name+'-video.png')
                controller.screenshot_to_file(str(target),mode='video')
                if not wait(target.is_file):raise RuntimeError('mpv screenshot missing')
                image=Image.open(target).convert('RGB')
                number=sum((1<<bit) for bit in range(10) if sum(image.getpixel((32+bit*40,32)))>380)
                position=actual();expected=round(position*1000)-trim
                data=dict(name=name,source_ms=position*1000,picture_frame=number,clock_ms=page.video.visual_position()*1000,
                    playhead_ms=page.timeline.playhead_ms,timecode=page.position_label.text(),expected_ms=expected,
                    pending=not settled(),mode=page._playback_mode)
                result['samples'].append(data);save()
                check(name+' picture matches actual frame PTS',abs(number-position*fps)<.55,data)
                check(name+' playhead follows actual source mapping',abs(page.timeline.playhead_ms-expected)<=3,data)
                check(name+' timecode follows playhead',page.position_label.text()==format_timeline_timecode(page.timeline.playhead_ms),data)
                current=page._renderer_cue_at_playhead()
                check(name+' current caption follows playhead',current is not None and current.start_ms<=page.timeline.playhead_ms<current.end_ms)
                return data
            before=actual();QTest.keyClick(page.video,Qt.Key_Right);wait(settled);pump(.2)
            check('single forward changes exactly one decoded frame',abs((actual()-before)*fps-1)<.15)
            sample('01-single-forward')
            before=actual();QTest.keyClick(page.video,Qt.Key_Left);wait(settled);pump(.15)
            check('single backward changes exactly one decoded frame',abs((before-actual())*fps-1)<.15)
            sample('02-single-backward')
            before=actual();QTest.keyPress(page.video,Qt.Key_Right);pump(.08)
            for _ in range(8):
                QApplication.sendEvent(page.video,QKeyEvent(QEvent.KeyPress,Qt.Key_Right,Qt.NoModifier,'',True,1));pump(.07)
            QTest.keyRelease(page.video,Qt.Key_Right);wait(settled);pump(.12)
            check('held Qt Right advances multiple real frames',(actual()-before)*fps>=3)
            released=actual();pump(.3);check('release stops repetition',abs(actual()-released)<1e-7)
            sample('03-qt-held-right')
            hwnd=int(page.video.winId());user=ctypes.windll.user32
            before=actual();user.PostMessageW(hwnd,0x100,0x25,1);pump(.12);wait(settled)
            check('one native key message executes exactly one frame',abs((before-actual())*fps-1)<.15)
            for _ in range(6):user.PostMessageW(hwnd,0x100,0x25,1|(1<<30));pump(.08)
            user.PostMessageW(hwnd,0x101,0x25,1|(1<<30)|(1<<31));wait(settled);pump(.15)
            check('held native Left advances multiple real frames',(before-actual())*fps>=3)
            sample('04-native-held-left')
            # The normal editable timecode owns arrow keys, including repeat.
            field=page.timecode_input;field.setFocus();field.setCursorPosition(len(field.text()))
            before=actual();cursor=field.cursorPosition();QTest.keyClick(field,Qt.Key_Left);pump(.15)
            check('text editor Left moves cursor without stepping',field.cursorPosition()<cursor and abs(actual()-before)<1e-7)
            page.video.setFocus();pump(.03)
            QApplication.sendEvent(page.video,QKeyEvent(QEvent.KeyPress,Qt.Key_Right,Qt.NoModifier,'',True,1))
            field.setFocus();pump(.15);wait(settled)
            focused=actual()
            for _ in range(5):
                QApplication.sendEvent(page.video,QKeyEvent(QEvent.KeyPress,Qt.Key_Right,Qt.NoModifier,'',True,1));pump(.04)
            check('editor focus stops further repeated frame commands',abs(actual()-focused)<1e-7)
            page.video.setFocus();pump(.05)
            page.follow_playhead_toggle.setChecked(False);page.timeline.set_visible_window(0,1000);page.timeline._manual_view_hold=True
            viewport=page.timeline.visible_start_ms;QTest.keyClick(page.video,Qt.Key_Right);wait(settled);pump(.12)
            check('manual viewport with follow off is preserved',page.timeline.visible_start_ms==viewport)
            page.follow_playhead_toggle.setChecked(True);page.timeline._manual_view_hold=False
            QTest.keyClick(page.timeline,Qt.Key_Right);wait(settled);pump(.12)
            check('timeline focus steps and follow on reveals playhead',page.timeline.visible_start_ms>viewport)
            sample('05-timeline-focus-follow')
            dialog=QDialog(window);edit=QLineEdit('modal',dialog);dialog.setModal(True);dialog.show();edit.setFocus();pump(.1)
            before=actual();QTest.keyClick(edit,Qt.Key_Left);pump(.15)
            check('modal editor owns arrow keys',abs(actual()-before)<1e-7)
            dialog.close();QApplication.setActiveWindow(window);page.video.setFocus();pump(.05)
            QTest.keyClick(page.video,Qt.Key_Space)
            check('normal playback starts before frame-step pause',wait(lambda:not page.video._paused,5))
            pump(.35)
            QTest.keyClick(page.video,Qt.Key_Left);wait(lambda:page.video._paused and settled(),3);pump(.1)
            check('stepping while playing pauses transport',page.video._paused)
            sample('06-step-during-playback')
            page._seek(0);wait(lambda:seek_settled(0));QTest.keyClick(page.video,Qt.Key_Left);pump(1.1)
            check('first frame remains bounded',actual()*1000>=trim-2)
            from ..timeline.studio_edit_sequence import timeline_duration_ms
            tail=max(0,timeline_duration_ms(page.project)-120)/1000
            page._seek(tail);wait(lambda:seek_settled(tail))
            for _ in range(5):QTest.keyClick(page.video,Qt.Key_Right);pump(.12)
            pump(1.1);check('tail leaves no accumulated requests',settled())
            _capture(window,output/'whole-window.png')
            result['passed']=all(x['passed'] for x in result['checks']);save()
        except Exception as exc:
            result['error']=str(exc);result['traceback']=traceback.format_exc();save()
        finally:
            page.video.set_paused(True)
            window.close();QTimer.singleShot(500,QApplication.instance().quit)
    QTimer.singleShot(500,run)
