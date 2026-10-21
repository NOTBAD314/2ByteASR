"""Drag-preview press cost scales with prepared rasters, not with the selection.

2026-10-10 performance round 2: a multi-cue press built a style snapshot for
every dragged cue (~1.5 ms each) only to look them up in a cache that holds a
few prepared frames. Closing a project also kept those rasters (~64 MB).
"""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from twobyteasr.studio import studio_timing_preview as module


class _Snapshot:
    def __init__(self, cue_id, token="v1"):
        self.cue_id = cue_id
        self.token = token

    def stable_hash(self):
        return f"{self.cue_id}:{self.token}"


class _Pixmap:
    def width(self):
        return 100

    def height(self):
        return 10


class _Page(QObject):
    def __init__(self, cue_count):
        super().__init__()
        cues = [SimpleNamespace(id=f"c{i}", start_ms=i * 1000, end_ms=i * 1000 + 900) for i in range(cue_count)]
        self.project = SimpleNamespace(cues=cues)
        self.timeline = SimpleNamespace(playhead_ms=-1)
        self.video = SimpleNamespace(_paused=True)
        self._close_requested = True  # no follow-up warm work in these tests
        self.advanced_cue_overlay = SimpleNamespace(_snapshot=None, _source=None, _compiled_scene=None)
        self._advanced_live_inflight_key = ""
        timer = SimpleNamespace(stop=lambda: None)
        self._visual_update_timer = timer
        self._initial_preview_timer = timer

    def _advanced_preview_size(self):
        return 320, 180


def _preview(monkeypatch, cue_count):
    QApplication.instance() or QApplication([])
    built = []

    def build(project, cue_id, **_kwargs):
        built.append(cue_id)
        return _Snapshot(cue_id)
    monkeypatch.setattr(module, "build_visual_cue_snapshot", build)
    monkeypatch.setattr(module.CueTimingPreview, "present", lambda self: None)
    preview = module.CueTimingPreview(_Page(cue_count))
    return preview, built


def test_press_builds_snapshots_only_for_prepared_cues(monkeypatch):
    preview, built = _preview(monkeypatch, 300)
    entry = (_Pixmap(), _Snapshot("c5"), None)
    preview._cache[entry[1].stable_hash()] = entry
    preview.start({f"c{i}": object() for i in range(300)})
    assert built == ["c5"]
    assert preview.frames == {"c5": entry}


def test_stale_prepared_raster_is_not_used(monkeypatch):
    preview, built = _preview(monkeypatch, 3)
    preview._cache["c1:old"] = (_Pixmap(), _Snapshot("c1", "old"), None)
    preview.start({"c0": object(), "c1": object()})
    assert built == ["c1"]
    assert preview.frames == {}


def test_release_drops_rasters_and_fences_late_warm_results(monkeypatch):
    preview, _built = _preview(monkeypatch, 3)
    entry = (_Pixmap(), _Snapshot("c1"), None)
    preview._cache[entry[1].stable_hash()] = entry
    preview._cache_bytes = 4000
    generation = preview._warm_generation
    preview.release()
    assert preview._cache == {} and preview._cache_bytes == 0
    preview._ready(generation, "c2", (object(), None), _Snapshot("c2"))
    assert preview._cache == {}
