from collections import deque
from types import SimpleNamespace

import pytest

from twobyteasr.diagnostics.publication_metrics import event_rate, upload_snapshot


def test_missing_warming_and_idle_observations_are_distinct():
    assert event_rate([], 10)['events_per_second'] is None
    assert event_rate([9.99], 10)['status'] == 'insufficient_samples'
    assert event_rate([2, 3], 10) == {
        'status': 'idle', 'events_per_second': 0.0, 'sample_count': 0,
        'window_seconds': 2.0, 'last_event_age_ms': 7000.0}
    rate = event_rate([float('nan'), float('inf'), 9, 9.5, 10], 10)
    assert rate['events_per_second'] == 2 and rate['status'] == 'measured'


def test_rejected_native_commands_never_count_as_acknowledgements():
    rows = [dict(started=9.1, accepted=False, applied_at=9.2),
            dict(started=9.3, accepted=True, applied_at=9.4),
            dict(started=9.5, accepted=True, applied_at=9.6)]
    snapshot = upload_snapshot(rows, 10)
    assert snapshot['attempts_in_window'] == 3 and snapshot['rejected_in_window'] == 1
    assert snapshot['ack']['events_per_second'] == 5
    assert snapshot['screen_events_per_second'] is None
    assert snapshot['gpu_upload_ms'] is None
    assert snapshot['cost_p95_ms']['write_ms'] is None


def test_async_submissions_are_counted_without_gui_publish_and_history_is_bounded(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.playback import video_compositor
    app = QApplication.instance() or QApplication([])
    scene = video_compositor.VideoCompositionScene()
    scene._async_video_active = True
    try:
        for _ in range(5000):
            scene._secondary_frame_arrived()
        assert len(scene._secondary_frame_timestamps_ns) == 1200
        assert scene._secondary_frame_total == 5000
        scene._async_compositor = SimpleNamespace(
            samples=deque([dict(compose_end=9 + i/60, composition_ms=.4) for i in range(61)]),
            submitted_count=61)
        monkeypatch.setattr(video_compositor, 'perf_counter', lambda: 10)
        result = scene.performance_snapshot()
        assert result['native_publish_fps'] == 60
        assert result['render_p95_ms'] == .4
        assert result['frame_samples_overwritten'] == 3800
        assert result['native_publish_status'] == 'measured'
        assert len(scene._native_publish_times) == 0
    finally:
        scene._async_compositor = None
        scene._async_video_active = False
        scene.close()


def test_ipc_wait_observer_records_actual_wait_without_changing_requested_sleep(monkeypatch):
    from twobyteasr.playback import studio_mpv
    actor = studio_mpv._MpvCommandActor.__new__(studio_mpv._MpvCommandActor)
    actor._init_request_metrics()
    times = iter((10., 10.012))
    monkeypatch.setattr(studio_mpv.time, 'perf_counter', lambda: next(times))
    waits = []
    monkeypatch.setattr(studio_mpv.time, 'sleep', waits.append)
    actor._sleep_for_response(.001)
    assert waits == [.001]
    assert actor._ipc_sleep_count == 1
    assert actor._ipc_sleep_samples[0][1] == pytest.approx(12)
    assert actor._ipc_sleep_samples[0][2] == 1


def test_bgra_costs_describe_real_buffer_without_changing_pixels():
    av = pytest.importorskip('av')
    from twobyteasr.playback.video_decode_worker import display_bgra
    frame = av.VideoFrame(160, 90, 'yuv420p')
    for plane in frame.planes:
        plane.update(bytes([100]) * plane.buffer_size)
    expected = display_bgra(frame, 1, (80, 45))
    costs = {}
    actual = display_bgra(frame, 1, (80, 45), costs=costs)
    assert actual == expected
    assert costs['input_pixels'] == [160, 90]
    assert costs['raster_pixels'] == [80, 45]
    assert costs['pixel_bytes'] == len(actual[2]) == 80*45*4
    assert costs['reformat_ms'] >= 0 and costs['pack_copy_ms'] >= 0
    assert costs['gpu_download_ms'] is None
