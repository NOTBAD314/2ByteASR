"""Opt-in continuous production audio capture on an isolated test project."""
import json
import os
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QObject, QTimer
    from .build_identity import load_build_identity
    from .studio_performance import performance_snapshot
    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page=window.studio_page
            self.result=dict(build=vars(load_build_identity()),executable=sys.executable,cases=[],
                capture='QAudioSink callback PCM before device; no system recording or human listening')
            self.started=time.monotonic();self.waiting=0.;self.phase_started=self.started
            self.steps=self.scenario();self.timer=QTimer(self);self.timer.setInterval(50)
            self.timer.timeout.connect(self.tick);self.timer.start()

        def tick(self):
            try:
                now=time.monotonic()
                if now-self.phase_started>35:raise TimeoutError('Audio readiness/phase timeout')
                if callable(self.waiting):
                    if not self.waiting():return
                elif now<self.waiting:return
                item=next(self.steps)
                self.waiting=item if callable(item) else now+float(item)
                self.phase_started=now
            except StopIteration:self.finish()
            except Exception:
                self.result['error']=traceback.format_exc()
                self.result['failure_snapshot']=performance_snapshot(self.page,compact=True)
                self.finish()

        def scenario(self):
            p=self.page
            yield lambda:p.project is not None and p.video.controller is not None and p.video.controller._subtitle_media_ready
            c=p.video.controller
            self.result['mpv']={key:c.get_property(key) for key in ('mpv-version','ffmpeg-version','aid','af')}
            self.result['mpv_executable']=str(c.executable)
            specs=json.loads(os.environ['TWOBYTEASR_AUDIO_CASES'])
            for n,spec in enumerate(specs):
                mode,rate,seconds=spec
                # Visibility-only reproduces the user's saved track state:
                # the other video is hidden while both audio lanes stay live.
                visual_mode=str(mode).removesuffix('-visible')
                p.video.set_paused(True)
                for track in p.project.video_tracks:
                    want=visual_mode=='both' or visual_mode==track.id
                    if track.enabled!=want:p._video_track_action(track.id,'enabled')
                for track in p.project.audio_tracks:
                    want=(mode=='V1' and track.id=='A2') or (mode=='V2' and track.id=='A1')
                    if track.muted!=want:p._audio_track_action(track.id,'muted')
                p._seek(0.);p._set_speed(float(rate))
                yield lambda:p.video.controller._subtitle_media_ready and p._playback_buffers_ready()
                # The endpoint deliberately rejects punctuation in capture
                # paths; retain the exact numeric rate in the receipt instead.
                name=f'case-{n}-{mode}-{rate:g}x'.replace('.', 'p')
                p.audio_engine.capture_pcm(name,True)
                yield lambda:(output/(name+'.started')).exists()
                row=dict(name=name,mode=mode,rate=rate,requested_seconds=seconds,samples=[])
                self.result['cases'].append(row)
                p._toggle_playback()
                yield lambda:not p.video._paused
                began=time.monotonic()
                while time.monotonic()-began<float(seconds):
                    snap=performance_snapshot(p,compact=True)
                    snap.update(wall_seconds=time.monotonic()-began,timeline_ms=p.timeline.playhead_ms,
                        tracks=[dict(id=t.id,enabled=t.enabled,muted=t.muted,soloed=getattr(t,'soloed',False))
                                for t in (*p.project.video_tracks,*p.project.audio_tracks)])
                    row['samples'].append(snap)
                    (output/'progress.json').write_text(json.dumps(dict(case=name,seconds=snap['wall_seconds'],
                        source_ms=snap['audio'].get('estimated_source_ms'),
                        generation=snap['audio'].get('source_generation'),underruns=snap['audio'].get('underruns'))),encoding='utf8')
                    if p.video._paused:
                        row['natural_eof']=p.timeline.playhead_ms>=p.project.media.duration_ms-300
                        row['ended_early']=not row['natural_eof']
                        if row['natural_eof']:
                            drain_until=time.monotonic()+2.5
                            while time.monotonic()<drain_until and p.audio_engine.telemetry_snapshot().get('state') not in {'DRAINED','IDLE'}:
                                yield .1
                        break
                    yield 1.
                row['continuous_wall_seconds']=time.monotonic()-began
                row['final_snapshot']=performance_snapshot(p,compact=True)
                p.video.set_paused(True);p.audio_engine.capture_pcm(name,False)
                yield lambda:(output/(name+'.json')).is_file()
                row['pcm_bytes']=(output/(name+'.pcm')).stat().st_size
                stable=[s['audio'] for s in row['samples'][2:] if s['audio'].get('state')=='SYNCED']
                row['checks']=dict(nonempty_pcm=row['pcm_bytes']>48000,continuous_coverage=not row.get('ended_early',False)
                    and (row.get('natural_eof') or row['continuous_wall_seconds']>=seconds),
                    expected_contributors=bool(stable) and all(len(s.get('active_sources',[]))==(2 if mode=='both' or str(mode).endswith('-visible') else 1) for s in stable),
                    expected_rate=bool(stable) and all(abs(s.get('effective_rate',0)-rate)<.001 for s in stable),
                    no_decoder_error=all(not s.get('decoder_error') for s in stable),
                    stable_decoder_generation=len({s.get('source_generation') for s in stable})==1,
                    no_underrun=all(s.get('underruns')==0 for s in stable))
                c.screenshot_to_file(output/(name+'-native.png'))
                window.grab().save(str(output/(name+'-ui.png')))
                self.save()
            if os.environ.get('TWOBYTEASR_AUDIO_TRANSITIONS')=='1':
                self.result['transitions']=[]
                p.video.set_paused(True);p._seek(0);p._set_speed(1.)
                yield lambda:p._playback_buffers_ready()
                p._toggle_playback()
                yield lambda:not p.video._paused
                for rate in (1.,2.,1.,4.,1.):
                    p._set_speed(rate)
                    # Rate changes own their asynchronous pause/resume. A
                    # second toggle during that transition can cancel resume.
                    yield lambda:p._playback_buffers_ready() and not p.video._paused
                    yield 4.
                    self.result['transitions'].append(dict(action='rate',rate=rate,snapshot=performance_snapshot(p,compact=True)))
                p.video.set_paused(True);yield 1.;p._toggle_playback();yield 3.
                self.result['transitions'].append(dict(action='pause_resume',snapshot=performance_snapshot(p,compact=True)))
                for ms in (20000,60000):
                    p._seek(ms/1000.);yield 3.
                    self.result['transitions'].append(dict(action='seek',target_ms=ms,snapshot=performance_snapshot(p,compact=True)))
                for mode in ('V1','V2','both','mute-A1','mute-A2','both','solo-A1','solo-A2','both'):
                    for track in p.project.video_tracks:
                        want=mode not in {'V1','V2'} or track.id==mode
                        if track.enabled!=want:p._video_track_action(track.id,'enabled')
                    for track in p.project.audio_tracks:
                        mute=(mode in {'V1','mute-A2'} and track.id=='A2') or (mode in {'V2','mute-A1'} and track.id=='A1')
                        if track.muted!=mute:p._audio_track_action(track.id,'muted')
                        solo=mode=='solo-'+track.id
                        if track.soloed!=solo:p._audio_track_action(track.id,'solo')
                    yield 3.
                    snap=performance_snapshot(p,compact=True)
                    snap['tracks']=[dict(id=t.id,enabled=t.enabled,muted=t.muted,soloed=getattr(t,'soloed',False))
                                    for t in (*p.project.video_tracks,*p.project.audio_tracks)]
                    self.result['transitions'].append(dict(action=mode,snapshot=snap))
                p.video.set_paused(True);self.save()

        def save(self):
            (output/'result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),encoding='utf8')

        def finish(self):
            self.timer.stop();self.result['elapsed_seconds']=time.monotonic()-self.started
            self.result['completed']=not self.result.get('error');self.save()
            self.page.undo_stack.setClean();self.page._recovered_autosave_pending=False
            window.close()
    window._sustained_audio_audit=Audit()
