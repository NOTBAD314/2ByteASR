"""Studio controls for original / translation / bilingual display.

Display settings are ``studio_state["bilingual"]`` (see bilingual_layout).
Changes are undoable commands committed like any visual edit, so the render
revision, the live caption scene and the ASS export all see the same state.
``studio_state["bilingual_mode"]`` is kept in step for older readers.
"""
from __future__ import annotations

import copy

from PySide6.QtGui import QUndoCommand

from .bilingual_layout import BilingualSettings, COMPACT_GAP_EM, MODES, compact_defaults, settings_from_state
from .i18n import bind_text, tr

MODE_LABELS = {"original": "显示原文", "translation": "显示译文", "bilingual": "显示双语（原文 + 译文）"}


class SetBilingualDisplayCommand(QUndoCommand):
    def __init__(self, project, settings: BilingualSettings, changed=None, label="双语显示"):
        super().__init__(label)
        self.project = project
        state = project.studio_state
        self.before = (copy.deepcopy(state.get("bilingual")), state.get("bilingual_mode"))
        values = settings.to_dict()
        self.after = (values, settings.mode != "original")
        self.changed = changed

    def _apply(self, value):
        from .studio_commands import _commit_mutation
        from .studio_runtime_state import DirtyDomain
        bilingual, flag = value

        def mutate():
            state = self.project.studio_state
            if bilingual is None:
                state.pop("bilingual", None)
            else:
                state["bilingual"] = copy.deepcopy(bilingual)
            if flag is None:
                state.pop("bilingual_mode", None)
            else:
                state["bilingual_mode"] = bool(flag)

        _commit_mutation(self.project, action_id=self.text(),
                         dirty=(DirtyDomain.NATIVE_SUBTITLE | DirtyDomain.ADVANCED_PREVIEW
                                | DirtyDomain.TIMELINE_PIXELS | DirtyDomain.AUTOSAVE),
                         cue_ids=(), mutate=mutate, changed=self.changed)

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)


def current_settings(page) -> BilingualSettings:
    return settings_from_state(page.project.studio_state if page.project else {})


def sync_controls(page, settings: BilingualSettings | None = None) -> None:
    """Reflect the project's display settings in buttons, editor and timeline."""
    settings = settings or current_settings(page)
    shown = settings.mode != "original"
    for name, checked in (("mono_button", not shown), ("bilingual_button", shown),
                          ("mono_display_action", not shown), ("bilingual_display_action", shown),
                          ("bilingual_toggle_button", shown)):
        widget = getattr(page, name, None)
        if widget is not None:
            widget.blockSignals(True)
            widget.setChecked(checked)
            widget.blockSignals(False)
    for mode, action in (getattr(page, "bilingual_mode_actions", None) or {}).items():
        action.blockSignals(True)
        action.setChecked(mode == settings.mode)
        action.blockSignals(False)
    swap = getattr(page, "bilingual_order_action", None)
    if swap is not None:
        swap.blockSignals(True)
        swap.setChecked(settings.order == "original_first")
        swap.setEnabled(settings.mode == "bilingual")
        swap.blockSignals(False)
    text = getattr(page, "translation_text", None)
    if text is not None:
        text.setVisible(shown)
    timeline = getattr(page, "timeline", None)
    if timeline is not None and hasattr(timeline, "set_bilingual"):
        timeline.set_bilingual(shown)


def apply_display(page, **changes) -> bool:
    """User change of display mode/order/fonts: one undoable visual edit."""
    if not page.project:
        return False
    current = current_settings(page)
    values = current.to_dict()
    values.update({key: value for key, value in changes.items() if value is not None})
    if current.legacy and "mode" in changes and set(changes) == {"mode"}:
        # First explicit choice on an old project starts from the new defaults.
        values.update(BilingualSettings(mode=values["mode"]).to_dict())
    if "bilingual" not in page.project.studio_state and not current.legacy and "layout" not in changes:
        # A project's first bilingual state uses the compact group layout.
        values.update(compact_defaults())
    settings = settings_from_state({"bilingual": values})
    if settings.to_dict() == current.to_dict() and not current.legacy:
        sync_controls(page, current)
        return False
    page.undo_stack.push(SetBilingualDisplayCommand(page.project, settings, None))
    sync_controls(page, settings)
    refresh = getattr(page, "_refresh_ass_preview", None)
    if callable(refresh):
        refresh()
    return True


def build_menu(page, menu) -> None:
    """Toolbar "双语" menu: display mode, order, fonts, translation actions."""
    from PySide6.QtGui import QAction, QActionGroup
    group = QActionGroup(menu)
    group.setExclusive(True)
    page.bilingual_mode_actions = {}
    for mode in MODES:
        action = QAction(tr(MODE_LABELS[mode]), menu)
        action.setCheckable(True)
        action.triggered.connect(lambda _checked=False, value=mode: apply_display(page, mode=value))
        group.addAction(action)
        menu.addAction(action)
        page.bilingual_mode_actions[mode] = action
    menu.addSeparator()
    order = QAction(tr("双语时原文在上（默认译文在上）"), menu)
    order.setCheckable(True)
    order.triggered.connect(lambda checked: apply_display(
        page, order="original_first" if checked else "translation_first"))
    menu.addAction(order)
    page.bilingual_order_action = order
    fonts = QAction(tr("双语字体与字号…"), menu)
    fonts.triggered.connect(lambda: open_style_dialog(page))
    menu.addAction(fonts)
    compact = QAction(tr("套用紧凑双语排版（可撤销）"), menu)
    compact.triggered.connect(lambda: apply_compact_layout(page))
    menu.addAction(compact)
    menu.addSeparator()
    translate = QAction(tr("翻译 / 生成双语字幕…"), menu)
    translate.triggered.connect(page._open_translation_dialog)
    menu.addAction(translate)
    sync_controls(page)


def apply_compact_layout(page) -> bool:
    """Explicit command: compact bilingual group layout for this project, one undo step.

    Lines that overlap other speakers' lines and were placed automatically are
    re-allocated with the group height; hand-placed lines are never moved.
    """
    if not page.project:
        return False
    from .subtitle_stacking import _cluster_overlaps, manual_position, rearrange_subtitles_command
    stack = page.undo_stack
    stack.beginMacro(tr("套用紧凑双语排版"))
    try:
        changed = apply_display(page, layout="ink_v1", gap_ratio=COMPACT_GAP_EM,
                                mode="bilingual" if current_settings(page).mode == "original" else None)
        crowded = [cue.id for cluster in _cluster_overlaps(list(page.project.cues)) if len(cluster) > 1
                   for cue in cluster if not manual_position(cue)]
        if crowded:
            command, _layout = rearrange_subtitles_command(page.project, crowded)
            if command is not None:
                stack.push(command)
                changed = True
    finally:
        stack.endMacro()
    return changed


def open_style_dialog(page) -> None:
    from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFontComboBox,
                                   QFormLayout, QLabel, QVBoxLayout)
    settings = current_settings(page)
    dialog = QDialog(page.window() or page)
    dialog.setWindowTitle(tr("双语字体与字号"))
    layout = QVBoxLayout(dialog)
    note = QLabel(tr("字号按当前字幕样式的百分比计算；预览和导出视频使用同一设置。"))
    note.setWordWrap(True)
    layout.addWidget(note)
    form = QFormLayout()
    inherit = QCheckBox(tr("译文字体跟随字幕样式"), dialog)
    inherit.setChecked(settings.translation_font == "")
    font = QFontComboBox(dialog)
    if settings.translation_font:
        font.setCurrentText(settings.translation_font)
    font.setEnabled(not inherit.isChecked())
    inherit.toggled.connect(lambda checked: font.setEnabled(not checked))
    translation_size = QDoubleSpinBox(dialog)
    original_size = QDoubleSpinBox(dialog)
    for box, value in ((translation_size, settings.translation_scale), (original_size, settings.original_scale)):
        box.setRange(40, 160)
        box.setSuffix(" %")
        box.setDecimals(0)
        box.setValue(round(value * 100))
    form.addRow(inherit)
    form.addRow(tr("译文字体"), font)
    form.addRow(tr("译文字号"), translation_size)
    form.addRow(tr("原文字号（双语时）"), original_size)
    layout.addLayout(form)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dialog)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.Accepted:
        return
    apply_display(page, translation_font="" if inherit.isChecked() else font.currentText().strip(),
                  translation_scale=translation_size.value() / 100.0, original_scale=original_size.value() / 100.0)


class ApplyTranslationSnapshotCommand(QUndoCommand):
    """One undo step for translation records + render view (AI batch or manual edit)."""

    def __init__(self, project, before, after, cue_ids=(), label="翻译字幕", changed=None):
        super().__init__(label)
        self.project = project
        self.before, self.after = copy.deepcopy(before), copy.deepcopy(after)
        self.cue_ids = tuple(str(item) for item in cue_ids)
        self.changed = changed

    def _apply(self, state):
        from .studio_commands import _commit_mutation
        from .studio_runtime_state import DirtyDomain
        from .subtitle_translation import restore_snapshot
        _commit_mutation(self.project, action_id=self.text(),
                         dirty=(DirtyDomain.CUE_CONTENT | DirtyDomain.TIMELINE_PIXELS | DirtyDomain.NATIVE_SUBTITLE
                                | DirtyDomain.ADVANCED_PREVIEW | DirtyDomain.QC | DirtyDomain.AUTOSAVE),
                         cue_ids=self.cue_ids, mutate=lambda: restore_snapshot(self.project, state),
                         changed=self.changed)

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)


def set_manual_translation(page, cue_id, text, changed=None) -> bool:
    """Inline translation edit: a manual record (protected from AI overwrite)."""
    from .subtitle_translation import migrate, set_manual
    project = page.session.project if hasattr(page, "session") else page.project
    if not project:
        return False
    migrate(project)
    before, after = set_manual(project, str(cue_id), str(text or ""))
    if before == after:
        return False
    page.session.undo_stack.push(ApplyTranslationSnapshotCommand(project, before, after, (cue_id,),
                                                                  label="编辑译文", changed=changed))
    return True
