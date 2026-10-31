"""Studio controls for original / translation / bilingual display.

Display settings are ``studio_state["bilingual"]`` (see bilingual_layout).
Changes are undoable commands committed like any visual edit, so the render
revision, the live caption scene and the ASS export all see the same state.
``studio_state["bilingual_mode"]`` is kept in step for older readers.
"""
from __future__ import annotations

import copy

from PySide6.QtGui import QUndoCommand

from ..caption_style.bilingual_layout import BilingualSettings, COMPACT_GAP_EM, MODES, compact_defaults, settings_from_state
from ..i18n import bind_text, tr

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
        from ..timeline.studio_commands import _commit_mutation
        from ..projects.studio_runtime_state import DirtyDomain
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
    tools = getattr(page, 'translation_text_tools', None)
    if tools is not None: tools.setVisible(shown)
    timeline = getattr(page, "timeline", None)
    if timeline is not None and hasattr(timeline, "set_bilingual"):
        timeline.set_bilingual(shown)


def settings_for_changes(project, **changes) -> BilingualSettings:
    """Resolve one display choice without mutating the project or its history."""
    current = settings_from_state(project.studio_state)
    values = current.to_dict()
    values.update({key: value for key, value in changes.items() if value is not None})
    if current.legacy and "mode" in changes and set(changes) == {"mode"}:
        # First explicit choice on an old project starts from the new defaults.
        values.update(BilingualSettings(mode=values["mode"]).to_dict())
    if "bilingual" not in project.studio_state and not current.legacy and "layout" not in changes:
        # A project's first bilingual state uses the compact group layout.
        values.update(compact_defaults())
    return settings_from_state({"bilingual": values})


def apply_display(page, **changes) -> bool:
    """User change of display mode/order/fonts: one undoable visual edit."""
    if not page.project:
        return False
    current = current_settings(page)
    settings = settings_for_changes(page.project, **changes)
    if settings.to_dict() == current.to_dict() and not current.legacy:
        sync_controls(page, current)
        return False
    page.undo_stack.push(SetBilingualDisplayCommand(page.project, settings, None))
    sync_controls(page, settings)
    refresh = getattr(page, "_refresh_ass_preview", None)
    if callable(refresh):
        refresh()
    # Refresh captures the final display revision. A paused raster-only
    # player does not get a native ASS redraw or a later transport tick to
    # request that revision; explicitly present it without moving the clock.
    present = getattr(page, "_present_caption_scene", None)
    if callable(present):
        present()
    return True


def build_menu(page, menu) -> None:
    """Toolbar "双语" menu: display mode, order, fonts, translation actions."""
    from PySide6.QtGui import QAction, QActionGroup
    from .translation_actions import add_actions
    add_actions(page, menu)
    translate_all = menu.addAction(tr('翻译整个工程…'))
    translate_all.triggered.connect(lambda: page._open_translation_dialog(scope='all'))
    # 2026-10-22 (user): 字幕简繁转换 lives here instead of its own toolbar button.
    from ..design.studio_theme import create_studio_menu
    from .studio_chinese_script import build_menu as build_chinese_script_menu
    script_menu = create_studio_menu(menu, theme_on_show=True)
    script_menu.setObjectName('studioChineseScriptMenu')
    bind_text(script_menu, '字幕简繁转换', property='title')
    menu.addMenu(script_menu)
    page.chinese_script_menu = script_menu
    build_chinese_script_menu(page, script_menu)
    menu.addSeparator()
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
    note = menu.addAction(tr('普通合并会在本机保留并合并已有译文，不发送请求。'))
    note.setEnabled(False)
    menu.aboutToShow.connect(lambda: (sync_controls(page), translate_all.setEnabled(bool(page.project))))
    if not getattr(page, "_bilingual_history_connected", False):
        page.undo_stack.indexChanged.connect(lambda _index: sync_controls(page))
        page._bilingual_history_connected = True
    sync_controls(page)


def apply_compact_layout(page) -> bool:
    """Explicit command: compact bilingual group layout for this project, one undo step.

    Lines that overlap other speakers' lines and were placed automatically are
    re-allocated with the group height; hand-placed lines are never moved.
    """
    if not page.project:
        return False
    from ..caption_style.subtitle_stacking import _cluster_overlaps, manual_position, rearrange_subtitles_command
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

    def __init__(self, project, before, after, cue_ids=(), label="翻译字幕", changed=None, *, display_settings=None):
        super().__init__(label)
        self.project = project
        self.before, self.after = copy.deepcopy(before), copy.deepcopy(after)
        self.cue_ids = tuple(str(item) for item in cue_ids)
        self.changed = changed
        self.display_before = self.display_after = None
        if display_settings is not None:
            self.display_before = (copy.deepcopy(project.studio_state.get("bilingual")),
                                   project.studio_state.get("bilingual_mode"))
            self.display_after = (display_settings.to_dict(), display_settings.mode != "original")
        self.outcome = {"applied": False, "error": None}

    def _apply(self, state):
        from ..timeline.studio_commands import _commit_mutation
        from ..projects.studio_runtime_state import DirtyDomain
        from ..subtitle_rules.subtitle_translation import restore_snapshot
        def mutate():
            restore_snapshot(self.project, state)
            display = self.display_after if state is self.after else self.display_before
            if display is not None:
                for key, value in zip(("bilingual", "bilingual_mode"), display):
                    if value is None:
                        self.project.studio_state.pop(key, None)
                    else:
                        self.project.studio_state[key] = copy.deepcopy(value)
        _commit_mutation(self.project, action_id=self.text(),
                         dirty=(DirtyDomain.CUE_CONTENT | DirtyDomain.TIMELINE_PIXELS | DirtyDomain.NATIVE_SUBTITLE
                                | DirtyDomain.ADVANCED_PREVIEW | DirtyDomain.QC | DirtyDomain.AUTOSAVE
                                | DirtyDomain.PROJECT_METADATA),
                         cue_ids=self.cue_ids, mutate=mutate,
                         changed=self.changed)

    def redo(self):
        self.outcome.update(applied=False, error=None)
        try:
            self._apply(self.after)
        except Exception as exc:
            self.outcome["error"] = exc
            self.setObsolete(True)
            return
        self.outcome["applied"] = True

    def undo(self):
        self._apply(self.before)
        self.outcome["applied"] = False


class ManualTranslationCommand(QUndoCommand):
    """One record and render entry; unrelated translations keep their identity."""
    def __init__(self, project, cue, value, changed=None, *, target=None):
        super().__init__('编辑译文')
        from ..subtitle_rules import subtitle_translation as st
        meta = project.generation_metadata
        if not st._valid_container(meta.get(st.RECORDS_KEY)):
            st.migrate(project)
        else:
            container = meta[st.RECORDS_KEY]
            rendered = meta.get(st.RENDER_KEY, {}).get(cue.id, '')
            record = container['records'].get(cue.id)
            if str(rendered or '').strip() and (not isinstance(record, dict) or str(record.get('text') or '') != str(rendered)):
                # Reuse the legacy reconciliation on just this target. Do not
                # deepcopy or overwrite unrelated records / in-flight results.
                small = dict(container, records={cue.id: record} if record else {})
                reconciled, _ = st._migrated_container({st.RECORDS_KEY:small,st.RENDER_KEY:{cue.id:rendered}},[cue])
                updated = dict(container['records']);updated[cue.id] = reconciled['records'][cue.id]
                meta[st.RECORDS_KEY] = dict(container, records=updated, history=reconciled['history'])
        self.project, self.cue_id, self.changed = project, cue.id, changed
        self.target = st.container_target(project)
        if target is not None and st.normalize_target(target) != self.target:
            raise ValueError('译文语言已切换，请重新选择字幕后编辑')
        self.before = copy.deepcopy(st.records_of(project).get(cue.id))
        self.after = st._record(value, cue.text, origin=st.ORIGIN_MANUAL, target=self.target,
                               previous=st._pushed_previous(self.before), cleared=True if not value else None)
        self.history = {'at': st._now(), 'kind': 'manual', 'cue_id': cue.id,
                        'target': self.target, 'cleared': not bool(value)}
        self.had_container = st._valid_container(meta.get(st.RECORDS_KEY))
        self.had_render = st.RENDER_KEY in meta
        self.before_render = meta.get(st.RENDER_KEY, {}).get(cue.id)

    def _apply(self, record, *, redo):
        from ..subtitle_rules import subtitle_translation as st
        from ..timeline.studio_commands import _commit_mutation
        from ..projects.studio_runtime_state import DirtyDomain
        from ..subtitle_rules.current_issues import invalidate
        def mutate():
            meta = self.project.generation_metadata
            container = meta.get(st.RECORDS_KEY)
            if not st._valid_container(container):
                container = st._empty_container(); container['target'] = self.target
                meta[st.RECORDS_KEY] = container
            if st.container_target_value(container) != self.target:
                raise ValueError('译文语言已变化，不能向另一语言写入旧编辑')
            records = dict(container['records'])
            if record is None:
                records.pop(self.cue_id, None)
            else:
                records[self.cue_id] = copy.deepcopy(record)
            container['records'] = records
            history = [entry for entry in container.get('history', ()) if entry is not self.history]
            if redo:history.append(self.history)
            container['history'] = history[-st.MAX_HISTORY:]
            view = dict(meta.get(st.RENDER_KEY, {}))
            value = str(record.get('text') or '') if record is not None else self.before_render
            if value:view[self.cue_id] = value
            else:view.pop(self.cue_id, None)
            if view or self.had_render or redo:meta[st.RENDER_KEY] = view
            else:meta.pop(st.RENDER_KEY, None)
            if not redo and not self.had_container and not records:
                meta.pop(st.RECORDS_KEY, None)
            st.mark_manual_intent(self.project, self.cue_id)
            invalidate(self.project)
        _commit_mutation(self.project, action_id=self.text(), cue_ids=(self.cue_id,),
            dirty=(DirtyDomain.CUE_CONTENT | DirtyDomain.TIMELINE_PIXELS | DirtyDomain.NATIVE_SUBTITLE |
                   DirtyDomain.ADVANCED_PREVIEW | DirtyDomain.QC | DirtyDomain.AUTOSAVE | DirtyDomain.PROJECT_METADATA),
            mutate=mutate, changed=self.changed)

    def redo(self):self._apply(self.after, redo=True)
    def undo(self):self._apply(self.before, redo=False)


def set_manual_translation(page, cue_id, text, changed=None, *, target=None) -> bool:
    """One manual text transaction, preserving/remapping the daily's local formatting."""
    from ..subtitle_rules.subtitle_translation import clean_translation, source_sha
    from ..caption_style.text_marks import layer_marks, remap_marks, with_marks
    from ..timeline.studio_commands import SetCueFieldsCommand
    project = page.session.project if hasattr(page, "session") else page.project
    if not project:
        return False
    cue = next((cue for cue in project.cues if cue.id == str(cue_id)), None)
    if cue is None:
        return False
    old = project.generation_metadata.get("translations", {}).get(cue.id, "")
    value = clean_translation(text)
    override = copy.deepcopy(cue.appearance_override)
    if value != old:
        marks = layer_marks(cue, "translation")
        if marks:
            override = with_marks(cue, remap_marks(old, value, marks), "translation")
        override.pop("translation_group", None)
    command = ManualTranslationCommand(project, cue, value, changed, target=target)
    style_changed = override != cue.appearance_override
    if old == value and not style_changed and (command.before is None or command.before.get('origin') == 'manual' and command.before.get('status') != 'failed' and command.before.get('source_sha') == source_sha(cue.text) and not command.before.get('legacy')):
        return False
    stack = page.session.undo_stack
    if style_changed:
        stack.beginMacro("编辑译文")
    try:
        stack.push(command)
        if style_changed:
            stack.push(SetCueFieldsCommand(project, cue.id, {"appearance_override": override}, "保留译文局部格式", changed))
    finally:
        if style_changed:
            stack.endMacro()
    return True
