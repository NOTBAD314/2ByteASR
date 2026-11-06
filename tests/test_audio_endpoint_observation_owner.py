from PySide6.QtWidgets import QApplication
from twobyteasr.playback.audio_engine import StudioAudioEngine


def test_retired_endpoint_pcm_and_clock_cannot_release_the_current_transport():
    app=QApplication.instance() or QApplication([])
    engine=StudioAudioEngine(isolated=False)
    try:
        engine._worker._endpoint_generation=2
        engine._last_payload=dict(audible=True,paused=True,session_generation=0,source_path='fixture.wav',
                                  transport_generation=(1,0),clip_rate=1.,transport_rate=1.)
        old=dict(state='PAUSED',session_generation=0,source_path='fixture.wav',transport_generation=(1,0),
                 effective_rate=1.,endpoint_generation=1,buffer_bytes=96000,clock_sequence=100)
        engine._telemetry=old
        assert not engine.playback_readiness().ready
        assert not engine.clock_observation()
        pending=engine.telemetry_snapshot()
        assert pending['state']=='ENDPOINT_STARTING' and pending['buffer_bytes']==0
        assert pending['endpoint_generation']==2 and pending['observation_endpoint_generation']==1
        assert pending['endpoint_pid'] is None
        engine._telemetry={'state':'ENDPOINT_STARTING','session_generation':0}
        engine._capture_telemetry(old)
        assert engine._telemetry['state']=='ENDPOINT_STARTING'
        engine._capture_telemetry(dict(old,endpoint_generation=2,clock_sequence=1))
        assert engine.playback_readiness().ready
        assert engine.clock_observation()['endpoint_generation']==2
    finally:
        engine.request_shutdown();assert engine.wait_for_shutdown(4)
        engine.deleteLater();app.processEvents()
