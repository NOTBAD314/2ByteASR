"""Explicit owned-window audit; provider proposals here are labelled synthetic."""
import json,time,traceback,os

def start(window,out):
    from PySide6.QtCore import QTimer
    QTimer.singleShot(500,lambda:run(window,out))

def run(window,out):
    from PySide6.QtCore import QPoint,Qt
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from ..recognition.speaker_roles import GROUP_KEY
    from ..caption_style.subtitle_visibility import layer_visible
    from ..studio.studio_timeline import WaveformTimeline
    from ..projects.studio_project import SubtitleProject,StudioCue,StudioMedia
    app=QApplication.instance();checks=[];timings=[];error=None;page=None;review=None
    from ..diagnostics.build_identity import load_build_identity
    identity=load_build_identity().to_dict()
    playback_probe={}
    def persist():
        (out/'result.json').write_text(json.dumps(dict(passed=bool(checks) and not error and all(c['passed'] for c in checks),
            checks=checks,timings=timings,error=error,identity=identity,pid=os.getpid(),
            dpr=window.devicePixelRatioF(),playback_locate=playback_probe),ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,value,detail=None):
        checks.append(dict(name=name,passed=bool(value),detail=detail));persist()
        if not value:raise AssertionError(name+': '+str(detail))
    def pump(seconds=.05):
        until=time.perf_counter()+seconds
        while time.perf_counter()<until:app.processEvents();time.sleep(.003)
    def wait(predicate,timeout=35):
        until=time.perf_counter()+timeout
        while not predicate() and time.perf_counter()<until:pump(.02)
        if not predicate():raise TimeoutError(str(predicate))
    def opened(path):
        window.open_studio_project(str(path))
        wait(lambda:window.built_page('studio') is not None and window.studio_page.project is not None)
        page=window.studio_page
        wait(lambda:getattr(window,'_studio_loading_session',None) is None or not window._studio_loading_session.active)
        wait(lambda:page.video._startup_state=='READY');page.video.set_paused(True);pump(.15)
        return page
    def picture(name):
        from .blank_project_audit import _capture
        _capture(window,out/(name+'-window.png'))
        path=out/(name+'-native.png')
        page.video.controller.screenshot_to_file(path,mode='window')
        wait(lambda:path.is_file())
    def settled():
        return not page.video._playback_clock.exact_seek_pending and getattr(getattr(page,'_caption_seek_preparation',None),'pending',None) is None
    def locate(cue_id,left,layer='original'):
        page.timeline.set_subtitle_layer(layer);page.select_cue(cue_id)
        t=page.timeline;vertical=t.vertical_scrollbar.value();height=t._speaker_track_height()
        before=page.undo_stack.count();began=time.perf_counter();page.selection_center_toggle.click()
        timings.append(dict(action='locate',cue=cue_id,ms=(time.perf_counter()-began)*1000))
        wait(settled);target=t._timeline_cue_by_id[cue_id].start_ms
        wait(lambda:abs(t.playhead_ms-target)<=40,10)
        check('seek and 15 second content window '+cue_id,(t.visible_duration_ms,t.visible_start_ms)==(15000,left),
            dict(playhead=t.playhead_ms,target=target,window=[t.visible_start_ms,t.visible_start_ms+t.visible_duration_ms]))
        check('locate preserves vertical geometry and document '+cue_id,
            t.vertical_scrollbar.value()==vertical and t._speaker_track_height()==height and page.undo_stack.count()==before)
        check('locate remains paused '+cue_id,page.video._paused)
    try:
        from ..design.theme_manager import apply_theme
        apply_theme(os.environ.get('TWOBYTEASR_ACCEPTANCE_THEME','grape'),app);window.refresh_theme_palette()
        window.resize(1660,1000);page=opened(out/'fixture.2byteproj');t=page.timeline
        check('32 secondary speakers default to compact header',len(t._group_members)==32 and not t._group_expanded
            and t._display_rows()[0][2]==24)
        locate('head',0);picture('01-head')
        locate('middle',592500);locate('tail',t._duration_ms()-15000,'translation')
        for width in (1180,1780):
            window.resize(width,1000);pump(.15);locate('middle',592500)
            check('real drawable width maps to 15 seconds '+str(width),t._x_to_time(t._content_right())-t._x_to_time(t.TRACK_HEADER_WIDTH)==15000)
        for cue_id in ('head','tail','middle'):
            page.select_cue(cue_id);page.selection_center_toggle.click()
        wait(settled);check('rapid navigation ends on latest target',abs(t.playhead_ms-600000)<=40 and t.visible_start_ms==592500)
        t.set_visible_window(590000,7000);pump(.15)
        check('ordinary selection does not reset user zoom',t.visible_duration_ms==7000)
        page.select_cue('middle');page.video.set_paused(False)
        # A play request may still be held while the isolated audio endpoint
        # primes its first PCM. Test locating during actual playback, then
        # observe the resume acknowledgement instead of assuming 100ms.
        wait(lambda:page.video.playback_intended and not page.video._paused,10)
        play_before=dict(intended=page.video.playback_intended,paused=page.video._paused,
                         position_ms=t.playhead_ms)
        locate_began=time.perf_counter();page.selection_center_toggle.click()
        wait(settled)
        wait(lambda:page.video.playback_intended and not page.video._paused,10)
        playback_probe.update(before=play_before,after=dict(
            intended=page.video.playback_intended,paused=page.video._paused,position_ms=t.playhead_ms),
            acknowledgement_ms=(time.perf_counter()-locate_began)*1000,
            scope='Observed GUI/player acknowledgement; excludes physical output latency.')
        check('locate during playback retains playing policy and zoom',not page.video._paused and t.visible_duration_ms==15000)
        page.video.set_paused(True);pump(.15)
        page.select_cue('sub-32');page._open_caption_editor('sub-32','original');pump(.1)
        check('E edits hidden group member without expanding',not t._group_expanded and page._caption_draft.target.cue_id=='sub-32')
        page._cancel_bound_caption_editor(trigger='acceptance')
        menu=page.secondary_group_button.menu();menu.aboutToShow.emit();menu.actions()[0].trigger();pump(.1)
        check('fixed control expands group',t._group_expanded)
        t.vertical_scrollbar.setValue(t.vertical_scrollbar.maximum());pump(.1)
        check('fixed group control accessible after scrolling',page.secondary_group_button.isVisible())
        menu.aboutToShow.emit();menu.actions()[0].trigger();check('fixed control collapses without scrolling up',not t._group_expanded)
        menu.aboutToShow.emit();roles=menu.actions()[2].menu()
        action=next(a for a in roles.actions() if 'S02' in a.text() or a.text()=='S2')
        action.setChecked(False)
        check('individual role control hides its own original and translation',not layer_visible(page.project,next(c for c in page.project.cues if c.id=='sub-2'))
            and not layer_visible(page.project,next(c for c in page.project.cues if c.id=='sub-2'),'translation'))
        page._subtitle_visibility_changed(GROUP_KEY,False);pump(.2)
        main=next(c for c in page.project.cues if c.id=='head');sub=next(c for c in page.project.cues if c.id=='sub-1')
        check('group hides only secondary original and translation',layer_visible(page.project,main) and layer_visible(page.project,main,'translation')
            and not layer_visible(page.project,sub) and not layer_visible(page.project,sub,'translation'))
        from ..exports.export_timeline import write_export_ass
        hidden=write_export_ass(page.project,out/'hidden-secondary.ass',skip_empty=True,start_ms=sub.start_ms,end_ms=sub.end_ms)
        check('burnin snapshot at hidden secondary contains no software captions',not hidden.cues and not (out/'hidden-secondary.ass').exists())
        page._seek(sub.start_ms/1000);wait(settled);picture('02-hidden-secondary')
        t.set_group_expanded(True);t.set_visible_window(30000,15000);t.vertical_scrollbar.setValue(0);pump(.1)
        check('hidden originals cannot be marquee targets',not any(kind=='subtitle' and key.startswith('sub-') for kind,key,rect in t._selection_items()))
        translation=t._track_layout()[1]
        point=QPoint(round(t._time_to_x(sub.start_ms+500)),round(translation.center().y()))
        check('hidden translations cannot be hit',not t._translation_candidates_at(point))
        page._subtitle_visibility_changed(GROUP_KEY,True);pump(.1)
        check('restoring group preserves individually hidden speaker',not layer_visible(page.project,next(c for c in page.project.cues if c.id=='sub-2'))
            and not layer_visible(page.project,next(c for c in page.project.cues if c.id=='sub-2'),'translation')
            and layer_visible(page.project,sub))
        t.set_group_expanded(False);window.grab().save(str(out/'02-secondary-window.png'))
        page.undo_stack.setClean();page.project_dirty=False
        page=opened(out/'real.2byteproj');check('real 395 cue project loaded',len(page.project.cues)==395)
        page.cue_proofread_action.trigger();wait(lambda:getattr(window,'glossary_proofread_page',None) is window.pages.currentWidget())
        review=window.glossary_proofread_page;wait(lambda:not review.checks_running(),90)
        imported=review._recognition_review_receipt
        check('existing recognition results load without libraries',not review._selected_ids() and any(i.get('recognition_import') for r in review._rows for i in r['issues']))
        check('suspect 433 maps to a real final cue',any(r.get('source_segment_id')==433 for r in imported['pending_rows']))
        window.grab().save(str(out/'03-real-review-window.png'))
        calls=[]
        def stand_in(view,wanted,snapshot,settings,**kw):
            from ..glossary.studio_glossary_service import GlossaryReviewPreview
            from ..studio.subtitle_text_targets import bind_occurrence
            from ..studio.studio_text_tools import TextOccurrence
            entries=list(view._review_text_entries.values());entry=entries[0];other=entries[1]
            calls.append(dict(empty=not snapshot.libraries,layer=entry.target.layer))
            hit=bind_occurrence(TextOccurrence(entry.key,entry.start_ms,entry.text,entry.text+'ね',(0,len(entry.text)),
                reason='Explicit synthetic UI proposal; not model quality',source='translation_ai',default_selected=False),entry)
            return GlossaryReviewPreview((hit,),dict(successful_cues=len(entries),fallback_cues=0,request_errors=[],run_state='completed',
                pending_rows=[dict(cue_id=other.key,state='speech_review',span=[0,len(other.text)],surface=other.text,reason='Synthetic listening doubt')]))
        review.ai_stand_in=stand_in;before=page.project.cues[0].text
        QTest.mouseClick(review.ai_button,Qt.LeftButton);wait(lambda:not review.checks_running(),90)
        check('empty-library AI button actually starts one job',calls==[dict(empty=True,layer='original')],calls)
        check('generating proposal does not write text',page.project.cues[0].text==before)
        row=review._rows[0];index=next(i for i,issue in enumerate(row['issues']) if issue.get('replacement')==before+'ね')
        review._toggle_issue(row['cue_id'],index);pump(.2)
        check('explicit proposal adoption writes once',page.project.cues[0].text==before+'ね')
        page.undo_stack.undo();pump(.2);check('adoption undo restores exact source',page.project.cues[0].text==before)
        page.undo_stack.redo();pump(.1);check('adoption redo restores proposal',page.project.cues[0].text==before+'ね')
        page.undo_stack.undo();pump(.2)
        review.search.setText('お昼');pump(.3);review.search.clear();pump(.3)
        check('filtering does not repeat paid work',len(calls)==1)
        review.text_targets.mode.setCurrentIndex(review.text_targets.mode.findData('translation'))
        wait(lambda:not review.checks_running(),60)
        current_translation=review._rows[0]['base']
        QTest.mouseClick(review.ai_button,Qt.LeftButton);wait(lambda:not review.checks_running(),90)
        check('empty-library translation AI button starts correct layer',calls[-1]==dict(empty=True,layer='translation') and len(calls)==2)
        check('translation cards contain Japanese reference',bool(review._rows[0]['source_text']))
        row=review._rows[0];index=next(i for i,issue in enumerate(row['issues']) if issue.get('replacement')==current_translation+'ね')
        review._toggle_issue(row['cue_id'],index);pump(.2)
        from ..subtitle_rules.subtitle_translation import records_of
        owner=row['target'].cue_id
        check('translation proposal writes only its own layer',records_of(page.project)[owner]['text']==current_translation+'ね'
            and page.project.cues[0].text==before)
        page.undo_stack.undo();pump(.1)
        check('translation adoption undo restores manual snapshot',records_of(page.project)[owner]['text']==current_translation)
        large=WaveformTimeline();large.thumbnail_requests_enabled=False;large.resize(1400,400)
        synthetic=SubtitleProject(StudioMedia('',duration_ms=21600000),cues=[StudioCue(str(i),i*2000,i*2000+1500,'規模試験','S0') for i in range(10000)])
        large.set_project(synthetic)
        for i in range(20):
            began=time.perf_counter();large.locate_subtitle_start(i*1000000)
            timings.append(dict(action='10000 cue horizontal locate',ms=(time.perf_counter()-began)*1000))
        large.deleteLater();check('large locate preserves exact duration',large.visible_duration_ms==15000)
        window.grab().save(str(out/'04-review-adoption-window.png'))
    except Exception:
        error=traceback.format_exc();(out/'error.txt').write_text(error,'utf8');window.grab().save(str(out/'failure.png'))
    finally:
        if review is not None:review.shutdown()
        if page is not None:
            page._cancel_bound_caption_editor(trigger='acceptance_cleanup');page.undo_stack.setClean();page.project_dirty=False
        persist();window.close();app.quit()
