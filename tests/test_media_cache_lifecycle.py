"""Isolated media files: no ASR, provider calls, models or user data."""
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from twobyteasr.media.indexed_media import IndexedMediaCache
from twobyteasr.rendering.overlay_buffer import OverlayBuffer
from twobyteasr.rendering.overlay_session import ensure_overlay_session, register_overlay_worker, retire_overlay_session
from twobyteasr.storage.storage_service import StorageService


@pytest.fixture
def storage(tmp_path, monkeypatch):
    import twobyteasr.storage.storage_service as module
    service = StorageService(roots=(tmp_path,), state_root=tmp_path/'state')
    monkeypatch.setattr(module, 'StorageService', lambda: service)
    return service


def test_flv_suffix_does_not_schedule_or_make_full_copy(tmp_path):
    source = tmp_path/'recording.flv'; source.write_bytes(b'isolated fixture')
    cache = IndexedMediaCache(tmp_path/'cache')
    for _ in range(100):
        assert cache.resolve(str(source)) == str(source)
    assert not cache._requested and not cache.root.exists()


def test_explicit_fallback_deduplicates_and_regenerates_after_deletion(tmp_path):
    source = tmp_path/'recording.flv'; source.write_bytes(b'isolated fixture')
    cache = IndexedMediaCache(tmp_path/'cache')
    calls = []
    def prepare(path, cancel):
        calls.append(path)
        time.sleep(.02)
        target = tmp_path/'cache'/'fixture.mp4'; target.parent.mkdir(exist_ok=True)
        target.write_bytes(b'owned cache'); return target
    cache._prepare = prepare
    for _ in range(50):
        cache.resolve(str(source), reason='failed compatibility probe')
    target = Path(cache.wait_optimized(str(source), timeout=2))
    assert len(calls) == 1 and target.is_file()
    target.unlink()
    assert Path(cache.wait_optimized(str(source), timeout=2)).is_file()
    assert len(calls) == 2


def test_generation_lock_across_two_cache_instances(tmp_path):
    folder=tmp_path/'identity'; folder.mkdir()
    a=IndexedMediaCache(tmp_path); b=IndexedMediaCache(tmp_path)
    held=threading.Event(); acquired=threading.Event(); release=threading.Event()
    def first():
        with a._generation_lock(folder, threading.Event()):
            held.set(); release.wait(2)
    def second():
        with b._generation_lock(folder, threading.Event()): acquired.set()
    t1=threading.Thread(target=first);t1.start();assert held.wait(1)
    t2=threading.Thread(target=second);t2.start()
    assert not acquired.wait(.1)
    release.set(); t1.join(2);t2.join(2)
    assert acquired.is_set() and not (folder/'generation.lock').exists()


def test_same_path_changed_material_invalidates_compatibility_cache(tmp_path):
    source=tmp_path/'recording.flv';source.write_bytes(b'first')
    target=tmp_path/'optimized.mp4';target.write_bytes(b'first copy')
    cache=IndexedMediaCache(tmp_path/'cache');key=str(source)
    stat=source.stat();cache._ready[key]=str(target)
    cache._ready_identities[key]=(stat.st_size,stat.st_mtime_ns);cache._requested.add(key)
    source.write_bytes(b'changed recording content')
    assert cache.resolve(key)==key
    assert key not in cache._ready and key not in cache._requested


def test_remux_validation_preserves_each_selected_audio_track_offset():
    original=dict(format=dict(start_time='0',duration='6'),streams=[
        dict(codec_type='video',start_time='0'),dict(codec_type='audio',start_time='.1'),
        dict(codec_type='audio',start_time='.4')])
    correct=json.loads(json.dumps(original));IndexedMediaCache._validate(original,correct)
    wrong=json.loads(json.dumps(original));wrong['streams'][1]['start_time']='.3'
    with pytest.raises(RuntimeError,match='timing mismatch'):IndexedMediaCache._validate(original,wrong)


def test_source_missing_only_remaining_media_is_protected(tmp_path, storage):
    source=tmp_path/'original.flv'
    folder=tmp_path/'cache'/'v2'/'identity';folder.mkdir(parents=True)
    target=folder/'optimized.mp4';target.write_bytes(b'unique available copy')
    (folder/'ready.json').write_text(json.dumps(dict(source=str(source),container='mp4')))
    cache=IndexedMediaCache(tmp_path/'cache')
    assert cache.resolve(str(source)) == str(target)
    item=next(i for i in storage.scan(include_models=False).items if i.path==str(target))
    assert not item.cleanable and item.reason
    outcome=storage.clean([item])
    assert target.is_file()


def test_overlay_buffer_reuses_bounded_file_and_close_removes_bytes(tmp_path, storage):
    path=tmp_path/'one.rgba';buffer=OverlayBuffer(path, 16)
    for frame in range(100):buffer.write(bytes([frame])*16)
    assert len(list(tmp_path.glob('*.rgba'))) == 1
    item=next(i for i in storage.scan(include_models=False).items if i.path==str(path))
    assert not item.cleanable
    buffer.close();buffer.close()
    assert not path.exists()


class DelayedController:
    running=True
    def __init__(self):self.pending=[]
    def post_raw_overlay(self, overlay_id, path, on_applied=None, **geometry):
        self.pending.append((Path(path), on_applied));return True
    def post_remove_overlay(self, *args, **kwargs):return True
    def close(self):
        self.running=False
        for _, callback in self.pending:
            if callback:callback(False)
        self.pending.clear()


def test_sync_overlay_ack_protects_two_slots_and_reuses_identical_frame(tmp_path, storage, monkeypatch):
    from twobyteasr.studio import studio_video_canvas as module
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(module, 'studio_data_root', lambda:tmp_path)
    canvas=module.MpvCanvas();controller=DelayedController();canvas.controller=controller
    canvas._media_attached=True
    image=QImage(8,8,QImage.Format_ARGB32_Premultiplied);image.fill(0xffffffff)
    rect=QRect(0,0,8,8)
    assert canvas.publish_compositor_overlay(2,image,rect)
    path,ack=controller.pending.pop(0)
    assert path.is_file()
    ack(True)
    assert not path.exists()
    assert canvas.publish_compositor_overlay(2,image,rect)
    assert controller.pending == []  # no write/upload for unchanged pixels
    for value in (0xff0000ff,0xff00ff00):
        changed=QImage(image);changed.fill(value)
        assert canvas.publish_compositor_overlay(2,changed,rect)
    files=list(canvas._compositor_overlay_dir.glob('*.rgba'))
    assert len(files)==2
    previous={p:p.read_bytes() for p in files}
    changed=QImage(image);changed.fill(0xffff0000)
    assert not canvas.publish_compositor_overlay(2,changed,rect)
    assert all(p.read_bytes()==pixels for p,pixels in previous.items())
    canvas.close_player()
    deadline=time.monotonic()+2
    while canvas._compositor_overlay_dir.exists() and time.monotonic()<deadline:
        app.processEvents();time.sleep(.01)
    assert not canvas._compositor_overlay_dir.exists()
    canvas.deleteLater();app.processEvents()


def test_retired_session_does_not_delete_unexpected_assets(tmp_path):
    folder=tmp_path/'owned-session';ensure_overlay_session(folder)
    (folder/'overlay-0-sync-0.rgba').write_bytes(b'pixels')
    asset=folder/'adopted-design.png';asset.write_bytes(b'user art')
    retire_overlay_session(folder)
    deadline=time.monotonic()+2
    while (folder/'overlay-0-sync-0.rgba').exists() and time.monotonic()<deadline:time.sleep(.01)
    assert asset.read_bytes()==b'user art'
    assert not (folder/'overlay-0-sync-0.rgba').exists()


def test_session_waits_for_late_caption_pixels_then_removes_known_empty_dirs(tmp_path):
    folder=tmp_path/'owned-session';ensure_overlay_session(folder)
    release=threading.Event();entered=threading.Event()
    def render():
        entered.set();release.wait(2)
        for name in ('caption-scenes','caption-prepared'):
            directory=folder/name;directory.mkdir()
            (directory/('a'*32+'.rgba')).write_bytes(b'late pixels')
    worker=threading.Thread(target=render);register_overlay_worker(folder,worker)
    worker.start();assert entered.wait(1)
    retire_overlay_session(folder)
    assert folder.exists()
    release.set();worker.join(2)
    deadline=time.monotonic()+2
    while folder.exists() and time.monotonic()<deadline:time.sleep(.01)
    assert not folder.exists()
