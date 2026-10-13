"""Long real-media playback with device submission AND WASAPI loopback."""
import hashlib
import json
import os
import threading
import time
import traceback
import wave


def start_endurance_acceptance(window, output):
    from PySide6.QtCore import QObject, QTimer, Qt
    from PySide6.QtWidgets import QApplication
    from .audio_engine import _PcmRingDevice
    from .build_identity import load_build_identity

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page=window.studio_page
            self.seconds=min(1800.,max(5.,float(os.environ.get('TWOBYTEASR_ENDURANCE_SECONDS','300'))))
            self.rate=float(os.environ.get('TWOBYTEASR_ENDURANCE_RATE','4'))
            self.result={'build':vars(load_build_identity()),'checks':{},'samples':[], 'operations':[],
                         'requested_wall_seconds':self.seconds,'rate':self.rate,
                         'media':self.page.project.media.path,'startup':self.page._readiness.profile}
            self.capture=False;self.pcm=[];self.chunks=[]
            self.stop=threading.Event();self.loop_ready=threading.Event()
            self.loop_thread=threading.Thread(target=self.loopback,name='audit-WASAPI-loopback',daemon=True)
            self.loop_thread.start()
            self.original=_PcmRingDevice.readData
            def read(device,count):
                data=self.original(device,count)
                if self.capture and data:
                    self.pcm.append(bytes(data))
                    self.chunks.append((time.perf_counter(),device._generation,len(data)))
                return data
            _PcmRingDevice.readData=read
            self.started=time.perf_counter();self.last=self.started;self.gaps=[]
            self.sequence=self.run();self.pending=0.
            self.timer=QTimer(self);self.timer.setTimerType(Qt.TimerType.PreciseTimer)
            self.timer.timeout.connect(self.tick);self.timer.start(100)

        def loopback(self):
            info={};self.result['loopback']=info
            try:
                import numpy as np
                import soundcard as sc
                speaker=sc.default_speaker()
                mic=sc.get_microphone(id=speaker.id,include_loopback=True)
                info.update(device=speaker.name,kind='WASAPI loopback',frames=0)
                with mic.recorder(samplerate=48000,channels=2,blocksize=4800) as recorder:
                    with wave.open(str(output/'wasapi-loopback.wav'),'wb') as wav:
                        wav.setparams((2,2,48000,0,'NONE','not compressed'))
                        self.loop_ready.set()
                        while not self.stop.is_set():
                            data=recorder.record(numframes=4800)
                            wav.writeframesraw((np.clip(data,-1,1)*32767).astype('<i2').tobytes())
                            info['frames']+=len(data)
                info['complete']=True
            except Exception:
                info['error']=traceback.format_exc()
                self.loop_ready.set()
            finally:
                (output/'loopback-status.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf8')

        def tick(self):
            now=time.perf_counter()
            if self.capture:
                self.gaps.append((now-self.last)*1000)
                state=self.page.audio_engine.telemetry_snapshot()
                keys=('state','source_generation','transport_generation','effective_rate','requested_source_ms',
                    'estimated_source_ms','drift_ms','buffer_bytes','sink_consumed_bytes','decoded_bytes',
                    'decoder_eof','underruns','device_empty_reads','callback_gaps_ms','callback_max_ms',
                    'mix_cost_ms','windows_sink_count','output_device','ffmpeg_pid','decoder_error')
                keys+=('sink_state','sink_error','sink_buffer_bytes','processed_us','elapsed_us','endpoint_pid','endpoint_backend')
                self.result['samples'].append({'wall':now, 'presentation_ms':self.page.video.visual_position()*1000,
                    **{k:state.get(k) for k in keys}})
                if len(self.result['samples'])%10==0:
                    (output/'endurance-progress.json').write_text(json.dumps(self.result['samples'][-1],ensure_ascii=False),encoding='utf8')
            self.last=now
            try:
                if now-self.started>self.seconds+150:raise TimeoutError('endurance audit timeout')
                if callable(self.pending):
                    if not self.pending():return
                elif now<self.pending:return
                value=next(self.sequence)
                self.pending=value if callable(value) else time.perf_counter()+value
            except StopIteration:self.finish()
            except Exception:self.result['error']=traceback.format_exc();self.finish()

        def run(self):
            page=self.page
            yield lambda:self.loop_ready.is_set()
            page.video.set_paused(True);page._seek(0.)
            page._shuttle_speed=self.rate;page.video.set_speed(self.rate)
            yield lambda:page._playback_buffers_ready()
            page.audio_engine.capture_pcm('endpoint-continuous',True)
            yield lambda:(output/'endpoint-continuous.started').is_file()
            self.capture=True;start=time.perf_counter()
            page.video.set_paused(False)
            yield self.seconds
            end=time.perf_counter();self.capture=False;page.video.set_paused(True)
            page.audio_engine.capture_pcm('endpoint-continuous',False)
            yield lambda:(output/'endpoint-continuous.json').is_file()
            from .audio_pcm_audit import read_capture
            captured=read_capture(output,'endpoint-continuous')
            self.pcm=[x[2] for x in captured]
            self.chunks=[(x[0],x[1],len(x[2])) for x in captured]
            data=b''.join(self.pcm)
            (output/'device-submission.s16le').write_bytes(data)
            self.result['continuous']={'wall_seconds':end-start,'pcm_bytes':len(data),
                'sha256':hashlib.sha256(data).hexdigest(),'generations':sorted({x[1] for x in self.chunks}),
                'callback_chunks':len(self.chunks),'first_chunk_ms':(self.chunks[0][0]-start)*1000 if self.chunks else None}
            self.result['checks']['continuous_duration']=end-start>=self.seconds
            self.result['checks']['continuous_pcm_duration']=len(data)/192000 >= self.seconds-.5
            # Preserve the completed window even if a later native seek fails.
            (output/'continuous-checkpoint.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),encoding='utf8')
            self.result['checks']['one_decoder_generation']=len({x[1] for x in self.chunks})==1
            self.result['checks']['single_endpoint']=all(x.get('windows_sink_count')==1 for x in self.result['samples'])
            self.result['checks']['isolated_endpoint']=all(x.get('endpoint_pid') and x['endpoint_pid']!=os.getpid() for x in self.result['samples'])
            self.result['checks']['no_starvation']=max((x.get('underruns') or 0 for x in self.result['samples']),default=0)==0
            self.result['checks']['no_decoder_error']=not any(x.get('decoder_error') for x in self.result['samples'])
            self.pcm=[]
            # Independent discontinuities after the uninterrupted window.
            for rate,target in ((1.,0.),(2.,600.),(4.,1100.),(1.,1197.)):
                page.video.set_paused(True);page._seek(target)
                page._shuttle_speed=rate;page.video.set_speed(rate)
                yield lambda:page._playback_buffers_ready()
                page.video.set_paused(False);yield 2.
                state=page.audio_engine.telemetry_snapshot()
                self.result['operations'].append({'rate':rate,'seek_seconds':target,
                    'presentation_ms':page.video.visual_position()*1000,'audio':state})
                self.result['checks'][f'seek-{target:g}-rate-{rate:g}']=state.get('sink_consumed_bytes',0)>0
            # Rate changes while playing, without a pause/seek in between.
            for rate in (4.,2.,1.):
                page._shuttle_speed=rate;page.video.set_speed(rate);yield 2.
                self.result['operations'].append({'hot_rate':rate,'audio':page.audio_engine.telemetry_snapshot()})
            page.video.set_paused(True)
            page.video.controller.screenshot_to_file(output/'endurance-tail-native.png')
            # A deliberately held GUI GIL must not starve the physical output.
            page._seek(0.);page._shuttle_speed=1.;page.video.set_speed(1.)
            yield lambda:page._playback_buffers_ready()
            page.audio_engine.capture_pcm('endpoint-gil-stall',True)
            yield lambda:(output/'endpoint-gil-stall.started').is_file()
            stall_start=time.perf_counter();page.video.set_paused(False);yield .5
            import ctypes
            ctypes.PyDLL('kernel32').Sleep(700)
            yield .5
            stall_end=time.perf_counter();page.video.set_paused(True)
            page.audio_engine.capture_pcm('endpoint-gil-stall',False)
            yield lambda:(output/'endpoint-gil-stall.json').is_file()
            stall_pcm=(output/'endpoint-gil-stall.pcm').stat().st_size/192000
            self.result['gil_stall']={'held_gui_gil_ms':700,'wall_seconds':stall_end-stall_start,
                                     'submitted_seconds':stall_pcm,'audio':page.audio_engine.telemetry_snapshot()}
            self.result['checks']['audio_survives_gui_gil_stall']=stall_pcm >= stall_end-stall_start-.15
            self.stop.set()
            yield lambda:not self.loop_thread.is_alive()
            self.result['checks']['loopback_recorded']=self.result['loopback'].get('frames',0)>48000
            self.result['user_gate']='Human listening remains separate from numeric loopback analysis.'

        def finish(self):
            self.timer.stop();self.stop.set();_PcmRingDevice.readData=self.original
            (output/'endurance-acceptance.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),encoding='utf8')
            self.page.close_page();window.hide();QTimer.singleShot(200,QApplication.instance().quit)

    window._endurance_audit=Audit()
