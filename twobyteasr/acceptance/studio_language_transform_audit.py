"""Owned real-window exercise for the 2026-10-23 Studio repair."""
import copy
import json
import os
import sys
from pathlib import Path
import threading
import time
import traceback


def start(window,output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    output=Path(output)
    def execute():
        try:code=run(window,output)
        except Exception:
            path=output/'result.json'
            result=json.loads(path.read_text('utf8')) if path.is_file() else {}
            result.update(passed=False,error=traceback.format_exc())
            path.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8');code=1
        window.result_exit_code=code
        def stopped():
            path=output/'result.json';result=json.loads(path.read_text('utf8'));result['gui_shutdown']=True
            path.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        QApplication.instance().aboutToQuit.connect(stopped)
        window.studio_page.undo_stack.setClean()
        window.close()
    QTimer.singleShot(100,execute)


def run(window,output):
    from PySide6.QtCore import Qt,QSignalBlocker,QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .studio_splitter_audit import _native_rects,_picture_box
    from ..projects.studio_project import SubtitleProject,StudioMedia,StudioCue,hydrate_media_contract,save_project,load_project
    from ..studio.studio_helpers import probe_media_identity
    from ..caption_style.caption_layer_transform import resolved_values
    from ..caption_style.bilingual_layout import project_display_cues
    from ..timeline.studio_edit_sequence import sequence_of
    from ..diagnostics.build_identity import load_build_identity
    media=Path(os.environ['TWOBYTEASR_REPAIR_MEDIA'])
    result=dict(passed=False,checks=[],identity=load_build_identity().to_dict(),source_entry=not bool(getattr(sys,'frozen',False)))
    from ..rendering.caption_scene import CaptionScene
    from ..rendering.caption_playback_cache import PlaybackCaptionCache
    for cls,method,label in ((CaptionScene,'work','scene'),(PlaybackCaptionCache,'_work','prepare')):
        original=getattr(cls,method)
        def profiled(instance,_original=original,_label=label):
            import cProfile
            profile=cProfile.Profile();profile.enable()
            try:return _original(instance)
            finally:
                profile.disable();profile.dump_stats(str(output/(_label+'-worker.prof')))
        setattr(cls,method,profiled)
    def save():(output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,value,detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail));save()
    def wait(predicate,label,seconds=45):
        deadline=time.monotonic()+seconds
        while not predicate():
            if time.monotonic()>deadline:raise TimeoutError(label)
            QTest.qWait(20)
    def capture(name):
        QTest.qWait(180)
        _capture(window,output/(name+'.png'))
        _,native=_native_rects(page.video)
        if native:
            _picture_box(_native_rects.mpv_hwnd,(native[2],native[3]))
            _picture_box.last_image.save(output/(name+'-video.png'))
    def enter(control,value):
        began=time.perf_counter()
        profile=None
        if control.objectName()=='caption_position_y' and not (output/'caption-edit.prof').exists():
            import cProfile
            profile=cProfile.Profile();profile.enable()
        control.setFocus();control.selectAll()
        QTest.keyClicks(control,str(value));QTest.keyClick(control,Qt.Key_Return)
        if control.objectName().startswith('caption_'):
            scene=getattr(page,'_caption_scene',None)
            if scene is not None:
                wait(lambda:scene.token and scene.token[2]==page._revision_store.render.visual_revision and scene.published is not None,'current caption pixels',10)
            result.setdefault('caption_edit_ms',[]).append(round((time.perf_counter()-began)*1000,2))
        else:QTest.qWait(100)
        if profile:
            profile.disable();profile.dump_stats(str(output/'caption-edit.prof'))
    p=SubtitleProject(media=StudioMedia(str(media),duration_ms=12000,width=1920,height=1080),
        cues=[StudioCue('line-a',0,4000,'朝起きて 歯を磨いて'),StudioCue('line-b',4000,8000,'あっという間午後10時'),
              StudioCue('line-c',8000,12000,'今日もたくさん笑ったな')],
        generation_metadata={'translations':{'line-a':'早上起床 刷牙','line-b':'一转眼就到晚上十点','line-c':'今天也笑了好多'}},
        studio_state={'bilingual':{'mode':'bilingual'}})
    hydrate_media_contract(p,probe_media_identity(str(media)));p.validate()
    path=save_project(p,output/'repair.2byteproj')
    page=window.studio_page;prior=page.project
    window.showNormal();window.resize(1700,1000);window.show()
    window.open_studio_project(str(path),mode='edit',source='studio_language_transform_audit')
    wait(lambda:page.project is not prior and page._readiness.ready,'project readiness')
    wait(lambda:page.video.controller is not None,'mpv ready')
    QTest.qWait(1500);page.video.set_paused(True);page._seek(1.2);QTest.qWait(800)
    p=page.project
    events=result['render_events']=[];t0=time.perf_counter()
    def stamp(kind,detail):events.append(dict(kind=kind,at_ms=round((time.perf_counter()-t0)*1000,1),detail=detail))
    if getattr(page,'_caption_playback_cache',None):
        page._caption_playback_cache.ready.connect(lambda key,ids:stamp('prepared',dict(key=list(key),ids=list(ids))))
    if getattr(page,'_caption_scene',None):
        page._caption_scene.ready.connect(lambda token,pixels,trace:stamp('scene',dict(revision=token[2],elapsed=trace.get('duration_ms'),current=page._revision_store.render.visual_revision)))
    baseline=[(c.id,c.text,c.start_ms,c.end_ms,copy.deepcopy(c.evidence_refs)) for c in p.cues]
    track=p.video_tracks[0];clip=track.clips[0]
    track.locked=True;sequence_of(p).video_track_locked=True
    page._video_clip_selected(track.id,clip.id);QTest.qWait(100)
    check('locked controls disabled',not page.video_position_x.isEnabled() and not page.video_scale_link.isEnabled())
    check('visible unlock action',page.video_unlock_button.isVisible())
    before=copy.deepcopy(vars(clip.transform));page._video_transform_committed(track.id,clip.id,{'position_x':-.5})
    check('rejected transform leaves project unchanged',vars(p.video_tracks[0].clips[0].transform)==before)
    capture('01-video-locked')
    page.video_unlock_button.click();QTest.qWait(150)
    check('unlocks both lock representations',not p.video_tracks[0].locked and not sequence_of(p).video_track_locked)
    enter(page.video_position_x,30)
    wait(lambda:page.video_compositor.has_video_overlays,'transformed base compositor')
    QTest.qWait(1300)
    check('unlocked position persisted',abs(p.video_tracks[0].clips[0].transform.position_x-.3)<.001)
    check('native composite received transformed position',page.video_compositor._composes_base)
    capture('02-video-position')
    enter(page.video_scale_x,70)
    check('linked video scale',p.video_tracks[0].clips[0].transform.scale_y==.7)
    page.video_scale_link.click();enter(page.video_scale_y,50)
    check('unlinked video scale',p.video_tracks[0].clips[0].transform.scale_x==.7 and p.video_tracks[0].clips[0].transform.scale_y==.5)
    enter(page.video_rotation,15);enter(page.video_anchor_x,25)
    capture('03-video-rotate-anchor')
    page.video_transform_reset.click();QTest.qWait(400)
    # 2026-10-24: caption transforms live on the 视频 tab (the caption card
    # replaces the clip cards while a caption is selected).
    page.context_drawer.setCurrentIndex(page.video_transform_tab_index);page.select_cue('line-a')
    panel=page.caption_transform_panel
    check('caption card on video tab',page.context_drawer.currentIndex()==page.video_transform_tab_index
          and panel.isVisible() and not page.video_clip_controls.isVisible())
    before_translation=resolved_values(p,p.cues[0],'translation')
    enter(panel.controls['position_x'],37);enter(panel.controls['position_y'],78)
    enter(panel.controls['scale_x'],115);enter(panel.controls['rotation'],8)
    check('source numeric transform persisted',resolved_values(p,p.cues[0],'original')['position_x']==710.4)
    check('source transform preserves translation',resolved_values(p,p.cues[0],'translation')==before_translation)
    capture('04-source-transform')
    panel.language.setCurrentIndex(1);enter(panel.controls['position_x'],64);enter(panel.controls['position_y'],63)
    enter(panel.controls['scale_x'],85);enter(panel.controls['rotation'],-6);enter(panel.controls['anchor_x'],30)
    translation=resolved_values(p,p.cues[0],'translation')
    check('translation numeric transform persisted',abs(translation['position_x']-1228.8)<.01 and translation['rotation']==-6)
    capture('05-translation-transform')
    page.select_cue('line-b');page.select_cue('line-a');panel.language.setCurrentIndex(1);panel.refresh()
    check('selection reload uses stable language ID',abs(panel.controls['position_x'].value()-64)<.01)
    page.undo_stack.undo();page.undo_stack.redo();panel.refresh()
    check('undo redo restores layer transform',resolved_values(p,p.cues[0],'translation')==translation)
    # Drag the translation through the actual canvas input path.
    overlay=page.position_overlay
    page.position_edit_button.setChecked(True)
    page.ensure_active_subtitle_renderer(reason='acceptance_canvas_drag')
    panel.refresh()
    result['canvas_before_drag']=dict(visible=overlay.isVisible(),checked=page.position_edit_button.isChecked(),
        geometry=overlay.geometry_diagnostics,scene=page._caption_scene.trace())
    save()
    wait(lambda:overlay._measured_bounds is not None,'translation selection geometry')
    before_original=resolved_values(p,p.cues[0],'original')
    point=overlay._subtitle_rect().center().toPoint()
    local=overlay.mapTo(window,point);handle_window=window.windowHandle()
    QTest.mouseMove(handle_window,local);QTest.mousePress(handle_window,Qt.LeftButton,Qt.NoModifier,local)
    for delta in (12,24,36):QTest.mouseMove(handle_window,local+QPoint(delta,-12));QTest.qWait(30)
    QTest.mouseRelease(handle_window,Qt.LeftButton,Qt.NoModifier,local+QPoint(36,-12))
    QTest.qWait(300)
    moved=resolved_values(p,p.cues[0],'translation')
    check('canvas drag updates translation numeric position',moved['position_x']!=translation['position_x'],dict(before=translation,after=moved))
    check('translation canvas drag leaves original unchanged',resolved_values(p,p.cues[0],'original')==before_original)
    translation=moved
    capture('05b-translation-canvas-drag')
    page.context_drawer.setCurrentIndex(page.motion_tab_index);QTest.qWait(200)
    before_clock=page.video.playback_position_snapshot()
    page.motion_inspector.choose('entry','whip_in')
    QTest.qWait(250)
    original,companion=project_display_cues(p)[:2]
    check('preset immediately changes both languages',original.effect_id==companion.effect_id and p.effects[original.effect_id]['entry']['type']=='whip_in')
    check('extra apply step removed',page.motion_apply.isHidden())
    check('motion preserves language geometry',resolved_values(p,p.cues[0],'translation')==translation)
    after_clock=page.video.playback_position_snapshot()
    check('motion keeps main paused playhead',after_clock.paused and abs(after_clock.presentation_media_ms-before_clock.presentation_media_ms)<80)
    count=page.undo_stack.count();page.motion_inspector.slider.sliderPressed.emit()
    for value in (12,14,16,18):page.motion_inspector.slider.setValue(value)
    page.motion_inspector.slider.sliderReleased.emit()
    check('duration drag has one undo command',page.undo_stack.count()==count+1,(count,page.undo_stack.count()))
    ids=[c.effect_id for c in p.cues];page.motion_scope.setCurrentIndex(page.motion_scope.findData('all'))
    check('scope switch does not reapply',ids==[c.effect_id for c in p.cues])
    page.select_cue('line-b')
    check('new cue resets broad motion scope',page.motion_scope.currentData()=='current')
    page.select_cue('line-a')
    capture('06-bilingual-motion')
    # Live splitter movement: video HWND, caption raster and selection bounds.
    from PySide6.QtWidgets import QSplitter
    from .studio_splitter_audit import _picture_lag
    _picture_lag.canvas=page.video
    all_geometry=copy.deepcopy([c.transform for c in p.cues])
    result['resize_samples']=[]
    for playing in (False,True):
        page._seek(1.2);page.video.set_paused(not playing);QTest.qWait(150)
        clock_before=page.video.playback_position_snapshot()
        for splitter_name,index,delta in (('studioUpperSplitter',2,-60),('studioUpperSplitter',2,60),('studioWorkspaceSplitter',1,50),('studioWorkspaceSplitter',1,-50)):
            splitter=page.findChild(QSplitter,splitter_name)
            handle=splitter.handle(index);start=handle.mapTo(window,handle.rect().center())
            vertical=splitter.orientation()==Qt.Vertical
            QTest.mouseMove(handle_window,start);QTest.mousePress(handle_window,Qt.LeftButton,Qt.NoModifier,start)
            for step in range(1,5):
                began=time.perf_counter();point=start+(QPoint(0,round(delta*step/4)) if vertical else QPoint(round(delta*step/4),0))
                QTest.mouseMove(handle_window,point);QApplication.processEvents()
                scene=page._caption_scene
                wait(lambda:scene.token and tuple(scene.token[-4:])==page.position_overlay._content_rect().toRect().getRect()
                    and scene.last_result_token==scene.token and scene.published is not None,'resized caption pixels',5)
                caption_ms=round((time.perf_counter()-began)*1000,2)
                video_ms,picture=_picture_lag()
                qt_rect,native_rect=_native_rects(page.video)
                result['resize_samples'].append(dict(playing=playing,splitter=splitter_name,delta=delta,step=step,
                    caption_ms=caption_ms,video_extra_ms=video_ms,native_matches=qt_rect==native_rect))
            QTest.mouseRelease(handle_window,Qt.LeftButton,Qt.NoModifier,point)
        clock_after=page.video.playback_position_snapshot()
        check(('playing' if playing else 'paused')+' resize does not seek',clock_after.playback_generation==clock_before.playback_generation)
        page.video.set_paused(True)
    check('resize preserves all project coordinates',[c.transform for c in p.cues]==all_geometry)
    check('video and caption geometry follow every resize',all(s['native_matches'] and s['video_extra_ms'] is not None and s['caption_ms']<500 for s in result['resize_samples']),
        dict(max_caption_ms=max(s['caption_ms'] for s in result['resize_samples'])))
    page._seek(1.2);page.video.set_paused(True);QTest.qWait(250)
    capture('07-resize-follow')
    # Export includes a non-default video transform as well as both text layers.
    track=p.video_tracks[0];clip=track.clips[0]
    page._video_transform_committed(track.id,clip.id,{'scale_x':.9,'scale_y':.9,'position_x':.5,'position_y':.5,'rotation':2.})
    QTest.qWait(700);capture('07b-export-layout')
    save_project(p,path);restored=load_project(path)
    check('saved project preserves independent language fields',restored.cues[0].transform==p.cues[0].transform)
    check('presentation edits preserve text times evidence',baseline==[(c.id,c.text,c.start_ms,c.end_ms,c.evidence_refs) for c in p.cues])
    # Real export uses the same frozen project and video graph as the UI.
    from ..exports.export_timeline import write_export_ass
    from ..exports.studio_render import RenderJob,RenderSettings,run_render_job
    from ..exports.video_export import capture_video_graph
    from ..runtime_paths import get_runtime_paths
    ass=output/'bilingual.ass';write_export_ass(p,ass)
    job=RenderJob(p.media.path,str(ass),str(output/'bilingual-12s.mp4'),
        RenderSettings(encoder='libx264',preset='ultrafast',width=960,height=540,fps=30,audio_codec='aac'),
        start_seconds=0,duration_seconds=12,video_graph=capture_video_graph(p))
    done={}
    def render():
        try:run_render_job(get_runtime_paths().install_root/'tools/ffmpeg/bin/ffmpeg.exe',job)
        except Exception:done['error']=traceback.format_exc()
        done['finished']=True
    threading.Thread(target=render,daemon=True).start()
    wait(lambda:done.get('finished'),'12-second export',240)
    check('twelve second bilingual burn-in succeeds',not done.get('error') and Path(job.output_path).is_file(),done.get('error'))
    result['export']=dict(path=job.output_path,metadata=job.completion_metadata)
    if not done.get('error'):
        import numpy as np
        from ..system.processes import run_hidden_subprocess
        counts={}
        for seconds in (.1,1.2):
            decoded=run_hidden_subprocess([str(get_runtime_paths().install_root/'tools/ffmpeg/bin/ffmpeg.exe'),
                '-v','error','-ss',str(seconds),'-i',job.output_path,'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],
                capture_output=True,check=True,timeout=20,purpose='verify bilingual export motion')
            frame=np.frombuffer(decoded.stdout,dtype=np.uint8).reshape(540,960,3)
            counts[str(seconds)]={}
            for language,(x1,y1,x2,y2) in {'original':(120,340,530,500),'translation':(540,230,900,370)}.items():
                area=frame[y1:y2,x1:x2]
                counts[str(seconds)][language]=int(np.count_nonzero((area.min(axis=2)>210)&(area.max(axis=2).astype(int)-area.min(axis=2)<25)))
        result['export_motion_pixels']=counts
        for language in ('original','translation'):
            check(language+' visibly animates in actual export',counts['1.2'][language]>50 and counts['0.1'][language]<counts['1.2'][language]*.85,counts)
    # Apply the actual real-provider result, then replay the captured failure.
    fixture_root=Path(os.environ.get('TWOBYTEASR_REPAIR_FIXTURE_ROOT') or Path(__file__).resolve().parents[2])
    suggestion_path=fixture_root/'tmp/studio-repair/real-ai-r2/suggestion.json'
    if suggestion_path.is_file():
        from ..caption_design.studio_ai import AIWebThemeSuggestion
        page.select_cue('line-a');page.context_drawer.setCurrentIndex(0)
        page.ai_prompt.setPlainText('「日常」动漫的风格');page._ai_last_instruction='「日常」动漫的风格'
        drafts=page._theme_drafts();page._ai_request_generation+=1
        suggestion=AIWebThemeSuggestion(**json.loads(suggestion_path.read_text('utf8')))
        drafts.begin(page._ai_request_generation,'line-a',provider=suggestion.provider,model=suggestion.model)
        drafts.receive(page._ai_request_generation,'line-a',suggestion)
        wait(lambda:getattr(drafts,'_concept_dialog',None) is not None,'real AI candidate dialog')
        if any(c.get('preview_integrity_error') for c in drafts.design.get('concepts',[])):
            # Frozen builds carry their own dependency fingerprint. Re-render
            # the exact captured source locally instead of trusting source-run
            # previews or issuing another model request.
            drafts._render_concepts()
            wait(lambda:drafts.phase in {'CHOOSING','VISUAL_REVIEW','FAILED'},'candidate preview in this build',150)
        drafts._concept_dialog.choose(suggestion.concepts[0]['id'])
        wait(lambda:drafts.phase in {'APPLIED','FAILED','READY'},'real AI application',120)
        check('real provider design validates and applies in Studio',drafts.phase=='APPLIED',dict(phase=drafts.phase,error=drafts.error))
        def ai_pixels_ready():
            trace=page._caption_scene.trace()
            return trace['visible'] and len(trace['cue_pixels'])==2 and all(row['status']=='rendered' and row.get('alpha_nonzero',0)>0 for row in trace['cue_pixels'])
        wait(ai_pixels_ready,'applied real AI visible pixels',60)
        check('real AI paints both language layers',ai_pixels_ready(),page._caption_scene.trace())
        capture('08-real-ai-applied')
        applied=copy.deepcopy(p.to_dict())
        page._ai_request_generation+=1
        drafts.begin(page._ai_request_generation,'line-a',provider=suggestion.provider,model=suggestion.model)
        raw=(fixture_root/'tests/fixtures/studio-design-38e22e1/provider-original.txt').read_text('utf8')
        from ..providers.structured_output import response_object
        try:response_object(raw)
        except ValueError as exc:
            folder=drafts.root/'creative';(folder/'directions').mkdir(parents=True,exist_ok=True)
            (folder/'directions/provider-original.txt').write_text(raw,'utf8')
            (folder/'ledger.json').write_text(json.dumps({'last_failure':dict(exc.diagnostics,finish_reason='stop')},ensure_ascii=False),'utf8')
            drafts._failed(drafts.operation,str(exc),exc.category)
        check('failure ends generating and leaves applied project intact',drafts.phase=='FAILED' and not drafts.generation_running and p.to_dict()==applied)
        check('failed direction has correct retry and diagnostics',page.ai_retry_theme_code_button.isEnabled()
            and drafts.diagnostics()['failure_diagnostics'].get('column')==490 and page.ai_suggestion_title.text()=='设计未完成')
        capture('09-ai-failure-preserves-design')
    result['passed']=all(row['passed'] for row in result['checks']);save()
    return 0 if result['passed'] else 1
