"""Short real hidden endpoint crash/recovery, with two audible lanes."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
import wave
from pathlib import Path
import numpy as np
from PySide6.QtWidgets import QApplication
from twobyteasr.playback.audio_engine import StudioAudioEngine


def test_two_lane_endpoint_recovers_at_current_position(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    app=QApplication.instance() or QApplication([])
    path=tmp_path/'tone.wav'
    pcm=(np.sin(np.arange(48000*20)*2*np.pi*440/48000)*3000).astype('<i2')
    with wave.open(str(path),'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(48000);stream.writeframes(pcm.tobytes())
    engine=StudioAudioEngine(ffmpeg_path=Path(__file__).resolve().parents[1]/'tools/ffmpeg/bin/ffmpeg.exe')
    start=time.monotonic();killed=None;recovered=None;last_send=0.
    try:
        while time.monotonic()-start<15:
            now=time.monotonic()
            if now-last_send>.05:
                target=4000+int((now-start)*1000)
                layers=[dict(source_path=str(path),source_ms=target,source_out_ms=20000,clip_id=f'clip{i}',audio_track_id=f'A{i}') for i in range(2)]
                engine.synchronize_mix(layers,paused=False,transport_rate=1.,volume=.3)
                last_send=now
            app.processEvents()
            state=engine.telemetry_snapshot()
            if killed is None and state.get('sink_consumed_bytes',0)>20000:
                process=engine._worker.process
                killed=process.pid
                process.kill()  # The exact Popen created by this test, no PID search.
            elif (killed and state.get('endpoint_pid') not in (None,killed)
                    and state.get('sink_consumed_bytes',0)>20000):
                recovered=state;break
            time.sleep(.005)
        assert killed is not None,'initial real audio endpoint never became audible'
        assert recovered is not None,engine.telemetry_snapshot()
        assert recovered['endpoint_generation']==2
        assert recovered['pipe_state']=='connected'
        assert recovered['source_start_ms']>=4000
        assert abs(recovered['requested_source_ms']-recovered['estimated_source_ms'])<1500
        assert recovered['windows_sink_count']==1
    finally:
        engine.request_shutdown()
        assert engine.wait_for_shutdown(4.)
        engine.deleteLater();app.processEvents()
