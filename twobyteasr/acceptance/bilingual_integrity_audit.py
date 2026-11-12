"""Known bilingual/secondary-track failures through normal MainWindow + mpv."""
import ctypes,json,os,platform,time,traceback
from pathlib import Path
from copy import deepcopy


def start(window,out):
    from PySide6.QtCore import QTimer,QPoint,Qt
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from ..projects.studio_project import SubtitleProject,StudioMedia,StudioSpeaker,StudioCue,save_project,load_project
    from ..subtitle_rules import subtitle_translation as st
    from ..caption_style.bilingual_layout import project_display_cues
    from ..caption_style.subtitle_visibility import translation_key
    from ..recognition.speaker_roles import decide
    from ..studio.studio_track_header import button_rect
    from ..studio.video_viewport import fitted_video_rect
    from ..diagnostics.build_identity import load_build_identity
    from ..system.processes import run_hidden_subprocess
    from .blank_project_audit import _capture
    app=QApplication.instance()
    result=dict(passed=False,checks=[],metrics={},identity=load_build_identity().to_dict(),pid=os.getpid(),
        executable=__import__('sys').executable,dpr=window.devicePixelRatioF(),hardware=dict(platform=platform.platform(),processor=platform.processor()),
        conditions='normal MainWindow; Qt events; private Windows desktop; real mpv; no physical screen/IME claim')
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.GetParent.argtypes=[ctypes.c_void_p];user.GetParent.restype=ctypes.c_void_p
    def save():(out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf-8')
    def check(name,value,detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail));save()
        if not value:raise AssertionError(name+' '+str(detail))
    def shot(name):
        _capture(window,out/(name+'.png'))
    def finish(error=None):
        if error:result['error']=error
        result['passed']=not error and bool(result['checks']) and all(r['passed'] for r in result['checks'])
        save()
        if window.studio_page is not None:window.studio_page.undo_stack.setClean()
        app.exit(0 if result['passed'] else 1)
    def ready():
        page=window.built_page('studio');loading=window.__dict__.get('_studio_loading_session')
        return bool(page and page.project and (loading is None or not loading.active))
    def open_project(path):
        if window.built_page('studio') is not None:
            page=window.studio_page;page.undo_stack.setClean();page.show_project_hub(skip_dirty_guard=True)
        window.open_studio_project(str(path))
    def shown(page):return {c.text for c in project_display_cues(page.project)}
    def flow():
        window.resize(1600,1000);window.show();yield .5
        from ..runtime_paths import detect_install_root
        ffmpeg=detect_install_root()/'tools/ffmpeg/bin/ffmpeg.exe'
        media=out/'fixture.mp4'
        run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-f','lavfi','-i','testsrc2=size=960x540:rate=30:duration=18',
            '-c:v','libx264','-preset','ultrafast',str(media)],capture_output=True,check=True,timeout=30,purpose='bilingual integrity fixture')
        p=SubtitleProject(StudioMedia(str(media),duration_ms=18000,width=960,height=540),
            speakers=[StudioSpeaker('A'),StudioSpeaker('B'),StudioSpeaker('C')],
            cues=[StudioCue('a',0,6000,'そうじゃなくてそうじゃなくて',speaker_id='A'),
                  StudioCue('b',0,6000,'えーナノちゃんお弁当なんだ',speaker_id='B'),
                  StudioCue('c',9000,12000,'ナノちゃん今日はパパッと食べちゃおうか',speaker_id='C'),
                  StudioCue('far',14000,17000,'遠くの字幕',speaker_id='B')])
        p.generation_metadata['language']={'code':'ja'}
        st.set_manual(p,'a','不是那个 不是那个',target='zh-Hans');st.set_manual(p,'b','小奈的便当啊',target='zh-Hans')
        p.studio_state['bilingual']={'mode':'bilingual'}
        p.studio_state['speaker_roles']=decide(p,manual={'A':'main','B':'secondary','C':'secondary'},expanded=False)
        path=save_project(p,out/'fixture.2byteproj');open_project(path);yield ready;yield .8
        page=window.studio_page;p=page.project;page.volume_slider.setValue(0);page.video.set_paused(True);page._seek(1.0);yield .7
        check('normal project and real mpv',len(p.cues)==4 and page.video.controller is not None)
        check('native canvas has viewport clipping parent',int(user.GetParent(int(page.video.internalWinId())) or 0)==int(page.video_overlay_host.internalWinId() or 0))
        page.timeline.set_group_expanded(False);page.select_cue('far');yield .1
        check('list selection expands minor owner',page.timeline._group_expanded)
        rect=page.timeline._track_layout()[0]['B'];viewport=page.timeline._track_viewport()
        check('owner row revealed in viewport',rect.intersects(viewport))
        page._seek(1.0);page.select_cue('a');page.timeline.set_subtitle_layer('original');yield .2
        QTest.keyClick(page.timeline,Qt.Key.Key_E);yield .2
        check('E original text and layer',page._caption_draft.target.layer=='original' and page.subtitle_edit_input.toPlainText()==p.cues[0].text)
        page.subtitle_edit_input.setPlainText('そうじゃなくてそうじゃなくて！');QTest.mouseClick(page.caption_confirm_button,Qt.LeftButton);yield .3
        check('E original commits only source',p.cues[0].text.endswith('！') and st.records_of(p)['a']['text']=='不是那个 不是那个')
        page.undo_stack.undo();yield .1;check('original edit undo',p.cues[0].text=='そうじゃなくてそうじゃなくて')
        page.undo_stack.redo();yield .1;check('original edit redo',p.cues[0].text.endswith('！'));page.undo_stack.undo()
        page.timeline.select_translation('a');yield .1;QTest.keyClick(page.timeline,Qt.Key.Key_E);yield .2
        check('E translation text and layer',page._caption_draft.target.layer=='translation' and page.subtitle_edit_input.toPlainText()=='不是那个 不是那个')
        page.subtitle_edit_input.setPlainText('不是那样 不是那样');QTest.mouseClick(page.caption_confirm_button,Qt.LeftButton);yield .2
        check('translation commits only record',p.cues[0].text=='そうじゃなくてそうじゃなくて' and st.records_of(p)['a']['text']=='不是那样 不是那样')
        page.undo_stack.undo();yield .1;page.undo_stack.redo();yield .1;check('translation undo redo',st.records_of(p)['a']['text']=='不是那样 不是那样')
        page.timeline.set_subtitle_layer('original');page.select_cue('b');page.timeline.reveal_cue('b');yield .1
        row=page.timeline._track_layout()[0]['B'];before=dict(p.studio_state.get('subtitle_track_visibility',{}))
        QTest.mouseClick(page.timeline,Qt.LeftButton,pos=button_rect('subtitle','visibility',row).center().toPoint());yield .7
        check('minor eye targets one original track',p.studio_state['subtitle_track_visibility']==dict(before,B=False))
        check('hidden original keeps translation and sibling',{'小奈的便当啊','そうじゃなくてそうじゃなくて'}<=shown(page) and 'えーナノちゃんお弁当なんだ' not in shown(page))
        yield lambda:page._caption_scene is not None and page._caption_scene.trace().get('visible') and all(r.get('status')!='pending' for r in page._caption_scene.trace().get('cue_pixels',[]))
        trace=page._caption_scene.trace();result['independent_scene']=deepcopy(trace)
        check('actual scene retains translation while source hidden','b#tr' in [r['cue_id'] for r in trace['cue_pixels']] and 'b' not in [r['cue_id'] for r in trace['cue_pixels']])
        from ..exports.studio_subtitle_export import export_language_layers
        exports=export_language_layers(p,out/'independent-srt','visible',layers=('original','translation','bilingual'))
        texts={a.layer:a.path.read_text(encoding='utf-8-sig') for a in exports.artifacts}
        check('actual source SRT omits hidden minor text','えーナノちゃんお弁当なんだ' not in texts['original'])
        check('actual translation and bilingual SRT retain visible translation','小奈的便当啊' in texts['translation'] and '小奈的便当啊' in texts['bilingual']
            and 'えーナノちゃんお弁当なんだ' not in texts['bilingual'])
        shot('independent-minor-eye');page.video.controller.screenshot_to_file(out/'independent-minor-eye-mpv.png');yield .2
        page.undo_stack.undo();yield .2;check('eye undo',p.studio_state['subtitle_track_visibility']['B'])
        page.undo_stack.redo();yield .2;check('eye redo',not p.studio_state['subtitle_track_visibility']['B']);page.undo_stack.undo()
        page.timeline.vertical_scrollbar.setValue(page.timeline.vertical_scrollbar.maximum());yield .1
        translation_row=page.timeline._track_layout()[1]
        QTest.mouseClick(page.timeline,Qt.LeftButton,pos=button_rect('subtitle','visibility',translation_row).center().toPoint());yield .4
        check('translation eye independent',not p.studio_state['subtitle_track_visibility'][translation_key(p)] and p.studio_state['subtitle_track_visibility']['B'])
        page.undo_stack.undo();yield .2
        from ..subtitle_rules.review_suggestions import model_suggestions
        check('Japanese name geminate ending repetition protected',not model_suggestions('えーナノちゃんお弁当なんだ',[('えナノちゃんお弁当なん',('reference',))]))
        # Actual latest Qt geometry at every drag step. Images are collected in
        # a separate slow sampling pass so capture overhead is not a timing claim.
        page.select_cue('a');page._seek(1.0);yield .4
        intervals=[];elapsed=[];geometries=[];last=[time.perf_counter()]
        timer=QTimer(window);timer.setInterval(10)
        def beat():
            now=time.perf_counter();intervals.append((now-last[0])*1000);last[0]=now
        timer.timeout.connect(beat);timer.start()
        controller=page.video.controller
        for playing in (False,True):
            page.video.set_paused(not playing)
            for i in range(48):
                started=time.perf_counter();height=260+round(340*(i%24)/23) if i<24 else 600-round(340*(i%24)/23)
                page.workspace_splitter.moveSplitter(height,1)
                elapsed.append((time.perf_counter()-started)*1000)
                target=fitted_video_rect(page.video_overlay_host.size(),page.video_overlay_host._video_aspect)
                geometries.append(dict(step=i,playing=playing,canvas=page.video.geometry().getRect(),expected=target.getRect(),overlay=page.position_overlay.geometry().getRect()))
                if page.video.geometry()!=target or page.position_overlay.geometry()!=page.video.rect():raise AssertionError('latest resize/overlay geometry')
                yield .016
        timer.stop();page.video.set_paused(True)
        percentile=lambda values,p:sorted(values)[min(len(values)-1,round((len(values)-1)*p))] if values else 0
        result['metrics']['resize']=dict(samples=len(elapsed),qt_geometry_ms_p95=percentile(elapsed,.95),qt_geometry_ms_max=max(elapsed),
            heartbeat_ms_p95=percentile(intervals,.95),heartbeat_ms_max=max(intervals),native_parent='viewport HWND',snapshots=geometries)
        check('latest geometry every paused and playing step',len(geometries)==96)
        for pos in (270,430,600,320):
            page.workspace_splitter.moveSplitter(pos,1);yield .08;shot('splitter-'+str(pos))
        page.timeline.set_subtitle_layer('original');page.select_cue('c');page._seek(10);yield .3
        saved=save_project(p,out/'saved.2byteproj');open_project(saved);yield ready;yield .5
        check('save reopen keeps identities and visibility',{c.id for c in window.studio_page.project.cues}=={'a','b','c','far'})
        if os.environ.get('BILINGUAL_AUDIT_PROJECT'):
            original=Path(os.environ['BILINGUAL_AUDIT_PROJECT']);open_project(original);yield ready;yield .8
            page=window.studio_page;p=page.project
            check('real saved project restores cue326',len(p.cues)==352 and any(c.id=='326' and c.text=='泣くなお前には来年がある' for c in p.cues))
            page.volume_slider.setValue(0);page._seek(754.5);yield .8;shot('real-352')
            gaps=p.generation_metadata['speech_coverage']['gaps']
            result['metrics']['legacy_gaps']=dict(total=len(gaps),pending=sum(g['status'] not in {'excluded','recovered','non_speech'} for g in gaps),
                text_retained=sum(g.get('text_reconciliation',{}).get('reason')=='text_retained_timing_contracted' for g in gaps))
            from PySide6.QtWidgets import QPushButton,QLabel,QScrollArea
            def inspect_recovery():
                dialog=QApplication.activeModalWidget()
                try:
                    check('seven retained-text windows remain in timing review',len(dialog.findChildren(QPushButton,'speechGapTimingReview'))==7)
                    check('only 61 unresolved speech windows offer recognition retry',len(dialog.findChildren(QPushButton,'speechGapRetry'))==61)
                    target=dialog.findChildren(QPushButton,'speechGapTimingReview')[0]
                    dialog.findChild(QScrollArea).ensureWidgetVisible(target)
                    QTest.qWait(30)
                    _capture(dialog,out/'speech-and-timing-review.png')
                finally:dialog.accept()
            QTimer.singleShot(150,inspect_recovery)
            from ..studio.speech_recovery_ui import open_recovery
            open_recovery(page);yield .3
            sample=next(c for c in p.cues if c.text=='えーナノちゃんお弁当なんだ')
            page.timeline.set_subtitle_layer('original');page.select_cue(sample.id);QTest.keyClick(page.timeline,Qt.Key.Key_E);yield .3
            check('real Japanese editor has no unsupported deletion',not any(not o.text for r in page._caption_draft.suggestions for o in r.options))
            shot('real-japanese-editor');page._cancel_canvas_inline_edit();yield .1
            sample=next(c for c in p.cues if 'パパッと食べちゃおうか' in c.text)
            page.timeline.set_subtitle_layer('original');page.select_cue(sample.id);page._seek(sample.start_ms/1000);yield .3
            QTest.keyClick(page.timeline,Qt.Key.Key_E);yield .2
            check('real geminate sample binds final ID and preserves text',page._caption_draft.target.cue_id==sample.id and 'パパッと' in page.subtitle_edit_input.toPlainText()
                and not any(not o.text for r in page._caption_draft.suggestions for o in r.options))
            shot('real-geminate-editor');page._cancel_canvas_inline_edit();yield .1
            from ..subtitle_rules.current_issues import current_issue_view
            view=current_issue_view(p)
            result['metrics']['review_counts']=dict(counts=view.counts(),totals=view.totals(),statistics=view.statistics())
        page=window.studio_page
        window.showMaximized();yield .2
        check('maximized geometry stays current',page.video.geometry()==fitted_video_rect(page.video_overlay_host.size(),page.video_overlay_host._video_aspect))
        window.showNormal();yield .2
        for visible in (False,True):
            if page.context_panel.isVisible()!=visible:page.context_expand_button.click()
            yield .1
            check('sidebar geometry '+str(visible),page.video.geometry()==fitted_video_rect(page.video_overlay_host.size(),page.video_overlay_host._video_aspect))
        large=SubtitleProject(StudioMedia(str(media),duration_ms=5000000,width=960,height=540),speakers=[StudioSpeaker(k) for k in ('A','B','C')],
            cues=[StudioCue('scale-'+str(i),i*500,i*500+480,'规模验证字幕 '+str(i),speaker_id=('A','B','C')[i%3]) for i in range(10000)])
        large_path=save_project(large,out/'scale-10000.2byteproj');began=time.perf_counter();open_project(large_path);yield ready;yield .3
        result['metrics']['scale_10000_ready_ms']=(time.perf_counter()-began)*1000
        page=window.studio_page;page.volume_slider.setValue(0)
        check('10000 caption project complete',len(page.project.cues)==10000)
        timings=[]
        for pos in range(280,600,20):
            began=time.perf_counter();page.workspace_splitter.moveSplitter(pos,1);timings.append((time.perf_counter()-began)*1000);yield .016
        result['metrics']['scale_10000_resize_ms']=dict(samples=len(timings),maximum=max(timings),p95=sorted(timings)[round((len(timings)-1)*.95)])
        check('10000 caption resize keeps newest geometry',page.video.geometry()==fitted_video_rect(page.video_overlay_host.size(),page.video_overlay_host._video_aspect))
        finish()
    steps=flow()
    def drive():
        try:wanted=next(steps)
        except StopIteration:return
        except Exception:finish(traceback.format_exc());return
        if callable(wanted):
            deadline=time.monotonic()+60
            def poll():
                try:
                    if wanted():QTimer.singleShot(10,drive)
                    elif time.monotonic()>deadline:finish('Timed out waiting for normal project readiness')
                    else:QTimer.singleShot(25,poll)
                except Exception:finish(traceback.format_exc())
            QTimer.singleShot(0,poll)
        else:QTimer.singleShot(max(1,round(wanted*1000)),drive)
    def shutdown():result['gui_shutdown']=True;save()
    app.aboutToQuit.connect(shutdown)
    QTimer.singleShot(800,drive)
