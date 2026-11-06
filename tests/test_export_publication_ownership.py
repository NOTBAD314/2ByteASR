"""Publication is atomic and successful bytes outlive notification failures."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from twobyteasr.exports import export_validation as receipts


def job(output, *, overwrite=False):
    return SimpleNamespace(output_path=str(output), completion_metadata={}, overwrite_existing=overwrite)


def test_new_destination_from_concurrent_writer_is_never_overwritten(tmp_path):
    final = tmp_path/'final.mp4'
    original = b'another completed export'
    staged = tmp_path/'staged.mp4'
    staged.write_bytes(b'this new export')
    current = job(final)
    @receipts.record_completion
    def render(job):
        final.write_bytes(original)  # Arrived after the job's initial target check.
        receipts.publish_output(staged, final, job, {'format': {'duration': '2'}})
    with pytest.raises(FileExistsError):
        render(current)
    assert final.read_bytes() == original
    assert current.completion_metadata == {}


def test_two_competing_publications_have_exactly_one_owner(tmp_path):
    final = tmp_path/'shared.mp4'
    barrier = threading.Barrier(2)
    jobs = [job(final), job(final)]
    values = [b'first verified bytes', b'second verified bytes']
    @receipts.record_completion
    def render(job, index):
        staged = tmp_path/f'{index}.mp4'
        staged.write_bytes(values[index])
        barrier.wait(timeout=5)
        receipts.publish_output(staged, final, job, {'format': {'duration': '2'}})
        return final
    def attempt(index):
        try:
            render(jobs[index], index)
            return True
        except FileExistsError:
            return False
    with ThreadPoolExecutor(max_workers=2) as executor:
        result = list(executor.map(attempt, range(2)))
    assert result.count(True) == 1
    winner = result.index(True)
    assert final.read_bytes() == values[winner]
    assert jobs[winner].completion_metadata['size_bytes'] == len(values[winner])
    assert jobs[1-winner].completion_metadata == {}


def test_explicit_overwrite_still_replaces_the_destination(tmp_path):
    final = tmp_path/'final.mp4'; final.write_bytes(b'old')
    staged = tmp_path/'staged.mp4'; staged.write_bytes(b'new')
    receipts.publish_output(staged, final, job(final, overwrite=True), {'format': {'duration': '2'}})
    assert final.read_bytes() == b'new'


def test_post_publication_observer_failure_preserves_success(tmp_path):
    final = tmp_path/'final.mp4'
    current = job(final)
    @receipts.record_completion
    def render(job):
        staged = tmp_path/'staged.mp4'; staged.write_bytes(b'verified')
        receipts.publish_output(staged, final, job, {'format': {'duration': '2'}})
        raise OSError('final progress persistence failed')
    assert render(current) == final
    assert final.read_bytes() == b'verified'
    assert current.completion_metadata['output_path'] == str(final)
    assert current.completion_metadata['completion_warnings'][0]['exception_type'] == 'OSError'
    assert '_receipt_active' not in current.completion_metadata


def test_final_notification_failure_does_not_skip_other_notifications(tmp_path):
    from twobyteasr.exports.export_validation import notify_after_publication
    final = tmp_path/'final.mp4'
    current = job(final)
    staged = tmp_path/'staged.mp4'; staged.write_bytes(b'verified')
    receipts.publish_output(staged, final, current, {'format': {'duration': '2'}})
    called = []
    def failed_progress(payload):
        raise OSError('observer failed')
    notify_after_publication(current, failed_progress, {'percent': '100'})
    notify_after_publication(current, called.append, 'trace completed')
    assert called == ['trace completed']
    assert current.completion_metadata['completion_warnings'][0]['exception_type'] == 'OSError'


def test_nested_failure_clears_receipt_only_before_commit(tmp_path):
    final = tmp_path/'final.mp4'
    current = job(final)
    @receipts.record_completion
    def inner(job):
        raise InterruptedError('cancel before publish')
    @receipts.record_completion
    def outer(job):
        return inner(job)
    with pytest.raises(InterruptedError):
        outer(current)
    assert current.completion_metadata == {}
    assert not final.exists()


def test_unsafe_metadata_is_rejected_before_the_file_is_published(tmp_path):
    staged = tmp_path/'staged.mp4'; staged.write_bytes(b'verified')
    final = tmp_path/'final.mp4'
    with pytest.raises((TypeError, ValueError, AttributeError)):
        receipts.publish_output(staged, final, job(final), {'format': []})
    assert not final.exists()
    assert staged.is_file()


def test_posix_publication_also_rejects_existing_output_atomically(tmp_path, monkeypatch):
    # Exercise the POSIX branch on Windows without changing pathlib's platform.
    monkeypatch.setattr(receipts, 'os', SimpleNamespace(name='posix', link=os.link, replace=os.replace))
    final = tmp_path/'final.mp4'
    staged = tmp_path/'staged.mp4'; staged.write_bytes(b'first')
    receipts.publish_output(staged, final, job(final), {'format': {'duration': '2'}})
    assert not staged.exists() and final.read_bytes() == b'first'
    staged.write_bytes(b'second')
    with pytest.raises(FileExistsError):
        receipts.publish_output(staged, final, job(final), {'format': {'duration': '2'}})
    assert final.read_bytes() == b'first'


def test_cleanup_error_after_posix_commit_keeps_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(receipts, 'os', SimpleNamespace(name='posix', link=os.link, replace=os.replace))
    final = tmp_path/'final.mp4'
    staged = tmp_path/'staged.mp4'; staged.write_bytes(b'verified')
    current = job(final)
    original_unlink = Path.unlink
    def fail_staged_cleanup(path, *args, **kwargs):
        if path == staged:
            raise PermissionError('staged cleanup temporarily blocked')
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', fail_staged_cleanup)
    receipts.publish_output(staged, final, current, {'format': {'duration': '2'}})
    assert final.read_bytes() == b'verified'
    assert current.completion_metadata['output_path'] == str(final)
    assert current.completion_metadata['completion_warnings'][0]['exception_type'] == 'PermissionError'


def test_late_observer_error_never_restarts_a_published_native_export(tmp_path, monkeypatch):
    from twobyteasr.exports import studio_render
    final = tmp_path/'final.mp4'
    current = studio_render.RenderJob('', '', str(final), studio_render.RenderSettings(encoder='h264_nvenc'))
    calls = []
    def attempt(ffmpeg, job, **kwargs):
        calls.append(job.settings.encoder)
        staged = tmp_path/'staged.mp4'; staged.write_bytes(b'verified')
        receipts.publish_output(staged, final, job, {'format': {'duration': '2'}})
        raise RuntimeError('nvenc observer unavailable after completion')
    monkeypatch.setattr(studio_render, '_run_render_attempt', attempt)
    assert studio_render.run_render_job('unused', current) == final
    assert calls == ['h264_nvenc']
    assert final.read_bytes() == b'verified'
