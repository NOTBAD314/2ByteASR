"""Real normal-entry UI actions; all modified projects belong to the audit."""
import json, os, sys, time, traceback
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMenu
    from .blank_project_audit import _capture
    from ..design.theme_manager import apply_theme
    from ..projects.studio_project import load_project
    from ..timeline.studio_edit_sequence import sequence_of
    from ..subtitle_rules.review_suggestions import ReviewSuggestion, SuggestionOption
    from ..studio import caption_editor as captions
    if window.built_page('studio') is None:
        QTimer.singleShot(100, lambda: start(window, output));return
    page = window.studio_page
    spec = json.loads((output/'input.json').read_text('utf8'))
    from ..diagnostics.build_identity import load_build_identity
    result = dict(passed=False, checks=[], screenshots=[], home=[], pid=os.getpid(),executable=sys.executable,
                  identity=load_build_identity().to_dict(),
                  dpr=window.devicePixelRatioF(), media_kind=spec['media_kind'])

    def receipt():
        (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    def check(name, value, detail=None):
        result['checks'].append(dict(name=name, passed=bool(value), detail=detail));receipt()
        if not value: raise AssertionError(name)
    def wait(predicate, seconds=25):
        end = time.monotonic() + seconds
        while not predicate() and time.monotonic() < end: QTest.qWait(20)
        if not predicate(): raise AssertionError('wait timeout')
    def shot(name, floating=False):
        QTest.qWait(160)
        _capture(window, output/(name+'.png'))
        page.timeline.grab().save(str(output/(name+'-timeline.png')))
        if floating:
            _capture(page.subtitle_edit_dock, output/(name+'-float.png'))
        if spec['visible']:
            # Actual desktop pixels, including the owned tool and native mpv.
            from PIL import ImageGrab
            import ctypes
            from ctypes import wintypes as W
            rect = W.RECT();ctypes.windll.user32.GetWindowRect(W.HWND(int(window.winId())), ctypes.byref(rect))
            ImageGrab.grab(bbox=(rect.left,rect.top,rect.right,rect.bottom), all_screens=True).save(output/(name+'-screen.png'))
        result['screenshots'].append(name);receipt()
    def geometry():
        return {name:[w.x(),w.y(),w.width(),w.height()] for name,w in
                [('video',page.video_overlay_host),('timeline',page.timeline),
                 ('left',page.cue_table),('right',page.context_panel)]}
    def seek(at):
        page._seek(at/1000);QTest.qWait(180)
        wait(lambda: abs(page.timeline.playhead_ms-at)<150)
    def opened(at=300):
        page.video.set_paused(True);seek(at)
        page.timeline.setFocus();QTest.keyClick(page.timeline,Qt.Key.Key_E)
        wait(lambda:page.subtitle_edit_dock.isVisible())
        return page.subtitle_edit_input
    def outside_timeline(at):
        t=page.timeline
        pos=QPoint(round(t._time_to_x(at)),round(t.RULER_HEIGHT/2))
        QTest.mouseClick(t,Qt.LeftButton,Qt.NoModifier,pos)
        QTest.qWait(100)

    def execute():
        try:
            wait(lambda:page.project is not None and page._readiness.ready,100)
            apply_theme(spec['theme'])
            wait(lambda:page.timeline.waveform_state in ('READY','ERROR'),60)
            check('waveform decoded from media',page.timeline.waveform_state=='READY')
            p=page.project;window.showNormal();window.resize(1680,1000);window.show();window.raise_();window.activateWindow()
            page.video.set_paused(True)
            # The real home and its normal global zoom controller, no HTML.
            window._switch_page(0);QTest.qWait(200)
            for percent in (80,100,120):
                window._ui_zoom.request(percent);QTest.qWait(650)
                for maximized in (False,True):
                    if maximized:window.showMaximized()
                    else:window.showNormal();window.resize(1680,1000)
                    QTest.qWait(500)
                    card=window.studio_entry_card;recent=window.studio_recent_list;footer=window.studio_entry_open
                    y=footer.mapTo(card,QPoint()).y();ly=recent.mapTo(card,QPoint()).y()
                    data=dict(zoom=percent,maximized=maximized,card=[card.width(),card.height()],
                              rows=len(recent.entries),row_height=recent.row_height(),footer_y=y,list_y=ly)
                    result['home'].append(data)
                    check(f'home footer stays inside original pinned card {percent}/{maximized}',
                          card.isAncestorOf(footer) and card.parentWidget() is window.settings_scroll.viewport()
                          and footer.mapTo(window,QPoint()).y()+footer.height()<window.bottom_bar.mapTo(window,QPoint()).y(),data)
                    check(f'home full rows {percent}/{maximized}',recent.height()==len(recent.entries)*recent.row_height())
                    paths=[e['path'] for e in recent.entries]
                    check(f'home no repeated hero {percent}/{maximized}',window.studio_recent_hero.entry.get('path') not in paths and len(paths)==len(set(paths)))
                    counts=[]
                    for _ in range(5):QTest.qWait(40);counts.append(len(recent.entries))
                    check(f'home row count settles {percent}/{maximized}',len(set(counts))==1,counts)
                    shot(f'home-{percent}-'+('max' if maximized else 'normal'))
            # Same width; only vertical space changes, then recovers.
            window.showNormal();window.resize(1680,760);QTest.qWait(400);small=len(window.studio_recent_list.entries);sh=window.studio_entry_card.height()
            window.resize(1680,1100);QTest.qWait(400);large=len(window.studio_recent_list.entries);lh=window.studio_entry_card.height()
            check('recent capacity follows actual card height',large>=small and (large>small or lh-sh<window.studio_recent_list.row_height()),dict(small=small,large=large,small_height=sh,large_height=lh))
            window._ui_zoom.request(100);QTest.qWait(500)
            window.open_studio_project(str(page.project_path));QTest.qWait(600)
            width,height=(int(x) for x in os.environ.get('TWOBYTEASR_STARTUP_SIZE','1680x1000').split('x'))
            window.resize(width,height);QTest.qWait(150)
            page.timeline.setMinimumHeight(320)
            page.timeline.set_track_heights({'subtitle':68,'video':68,'audio':74})
            page.timeline.set_visible_window(0,14000)
            seek(300);before=geometry();editor=opened()
            check('E keeps timeline input context',not page._editing_has_focus() and not page._caption_edit_locked)
            check('E leaves all workspace geometry stable',geometry()==before,dict(before=before,after=geometry()))
            dock=page.subtitle_edit_dock
            track_top=page.timeline.mapToGlobal(QPoint(0,page.timeline.RULER_HEIGHT)).y()
            check('float sits between video captions and timeline captions',
                  abs(dock.y()+dock.height()-(track_top-8))<=1 and
                  dock.y()+dock.height()//2>page.video_overlay_host.mapToGlobal(QPoint(0,page.video_overlay_host.height()//2)).y(),
                  dict(float=[dock.x(),dock.y(),dock.width(),dock.height()],first_subtitle_y=track_top))
            handle=int(page.video._embed_hwnd)
            shot('editor-follow',True)
            page.video.controller.screenshot_to_file(str(output/'mpv-real-frame.png'),mode='window')
            wait(lambda:(output/'mpv-real-frame.png').exists(),8)
            from PIL import Image,ImageStat
            check('actual mpv pixels are not black',max(ImageStat.Stat(Image.open(output/'mpv-real-frame.png').convert('RGB')).var)>5)
            QTest.keyClick(page.timeline,Qt.Key.Key_Space)
            wait(lambda:not page.video._paused,8)
            wait(lambda:page._caption_draft is not None and page._caption_draft.target.cue_id=='b',8)
            check('space plays and visible float follows B',page.subtitle_edit_dock.isVisible() and editor.toPlainText()=='第二条继续跟随')
            QTest.mouseClick(editor.viewport(),Qt.LeftButton)
            check('click alone locks B before any text mutation',page._caption_edit_locked)
            editor.setPlainText('第二条 · 播放中锁定修改')
            wait(lambda:page.timeline.playhead_ms>4700,8)
            check('playback crosses cues without overwriting B',page._caption_draft.target.cue_id=='b' and editor.toPlainText()=='第二条 · 播放中锁定修改')
            QTest.keyClick(editor,Qt.Key.Key_R,Qt.ShiftModifier)
            check('confirm saves B and closes the edit session',page._cue_lookup['b'].text=='第二条 · 播放中锁定修改'
                  and page._caption_draft is None and not page.subtitle_edit_dock.isVisible())
            QTest.keyClick(page.timeline,Qt.Key.Key_Space);wait(lambda:page.video._paused)
            check('space pauses and confirmed float stays closed',not page.subtitle_edit_dock.isVisible())
            page._end_caption_editor(keep_open=False)
            editor=opened(1900)
            check('E in a real playback gap shows no caption',page._caption_draft is None and '无字幕' in page.subtitle_edit_title.text())
            page._end_caption_editor(keep_open=False)
            editor=opened();editor.setPlainText('字幕列表首点')
            index=page.cue_model.index(1,3);page.cue_table.scrollTo(index);QTest.qWait(40)
            QTest.mouseClick(page.cue_table.viewport(),Qt.LeftButton,pos=page.cue_table.visualRect(index).center())
            QTest.qWait(150)
            check('subtitle row first click saves closes and selects B',page._cue_lookup['a'].text=='字幕列表首点' and not page.subtitle_edit_dock.isVisible() and page.selected_cue_id=='b')
            for i in range(3):
                editor=opened();editor.setPlainText('第一条保存'+str(i));outside_timeline(8500)
                check('outside ruler first click saves and seeks '+str(i),not page.subtitle_edit_dock.isVisible() and page._cue_lookup['a'].text=='第一条保存'+str(i) and abs(page.timeline.playhead_ms-8500)<150)
                check('repeated E/external close keeps geometry '+str(i),geometry()==before)
            editor=opened();editor.setPlainText('播放按钮首点')
            QTest.mouseClick(page.play_button,Qt.LeftButton);wait(lambda:not page.video._paused)
            check('play button first click saves closes and plays',not page.subtitle_edit_dock.isVisible() and page._cue_lookup['a'].text=='播放按钮首点')
            page.video.set_paused(True)
            editor=opened();QApplication.setActiveWindow(page.subtitle_edit_dock);editor.setFocus()
            QApplication.sendEvent(editor,QInputMethodEvent('ni',[]))
            page._follow_caption_editor(8500)
            check('Qt composition retains A binding',page._caption_draft.target.cue_id=='a')
            menu=QMenu(editor);action=menu.addAction('复制');menu.popup(editor.mapToGlobal(QPoint(8,8)));QTest.qWait(60)
            QTest.mouseClick(menu,Qt.LeftButton,pos=menu.actionGeometry(action).center())
            check('owned menu does not close draft',page._caption_draft is not None)
            menu.close();event=QInputMethodEvent();event.setCommitString('你');QApplication.sendEvent(editor,event)
            editor.setPlainText('失败重试保持A')
            cls=type(page.cue_controller);writer=cls.set_text
            try:
                cls.set_text=lambda *a,**k:(_ for _ in ()).throw(ValueError('controlled validation failure'))
                outside_timeline(8500)
                check('failed outside commit retains text and A target',page._caption_draft.target.cue_id=='a' and editor.toPlainText()=='失败重试保持A' and page.subtitle_edit_dock.isVisible())
                shot('editor-failure',True)
            finally:cls.set_text=writer
            QTest.mouseClick(page.caption_confirm_button,Qt.LeftButton)
            check('retry saves A without touching D',page._cue_lookup['a'].text=='失败重试保持A' and page._cue_lookup['d'].text=='确认后跟随此刻')
            page._end_caption_editor(keep_open=False)
            editor=opened();before_undo=page.undo_stack.count()
            old_view,old_rules=captions.current_issue_view,captions.review_suggestions
            old_review=page._review_suggestions_for
            try:
                from types import SimpleNamespace
                captions.current_issue_view=lambda *a:SimpleNamespace(for_cue=lambda *a,**k:())
                captions.review_suggestions=lambda *a,**k:[]
                page._review_suggestions_for=lambda *a:()
                editor.setPlainText('她还在营第')
                draft=page._caption_draft
                draft.suggestion_text=editor.toPlainText()
                draft.suggestions=(ReviewSuggestion(3,5,'营第',(SuggestionOption('营地'),),'model'),)
                page._refresh_editor_suggestions()
                QTest.mouseClick(page.caption_suggestion_text.candidate_button(0,0),Qt.LeftButton)
                check('suggestion button edits the bound draft without closing',page._caption_draft.target.cue_id=='a' and editor.toPlainText()=='她还在营地')
                QTest.mouseClick(editor.viewport(),Qt.LeftButton);editor.moveCursor(editor.textCursor().MoveOperation.Start)
                QTest.keyClick(editor,Qt.Key.Key_P,Qt.ShiftModifier)
                check('Shift P still targets locked caption',editor.toPlainText()=='他还在营地')
                shot('editor-suggestions',True)
            finally:
                captions.current_issue_view,captions.review_suggestions=old_view,old_rules
                page._review_suggestions_for=old_review
            page._cancel_canvas_inline_edit()
            # Exact media cuts and undo via actual timeline pointer dispatch.
            t=page.timeline;row=t._video_track_rect('V1');t.set_tool_mode('razor')
            pos=QPoint(round(t._time_to_x(5950)),round(row.center().y()))
            QTest.mouseMove(t.window().windowHandle(),t.mapTo(t.window(),pos));QTest.qWait(120)
            cut=t._media_cut;check('razor has a resolved media cut',cut is not None)
            split=cut.split_ms;shot('razor-cut')
            QTest.mouseClick(t,Qt.LeftButton,Qt.NoModifier,pos);QTest.qWait(200)
            segments=sequence_of(p).segments
            check('razor commits displayed cut for linked media',len(segments)==2 and segments[0].timeline_out_ms==split and segments[1].timeline_in_ms==split)
            page.undo_stack.undo();QTest.qWait(100)
            check('one undo restores single media segment',len(sequence_of(p).segments)==1)
            # Retain the split for a rounded adjacent-boundary visual.
            page.undo_stack.redo();QTest.qWait(100);t.set_tool_mode('selection')
            t.set_snap_enabled(False);t.set_tool_mode('razor')
            tiny_pos=QPoint(round(t._time_to_x(split+120)),round(row.center().y()))
            QTest.mouseMove(t.window().windowHandle(),t.mapTo(t.window(),tiny_pos));QTest.qWait(100)
            QTest.mouseClick(t,Qt.LeftButton,Qt.NoModifier,tiny_pos);QTest.qWait(120)
            check('very short real media segment remains time exact',len(sequence_of(p).segments)==3 and 0<sequence_of(p).segments[1].timeline_out_ms-sequence_of(p).segments[1].timeline_in_ms<300)
            t.set_tool_mode('selection')
            for theme in ('warm','grape'):
                apply_theme(theme);QTest.qWait(180)
                for start,duration,label in ((0,14000,'full'),(4000,4000,'scrolled'),(5800,400,'zoomed')):
                    t.set_visible_window(start,duration);QTest.qWait(180);shot('clips-'+theme+'-'+label)
            check('native player surface was never rebuilt',int(page.video._embed_hwnd)==handle)
            apply_theme(spec['theme']);t.set_visible_window(0,14000);editor=opened()
            shot('editor-final',True)
            editor.setPlainText('CtrlS实际保存A');seek(8500)
            QTest.keyClick(editor,Qt.Key.Key_S,Qt.ControlModifier)
            wait(lambda:page.undo_stack.isClean(),35)
            check('Ctrl S from visible text editor really writes disk and keeps follow',
                  next(c.text for c in load_project(page.project_path).cues if c.id=='a')=='CtrlS实际保存A'
                  and page.subtitle_edit_dock.isVisible() and not page._caption_edit_locked)
            page._end_caption_editor(keep_open=False)
            editor=opened();editor.setPlainText('磁盘失败后CtrlS重试A');seek(8500)
            from ..projects import studio_project as persistence
            replace=persistence.os.replace;save=page.save;errors=[]
            def blocked(src,dst):
                if str(dst)==str(page.project_path):raise PermissionError('controlled atomic disk failure')
                return replace(src,dst)
            try:
                persistence.os.replace=blocked
                page.save=lambda:page.project_controller.save(message_box_fn=lambda *a:errors.append(str(a[-1])))
                QTest.keyClick(editor,Qt.Key.Key_S,Qt.ControlModifier)
                check('disk failure keeps dirty original target and text',bool(errors) and not page.undo_stack.isClean()
                      and page._caption_draft.target.cue_id=='a' and editor.toPlainText()=='磁盘失败后CtrlS重试A')
                shot('editor-disk-failure',True)
            finally:persistence.os.replace=replace;page.save=save
            QTest.keyClick(editor,Qt.Key.Key_S,Qt.ControlModifier)
            wait(lambda:page.undo_stack.isClean(),35)
            check('Ctrl S retries retained disk failure without losing text',
                  next(c.text for c in load_project(page.project_path).cues if c.id=='a')=='磁盘失败后CtrlS重试A')
            page._end_caption_editor(keep_open=False)
            QTest.mouseClick(page.save_button,Qt.LeftButton);wait(lambda:page.undo_stack.isClean(),35)
            disk=load_project(page.project_path)
            check('normal save persists bound A and B edits',next(c.text for c in disk.cues if c.id=='a')=='磁盘失败后CtrlS重试A' and next(c.text for c in disk.cues if c.id=='b')=='第二条 · 播放中锁定修改')
            editor=opened();undo=page.undo_stack.index();stamp=Path(page.project_path).stat().st_mtime_ns
            follow,bind=page._follow_caption_editor,page._bind_caption_editor
            timings=[];binds=[]
            def followed(*a,**k):
                begin=time.perf_counter()
                try:return follow(*a,**k)
                finally:timings.append((time.perf_counter()-begin)*1000)
            def bound(target):
                binds.append(target.cue_id);return bind(target)
            page._follow_caption_editor,page._bind_caption_editor=followed,bound
            try:
                QTest.keyClick(page.timeline,Qt.Key.Key_Space);wait(lambda:not page.video._paused)
                wait(lambda:page.timeline.playhead_ms>6800,12)
                QTest.keyClick(page.timeline,Qt.Key.Key_Space);wait(lambda:page.video._paused)
                ordered=sorted(timings)
                result['follow_metrics']=dict(calls=len(timings),bindings=binds,
                    p95_ms=ordered[min(len(ordered)-1,int(len(ordered)*.95))],max_ms=max(ordered))
                check('continuous follow only binds on changed captions',len(timings)>30 and len(binds)<=4,result['follow_metrics'])
                check('continuous follow reuses controls without undo or project writes',
                      editor is page.subtitle_edit_input and page.undo_stack.index()==undo and Path(page.project_path).stat().st_mtime_ns==stamp)
            finally:
                page._follow_caption_editor,page._bind_caption_editor=follow,bind
                page._end_caption_editor(keep_open=False)
            result['passed']=True
        except BaseException:
            result['error']=traceback.format_exc()
        finally:
            receipt();QApplication.instance().aboutToQuit.connect(lambda:(result.update(gui_shutdown=True),receipt()))
            page.video.set_paused(True);page.undo_stack.setClean()
            window.result_exit_code=0 if result['passed'] else 1;window.close()
    QTimer.singleShot(200,execute)
