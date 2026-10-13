"""Customizable shortcuts (2026-10-13): one registry for dispatch, tooltips and settings."""
import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from twobyteasr import shortcut_registry as reg


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_normalize_one_spelling_per_key(qapp):
    assert reg.normalize("Ctrl+Enter") == "Ctrl+Return"
    assert reg.normalize("Ctrl+Num+Enter") == "Ctrl+Return"
    assert reg.normalize("Enter") == "Return"
    assert reg.normalize("Del") == "Delete"
    assert reg.normalize("Ctrl++") == "Ctrl++"
    assert reg.normalize("Ctrl+K, Ctrl+S") == "Ctrl+K"  # chords are never dispatched


def test_default_keys_keep_the_existing_habits():
    values = reg.platform_defaults("win32")
    expected = {"trim_start": "Q", "trim_end": "W", "edit_at_playhead": "E", "toggle_review": "R",
                "track_forward_tool": "A", "video_transition": "Ctrl+D", "audio_transition": "Ctrl+Shift+D",
                "play_pause": "Space", "merge_tool": "B", "razor_tool": "C", "split_at_playhead": "Ctrl+K",
                "save": "Ctrl+S", "find_replace": "Ctrl+H", "home.start_run": "Ctrl+Return"}
    for key, value in expected.items():
        assert values[key] == value, key


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_defaults_have_no_blocking_conflict(platform, qapp):
    assert reg.blocking_conflicts(reg.platform_defaults(platform)) == []


def test_mac_defaults_avoid_command_h_hide(qapp):
    values = reg.platform_defaults("darwin")
    assert values["find_replace"] != "Ctrl+H" and values["proofread.replace"] != "Ctrl+H"
    assert reg.reserved_reason("Ctrl+H", "darwin")


def test_conflicts_follow_scopes(qapp):
    values = reg.platform_defaults("win32")
    clash = dict(values, trim_start="W")
    [conflict] = reg.blocking_conflicts(clash)
    assert {conflict.first, conflict.second} == {"trim_start", "trim_end"}
    assert "字幕起点" in conflict.describe() and "字幕终点" in conflict.describe()
    # Review keys override Studio keys only while reviewing: a note, never a block.
    notes = [c for c in reg.conflicts(values) if not c.blocking]
    assert any({c.first, c.second} == {"play_pause", "review_play_context"} for c in notes)
    # Different pages may share a combination.
    assert values["home.search"] == values["split_at_playhead"] == "Ctrl+K"
    # App-wide keys clash with everything.
    assert reg.blocking_conflicts(dict(values, save="Ctrl+0"))


def test_stored_values_migrate_and_new_defaults_never_steal(qapp):
    stored = {"merge_tool": "M", "reasr_review": "R", "toggle_review": "Shift+R", "edit_review": "E",
              "confirm_next_review": "Ctrl+Enter", "track_gain": "Ctrl+A"}
    values, unbound = reg.load_values(stored, "win32")
    assert values["merge_tool"] == "B" and values["reasr_review"] == "Shift+R" and values["toggle_review"] == "R"
    assert values["confirm_next_review"] == "Ctrl+Return"   # stored "Ctrl+Enter" now actually matches
    assert values["edit_at_playhead"] == "E" and "edit_review" not in values
    assert values["track_gain"] == "Ctrl+A" and values["select_all"] == "" and "select_all" in unbound


def test_export_import_roundtrip_ignores_unknown_ids(qapp):
    values = dict(reg.platform_defaults("win32"), trim_start="Alt+Q")
    text = reg.export_payload(values)
    assert json.loads(text)["format"] == reg.FORMAT
    loaded = reg.import_payload(text.replace('"trim_end"', '"bogus_id"'))
    assert loaded["trim_start"] == "Alt+Q" and "bogus_id" not in loaded
    with pytest.raises(ValueError):
        reg.import_payload('{"bindings": {}}')


def test_save_merges_into_studio_settings_and_notifies(qapp, tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"project_root": "X", "mcp": {"enabled": False}, "shortcuts": {"forward": "L"}}),
                    encoding="utf-8")
    monkeypatch.setattr(reg, "settings_path", lambda: path)
    seen = []
    reg.subscribe(seen.append)
    try:
        reg.save_values({"forward": "Shift+L", "home.start_run": "F5"})
    finally:
        reg.unsubscribe(seen.append)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["project_root"] == "X" and payload["mcp"] == {"enabled": False}
    assert payload["shortcuts"]["forward"] == "Shift+L" and payload["shortcuts"]["home.start_run"] == "F5"
    assert seen and seen[-1]["forward"] == "Shift+L"


def _dispatch_page(**overrides):
    from twobyteasr.studio_ui import SubtitleStudioPage
    calls = []
    callbacks = {name: (lambda name=name: calls.append(name)) for name in reg.BY_ID}
    callbacks["select_all"] = lambda: False  # nothing focused that can select
    page = SimpleNamespace(
        _editing_has_focus=lambda: False, _studio_ime_composing=False, _review_mode=False,
        timeline=SimpleNamespace(cancel_selection_gesture=lambda: False),
        _interaction_runtime_audit=SimpleNamespace(measure=lambda name: __import__("contextlib").nullcontext()),
        _command_callbacks=callbacks, _CONTEXTUAL_SHORTCUTS=SubtitleStudioPage._CONTEXTUAL_SHORTCUTS,
        _shortcut_lookup={}, _review_shortcut_lookup={})
    values = reg.platform_defaults("win32")
    for action in reg.ACTIONS:
        if action.scope == "studio":
            page._shortcut_lookup.setdefault(values[action.id], action.id)
        elif action.scope == "studio.review":
            page._review_shortcut_lookup.setdefault(values[action.id], action.id)
    page.__dict__.update(overrides)
    dispatch = lambda sequence: SubtitleStudioPage._dispatch_shortcut_sequence(page, sequence)
    return page, dispatch, calls


def test_dispatch_one_press_one_command_and_review_precedence(qapp):
    page, dispatch, calls = _dispatch_page()
    assert dispatch("Q") and calls == ["trim_start"]
    assert dispatch("Space") and calls[-1] == "play_pause"
    assert not dispatch("Ctrl+Return")          # review-only outside review
    page._review_mode = True
    assert dispatch("Space") and calls[-1] == "review_play_context"
    assert dispatch("Ctrl+Enter") and calls[-1] == "confirm_next_review"  # was unreachable before
    assert dispatch("Num+Enter") and calls[-1] == "confirm_review"
    assert dispatch("3") and calls[-1] == "review_adopt_3"
    assert dispatch("E") and calls[-1] == "edit_at_playhead"  # E keeps its meaning in review
    assert dispatch("Q") and calls[-1] == "trim_start"        # Studio keys still work while reviewing


def test_typing_never_triggers_letter_or_space_shortcuts(qapp):
    page, dispatch, calls = _dispatch_page(_editing_has_focus=lambda: True)
    for key in ("Q", "W", "E", "Space", "A"):
        assert not dispatch(key)
    page._editing_has_focus = lambda: False
    page._studio_ime_composing = True
    assert not dispatch("Q") and calls == []


def test_contextual_command_declines_so_the_widget_gets_the_key(qapp):
    _page, dispatch, calls = _dispatch_page()
    assert not dispatch("Ctrl+A") and calls == []
    assert not dispatch("Alt+Q")  # Alt+Q is not Q


def test_settings_panel_records_resolves_unbinds_and_restores(qapp, tmp_path):
    from PySide6.QtGui import QKeySequence
    from twobyteasr.studio_shortcuts import STUDIO_COMMANDS, ShortcutSettingsPanel
    panel = ShortcutSettingsPanel(reg.platform_defaults(), None)
    assert set(panel.values()) == set(STUDIO_COMMANDS)
    panel._editors["trim_start"].setKeySequence(QKeySequence("W"))
    assert not panel._save_button.isEnabled() and "字幕终点" in panel.conflict_label.text()
    assert not panel.resolve_button.isHidden()
    panel.resolve_button.click()
    assert panel.values()["trim_start"] == "W" and panel.values()["trim_end"] == ""
    assert panel._save_button.isEnabled()
    from PySide6.QtWidgets import QToolButton
    panel.findChild(QToolButton, "shortcutReset_trim_end").click()
    assert panel.values()["trim_end"] == "W"  # its default now clashes again
    panel.findChild(QToolButton, "shortcutReset_trim_start").click()
    assert panel.values()["trim_start"] == "Q" and panel._save_button.isEnabled()
    panel.findChild(QToolButton, "shortcutClear_razor_tool").click()
    assert panel.values()["razor_tool"] == ""
    panel.search.setText("剃刀")
    visible = [aid for aid, row in panel._rows.items() if not panel.table.isRowHidden(row)]
    assert visible == ["razor_tool"]
    exported = tmp_path / "keys.json"
    exported.write_text(reg.export_payload(dict(reg.platform_defaults(), razor_tool="Shift+C")), encoding="utf-8")
    assert panel.import_file(str(exported)) and panel.values()["razor_tool"] == "Shift+C"
    panel.deleteLater()


def test_settings_panel_refuses_system_keys(qapp, monkeypatch):
    from PySide6.QtGui import QKeySequence
    from twobyteasr.studio_shortcuts import ShortcutSettingsPanel
    monkeypatch.setattr(reg, "reserved_reason", lambda sequence, platform=None: "系统使用" if sequence == "Alt+Tab" else "")
    panel = ShortcutSettingsPanel(reg.platform_defaults(), None)
    panel._editors["save"].setKeySequence(QKeySequence("Alt+Tab"))
    assert panel.values()["save"] == "" and "系统使用" in panel.conflict_label.text()
    panel.deleteLater()


def test_application_page_covers_every_scope(qapp):
    from twobyteasr.studio_shortcuts import ShortcutSettingsPanel
    panel = ShortcutSettingsPanel(reg.current_values(), None, scopes=tuple(reg.SCOPE_LABELS), embedded=True)
    assert {"home.start_run", "proofread.find", "app.zoom_reset", "review_adopt_1", "trim_start"} <= set(panel.values())
    panel.deleteLater()


def test_settings_dialog_does_not_ask_to_save_after_searching_shortcuts(tmp_path):
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QApplication, QKeySequenceEdit
    from twobyteasr.application_settings_ui import ApplicationSettingsDialog
    app = QApplication.instance() or QApplication([])
    dialog = ApplicationSettingsDialog(None, {}, tmp_path / "Projects", browse=lambda *a: None,
                                       clear_recent=lambda: None, reset_layout=lambda: None)
    dialog.shortcut_panel.search.setText("吸附")          # looking around is not a change
    assert dialog._values() == dialog._saved_values
    editor = dialog.shortcut_panel.findChild(QKeySequenceEdit, "shortcutEditor_toggle_snap")
    editor.setKeySequence(QKeySequence("Shift+S"))        # an unsaved binding is
    assert dialog._values() != dialog._saved_values
    dialog._save_shortcuts()                              # saved by the page's own button
    assert dialog._values() == dialog._saved_values
    dialog.deleteLater()
    app.processEvents()
