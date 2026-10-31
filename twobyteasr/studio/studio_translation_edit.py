"""Manual translation UI commands. Every write goes through the record/undo path."""
from __future__ import annotations

import json

from PySide6.QtCore import QEvent, QMimeData, QTimer, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QInputDialog, QScrollArea

from .caption_text_tools import CaptionInputEdit as InputLatencyTextEdit
from PySide6.QtWidgets import QPlainTextEdit
from PySide6.QtGui import QKeyEvent
from ..i18n import tr
from ..subtitle_rules.subtitle_translation import TARGET_LABELS, container_target, mark_manual_intent

MIME = "application/x-2byteasr-translation-text+json"


def selected_ids(page):
    timeline = page.timeline
    ids = set(timeline.translation_selected_ids)
    return [cue.id for cue in sorted(page.project.cues, key=lambda c: (c.start_ms, c.end_ms, c.id))
            if cue.id in ids] if page.project else []


def copy_translation(page):
    if not page.project:
        return False
    view = page.project.generation_metadata.get("translations", {})
    cues = {cue.id: cue for cue in page.project.cues}
    entries = [{"text": view[key], "start_ms": cues[key].start_ms, "end_ms": cues[key].end_ms}
               for key in selected_ids(page) if view.get(key)]
    if not entries:
        return False
    mime = QMimeData()
    mime.setText("\n\n".join(item["text"] for item in entries))
    # Source IDs are deliberately absent: the destination must be selected anew.
    mime.setData(MIME, json.dumps({"version": 1, "layer": "translation",
                                 "target": container_target(page.project), "entries": entries},
                                ensure_ascii=False).encode("utf-8"))
    QApplication.clipboard().setMimeData(mime)
    if QApplication.platformName() != "offscreen" and not QApplication.clipboard().ownsClipboard():
        page.save_state.setText(tr("复制未完成：系统剪贴板正忙，请重试。"))
        return False
    return True


def paste_translation(page):
    ids = selected_ids(page)
    if len(ids) != 1:
        page.save_state.setText(tr("请只选择一条目标译文；多行文字会保留在同一条字幕中。"))
        return False
    mime = QApplication.clipboard().mimeData()
    if not mime or not mime.hasText():
        return False
    return page.cue_controller.set_translation(ids[0], mime.text(), target=page.timeline.subtitle_target_language)


def clear_translation(page):
    ids = selected_ids(page)
    if not ids:
        return False
    stack = page.undo_stack
    if len(ids) > 1:
        stack.beginMacro(tr("清空所选译文"))
    try:
        for cue_id in ids:
            if page.timeline.subtitle_target_language == container_target(page.project):
                mark_manual_intent(page.project, cue_id)
            page.cue_controller.set_translation(cue_id, "", target=page.timeline.subtitle_target_language)
    finally:
        if len(ids) > 1:
            stack.endMacro()
    return True


def choose_cue(timeline, candidates=None):
    cues = list(candidates if candidates is not None else timeline.project.cues)
    cues.sort(key=lambda c: (c.start_ms, c.end_ms, c.id))
    if not cues:
        timeline.edit_blocked.emit(tr("译文需要关联原文；请先在原文轨道添加字幕。"))
        return None
    labels = [f"{c.start_ms / 1000:.3f}–{c.end_ms / 1000:.3f}  [{c.id}]  {c.text[:100]}" for c in cues]
    value, ok = QInputDialog.getItem(timeline, tr("选择关联原文"),
                                    tr("请选择这条译文对应的原文："), labels, 0, False)
    return cues[labels.index(value)] if ok and value in labels else None


def edit_translation(page, cue_id=None):
    if not page.project:
        return
    timeline = page.timeline
    if cue_id is None:
        ids = selected_ids(page)
        cue_id = ids[0] if len(ids) == 1 else ""
    cue = next((cue for cue in page.project.cues if cue.id == cue_id), None)
    if cue is None:
        cue = choose_cue(timeline)
    if cue is None:
        return
    if not timeline.bilingual:
        from .studio_bilingual import apply_display
        apply_display(page, mode="bilingual")
    timeline.select_translation(cue.id)
    text = page.project.generation_metadata.get("translations", {}).get(cue.id, "")
    page._open_caption_editor(cue.id, "translation")


def build_menu(page, menu, cue_id):
    if cue_id:
        view = page.project.generation_metadata.get("translations", {})
        menu.addAction(tr("编辑译文") if view.get(cue_id) else tr("添加译文"),
                       lambda: edit_translation(page, cue_id))
        copy_action = menu.addAction(tr("复制译文"), lambda: copy_translation(page))
        copy_action.setEnabled(any(view.get(key) for key in selected_ids(page)))
        menu.addAction(tr("粘贴为译文"), lambda: paste_translation(page)).setEnabled(
            len(selected_ids(page)) == 1 and QApplication.clipboard().mimeData().hasText())
        menu.addAction(tr("清空译文"), lambda: clear_translation(page))
    else:
        note = menu.addAction(tr("此处没有唯一原文，译文必须关联原文"))
        note.setEnabled(False)
        menu.addAction(tr("选择关联原文并添加译文…"), lambda: edit_translation(page, ""))


def handle_key(page, event):
    if not page.project or getattr(page.timeline, "active_subtitle_layer", "original") != "translation" or page._editing_has_focus():
        return False
    for key, callback in ((QKeySequence.StandardKey.Copy, copy_translation),
                          (QKeySequence.StandardKey.Paste, paste_translation),
                          (QKeySequence.StandardKey.Cut, None)):
        if event.matches(key):
            if callback:
                callback(page)
            elif copy_translation(page):
                clear_translation(page)
            return True
    if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
        clear_translation(page)
        return True
    if event.matches(QKeySequence.StandardKey.SelectAll):
        page.timeline.translation_selected_ids = {cue.id for cue in page.project.cues}
        page.timeline.set_selected_ids(page.timeline.translation_selected_ids, page.timeline.selected_id)
        page.timeline.update()
        return True
    return False


def handle_sequence(page, sequence):
    if not page.project or getattr(page.timeline, "active_subtitle_layer", "original") != "translation" or page._editing_has_focus():
        return False
    keys = QKeySequence(sequence)
    if keys.count() != 1:
        return False
    combination = keys[0]
    return handle_key(page, QKeyEvent(QEvent.Type.KeyPress, combination.key(), combination.keyboardModifiers()))


def sync_editor_layer(page, *, explicit=False):
    if explicit:
        page._caption_canvas_edit_target=None
    timeline = page.timeline
    translation = timeline.active_subtitle_layer == "translation"
    target = container_target(page.project) if page.project else ""
    target = TARGET_LABELS.get(target, target)
    label = getattr(page, "current_text_layer_label", None)
    if label is not None:
        label.setText(tr("当前操作：译文（{target}）", target=target) if translation else tr("当前操作：原文"))
    button = getattr(page, "current_cue_section_button", None)
    if button is not None:
        button.setText(tr("当前译文") if translation else tr("当前字幕"))
        if translation:
            button.setChecked(True)
    style_layer = getattr(page, "style_layer", None)
    if style_layer is not None:
        layer = "translation" if translation else "original"
        if getattr(page, "_translation_style_layer_synced", None) != layer:
            page._translation_style_layer_synced = layer
            index = style_layer.findData(layer)
            if index >= 0 and style_layer.currentIndex() != index:
                style_layer.setCurrentIndex(index)
    else:
        for host in getattr(page, "style_native_hosts", ())[:-1]:
            host.setEnabled(not translation)
    style_button = getattr(page, "translation_style_button", None)
    if style_button is not None:
        style_button.setVisible(translation)
    if translation:
        editor = getattr(page, "translation_text", None)
        if editor is not None:
            editor.show()
            parent = editor.parentWidget()
            while parent is not None and not isinstance(parent, QScrollArea):
                parent = parent.parentWidget()
            if parent is not None:
                QTimer.singleShot(0, parent, lambda: parent.ensureWidgetVisible(editor, 0, 40)
                                  if page.timeline.active_subtitle_layer == "translation" else None)


class TranslationTextEdit(InputLatencyTextEdit):
    """A bound draft: one record command per commit, no full snapshot per key."""
    def __init__(self, page, parent=None):
        super().__init__(parent)
        self.page = page
        self.binding = None
        self.dirty = False
        self.composing = False
        self.loading = False
        self.textChanged.connect(self._draft_changed)
        self.setToolTip(tr("Enter 提交 · Shift+Enter 换行 · Esc 取消；点击其他位置也会提交"))

    def bind(self, project, cue_id, text):
        key = (project, cue_id, container_target(project))
        same = self.binding is not None and self.binding[0] is project and self.binding[1:] == key[1:]
        if same and (self.dirty or self.composing):
            return
        if not same:
            if self.commit() is False:return False
        self.binding = key
        self.loading = True
        try:
            tools = getattr(self, "_caption_tools", None)
            cue = next((cue for cue in project.cues if cue.id == cue_id), None)
            if tools is not None and cue is not None:
                tools.hydrate(cue, text)
            elif self.toPlainText() != text:
                self.setPlainText(text)
            self._baseline = self.toPlainText()
            self.dirty = False
        finally:
            self.loading = False

    def _draft_changed(self):
        if self.loading or not self.binding:
            return
        if not self.dirty:
            mark_manual_intent(self.binding[0], self.binding[1])
        self.dirty = True

    def createMimeDataFromSelection(self):
        mime = super().createMimeDataFromSelection()
        if mime.hasFormat(self.MIME):
            try:
                payload = json.loads(bytes(mime.data(self.MIME)))
                payload.update(layer="translation", target=self.binding[2] if self.binding else container_target(self.page.project))
                mime.setData(self.MIME, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            except (ValueError, TypeError):
                pass
        return mime

    def clear_binding(self):
        if self.commit() is False:return False
        self.binding = None
        self.loading = True
        self.clear()
        self.loading = False
        self.dirty = False

    def commit(self):
        if self.composing:
            from PySide6.QtWidgets import QApplication
            method=QApplication.inputMethod()
            if method is not None:method.commit()
            if self.composing:
                self.page.save_state.setText(tr('输入法候选尚未确认，请先确认候选再提交'))
                return False
        if not self.dirty or not self.binding:
            return
        project, cue_id, target = self.binding
        if self.page.project is project:
            if container_target(project) != target:
                self.page.save_state.setText(tr("译文语言已切换，请重新选择字幕后编辑"))
                return
            tools = getattr(self, "_caption_tools", None)
            desired=self.toPlainText()
            if tools is not None and tools.mode.currentIndex():
                from ..caption_style.text_marks import parse_markdown
                desired=parse_markdown(desired)[0]
            if tools is not None:
                before = self.page.undo_stack.index()
                tools.commit()
                cue = tools.current()
                if cue is not None and self.page.undo_stack.index() == before:
                    self.page.cue_controller.set_translation(cue_id, tools.body(cue), target=target)
            else:
                self.page.cue_controller.set_translation(cue_id, self.toPlainText(), target=target)
            from ..caption_style.bilingual_layout import translations_of
            if str(translations_of(project.generation_metadata).get(cue_id,'') or '') != desired:
                self.page.save_state.setText(tr('译文未提交；草稿已保留，可重试'))
                return False
            self.dirty = False
            self._baseline = self.toPlainText()
            return True

    def inputMethodEvent(self, event):
        self.composing = bool(event.preeditString())
        super().inputMethodEvent(event)

    def event(self, event):
        if event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if self.dirty and (event.matches(QKeySequence.StandardKey.Undo) or event.matches(QKeySequence.StandardKey.Redo)):
            return QPlainTextEdit.keyPressEvent(self, event)
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
            if not self.composing:
                self.commit()
                self.page.timeline.setFocus()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and not self.composing:
            self.loading = True
            self.setPlainText(getattr(self, "_baseline", ""))
            self.loading = False
            self.dirty = False
            self.page.timeline.setFocus()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event):
        if self.binding and self.page.project is self.binding[0]:
            self.page.timeline.select_translation(self.binding[1])
            sync_editor_layer(self.page)
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        if self.composing:
            QApplication.inputMethod().commit()
        self.commit()
        super().focusOutEvent(event)
