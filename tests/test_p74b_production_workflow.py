from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QUndoStack
from PySide6.QtTest import QTest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from twobyteasr.app.single_instance import SingleInstanceGuard
from twobyteasr.system.processes import main_python_executable
from twobyteasr.exports.studio_export_ui import StudioExportWorkspace
from twobyteasr.timeline.studio_media_commands import AudioMasterCommand, media_graph_command
from twobyteasr.timeline.studio_media_pool import (
    add_media_asset,
    add_video_clip,
    audio_master_track_id,
    create_video_track,
    set_audio_master_track,
    update_video_clip_transform,
)
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    SubtitleStyle,
    load_project,
    save_project,
)
from twobyteasr.studio.studio_ui import SubtitleStudioPage, WaveformTimeline
from twobyteasr.caption_style.style_presets import StylePresetStore
from twobyteasr.caption_style.style_resolution import resolve_cue_visual
from twobyteasr.playback.video_compositor import VideoCompositionScene
from twobyteasr.rendering.visual_runtime import VisualOwner


APP = QApplication.instance() or QApplication([])


def test_frozen_helpers_never_relaunch_the_gui_executable(tmp_path, monkeypatch):
    root = tmp_path / "release"
    root.mkdir()
    exe = root / "2ByteASR.exe"
    exe.write_bytes(b"fixture")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    # Keep the machine's registered/legacy runtime venvs (including this
    # checkout's own .venv-main on a dev machine) out of the test: it
    # verifies the last-resort exe-directory fallback below them.
    monkeypatch.setattr(
        "twobyteasr.system.runtime_registry.resolve_runtime_python", lambda _role: ""
    )

    assert main_python_executable() == ""
    python = root / ".venv-main" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"fixture")
    assert Path(main_python_executable()) == python.resolve()
    assert Path(main_python_executable()) != exe.resolve()
ROOT = Path(__file__).resolve().parents[1]


def _project(tmp_path: Path) -> SubtitleProject:
    primary = tmp_path / "primary.mp4"
    overlay = tmp_path / "overlay.mp4"
    primary.write_bytes(b"primary")
    overlay.write_bytes(b"overlay")
    project = SubtitleProject(
        media=StudioMedia(
            path=str(primary), duration_ms=8_000, width=1920, height=1080,
        ),
        cues=[
            StudioCue("cue-a", 0, 2_000, "alpha subtitle"),
            StudioCue("cue-b", 2_500, 4_500, "beta subtitle"),
        ],
    )
    project.validate()
    project.video_tracks[0].locked = False
    asset = add_media_asset(
        project, overlay, fingerprint="overlay", duration_ms=8_000,
    )
    track = create_video_track(project, "Picture in picture")
    add_video_clip(project, track.id, asset.asset_id, timeline_in_ms=0)
    project.validate()
    return project


def _start_instance_owner(name: str) -> subprocess.Popen[str]:
    code = (
        "from PySide6.QtCore import QCoreApplication,QTimer\n"
        "from twobyteasr.app.single_instance import SingleInstanceGuard\n"
        "import sys\n"
        "app=QCoreApplication([])\n"
        "guard=SingleInstanceGuard(sys.argv[1])\n"
        "assert guard.acquire()\n"
        "print('READY',flush=True)\n"
        "QTimer.singleShot(15000,app.quit)\n"
        "app.exec()\n"
        "guard.release()\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    process = subprocess.Popen(
        [sys.executable, "-B", "-c", code, name],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "READY"
    return process


def test_single_instance_live_released_and_crashed_endpoint_recovery():
    name = f"2ByteASR-p74b-{uuid.uuid4().hex}"
    owner = _start_instance_owner(name)
    contender = SingleInstanceGuard(name)
    try:
        assert contender.acquire(connect_timeout_ms=1_000) is False
    finally:
        owner.kill()
        owner.wait(timeout=5)

    recovered = SingleInstanceGuard(name)
    deadline = time.monotonic() + 3.0
    while not recovered.acquire(connect_timeout_ms=100):
        assert time.monotonic() < deadline
        QTest.qWait(25)
    assert recovered.owns_endpoint
    recovered.release()

    relaunched = SingleInstanceGuard(name)
    assert relaunched.acquire()
    relaunched.release()


def test_video_transform_audio_master_undo_redo_and_save_reopen(tmp_path):
    project = _project(tmp_path)
    track = project.video_tracks[1]
    clip = track.clips[0]
    source_timing = (
        clip.source_in_ms, clip.source_out_ms,
        clip.timeline_in_ms, clip.timeline_out_ms,
    )
    stack = QUndoStack()
    stack.push(media_graph_command(
        project,
        "Adjust V2 transform",
        lambda working: update_video_clip_transform(working, track.id, clip.id, {
            "position_x": 0.78,
            "position_y": 0.22,
            "scale_x": 0.46,
            "scale_y": 0.46,
            "rotation": 7.5,
            "opacity": 0.82,
            "anchor_x": 0.5,
            "anchor_y": 0.5,
            "fit_mode": "cover",
        }),
    ))
    assert project.video_tracks[1].clips[0].transform.position_x == 0.78
    assert source_timing == (
        clip.source_in_ms, clip.source_out_ms,
        clip.timeline_in_ms, clip.timeline_out_ms,
    )
    stack.undo()
    assert project.video_tracks[1].clips[0].transform.position_x == 0.5
    stack.redo()
    assert project.video_tracks[1].clips[0].transform.fit_mode == "cover"

    set_audio_master_track(project,"V1")
    stack.push(AudioMasterCommand(project, track.id))
    assert audio_master_track_id(project) == track.id
    stack.undo()
    assert audio_master_track_id(project) == "V1"
    stack.redo()

    path = save_project(project, tmp_path / "multitrack.2byteproj")
    reopened = load_project(path)
    restored = reopened.video_tracks[1].clips[0]
    assert restored.transform.position_x == 0.78
    assert restored.transform.scale_x == 0.46
    assert restored.transform.opacity == 0.82
    assert restored.transform.fit_mode == "cover"
    assert audio_master_track_id(reopened) == track.id


def test_video_lanes_are_pinned_below_subtitle_lanes(tmp_path):
    project = _project(tmp_path)
    timeline = WaveformTimeline()
    timeline.resize(1200, 320)
    timeline.set_project(project)
    timeline.show()
    APP.processEvents()

    speaker_rects, translation_rect, _waveform = timeline._track_layout()
    video_rects = timeline._video_track_rects()
    subtitle_bottom = max(
        [rect.bottom() for rect in speaker_rects.values()]
        + ([translation_rect.bottom()] if translation_rect is not None else [])
    )
    assert set(video_rects) == {"V1", "V2"}
    assert subtitle_bottom <= min(rect.top() for rect in video_rects.values())
    assert video_rects["V2"].bottom() <= video_rects["V1"].top()  # higher z-order is the upper lane
    assert timeline.minimumHeight() == 278  # V1/A1 and V2/A2 compact linked groups
    timeline.deleteLater()


def test_two_speaker_lanes_do_not_overlap_two_video_lanes(tmp_path):
    project = _project(tmp_path)
    project.speakers.append(StudioSpeaker("S02", "Guest"))
    project.cues.append(
        StudioCue("cue-s02", 5_000, 7_000, "guest subtitle", speaker_id="S02")
    )
    project.validate()
    timeline = WaveformTimeline()
    timeline.resize(1200, timeline.minimumHeight())
    timeline.set_project(project)
    timeline.resize(1200, timeline.minimumHeight())
    timeline.show()
    APP.processEvents()

    speaker_rects, translation_rect, _waveform = timeline._track_layout()
    video_rects = timeline._video_track_rects()
    subtitle_bottom = max(
        [rect.bottom() for rect in speaker_rects.values()]
        + ([translation_rect.bottom()] if translation_rect is not None else [])
    )
    assert set(speaker_rects) == {"S00", "S02"}
    assert subtitle_bottom <= min(rect.top() for rect in video_rects.values())
    timeline.deleteLater()


class _FrameRuntime:
    def __init__(self) -> None:
        self.image = QImage(320, 180, QImage.Format.Format_ARGB32)
        self.image.fill(0xFF4E89B8)


def test_video_compositor_canvas_drag_commits_transform_with_qtest():
    scene = VideoCompositionScene()
    scene.resize(640, 360)
    scene._layers = [{
        "track_id": "V2",
        "clip_id": "v2-clip",
        "transform": {
            "position_x": 0.75, "position_y": 0.25,
            "scale_x": 0.5, "scale_y": 0.5,
            "rotation": 0.0, "opacity": 1.0,
            "anchor_x": 0.5, "anchor_y": 0.5,
            "fit_mode": "contain",
        },
    }]
    scene._players = {"v2-clip": _FrameRuntime()}
    scene.set_selected_clip("v2-clip")
    committed = []
    scene.transform_committed.connect(
        lambda track_id, clip_id, values: committed.append(
            (track_id, clip_id, dict(values))
        )
    )
    scene.show()
    scene.repaint()
    APP.processEvents()
    polygon = scene._layer_polygons["v2-clip"]
    start = polygon.boundingRect().center().toPoint()
    end = start + QPoint(32, 24)
    QTest.mousePress(scene, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(scene, end, delay=10)
    QTest.mouseRelease(scene, Qt.MouseButton.LeftButton, pos=end)
    APP.processEvents()

    assert committed and committed[-1][:2] == ("V2", "v2-clip")
    assert committed[-1][2]["position_x"] > 0.75
    assert committed[-1][2]["position_y"] > 0.25
    scene._players = {}
    scene.deleteLater()


def test_multitrack_promotes_native_subtitle_to_live_foreground(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    path = save_project(_project(tmp_path), tmp_path / "foreground.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        page.video_compositor, "set_composition", lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        type(page.video_compositor), "has_video_overlays", property(lambda _self: True),
    )
    page.resize(1400, 850)
    page.show()
    page.open_project(path)
    page.timeline.set_playhead(1_000)
    secondary = page.project.video_tracks[1].clips[0]
    page._video_clip_selected("V2", secondary.id)
    assert page.video_compositor._selected_clip_id == secondary.id
    page._follow_playhead_selection(1_000)
    assert page.timeline.selected_video_clip_id == secondary.id
    assert page.selected_cue_id == ""
    page.select_cue("cue-a")
    APP.processEvents()

    assert page.timeline.selected_video_clip_id == ""
    assert page.video_compositor._selected_clip_id == ""

    page._sync_video_compositor(1_000)
    assert page._multitrack_composition_active
    page._activate_selected_advanced_if_needed(force=True)
    # LIVE rasterization runs off the GUI thread; wait for its ready signal.
    deadline = time.monotonic() + 5
    while page.advanced_cue_overlay._source.isNull() and time.monotonic() < deadline:
        QTest.qWait(20)
    trace = page.ensure_active_subtitle_renderer(reason="p74b-test")

    assert trace["canonical_renderer_route"] == "native"
    assert trace["multitrack_foreground_promotion"] is True
    assert trace["foreground_owner"] == VisualOwner.ADVANCED_LIVE.value
    assert trace["foreground_owner_count"] == 1
    assert trace["native_track_visible"] is False
    assert trace["advanced_canvas_visible"] is True
    assert trace["z_order"] == "mpv V1 < bitmap V2+ < subtitle foreground < transform"

    page.close_page()
    page.deleteLater()


def _appearance(project: SubtitleProject, cue: StudioCue) -> tuple[object, ...]:
    style = resolve_cue_visual(project, cue).style
    return (
        style.font_family, style.font_size, style.primary_color,
        style.outline_color, style.outline_width, style.shadow,
    )


def test_user_preset_popup_drag_undo_redo_and_save_reopen(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    polar = SubtitleStyle(
        "polar-bear", "北极熊", font_family="Microsoft YaHei UI",
        font_size=62, primary_color="#EAF8FF", outline_color="#102333",
        outline_width=7, shadow=3, bold=True,
    )
    StylePresetStore().upsert(polar)
    path = save_project(_project(tmp_path), tmp_path / "preset.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.resize(1400, 850)
    page.show()
    page.open_project(path)
    page.select_cue("cue-a")
    page.context_drawer.setCurrentIndex(2)
    APP.processEvents()

    index = page.style_preset.findData("polar-bear")
    assert index >= 0
    page.style_preset.showPopup()
    APP.processEvents()
    view = page.style_preset.view()
    popup_index = page.style_preset.model().index(index, 0)
    view.setCurrentIndex(popup_index)
    QTest.keyClick(view, Qt.Key.Key_Return)
    APP.processEvents()
    cue = next(item for item in page.project.cues if item.id == "cue-a")
    assert cue.base_preset_id == "polar-bear"
    before_appearance = _appearance(page.project, cue)
    before_transform = dict(cue.transform)

    QTest.mouseClick(page.position_edit_button, Qt.MouseButton.LeftButton)
    APP.processEvents()
    overlay = page.position_overlay
    from PySide6.QtCore import QRectF
    # This command test supplies a measured-box fixture; headed tests verify real glyph bounds.
    overlay.set_measured_bounds(QRectF(120,80,220,70))
    overlay.show()
    overlay.repaint()
    APP.processEvents()
    start = overlay._subtitle_rect().center().toPoint()
    end = start + QPoint(30, 0)
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(overlay, end, delay=10)
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=end)
    APP.processEvents()

    after_transform = dict(cue.transform)
    assert after_transform != before_transform
    assert cue.base_preset_id == "polar-bear"
    assert page.style_preset.currentData() == "polar-bear"
    assert _appearance(page.project, cue) == before_appearance

    page.undo_stack.undo()
    assert dict(cue.transform) == before_transform
    assert cue.base_preset_id == "polar-bear"
    page.undo_stack.redo()
    assert dict(cue.transform) == after_transform
    assert _appearance(page.project, cue) == before_appearance
    page.save()
    reopened = load_project(path)
    restored = next(item for item in reopened.cues if item.id == "cue-a")
    assert restored.base_preset_id == "polar-bear"
    assert restored.transform == after_transform
    assert _appearance(reopened, restored) == before_appearance
    page.close_page()
    page.deleteLater()


def test_review_session_snapshots_current_search_scope_with_qtest(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    path = save_project(_project(tmp_path), tmp_path / "review.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(path)
    page.show()
    page.cue_search.setFocus()
    QTest.keyClicks(page.cue_search, "alpha")
    APP.processEvents()
    assert page.cue_model.rowCount() == 1
    QTest.mouseClick(page.review_entry_button, Qt.MouseButton.LeftButton)
    APP.processEvents()

    session = page._review_session
    assert session.scope.filter_mode == "all"
    assert session.scope.search_query == "alpha"
    assert session.scope.visible_cue_ids == ("cue-a",)
    assert session.total == 1
    page._confirm_current_review()
    assert session.scope.visible_cue_ids == ("cue-a",)
    assert session.completed == 1
    page.close_page()
    page.deleteLater()


def test_export_symbols_and_preset_batch_ctrl_a_current_filter(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = _project(tmp_path)
    workspace = StudioExportWorkspace(project, str(tmp_path / "preview.ass"))
    workspace.show()
    APP.processEvents()
    # The native checkbox indicator is the single state source; labels carry
    # the plain format name (no Unicode box duplicates the indicator).
    assert workspace.subtitle_format_checks["srt"].text() == "SRT"
    assert workspace.subtitle_format_checks["srt"].isChecked()
    assert not workspace.subtitle_format_checks["ass"].isChecked()
    QTest.mouseClick(workspace.subtitle_format_checks["ass"], Qt.MouseButton.LeftButton)
    QTest.mouseClick(workspace.subtitle_speaker_modes["both"], Qt.MouseButton.LeftButton)
    assert workspace.subtitle_format_checks["ass"].isChecked()
    assert workspace.subtitle_speaker_modes["both"].isChecked()
    assert not workspace.subtitle_speaker_modes["combined"].isChecked()
    workspace.deleteLater()

    store = StylePresetStore()
    store.upsert(SubtitleStyle("custom-alpha", "Alpha custom"))
    store.upsert(SubtitleStyle("custom-beta", "Beta custom"))
    page = SubtitleStudioPage()
    page.show()
    page._open_style_preset_manager()
    page._style_preset_manager.resize(760, 650)
    page._style_preset_manager.show()
    page._style_preset_manager_search.setText("Alpha")
    page._style_preset_manager_batch_toggle.click()
    tree = page._style_preset_manager_tree
    APP.processEvents()
    assert tree.topLevelItemCount() == 1
    tree.setFocus()
    QTest.keyClick(tree, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    APP.processEvents()
    assert tree.topLevelItem(0).checkState(0) == Qt.CheckState.Checked
    assert tree.topLevelItem(0).data(0, Qt.ItemDataRole.UserRole) == "custom-alpha"
    delete = next(
        button for button in page._style_preset_manager.findChildren(QPushButton)
        if button.text() == "删除所选"
    )
    QTest.mouseClick(delete, Qt.MouseButton.LeftButton)
    assert "custom-alpha" not in StylePresetStore().all()
    assert "custom-beta" in StylePresetStore().all()
    page.close_page()
    page.deleteLater()
