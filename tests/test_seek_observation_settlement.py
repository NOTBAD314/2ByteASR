from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from twobyteasr.studio.studio_video_canvas import MpvCanvas


def test_deep_source_timestamp_is_mapped_before_project_eof_and_seek_settlement():
    app = QApplication.instance() or QApplication([])
    properties = {'duration': 108.0, 'pause': True, 'speed': 1.0,
                  'time-pos': 102.0, 'seeking': False, 'video-frame-info': {'pts': 102.0}}
    canvas = MpvCanvas()
    canvas._startup_state = 'READY'
    canvas._duration = canvas._duration_override = 15.0
    canvas.set_project_time_mapping(enabled=True, timeline_in_ms=10000, source_in_ms=100000)
    canvas.controller = SimpleNamespace(running=True, observed_properties=lambda: properties.copy())
    try:
        canvas._playback_clock.begin_seek(12000)
        canvas._reconcile_position()
        assert not canvas.at_eof
        assert not canvas._playback_clock.exact_seek_pending
        assert canvas.playback_position_snapshot().observed_media_ms == 12000
        assert canvas.visual_position() == 12.0
    finally:
        canvas.controller = None
        canvas.close()
        canvas.deleteLater()
        app.processEvents()


def test_seeking_false_before_target_frame_keeps_fast_observation():
    app = QApplication.instance() or QApplication([])
    properties = {
        'duration': 30.0, 'pause': True, 'speed': 1.0,
        'time-pos': 2.61, 'seeking': False,
        'video-frame-info': {'pts': 0.0},
    }
    canvas = MpvCanvas()
    canvas._startup_state = 'READY'
    canvas.controller = SimpleNamespace(
        running=True,
        observed_properties=lambda: properties.copy(),
        observed_property=lambda key, default=None: properties.get(key, default),
    )
    try:
        canvas.begin_seek_trace(2.61)
        canvas.mark_seek_stage('T4_mpv_seek_accepted')
        canvas._reconcile_position()
        markers = canvas._active_seek_trace['markers']
        assert 'T6_seeking_false' in markers
        assert 'T5_first_target_frame' not in markers
        assert not canvas._playback_clock.exact_seek_pending
        assert canvas._sync_timer.interval() == 16

        properties['video-frame-info'] = {'pts': 2.6}
        canvas._reconcile_position()
        assert 'T5_first_target_frame' in markers
        assert canvas._sync_timer.interval() == 150
    finally:
        canvas.controller = None
        canvas.close()
        canvas.deleteLater()
        app.processEvents()
