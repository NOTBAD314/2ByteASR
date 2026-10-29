"""2026-10-17 shortcut page redesign and the added rebindable keys.

User: the settings page was a dense four-row table, and too few keys could be
changed. The panel is now one grouped list with key caps; about thirty more
Studio / home / app actions joined the registry.
"""
import ast
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from twobyteasr.studio import shortcut_registry as reg

ADDED_STUDIO = ("jump_start", "jump_end", "seek_back", "seek_forward", "loop_cue", "speed_down", "speed_up",
                "speed_reset", "nudge_earlier", "nudge_later", "smart_align", "reasr_current", "timeline_zoom_in",
                "timeline_zoom_out", "timeline_fit", "toggle_waveform", "toggle_filmstrip", "toggle_follow",
                "go_to_in", "go_to_out", "clear_in_out", "open_project", "import_media", "export_subtitles",
                "export_video", "toggle_cue_list", "toggle_tool_panel", "fullscreen", "speaker_manager")


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ------------------------------------------------------------ registry


def test_more_keys_can_be_changed_and_defaults_do_not_clash(qapp):
    assert len(reg.ACTIONS) >= 95
    assert set(ADDED_STUDIO) <= set(reg.BY_ID)
    assert {"home.open_studio", "app.open_settings"} <= set(reg.BY_ID)
    values = reg.platform_defaults("win32")
    assert values["jump_start"] == "Home" and values["timeline_zoom_in"] == "=" and values["fullscreen"] == "F11"
    assert values["app.open_settings"] == "Ctrl+,"
    assert reg.platform_defaults("darwin")["fullscreen"] == "Ctrl+Meta+F"
    assert {action.category for action in reg.ACTIONS} <= set(reg.CATEGORY_ORDER)


def test_new_defaults_never_take_a_key_the_user_already_chose(qapp):
    values, unbound = reg.load_values({"track_gain": "Home"}, "win32")
    assert values["track_gain"] == "Home" and values["jump_start"] == "" and "jump_start" in unbound


def _install_shortcut_ids():
    """Ids in the literal callback map of SubtitleStudioPage._install_shortcuts."""
    import inspect
    import textwrap
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    tree = ast.parse(textwrap.dedent(inspect.getsource(SubtitleStudioPage._install_shortcuts)))
    for child in ast.walk(tree):
        if (isinstance(child, ast.Assign) and isinstance(child.value, ast.Dict)
                and any(getattr(t, "attr", "") == "_command_callbacks" for t in child.targets)):
            return {key.value for key in child.value.keys}
    raise AssertionError("callback map not found")


def _fake_page(**overrides):
    from PySide6.QtWidgets import QCheckBox, QComboBox
    calls = []

    def record(name):
        return lambda *args: calls.append((name,) + args)
    speed = QComboBox()
    for value in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 4.0, 8.0):
        speed.addItem(f"{value:g}x", value)
    speed.setCurrentIndex(speed.findData(1.0))
    page = SimpleNamespace(
        project=object(), timeline=SimpleNamespace(playhead_ms=500), speed_box=speed,
        waveform_toggle=QCheckBox(), filmstrip_toggle=QCheckBox(), follow_playhead_toggle=QCheckBox(),
        selected_cue_ids=lambda: ["a"], calls=calls)
    for name in ("_seek", "_nudge", "_apply_timing_offset", "_toggle_loop_current", "_smart_align_current",
                 "_reasr_current", "_zoom_timeline", "_fit_timeline", "_clear_range", "open_project_dialog",
                 "import_media_dialog", "export_subtitles", "_open_render_dialog", "_toggle_cue_list",
                 "_toggle_context_panel", "_toggle_fullscreen", "_open_speaker_manager"):
        setattr(page, name, record(name))
    page.__dict__.update(overrides)
    return page


def test_every_studio_action_has_a_command(qapp):
    from twobyteasr.studio.studio_shortcut_actions import extra_command_callbacks
    handled = _install_shortcut_ids() | set(extra_command_callbacks(_fake_page()))
    studio_ids = {action.id for action in reg.ACTIONS if action.scope in ("studio", "studio.review")}
    assert studio_ids <= handled, sorted(studio_ids - handled)


def test_added_commands_call_the_existing_features(qapp, monkeypatch):
    from twobyteasr.studio.studio_shortcut_actions import extra_command_callbacks
    from twobyteasr.timeline import studio_edit_sequence
    from twobyteasr.projects import project_range
    monkeypatch.setattr(studio_edit_sequence, "timeline_duration_ms", lambda project: 60_000)
    monkeypatch.setattr(project_range, "effective_range", lambda project: (2_000, 9_000))
    page = _fake_page()
    run = extra_command_callbacks(page)
    run["jump_start"](); run["jump_end"](); run["seek_back"](); run["seek_forward"]()
    run["go_to_in"](); run["go_to_out"]()
    assert [call for call in page.calls if call[0] == "_seek"] == [
        ("_seek", 0.0), ("_seek", 59.96), ("_seek", 0.0), ("_seek", 1.5), ("_seek", 2.0), ("_seek", 9.0)]
    run["nudge_earlier"]()
    assert page.calls[-1] == ("_nudge", -100)
    page.selected_cue_ids = lambda: ["a", "b"]
    run["nudge_later"]()
    assert page.calls[-1] == ("_apply_timing_offset", ["a", "b"], 100)
    run["speed_up"]()
    assert page.speed_box.currentData() == 1.25
    run["speed_reset"]()
    assert page.speed_box.currentData() == 1.0
    for _ in range(5):
        run["speed_down"]()
    assert page.speed_box.currentData() == 0.5  # stops at the slowest choice
    run["toggle_waveform"]()
    assert page.waveform_toggle.isChecked()
    run["timeline_zoom_in"]()
    assert page.calls[-1] == ("_zoom_timeline", 0.8)
    for name, method in (("export_video", "_open_render_dialog"), ("fullscreen", "_toggle_fullscreen"),
                         ("open_project", "open_project_dialog"), ("toggle_cue_list", "_toggle_cue_list")):
        run[name]()
        assert page.calls[-1] == (method,), name


def test_added_commands_do_nothing_without_a_project(qapp):
    from twobyteasr.studio.studio_shortcut_actions import extra_command_callbacks
    page = _fake_page(project=None)
    run = extra_command_callbacks(page)
    for name in ("jump_start", "jump_end", "seek_forward", "nudge_later", "go_to_in", "smart_align",
                 "speaker_manager"):
        run[name]()
    assert page.calls == []


def test_added_keys_dispatch_in_studio(qapp):
    from tests.test_shortcut_registry import _dispatch_page
    _page, dispatch, calls = _dispatch_page()
    for key, command in (("Home", "jump_start"), ("End", "jump_end"), ("=", "timeline_zoom_in"),
                         ("-", "timeline_zoom_out"), ("Alt+Left", "nudge_earlier"), ("Shift+Right", "seek_forward"),
                         ("F11", "fullscreen"), ("Ctrl+E", "export_subtitles")):
        assert dispatch(key) and calls[-1] == command, key


# ------------------------------------------------------------ key caps


def test_key_caps_name_each_key(qapp):
    from twobyteasr.studio.studio_shortcuts import key_caps
    assert key_caps("Ctrl+Shift+S", "win32") == ["Ctrl", "Shift", "S"]
    assert key_caps("Ctrl++", "win32") == ["Ctrl", "+"]
    assert key_caps("Alt+Left", "win32") == ["Alt", "←"]
    assert key_caps("Ctrl+Shift+S", "darwin") == ["⌘", "⇧", "S"]
    assert key_caps("", "win32") == []


# ------------------------------------------------------------ panel


def _panel(embedded=False):
    from twobyteasr.studio.studio_shortcuts import ShortcutSettingsPanel
    scopes = tuple(reg.SCOPE_LABELS) if embedded else ("studio", "studio.review")
    return ShortcutSettingsPanel(reg.platform_defaults(), None, scopes=scopes, embedded=embedded)


def test_panel_lists_every_key_once_in_groups(qapp):
    panel = _panel(embedded=True)
    assert set(panel.rows) == set(reg.BY_ID)
    titles = [header.findChild(__import__("PySide6.QtWidgets").QtWidgets.QLabel, "shortcutGroupTitle").text()
              for header, _group, _rows in panel._groups]
    assert titles == [c for c in reg.CATEGORY_ORDER if any(a.category == c for a in reg.ACTIONS)]
    assert panel._save_button is None and panel.cancel_button is None  # 应用设置 saves with 保存更改
    assert all(row.reset.isHidden() for row in panel.rows.values())   # nothing changed yet
    panel.deleteLater()


def test_changed_rows_show_their_default_and_can_be_listed_alone(qapp):
    from PySide6.QtGui import QKeySequence
    panel = _panel()
    assert not panel.changed_only.isEnabled()
    panel._editors["razor_tool"].setKeySequence(QKeySequence("Shift+C"))
    row = panel.rows["razor_tool"]
    assert not row.reset.isHidden() and "C" in row.detail.text()
    assert panel.changed_only.isEnabled() and "1" in panel.changed_only.text()
    panel.changed_only.setChecked(True)
    assert panel.visible_action_ids() == ["razor_tool"]
    row.reset.click()
    assert panel.values()["razor_tool"] == "C" and not panel.changed_only.isChecked()
    assert len(panel.visible_action_ids()) == len(panel.rows)
    panel.deleteLater()


def test_a_clash_is_named_on_both_rows_and_in_the_banner(qapp):
    from PySide6.QtGui import QKeySequence
    panel = _panel()
    panel._editors["jump_start"].setKeySequence(QKeySequence("End"))
    for action_id, other in (("jump_start", "跳到结尾"), ("jump_end", "跳到开头")):
        row = panel.rows[action_id]
        assert other in row.detail.text() and row.field._conflict, action_id
    assert not panel.banner.isHidden() and panel.banner.property("kind") == "error"
    assert not panel._save_button.isEnabled()
    panel.resolve_button.click()
    assert panel.values()["jump_end"] == "" and not panel.rows["jump_end"].field._conflict
    assert panel.banner.isHidden() and panel._save_button.isEnabled()
    panel.deleteLater()


def test_search_finds_keys_by_name_or_cap_and_says_when_nothing_matches(qapp):
    panel = _panel()
    panel.search.setText("F11")
    assert panel.visible_action_ids() == ["fullscreen"]
    panel.search.setText("没有这个功能")
    assert panel.visible_action_ids() == [] and not panel.empty_label.isHidden()
    panel.search.setText("")
    assert panel.empty_label.isHidden()
    panel.deleteLater()


def test_escape_cancels_recording_and_tab_is_not_recorded(qapp):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    panel = _panel()
    field = panel._editors["pause"]
    for key in (Qt.Key.Key_Escape, Qt.Key.Key_Tab):
        field.event(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))
        assert panel.values()["pause"] == "K", key
    field.event(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_P, Qt.KeyboardModifier.ShiftModifier, "P"))
    assert panel.values()["pause"] == "Shift+P"
    panel.deleteLater()


def test_caps_are_styled_labels_not_painted_text(qapp):
    # Caps, the recording prompt and 未设置 are labels styled by the panel sheet.
    from PySide6.QtGui import QKeySequence
    panel = _panel()
    assert panel._editors["split"].cap_texts() == ["Ctrl", "Shift", "S"]
    field = panel._editors["speed_up"]
    assert field.cap_texts() == [] and field.caps.findChildren(
        __import__("PySide6.QtWidgets").QtWidgets.QLabel, "shortcutKeyEmpty")
    field.setKeySequence(QKeySequence("Alt+Right"))
    assert field.cap_texts() == ["Alt", "→"]
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QFocusEvent
    from PySide6.QtWidgets import QLabel
    field.focusInEvent(QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason))
    assert field.is_recording() and field.cap_texts() == []
    assert [label.text() for label in field.caps.findChildren(QLabel, "shortcutKeyPrompt")] == ["按新组合 · Esc 取消"]
    field.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.MouseFocusReason))
    assert not field.is_recording() and field.cap_texts() == ["Alt", "→"]
    panel.deleteLater()


def test_fixed_gestures_stay_folded_until_asked(qapp):
    panel = _panel()
    assert panel.fixed_body.isHidden()
    panel.fixed_toggle.setChecked(True)
    assert not panel.fixed_body.isHidden()
    panel.deleteLater()


def test_narrow_drawer_puts_the_keys_under_the_name(qapp):
    panel = _panel()
    panel.resize(360, 700)
    panel.show()
    qapp.processEvents()
    row = panel.rows["play_pause"]
    assert row._stacked and row.field.geometry().top() > row.name.geometry().top()
    panel.resize(620, 700)
    qapp.processEvents()
    assert not row._stacked
    panel.close()
    panel.deleteLater()


def test_settings_page_has_one_scroll_area_and_one_save(qapp, tmp_path):
    from PySide6.QtWidgets import QScrollArea
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    dialog = ApplicationSettingsDialog(None, {}, tmp_path / "Projects", browse=lambda *a: None,
                                       clear_recent=lambda: None, reset_layout=lambda: None)
    panel = dialog.shortcut_panel
    node = panel.parentWidget()
    while node is not None and node is not dialog:
        assert not isinstance(node, QScrollArea), node.objectName()
        node = node.parentWidget()
    assert panel._save_button is None
    dialog.deleteLater()
    qapp.processEvents()
