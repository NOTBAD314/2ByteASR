"""Normal-entry proof of disabled-V1 output, linked gap edits and audio fades."""
import copy
import json
import os
import sys
import time
import traceback
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QObject,QTimer
    from .build_identity import load_build_identity
    from .audio_graph import capture_audio_graph,preview_audio_layers
    from .studio_clip_edit import clip_edit_command
    from .studio_track_delete import DeleteTrackCommand
    from .studio_project import AudioTrack,AudioClip
    from .studio_runtime_state import DirtyDomain as D,state_for
    from .studio_transitions import set_transition
    from .audio_export import audio_mix_arguments
    from .audio_engine import build_audio_mix_command
    from .audio_engine import studio_ffmpeg_path
    from .processes import run_hidden_subprocess
    from types import SimpleNamespace
    import numpy as np

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page=window.studio_page;self.output=Path(output)
            self.result=dict(passed=False,checks={},samples=[],identity=load_build_identity().to_dict(),
                executable=sys.executable,capture='Actual QAudioSink callback PCM before device; no system loopback or human listening')
            self.steps=self.scenario();self.waiting=0.;self.phase_started=time.monotonic()
            self.timer=QTimer(self);self.timer.setInterval(30);self.timer.timeout.connect(self.tick);self.timer.start()

        def save(self):
            (self.output/'audio-workflow-result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),'utf8')

        def check(self,name,value):
            self.result['checks'][name]=bool(value);self.save()
            if not value:raise AssertionError(name)

        def tick(self):
            try:
                now=time.monotonic()
                if now-self.phase_started>45:raise TimeoutError('Audio workflow phase timed out')
                if callable(self.waiting):
                    if not self.waiting():return
                elif now<self.waiting:return
                step=next(self.steps);self.waiting=step if callable(step) else now+float(step);self.phase_started=now
            except StopIteration:self.result['passed']=True;self.finish()
            except Exception:self.result['error']=traceback.format_exc();self.finish()

        def sample(self,name,position,rate,seconds,owners):
            p=self.page;p.video.set_paused(True);p._seek(position/1000.)
            yield lambda:not p.video._playback_clock.exact_seek_pending
            p._set_speed(rate);yield .3
            p.audio_engine.capture_pcm(name,True)
            yield lambda:(self.output/(name+'.started')).exists()
            p.video.set_paused(False)
            row=dict(name=name,position_ms=position,rate=rate,seconds=seconds,expected_owners=sorted(owners),snapshots=[])
            self.result['samples'].append(row)
            until=time.monotonic()+seconds
            while time.monotonic()<until:
                row['snapshots'].append(dict(project_ms=p.timeline.playhead_ms,request=copy.deepcopy(p.audio_engine._last_payload),
                    telemetry=copy.deepcopy(p.audio_engine.telemetry_snapshot())))
                yield .1
            p.video.set_paused(True);p.audio_engine.capture_pcm(name,False)
            yield lambda:(self.output/(name+'.json')).exists()
            row['bytes']=(self.output/(name+'.pcm')).stat().st_size
            stable=row['snapshots'][3:]
            actual=[{x.get('track_id') for x in snap['telemetry'].get('active_sources',[]) if x.get('source_path')} for snap in stable]
            self.check(name+' contributors',bool(actual) and all(value==owners for value in actual))
            self.check(name+' output samples',row['bytes']>1000 if owners else row['bytes']==0)
            self.check(name+' never V1',all(not any(x.get('track_id')=='V1' for x in snap['telemetry'].get('active_sources',[])) for snap in stable))
            self.check(name+' mpv audio closed',p.video.controller.get_property('aid') in (None,False,'no'))
            window.grab().save(str(self.output/(name+'-ui.png')));self.save()

        def reopen(self,path):
            p=self.page;p.video.set_paused(True);p.undo_stack.setClean();p.show_project_hub(skip_dirty_guard=True)
            yield .2
            ready=[];window.open_studio_project(path,on_ready=lambda *_:ready.append(True))
            yield lambda:bool(ready) and p._readiness.ready
            p.volume_slider.setValue(35);yield .2

        def export(self,name,background):
            p=self.page;ffmpeg=Path(studio_ffmpeg_path());graph=capture_audio_graph(p.project)
            movie=self.output/(name+'.mkv');job=SimpleNamespace(start_seconds=0.,duration_seconds=12.,video_graph={'duration_ms':12000})
            run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-f','lavfi','-i','color=s=160x90:r=10:d=12',
                *audio_mix_arguments(ffmpeg,job,graph['segments']),'-map','0:v','-c:v','ffv1','-t','12',str(movie)],
                purpose='actual disabled owner audio export',check=True,timeout=25)
            pcm=run_hidden_subprocess([str(ffmpeg),'-v','error','-i',str(movie),'-vn','-ac','2','-ar','48000','-f','s16le','pipe:1'],
                purpose='actual final movie audio samples',capture_output=True,check=True,timeout=15).stdout
            values=np.frombuffer(pcm,'<i2').reshape(-1,2).astype(float);gap=values[round(4.3*48000):round(5.7*48000)]
            rms=float(np.sqrt(np.mean(gap**2)))
            self.result.setdefault('exports',[]).append(dict(path=str(movie),samples=len(values),gap_rms=rms,graph=graph))
            self.check(name+' exported gap',rms>1000 if background else rms==0)
            self.check(name+' no V1 owner',all(x['track_id']!='V1' for x in graph['segments']))

        def scenario(self):
            p=self.page
            yield lambda:p.project is not None and p._readiness.ready and p.video.controller._subtitle_media_ready
            p.video.set_paused(True);p.volume_slider.setValue(35)
            if not p.project.video_tracks[0].locked:p._video_track_action('V1','locked')
            self.original_v1=copy.deepcopy(p.project.video_tracks[0])
            self.check('fixture V1 disabled locked',not p.project.video_tracks[0].enabled and p.project.video_tracks[0].locked)
            for point in (4000,6000):
                track=p.project.video_tracks[1];clip=next(c for c in track.clips if c.timeline_in_ms<point<c.timeline_out_ms)
                p.undo_stack.push(clip_edit_command(p.project,track.id,'split',clip_id=clip.id,time_ms=point,page=p))
                yield .2
            middle=p.project.video_tracks[1].clips[1]
            p.undo_stack.push(DeleteTrackCommand(p.project,'video','V2',p,clip_ids=[middle.id]));yield .5
            audio=next(t for t in p.project.audio_tracks if t.id=='A2')
            self.check('normal deletion cuts linked A2',[(c.timeline_in_ms,c.timeline_out_ms) for c in audio.clips]==[(0,4000),(6000,12000)])
            yield from self.sample('gap-1x',4200,1.,.9,set())
            yield from self.sample('gap-2x',4200,2.,.65,set())
            p.undo_stack.undo();yield .4
            yield from self.sample('undo-v2',4200,1.,.8,{'V2'})
            p.undo_stack.redo();yield .4
            yield from self.sample('redo-gap',4200,1.,.8,set())
            self.check('V1 remains byte equal',p.project.video_tracks[0]==self.original_v1)
            with state_for(p.project).transaction(p.project,action_id='independent audio fixture',dirty=D.AUDIO_TRACKS|D.TIMELINE_INDEX|D.TIMELINE_PIXELS|D.AUTOSAVE):
                p.project.audio_tracks.append(AudioTrack('BGM','Independent same-source music',clips=[AudioClip('bgm-instance',p.project.media_pool[0].asset_id,source_out_ms=12000,timeline_out_ms=12000)]))
            p.timeline.reindex_project()
            yield from self.sample('background-gap',4200,1.,.8,{'BGM'})
            self.export('background-export',True)
            p.save();saved=Path(p.project_path)
            yield from self.reopen(saved)
            self.check('disabled lock survives reopen',not p.project.video_tracks[0].enabled and p.project.video_tracks[0].locked)
            yield from self.sample('reopen-background',4200,2.,.65,{'BGM'})
            p._audio_track_action('BGM','muted');yield .3
            self.export('silent-export',False)
            yield from self.sample('muted-background-gap',4200,1.,.8,set())
            yield from self.reopen(self.output/'pristine.2byteproj')
            track=p.project.video_tracks[1];p.undo_stack.push(clip_edit_command(p.project,track.id,'split',clip_id=track.clips[0].id,time_ms=6000,page=p));yield .3
            audio=next(t for t in p.project.audio_tracks if t.id=='A2')
            record=set_transition(p.project,'audio','A2',audio.clips[0].id,audio.clips[1].id,duration_ms=500)
            p._refresh_audio_mix_only();p.timeline.update()
            yield from self.sample('equal-power-seam',5700,1.,1.,{'V2'})
            graph=capture_audio_graph(p.project);layers=preview_audio_layers(graph,5800)
            self.check('seam reads two actual instances',len(layers)==2 and len({x['audio_clip_id'] for x in layers})==2)
            ffmpeg=Path(studio_ffmpeg_path());command=build_audio_mix_command(ffmpeg,[{**x,'source_out_ms':x['source_ms']+400} for x in layers])
            ref=run_hidden_subprocess(command,purpose='actual transition preview reference',capture_output=True,check=True,timeout=15).stdout
            job=SimpleNamespace(start_seconds=5.8,duration_seconds=.4,video_graph={'duration_ms':12000});movie=self.output/'transition-export.mkv'
            run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-f','lavfi','-i','color=s=160x90:r=10:d=0.4',*audio_mix_arguments(ffmpeg,job,graph['segments']),'-map','0:v','-c:v','ffv1','-t','0.4',str(movie)],purpose='actual transition final movie',check=True,timeout=15)
            actual=run_hidden_subprocess([str(ffmpeg),'-v','error','-i',str(movie),'-vn','-ac','2','-ar','48000','-f','s16le','pipe:1'],purpose='actual transition movie PCM',capture_output=True,check=True,timeout=15).stdout
            a=np.frombuffer(actual,'<i2');b=np.frombuffer(ref,'<i2')
            error=int(np.max(abs(a.astype(int)-b.astype(int)))) if a.shape==b.shape else None
            self.result['transition']=dict(record=record,movie=str(movie),max_sample_error=error,preview_samples=len(b),export_samples=len(a))
            self.check('transition preview export sample agreement',error is not None and error<=2)
            p.save();saved=Path(p.project_path);yield from self.reopen(saved)
            self.check('audio transition survives reopen',p.project.studio_state.get('clip_transitions')==[record])
            self.save()

        def finish(self):
            self.timer.stop();self.save();self.page.video.set_paused(True);self.page.undo_stack.setClean();self.page._recovered_autosave_pending=False
            QTimer.singleShot(150,window.close)
    window._audio_output_workflow_audit=Audit()
