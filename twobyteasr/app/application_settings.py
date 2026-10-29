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
from ..diagnostics.navigation_timing import timed as navigation_timed
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


def update_reminder_enabled() -> bool:
    """Check for updates at every start and pop up a newer version (2026-10-24; on by default)."""
    return bool(read_studio_preferences().get("update_reminder", True))


def save_update_reminder(enabled: bool) -> None:
    """The reminder switch alone (the check box in the update dialog)."""
    def mutate(payload: dict) -> None:
        preferences = payload.get("studio_preferences")
        payload["studio_preferences"] = dict(preferences) if isinstance(preferences, dict) else {}
        payload["studio_preferences"]["update_reminder"] = bool(enabled)

    _write_settings_json(mutate)


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
    update_reminder: bool | None = None,
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
        if update_reminder is not None:
            payload["studio_preferences"]["update_reminder"] = bool(update_reminder)

    _write_settings_json(mutate)


@navigation_timed('settings.read_inputs')
def _dialog_cache_stamp(owner, preferences, repaired_fields, reset_layout):
    """Everything the settings window shows when built; any change rebuilds it."""
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QComboBox
    from ..i18n import current_language
    from ..local_mcp.mcp_common import read_settings as read_mcp_settings
    from ..runtime_paths import get_runtime_paths
    from ..studio import shortcut_registry
    from .ui_zoom import zoom_percent
    paths = get_runtime_paths()
    storage = []
    for name in ('policy.json', 'last-cleanup.json', 'last-uv-cleanup.json'):
        try:
            stat = (paths.user_data_root / 'storage' / name).stat()
            storage.append((stat.st_size, stat.st_mtime_ns))
        except OSError:
            storage.append(None)
    # 高级设置 copies these recognition-page controls (never builds that page).
    advanced = []
    for key in ('dialogue_coverage', 'expected_speakers', 'overwrite', 'review_track', 'jianying_txt',
                'speaker_tracks', 'refresh_polish', 'refresh_group'):
        control = owner.__dict__.get(key)
        if isinstance(control, QComboBox):
            advanced.append((key, control.currentIndex(), control.count(), control.isEnabled()))
        elif control is not None:
            advanced.append((key, control.isChecked(), control.isEnabled()))
    return (json.dumps(preferences, sort_keys=True, default=str), tuple(repaired_fields),
            str(project_library_root()), str(paths.model_root), str(paths.managed_runtime_root),
            str(paths.user_data_root), tuple(storage), theme_key(), current_language(), zoom_percent(),
            str(QSettings('2ByteASR', '2ByteASR').value('frame_export/directory', '')), tuple(advanced),
            tuple(sorted(shortcut_registry.current_values().items())),
            json.dumps(read_mcp_settings(), sort_keys=True, default=str),
            id(existing_page(owner, 'studio')), callable(reset_layout))


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

    2026-10-25: a window closed without changes is kept (one per main window)
    and shown again while everything it shows is unchanged
    (``_dialog_cache_stamp``); rebuilding it took about 2 s.
    """
    from .application_settings_ui import ApplicationSettingsDialog
    from shiboken6 import isValid
    preferences, repaired_fields = _preferences_snapshot()
    owner = parent.window()
    advanced_owner = owner if hasattr(owner, 'advanced_disclosure') else None

    def _clear_recent():
        clear_recent_project_metadata()
        if callable(refresh_library):
            refresh_library()

    from ..diagnostics.event_log import emit
    stamp = _dialog_cache_stamp(owner, preferences, repaired_fields, reset_layout)
    dialog = owner.__dict__.get('_application_settings_cache')
    owner._application_settings_cache = None   # a failing visit must not be reused
    if dialog is not None and (not isValid(dialog) or owner.__dict__.get('_application_settings_cache_stamp') != stamp):
        if isValid(dialog):
            dialog.deleteLater()
        dialog = None
    if dialog is None:
        # Owned by the window, not the page it was opened from, so it outlives page changes.
        dialog = ApplicationSettingsDialog(
            owner, preferences, project_library_root(), browse=_choose_hub_project_root,
            clear_recent=_clear_recent, reset_layout=reset_layout,
            advanced_owner=advanced_owner, repaired_fields=repaired_fields,
        )
        retain(owner, dialog, 'application')
        from ..diagnostics.support_dialog import open_support_dialog
        from PySide6.QtWidgets import QDialogButtonBox
        report_button = dialog.buttons.addButton("回报问题／导出诊断", QDialogButtonBox.ButtonRole.ActionRole)
        report_button.clicked.connect(lambda: open_support_dialog(dialog, getattr(parent, "_studio_page", None)))
        emit("settings.dialog", result="completed", phase="created")
        dialog.finished.connect(lambda code: emit("settings.dialog",result="completed",phase="closed",dialog_code=code))
        dialog.destroyed.connect(lambda: emit("settings.dialog",result="completed",phase="destroyed"))
    else:
        owner._application_settings_dialog = dialog
        dialog.prepare_reuse(clear_recent=_clear_recent, reset_layout=reset_layout)
        trace('reused', 'application')
        emit("settings.dialog", result="completed", phase="reused")
    root_edit, auto_save, interval = dialog.root_edit, dialog.auto_save, dialog.interval
    recovery_policy = dialog.recovery_policy
    if isinstance(initial_section, str):
        dialog.ensure_section(initial_section)
    trace('showing', 'application')
    emit("settings.dialog", result="started", phase="shown")
    if dialog.exec() != QDialog.DialogCode.Accepted:
        owner._application_settings_dialog = None
        if dialog.reusable():
            owner._application_settings_cache = dialog
            owner._application_settings_cache_stamp = stamp
        else:
            # 2026-10-14: each opening used to stay alive (~770 widgets) and every
            # later theme switch restyled all of them; the theme preview made that visible.
            dialog.deleteLater()
        return False

    def chosen(name, key, default):
        """A control's value, or the stored one when its category was never shown."""
        control = dialog.__dict__.get(name)
        if control is None:
            return preferences.get(key, default)
        return control.currentData() if hasattr(control, 'currentData') else control.isChecked()

    if dialog.section_built('存储与缓存'):
        dialog.storage_panel.save_policy()
    if dialog.section_built('外部 AI（MCP）'):
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
    reduce_motion = bool(chosen('reduce_motion_box', 'reduce_motion', False))
    save_hub_preferences(
        root_edit.text().strip(), bool(auto_save.isChecked()), int(interval.currentData() or 60),
        int(preferences.get("recent_project_count", 9) or 9),
        bool(chosen('cover', 'auto_cover', True)), bool(chosen('restore_layout_box', 'restore_layout', True)),
        str(recovery_policy.currentData() or "ask"),
        reduce_motion,
        str(dialog.startup_page.currentData() or "recognition"),
        speaker_main_tracks=int(chosen('speaker_tracks', 'speaker_main_tracks', 2) or 2),
        update_reminder=bool(chosen('update_reminder_box', 'update_reminder', True)),
    )
    _apply_speaker_tracks_to_open_project(owner)
    QApplication.instance().setProperty("reduceMotion", reduce_motion)
    if advanced_owner is not None:
        from PySide6.QtWidgets import QComboBox
        from ..storage.settings import save_runtime_settings
        for key, control in dialog.__dict__.get('advanced_controls', {}).items():
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
        advanced_owner._apply_saved_ai_configuration(source='application_settings')
    if callable(on_saved):
        on_saved()
    # A moved project root invalidates the visible library; refresh it only
    # for that data change, never for a pure theme save.
    if root_edit.text().strip() and Path(root_edit.text().strip()).expanduser() != Path(previous_root).expanduser():
        if callable(refresh_library):
            refresh_library()
    if dialog.section_built('外观'):   # otherwise the theme was neither previewed nor changed
        apply_theme(str(dialog.theme_gallery.currentData() or DEFAULT_THEME_KEY), QApplication.instance())
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
