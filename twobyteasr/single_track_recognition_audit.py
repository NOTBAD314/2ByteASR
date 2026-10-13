"""Explicit acceptance-only real API chain; settings, media and results stay in tmp."""
import json
import os
from pathlib import Path
import time


def start(window,out):
    from PySide6.QtCore import QTimer
    def begin():
        from PySide6.QtWidgets import QApplication
        import threading,traceback
        from .studio_acceptance_audit import require
        report={'passed':False};page=window.studio_page;state={}
        def pump():QApplication.processEvents();time.sleep(.01)
        try:
            until=time.monotonic()+60
            while (page.project is None or not page._readiness.ready) and time.monotonic()<until:pump()
            require(page.project is not None and page._readiness.ready,'normal Studio ready')
            page.video.set_paused(True);page._set_volume(0)
            source=page.project.media.path
            from .build_identity import load_build_identity
            report['build']=load_build_identity().to_dict()
            def work():
                try:state['result']=run(source,out/'live-recognition')
                except Exception:state['error']=traceback.format_exc()
                finally:state['done']=True
            threading.Thread(target=work,daemon=True).start()
            until=time.monotonic()+300
            while not state.get('done') and time.monotonic()<until:pump()
            require(state.get('done'),'live ASR bounded wait')
            require(not state.get('error'),state.get('error',''))
            report['recognition']=state['result']
            report['continued_ui']=continue_editing(page,state['result']['project_path'],source,out)
            report['passed']=True
        except Exception:report['error']=traceback.format_exc()
        finally:
            (out/'recognition-runtime.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            page.undo_stack.setClean();window.close()
    QTimer.singleShot(600,begin)


def run(source,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    root=Path(__file__).resolve().parents[1]
    from . import llm_config,settings,reporting
    secret_reader=llm_config._read_secrets
    secret_path=Path(os.environ['USERPROFILE'])/'AppData/Local/2ByteASR/secrets.dat'
    llm_config._read_secrets=lambda:secret_reader(read_only_path=secret_path)
    settings.stable_settings_root=lambda:out/'config'
    reporting.REPORT_ROOT=out/'reports'
    from .processes import run_hidden_subprocess
    audio=out/'sample.wav'
    run_hidden_subprocess([str(root/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-i',str(source),
        '-t','12','-vn','-ac','1','-ar','16000',str(audio)],check=True,timeout=30,purpose='authorized 12s ASR acceptance sample')
    import subtitle_core as legacy
    legacy.CACHE_ROOT=str(out/'cache')
    models=dict(primary_asr_backend='api',qwen_asr_backend='off',firered_asr_backend='off',
        qwen_asr_api_provider='dashscope_qwen_audio',qwen_asr_api_protocol='dashscope_multimodal',
        qwen_asr_api_model='qwen-audio-3.0-asr-flash',
        qwen_asr_api_url='https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation')
    legacy.configure_runtime_asr(models)
    from .service import RunOptions,run_media_queue
    from dataclasses import asdict
    calls=[]
    def event(e):
        calls.append(asdict(e))
        (out/'events.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2),encoding='utf-8')
    started=time.perf_counter()
    result=run_media_queue([str(audio)],RunOptions(recognition_purpose='analysis',studio_project_path=str(out/'result.2byteproj')),event_sink=event)
    receipt=asdict(result);receipt['wall_seconds']=time.perf_counter()-started
    receipt['scope']='real 12s primary API, normal analysis pipeline; no review/polish models requested'
    if not result.successes:raise RuntimeError('实际单轨识别未完成：'+str([r.error for r in result.results]))
    from .studio_project import load_project
    p=load_project(result.successes[0].project_path)
    recovery=p.generation_metadata.get('speaker_recovery',{})
    receipt.update(speaker_ids=[s.id for s in p.speakers],cue_count=len(p.cues),processing=recovery.get('processing'),
        raw_labels=sorted({str(r.get('speaker')) for r in recovery.get('raw_segments',[])}),project_path=result.successes[0].project_path)
    from .studio_acceptance_audit import require
    require(len(p.cues)>0 and len(p.speakers)==1 and p.speakers[0].id=='SUBTITLES','real API default single caption track')
    require(recovery.get('processing',{}).get('mode')=='single','default processing mode')
    require(not recovery.get('processing',{}).get('moss_called'),'no hidden MOSS')
    (out/'result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    return receipt


def continue_editing(page,project_path,source,out):
    """Continue with unchanged real ASR text, bound to its exact source interval."""
    import copy
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QPushButton
    from .studio_acceptance_audit import require
    from .studio_project import SubtitleProject,StudioMedia,StudioSpeaker,load_project,save_project
    from .studio_edit_sequence import EditSequence,VideoSegment,store_sequence,projected_cues,sequence_of
    from .studio_media_pool import sync_primary_video_track_from_sequence
    from .recognition_input import capture_recognition_snapshot,attach_timeline_result
    result=load_project(project_path)
    media=copy.deepcopy(page.project.media);media.path=str(source);media.duration_ms=12000
    video=SubtitleProject(media=media,speakers=[StudioSpeaker('SUBTITLES',name='统一字幕')]);video.validate()
    seq=EditSequence(source_path=str(source),source_duration_ms=12000,video_track_locked=False,
        segments=[VideoSegment('real-source',str(source),0,12000,0,12000)])
    store_sequence(video,seq);sync_primary_video_track_from_sequence(video,seq)
    p=attach_timeline_result(result,capture_recognition_snapshot(video))
    target=out/'real-asr-video.2byteproj';save_project(p,target)
    def pump():QApplication.processEvents();time.sleep(.01)
    def wait(predicate,seconds=90):
        until=time.monotonic()+seconds
        while not predicate() and time.monotonic()<until:pump()
        require(predicate(),'real ASR edit wait')
    page.open_project(target,skip_dirty_guard=True)
    wait(lambda:page.project is not None and page.project.project_id==p.project_id and page._readiness.ready)
    p=page.project;page.video.set_paused(True);page._set_volume(0)
    signature=lambda:[(c.text,c.start_ms,c.end_ms) for c in projected_cues(p)]
    before=signature();checks={'real_asr_loaded':len(p.speakers)==1 and bool(before)}
    from .studio_speaker_manager import SpeakerManagerDialog
    manager=SpeakerManagerDialog(page);manager.show();manager.tabs.setCurrentIndex(manager.tabs.count()-1)
    def click(text):
        button=next(b for b in manager.findChildren(QPushButton) if b.text()==text)
        QTest.mouseClick(button,Qt.LeftButton)
    click('全选筛选结果');click('归入游戏背景声');page.undo_stack.undo()
    checks['real_batch_undo']=signature()==before
    manager.close()
    page._seek(6);QTest.qWait(450);page.timeline.setFocus()
    QTest.keyClick(page.timeline,Qt.Key_K,Qt.ControlModifier)
    checks['real_cut_keeps_captions']=signature()==before and len(sequence_of(p).segments)==2
    from .style_recipe import StyleRecipe
    recipe=StyleRecipe.from_dict({'name':'真实识别范围验收','engine':'remotion',
        'typography':{'fontFamily':'Microsoft YaHei','fontSize':72,'bold':True},
        'layout':{'alignment':2,'marginV':85},'colors':{'fill':{'type':'linear','angle':90,
        'stops':[{'color':'#FFFF50','pos':0},{'color':'#FF5040','pos':1}]}},
        'outline':{'layers':[{'color':'#000000','width':5}]},'motion':{},'background':{'enabled':False}})
    for cue in list(p.cues):page.select_cue(cue.id);page._apply_style_recipe(cue.id,recipe)
    cue=next((c for c in projected_cues(p) if c.end_ms>1500),projected_cues(p)[0])
    start=max(1,cue.start_ms-100);end=min(12000,max(start+500,cue.end_ms+100))
    page.project_range_bar.apply((start,end))
    QTest.mouseClick(page.studio_render_button,Qt.LeftButton);wait(lambda:page.export_workspace is not None)
    ui=page.export_workspace;ui.directory.setText(str(out/'real-exports'))
    ui.filename_prefix.clear();ui.filename_suffix.clear()
    ui.resolution.setCurrentIndex(ui.resolution.findData((1280,720)))
    if ui.encoder.findData('libx264')<0:ui.encoder.addItem('Software x264','libx264')
    ui.encoder.setCurrentIndex(ui.encoder.findData('libx264'))
    exports=[]
    for iteration in range(2):
        if iteration:
            ui._return_to_settings()
            page.cue_controller.set_text(cue.id, cue.text+'（人工编辑验收）')
        ui.filename.setText('real-asr-'+str(iteration));began=time.perf_counter()
        QTest.mouseClick(ui.export_button,Qt.LeftButton);wait(lambda:not ui._running,150)
        checks['real_export_'+str(iteration)]=ui.pages.currentWidget()==ui.success_page and ui._advanced_route
        require(checks['real_export_'+str(iteration)],'real ASR advanced export')
        exports.append({'path':ui._last_job.output_path,'elapsed_seconds':time.perf_counter()-began})
    frames=out/'real-frames';frames.mkdir()
    page.frame_capture.settings.setValue('frame_export/directory',str(frames))
    page.frame_capture.settings.setValue('frame_export/subtitles',True)
    page._seek((start+end)/2000);QTest.qWait(200)
    page.frame_capture.save();wait(lambda:not page.frame_capture.busy)
    checks['real_frame_saved']=page.frame_capture.last is not None
    for key,value in checks.items():require(value,key)
    save_project(p,out/'real-edited.2byteproj')
    return {'checks':checks,'exports':exports,'frame':page.frame_capture.last,'original_asr_text':before}
