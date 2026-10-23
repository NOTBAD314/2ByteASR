"""Application-wide settings dialog shared by every workspace.

Recognition, Project Library and Studio Editor all open this exact dialog,
so preferences (including the UI theme) are always one click away and are
managed by a single code path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..projects.studio_project import project_library_root, studio_settings_path
from ..diagnostics.build_identity import about_build_text
from ..design.studio_theme import StudioComboBox, apply_secondary_surface_theme
from ..design.theme_manager import apply_theme, available_themes, theme_key
from ..design.ui_theme import DEFAULT_THEME_KEY, theme_display_label

from ..i18n import bind_text, tr
from .lazy_pages import existing_page
from .settings_lifecycle import owned_settings, retain, trace, normalized_preferences


def _preferences_snapshot():
    try:
        payload = json.loads(studio_settings_path().read_text(encoding="utf-8"))
        value = payload.get("studio_preferences", {}) if isinstance(payload, dict) else {}
        prefs, repaired = normalized_preferences(value)
        if not isinstance(payload, dict) or not isinstance(value, dict):
            repaired.append('studio_preferences')
        return prefs, repaired
    except (OSError, ValueError, TypeError):
        return {}, ['settings_file'] if studio_settings_path().is_file() else []


def read_studio_preferences() -> dict[str, object]:
    return _preferences_snapshot()[0]


def _write_settings_json(mutate) -> None:
    path = studio_settings_path()
    repair = False
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError, TypeError):
        payload = {}
        repair = True
    if not isinstance(payload, dict):
        payload = {}
        repair = True
    if normalized_preferences(payload.get('studio_preferences', {}))[1]:
        repair = True
    if repair and path.is_file():
        import shutil, uuid
        backup = path.with_name(path.name + '.before-repair-' + uuid.uuid4().hex[:10])
        shutil.copy2(path, backup)
        trace('backup-before-repair', 'application')
    mutate(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    from ..storage.atomic_files import write_text_atomic
    write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def clear_recent_project_metadata() -> None:
    def mutate(payload: dict) -> None:
        payload["recent_projects"] = []

    _write_settings_json(mutate)


def save_hub_preferences(
    root: str,
    auto_save: bool,
    interval: int,
    recent_count: int,
    cover: bool,
    restore_layout: bool,
    recovery_policy: str = "ask",
    reduce_motion: bool | None = None,
    startup_page: str | None = None,
    speaker_main_tracks: int | None = None,
) -> None:
    def mutate(payload: dict) -> None:
        previous_preferences = payload.get("studio_preferences", {})
        previous_reduce_motion = (
            bool(previous_preferences.get("reduce_motion", False))
            if isinstance(previous_preferences, dict) else False
        )
        if root:
            payload["project_root"] = str(Path(root).expanduser())
        else:
            payload.pop("project_root", None)
        payload["studio_preferences"] = dict(previous_preferences) if isinstance(previous_preferences, dict) else {}
        payload["studio_preferences"].update({
            "autosave_enabled": bool(auto_save), "autosave_interval_seconds": int(interval),
            "recent_project_count": int(recent_count), "auto_cover": bool(cover),
            "restore_layout": bool(restore_layout),
            "recovery_policy": recovery_policy if recovery_policy in {"ask", "auto", "official"} else "ask",
            "reduce_motion": (
                previous_reduce_motion if reduce_motion is None else bool(reduce_motion)
            ),
        })
        if speaker_main_tracks is not None:
            payload["studio_preferences"]["speaker_main_tracks"] = int(speaker_main_tracks)
        if startup_page is not None:
            payload["studio_preferences"]["startup_page"] = (
                "project_library" if startup_page == "project_library" else "recognition"
            )

    _write_settings_json(mutate)


@owned_settings('application')
def open_application_settings(
    parent: QWidget,
    *,
    on_saved=None,
    reset_layout=None,
    refresh_library=None,
    initial_section=None,
) -> bool:
    """Open the shared Application Settings dialog.

    Returns True when the user saved. The dialog never navigates pages,
    rescans the project library, or touches any project content: saving only
    persists preferences and re-applies the UI theme.
    """
    from .application_settings_ui import ApplicationSettingsDialog
    preferences, repaired_fields = _preferences_snapshot()
    owner = parent.window()
    advanced_owner = owner if hasattr(owner, 'advanced_disclosure') else None

    def _clear_recent():
        clear_recent_project_metadata()
        if callable(refresh_library):
            refresh_library()

    dialog = ApplicationSettingsDialog(
        parent, preferences, project_library_root(), browse=_choose_hub_project_root,
        clear_recent=_clear_recent, reset_layout=reset_layout,
        advanced_owner=advanced_owner, repaired_fields=repaired_fields,
    )
    retain(owner, dialog, 'application')
    from ..diagnostics.event_log import emit
    from ..diagnostics.support_dialog import open_support_dialog
    from PySide6.QtWidgets import QDialogButtonBox
    report_button = dialog.buttons.addButton("回报问题／导出诊断", QDialogButtonBox.ButtonRole.ActionRole)
    report_button.clicked.connect(lambda: open_support_dialog(dialog, getattr(parent, "_studio_page", None)))
    emit("settings.dialog", result="completed", phase="created")
    dialog.finished.connect(lambda code: emit("settings.dialog",result="completed",phase="closed",dialog_code=code))
    dialog.destroyed.connect(lambda: emit("settings.dialog",result="completed",phase="destroyed"))
    root_edit, auto_save, interval = dialog.root_edit, dialog.auto_save, dialog.interval
    cover, restore_layout_box = dialog.cover, dialog.restore_layout_box
    recovery_policy, theme_combo = dialog.recovery_policy, dialog.theme_gallery
    reduce_motion_box = dialog.reduce_motion_box
    if isinstance(initial_section, str):
        from ..i18n import tr
        matches = (dialog.navigation.findItems(initial_section, Qt.MatchFlag.MatchExactly)
                   or dialog.navigation.findItems(str(tr(initial_section)), Qt.MatchFlag.MatchExactly))
        if matches: dialog.navigation.setCurrentItem(matches[0])
    trace('showing', 'application')
    emit("settings.dialog", result="started", phase="shown")
    if dialog.exec() != QDialog.DialogCode.Accepted:
        # 2026-10-14: each opening used to stay alive (~770 widgets) and every
        # later theme switch restyled all of them; the theme preview made that visible.
        dialog.deleteLater()
        owner._application_settings_dialog = None
        return False
    dialog.storage_panel.save_policy()
    # Local MCP access (additive "mcp" settings key; off by default).
    from ..local_mcp.mcp_common import save_settings as save_mcp_settings
    mcp_values = save_mcp_settings(dialog.mcp_values())
    from ..local_mcp import mcp_bridge
    if mcp_values["enabled"] or mcp_bridge._BRIDGE is not None:
        mcp_bridge.bridge_for(owner).apply_settings(mcp_values)
    workshop = existing_page(owner, 'workshop')
    if workshop is not None:
        workshop.refresh()
    previous_root = str(project_library_root())
    save_hub_preferences(
        root_edit.text().strip(), bool(auto_save.isChecked()), int(interval.currentData() or 60),
        int(preferences.get("recent_project_count", 9) or 9), bool(cover.isChecked()), bool(restore_layout_box.isChecked()),
        str(recovery_policy.currentData() or "ask"),
        bool(reduce_motion_box.isChecked()),
        str(dialog.startup_page.currentData() or "recognition"),
        speaker_main_tracks=int(dialog.speaker_tracks.currentData() or 2),
    )
    _apply_speaker_tracks_to_open_project(owner)
    QApplication.instance().setProperty("reduceMotion", bool(reduce_motion_box.isChecked()))
    if advanced_owner is not None:
        from PySide6.QtWidgets import QComboBox
        from ..storage.settings import save_runtime_settings
        for key, control in dialog.advanced_controls.items():
            target = getattr(advanced_owner, key)
            if isinstance(control, QComboBox):
                target.setCurrentIndex(control.currentIndex())
            else:
                target.setChecked(control.isChecked())
        runtime = advanced_owner.legacy.RUNTIME_SETTINGS
        switches = runtime.setdefault('switches', {})
        switches['dialogue_coverage_mode'] = str(advanced_owner.dialogue_coverage.currentData() or 'all_dialogue')
        for name, key in (('review_track', 'output_review_track'), ('jianying_txt', 'output_jianying_txt'), ('speaker_tracks', 'output_speaker_tracks')):
            switches[key] = getattr(advanced_owner, name).isChecked()
        for name, key in (('refresh_polish', 'force_refresh_polish'), ('refresh_group', 'force_refresh_group')):
            runtime.setdefault('cache', {})[key] = getattr(advanced_owner, name).isChecked()
        advanced_owner.legacy.RUNTIME_SETTINGS, _, _ = save_runtime_settings(runtime)
    if callable(on_saved):
        on_saved()
    # A moved project root invalidates the visible library; refresh it only
    # for that data change, never for a pure theme save.
    if root_edit.text().strip() and Path(root_edit.text().strip()).expanduser() != Path(previous_root).expanduser():
        if callable(refresh_library):
            refresh_library()
    apply_theme(str(theme_combo.currentData() or DEFAULT_THEME_KEY), QApplication.instance())
    dialog.deleteLater()
    owner._application_settings_dialog = None
    return True


def _choose_hub_project_root(dialog: QDialog, editor: QLineEdit) -> None:
    chosen = QFileDialog.getExistingDirectory(dialog, tr('选择默认工程目录'), editor.text())
    if chosen:
        editor.setText(chosen)


def _apply_speaker_tracks_to_open_project(owner) -> None:
    """A new 「默认独立字幕轨」 regroups the open project now (one undo step)
    when its groups are automatic; other projects follow when opened."""
    page = getattr(owner, "_studio_page_instance", None)
    project = getattr(page, "project", None)
    if project is None:
        return
    from ..projects.studio_project import speaker_track_preference
    from ..recognition.speaker_roles import POLICY, state_of
    state = state_of(project)
    cap = speaker_track_preference()
    if (not cap or not state or not state.get("grouped") or state.get("cap_chosen")
            or (state.get("policy") == POLICY and int(state.get("cap") or 0) == cap)):
        return
    from ..studio.studio_speaker_roles import organize
    organize(page)
