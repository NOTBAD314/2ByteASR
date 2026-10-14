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

from .studio_project import project_library_root, studio_settings_path
from .build_identity import about_build_text
from .studio_theme import StudioComboBox, apply_secondary_surface_theme
from .theme_manager import apply_theme, available_themes, theme_key
from .ui_theme import DEFAULT_THEME_KEY, theme_display_label

from .i18n import bind_text, tr
from .lazy_pages import existing_page


def read_studio_preferences() -> dict[str, object]:
    try:
        payload = json.loads(studio_settings_path().read_text(encoding="utf-8"))
        value = payload.get("studio_preferences", {}) if isinstance(payload, dict) else {}
        return dict(value) if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_settings_json(mutate) -> None:
    path = studio_settings_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    mutate(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
        if startup_page is not None:
            payload["studio_preferences"]["startup_page"] = (
                "project_library" if startup_page == "project_library" else "recognition"
            )

    _write_settings_json(mutate)


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
    preferences = read_studio_preferences()
    owner = parent.window()
    advanced_owner = owner if hasattr(owner, 'advanced_disclosure') else None

    def _clear_recent():
        clear_recent_project_metadata()
        if callable(refresh_library):
            refresh_library()

    dialog = ApplicationSettingsDialog(
        parent, preferences, project_library_root(), browse=_choose_hub_project_root,
        clear_recent=_clear_recent, reset_layout=reset_layout,
        advanced_owner=advanced_owner,
    )
    root_edit, auto_save, interval = dialog.root_edit, dialog.auto_save, dialog.interval
    cover, restore_layout_box = dialog.cover, dialog.restore_layout_box
    recovery_policy, theme_combo = dialog.recovery_policy, dialog.theme_gallery
    reduce_motion_box = dialog.reduce_motion_box
    if isinstance(initial_section, str):
        from .i18n import tr
        matches = (dialog.navigation.findItems(initial_section, Qt.MatchFlag.MatchExactly)
                   or dialog.navigation.findItems(str(tr(initial_section)), Qt.MatchFlag.MatchExactly))
        if matches: dialog.navigation.setCurrentItem(matches[0])
    if dialog.exec() != QDialog.DialogCode.Accepted:
        # 2026-10-14: each opening used to stay alive (~770 widgets) and every
        # later theme switch restyled all of them; the theme preview made that visible.
        dialog.deleteLater()
        return False
    dialog.storage_panel.save_policy()
    # Local MCP access (additive "mcp" settings key; off by default).
    from .mcp_common import save_settings as save_mcp_settings
    mcp_values = save_mcp_settings(dialog.mcp_values())
    from . import mcp_bridge
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
    )
    QApplication.instance().setProperty("reduceMotion", bool(reduce_motion_box.isChecked()))
    if advanced_owner is not None:
        from PySide6.QtWidgets import QComboBox
        from .settings import save_runtime_settings
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
    return True


def _choose_hub_project_root(dialog: QDialog, editor: QLineEdit) -> None:
    chosen = QFileDialog.getExistingDirectory(dialog, tr('选择默认工程目录'), editor.text())
    if chosen:
        editor.setText(chosen)
