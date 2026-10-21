"""Receipt statistics must describe the published container, not UI settings."""
from dataclasses import replace

import pytest

from twobyteasr.exports.studio_render import RenderJob


def test_container_metadata_is_cross_checked_against_real_bytes(tmp_path):
    from twobyteasr.exports.export_validation import completion_statistics
    output = tmp_path / 'final.mp4'
    output.write_bytes(b'x' * 1000)
    metadata = {'format': {'duration': '2', 'bit_rate': '4000'},
                'streams': [{'codec_type': 'video', 'bit_rate': '3000'}]}
    result = completion_statistics(output, metadata)
    assert result['size_bytes'] == 1000
    assert result['duration_seconds'] == 2
    assert result['average_bitrate_bps'] == 4000
    assert result['bitrate_source'] == 'ffprobe.format.bit_rate'
    assert result['bitrate_relative_error'] == 0
    metadata['format']['bit_rate'] = '9000'
    result = completion_statistics(output, metadata)
    assert result['average_bitrate_bps'] == 4000
    assert result['bitrate_source'] == 'file_bytes*8/container_duration'
    assert result['bitrate_relative_error'] == 1.25


@pytest.mark.parametrize('duration', ['N/A', None, '0', '-1', 'nan', 'inf'])
def test_unknown_duration_does_not_fabricate_bitrate(tmp_path, duration):
    from twobyteasr.exports.export_validation import completion_statistics
    output = tmp_path / 'final.mp4'; output.write_bytes(b'x')
    result = completion_statistics(output, {'format': {'duration': duration, 'bit_rate': '6000000'}})
    assert result['average_bitrate_bps'] is None
    assert result['duration_seconds'] is None


def test_receipt_is_shared_through_preparation_and_restarts_on_next_job(tmp_path, monkeypatch):
    from twobyteasr.exports import export_validation as receipts
    tick = iter([10.0, 12.4, 20.0, 23.0])
    monkeypatch.setattr(receipts.time, 'monotonic', lambda: next(tick))
    job = RenderJob('', '', str(tmp_path / 'final.mp4'), overwrite_existing=True)
    @receipts.record_completion
    def inner(job):
        staged = tmp_path / 'staged.mp4'; staged.write_bytes(b'x' * 1000)
        receipts.publish_output(staged, tmp_path / 'final.mp4', job,
            {'format': {'duration': '2', 'bit_rate': '4000'}})
    @receipts.record_completion
    def render(job):
        inner(replace(job))
    render(job)
    assert job.completion_metadata['elapsed_seconds'] == pytest.approx(2.4)
    assert job.completion_metadata['output_path'] == str(tmp_path / 'final.mp4')
    assert '_receipt_active' not in job.completion_metadata
    job.completion_metadata['stale'] = 'old'
    render(job)
    assert 'stale' not in job.completion_metadata
    assert job.completion_metadata['elapsed_seconds'] == 3


def test_failed_receipt_never_reuses_success_fields(tmp_path):
    from twobyteasr.exports.export_validation import record_completion
    job = RenderJob('', '', '', completion_metadata={'elapsed_seconds': 50, 'streams': [{}]})
    @record_completion
    def render(job):
        raise InterruptedError('cancelled')
    with pytest.raises(InterruptedError): render(job)
    assert job.completion_metadata == {}


def test_elapsed_rounding_preserves_tenths_and_carries_minutes():
    from twobyteasr.exports.export_success import elapsed_text
    assert elapsed_text(32.4) == '32.4 秒'
    assert elapsed_text(110.6) == '1 分 50.6 秒'
    assert elapsed_text(59.96) == '1 分 0.0 秒'
    assert elapsed_text(None) == '—'


def test_cancel_after_validation_preserves_existing_output(tmp_path):
    from twobyteasr.exports.export_validation import record_completion, publish_output
    final = tmp_path/'final.mp4'; final.write_bytes(b'previous verified output')
    staged = tmp_path/'staged.mp4'; staged.write_bytes(b'new validated output')
    job = RenderJob('', '', str(final))
    @record_completion
    def render(job):
        publish_output(staged, final, job, {'format': {'duration': '2'}}, cancelled=lambda: True)
    with pytest.raises(InterruptedError): render(job)
    assert final.read_bytes() == b'previous verified output'
    assert job.completion_metadata == {}
