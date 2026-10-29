"""Barrier-controlled cancellation: QtCore only, fake CPU rasters, no GUI/GPU."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from shiboken6 import isValid

from twobyteasr.rendering import caption_playback_cache as cache_module
from twobyteasr.rendering import caption_scene as scene_module
from twobyteasr.rendering import caption_pixel_cache as pixel_module


@pytest.fixture(scope="module", autouse=True)
def app():
    application = QCoreApplication.instance() or QCoreApplication([])
    assert type(application) is QCoreApplication  # No QGuiApplication/QApplication or platform surface.
    yield application
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@dataclass(frozen=True)
class Snapshot:
    cue_id: str = "A"
    start_ms: int = 0
    end_ms: int = 1000
    appearance_generation: int = 0
    style_recipe: dict = field(default_factory=dict)
    def stable_hash(self): return "fixed-snapshot"


def cache_inputs(monkeypatch):
    from twobyteasr.caption_style import visual_snapshot
    cue = SimpleNamespace(id="A", style_id="default", base_preset_id="", appearance_override={})
    project = SimpleNamespace(cues=[cue], style_recipes={})
    revision = SimpleNamespace(project_id="project", mapping_revision=1, visual_revision=1,
                               cues=(cue,), timeline_cues=None)
    monkeypatch.setattr(cache_module, "materialize_captions", lambda *a, **k: (
        SimpleNamespace(project=project), set(), ""))
    monkeypatch.setattr(visual_snapshot, "build_visual_cue_snapshot", lambda *a, **k: Snapshot())
    monkeypatch.setattr(cache_module, "basic_caption", lambda *a, **k: None)
    return revision, visual_snapshot


def start_cache(cache, revision):
    finished = threading.Event()
    original = cache._work
    def work():
        try: original()
        finally: finished.set()
    cache._work = work
    cache.prepare(revision, ("A",), 64, 32)
    return finished


@pytest.mark.parametrize("phase", ["materialize", "snapshot", "fallback"])
def test_failed_work_after_close_cannot_refill_cache_or_emit(monkeypatch, phase):
    revision, visual = cache_inputs(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    def blocked_failure(*a, **k):
        entered.set()
        assert release.wait(3)
        raise ValueError("controlled old preparation failed")
    if phase == "materialize":
        monkeypatch.setattr(cache_module, "materialize_captions", blocked_failure)
    elif phase == "snapshot":
        monkeypatch.setattr(visual, "build_visual_cue_snapshot", blocked_failure)
    else:
        monkeypatch.setattr(visual, "build_visual_cue_snapshot", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad cue")))
        monkeypatch.setattr(cache_module, "basic_caption", blocked_failure)
    cache = cache_module.PlaybackCaptionCache()
    notifications = []
    cache.ready.connect(lambda *a: notifications.append(("ready", a)), Qt.DirectConnection)
    cache.failed.connect(lambda *a: notifications.append(("failed", a)), Qt.DirectConnection)
    finished = start_cache(cache, revision)
    try:
        assert entered.wait(3)
        cache.close()
        release.set()
        assert finished.wait(3)
        assert not cache._frames and not cache._failures and cache._materialized is None
        assert not notifications and not cache._running
    finally:
        cache.close(); release.set(); assert finished.wait(3)


@pytest.mark.parametrize("delete_target", ["cache", "parent"])
def test_qobject_deletion_retires_cache_before_worker_notification(monkeypatch, delete_target):
    revision, visual = cache_inputs(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    def blocked(*a, **k):
        entered.set()
        assert release.wait(3)
        return Snapshot()
    monkeypatch.setattr(visual, "build_visual_cue_snapshot", blocked)
    parent = QObject()
    cache = cache_module.PlaybackCaptionCache(parent)
    notifications = []
    cache.ready.connect(lambda *a: notifications.append(a), Qt.DirectConnection)
    finished = start_cache(cache, revision)
    try:
        assert entered.wait(3)
        (cache if delete_target == "cache" else parent).deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not isValid(cache) and cache._closed
        release.set()
        assert finished.wait(3)
        assert not notifications and not cache._frames and not cache._running
    finally:
        cache.close(); release.set(); assert finished.wait(3)


def test_normal_cache_results_still_publish_without_serializing_other_caches(monkeypatch):
    revision, visual = cache_inputs(monkeypatch)
    entered, release, fast_ready = threading.Event(), threading.Event(), threading.Event()
    def build(project, cue_id, **kwargs):
        if threading.current_thread().name == "slow-caption-test":
            entered.set()
            assert release.wait(3)
        return Snapshot()
    monkeypatch.setattr(visual, "build_visual_cue_snapshot", build)
    slow, fast = cache_module.PlaybackCaptionCache(), cache_module.PlaybackCaptionCache()
    original = slow._work
    def slow_work():
        threading.current_thread().name = "slow-caption-test"
        original()
    slow._work = slow_work
    fast.ready.connect(lambda *a: fast_ready.set(), Qt.DirectConnection)
    slow_done = start_cache(slow, revision)
    fast_done = None
    try:
        assert entered.wait(3)
        fast_done = start_cache(fast, revision)
        assert fast_ready.wait(3) and not release.is_set()
        assert fast.prepared(revision, "A", 64, 32) is not None
    finally:
        slow.close(); fast.close(); release.set()
        assert slow_done.wait(3)
        if fast_done is not None: assert fast_done.wait(3)


class Image:
    def sizeInBytes(self): return 4


class Page(QObject):
    def __init__(self, folder):
        super().__init__()
        self.project = object()
        self.video = SimpleNamespace(_compositor_overlay_dir=folder)


def start_scene(monkeypatch, tmp_path, frame, pack):
    class Rasterizer:
        def __init__(self, *a): pass
        def frame(self, *a, **k): return frame()
        def close(self): pass
    monkeypatch.setattr(scene_module, "SceneRasterizer", Rasterizer)
    monkeypatch.setattr(scene_module, "animated_caption", lambda _: False)
    monkeypatch.setattr(pixel_module, "prepared_pixels", pack)
    # Consumer/UI rendering is outside this producer-retirement test.
    monkeypatch.setattr(scene_module.CaptionScene, "accept", lambda *a: None)
    page = Page(tmp_path)
    scene = scene_module.CaptionScene(page)
    notifications = []
    scene.ready.connect(lambda *a: notifications.append(a), Qt.DirectConnection)
    token = (id(page.project), 1, 1, 1, ("A",), "", (64, 32, True), 0, 0, 64, 32)
    with scene.lock:
        scene.pending = (token, (("A", object()),), 0, 64, 32)
        scene.wake.set()
    return page, scene, notifications


def test_scene_close_during_raster_skips_packing_and_failure_emit(monkeypatch, tmp_path):
    entered, release = threading.Event(), threading.Event()
    packed = []
    def frame():
        entered.set(); assert release.wait(3)
        raise ValueError("old raster failed after close")
    page, scene, notifications = start_scene(monkeypatch, tmp_path, frame, lambda *a: packed.append(a))
    try:
        assert entered.wait(3)
        scene.close(); release.set(); scene.thread.join(3)
        assert not scene.thread.is_alive()
        assert not notifications and not packed and not scene.frames
    finally:
        scene.close(); release.set(); scene.thread.join(3)


def test_scene_close_during_packing_releases_unadopted_pixels_and_lease(monkeypatch, tmp_path):
    entered, release = threading.Event(), threading.Event()
    released = []
    path = tmp_path / "owned.rgba"
    class Lease:
        def __exit__(self, *a): released.append(True)
    def pack(*a):
        path.write_bytes(b"rgba")
        value = pixel_module.PreparedPixels(Image(), None, 0, 1, path, {}, Lease())
        entered.set(); assert release.wait(3)
        return value
    page, scene, notifications = start_scene(monkeypatch, tmp_path,
        lambda: (Image(), [{"cue_id": "A", "status": "rendered"}]), pack)
    try:
        assert entered.wait(3) and path.exists()
        scene.close(); release.set(); scene.thread.join(3)
        assert not scene.thread.is_alive()
        assert not scene.frames and not notifications
        assert released == [True] and not path.exists()
    finally:
        scene.close(); release.set(); scene.thread.join(3)


def test_scene_deletion_blocks_worker_and_late_web_signals(monkeypatch, tmp_path):
    entered, release = threading.Event(), threading.Event()
    def frame():
        entered.set(); assert release.wait(3)
        return Image(), [{"cue_id": "A", "status": "rendered"}]
    packed = []
    page, scene, notifications = start_scene(monkeypatch, tmp_path, frame, lambda *a: packed.append(a))
    web_callback = scene.web_cache.changed
    try:
        assert entered.wait(3)
        scene.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not isValid(scene) and scene.closed
        web_callback()  # A completion captured before QObject destruction.
        release.set(); scene.thread.join(3)
        assert not scene.thread.is_alive() and not notifications and not packed
    finally:
        scene.close(); release.set(); scene.thread.join(3)


def test_published_pixels_remain_owned_by_consumer_until_release(monkeypatch, tmp_path):
    ready = threading.Event()
    released = []
    path = tmp_path / "published.rgba"
    class Lease:
        def __exit__(self, *a): released.append(True)
    def pack(*a):
        path.write_bytes(b"rgba")
        return pixel_module.PreparedPixels(Image(), None, 0, 1, path, {}, Lease())
    page, scene, notifications = start_scene(monkeypatch, tmp_path,
        lambda: (Image(), [{"cue_id": "A", "status": "rendered"}]), pack)
    # Work may have finished before this observer is connected; the retained
    # notifications are the actual consumer ownership, not a timer assumption.
    scene.ready.connect(lambda *a: ready.set(), Qt.DirectConnection)
    try:
        if not notifications: assert ready.wait(3)
        assert len(notifications) == 1 and path.exists()
        scene.close(); scene.thread.join(3)
        assert not scene.thread.is_alive() and not scene.frames
        assert path.exists() and not released
        # A signal queued before retirement also legitimately owns its payload
        # until its receiver consumes/discards it.
        QCoreApplication.processEvents()
        notifications.clear()
        assert not path.exists() and released == [True]
    finally:
        scene.close(); scene.thread.join(3); notifications.clear()
