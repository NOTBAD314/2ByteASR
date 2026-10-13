"""Back-to-back cues swap in one overlay update during playback.

2026-10-12: when the next cue set's raster was not cached yet, CaptionScene
withdrew the old bitmap first and published the new one 50-450 ms later
(measured on the user's session), so back-to-back cues blinked empty. During
ordinary playback the old raster now stays until the new one replaces it,
bounded by HOLD_PREVIOUS_MS; seeks, pauses, geometry changes and real gaps
still withdraw at once, and a gap withdraws only once.
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEventLoop, QObject, QRectF, QTimer
from PySide6.QtWidgets import QApplication

from twobyteasr import caption_scene as scene_module
from twobyteasr.caption_playback_cache import PreparedCaption
from twobyteasr.caption_scene import CaptionScene
from twobyteasr.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, SubtitleStyle
from twobyteasr.style_recipe import RecipeRoute
from twobyteasr.visual_snapshot import build_visual_cue_snapshot


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _spin(seconds):
    loop = QEventLoop()
    QTimer.singleShot(int(seconds * 1000), loop.quit)
    loop.exec()


def _until(condition, seconds=3.0):
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        if condition():
            return True
        _spin(0.01)
    return condition()


class FakeVideo:
    ADVANCED_OVERLAY_ID = 1

    def __init__(self):
        self._paused = False
        self._playback_rate = 1.0
        self._web_live_epoch = 0
        import tempfile
        self._compositor_overlay_dir = Path(tempfile.mkdtemp(prefix="caption-handoff-"))
        self._playback_clock = SimpleNamespace(generation=1)
        self.calls = []

    def playback_position_snapshot(self):
        return SimpleNamespace(playback_generation=self._playback_clock.generation)

    def remove_compositor_overlay(self, overlay_id, *, force=False, context=None):
        self.calls.append(("remove", overlay_id))
        return True

    def publish_compositor_overlay(self, overlay_id, image, rect, *, prepared_pixels=None, context=None):
        self.calls.append(("publish", tuple(context["expected_cue_ids"])))
        return True

    def set_native_subtitle_visible(self, visible):
        pass

    def clear_caption_boundaries(self):
        pass

    def devicePixelRatioF(self):
        return 1.0


class FakePage(QObject):
    def __init__(self, project):
        super().__init__()
        self.project = project
        self.video = FakeVideo()
        self.session = SimpleNamespace(runtime=None)
        self.timeline = SimpleNamespace(hidden_speakers=set(), _speaker_ids=["S0"])
        self._subtitle_track_visibility = {}
        self._revision_store = SimpleNamespace(render=SimpleNamespace(mapping_revision=1, visual_revision=1))
        self.position_overlay = SimpleNamespace(_content_rect=lambda: QRectF(0, 0, 320, 180))
        self._visual_ownership = SimpleNamespace(commit=lambda *a, **k: None)
        self.save_state = SimpleNamespace(text=lambda: "", setToolTip=lambda *_: None)
        self.undo_stack = SimpleNamespace(isClean=lambda: True)
        self.now_ms = 0
        self.traces = []
        self._prepared = {}

    def _studio_trace(self, event, **fields):
        self.traces.append((event, fields))

    def _caption_sample_ms(self, milliseconds=None):
        return self.now_ms

    def _prepared_caption(self, cue_id):
        return self._prepared.get(cue_id)

    def _prepare_caption_window(self, *_a, **_k):
        pass

    def _stop_web_live_preview(self, *_a):
        pass

    def _revoke_advanced_preview(self, **_k):
        pass

    def _audio_tail_visual_active(self):
        return False

    def _present_caption_scene(self):
        pass


def _page():
    project = SubtitleProject(
        media=StudioMedia("", width=320, height=180, duration_ms=10_000),
        render_settings={"play_res_x": 320, "play_res_y": 180, "_cue_domain": "timeline"},
        cues=[StudioCue("a", 0, 1000, "第一句", speaker_id="S0", style_id="s"),
              StudioCue("b", 1000, 2000, "第二句", speaker_id="S0", style_id="s"),
              StudioCue("c", 3000, 4000, "第三句", speaker_id="S0", style_id="s")],
        speakers=[StudioSpeaker("S0")],
        styles=[SubtitleStyle("s", "s", font_size=24, outline_width=0, shadow=0, position_x=160, position_y=150)])
    page = FakePage(project)
    for cue in project.cues:
        snapshot = build_visual_cue_snapshot(project, cue.id, width=320, height=180)
        page._prepared[cue.id] = PreparedCaption(snapshot, snapshot.stable_hash(), RecipeRoute("native", ()))
    return page


def _present(scene, page, ms):
    page.now_ms = ms
    cues = [c for c in page.project.cues if c.start_ms <= ms < c.end_ms]
    scene.present(cues, ms)


def _slow_frames(monkeypatch, seconds):
    original = scene_module.SceneRasterizer.frame

    def frame(self, *args, **kwargs):
        if threading.current_thread().name == "caption-scene":
            time.sleep(seconds)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(scene_module.SceneRasterizer, "frame", frame)


def test_playing_handoff_replaces_previous_raster_without_blank(app, monkeypatch):
    monkeypatch.setattr(scene_module, "PREHEAT_MIN_BOUNDARIES", 0)  # force a cache miss
    page = _page()
    scene = CaptionScene(page)
    try:
        _present(scene, page, 100)
        assert _until(lambda: ("publish", ("a",)) in page.video.calls)
        page.video.calls.clear()
        _slow_frames(monkeypatch, 0.12)
        _present(scene, page, 1000)
        assert ("remove", 1) not in page.video.calls
        assert any(event == "CAPTION_SCENE_HELD" for event, _ in page.traces)
        assert _until(lambda: ("publish", ("b",)) in page.video.calls)
        assert ("remove", 1) not in page.video.calls
        held = [f for e, f in page.traces if e == "CAPTION_SCENE" and f.get("held_previous_ms") is not None]
        assert held and held[-1]["held_previous_ms"] < scene_module.HOLD_PREVIOUS_MS
    finally:
        scene.close()


def test_late_raster_retires_previous_after_bounded_hold(app, monkeypatch):
    monkeypatch.setattr(scene_module, "PREHEAT_MIN_BOUNDARIES", 0)
    page = _page()
    scene = CaptionScene(page)
    try:
        _present(scene, page, 100)
        assert _until(lambda: ("publish", ("a",)) in page.video.calls)
        page.video.calls.clear()
        _slow_frames(monkeypatch, 0.6)
        _present(scene, page, 1000)
        assert _until(lambda: ("remove", 1) in page.video.calls, seconds=1.0)
        retired = [f for e, f in page.traces if e == "CAPTION_SCENE_RETIRED"]
        assert retired and retired[-1].get("reason") == "hold_timeout"
        assert retired[-1]["held_ms"] >= scene_module.HOLD_PREVIOUS_MS - 20
    finally:
        scene.close()


def test_paused_navigation_still_withdraws_immediately(app, monkeypatch):
    monkeypatch.setattr(scene_module, "PREHEAT_MIN_BOUNDARIES", 0)
    page = _page()
    scene = CaptionScene(page)
    try:
        _present(scene, page, 100)
        assert _until(lambda: ("publish", ("a",)) in page.video.calls)
        page.video.calls.clear()
        _slow_frames(monkeypatch, 0.12)
        page.video._paused = True
        _present(scene, page, 1500)
        assert page.video.calls[:1] == [("remove", 1)]
        # A seek while playing changes the clock generation: also immediate.
        page.video._paused = False
        page.video.calls.clear()
        page.video._playback_clock.generation = 2
        _present(scene, page, 3500)
        assert ("remove", 1) in page.video.calls
    finally:
        scene.close()


def test_gap_withdraws_once_not_every_tick(app):
    page = _page()
    scene = CaptionScene(page)
    try:
        _present(scene, page, 1500)
        assert _until(lambda: ("publish", ("b",)) in page.video.calls)
        page.video.calls.clear()
        for ms in range(2000, 3000, 16):
            _present(scene, page, ms)
        assert page.video.calls.count(("remove", 1)) == 1
    finally:
        scene.close()


def test_chained_holds_share_one_deadline(app, monkeypatch):
    """A short middle cue whose raster never showed does not extend the hold."""
    monkeypatch.setattr(scene_module, "PREHEAT_MIN_BOUNDARIES", 0)
    page = _page()
    page.project.cues.insert(1, StudioCue("a2", 1000, 1050, "短", speaker_id="S0", style_id="s"))
    page.project.cues[0].end_ms = 1000
    page.project.cues[2].start_ms = 1050
    for cue in page.project.cues:
        snapshot = build_visual_cue_snapshot(page.project, cue.id, width=320, height=180)
        page._prepared[cue.id] = PreparedCaption(snapshot, snapshot.stable_hash(), RecipeRoute("native", ()))
    scene = CaptionScene(page)
    try:
        _present(scene, page, 100)
        assert _until(lambda: ("publish", ("a",)) in page.video.calls)
        page.video.calls.clear()
        _slow_frames(monkeypatch, 0.6)
        started = time.perf_counter()
        _present(scene, page, 1000)   # short cue, raster late
        _spin(0.2)
        _present(scene, page, 1100)   # next cue, raster late too
        assert _until(lambda: ("remove", 1) in page.video.calls, seconds=1.0)
        # Retired about HOLD_PREVIOUS_MS after the first stale moment, not 0.2 s later.
        assert (time.perf_counter() - started) * 1000 < scene_module.HOLD_PREVIOUS_MS + 150
    finally:
        scene.close()
