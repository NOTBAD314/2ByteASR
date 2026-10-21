import io
from types import SimpleNamespace

import pytest

from twobyteasr.exports.export_bitrate import PacketMeasurement, measure_packets, target_comparison
from twobyteasr.exports.studio_render import RenderJob, RenderSettings


def test_packet_duration_uses_whole_presentation_extent_despite_b_frame_order_and_nonzero_origin():
    measurement = PacketMeasurement()
    for pts in (12, 10, 13, 11):
        measurement.add(dict(size='100', pts_time=str(pts), dts_time=str(pts - 2), duration_time='1'))
    result = measurement.result(dict(duration='4', avg_frame_rate='1/1', bit_rate='999999'))
    assert result['duration_seconds'] == 4
    assert result['average_bitrate_bps'] == 800
    assert result['metadata_bitrate_bps'] == 999999
    assert result['packet_start_seconds'] == 10
    assert result['reliable']


def test_missing_final_duration_requires_clock_and_count_agreement():
    measurement = PacketMeasurement()
    for pts in (12, 10, 13, 11):
        measurement.add(dict(size=100, pts_time=pts, duration_time='N/A'))
    result = measurement.result(dict(duration=4, avg_frame_rate='1/1', nb_frames=4))
    assert result['average_bitrate_bps'] == 800
    assert result['duration_source'] == 'packet_pts+verified_final_frame_interval'
    for stream in (dict(duration=4), dict(duration=4, avg_frame_rate='60/1', nb_frames=4),
                   dict(duration=4, avg_frame_rate='1/1', nb_frames=8)):
        assert not measurement.result(stream)['reliable']


def test_unknown_or_disagreeing_timestamps_never_use_requested_rate():
    for packets in ([dict(size=100, pts_time='N/A', dts_time=0, duration_time=1)],
                    [dict(size=100, pts_time=0, duration_time=1)]):
        measurement = PacketMeasurement()
        for packet in packets:
            measurement.add(packet)
        result = measurement.result(dict(duration=10, bit_rate=10000000))
        assert result['average_bitrate_bps'] is None
        assert not result['reliable']


def test_streaming_probe_parses_named_fields_without_packet_json_buffer(tmp_path, monkeypatch):
    from twobyteasr.system import processes
    commands = []
    child = SimpleNamespace(stdout=io.StringIO('size=100|dts_time=0|pts_time=2|duration_time=1\n'
        'duration_time=1|size=100|pts_time=1|dts_time=1\n'), stderr=io.StringIO(''),
        wait=lambda:0, poll=lambda:0, returncode=0)
    monkeypatch.setattr(processes, 'popen_hidden_subprocess', lambda command, **kwargs: commands.append(command) or child)
    result = measure_packets(tmp_path/'ffmpeg.exe', tmp_path/'中文 空格.mp4', {'duration':'2'})
    assert result['packet_count'] == 2
    assert result['average_bitrate_bps'] == 800
    assert 'compact=p=0:nk=0' in commands[0]
    assert commands[0][-1] == str(tmp_path/'中文 空格.mp4')


def test_target_band_uses_video_measurement_excluding_audio_and_container():
    job = RenderJob('', '', '', RenderSettings(quality_mode='target', bitrate_kbps=10000))
    metadata = dict(average_bitrate_bps=11000000, audio_bitrate=[{'average_bitrate_bps':5000000}],
        video_bitrate=dict(reliable=True, average_bitrate_bps=5000000))
    assert target_comparison(job, metadata)['bitrate_target_met'] is False
    metadata['video_bitrate']['average_bitrate_bps'] = 9900000
    assert target_comparison(job, metadata)['bitrate_target_met'] is True
    metadata['video_bitrate']['reliable'] = False
    assert target_comparison(job, metadata)['bitrate_target_met'] is None
    job.settings.quality_mode = 'crf'
    assert target_comparison(job, metadata)['requested_video_bitrate_bps'] is None


def test_extreme_finite_timestamp_arithmetic_is_unknown_not_an_infinite_duration():
    measurement = PacketMeasurement()
    measurement.add(dict(size=100, pts_time='1e308', duration_time='1e308'))
    result = measurement.result({})
    assert not result['reliable']
    assert result['duration_seconds'] is None
    assert result['average_bitrate_bps'] is None
