"""Explicit normal-window sync acceptance on an owned project copy."""
import copy
import json
import time
import traceback
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .studio_edit_sequence import projected_cues
    from .studio_project import load_project
    from .studio_subtitle_export import export_subtitle_artifacts, SubtitleExportOptions, verify_subtitle_artifact
    spec=json.loads((output/'input.json').read_text('utf-8'))
    result=dict(passed=False,checks=[],observations=[],identity=load_build_identity().to_dict(),
                scope='actual normal-window playback/seek/pixels; original project copy; no inference')
    page=window.studio_page
    original=load_project(spec['project'])
    expected=[(c.id,c.start_ms,c.end_ms,c.text,c.speaker_id) for c in projected_cues(original)]

    def check(name, value, detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail))
        if not value:raise AssertionError(name)

    def observation():
        clock=page.video.playback_position_snapshot();controller=page.video.controller
        value=dict(timeline_ms=page.timeline.playhead_ms,mpv_time_s=controller.observed_property('time-pos',None),
            mpv_path=controller.observed_property('path',None),mpv_pause=controller.observed_property('pause',None),
            seeking=clock.seeking,exact=clock.exact_seek_pending,clock_ms=clock.presentation_media_ms,
            source_domain=getattr(page.video,'_playback_time_domain',None),
            clip_id=page._active_video_preview_clip_id)
        result['last_observation']=value
        return value

    def seek(ms):
        box=page.timecode_input;box.setFocus();QTest.keyClick(box,Qt.Key_A,Qt.ControlModifier)
        seconds,millis=divmod(ms,1000);minutes,seconds=divmod(seconds,60);hours,minutes=divmod(minutes,60)
        QTest.keyClicks(box,f'{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}');QTest.keyClick(box,Qt.Key_Return)

    def settled(ms):
        value=observation()
        trace=getattr(page.video,'_active_seek_trace',{}) or {}
        target=trace.get('decoder_target_seconds',trace.get('target_seconds'))
        return (value['mpv_pause'] is True and not value['seeking'] and not value['exact']
                and abs(value['timeline_ms']-ms)<50 and isinstance(value['mpv_time_s'],(int,float))
                and isinstance(target,(int,float)) and abs(value['mpv_time_s']-target)<.08)

    def steps():
        window.showNormal();window.resize(1440,900)
        window.open_studio_project(spec['project'],mode='edit',source='timeline_sync_audit')
        yield lambda:page.project is not None and page._readiness.ready and not page._readiness.active and page.video.controller is not None
        yield 1.
        check('subtitle list retains every saved cue',page.cue_model.rowCount()==len(original.cues),page.cue_model.rowCount())
        if observation()['mpv_pause'] is not True:
            QTest.mouseClick(page.play_button,Qt.LeftButton)
            yield lambda:observation()['mpv_pause'] is True
        for i,ms in enumerate(spec['positions_ms']):
            seek(ms);yield lambda ms=ms:settled(ms)
            yield .25
            value=observation();value['requested_ms']=ms
            clip=next(c for t in original.video_tracks if t.id=='V1' for c in t.clips
                      if c.timeline_in_ms<=value['timeline_ms']<c.timeline_out_ms)
            source_s=(clip.source_in_ms+(value['timeline_ms']-clip.timeline_in_ms)*clip.playback_rate)/1000
            value['independent_clip_source_s']=source_s
            check('actual decoder uses clip content time '+str(ms),abs(value['mpv_time_s']-source_s)<.1,value.copy())
            value['seek_trace']=dict(getattr(page.video,'_active_seek_trace',{}) or {})
            value['subtitle_pixels']=page.subtitle_visibility_trace(reason='timeline_sync_audit')
            wanted={c.id for c in projected_cues(page.project) if c.start_ms<=value['timeline_ms']<c.end_ms}
            visible=value['subtitle_pixels']
            check('subtitle hit time '+str(ms),set(visible.get('expected_cue_ids',()))==wanted,visible)
            if wanted:
                check('actual subtitle pixels '+str(ms),set(visible.get('rendered_cue_ids',()))==wanted,visible)
            result['observations'].append(value)
            if i in {0,6,7,13,14,16}:
                _capture(window,output/f'seek-{ms}.png')
                page.video.controller.screenshot_to_file(output/f'mpv-{ms}.png')
        for ms in spec['play_from_ms']:
            seek(ms);yield lambda ms=ms:settled(ms)
            QTest.mouseClick(page.play_button,Qt.LeftButton)
            yield lambda:observation()['mpv_pause'] is False
            began=time.monotonic()
            yield lambda ms=ms:observation()['timeline_ms']>ms+1700
            after=observation()
            after['elapsed_wall_s']=time.monotonic()-began
            after['audio']=page.audio_engine.telemetry_snapshot()
            check('continuous play crosses cut '+str(ms),after['timeline_ms']>ms+1500,after)
            QTest.mouseClick(page.play_button,Qt.LeftButton)
            yield lambda:observation()['mpv_pause'] is True
            yield .25
        page.save()
        saved=load_project(spec['project'])
        check('save/reopen does not map cues twice',expected==[(c.id,c.start_ms,c.end_ms,c.text,c.speaker_id) for c in projected_cues(saved)])
        artifacts=export_subtitle_artifacts(saved,output/'subtitles','verified',
            SubtitleExportOptions(formats=frozenset({'srt','json'}),speaker_mode='both'))
        for artifact in artifacts:
            view=copy.deepcopy(saved)
            if artifact.speaker_id:view.cues=[c for c in view.cues if c.speaker_id==artifact.speaker_id]
            check('export parser '+str(artifact.path),verify_subtitle_artifact(artifact,view).valid)
        result['export_count']=len(artifacts)
        result['passed']=True

    iterator=steps();state=dict(wait=None,deadline=0.,until=0.)
    timer=QTimer(window);timer.setInterval(50)
    def save():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf-8')
    def finish():
        timer.stop();save();window.close();QTimer.singleShot(500,QApplication.instance().quit)
    def tick():
        try:
            if state['wait'] is not None:
                if state['wait']():state['wait']=None
                elif time.monotonic()>state['deadline']:raise TimeoutError('Actual transport/pixels did not settle')
                else:return
            if time.monotonic()<state['until']:return
            value=next(iterator)
            if callable(value):state.update(wait=value,deadline=time.monotonic()+45)
            else:state['until']=time.monotonic()+float(value or 0)
        except StopIteration:finish()
        except BaseException:
            result['error']=traceback.format_exc()
            try:_capture(window,output/'failure.png')
            except Exception:pass
            finish()
    def shutdown():result['gui_shutdown']=True;save()
    QApplication.instance().aboutToQuit.connect(shutdown)
    window._timeline_sync_audit_timer=timer;timer.timeout.connect(tick);timer.start()
