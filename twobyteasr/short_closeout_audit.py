"""Opt-in four-minute V1/V2/Web regression; isolated by the audit entry gate."""
from __future__ import annotations
import json
import os
from pathlib import Path
import time
import traceback


def start_short_closeout(window, output):
    from PySide6.QtCore import QObject,QTimer,Qt
    from PySide6.QtTest import QTest
    from .studio_performance import performance_snapshot
    from .visual_snapshot import build_visual_cue_snapshot
    from .build_identity import load_build_identity

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page=window.studio_page
            self.started=time.monotonic();self.last=self.started;self.sample_at=0.
            self.phase='setup';self.phase_started=self.started
            self.smoke=os.environ.get('TWOBYTEASR_SHORT_SMOKE')=='1'
            self.result=dict(build=vars(load_build_identity()),checks={},samples=[],operations=[],shadow=[],
                real_media=self.page.project.media.path,provider_requests_in_this_audit=0,
                note='Real recording; one explicit regression caption; device PCM telemetry is not an external recording.')
            self.gaps=[];self.sequence=self.run();self.waiting=0.
            self.timer=QTimer(self);self.timer.setTimerType(Qt.TimerType.PreciseTimer)
            self.timer.timeout.connect(self.tick);self.timer.start(25)
        def mark(self,name):
            self.phase=name;self.phase_started=time.monotonic()
            self.result['operations'].append(dict(name=name,at=self.phase_started,snapshot=performance_snapshot(self.page,compact=True)))
        def check(self,name,condition):self.result['checks'][name]=bool(condition)
        def tick(self):
            now=time.monotonic()
            self.gaps.append(dict(phase=self.phase,ms=(now-self.last)*1000));self.last=now
            try:
                if now-self.started>270:raise TimeoutError('short audit hard deadline')
                if now-self.sample_at>=.5:
                    self.sample_at=now
                    state=performance_snapshot(self.page,compact=True)
                    self.result['samples'].append(dict(phase=self.phase,at=now,phase_age=now-self.phase_started,**state))
                if callable(self.waiting):
                    if not self.waiting():return
                elif now<self.waiting:return
                value=next(self.sequence)
                self.waiting=value if callable(value) else time.monotonic()+float(value)
            except StopIteration:self.finish()
            except Exception:
                self.result['error']=traceback.format_exc();self.finish()
        def native(self,name):
            self.page.video.controller.screenshot_to_file(output/(name+'.png'))
        def run(self):
            page=self.page
            yield 1.
            page.video.set_paused(True);page.select_cue('p0-cue');page._seek(10.)
            yield 1.
            for graph in (() if self.smoke else (False,True)):
                if graph:
                    from .visual_design_graph import VisualDesignGraph
                    payload=page._base_recipe_for_style(page.project.styles[0]).to_dict()
                    payload['engine']='remotion'
                    payload['visualGraph']=VisualDesignGraph(name='Shadow runtime fixture').to_dict()
                    from .style_recipe import StyleRecipe
                    page._apply_style_recipe('p0-cue',StyleRecipe.from_dict(payload))
                    yield .5
                page._appearance_rows['shadow'].set_expanded(True)
                for name,text,key in [('style_shadow_distance','17','offset_x'),('style_shadow_blur','13','blur_radius'),('style_shadow_opacity','71','opacity')]:
                    control=getattr(page,name);control.setFocus();control.lineEdit().selectAll()
                    QTest.keyClicks(control.lineEdit(),text)
                    page._load_style_inspector()
                    QTest.keyClick(control.lineEdit(),Qt.Key.Key_Return)
                    yield .4
                    shadow=build_visual_cue_snapshot(page.project,'p0-cue').shadow
                    self.check(f'shadow_{graph}_{key}',control.value()==float(text))
                    self.result['shadow'].append(dict(graph=graph,field=key,shadow=shadow))
                    self.native(f'shadow-{graph}-{key}')
                page.undo_stack.undo();yield .3
                page.undo_stack.redo();yield .3
                self.check(f'shadow_{graph}_redo',page.style_shadow_opacity.value()==71)
            page._seek(20.);yield .4
            self.mark('v1');page._toggle_playback();yield 5. if self.smoke else 20.
            v2=page.project.video_tracks[1].id
            self.mark('enable_v2');page._video_track_action(v2,'enabled');page._video_track_action(v2,'muted');yield 5. if self.smoke else 20.
            self.mark('pause_seek');page._toggle_playback();yield .4
            page._seek(180.);yield 1.
            page._toggle_playback();yield 8.
            self.mark('v2_hidden');page._video_track_action(v2,'enabled');yield 5.
            self.mark('v2_visible');page._video_track_action(v2,'enabled');yield 8.
            # The generated polar theme is used if the one authorized request
            # succeeded. Otherwise the launcher provides a labelled saved theme.
            self.mark('ai_preview')
            page._open_ai_design_from_style()
            theme=json.loads((output/'theme.json').read_text(encoding='utf8'))
            drafts=page._theme_drafts();drafts.adopt(theme,'p0-cue',label='短流程预览',auto_apply=False)
            yield lambda:drafts.phase in {'READY','FAILED','CANCELLED'}
            self.check('ai_preview_valid',drafts.is_valid())
            self.result['draft_preview']=drafts.diagnostics()
            window.grab().save(str(output/'ai-preview-controls.png'))
            if page.video.playback_position_snapshot().paused:page._toggle_playback()
            self.mark('dual_with_preview');yield 20. if self.smoke else 150.
            self.native('dual-with-preview-native')
            self.check('ai_preview_animation',len(getattr(page,'_storyboard_frame_times',[]))>20)
            self.result['preview_frames']=len(getattr(page,'_storyboard_frame_times',[]))
        def finish(self):
            self.timer.stop();self.result['elapsed_seconds']=time.monotonic()-self.started
            summary={}
            for phase in ('v1','enable_v2','v2_visible','dual_with_preview'):
                rows=[r for r in self.result['samples'] if r['phase']==phase and r['phase_age']>2]
                gaps=[r['ms'] for r in self.gaps if r['phase']==phase]
                stale=[max(0.,r['at']-float((r['audio'] or {}).get('last_pcm_write_monotonic',0))) for r in rows]
                buffers=[(r['audio'] or {}).get('buffer_bytes',0) for r in rows]
                frames=[d.get('frame_age_ms') for r in rows for d in r['decoders'].values() if d.get('frame_age_ms') is not None]
                silent=[r for r in rows if (r['audio'] or {}).get('sink_state')!='ActiveState' or not (r['audio'] or {}).get('sink_consumed_bytes')]
                summary[phase]=dict(samples=len(rows),gui_max_ms=max(gaps,default=0),
                    pcm_write_age_max_s=max(stale,default=0),buffer_min=min(buffers,default=0),
                    follower_frame_age_max_ms=max(frames,default=0),silent_samples=len(silent),
                    endpoint_pids=sorted({(r['audio'] or {}).get('endpoint_pid',0) for r in rows}),
                    underruns_max=max(((r['audio'] or {}).get('underruns',0) for r in rows),default=0))
                self.check(phase+'_audio_continuous',bool(rows) and not silent and max(stale,default=9)<2.)
                self.check(phase+'_no_seconds_freeze',bool(rows) and max(gaps,default=9999)<2000 and max(frames,default=0)<2000)
            self.result['summary']=summary
            self.page._stop_storyboard_animation();self.page.video.set_paused(True)
            self.page.undo_stack.setClean();self.page.close_ready_signal.connect(self.closed)
            (output/'short-closeout-acceptance.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),encoding='utf8')
            window.close()
        def closed(self,profile):
            self.result['close_profile']=dict(profile)
            self.check('close_audio_idle',profile.get('audio_idle') is True)
            (output/'short-closeout-acceptance.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),encoding='utf8')
    window._short_closeout_audit=Audit()
