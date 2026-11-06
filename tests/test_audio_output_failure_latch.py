from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QAudioDevice,QMediaDevices
from twobyteasr.playback.audio_engine import _AudioEngineWorker


def test_unavailable_device_remains_failed_and_is_not_reprobed_on_every_sync(monkeypatch):
    app=QApplication.instance() or QApplication([])
    queries=[]
    def missing():queries.append(1);return QAudioDevice()
    monkeypatch.setattr(QMediaDevices,'defaultAudioOutput',missing)
    worker=_AudioEngineWorker(Path('unused-ffmpeg'))
    states=[];acks=[]
    worker.telemetry.connect(lambda value:states.append(value['state']))
    worker.synchronize_complete.connect(lambda:acks.append(1))
    request=dict(source_path='fixture.wav',source_ms=0,source_out_ms=5000,audible=True,
                 paused=True,transport_generation=(1,0),session_generation=1,
                 transport_rate=1.,clip_rate=1.,playback_rate=1.,volume=0.)
    worker.synchronize(request)
    assert states[-1]=='NO_OUTPUT_DEVICE'
    for _ in range(20):worker.synchronize(request)
    assert len(queries)==1 and len(acks)==21
    assert set(states)=={'NO_OUTPUT_DEVICE'}
    worker.prepare_shutdown();worker.deleteLater();app.processEvents()
