"""Real staged media: bounded validation must preserve the publication gate."""
from pathlib import Path

import pytest

from twobyteasr.exports.export_validation import validate_output, validation_windows
from twobyteasr.exports.export_bitrate import export_bitrate_measurements
from twobyteasr.system.platform_media import ffmpeg_tool
from twobyteasr.system.processes import run_hidden_subprocess


@pytest.fixture
def media(tmp_path):
    ffmpeg = ffmpeg_tool()
    output = tmp_path / 'staged.mp4'
    run_hidden_subprocess([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i',
        'testsrc2=s=160x90:r=30:d=8', '-f', 'lavfi', '-i', 'sine=duration=8:sample_rate=48000',
        '-c:v', 'libx264', '-threads', '2', '-g', '30', '-c:a', 'aac', '-movflags', '+faststart', str(output)],
        purpose='validation fixture', check=True, capture_output=True, timeout=30)
    return ffmpeg, output


def test_quick_checks_real_windows_and_full_mode_still_decodes_every_frame(media, monkeypatch):
    from twobyteasr.exports import export_validation as validation
    ffmpeg, output = media
    original = validation.popen_hidden_subprocess
    commands = []
    def capture(command, **kwargs):
        commands.append(command)
        return original(command, **kwargs)
    monkeypatch.setattr(validation, 'popen_hidden_subprocess', capture)
    quick = validate_output(ffmpeg, output, duration=8, fps=30, expected_audio=True, cut_points=[3.0])
    assert quick['validation']['full_decode'] is False
    assert quick['validation']['coverage'] == 'metadata_and_bounded_samples'
    assert sum(w['decoded_video_frames'] for w in quick['validation']['windows']) < 120
    assert all('-ss' in c and c.index('-ss') < c.index('-i') and '-t' in c for c in commands)
    assert not any('select=' in item for c in commands for item in c)
    assert quick['video_bitrate']['bitrate_source'] == 'ffprobe.stream.bit_rate'
    full = validate_output(ffmpeg, output, duration=8, fps=30, mode='full')
    assert full['validation']['full_decode'] is True
    assert full['validation']['windows'][0]['decoded_video_frames'] == 240
    assert full['video_bitrate']['packet_count'] == 240
    assert full['video_bitrate']['average_bitrate_bps'] == pytest.approx(quick['video_bitrate']['average_bitrate_bps'], rel=.001)


def test_faststart_table_does_not_hide_truncated_payload(media):
    ffmpeg, output = media
    data = output.read_bytes()
    output.write_bytes(data[:len(data)//2])
    with pytest.raises(RuntimeError) as caught:
        validate_output(ffmpeg, output, duration=8, fps=30)
    assert '检查' in str(caught.value) or '验证' in str(caught.value)


def test_missing_audio_and_pre_cancel_are_failures(media, tmp_path):
    ffmpeg, output = media
    silent = tmp_path / 'silent.mp4'
    run_hidden_subprocess([str(ffmpeg), '-v', 'error', '-i', str(output), '-an', '-c:v', 'copy', str(silent)],
        purpose='missing audio fixture', check=True, capture_output=True, timeout=20)
    with pytest.raises(RuntimeError, match='音频'):
        validate_output(ffmpeg, silent, duration=8, expected_audio=True)
    with pytest.raises(InterruptedError):
        validate_output(ffmpeg, output, cancelled=lambda: True)
    assert not list(tmp_path.glob('*.validation.*'))


def test_ordinary_mux_metadata_skips_all_packet_walks(monkeypatch, tmp_path):
    from twobyteasr.exports import export_bitrate
    def forbidden(*args, **kwargs):
        pytest.fail('MP4 streams with duration+bit_rate must not trigger a full packet scan')
    monkeypatch.setattr(export_bitrate, 'measure_packets', forbidden)
    data = dict(streams=[dict(index=0, codec_type='video', duration='60', bit_rate='10000000'),
                         dict(index=1, codec_type='audio', duration='60', bit_rate='192000')],
                format=dict(bit_rate='11000000'))
    result = export_bitrate_measurements('ffmpeg', tmp_path / 'unused.mp4', data)
    assert result['video_bitrate']['average_bitrate_bps'] == 10_000_000
    assert result['audio_bitrate'][0]['average_bitrate_bps'] == 192_000


def test_sampling_work_is_bounded_for_many_cuts_and_includes_both_sides():
    windows = validation_windows(3600, 60, range(1, 3600))
    assert len(windows) <= 24
    assert sum(b-a for a, b in windows) < 7
    assert windows[0][0] == 0 and windows[-1][1] == 3600
    simple = validation_windows(10, 30, [3])
    assert any(a < 3 < b for a, b in simple)


def test_direct_route_fails_on_corrupt_source_before_tail_padding_can_hide_it(media, tmp_path):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia
    from twobyteasr.exports.export_timeline import write_export_ass
    from twobyteasr.exports.video_export import capture_video_graph
    from twobyteasr.exports.studio_render import RenderJob, RenderSettings, run_render_job
    app = QApplication.instance() or QApplication([])
    ffmpeg, source = media
    project = SubtitleProject(media=StudioMedia(str(source), duration_ms=8000, width=160, height=90))
    project.validate()
    ass = tmp_path/'subtitles.ass'; write_export_ass(project, ass)
    job = RenderJob(str(source), str(ass), str(tmp_path/'not-published.mp4'),
        RenderSettings(encoder='libx264', preset='ultrafast', fps=30, width=160, height=90),
        duration_seconds=8, video_graph=capture_video_graph(project))
    original = source.read_bytes()
    source.write_bytes(original[:len(original)//2])
    with pytest.raises(RuntimeError):run_render_job(ffmpeg, job)
    assert not Path(job.output_path).exists()
    assert job.export_context['failure']['stage'] == 'encode'
    assert job.export_context['failure']['returncode'] != 0
