"""Real export workspace, edited media graph and audio/video artifacts."""
import json
import os
from pathlib import Path
import time


def run(window,output):
    from PySide6.QtTest import QTest
    from ..projects.studio_project import (SubtitleProject,StudioCue,StudioMedia,AudioClip,AudioTrack,
        save_project,hydrate_media_contract)
    from ..studio.studio_helpers import probe_media_identity
    from ..timeline.studio_edit_sequence import EditSequence,VideoSegment
    from ..timeline.studio_edit_commands import EditSequenceCommand
    from ..timeline.studio_media_pool import add_media_asset,set_audio_master_mode
    from ..system.platform_media import ffmpeg_tool
    from ..system.processes import run_hidden_subprocess
    from ..exports.audio_delivery import probe_audio
    from .blank_project_audit import _capture
    ffmpeg=ffmpeg_tool();media=Path(os.environ['TWOBYTEASR_PERF_MEDIA'])
    result={'checks':[],'exports':[]}
    def save():(output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,ok,detail=None):
        result['checks'].append(dict(name=name,passed=bool(ok),detail=detail));save()
    def wait(fn,label,seconds=90):
        end=time.monotonic()+seconds
        while not fn():
            if time.monotonic()>end:raise TimeoutError(label)
            QTest.qWait(10)
    p=SubtitleProject(media=StudioMedia(str(media),duration_ms=12000,width=1280,height=720),
        cues=[StudioCue('first',0,2000,'剪輯後第一段'),StudioCue('last',3000,4500,'加速與多軌混音')],
        generation_metadata={'translations':{'first':'Edited first clip','last':'Speed and audio mix'}},
        studio_state={'bilingual':{'mode':'bilingual'}})
    hydrate_media_contract(p,probe_media_identity(str(media)));p.validate()
    sequence=EditSequence(source_path=str(media),source_duration_ms=12000,segments=[
        VideoSegment('first-video',str(media),1000,3000,0,2000),
        VideoSegment('last-video',str(media),6000,9000,3000,4500)])
    EditSequenceCommand(p,sequence).redo()
    p.render_settings.update(_cue_domain='timeline',play_res_x=1280,play_res_y=720)
    p.audio_tracks[0].clips[-1].gain_db=-6
    tone=output/'混音 220.wav'
    run_hidden_subprocess([str(ffmpeg),'-v','error','-f','lavfi','-i','sine=frequency=220:sample_rate=44100:duration=2',
        '-c:a','pcm_s16le',str(tone)],purpose='audio acceptance source',check=True,capture_output=True,timeout=20)
    asset=add_media_asset(p,tone,duration_ms=2000,video_metadata={'has_video':False},audio_metadata={'has_audio':True})
    p.audio_tracks.append(AudioTrack(id='mix-extra',name='附加混音',
        clips=[AudioClip(id='mix-clip',asset_id=asset.asset_id,source_in_ms=0,source_out_ms=750,
                         timeline_in_ms=3500,timeline_out_ms=4250,gain_db=-12)]))
    set_audio_master_mode(p,'mix_all')
    path=save_project(p,output/'剪輯混音 工程.2byteproj')
    page=window.studio_page;prior=page.project;page.undo_stack.setClean()
    window.showNormal();window.resize(1600,950);window.show()
    window.open_studio_project(str(path),mode='edit',source='workbench-export')
    wait(lambda:page.project is not prior and page._readiness.ready,'project ready')
    QTest.qWait(700);page.video.set_paused(True)
    page.studio_render_button.click()
    wait(lambda:page.export_workspace is not None,'export workspace')
    w=page.export_workspace
    QTest.qWait(400)
    w.directory.setText(str(output));w.output_kind.setCurrentIndex(w.output_kind.findData('audio'))
    wait(lambda:w.audio_delivery.capabilities is not None,'audio codecs',60)
    check('audio hides video settings',not w.video_group.isVisible() and not w.preview_host.isVisible())
    _capture(window,output/'audio-setup.png')
    for name in ('mp3','wav','m4a','flac','ogg','opus'):
        w._return_to_settings()
        w.filename.setText('工作台 音訊 '+name)
        w.extension.setCurrentIndex(w.extension.findData(name))
        if name in ('wav','flac'):w.audio_delivery.depth.setCurrentIndex(1)
        destination=w.export_target().full_path
        started=time.perf_counter();w.export_button.click()
        wait(lambda:not w._running,'audio export '+name,120)
        QTest.qWait(80)
        ok=destination.is_file() and w.pages.currentWidget() is w.success_page
        check(name+' published',ok,w._last_failure)
        if not ok:raise RuntimeError(w._last_failure)
        meta=probe_audio(ffmpeg,destination)
        check(name+' audio duration',abs(float(meta['format']['duration'])-4.5)<.1,meta)
        check(name+' bypass video and subtitles',w._last_job.video_graph is None and not w._last_job.ass_path and
              w._last_job.preview_callback is None and not w._last_job.export_project_data)
        result['exports'].append(dict(format=name,wall_seconds=time.perf_counter()-started,
            file=str(destination),metadata=meta,receipt=w._last_job.completion_metadata))
        _capture(window,output/('audio-success-'+name+'.png'));save()
    w._return_to_settings()
    w.filename.setText('已取消 音訊');destination=w.export_target().full_path
    w.export_button.click();w._cancel_export()
    wait(lambda:not w._running,'cancelled audio')
    check('cancel does not publish',not destination.exists())
    w._return_to_settings()
    for track in page.project.audio_tracks:track.muted=True
    w.filename.setText('全軌靜音');destination=w.export_target().full_path;w.export_button.click()
    check('all muted explains failure',w.pages.currentWidget() is w.failure_page and not destination.exists(),w._last_failure)
    for track in page.project.audio_tracks:track.muted=False
    w._return_to_settings();w.output_kind.setCurrentIndex(w.output_kind.findData('video'))
    # Original formats still go through their real, unmodified video pipeline.
    for name in ('mp4','mov','mkv','webm'):
        w._return_to_settings();w.filename.setText('工作台 影片 '+name)
        w.extension.setCurrentIndex(w.extension.findData(name))
        w.codec.setCurrentIndex(w.codec.findData('av1' if name=='webm' else 'h264'))
        encoder='libsvtav1' if name=='webm' else 'libx264'
        w.encoder.setCurrentIndex(w.encoder.findData(encoder))
        destination=w.export_target().full_path;started=time.perf_counter()
        w.export_button.click();wait(lambda:not w._running,'video export '+name,180)
        ok=destination.is_file() and w.pages.currentWidget() is w.success_page
        check(name+' video published',ok,w._last_failure)
        if not ok:raise RuntimeError(w._last_failure)
        result['exports'].append(dict(format=name,wall_seconds=time.perf_counter()-started,
            file=str(destination),receipt=w._last_job.completion_metadata))
        save()
    result['completed']=True;result['passed']=all(r['passed'] for r in result['checks']);save()
    page._close_export_workspace()
