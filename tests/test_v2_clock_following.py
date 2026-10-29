# Legacy Qt decoder comparison tests; process backend contracts live in test_video_decode_pipe.py.
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QObject
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication
from twobyteasr.playback.secondary_video_legacy import _DecoderWorker, SecondaryVideoSource

@pytest.fixture
def app(): return QApplication.instance() or QApplication([])

class Player:
    def __init__(self): self.seeks=[]; self.rate=1.; self.ms=0; self.state=QMediaPlayer.PlaybackState.PausedState
    def position(self): return self.ms
    def setPosition(self, ms): self.ms=ms; self.seeks.append(ms)
    def playbackRate(self): return self.rate
    def setPlaybackRate(self, rate): self.rate=rate
    def playbackState(self): return self.state
    def setVideoSink(self, sink): pass
    def play(self): self.state=QMediaPlayer.PlaybackState.PlayingState
    def pause(self): self.state=QMediaPlayer.PlaybackState.PausedState

def request(worker, ms, paused=True, generation=1):
    worker.request(ms,generation,paused,1.,0.,False,False)

def test_loading_applies_latest_seek_at_loaded_event(app):
    worker=_DecoderWorker(); worker.player=Player(); worker.path='fixture.mp4'
    request(worker,20000); request(worker,30000)
    assert worker.player.seeks==[]
    worker._log_media_status(QMediaPlayer.MediaStatus.LoadedMedia)
    assert worker.player.seeks==[30000]
    assert worker._pending_pause_after_frame
    request(worker,30000,paused=False)
    assert not worker._pending_pause_after_frame
    assert worker.player.state==QMediaPlayer.PlaybackState.PlayingState

def test_normal_playback_drift_does_not_reseek_every_frame(app):
    worker=_DecoderWorker(); worker.player=Player(); worker.path='fixture.mp4'; worker._source_loaded=True
    request(worker,10000,paused=False)
    for ms in range(10016,10160,16): request(worker,ms,paused=False)
    assert worker.player.seeks==[10000]
    request(worker,3000,paused=False,generation=2)
    assert worker.player.seeks==[10000,3000]

def test_prewarm_zero_timestamp_starts_first_frame_decode(app):
    worker=_DecoderWorker(); worker.player=Player(); worker.path='fixture.mp4'; worker._source_loaded=True
    request(worker,0,generation=0)
    assert worker.player.seeks==[0]
    assert worker._pending_pause_after_frame
    assert worker.player.state==QMediaPlayer.PlaybackState.PlayingState

def test_pause_keeps_nearest_frame_despite_backend_preroll_queue(app):
    worker=_DecoderWorker(); worker.player=Player(); worker.path='fixture.mp4'; worker._source_loaded=True
    frames=[]
    def receive(generation,target,pts,image,path):
        frames.append(pts);worker.frame_consumed()
    worker.frame_ready.connect(receive)
    request(worker,20000)
    class Frame:
        def __init__(self,pts):self.pts=pts
        def isValid(self):return True
        def startTime(self):return self.pts*1000
        def toImage(self):
            image=QImage(8,8,QImage.Format.Format_ARGB32);image.fill(0xffffffff);return image
    for pts in (20017,20033,20050,20000,20017):worker._on_frame(Frame(pts))
    assert frames==[20017,20000]
    request(worker,20000,paused=False)
    assert worker.player.seeks==[20000,20000]

def test_late_frame_cannot_rewind_requested_time_and_age_grows(app,monkeypatch):
    from twobyteasr.playback import secondary_video_legacy as secondary_video
    now=[10.]
    monkeypatch.setattr(secondary_video,'perf_counter',lambda:now[0])
    source=SecondaryVideoSource();source.generation=2;source.requested_ms=2000
    image=QImage(8,8,QImage.Format.Format_ARGB32);image.fill(0xffffffff)
    source._on_frame(2,1900,1983,image,'fixture.mp4')
    assert source.requested_ms==2000 and source.pts_ms==1983
    now[0]+=.5
    assert source.frame_age_ms==pytest.approx(500)
    source._on_frame(1,1000,1000,image,'fixture.mp4')
    assert source.pts_ms==1983

def test_audio_backward_seek_restarts_once_per_clock_generation(app,monkeypatch):
    from pathlib import Path
    from twobyteasr.playback.audio_engine import _AudioEngineWorker
    worker=_AudioEngineWorker(Path('ffmpeg.exe'));worker.process=SimpleNamespace(poll=lambda:None)
    worker._source_path='fixture.mp4';worker._source_start_ms=30000
    monkeypatch.setattr(worker,'_emit',lambda *a:None)
    starts=[]
    monkeypatch.setattr(worker,'_start_decoder',lambda path,ms,rate:starts.append(ms))
    payload=dict(source_path='fixture.mp4',source_ms=30000,audible=True,paused=False,transport_generation=4)
    worker.synchronize(payload)
    assert starts==[30000]
    # Same source, backward target and an otherwise healthy process: the
    # clock epoch must force a flush despite the negative drift policy.
    payload.update(source_ms=10000,transport_generation=5)
    worker.synchronize(payload);worker.synchronize(payload)
    assert starts==[30000,10000]
