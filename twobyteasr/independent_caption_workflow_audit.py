"""Opt-in real Q/W, caption lock, save/reopen and project-clock bitmap audit."""
from __future__ import annotations
import copy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QObject,QTimer,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QMessageBox
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .studio_caption_timeline import KEY,ensure_independent_captions
    from .studio_edit_sequence import projected_cues,sequence_of
    from .studio_project import load_project
    from .studio_track_header import button_rect
    from .studio_subtitle_export import SubtitleExportOptions,export_subtitle_artifacts,verify_subtitle_artifact
    output=Path(output).resolve()
    plan=json.loads((output/'caption-plan.json').read_text('utf8'))

    class Audit(QObject):
        def __init__(self):
            super().__init__(window);self.page=window.studio_page;self.phase='initial-ready';self.waiting=0;self.busy=False
            self.result={'passed':False,'checks':[],'screenshots':[],'visibility':[],'exports':[],
                         'identity':load_build_identity().to_dict(),'pid':os.getpid(),'executable':sys.executable,
                         'scope':'Real normal Studio shortcuts and bitmap output; synthetic isolated V1/V2 test media; no model inference'}
            self.steps=self.run();self.deadline=time.monotonic()+100
            self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(50)

        def check(self,name,value,detail=None):
            self.result['checks'].append({'name':name,'passed':bool(value),'detail':detail})
            (output/'caption-progress.json').write_text(json.dumps({'phase':self.phase,'checks':self.result['checks']},ensure_ascii=False,indent=2),'utf8')
            if not value:raise AssertionError(name+': '+str(detail))

        def tick(self):
            if self.busy:return
            self.busy=True
            try:
                self.page=window.studio_page
                modal=QApplication.activeModalWidget()
                if isinstance(modal,QMessageBox):
                    message=modal.text()+' '+modal.informativeText();modal.reject();raise RuntimeError(message)
                now=time.monotonic()
                if now>self.deadline:raise TimeoutError('caption workflow phase '+self.phase)
                gate=getattr(self.page,'_readiness',None)
                if gate and gate.retry.isVisible():raise RuntimeError('Studio preparation failed: '+gate.label.text())
                if callable(self.waiting):
                    if not self.waiting():return
                elif now<self.waiting:return
                step=next(self.steps);self.waiting=step if callable(step) else now+float(step);self.deadline=time.monotonic()+100
            except StopIteration:self.result['passed']=True;self.finish()
            except Exception:
                self.result['error']=traceback.format_exc()
                try:self.shot('caption-failure')
                except Exception:self.result['capture_error']=traceback.format_exc()
                self.finish()
            finally:self.busy=False

        def ready(self):
            p=self.page
            return (p.project is not None and p._readiness.ready and not p._readiness.active
                and p.video.controller is not None and p.video.controller.running)

        def signature(self):return [asdict(c) for c in projected_cues(self.page.project)]

        def graph(self):
            return self.page.project.to_dict()['video_tracks'],self.page.project.to_dict()['audio_tracks']

        def seek(self,milliseconds):
            control=self.page.timecode_input;control.setFocus();QTest.keyClick(control,Qt.Key_A,Qt.ControlModifier)
            seconds,ms=divmod(int(milliseconds),1000);hours,seconds=divmod(seconds,3600);minutes,seconds=divmod(seconds,60)
            QTest.keyClicks(control,f'{hours:02d}:{minutes:02d}:{seconds:02d}.{ms:03d}');QTest.keyClick(control,Qt.Key_Return)

        def key(self,key,modifiers=Qt.NoModifier):
            self.page.timeline.setFocus();QTest.keyClick(self.page.timeline,key,modifiers)

        def visible(self,milliseconds,expected):
            p=self.page;trace=p.subtitle_visibility_trace(reason='independent_caption_audit_wait')
            controller=p.video.controller
            return (abs(p.timeline.playhead_ms-milliseconds)<=1 and controller.observed_property('pause',None) is True
                and trace.get('owner')=='caption_scene' and trace.get('visible') is True
                and set(trace.get('expected_cue_ids',()))==set(expected) and set(trace.get('rendered_cue_ids',()))==set(expected))

        def shot(self,name):
            target=output/(name+'.png');_capture(window,target)
            self.result['screenshots'].append({'path':str(target),'method':'actual HWND PrintWindow'})
            controller=self.page.video.controller
            if controller and controller.running:
                pixels=output/(name+'-mpv.png');controller.screenshot_to_file(pixels)
                self.result['screenshots'].append({'path':str(pixels),'method':'mpv screenshot-to-file window: video plus bitmap'})
            self.result['visibility'].append({'phase':self.phase,**self.page.subtitle_visibility_trace(reason=name)})

        def run(self):
            yield lambda:self.ready()
            working=output/'runtime-caption.2byteproj';working.write_bytes(Path(plan['project']).read_bytes())
            window.open_studio_project(working,mode='edit',source='independent-caption-workflow')
            yield lambda:self.ready() and Path(self.page.project_path).resolve()==working
            window.showNormal();window.resize(1500,930);window.raise_();window.activateWindow();yield .5
            p=self.page.project;self.page.video.set_paused(True);self.page.volume_slider.setValue(0)
            baseline=self.signature();baseline_graph=self.graph();v1=copy.deepcopy(p.video_tracks[0]);raw_asr=copy.deepcopy(p.asr_evidence)
            self.check('startup caption positions frozen exactly once',baseline==plan['raw_cues'])
            self.check('complete source archive retained',p.studio_state[KEY]['source_archive']==plan['raw_cues'])
            self.check('locked disabled V1 remains baseline',v1.locked and not v1.enabled and sequence_of(p).video_track_locked)
            self.phase='real-Q-at-12';self.seek(12000);yield lambda:abs(self.page.timeline.playhead_ms-12000)<=1;yield .3
            index=self.page.undo_stack.index();self.key(Qt.Key_Q);yield .5
            self.check('one Q keyboard transaction',self.page.undo_stack.index()==index+1)
            self.check('Q keeps locked V1 exactly',self.page.project.video_tracks[0]==v1)
            video=self.page.project.video_tracks[1]
            self.check('Q resolved one V2 range10to12',[(c.timeline_in_ms,c.timeline_out_ms,c.source_in_ms,c.source_out_ms) for c in video.clips]==[(0,10000,0,10000),(10000,18000,12000,20000)])
            group=next(g for g in self.page.project.av_track_groups if g.video_track_id==video.id)
            audio=next(a for a in self.page.project.audio_tracks if a.id==group.audio_track_id)
            self.check('linked A2 uses identical Q geometry',[(c.timeline_in_ms,c.timeline_out_ms,c.source_in_ms,c.source_out_ms) for c in audio.clips]==[(0,10000,0,10000),(10000,18000,12000,20000)])
            cues=self.page.project.cues
            self.check('inside caption removed','inside' not in {c.id for c in cues})
            self.check('after caption shifts once',next(c for c in cues if c.id=='after').start_ms==10500)
            self.check('repeated digits exact surviving tokens',[(c.text,c.start_ms,c.end_ms) for c in cues if c.text in {'11','44'}]==[('11',9000,9900),('44',10200,10900)])
            self.check('conservative boundary visibly needs review',self.page.project.studio_state['cue_statuses'].get('left')=='issue')
            q_cues=self.signature();q_graph=self.graph()
            self.phase='Q-single-undo';self.key(Qt.Key_Z,Qt.ControlModifier);yield .4
            self.check('single undo restores captions and linked graph',self.signature()==baseline and self.graph()==baseline_graph)
            self.key(Qt.Key_Z,Qt.ControlModifier|Qt.ShiftModifier);yield .4
            self.check('single redo restores complete Q',self.signature()==q_cues and self.graph()==q_graph)
            self.phase='Q-projectclock-pixels';self.seek(10700)
            active=[c.id for c in self.page.project.cues if c.start_ms<=10700<c.end_ms]
            yield lambda:self.visible(10700,active);yield .2;self.shot('caption-Q-multi-projectclock')
            self.check('native subtitle owner suppressed',not self.page.video._native_subtitle_visible)
            self.phase='single-caption-projectclock';self.seek(8500);yield lambda:self.visible(8500,['before']);yield .2
            self.shot('caption-single-projectclock')
            self.check('single ordinary caption uses one project-clock bitmap',self.page.subtitle_visibility_trace().get('owner')=='caption_scene')
            self.phase='real-W';self.seek(14000);yield lambda:abs(self.page.timeline.playhead_ms-14000)<=1;yield .2
            self.key(Qt.Key_W);yield .4
            self.check('W clips V2 remainder without moving V1',self.page.project.video_tracks[0]==v1 and self.page.project.video_tracks[1].clips[-1].timeline_out_ms==14000)
            self.key(Qt.Key_Z,Qt.ControlModifier);yield .4
            self.check('W undo restores prior Q transaction',self.signature()==q_cues and self.graph()==q_graph)
            self.phase='real-caption-lock';t=self.page.timeline
            rect=t._track_layout()[0]['S2'];button=button_rect('subtitle','lock',rect)
            QTest.mouseClick(t,Qt.LeftButton,Qt.NoModifier,button.center().toPoint());yield .2
            self.check('actual subtitle header lock engaged','S2' in t.locked_speakers)
            locked=copy.deepcopy([c for c in self.page.project.cues if c.speaker_id=='S2'])
            self.seek(11000);yield lambda:abs(self.page.timeline.playhead_ms-11000)<=1;yield .2
            self.key(Qt.Key_W);yield .4
            self.check('own locked captions stay unchanged',[c for c in self.page.project.cues if c.speaker_id=='S2']==locked)
            self.check('caption lock skip is visible','锁定' in self.page.save_state.text() or 'locked' in self.page.save_state.text().lower(),self.page.save_state.text())
            self.shot('caption-own-lock-skipped');self.key(Qt.Key_Z,Qt.ControlModifier);yield .4
            self.check('undo restores all unlocked range edits',self.signature()==q_cues and self.graph()==q_graph)
            self.phase='production-save-reopen';QTest.mouseClick(self.page.save_button,Qt.LeftButton);yield .4
            self.check('production save writes canonical caption positions',load_project(working).to_dict()['cues']==self.signature())
            saved=load_project(working)
            self.check('original ASR evidence preserved',saved.asr_evidence==raw_asr)
            self.check('subtitle lock saved','S2' in saved.studio_state.get('locked_speakers',()))
            reopened=output/'reopened-caption.2byteproj';reopened.write_bytes(working.read_bytes())
            window.open_studio_project(reopened,mode='edit',source='independent-caption-reopen')
            yield lambda:self.ready() and Path(self.page.project_path).resolve()==reopened;yield .3
            self.check('save reopen positions stable no double shift',self.signature()==q_cues)
            self.check('save reopen V1 disabled and locked',self.page.project.video_tracks[0]==v1)
            self.check('save reopen own subtitle lock','S2' in self.page.timeline.locked_speakers)
            self.page.video.set_paused(True);self.seek(8500);yield lambda:self.visible(8500,['before']);yield .2
            self.shot('caption-saved-reopened')
            self.phase='production-subtitle-export'
            artifacts=export_subtitle_artifacts(saved,output/'exports','独立字幕波纹',SubtitleExportOptions(frozenset({'srt'}),'both'))
            for artifact in artifacts:
                expected=copy.copy(saved);expected.cues=[c for c in saved.cues if not artifact.speaker_id or c.speaker_id==artifact.speaker_id]
                self.check('production SRT parse and exact time '+artifact.path.name,verify_subtitle_artifact(artifact,expected).valid)
                self.result['exports'].append({'path':str(artifact.path),'count':artifact.cue_count,'speaker_id':artifact.speaker_id})
            protected=plan.get('protected_project')
            if protected:
                self.phase='real-user-copy-migration'
                window.open_studio_project(Path(protected['copy']),mode='edit',source='independent-caption-protected-copy')
                yield lambda:self.ready() and Path(self.page.project_path).resolve()==Path(protected['copy']);yield .3
                current=self.page.project
                self.check('actual copied engineering displayed positions retained',self.signature()==protected['displayed_cues'])
                self.check('actual copied manual/source archive preserved',current.studio_state[KEY]['source_archive']==protected['raw_cues'])
                self.check('actual copied ASR and speaker identity unchanged',current.asr_evidence==protected['asr_evidence'] and current.to_dict()['speakers']==protected['speakers'])
                signature=self.signature();self.check('actual migration idempotent',not ensure_independent_captions(current) and self.signature()==signature)
                self.check('read-only original project SHA unchanged',hashlib.sha256(Path(protected['source']).read_bytes()).hexdigest()==protected['sha256'])
                self.shot('caption-actual-copy-migration')
            from . import blank_project_audit
            self.result['provider_calls_attempted']=blank_project_audit._provider_calls
            self.check('zero new provider requests',blank_project_audit._provider_calls==0)

        def finish(self):
            self.timer.stop();self.result['last_phase']=self.phase
            target=output/'caption-workflow-result.json'
            def write():target.write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),'utf8')
            write()
            def stopped():self.result['gui_shutdown']=True;write()
            QApplication.instance().aboutToQuit.connect(stopped)
            window.result_exit_code=0 if self.result['passed'] else 1
            self.page.undo_stack.setClean();window.close()
    window._independent_caption_audit=Audit()
