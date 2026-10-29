"""Actual staged bytes: an audio-length container must not hide accelerated video."""
from pathlib import Path
import pytest

from twobyteasr.system.platform_media import ffmpeg_tool
from twobyteasr.system.processes import run_hidden_subprocess
from twobyteasr.exports.export_validation import validate_output


def encode(path, *, video_speed=1, audio_speed=1, vfr=False):
    ffmpeg = Path(ffmpeg_tool())
    filters = ["drawbox=x=0:y=0:w=30:h=30:color=white:t=fill:enable='between(mod(t,1),0.4,0.6)'"]
    if vfr:
        filters.append("select='if(lt(t,2),not(mod(n,2)),1)'")
    filters.append(f"setpts=PTS/({video_speed})")
    run_hidden_subprocess([str(ffmpeg), '-v', 'error', '-y', '-f', 'lavfi', '-i',
        'color=c=0x204080:s=160x90:r=60:d=4', '-f', 'lavfi', '-i',
        'sine=frequency=800:sample_rate=48000:duration=4', '-vf', ','.join(filters),
        '-af', f'atempo={audio_speed}', '-fps_mode:v', 'vfr', '-c:v', 'libx264',
        '-preset', 'ultrafast', '-c:a', 'aac', str(path)], purpose='export clock fixture',
        capture_output=True, check=True, timeout=20)
    return ffmpeg


@pytest.mark.parametrize('extension', ['mkv', 'mp4'])
def test_audio_length_cannot_hide_twice_speed_video(tmp_path, extension):
    path = tmp_path / ('bad.' + extension)
    ffmpeg = encode(path, video_speed=2)
    # MKV has no stream.duration/nb_frames here. Its format duration is still
    # four seconds because of the audio; the video actually ends at two.
    with pytest.raises(RuntimeError, match='视频.*(时长|时间轴)'):
        validate_output(ffmpeg, path, duration=4, fps=0)


@pytest.mark.parametrize('extension', ['mkv', 'mp4'])
@pytest.mark.parametrize('speed,vfr', [(1, False), (1, True), (.5, False), (2, False)])
def test_valid_video_clock_accepts_vfr_and_intentional_av_speed(tmp_path, extension, speed, vfr):
    path = tmp_path / ('good.' + extension)
    ffmpeg = encode(path, video_speed=speed, audio_speed=speed, vfr=vfr)
    data = validate_output(ffmpeg, path, duration=4/speed, fps=0)
    assert data['video_bitrate']['reliable']
    assert abs(data['video_bitrate']['duration_seconds'] - 4/speed) < .06


def test_short_audio_is_not_mistaken_for_fast_video(tmp_path):
    path = tmp_path / 'short-audio.mkv'
    ffmpeg = encode(path, audio_speed=2)
    data = validate_output(ffmpeg, path, duration=4, fps=0)
    assert data['video_bitrate']['duration_seconds'] > 3.9
    assert data['audio_bitrate'][0]['duration_seconds'] < 2.1


def test_render_job_never_publishes_accelerated_staged_video(tmp_path, monkeypatch):
    from twobyteasr.exports import studio_render
    broken = tmp_path / 'encoded-too-fast.mkv'
    ffmpeg = encode(broken, video_speed=2)
    output = tmp_path / 'delivered.mkv'
    job = studio_render.RenderJob(str(broken), '', str(output),
        studio_render.RenderSettings(container='mkv', encoder='libx264', fps=0),
        duration_seconds=4)

    # Inject broken encoder bytes at the command boundary. FFmpeg, staged
    # validation and the production publication path all remain real.
    def bad_encoder(executable, staged_job):
        return [str(executable), '-v', 'error', '-y', '-i', str(broken),
                '-map', '0', '-c', 'copy', '-progress', 'pipe:1', staged_job.output_path]
    monkeypatch.setattr(studio_render, 'build_render_command', bad_encoder)
    with pytest.raises(RuntimeError, match='视频实际时间轴'):
        studio_render.run_render_job(ffmpeg, job)
    assert not output.exists()
    assert 'output_path' not in job.completion_metadata
