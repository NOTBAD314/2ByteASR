"""Rate-control construction only: no capabilities, devices or child processes."""
import subprocess

import pytest

from twobyteasr.exports import studio_render
from twobyteasr.exports.studio_render import RenderSettings, _quality_arguments


@pytest.fixture(autouse=True)
def reject_native_boundaries(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('native probing/encoding forbidden in rate-control unit tests')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(studio_render, 'select_encoder', forbidden)
    monkeypatch.setattr(studio_render, '_run_probe', forbidden)


ENCODERS = ('h264_qsv', 'hevc_qsv', 'av1_qsv', 'h264_amf', 'hevc_amf', 'av1_amf',
            'libx264', 'h264_nvenc')


@pytest.mark.parametrize('target', [5000, 10000, 20000])
@pytest.mark.parametrize('encoder', ENCODERS)
def test_target_does_not_apply_unselected_maxrate_or_constant_quality(encoder, target):
    # Deliberately leave the stale maximum below target: target does not select
    # that field, and a 20 Mbps request must not become constrained by 18 Mbps.
    settings = RenderSettings(encoder=encoder, quality_mode='target', bitrate_kbps=target,
        max_bitrate_kbps=18000, quality=20)
    settings.validate()
    args = _quality_arguments(encoder, settings)
    assert args[args.index('-b:v')+1] == f'{target}k'
    assert not any(flag in args for flag in ('-maxrate', '-bufsize', '-crf', '-cq', '-global_quality',
                                            '-qp_i', '-qp_p', '-filler_data', '-enforce_hrd'))
    if encoder.endswith('_amf'):
        assert args[args.index('-rc')+1] == 'vbr_peak'
    elif encoder.endswith('_nvenc'):
        assert args[args.index('-rc')+1] == 'vbr'
    else:
        assert '-rc' not in args


@pytest.mark.parametrize('target', [5000, 10000, 20000])
@pytest.mark.parametrize('encoder', ENCODERS)
def test_limited_continues_to_apply_explicit_maximum_separately(encoder, target):
    maximum = target+7000
    settings = RenderSettings(encoder=encoder, quality_mode='limited', bitrate_kbps=target,
        max_bitrate_kbps=maximum)
    settings.validate()
    args = _quality_arguments(encoder, settings)
    assert args[args.index('-b:v')+1] == f'{target}k'
    assert args[args.index('-maxrate')+1] == f'{maximum}k'
    assert not any(flag in args for flag in ('-crf', '-cq', '-global_quality', '-qp_i', '-qp_p'))
    if encoder.endswith('_amf'):
        assert args[args.index('-rc')+1] == 'vbr_peak'
    elif encoder.endswith('_nvenc'):
        assert args[args.index('-rc')+1] == 'vbr'
