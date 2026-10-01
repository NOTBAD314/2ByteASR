"""Isolated real-player workflow checks; does not claim human listening."""
from __future__ import annotations
import json, sys, time, traceback

def start(window, output):
    from PySide6.QtCore import QObject, QTimer
    from PySide6.QtWidgets import QLabel
    from .studio_acceptance_audit import require
    from .build_identity import load_build_identity
    from .studio_project import save_project, load_project
    from .studio_design_target import DesignTarget
    from .studio_performance import performance_snapshot

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page=window.studio_page
            self.result=dict(runtime='frozen' if getattr(sys,'frozen',False) else 'source',
                executable=sys.executable, build=vars(load_build_identity()), checks={}, transitions=[], playback=[],
                scope='programmatic headed real mpv/Qt/WASAPI; no human listening or cloud design')
            self.started=time.monotonic(); self.waiting=0; self.phase_started=self.started
            self.steps=self.scenario()
            self.timer=QTimer(self); self.timer.setInterval(25);self.timer.timeout.connect(self.tick);self.timer.start()

        def check(self,key,value):
            self.result['checks'][key]=bool(value); require(value,key)

        def tick(self):
            try:
                now=time.monotonic()
                if now-self.started>240 or now-self.phase_started>25:
                    raise TimeoutError(f'workflow phase {self.result.get("phase_line")} timed out')
                if callable(self.waiting):
                    if not self.waiting():return
                elif now<self.waiting:return
                item=next(self.steps)
                self.result['phase_line']=self.steps.gi_frame.f_lineno
                (output/'progress.json').write_text(json.dumps(dict(phase=self.result['phase_line'],
                    checks=len(self.result['checks']),playback=len(self.result['playback']))),encoding='utf8')
                self.waiting=item if callable(item) else now+float(item)
                self.phase_started=now
            except StopIteration:self.finish()
            except Exception:
                self.result['error']=traceback.format_exc(); self.finish()

        def open(self,name):
            self.opened=False
            path=output/'projects'/name/(name+'.2byteproj') if name in {'A','B'} else output/(name+'.2byteproj')
            window.open_studio_project(path,on_ready=lambda *_:setattr(self,'opened',True))

        def subtitles_ready(self):
            c=self.page.video.controller
            if c is None or not getattr(c,'_subtitle_media_ready',False):return False
            return bool(c._studio_subtitle_sid is not None and c._studio_subtitle_path==str(self.page.video._ass_path))

        def shot(self,name):
            window.grab().save(str(output/(name+'-ui.png')))
            self.page.video.controller.screenshot_to_file(output/(name+'-native.png'))

        def scenario(self):
            p=self.page
            # Startup follows the normal entry point. No fixed delay releases readiness.
            yield lambda:p.project is not None and self.subtitles_ready()
            for turn in range(10):
                for name in ('A','B'):
                    p.show_project_hub(skip_dirty_guard=True)
                    self.open(name)
                    yield lambda:self.opened and self.subtitles_ready()
                    c=p.video.controller
                    diag=c.subtitle_diagnostics()
                    self.check(f'{name}_{turn}_paused',bool(c.get_property('pause')))
                    self.check(f'{name}_{turn}_single_ass',sum(t.get('type')=='sub' and t.get('external',False)
                        for t in diag.get('track-list',[]))==1)
                    text=__import__('pathlib').Path(c._studio_subtitle_path).read_text(encoding='utf8')
                    self.check(f'{name}_{turn}_own_text',f'WORKFLOW {name}' in text and f'WORKFLOW {"B" if name=="A" else "A"}' not in text)
                    self.result['transitions'].append(dict(project=name,turn=turn,subtitle=diag,
                        source_time=c.get_property('time-pos'),timeline_ms=p.timeline.playhead_ms))
                    if turn in (0,9):self.shot(f'{name}-{turn}')
            target=DesignTarget.capture(p)
            self.check('projected_design_selected',target is not None and '#' in target.cue.id)
            draft=p._theme_drafts();p._ai_request_generation+=1
            draft.begin(p._ai_request_generation,target.cue.id,provider='audit',model='fixture')
            selected=next(c for c in draft.request_project.cues if c.id==target.cue.id)
            self.check('design_frozen_timeline',selected.start_ms==target.cue.start_ms and selected.text==target.cue.text)
            draft.cancel()
            reopened=load_project(save_project(p.project,output/'saved-B.2byteproj'))
            self.check('canonical_saved_unchanged',reopened.cues==p.project.cues)
            p.show_project_hub(skip_dirty_guard=True)
            # The general acceptance harness disables cover generation; this
            # scenario explicitly enables it and waits for actual output first.
            yield lambda:all((output/'projects'/name/'preview/project-cover.jpg').is_file() for name in ('A','B'))
            p._rebuild_project_library()
            yield lambda:bool(getattr(p,'_library_cover_images',{}))
            first=len(p._library_cover_images)
            p._rebuild_project_library()
            yield lambda:bool(p._hub_card_widgets)
            window.grab().save(str(output/'library-ui.png'))
            self.check('library_reentry_cached',len(p._library_cover_images)>=first)

            self.open('dual')
            yield lambda:self.opened and self.subtitles_ready()
            # Same two media files and timings for every routing/rate case.
            for mode in ('V1','V2','both','both_A1_muted','V1_hidden'):
                p.video.set_paused(True)
                for track in p.project.video_tracks:
                    track.enabled = (track.id==mode) if mode in {'V1','V2'} else not (mode=='V1_hidden' and track.id=='V1')
                for track in p.project.audio_tracks:
                    track.muted = (track.id=='A1' and mode in {'V2','both_A1_muted'}) or (track.id=='A2' and mode=='V1')
                for rate in (1.,1.5,2.,4.):
                    p._seek(3.);p._set_speed(rate)
                    yield lambda:p.video.controller._subtitle_media_ready
                    capture=f'audio-{mode}-{rate:g}x'.replace('.', 'p')
                    p.audio_engine.capture_pcm(capture,True)
                    yield lambda:(output/(capture+'.started')).is_file()
                    p._toggle_playback()
                    yield lambda:not p.video._paused
                    yield 1.2  # measurement window, never a production readiness workaround
                    row=performance_snapshot(p,compact=True)
                    row.update(mode=mode,rate=rate)
                    self.result['playback'].append(row)
                    p.video.set_paused(True)
                    p.audio_engine.capture_pcm(capture,False)
                    yield lambda:(output/(capture+'.json')).is_file()
                    self.check(f'{mode}_{rate:g}_transport_rate',p._shuttle_speed==rate)
                    expected={'A1'} if mode=='V1' else {'A2'} if mode in {'V2','both_A1_muted'} else {'A1','A2'}
                    audio=row['audio']
                    self.check(f'{mode}_{rate:g}_actual_routes',
                        {s.get('audio_track_id') or s['track_id'] for s in audio.get('active_sources',[])}==expected)
                    self.check(f'{mode}_{rate:g}_actual_rate',abs(audio.get('effective_rate',0)-rate)<.001)
                    self.check(f'{mode}_{rate:g}_pcm_submitted',(output/(capture+'.pcm')).stat().st_size>0)
                    if mode in {'V2','V1_hidden'}:
                        self.check(f'{mode}_{rate:g}_no_duplicate_base',not p.video_compositor._layers)
            self.shot('final-dual')

        def finish(self):
            self.timer.stop()
            self.result['elapsed_seconds']=round(time.monotonic()-self.started,2)
            self.result['passed']=not self.result.get('error') and all(self.result['checks'].values())
            (output/'result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
            self.page.undo_stack.setClean(); self.page._recovered_autosave_pending=False
            window.close()
    window._workflow_audit=Audit()
