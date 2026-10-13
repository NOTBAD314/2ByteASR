"""Fixed real-widget playback matrix, with output capture and a ten-minute gate."""
import json,time,traceback,os,threading,sys,wave
from pathlib import Path
from PySide6.QtCore import QObject,QTimer,Qt,QPoint,QPointF,QMimeData,QUrl
from PySide6.QtTest import QTest
from PySide6.QtGui import QDragEnterEvent,QDropEvent
from PySide6.QtWidgets import QApplication,QInputDialog,QComboBox

def start(window,out):
    class Audit(QObject):
        def __init__(self):
            super().__init__(window);self.page=window.studio_page;self.started=time.monotonic()
            self.result={'operations':[],'checks':{},'error':''};self.pending=0.;self.sequence=self.run();self.busy=False
            self.expected_rate=1.
            from .build_identity import load_build_identity
            self.result['build']=vars(load_build_identity())
            self.result['real_user_click']=False
            self.result['interaction']='Real Qt drag/drop, mouse and keyboard events through Studio widgets'
            self.ablation=os.environ.get('TWOBYTEASR_RECOVERY_ABLATION','none');self.result['ablation']=self.ablation
            self.stop=threading.Event();self.last=time.perf_counter();self.gaps=[];self.phase='setup';self.capture=False;self.sample_at=0.
            self.sequence_finished=False
            if os.environ.get('TWOBYTEASR_RECOVERY_UNMUTE')=='1':
                from .recovery_audio_session_audit import monitor
                threading.Thread(target=monitor,args=(out,self.stop),daemon=True).start()
            threading.Thread(target=self.loopback,name='recovery-WASAPI',daemon=True).start()
            self.main_id=threading.get_ident()
            threading.Thread(target=self.watchdog,name='recovery-GUI-stacks',daemon=True).start()
            self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(25)
        def watchdog(self):
            previous=0.
            with (out/'gui-stacks.jsonl').open('w',encoding='utf8') as stream:
                while not self.stop.wait(.05):
                    now=time.perf_counter()
                    if now-self.last>.1 and now-previous>.5:
                        previous=now
                        stream.write(json.dumps({'phase':self.phase,'wall':now,'delay_ms':(now-self.last)*1000,
                            'stack':traceback.format_stack(sys._current_frames().get(self.main_id))})+'\n');stream.flush()
        def loopback(self):
            import numpy as np
            info={'start':time.perf_counter(),'rate':48000,'channels':2,'frames':0}
            try:
                import soundcard as sc
                speaker=sc.default_speaker();mic=sc.get_microphone(id=speaker.id,include_loopback=True)
                info.update(device=speaker.name,device_id=speaker.id)
                with mic.recorder(samplerate=48000,channels=2,blocksize=4800) as recorder,wave.open(str(out/'loopback.wav'),'wb') as wav:
                    wav.setparams((2,2,48000,0,'NONE','not compressed'))
                    while not self.stop.is_set():
                        data=recorder.record(numframes=4800)
                        wav.writeframes((np.clip(data,-1,1)*32767).astype('<i2').tobytes());info['frames']+=len(data)
                        if info['frames']%48000==0:(out/'loopback.json').write_text(json.dumps(info,ensure_ascii=False),encoding='utf8')
                info['complete']=True
            except Exception:info['error']=traceback.format_exc()
            finally:(out/'loopback.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf8')
        def mark(self,name):
            from twobyteasr.studio_performance import performance_snapshot
            state=performance_snapshot(self.page,compact=True)
            state['rate_widget']=self.page.speed_box.currentData()
            self.result['operations'].append({'name':name,'wall':time.perf_counter(),'state':state})
            if name.endswith('-playing') or name in ('mix-all-4x','resume-4x','seek-4x','hide-V2','show-V2','mix-all-1x-restored','endurance-complete'):
                audio_ok=(not state['audio_routing'].get('audible_track_id') and not state['audio_routing'].get('mix_track_ids')) if self.ablation in ('audio-off','basic') else state['audio'].get('sink_state')=='ActiveState' and state['audio'].get('sink_consumed_rms',0)>0
                self.result['checks'][name]=not state['clock']['paused'] and audio_ok
                rates={'widget':state['rate_widget'],'clock':state['clock']['playback_rate']}
                if self.ablation not in ('audio-off','basic'):rates['audio']=state['audio'].get('effective_rate')
                self.result['checks'][name+'-rate']=all(value is not None and abs(float(value)-self.expected_rate)<.001 for value in rates.values())
            (out/'ui-operations.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
            self.phase=name
        def seek(self,value):
            w=self.page.timecode_input;QTest.mouseClick(w,Qt.LeftButton);QTest.keyClick(w,Qt.Key_A,Qt.ControlModifier)
            QTest.keyClicks(w,value);QTest.keyClick(w,Qt.Key_Return)
        def track(self,track,x=101):
            rect=self.page.timeline._video_track_rect(track)
            assert rect.isValid(),track
            QTest.mouseClick(self.page.timeline,Qt.LeftButton,pos=QPoint(x,int(rect.center().y())))
        def play(self,playing):
            if self.page.video.playback_position_snapshot().paused==bool(playing):
                QTest.mouseClick(self.page.play_button,Qt.LeftButton)
        def tick(self):
            if self.busy:return
            try:
                now=time.perf_counter();self.gaps.append({'phase':self.phase,'ms':(now-self.last)*1000});self.last=now
                if now-self.sample_at>.5:
                    from .studio_performance import performance_snapshot
                    self.sample_at=now;state=performance_snapshot(self.page,compact=True);state['wall']=now;state['phase']=self.phase
                    (out/'latest.json').write_text(json.dumps(state,ensure_ascii=False,default=str),encoding='utf8')
                    with (out/'samples.jsonl').open('a',encoding='utf8') as stream:stream.write(json.dumps(state,ensure_ascii=False,default=str)+'\n')
                    if not self.capture and state.get('audio',{}).get('endpoint_pid'):
                        self.page.audio_engine.capture_pcm('backend',True);self.capture=True
                if time.monotonic()-self.started>float(os.environ.get('TWOBYTEASR_RECOVERY_BUDGET','900')):raise TimeoutError('UI recovery budget')
                if time.monotonic()<self.pending:return
                self.busy=True
                value=next(self.sequence);self.pending=time.monotonic()+float(value)
            except StopIteration:self.finish()
            except Exception:self.result['error']=traceback.format_exc();self.finish()
            finally:self.busy=False
        def combo(self,widget,value):
            index=widget.findData(value);assert index>=0
            QTest.mouseClick(widget,Qt.LeftButton)
            QTest.qWait(100)
            view=widget.view();assert view.isVisible(),'Combo popup did not open'
            # The popup owns navigation while open. Sending these keys to the
            # closed combo instead changes 0.5x immediately and dismisses it.
            QTest.keyClick(view,Qt.Key_Home)
            for _ in range(index):QTest.keyClick(view,Qt.Key_Down)
            assert view.currentIndex().row()==index,(index,view.currentIndex().row())
            view.window().grab().save(str(out/f'rate-popup-{value:g}x.png'))
            QTest.keyClick(view,Qt.Key_Return)
            QTest.qWait(100)
            assert widget.currentData()==value,(value,widget.currentData())
            self.expected_rate=float(value)
        def drop_media(self,filename):
            def accept():
                dialog=QApplication.activeModalWidget()
                if isinstance(dialog,QInputDialog):
                    assert dialog.findChild(QComboBox).currentText()=='新建视频轨道'
                    QTest.keyClick(dialog,Qt.Key_Return)
            QTimer.singleShot(300,accept)
            media_root=Path(os.environ['TWOBYTEASR_RECOVERY_MEDIA_ROOT']).resolve()
            if not media_root.is_relative_to((Path.cwd()/'tmp').resolve()):raise ValueError('Diagnostic media must be under tmp')
            mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(media_root/filename))])
            QApplication.sendEvent(self.page,QDragEnterEvent(QPoint(300,300),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier))
            QApplication.sendEvent(self.page,QDropEvent(QPointF(300,300),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier))
        def run(self):
            yield 2
            while self.page._readiness.active:yield .2
            self.play(False);yield .2
            if self.ablation in ('web-off','basic'):
                self.page._stop_web_live_preview('explicit recovery ablation')
                self.page._stop_storyboard_animation()
                # Test-only removal of the renderer consumers. The normal
                # production paths and all user files remain unchanged.
                self.page._schedule_advanced_preview=lambda *a,**k:None
                self.page._publish_advanced_frame=lambda *a,**k:None
                self.page._publish_advanced_live=lambda *a,**k:False
                self.page._ensure_web_live_preview=lambda *a,**k:False
            if self.ablation in ('audio-off','basic'):
                for track in self.page.project.audio_tracks:
                    if not track.muted:
                        rect=self.page.timeline._audio_track_rects()[track.id]
                        QTest.mouseClick(self.page.timeline,Qt.LeftButton,pos=QPoint(120,int(rect.center().y())))
                yield .3
            if self.ablation in ('waveform-off','basic') and self.page.waveform_toggle.isChecked():
                QTest.mouseClick(self.page.waveform_toggle,Qt.LeftButton)
            diagnostic=len(self.page.project.video_tracks)<2
            if diagnostic:
                if not self.page.project.media.path:
                    self.mark('UI-drop-V1-start');self.drop_media('V1-440Hz.mp4');yield 2
                    while not self.page.project.media.path:yield .3
                    self.mark('UI-drop-V1-complete')
                    self.play(False);yield .5
                self.seek('00:00:00.000');yield .5
                self.mark('UI-drop-V2-start');self.drop_media('V2-880Hz.mp4');yield 3
                while len(self.page.project.video_tracks)<2:yield .3
                self.mark('UI-drop-V2-complete')
                self.play(False);yield .5
                self.track('V2',143);self.track('V2',167);self.track('V1');yield .6
                self.mark('V1-only-start');self.play(True);yield 6
                self.mark('V1-only-playing');self.play(False);yield .3
                self.track('V2',143);self.track('V2',167);self.track('V1',143);self.track('V1',167);self.track('V2');yield .6
                self.mark('V2-only-start');self.play(True);yield 6
                self.mark('V2-only-playing');self.play(False);yield .3
                self.track('V1',143);self.track('V1',167);yield .5
            self.seek('00:00:10.000');yield 1
            self.mark('before-select')
            self.track('V2');yield .5
            self.mark('V2-selected-default-routing')
            self.play(True);yield 6
            self.mark('dual-default-playing')
            self.page.video.controller.screenshot_to_file(out/'dual-default-native.png')
            window.grab().save(str(out/'dual-default-ui.png'))
            self.play(False);yield .5
            self.track('V1');yield .4
            self.play(True);yield 6
            self.mark('V1-selected-playing')
            self.play(False);yield .4
            if diagnostic:
                rect=self.page.timeline._audio_track_rects()['A1']
                QTest.mouseClick(self.page.timeline,Qt.LeftButton,pos=QPoint(178,int(rect.center().y())))
                yield .6
                assert self.page.project.studio_state['audio_master_mode']=='mix_all'
                self.mark('mix-all-start');self.play(True);yield 8
                self.mark('mix-all-playing')
                self.combo(self.page.speed_box,4.);yield 8
                self.mark('mix-all-4x')
                self.play(False);yield .5
                self.play(True);yield 4
                self.mark('resume-4x')
                self.seek('00:01:00.000');yield 4
                self.mark('seek-4x')
                self.track('V2',143);yield 4
                self.mark('hide-V2')
                self.track('V2',143);yield 4
                self.mark('show-V2')
                self.combo(self.page.speed_box,1.);yield 3
                self.mark('mix-all-1x-restored')
                self.play(False);yield .4
                if os.environ.get('TWOBYTEASR_RECOVERY_MODE')=='endurance':
                    self.seek('00:00:05.000');yield .7
                    self.mark('endurance-start');self.play(True)
                    yield 602.
                    self.mark('endurance-complete');self.play(False);yield .4
            self.page.audio_engine.capture_pcm('backend',False);yield 1
            self.mark('done')
        def finish(self):
            if self.sequence_finished:return
            self.sequence_finished=True
            self.timer.stop();self.result['elapsed']=time.monotonic()-self.started
            self.result['gaps']=self.gaps
            self.stop.set()
            (out/'ui-operations.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
            (out/'stop-loopback').touch()
            self.page.undo_stack.setClean();QTimer.singleShot(600,window.close)
    window._recovery_audit=Audit()
