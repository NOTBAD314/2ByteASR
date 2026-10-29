from pathlib import Path
from twobyteasr.rendering.advanced_renderer import _cache_overlay,_copy_verified_overlay
from twobyteasr.exports.studio_render import RenderJob
from twobyteasr.exports.studio_render_queue import QueuedRenderJob


def test_corrupted_overlay_is_a_cache_miss(tmp_path):
    source=tmp_path/'source.mov';source.write_bytes(b'original verified overlay')
    cached=tmp_path/'cache.mov';destination=tmp_path/'copy.mov'
    _cache_overlay(source,cached)
    assert _copy_verified_overlay(cached,destination)
    cached.write_bytes(b'corrupt but nonempty')
    destination.unlink()
    assert not _copy_verified_overlay(cached,destination) and not destination.exists()
    cached.with_suffix('.sha256').unlink()
    assert not _copy_verified_overlay(cached,destination)


def test_completion_receipt_is_not_persisted_in_queue_contract():
    job=RenderJob('video.mp4','text.ass','out.mp4',completion_preview_path='temporary.jpg',completion_metadata={'streams':[]})
    payload=QueuedRenderJob(job).to_dict()
    assert 'completion_metadata' not in payload['job']
    assert 'completion_preview_path' not in payload['job']
    restored=QueuedRenderJob.from_dict(payload).job
    assert restored.completion_metadata=={} and restored.completion_preview_path==''
