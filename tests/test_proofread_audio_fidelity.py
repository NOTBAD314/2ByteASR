"""Real PCM decoding and output lifecycle, independent of caption text length."""
import subprocess
import wave
import time
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QAudio
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
from twobyteasr.playback.cue_audio_preview import plan_cue_preview, preview_command
from twobyteasr.playback.cue_player import CuePlayer, _PreviewThread
from twobyteasr.studio.studio_video_track import ffmpeg_executable

APP=QApplication.instance() or QApplication([])
FFMPEG=str(ffmpeg_executable())


def project(path, start=1234, end=2387):
    p=SubtitleProject(StudioMedia(str(path),duration_ms=5000),cues=[StudioCue('stable',start,end,'短いね')])
    p.validate();p.render_settings['_cue_domain']='timeline'
    return p


@pytest.mark.parametrize('rate,channels',[(44100,1),(44100,2),(48000,1),(48000,2)])
def test_full_band_original_pcm_stereo_and_exact_boundaries(tmp_path,rate,channels):
    t=np.arange(rate*5)/rate
    left=.16*np.sin(2*np.pi*11000*t)+.22*np.sin(2*np.pi*703*t)
    right=.14*np.sin(2*np.pi*13000*t)+.24*np.sin(2*np.pi*997*t)
    frames=np.stack((left,right),axis=1) if channels==2 else left[:,None]
    raw=np.rint(frames*32767).astype('<i2')
    path=tmp_path/'original.wav'
    with wave.open(str(path),'wb') as wav:
        wav.setparams((channels,2,rate,0,'NONE','not compressed'));wav.writeframes(raw.tobytes())
    plan=plan_cue_preview(project(path),'stable')
    command,_=preview_command(plan,FFMPEG)
    out=subprocess.run(command,capture_output=True,check=True).stdout
    pcm=np.frombuffer(out,dtype='<i2').reshape(-1,2)
    reference=subprocess.run([FFMPEG,'-v','error','-i',str(path),'-ac','2','-ar','48000','-f','s16le','-'],capture_output=True,check=True).stdout
    expected=np.frombuffer(reference,dtype='<i2').reshape(-1,2)[1234*48:2387*48]
    assert pcm.shape==expected.shape==(1153*48,2)
    # Resampler's finite boundary kernel may differ in the first few samples.
    for channel in range(2):
        if rate == 48000:
            assert np.corrcoef(pcm[100:-100,channel],expected[100:-100,channel])[0,1]>.995
            assert np.corrcoef(pcm[-2000:-100,channel],expected[-2000:-100,channel])[0,1]>.995
        else:
            # 1.234 s is a fractional 44.1k source frame. Measure that seek
            # quantization instead of interpreting high-frequency phase as
            # missing/wrong audio; require less than one source-frame error.
            hz = 703 if channel == 0 or channels == 1 else 997
            carrier = np.exp(-2j*np.pi*hz*np.arange(len(pcm)-200)/48000)
            got = np.dot(pcm[100:-100,channel],carrier)
            wanted = np.dot(expected[100:-100,channel],carrier)
            boundary_error_seconds = abs(np.angle(got/wanted))/(2*np.pi*hz)
            assert boundary_error_seconds < 1/44100
    frequencies=np.fft.rfftfreq(len(pcm),1/48000)
    spectrum=np.abs(np.fft.rfft(pcm[:,0].astype(float)))
    assert spectrum[(frequencies>10500)&(frequencies<11500)].max()>spectrum.max()*.2
    if channels==2:
        assert np.corrcoef(pcm[:,0],pcm[:,1])[0,1]<.1
    assert '-ss' in command and '-t' in command


def test_initial_idle_and_underrun_cannot_finish_unconsumed_pcm():
    player=CuePlayer();player.cue_id='stable';player.request_id='new';player._expected_ms=1000
    player._started_at=time.perf_counter();player._clicked_at=time.perf_counter()
    snap=[0,QAudio.State.IdleState,QAudio.Error.NoError,7680,0,192000]
    calls=[]
    player._sink=SimpleNamespace(output_snapshot=lambda:tuple(snap),bufferSize=lambda:7680,
        stop=lambda:calls.append('finish'),reset=lambda:None)
    player._check_finished()
    assert player.request_id=='new' and player._drain_deadline is None and not calls
    snap[:]=[250000,QAudio.State.IdleState,QAudio.Error.UnderrunError,7680,48000,192000]
    player._check_finished()
    assert player.request_id=='new' and player._drain_deadline is None
    snap[:]=[1000000,QAudio.State.IdleState,QAudio.Error.NoError,7680,192000,192000]
    player._check_finished();assert player._drain_deadline is not None
    player._drain_deadline=0;player._check_finished()
    assert calls==['finish'] and not player.cue_id
    player.shutdown()


def test_twenty_old_decode_callbacks_cannot_replace_latest_request(monkeypatch):
    player=CuePlayer();player.cue_id='last';player.request_id='request-20'
    seen=[]
    monkeypatch.setattr(player,'_ensure_sink',lambda:(_ for _ in ()).throw(AssertionError('stale output opened')))
    player.state_changed.connect(lambda *args:seen.append(args))
    for n in range(20):
        player._start(f'request-{n}',b'old pcm')
        player._decode_failed(f'request-{n}','old failure')
    assert player.request_id=='request-20' and not seen
    player._sink=None;player.shutdown()


def test_old_finished_signal_cannot_start_pending_decode_while_new_worker_runs(monkeypatch):
    class Finished:
        def deleteLater(self):pass
        def cancel(self):pass
        def wait(self,*_args):pass
    old,current=Finished(),Finished()
    player=CuePlayer();player._thread=current;player._threads={old,current}
    plan=SimpleNamespace(request_id='latest')
    player.request_id='latest';player._pending_plan=(plan,'cue-latest')
    started=[];monkeypatch.setattr(player,'_decode_plan',started.append)
    player._thread_finished(old)
    assert not started and player._pending_plan==(plan,'cue-latest') and player._thread is current
    player._thread_finished(current)
    assert started==[plan] and player._pending_plan is None
    player.shutdown()
