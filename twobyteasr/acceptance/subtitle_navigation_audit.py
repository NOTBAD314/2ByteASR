"""Real Studio entry, video plane, navigation ownership and gesture audit."""
from __future__ import annotations
import hashlib
import json
import time
import traceback
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QTimer
    QTimer.singleShot(400, lambda: run(window, output))


def run(window, output):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QImage, QInputMethodEvent, QTextCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..timeline.studio_commands import SetCueFieldsCommand
    from ..timeline.selection_scope import SelectionScope
    from ..projects.studio_project import load_project, save_project, StudioCue
    from ..studio import shortcut_registry
    app=QApplication.instance();checks=[];requests=[];samples=[];timings=[];error=None
    def persist():
        (output/'result.json').write_text(json.dumps(dict(passed=error is None and bool(checks) and all(c['passed'] for c in checks),
            checks=checks,requests=requests,samples=samples,timings=timings,error=error),ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name, passed, detail=None):
        checks.append(dict(name=name,passed=bool(passed),detail=detail));persist()
        if not passed:raise AssertionError(name+': '+str(detail))
    def settle(seconds=.05):
        end=time.perf_counter()+seconds
        while time.perf_counter()<end:app.processEvents();time.sleep(.003)
    def wait(predicate,timeout=20):
        until=time.perf_counter()+timeout
        while not predicate() and time.perf_counter()<until:settle(.015)
        if not predicate():raise TimeoutError(str(predicate))
    def opened(path,count=None):
        window.open_studio_project(str(path))
        wait(lambda:window.built_page('studio') is not None and window.built_page('studio').project is not None)
        page=window.studio_page
        wait(lambda:getattr(window,'_studio_loading_session',None) is None or
             not window._studio_loading_session.active and not window._studio_loading_session.view.isVisible(),35)
        wait(lambda:getattr(page.video,'_startup_state','')=='READY',35)
        if count is not None:check('normal entry cue count',len(page.project.cues)==count)
        page.video.set_paused(True);page.timeline.setFocus();app.setActiveWindow(window);settle(.2)
        return page
    page=None
    try:
        window.resize(1560,980)
        page=opened(output/'fixture.2byteproj')
        original_seek=page._seek
        def seek(seconds,**kwargs):
            requests.append(dict(ms=round(seconds*1000),navigation=kwargs.get('preserve_subtitle_target',False),at=time.perf_counter()))
            return original_seek(seconds,**kwargs)
        page._seek=seek
        def ready():
            return (not page.video._playback_clock.exact_seek_pending
                    and getattr(getattr(page,'_caption_seek_preparation',None),'pending',None) is None)
        def at(value):
            wait(ready,25)
            wait(lambda:abs(page.timeline.playhead_ms-value)<=40,8);settle(.08)
        def center_error():
            t=page.timeline
            return abs(t._time_to_x(t.playhead_ms)-(t.TRACK_HEADER_WIDTH+t._content_right())/2)
        def picture(label):
            window.grab().save(str(output/(label+'-window.png')))
            path=output/(label+'-video.png');page.video.controller.screenshot_to_file(path,mode='window')
            wait(lambda:path.is_file())
            check(label+' native video image',not QImage(str(path)).isNull())
            scene=getattr(page,'_caption_scene',None)
            if scene is not None and scene.published is not None:
                scene.published.image.save(str(output/(label+'-caption.png')))
                (output/(label+'-scene.json')).write_text(json.dumps(scene.trace(),ensure_ascii=False,indent=2,default=str),'utf8')
            return hashlib.sha256(path.read_bytes()).hexdigest()
        def click(cue_id,layer='original',repeat=False):
            cue=page.timeline._timeline_cue_by_id[cue_id];t=page.timeline
            # The user can browse to the block before clicking it again.
            t.hold_manual_view();t.set_visible_window(max(0,cue.start_ms-2000),10000)
            rect=t._track_layout()[1] if layer=='translation' else t._track_layout()[0][cue.speaker_id]
            if rect is None:raise AssertionError('missing '+layer+' lane')
            pos=QPoint(round(t._time_to_x(cue.start_ms+min(500,(cue.end_ms-cue.start_ms)//2))),round(rect.center().y()))
            before=t.playhead_ms
            QTest.mousePress(t,Qt.LeftButton,Qt.NoModifier,pos)
            check('press establishes target without moving viewport',t.playhead_ms==before)
            QTest.mouseRelease(t,Qt.LeftButton,Qt.NoModifier,pos)
            at(cue.start_ms)
            check(('repeat ' if repeat else '')+layer+' click selects and centers',
                page.selected_cue_id==cue_id and t.active_subtitle_layer==layer and center_error()<=2,
                dict(selected=page.selected_cue_id,layer=t.active_subtitle_layer,error=center_error()))
            return pos
        def key(widget=None):
            target=widget or page.timeline;target.setFocus(Qt.ShortcutFocusReason)
            QTest.keyClick(target,Qt.Key_J,Qt.AltModifier)
        page._seek(1000/1000);at(1000);before_picture=picture('00-paused-before')
        page.selection_center_toggle.setChecked(True)
        check('visible named switch and exact tooltip',page.selection_center_toggle.isVisible()
              and page.selection_center_toggle.text()=='选中定位并居中'
              and page.selection_center_toggle.toolTip()=='选中字幕时跳到字幕起点，并让播放头保持在时间线中央。')
        check('default binding and interface hint',page._shortcut_values['jump_cue_boundary']=='Alt+J'
              and 'Alt+J' in page.cue_boundary_button.toolTip()
              and not [c for c in shortcut_registry.blocking_conflicts(shortcut_registry.current_values()) if 'jump_cue_boundary' in (c.first,c.second)])
        clean=(page.undo_stack.count(),page._autosave_generation)
        click('a');check('paused navigation stays paused',page.video._paused)
        after_picture=picture('01-paused-a');check('paused native video changed',before_picture!=after_picture)
        check('paused timeline and time display',abs(page.timeline.playhead_ms-10000)<=40 and '10.' in page.timecode_input.text(),page.timecode_input.text())
        pos=click('a',repeat=True)
        QTest.mouseDClick(page.timeline,Qt.LeftButton,Qt.NoModifier,pos)
        check('original double-click survives first-click scroll',page.timeline._inline_target==('a',False))
        page.timeline._cancel_inline_edit()
        count=len(requests);key();at(13000)
        check('one physical combination produces one exact endpoint request',len(requests)==count+1 and requests[-1]['ms']==13000)
        check('adjacent and overlapping target stays a',page.selected_cue_id=='a' and page.selection_model.scope.active_id=='a')
        rendered=page._caption_scene.trace()['rendered_cue_ids']
        check('half-open endpoint removes a and keeps adjacent b',not any(str(x).split('::')[0]=='a' for x in rendered)
              and any(str(x).split('::')[0]=='b' for x in rendered),rendered)
        picture('02-exact-end')
        key();at(10000);check('endpoint returns to same start',requests[-1]['ms']==10000 and page.selected_cue_id=='a')
        for _ in range(14):key()
        at(10000);check('fast key sequence alternates true endpoints',
            [r['ms'] for r in requests[-14:]]==[13000,10000]*7)
        held=[]
        for _ in range(15):settle(.02);held.append(page.timeline.playhead_ms)
        check('no old asynchronous frame rolls back final target',max(abs(v-10000) for v in held)<=40,held)
        click('a')
        old=page.selected_cue_id;page.timeline.setFocus();QTest.keyClick(page.timeline,Qt.Key_Down)
        target=page._cue_lookup.get(page.selected_cue_id)
        wait(ready);check('keyboard switches selection and seeks its start',target is not None and target.id!=old and abs(page.timeline.playhead_ms-target.start_ms)<=40)
        pos=click('a','translation')
        QTest.mouseDClick(page.timeline,Qt.LeftButton,Qt.NoModifier,pos)
        check('translation double-click survives first-click scroll',page.timeline._inline_target==('a',True))
        page.timeline._cancel_inline_edit()
        key();at(13000)
        check('translation endpoint keeps editing field',page.timeline.active_subtitle_layer=='translation' and page.selected_cue_id=='a')
        key();at(10000)
        # MainWindow's E path must retain the explicitly picked original/translation field.
        page.timeline.setFocus();QTest.keyClick(page.timeline,Qt.Key_E);settle(.15)
        check('E opens translation bound identity',page._caption_draft is not None
              and (page._caption_draft.target.cue_id,page._caption_draft.target.layer)==('a','translation'))
        editor=page.subtitle_edit_input;text=editor.toPlainText();cursor=editor.textCursor().position()
        app.setActiveWindow(page.subtitle_edit_dock);editor.setFocus();key(editor);at(13000)
        check('E window navigation retains identity and unmodified text',
              page._caption_draft is not None and (page._caption_draft.target.cue_id,page._caption_draft.target.layer)==('a','translation')
              and editor.toPlainText()==text and editor.textCursor().position()==cursor)
        key(editor);at(10000)
        input_event=QInputMethodEvent('拼',[]);app.sendEvent(editor,input_event);count=len(requests)
        key(editor);settle(.05);check('IME composition keeps combination',len(requests)==count)
        app.sendEvent(editor,QInputMethodEvent('',[]));settle(.05)
        app.setActiveWindow(page.subtitle_edit_dock);editor.setFocus();settle(.05)
        QTest.keyClick(editor,Qt.Key_A,Qt.ControlModifier);QTest.keyClick(editor,Qt.Key_C,Qt.ControlModifier)
        check('editor select and copy retained',editor.textCursor().hasSelection() and app.clipboard().text()==text,
              dict(selected=editor.textCursor().selectedText(),clipboard=app.clipboard().text(),text=editor.toPlainText(),
                   draft=repr(page._caption_draft.target if page._caption_draft else None),focus=repr(app.focusWidget()),
                   preedit=getattr(editor,'_preediting',None),composing=getattr(page,'_studio_ime_composing',None)))
        QTest.keyClick(editor,Qt.Key_Escape);settle(.1);app.setActiveWindow(window)
        click('a','original');QTest.keyClick(page.timeline,Qt.Key_E);settle(.1)
        check('E opens explicitly selected original',page._caption_draft is not None and page._caption_draft.target.layer=='original')
        QTest.keyClick(page.subtitle_edit_input,Qt.Key_Escape);settle(.1);app.setActiveWindow(window)
        check('navigation does not dirty or save project',(page.undo_stack.count(),page._autosave_generation)==clean,
              dict(before=clean,after=(page.undo_stack.count(),page._autosave_generation)))
        # Real pointer move and trim in the same Studio, followed by updated bounds.
        t=page.timeline;t.snap_enabled=False;t.hold_manual_view();t.set_visible_window(8000,10000)
        y=round(t._track_layout()[0]['S0'].center().y());pos=QPoint(round(t._time_to_x(11000)),y)
        count=len(requests);start=t.visible_start_ms
        QTest.mousePress(t,Qt.LeftButton,Qt.NoModifier,pos);QTest.mouseMove(t,pos+QPoint(30,0));settle(.04)
        check('drag owns viewport',t.visible_start_ms==start)
        QTest.mouseRelease(t,Qt.LeftButton,Qt.NoModifier,pos+QPoint(30,0));settle(.08)
        check('drag commits edit without navigation',len(requests)==count and page._cue_lookup['a'].start_ms!=10000)
        page.undo_stack.undo();settle(.1)
        t.hold_manual_view();t.set_visible_window(8000,10000)
        edge=QPoint(round(t._time_to_x(page._cue_lookup['a'].end_ms))-2,y)
        count=len(requests);QTest.mousePress(t,Qt.LeftButton,Qt.NoModifier,edge);QTest.mouseMove(t,edge-QPoint(25,0));settle(.04)
        QTest.mouseRelease(t,Qt.LeftButton,Qt.NoModifier,edge-QPoint(25,0));settle(.08)
        changed_end=page._cue_lookup['a'].end_ms
        check('trim preserves pointer and does not navigate',changed_end<13000 and len(requests)==count)
        page._navigate_selected_subtitle('a');at(page._cue_lookup['a'].start_ms);key();at(changed_end)
        check('boundary action reads trimmed endpoint',requests[-1]['ms']==changed_end)
        page.undo_stack.undo();settle(.1)
        # Multiselect's explicit primary is independent of the visible caption.
        page.cue_controller.apply_selection_scope(SelectionScope.explicit(('a','x'),'a'))
        page._navigate_selected_subtitle('a');at(10000);key();at(13000)
        check('multiselect primary and members retained',page.selection_model.scope.active_id=='a'
              and page.selection_model.scope.explicit_ids==frozenset(('a','x')))
        page.cue_controller.cancel_selection();count=len(requests);key();settle(.1)
        check('no target leaves position and hints',len(requests)==count and '选中' in page.save_state.text(),page.save_state.text())
        click('a');page.video.set_paused(False);wait(lambda:not page.video._paused,8)
        until=time.perf_counter()+1.5
        while time.perf_counter()<until:
            settle(.016);samples.append(dict(at=time.perf_counter(),playhead=page.timeline.playhead_ms,
                left=page.timeline.visible_start_ms,center_error=center_error(),clock=page.video.visual_position()*1000))
        check('playback follows every frame near center',len({s['left'] for s in samples})>=25
              and max(s['center_error'] for s in samples)<=2,
              dict(samples=len(samples),different_left=len({s['left'] for s in samples}),max_error=max(s['center_error'] for s in samples)))
        check('playhead follows same video clock',max(abs(s['playhead']-s['clock']) for s in samples)<100)
        t._horizontal_scrolled(4000);held=t.visible_start_ms;settle(.25)
        check('manual browse stays while playing',t.visible_start_ms==held,
              dict(expected=held,actual=t.visible_start_ms,held=t._manual_view_hold,
                   intended=page.video.playback_intended,last_intended=getattr(page,'_navigation_playback_intended',None),
                   pending=getattr(page,'_navigation_resume_follow_pending',None)))
        page.video.set_paused(True);settle(.1);page.video.set_paused(False);wait(lambda:not page.video._paused,8);settle(.12)
        check('resume restores centered follow',center_error()<=2)
        click('a');check('selection seek while playing continues playback',page.video.playback_intended)
        page.video.set_paused(True);wait(lambda:page.video._paused)
        page._seek(0);at(0);check('project head can center with blank lead',center_error()<=2 and t.visible_start_ms<0)
        page._seek(24);at(24000);check('project tail can center with blank tail',center_error()<=2)
        picture('03-tail-padding')
        page.selection_center_toggle.setChecked(False);t._horizontal_scrolled(4000);hold=t.visible_start_ms;settle(.2)
        check('switch off restores free browse',not t.center_playhead_mode and t.visible_start_ms==hold)
        page._timeline_cue_clicked('a')
        page._seek(14.0);at(14000)
        check('disabled centering keeps explicit target across ordinary seek',page.selected_cue_id=='a')
        key();at(10000);key();at(13000)
        check('boundary shortcut works independently with centering disabled',
              page.selected_cue_id=='a' and [r['ms'] for r in requests[-2:]]==[10000,13000])
        page.selection_center_toggle.setChecked(True)
        check('preference saved globally',page._studio_preferences().get('selection_centered') is True)
        # Large project navigation: 7000 additional captions on real six-hour synthetic video.
        longpath=output/'long.2byteproj'
        if longpath.is_file():
            page.undo_stack.setClean();page=opened(longpath,7005)
            original_seek=type(page)._seek.__get__(page)
            page._seek=seek
            check('preference persists across project open',page.selection_center_toggle.isChecked())
            before=(page.undo_stack.count(),page._autosave_generation)
            for index in range(0,7000,350):
                cue_id=f'long-{index}';began=time.perf_counter()
                page.select_cue(cue_id,hydrate=False);page._navigate_selected_subtitle(cue_id)
                timings.append(dict(action='large selection',ms=(time.perf_counter()-began)*1000,cue=cue_id))
            final=page.timeline._timeline_cue_by_id['long-6650'].start_ms
            wait(ready,35);wait(lambda:abs(page.timeline.playhead_ms-final)<=500,10)
            check('large rapid selections finish at latest stable ID',page.selected_cue_id=='long-6650' and center_error()<=2)
            for _ in range(10):key()
            wait(ready,35);check('large repeated boundary latest wins',requests[-1]['ms']==final)
            check('large navigation does not save or edit',(page.undo_stack.count(),page._autosave_generation)==before)
            check('large handler remains timely',max(v['ms'] for v in timings)<250,timings)
            picture('04-long-latest')
        window.resize(1100,780);settle(.2);window.grab().save(str(output/'05-narrow.png'))
        check('navigation switch remains available at narrow size',page.selection_center_toggle.isVisible())
        page.undo_stack.setClean()
    except Exception:
        error=traceback.format_exc()
        (output/'error.txt').write_text(error,'utf8')
        window.grab().save(str(output/'failure.png'))
    finally:
        persist()
        if page is not None and page.project:
            page._cancel_bound_caption_editor(trigger='acceptance_cleanup')
            page.undo_stack.setClean()
        window.close();app.quit()
