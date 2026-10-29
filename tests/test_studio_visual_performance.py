"""Regressions for hot-path IO and reparented read-only preview geometry."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from threading import Event, get_ident
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QObject, QRectF, QTimer, Signal, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.studio.studio_hub import StudioHubMixin
from twobyteasr.studio.studio_timeline import WaveformTimeline
from twobyteasr.studio.studio_video_flow import StudioVideoFlowMixin
from twobyteasr.playback.video_compositor import VideoCompositionScene


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_preview_follows_current_canvas_and_export_disables_editing(app):
    owner = QWidget(); owner.resize(1600, 1000)
    scene = VideoCompositionScene(owner); scene.set_video_size(1920, 1080)
    owner.show(); app.processEvents()
    assert scene.geometry().getRect() == (0, 50, 1600, 900)
    scene.set_selected_clip("clip")
    scene.set_interaction_enabled(False)
    scene.set_selected_clip("clip")  # Clock updates cannot restore export handles.
    assert scene._selected_clip_id == ""
    assert scene.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    owner.resize(518, 408); app.processEvents()
    assert scene.geometry().getRect() == (0, 58, 518, 292)
    scene.set_interaction_enabled(True); scene.set_selected_clip("clip")
    assert not scene.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    owner.close()


def test_preview_raster_cap_preserves_transformed_pixels(app):
    scene = VideoCompositionScene(); scene.resize(3840, 2160)
    sample = QImage(160, 90, QImage.Format.Format_ARGB32); sample.fill(0xffff0000)
    scene._players = {"clip": SimpleNamespace(image=sample, pts_ms=0, frame_age_ms=0, generation=1)}
    scene._layers = [dict(clip_id="clip", source_ms=0, fps=60, transform={
        "position_x": .75, "position_y": .5, "scale_x": .25, "scale_y": .25})]
    scene._render_composition()
    raster = scene._rendered_frames[0]
    assert (raster.width(), raster.height()) == (1920, 1080)
    assert raster.pixelColor(1440, 540).red() == 255
    assert raster.pixelColor(100, 100).alpha() == 0
    assert scene._layer_polygons["clip"].boundingRect().center().x() == pytest.approx(2880)
    scene._players.clear(); scene.close()


def test_waveform_cache_reuses_path_and_invalidates_view_or_source(app):
    class Cache:
        def __init__(self): self.reads = 0
        def read_window(self, *args):
            self.reads += 1
            from twobyteasr.playback.waveform_cache import WaveformLevel
            return WaveformLevel(0,2,500.,"fixture"), np.array([[-.5, .5], [-.3, .8]], dtype="float32")
    timeline = WaveformTimeline(); cache = Cache(); rect = QRectF(0, 100, 800, 28)
    def draw(target=cache, start=0, shape=rect):
        return timeline._waveform_envelope(target, start, 1000, 800, 0, 800, shape)
    first = draw()
    for _ in range(60): assert draw() == first
    assert cache.reads == 1
    assert draw(start=100) is not None
    assert draw(shape=rect.translated(0, 28)).boundingRect().center().y() == first.boundingRect().center().y()+28
    another = Cache(); draw(target=another)
    assert cache.reads == 2 and another.reads == 1
    timeline.close()


def test_media_path_resolution_happens_once_and_relink_is_not_stale(monkeypatch):
    calls = []
    monkeypatch.setattr(Path, "resolve", lambda path: calls.append(str(path)) or path)
    host = StudioVideoFlowMixin(); host.project = object()
    for _ in range(60): host._preview_media_path("source.mp4")
    assert calls == ["source.mp4"]
    assert host._preview_media_path("relinked.mp4") == "relinked.mp4"
    host.project = object(); host._preview_media_path("source.mp4")
    assert calls == ["source.mp4", "relinked.mp4", "source.mp4"]


def test_library_scan_does_not_block_ui_and_applies_results_on_ui_thread(app):
    entered = Event(); release = Event(); main_thread = get_ident()
    class Host(QObject, StudioHubMixin):
        library_records_ready_signal = Signal(object)
        def __init__(self):
            super().__init__(); self.project = None; self.applied = []
        def _project_library_records(self):
            assert get_ident() != main_thread
            entered.set(); release.wait(2)
            return [{"name": "fresh"}]
        def _rebuild_project_library(self):
            self.applied.append((get_ident(), self._hub_library_records))
    host = Host(); host._request_library_scan()
    assert entered.wait(1)
    assert host._hub_scan_pending and not host.applied
    release.set()
    loop = QEventLoop(); QTimer.singleShot(80, loop.quit); loop.exec()
    assert host.applied == [(main_thread, [{"name": "fresh"}])]
    assert not host._hub_scan_pending
