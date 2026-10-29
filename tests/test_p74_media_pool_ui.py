"""P7.4 Media Pool and V1/V2/V3 UI regressions."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPalette, QUndoStack
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.timeline.studio_media_commands import media_graph_command
from twobyteasr.timeline.studio_media_pool import (
    audio_master_track_id,
    add_media_asset,
    add_video_clip,
    create_video_track,
    reorder_video_track,
    set_audio_master_track,
    set_video_track_state,
)
from twobyteasr.timeline.studio_edit_commands import (
    razor_video_command,
    set_video_lock_command,
)
from twobyteasr.timeline.studio_edit_sequence import timeline_duration_ms
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    SubtitleProject,
    save_project,
)
from twobyteasr.projects.studio_runtime_state import DirtyDomain, state_for
from twobyteasr.caption_style.font_system import SystemFontEntry
from twobyteasr.design.studio_theme import build_secondary_surface_qss
from twobyteasr.studio.studio_ui import LazyFontComboBox, SubtitleStudioPage
from twobyteasr.caption_style.style_presets import StylePresetStore
from twobyteasr.projects.studio_project import SubtitleStyle
from twobyteasr.design.ui_theme import theme_definition


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _project(tmp_path) -> SubtitleProject:
    primary = tmp_path / "primary.mp4"
    broll = tmp_path / "reaction.mp4"
    overlay = tmp_path / "overlay.mp4"
    for path in (primary, broll, overlay):
        path.write_bytes(path.name.encode("ascii"))
    project = SubtitleProject(
        media=StudioMedia(
            path=str(primary),
            display_name=primary.name,
            duration_ms=12_000,
            fingerprint="primary",
            width=1920,
            height=1080,
        ),
        cues=[StudioCue("cue", 0, 1_000, "空中打拳")],
    )
    project.validate()
    project.video_tracks[0].locked = False
    for name, path in (("反应画面", broll), ("贴图", overlay)):
        asset = add_media_asset(
            project,
            path,
            fingerprint=path.stem,
            duration_ms=8_000,
        )
        track = create_video_track(project, name)
        add_video_clip(project, track.id, asset.asset_id, timeline_in_ms=1_000)
    project.video_tracks[2].clips.clear()
    project.validate()
    return project


def test_preset_manager_is_searchable_filterable_and_uses_row_selection(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    store = StylePresetStore()
    store.upsert(SubtitleStyle("custom-focus", "Creator Focus"), source="custom")
    page = SubtitleStudioPage()

    page._open_style_preset_manager()
    tree = page._style_preset_manager_tree
    search = page._style_preset_manager_search
    filters = page._style_preset_manager_filters

    assert tree.isHeaderHidden()
    assert tree.topLevelItemCount() >= 7
    search.setText("Creator Focus")
    app.processEvents()
    assert tree.topLevelItemCount() == 1
    assert tree.topLevelItem(0).data(0, Qt.ItemDataRole.UserRole) == "custom-focus"

    search.clear()
    filters["builtin"].click()
    app.processEvents()
    assert tree.topLevelItemCount() >= 6
    assert all(
        tree.topLevelItem(index).data(0, Qt.ItemDataRole.UserRole + 1) == "builtin"
        for index in range(tree.topLevelItemCount())
    )

    game = next(
        tree.topLevelItem(index)
        for index in range(tree.topLevelItemCount())
        if tree.topLevelItem(index).data(0, Qt.ItemDataRole.UserRole) == "game"
    )
    tree.setCurrentItem(game)
    page._style_preset_manager_favorite.click()
    assert StylePresetStore().load_metadata()["game"]["favorite"] is True
    page.close_page()
    page.deleteLater()


def test_font_popup_palette_tracks_theme_without_reenumerating_fonts(monkeypatch):
    _app()
    calls = []
    entries = (
        SystemFontEntry("Source Han Sans SC", ("Heavy",)),
        SystemFontEntry("Microsoft YaHei UI", ("Regular",)),
    )
    monkeypatch.setattr(
        "twobyteasr.caption_style.studio_font_combo.system_font_inventory",
        lambda: calls.append("inventory") or entries,
    )
    combo = LazyFontComboBox()
    combo.setEditable(True)
    combo._load_full_font_list()
    combo._load_full_font_list()
    assert calls == ["inventory"]

    for key in ("warm", "plum", "lavender", "slate"):
        monkeypatch.setattr("twobyteasr.design.theme_manager.theme_key", lambda value=key: value)
        combo.refresh_theme_palette()
        theme = theme_definition(key)
        palette = combo.view().palette()
        assert palette.color(QPalette.ColorRole.Base).name().upper() == theme.input_surface.upper()
        assert palette.color(QPalette.ColorRole.Text).name().upper() == theme.text.upper()
        assert palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text).name().upper() == theme.disabled.upper()
        qss = build_secondary_surface_qss(theme)
        assert "QAbstractItemView::item:hover" in qss
        assert "QAbstractItemView::item:disabled" in qss
        assert "QScrollBar::handle:vertical:hover" in qss
    assert calls == ["inventory"]


def test_media_graph_command_is_one_scoped_undo_without_copying_cues(tmp_path):
    _app()
    project = _project(tmp_path)
    cue_list = project.cues
    state = state_for(project)
    deltas = []
    state.subscribe(deltas.append)
    stack = QUndoStack()

    stack.push(
        media_graph_command(
            project,
            "新建视频轨",
            lambda working: create_video_track(working, "V4 贴纸"),
        )
    )

    assert stack.count() == 1
    assert project.cues is cue_list
    assert len(project.video_tracks) == 4
    assert deltas[-1].dirty & DirtyDomain.VIDEO_TRACKS
    assert deltas[-1].dirty & DirtyDomain.AUTOSAVE
    stack.undo()
    assert len(project.video_tracks) == 3
    assert project.cues is cue_list
    stack.redo()
    assert [track.name for track in project.video_tracks][-1] == "V4 贴纸"


def test_media_pool_search_add_to_selected_track_and_undo(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    path = save_project(_project(tmp_path), tmp_path / "pool.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(path)
    app.processEvents()

    panel = page.media_pool_panel
    assert panel.assets.topLevelItemCount() == 3
    assert panel.track_selector.count() == 3
    panel.select_track("V1")
    panel.assets.setCurrentItem(panel.assets.topLevelItem(0))
    assert panel.add_to_track_button.isEnabled() is False
    assert "V2" in panel.add_to_track_button.toolTip()
    panel.search.setText("overlay")
    visible = [
        panel.assets.topLevelItem(row)
        for row in range(panel.assets.topLevelItemCount())
        if not panel.assets.topLevelItem(row).isHidden()
    ]
    assert len(visible) == 1
    panel.assets.setCurrentItem(visible[0])
    panel.select_track("V3")
    before = page.undo_stack.count()
    panel._add_selected_to_track()

    assert page.undo_stack.count() == before + 1
    assert len(page.project.video_tracks[2].clips) == 1
    assert set(page.timeline._video_track_rects()) == {"V1", "V2", "V3"}
    page.undo_stack.undo()
    assert page.project.video_tracks[2].clips == []
    page.close_page()
    page.deleteLater()


def test_video_track_header_controls_mutate_target_track_once(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    path = save_project(_project(tmp_path), tmp_path / "tracks.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.resize(1500, 900)
    page.show()
    page.open_project(path)
    app.processEvents()

    rect = page.timeline._video_track_rect("V2")
    before = page.undo_stack.count()
    QTest.mouseClick(
        page.timeline,
        Qt.MouseButton.LeftButton,
        pos=QPoint(152, round(rect.center().y())),
    )
    app.processEvents()

    assert page.project.video_tracks[1].enabled is False
    assert page.project.video_tracks[1].muted is False
    assert page.project.video_tracks[0].muted is False
    assert page.undo_stack.count() == before + 1
    page.undo_stack.undo()
    assert page.project.video_tracks[1].enabled is True
    page.close_page()
    page.deleteLater()


def test_preview_target_is_topmost_active_clip_with_primary_fallback(tmp_path):
    _app()
    project = _project(tmp_path)
    reorder_video_track(project, "V2", 0)
    page = SubtitleStudioPage()
    page.project = project

    target = page._multitrack_preview_target(1_500)
    assert target is not None
    assert target["track_id"] == "V2"
    assert target["mode"] == "multitrack"
    assert target["source_ms"] == 500

    set_video_track_state(project, "V2", enabled=False)
    fallback = page._multitrack_preview_target(1_500)
    assert fallback is not None
    assert fallback["track_id"] == "V1"
    assert fallback["mode"] == "primary"
    page.close_page()
    page.deleteLater()


def test_preview_target_skips_offline_top_track(tmp_path):
    _app()
    project = _project(tmp_path)
    reorder_video_track(project, "V2", 0)
    top_asset_id = project.video_tracks[0].clips[0].asset_id
    next(asset for asset in project.media_pool if asset.asset_id == top_asset_id).offline = True
    page = SubtitleStudioPage()
    page.project = project

    target = page._multitrack_preview_target(1_500)

    assert target is not None
    assert target["track_id"] == "V1"
    assert target["mode"] == "primary"
    page.close_page()
    page.deleteLater()


def test_multitrack_duration_extends_beyond_legacy_v1(tmp_path):
    _app()
    project = _project(tmp_path)
    clip = project.video_tracks[1].clips[0]
    clip.timeline_in_ms = 15_000
    clip.timeline_out_ms = 23_000
    project.validate()

    page = SubtitleStudioPage()
    page.project = project
    page._refresh_edit_playback_state()

    assert timeline_duration_ms(project) == 23_000
    assert page.video._duration_override == 23.0
    page.close_page()
    page.deleteLater()


def test_legacy_v1_razor_and_lock_project_into_media_graph(tmp_path):
    _app()
    project = _project(tmp_path)
    stack = QUndoStack()
    cue_list = project.cues

    stack.push(set_video_lock_command(project, False))
    stack.push(razor_video_command(project, 3_000))

    primary = next(track for track in project.video_tracks if track.id == "V1")
    assert primary.locked is False
    assert project.cues is cue_list
    assert [
        (clip.source_in_ms, clip.source_out_ms, clip.timeline_in_ms, clip.timeline_out_ms)
        for clip in primary.clips
    ] == [
        (0, 3_000, 0, 3_000),
        (3_000, 12_000, 3_000, 12_000),
    ]
    stack.undo()
    assert len(primary.clips) == 1
    assert primary.clips[0].timeline_out_ms == 12_000


class _ActorOnlyController:
    def __init__(self) -> None:
        self.running = True
        self.loads: list[str] = []
        self.seeks: list[float] = []
        self.paused: list[bool] = []
        self.volumes: list[float] = []
        self.clears = 0

    def post_load(self, source: str) -> bool:
        self.loads.append(str(Path(source).resolve()))
        return True

    def post_seek(self, seconds: float, **_kwargs) -> bool:
        self.seeks.append(float(seconds))
        return True

    def post_set_paused(self, paused: bool) -> bool:
        self.paused.append(bool(paused))
        return True

    def post_set_volume(self, volume: float) -> bool:
        self.volumes.append(float(volume))
        return True

    def post_clear_media(self) -> bool:
        self.clears += 1
        return True

    def post_remove_overlay(self, *args, **kwargs):
        return True

    def load(self, *_args, **_kwargs):
        raise AssertionError("GUI thread used synchronous mpv load")

    def seek(self, *_args, **_kwargs):
        raise AssertionError("GUI thread used synchronous mpv seek")

    def set_paused(self, *_args, **_kwargs):
        raise AssertionError("GUI thread used synchronous mpv pause")

    def set_volume(self, *_args, **_kwargs):
        raise AssertionError("GUI thread used synchronous mpv volume")

    def clear_media(self, *_args, **_kwargs):
        raise AssertionError("GUI thread used synchronous mpv clear")


def test_source_transitions_use_one_actor_load_and_restore_muted_volume(tmp_path):
    _app()
    project = _project(tmp_path)
    reorder_video_track(project, "V2", 0)
    track = project.video_tracks[0]
    first = track.clips[0]
    first.source_out_ms = 1_000
    first.timeline_out_ms = 2_000
    second = add_video_clip(
        project,
        track.id,
        first.asset_id,
        timeline_in_ms=2_000,
        source_in_ms=1_000,
        source_out_ms=2_000,
    )
    assert second.timeline_out_ms == 3_000
    project.validate()

    page = SubtitleStudioPage()
    page.project = project
    controller = _ActorOnlyController()
    page.video.controller = controller
    page.video._media_path = project.media.path
    page.video._media_attached = True
    page.volume_slider.setValue(73)
    set_audio_master_track(project, track.id)
    from twobyteasr.timeline.studio_media_pool import set_audio_master_mode
    set_audio_master_mode(project,'manual')

    page._sync_multitrack_preview_at(1_500)
    page._sync_multitrack_preview_at(2_500)
    assert len(controller.loads) == 1
    assert controller.loads[0] == str(Path(next(
        asset.canonical_source
        for asset in project.media_pool
        if asset.asset_id == first.asset_id
    )).resolve())

    set_video_track_state(project, track.id, muted=True)
    page._activate_multitrack_preview(2_500)
    set_video_track_state(project, track.id, muted=False)
    page._activate_multitrack_preview(2_500)
    assert controller.volumes and all(value==0 for value in controller.volumes)  # mpv never owns audible playback
    assert page.volume_slider.value()==73
    assert audio_master_track_id(project)==track.id

    set_video_track_state(project, track.id, enabled=False)
    page._sync_multitrack_preview_at(2_500)
    assert len(controller.loads) == 2
    assert controller.loads[-1] == str(Path(project.media.path).resolve())
    page.close_page()
    page.deleteLater()
