"""Behavioral regressions for the September playback/interaction follow-up."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.playback.audio_engine import build_audio_mix_command
from twobyteasr.playback.audio_playback_graph import AudioPlaybackGraph
from twobyteasr.app.home_studio_entry import StudioEntryCard, studio_paper_colors
from twobyteasr.playback.secondary_video import SecondaryVideoSource
from twobyteasr.design.ui_theme import theme_definition
from twobyteasr.playback.video_compositor import VideoCompositionScene


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])




def test_all_four_video_tracks_share_one_audio_decision():
    layers = [dict(track_id=f"V{i}", source_path=f"v{i}.mp4", source_ms=i*1000) for i in range(1, 5)]
    graph = AudioPlaybackGraph()
    result = graph.decide(layers, base_track_id="V1")
    assert not result.mpv_output_enabled
    assert len(result.secondary_layers) == 4
    command = build_audio_mix_command("ffmpeg", result.secondary_layers)
    assert command.count("-i") == 4
    assert command.count("pipe:1") == 1
    assert [command[i+1] for i,item in enumerate(command) if item == "-ss"] == ["1.000000", "2.000000", "3.000000", "4.000000"]
    graph.configure(master_track_id="", solo_track_ids=("V3",))
    assert graph.decide(layers, base_track_id="V1").mix_track_ids == ("V3",)


def test_pending_seek_uses_one_decoder_generation_as_clock_advances(app):
    source = SecondaryVideoSource()
    source._ensure_thread = lambda: None
    source._pipe = SimpleNamespace(request=lambda *args: 1, close=lambda: True)
    for target in (5000, 5020, 5040, 5060):
        source.request_frame(target, paused=False, seek=True, seek_token=10)
    assert source.generation == 1
    source.request_frame(9000, paused=False, seek=True, seek_token=11)
    assert source.generation == 2
    source.close()


def test_timeline_cursor_reuses_static_pixels_but_edits_invalidate(app):
    from twobyteasr.studio.studio_timeline import WaveformTimeline
    timeline = WaveformTimeline(); timeline.resize(1200, 350); timeline.show()
    app.processEvents(); timeline.grab()
    original = timeline._static_timeline_cache[1].cacheKey()
    timeline.set_playhead(1000); app.processEvents(); timeline.grab()
    assert timeline._static_timeline_cache[1].cacheKey() == original
    timeline.set_waveform_state('LOADING', 'Preparing')
    app.processEvents(); timeline.grab()
    assert timeline._static_timeline_cache[1].cacheKey() != original
    timeline.close()


def test_static_transform_handles_are_reused_across_video_frames(app):
    scene = VideoCompositionScene(); scene.resize(1280, 720)
    image = QImage(320, 180, QImage.Format.Format_ARGB32); image.fill(0xffff0000)
    runtime = SimpleNamespace(image=image, pts_ms=0, frame_age_ms=0, generation=1)
    scene._players = {"clip": runtime}
    scene._layers = [dict(clip_id="clip", source_ms=0, fps=60, transform={"scale_x":.885,"scale_y":.885,"rotation":1.25})]
    scene.set_selected_clip("clip")
    scene._render_composition()
    key = scene._rendered_frames[1].cacheKey()
    runtime.pts_ms = 17
    scene._layers[0]['source_ms'] = 17
    scene._render_composition()
    assert scene._rendered_frames[1].cacheKey() == key
    scene._layers[0]['transform']['rotation'] = 2.5
    scene._render_composition()
    assert scene._rendered_frames[1].cacheKey() != key
    scene._players.clear(); scene.close()


