"""2026-11-22: GPU export without a current NVIDIA driver.

The bundled FFmpeg 9 builds NVENC against a new SDK, so older NVIDIA drivers
fail its probe; machines with AMD / Intel graphics only got the GPU by choosing
it by hand. Media Foundation hardware encoders go through the display driver's
own encoder and join the scan between the vendor encoders and software.
"""
from types import SimpleNamespace

import pytest

from twobyteasr.exports import studio_render
from twobyteasr.exports.studio_render import (
    CAPABILITY_SCHEMA, HARDWARE_ENCODERS, VIDEO_ENCODERS, RenderJob, RenderSettings,
    _quality_arguments, build_render_command, encoder_preset, hardware_encoders_for,
    probe_encoder_detail, render_fallback_job,
)


def test_media_foundation_sits_after_vendor_encoders_and_before_software():
    for codec, names in VIDEO_ENCODERS.items():
        mf = names.index(f'{codec}_mf')
        assert names.index(f'{codec}_amf') < mf < min(i for i, n in enumerate(names) if n.startswith('lib'))
        assert f'{codec}_mf' in HARDWARE_ENCODERS
    # Older capability caches never probed Media Foundation: they must rescan.
    assert CAPABILITY_SCHEMA >= 4


def test_probe_forces_hardware_media_foundation(monkeypatch):
    seen = []
    monkeypatch.setattr(studio_render, 'run_hidden_subprocess',
                        lambda command, **kw: seen.append(command) or SimpleNamespace(returncode=0, stderr=''))
    settings = RenderSettings(codec='h264', encoder='h264_mf', profile='high', level='4.1', preset='medium')
    detail = probe_encoder_detail('ffmpeg', 'h264_mf', settings=settings)
    command = seen[-1]
    assert detail['functional']
    assert command[command.index('-c:v') + 1:command.index('-c:v') + 4] == ['h264_mf', '-hw_encoding', '1']
    assert detail['pixel_format'] == command[command.index('-pix_fmt') + 1] == 'nv12'
    # Media Foundation rejects named profiles and has no speed presets.
    assert not {'-profile:v', '-level:v', '-preset'} & set(command)


def test_software_only_media_foundation_fails_the_probe(monkeypatch):
    # On a machine without a hardware encoder MFT, -hw_encoding 1 fails; the
    # encoder must not be offered (Microsoft's CPU MFT is slower than x264).
    monkeypatch.setattr(studio_render, 'run_hidden_subprocess', lambda command, **kw: SimpleNamespace(
        returncode=-40, stderr='could not find any MFT for the given media type'))
    assert not probe_encoder_detail('ffmpeg', 'hevc_mf')['functional']


def test_render_command_keeps_media_foundation_on_the_gpu(tmp_path, monkeypatch):
    media, ass = tmp_path / 'source.mp4', tmp_path / 'subtitle.ass'
    media.write_bytes(b'0'); ass.write_text('[Script Info]\n', encoding='utf-8')
    monkeypatch.setattr(studio_render, 'select_encoder', lambda _ffmpeg, settings: 'h264_mf')
    settings = RenderSettings(container='mp4', codec='h264', encoder='auto', quality_mode='cq', quality=24,
                              profile='high', level='4.1', preset='medium')
    command = build_render_command(tmp_path / 'ffmpeg.exe', RenderJob(str(media), str(ass), str(tmp_path / 'out.mp4'), settings))
    at = command.index('-c:v')
    assert command[at + 1:at + 4] == ['h264_mf', '-hw_encoding', '1']
    assert command[command.index('-pix_fmt') + 1] == 'nv12'
    assert command[command.index('-rate_control') + 1] == 'quality'
    assert command[command.index('-quality') + 1] == str(round((51 - 24) * 100 / 51))
    assert not {'-profile:v', '-level:v', '-preset', '-cq', '-crf'} & set(command)


@pytest.mark.parametrize(('mode', 'control', 'maxrate'), [
    ('cbr', 'cbr', False), ('target', 'u_vbr', False), ('vbr', 'pc_vbr', True), ('limited', 'pc_vbr', True)])
def test_media_foundation_bitrate_modes(mode, control, maxrate):
    settings = RenderSettings(encoder='hevc_mf', codec='hevc', quality_mode=mode, bitrate_kbps=8000, max_bitrate_kbps=12000)
    args = _quality_arguments('hevc_mf', settings)
    assert args[args.index('-rate_control') + 1] == control
    assert args[args.index('-b:v') + 1] == '8000k'
    assert ('-maxrate' in args) is maxrate


@pytest.mark.parametrize('quality', [0, 51, 99])
def test_media_foundation_quality_stays_in_range(quality):
    args = _quality_arguments('h264_mf', SimpleNamespace(quality_mode='cq', quality=quality))
    assert 1 <= int(args[args.index('-quality') + 1]) <= 100


def test_media_foundation_presets_are_dropped_and_failures_fall_back_to_software():
    assert encoder_preset('h264_mf', 'p4') == ''
    job = RenderJob('in.mp4', '', 'out.mp4', RenderSettings(codec='h264', encoder='h264_mf'))
    fallback = render_fallback_job(job, RuntimeError('format negotiation failed (1/0)'))
    assert fallback is not None and fallback[0].settings.encoder == 'libx264'


def test_media_foundation_counts_as_hardware(monkeypatch):
    monkeypatch.setattr(studio_render, 'cached_encoder_choices', lambda *_a: ['h264_mf', 'libx264'])
    assert hardware_encoders_for('h264', 'ffmpeg') == ['h264_mf']
