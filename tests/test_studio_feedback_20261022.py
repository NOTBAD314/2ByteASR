"""2026-10-22 night user feedback on daily b9260c23.

Entering Studio crashed twice while the motion tiles were built; the project
library built 16+ cards and parsed each project file on the GUI thread; the
recognition plans were trimmed; the translation row could only be edited by
double click; every jump during playback made mpv decode twice.
"""
from __future__ import annotations

import json
import os
import shutil
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from tests.test_studio_ui import _app, _path


def _studio(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.resize(1500, 900)
    page.show()
    page.open_project(_path(tmp_path))
    app.processEvents()
    return app, page


def test_click_translation_block_then_e_edits_the_translation(tmp_path, monkeypatch):
    app, page = _studio(tmp_path, monkeypatch)
    try:
        page.project.generation_metadata["translations"] = {"a": "First line", "b": "Second"}
        page._set_bilingual_mode(True)
        timeline = page.timeline
        page.resize(1600, 1800)  # room for both speaker rows and the translation row
        timeline.setMinimumHeight(420)
        timeline.set_visible_window(0, 10_000)
        app.processEvents()
        _speakers, translation_rect, _wave = timeline._track_layout()
        assert timeline._track_viewport().contains(translation_rect.center())
        point = QPoint(int(timeline._time_to_x(2_200)), int(translation_rect.center().y()))
        cue, mode = timeline._cue_at(point)
        assert (cue.id, mode) == ("b", "translation")
        QTest.mouseClick(timeline, Qt.MouseButton.LeftButton, pos=point)
        app.processEvents()
        assert timeline.selected_id == "b" and timeline.selected_lane == "translation"
        assert page._shortcut_edit_at_playhead()
        editor = timeline._inline_editor
        assert editor is not None and timeline._inline_target == ("b", True)
        assert editor.toPlainText() == "Second"
        editor.selectAll()
        editor.insertPlainText("Edited")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        app.processEvents()
        assert page.project.generation_metadata["translations"]["b"] == "Edited"
        page.undo_stack.undo()
        assert page.project.generation_metadata["translations"]["b"] == "Second"
        # Selecting another cue (any route) forgets the translation line.
        page.select_cue("a")
        app.processEvents()
        assert timeline.selected_lane == ""
    finally:
        page.close_page()
        page.deleteLater()


def test_e_without_a_selected_translation_still_follows_the_playhead(tmp_path, monkeypatch):
    app, page = _studio(tmp_path, monkeypatch)
    try:
        calls = []
        monkeypatch.setattr(page, "_edit_subtitle_at_playhead", lambda: calls.append("playhead"))
        page.project.generation_metadata["translations"] = {"a": "First line"}
        page._set_bilingual_mode(True)
        page.select_cue("a")
        assert page.timeline.selected_lane == ""
        assert page._shortcut_edit_at_playhead()
        assert calls == ["playhead"] and page.timeline._inline_editor is None
    finally:
        page.close_page()
        page.deleteLater()


def test_motion_tiles_are_built_when_the_motion_page_is_shown(tmp_path, monkeypatch):
    app, page = _studio(tmp_path, monkeypatch)
    try:
        inspector = page.motion_inspector
        assert inspector._cards == {} and not inspector._tiles_built
        page.context_drawer.setCurrentIndex(page.motion_tab_index)
        app.processEvents()
        current = inspector.stages[inspector.tabs.currentIndex()]
        assert inspector._tiles_built == {current}
        assert any(stage == current for stage, _key in inspector._cards)
        inspector.tabs.setCurrentIndex((inspector.tabs.currentIndex() + 1) % len(inspector.stages))
        app.processEvents()
        assert len(inspector._tiles_built) == 2
        # Code that asks for every tile still gets every tile.
        assert {stage for stage, _key in inspector.cards} == set(inspector.stages)
    finally:
        page.close_page()
        page.deleteLater()


class _PostController:
    running = True

    def __init__(self):
        self.calls = []

    def post_set_paused(self, paused, *, position_seconds=None):
        self.calls.append(("pause", bool(paused), position_seconds))
        return True

    def set_paused(self, paused):
        self.calls.append(("pause", bool(paused), "direct"))

    def seek(self, seconds, accurate=True):
        self.calls.append(("seek", round(float(seconds), 3)))

    def set_speed(self, value):
        self.calls.append(("speed", float(value)))

    def source_alive(self):
        return True

    def get_property(self, name, default=None):
        return default


def test_seek_hold_pause_does_not_align_the_old_frame_first():
    from twobyteasr.studio.studio_video_canvas import MpvCanvas
    _app()
    canvas = MpvCanvas()
    canvas.controller = _PostController()
    canvas._startup_state = "READY"
    canvas._media_attached = True
    canvas._duration = 600.0
    canvas.playback_ready = lambda: False
    canvas.playback_prepare = lambda: None
    canvas.set_paused(False)
    canvas.controller.calls.clear()
    canvas.seek(120.0)
    pauses = [call for call in canvas.controller.calls if call[0] == "pause"]
    # The hold's pause carries no position: the seek right after it moves mpv.
    assert pauses[0] == ("pause", True, None)
    assert ("seek", 120.0) in canvas.controller.calls
    canvas.controller.calls.clear()
    # An ordinary pause still aligns the paused frame with the clock.
    canvas._end_seek_hold(resumed=False)
    canvas._paused = False
    canvas.set_paused(True)
    assert canvas.controller.calls[0][0] == "pause" and canvas.controller.calls[0][2] is not None
    canvas.deleteLater()


def test_cloud_plan_reminds_once_when_the_moss_pro_key_is_missing(monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.app.ui import MainWindow
    from twobyteasr.recognition.recognition_plans import recognition_plan
    opened = []
    host = SimpleNamespace()
    host._open_api_setup_guide = opened.append
    monkeypatch.setattr("twobyteasr.providers.llm_config.read_asr_api_key", lambda *a, **k: ("", ""))
    monkeypatch.setattr("twobyteasr.app.ui.QTimer.singleShot", lambda _ms, fn: fn())
    plan = recognition_plan("moss_pro_qwen")
    MainWindow._remind_plan_api_key(host, plan)
    MainWindow._remind_plan_api_key(host, plan)
    assert opened == ["mosi_moss_pro"]
    monkeypatch.setattr("twobyteasr.providers.llm_config.read_asr_api_key", lambda *a, **k: ("saved", ""))
    host.__dict__.clear()
    host._open_api_setup_guide = opened.append
    MainWindow._remind_plan_api_key(host, plan)
    assert opened == ["mosi_moss_pro"]


def test_removed_plan_in_a_saved_profile_reads_as_custom():
    from twobyteasr.recognition.recognition_profiles import ProjectProfile
    profile = ProjectProfile(id="old", name="旧方案", recognition_plan="low_memory").normalize()
    assert profile.recognition_plan == "custom"
    assert ProjectProfile(id="new", name="新", recognition_plan="moss_pro_qwen").normalize().recognition_plan == "moss_pro_qwen"


@pytest.fixture
def big_library(tmp_path, monkeypatch):
    import twobyteasr.projects.studio_project as studio_project
    import twobyteasr.studio.studio_hub as studio_hub
    import twobyteasr.studio.studio_media_flow as studio_media_flow
    import twobyteasr.studio.studio_project_flow as studio_project_flow
    import twobyteasr.studio.studio_ui as studio_ui
    base = tmp_path.resolve()
    root = base / "projects"
    root.mkdir()
    settings = base / "settings.json"
    recent = []
    for index in range(25):
        path = root / f"project-{index:02d}.2byteproj"
        project = SubtitleProject(media=StudioMedia(path=str(base / f"media-{index}.mp4")),
                                  cues=[StudioCue(id="1", start_ms=0, end_ms=900, text="字幕")])
        if index == 0:
            project.studio_state["project_name"] = "改过名字的工程"
        save_project(project, path)
        recent.append({"path": str(path.resolve()), "name": path.stem, "cue_count": 1})
    settings.write_text(json.dumps({"recent_projects": recent[:3],
                                    "studio_preferences": {"auto_cover": False}}), encoding="utf-8")
    for module in (studio_hub, studio_project, studio_ui, studio_project_flow):
        monkeypatch.setattr(module, "studio_settings_path", lambda *a: settings)
    for module in (studio_hub, studio_media_flow):
        monkeypatch.setattr(module, "project_library_root", lambda *a: root)
    QApplication.instance() or QApplication([])
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_library_builds_ten_projects_then_more_on_scroll_and_reads_names_off_thread(big_library):
    from twobyteasr.projects import project_display_name
    project_display_name._read.cache_clear()
    project_display_name._READ_KEYS.clear()
    app = QApplication.instance()
    page = SubtitleStudioPage()
    page.resize(1500, 950)
    page.show()
    try:
        page.show_project_hub()
        end = time.monotonic() + 15
        # The first paint shows the recent projects; the library scan adds the rest.
        while time.monotonic() < end and (len(page._hub_card_widgets) < 10 or getattr(page, "_hub_scan_pending", False)):
            app.processEvents()
            time.sleep(0.01)
        for _ in range(20):
            app.processEvents()
        columns = page._hub_grid_metrics[0]
        first = len(page._hub_card_widgets)
        assert 10 <= first <= max(10, -(-10 // columns) * columns) < 25
        # The renamed project's exact name arrives from the library-names thread.
        renamed = next(card for card in page._hub_card_widgets if card._library_item_path.endswith("project-00.2byteproj"))
        end = time.monotonic() + 8
        while time.monotonic() < end and "改过名字的工程" not in renamed.text():
            app.processEvents()
            time.sleep(0.01)
        assert renamed.text().startswith("改过名字的工程")
        bar = page.project_library_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        page._library_scrolled()
        for _ in range(40):
            app.processEvents()
        assert len(page._hub_card_widgets) > first
    finally:
        page.close_page()
        page.deleteLater()


def test_speaker_track_preference_is_saved_validated_and_read(tmp_path, monkeypatch):
    import twobyteasr.app.application_settings as application_settings
    import twobyteasr.projects.studio_project as studio_project
    from twobyteasr.app.settings_lifecycle import normalized_preferences
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(application_settings, "studio_settings_path", lambda *a: settings)
    monkeypatch.setattr(studio_project, "studio_settings_path", lambda *a: settings)
    assert studio_project.speaker_track_preference() is None
    application_settings.save_hub_preferences("", True, 60, 9, True, True, speaker_main_tracks=3)
    assert json.loads(settings.read_text("utf-8"))["studio_preferences"]["speaker_main_tracks"] == 3
    assert studio_project.speaker_track_preference() == 3
    prefs, changes = normalized_preferences({"speaker_main_tracks": 4})
    assert prefs["speaker_main_tracks"] == 2 and changes == ["speaker_main_tracks"]


def test_studio_translation_choice_is_for_this_run_and_needs_the_ai():
    # 2026-10-23: the 识别字幕 sheet chooses the translation for one run.
    from twobyteasr.app.ui import studio_translation_choice
    home = {"recognition_language": "ja", "chinese_script": "zh-Hans",
            "subtitle_output": "original", "translation_script": "en"}
    chosen = {"subtitle_output": "bilingual", "translation_script": "zh-Hans"}
    assert studio_translation_choice(home, chosen, True) == dict(home, subtitle_output="bilingual",
                                                                 translation_script="zh-Hans")
    assert studio_translation_choice(home, chosen, False)["subtitle_output"] == "original"
    assert studio_translation_choice(home, {}, True) == home          # a home run keeps home's choice
    assert home["subtitle_output"] == "original"                      # never written back
