"""Canvas inline editing, subtitle position overlay glue, and editor
card theming for Subtitle Studio."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from time import perf_counter
from PySide6.QtCore import (QPoint, QRect, QTimer, Qt)
from PySide6.QtGui import (QColor, QFont, QPen, QTextCharFormat, QTextCursor, QTextOption)
from PySide6.QtWidgets import (QApplication)
from .studio_cards import _CanvasInlineEdit
from .studio_commands import (AdoptReviewCandidateCommand, MutationOrigin, cue_by_id)
from .style_recipe import (recipe_payload_for_style, route_recipe)
from .ui_theme import theme_definition

from .i18n import bind_text

class StudioCanvasEditMixin:
    """Feature-domain mixin; host class provides widgets and state."""

    def _toggle_position_edit(self, enabled: bool) -> None:
        if not hasattr(self, "position_overlay"):
            return
        if enabled and (not self.project or not self.selected_cue_id):
            self.position_edit_button.setChecked(False)
            return
        self.ensure_active_subtitle_renderer(reason="transform_toggle")

    def _sync_transform_visual_overlay(self) -> None:
        """Compatibility hook: the interaction overlay is the sole visual."""
        source = getattr(self, "position_overlay", None)
        if source is None:
            return
        if source.isVisible():
            source.raise_()

    def _commit_canvas_style(self, *, position: tuple[int, int] | None = None, font_size: float | None = None) -> None:
        return self.style_controller._commit_canvas_style(position=position, font_size=font_size)

    def _position_overlay_font_preview(self, value: float) -> None:
        web = bool(getattr(self.position_overlay,'_web_theme_transform',False))
        if hasattr(self, "style_font_size") and not web:
            self._updating_style_ui = True
            try:
                self.style_font_size.setValue(round(value))
            finally:
                self._updating_style_ui = False
            self._refresh_style_preview()
        if self.selected_cue_id:
            current = self._live_transform_overrides.setdefault(self.selected_cue_id, {})
            current["font_size"] = float(value)
            if web and getattr(self,'_web_resize_anchor',None):
                ax,ay=self._web_resize_anchor
                current['preview_anchor_x']=ax*self.project.render_settings.get('play_res_x',1920)
                current['preview_anchor_y']=ay*self.project.render_settings.get('play_res_y',1080)
            if not self._transform_preview_timer.isActive():
                self._transform_preview_timer.start()

    def _position_overlay_interaction_started(self) -> None:
        if self._subtitle_transform_interactive:
            return
        self._subtitle_transform_interactive = True
        bounds=getattr(self.position_overlay,'_measured_bounds',None)
        content=self.position_overlay._content_rect()
        self._web_resize_anchor = ((bounds.center().x()-content.x())/max(1,content.width()),
            (bounds.center().y()-content.y())/max(1,content.height())) if bounds is not None else None
        cue = self._cue_lookup.get(self.selected_cue_id)
        payload = (
            recipe_payload_for_style(self.project.style_recipes, cue.style_id)
            if self.project and cue else {}
        )
        if payload.get('webTheme'):
            # Keep the exact currently visible raster during a gesture. A
            # fresh browser request here can replace it with an earlier frame.
            return
        if payload and route_recipe(payload).engine == "remotion":
            # Force bypasses a cached Fidelity frame and publishes canonical
            # LIVE once before the first drag delta becomes visible.
            self._schedule_advanced_preview(
                payload, force=True, queue_fidelity=False
            )
        else:
            self._schedule_advanced_preview(
                payload or {"engine": "native"}, force=True, queue_fidelity=False
            )

    def _finish_position_overlay_interaction(self) -> None:
        if not self._subtitle_transform_interactive:
            return
        self._subtitle_transform_interactive = False
        self._transform_preview_timer.stop()
        self._advanced_live_render_generation = getattr(self, "_advanced_live_render_generation", 0) + 1
        self._advanced_live_inflight_key = ""
        self._subtitle_transform_handoff_cue_id = self.selected_cue_id
        cue = self._cue_lookup.get(self.selected_cue_id)
        payload = (
            recipe_payload_for_style(self.project.style_recipes, cue.style_id)
            if self.project and cue else {}
        )
        if (payload and route_recipe(payload).engine == "remotion") or getattr(self, "_multitrack_composition_active", False):
            self._schedule_advanced_preview(payload or {"engine": "native"}, force=True,
                queue_fidelity=bool(payload and route_recipe(payload).engine == "remotion"))
        self.ensure_active_subtitle_renderer(reason="transform_finished")

    def _position_overlay_font_committed(self, value: float) -> None:
        try:
            self._position_overlay_font_preview(value)
            self._flush_transform_preview()
            self._commit_canvas_style(font_size=value)
            self._live_transform_overrides.pop(self.selected_cue_id, None)
            self._refresh_ass_preview()
        finally:
            self._finish_position_overlay_interaction()

    def _position_overlay_cancelled(self) -> None:
        self._live_transform_overrides.pop(self.selected_cue_id, None)
        self.advanced_cue_overlay.set_transform_preview({})
        if self.project and self.selected_cue_id:
            self._load_style_inspector()
            self._refresh_ass_preview()
        self._finish_position_overlay_interaction()

    def _set_subtitle_editor_visible(self, visible: bool) -> None:
        card = getattr(self, "subtitle_edit_card", None)
        if card is None:
            return
        card.setVisible(bool(visible))
        if visible:
            card.raise_()

    def _widget_alive(self, widget) -> bool:
        if widget is None:
            return False
        try:
            from shiboken6 import isValid
            return bool(isValid(widget))
        except Exception:
            try:
                widget.objectName()
                return True
            except RuntimeError:
                return False

    def _restore_studio_video(self) -> None:
        host = getattr(self, "video_overlay_host", None)
        video = getattr(self, "video", None)
        if host is None or not self._widget_alive(video):
            return
        if video.parentWidget() is host:
            return
        layout = host.layout()
        if layout is None:
            return
        layout.addWidget(video, 0, 0)

    def _edit_subtitle_at_playhead(self) -> None:
        """Resolve E from the current clock; an open editor keeps its own ID."""
        if not self.project:
            return
        if getattr(self, "_canvas_editor", None) is not None:
            self._canvas_editor.setFocus(Qt.FocusReason.ShortcutFocusReason)
            return
        snapshot = self.video.playback_position_snapshot()
        position = round(snapshot.presentation_media_ms)
        cue = self.cue_controller.sync_playhead_target(position, force=True)
        if cue is None:
            bind_text(self.save_state, '当前没有可编辑字幕')
            return
        self.select_cue(cue.id)
        self._manual_selection_hold = True
        self._begin_canvas_inline_edit()

    def _begin_canvas_inline_edit(self) -> None:
        started = perf_counter()
        if getattr(self, '_canvas_editor', None) is not None:
            self._canvas_editor.setFocus(Qt.FocusReason.ShortcutFocusReason)
            return
        if not self.project or not self.selected_cue_id:
            return
        cue = self._cue_lookup.get(self.selected_cue_id)
        if cue is None:
            return
        if cue.speaker_id in self.timeline.locked_speakers:
            bind_text(self.save_state, '轨道已锁定，请先解锁')
            return
        # Editing is a transactional operation: pause first, then lock the
        # cue/candidate identity used for commit and cancel. This prevents a
        # moving playhead or review navigation from applying text to another
        # cue while the editor is open.
        try:
            if self.video.controller and not bool(self.video.playback_position_snapshot().paused):
                self.video.set_paused(True)
                self._sync_play_button(True)
        except (RuntimeError, AttributeError):
            pass
        if self._review_mode:
            candidate_id = ""
            candidates = getattr(self, "_review_candidates", ())
            if candidates:
                candidate_id = f"{cue.id}:candidate:{getattr(self, '_review_selected_candidate_index', 0)}"
            self._review_edit_lock = {"cue_id": cue.id, "candidate_id": candidate_id}
        if getattr(self, "_canvas_editor", None) is not None:
            QApplication.setActiveWindow(self.window())
            self._canvas_editor.setFocus(Qt.FocusReason.ShortcutFocusReason)
            return
        # Use the existing transaction lock for normal editing too. Playback
        # and an explicit selection change may happen before this is committed.
        if not self._review_mode:
            self._review_edit_lock = {'cue_id': cue.id, 'candidate_id': ''}
        editor = self.subtitle_edit_input
        if editor.toPlainText() != cue.text and getattr(self, "_canvas_editor", None) is not editor:
            editor.setPlainText(cue.text)
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        editor.setTextCursor(cursor)
        self._set_subtitle_editor_visible(True)
        self._canvas_editor = editor
        self.position_overlay._inline_editing = True
        self.position_overlay.hide()
        self._sync_transform_visual_overlay()
        self._live_edit_text_overrides[cue.id] = cue.text
        payload = recipe_payload_for_style(self.project.style_recipes, cue.style_id)
        if not payload or route_recipe(payload).engine != "remotion":
            self._refresh_ass_preview()
        self._canvas_editor_hint = None
        self.window().activateWindow()
        QApplication.setActiveWindow(self.window())
        editor.setFocus(Qt.FocusReason.ShortcutFocusReason)
        QTimer.singleShot(0, lambda target=editor: target.setFocus(Qt.FocusReason.ShortcutFocusReason))
        self._studio_trace(
            "EDIT_CARD_OPEN", cue_id=cue.id, visible=editor.isVisible(),
            current_text=editor.toPlainText(),
            editor_show_ms=round((perf_counter() - started) * 1000, 2),
        )
        return
        self._studio_trace("INLINE_BEGIN", cue_id=self.selected_cue_id)
        focus_before = QApplication.focusWidget()
        editor = _CanvasInlineEdit(self)
        editor.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        editor.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        editor.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        editor.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        editor.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        created = perf_counter()
        self._studio_trace("EDITOR_CREATED", cue_id=cue.id, native=True)
        editor.setObjectName("canvasInlineEditor")
        editor.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        editor.setPlainText(cue.text)
        editor.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        editor.document().setDocumentMargin(0)
        editor.setCursorWidth(2)
        style = next((item for item in self.project.styles if item.id == cue.style_id), None)
        if style is not None:
            mapper = self.position_overlay._mapper()
            editor_font = editor.font()
            editor_font.setFamily(style.font_family)
            editor_font.setPixelSize(max(8, round(
                float(style.font_size) * mapper.scale_y * float(style.scale_y) / 100.0
                * self.position_overlay.ASS_VISIBLE_EM_FACTOR
            )))
            editor_font.setStretch(max(1, round(float(style.scale_x) / max(float(style.scale_y), 1e-6) * 100)))
            editor_font.setBold(bool(style.bold)); editor_font.setItalic(bool(style.italic)); editor_font.setUnderline(bool(style.underline))
            editor_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, float(style.spacing or 0.0) * mapper.scale_x)
            editor.setFont(editor_font)
            text_format = QTextCharFormat()
            text_format.setForeground(QColor(style.primary_color))
            text_format.setTextOutline(QPen(
                QColor(style.outline_color),
                max(0.0, float(style.outline_width) * max(mapper.scale_x, mapper.scale_y)),
            ))
            cursor = editor.textCursor()
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.mergeCharFormat(text_format)
            cursor.clearSelection()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            editor.setTextCursor(cursor)
            option = editor.document().defaultTextOption()
            column = (int(style.alignment) - 1) % 3
            option.setAlignment((Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignHCenter, Qt.AlignmentFlag.AlignRight)[column])
            editor.document().setDefaultTextOption(option)
        editor.setMinimumWidth(80)
        editor.setMaximumWidth(max(320, min(720, self.video.width() - 24)))
        editor.setStyleSheet(
            "QPlainTextEdit#canvasInlineEditor { background:rgba(246,248,242,18); color:#fffdf8; "
            "border:1px solid rgba(142,190,151,220); border-radius:3px; padding:1px; "
            "selection-background-color:rgba(113,152,122,95); }"
        )
        rect = self.position_overlay._rendered_text_rect().toRect().adjusted(-3, -3, 3, 3)
        rect.moveTopLeft(self.position_overlay.mapToGlobal(rect.topLeft()))
        video_rect = QRect(self.video.mapToGlobal(QPoint(0, 0)), self.video.size())
        rect.setWidth(min(editor.maximumWidth(), max(editor.minimumWidth(), rect.width())))
        rect.moveLeft(max(video_rect.left() + 6, min(video_rect.right() - rect.width() - 6, rect.left())))
        rect.moveTop(max(video_rect.top() + 6, min(video_rect.bottom() - rect.height() - 6, rect.top())))
        rect.moveTopLeft(self.mapFromGlobal(rect.topLeft()))
        editor.setGeometry(rect)
        editor._wysiwyg_min_height = max(24, rect.height())
        geometry_ready = perf_counter()
        editor.installEventFilter(self)
        editor.textChanged.connect(self._resize_canvas_inline_editor)
        editor.input_method_received.connect(
            lambda preedit, commit, text: (
                self._studio_trace("IME_PREEDIT", cue_id=self.selected_cue_id, preedit=preedit, current_text=text)
                if preedit else None,
                self._studio_trace("IME_COMMIT", cue_id=self.selected_cue_id, commit=commit, current_text=text)
                if commit else None,
            )
        )
        editor.diagnostic.connect(lambda event, fields: self._studio_trace(event, cue_id=self.selected_cue_id, **dict(fields)))
        self.position_overlay._inline_editing = True
        self.position_overlay.update()
        editor.show()
        editor.raise_()
        visible = perf_counter()
        self._canvas_editor = editor
        self._studio_trace("EDITOR_GEOMETRY", cue_id=cue.id, geometry=[rect.x(), rect.y(), rect.width(), rect.height()])
        self._studio_trace("EDITOR_VISIBLE", cue_id=cue.id, visible=editor.isVisible())
        editor.activateWindow()
        editor.setFocus(Qt.FocusReason.MouseFocusReason)
        def activate_editor(target=editor) -> None:
            if target is not getattr(self, "_canvas_editor", None):
                return
            target.raise_()
            target.activateWindow()
            handle = target.windowHandle()
            if handle is not None:
                handle.requestActivate()
            target.setFocus(Qt.FocusReason.ShortcutFocusReason)
            focus = QApplication.focusWidget()
            self._studio_trace("EDITOR_ACTIVE", cue_id=cue.id, active=QApplication.activeWindow() is self.window())
            self._studio_trace("FOCUS_WIDGET", cue_id=cue.id, widget=type(focus).__name__ if focus else "None")
        QTimer.singleShot(0, activate_editor)
        QTimer.singleShot(40, activate_editor)
        focused = perf_counter()
        self._canvas_editor_hint = None
        if self._review_mode:
            self.review_dock_candidates.setEnabled(False)
        self._studio_trace(
            "E_EDIT",
            cue_id=self.selected_cue_id,
            focus_before=type(focus_before).__name__ if focus_before else "None",
            editor_created=True,
            editor_visible=editor.isVisible(),
            geometry=[rect.x(), rect.y(), rect.width(), rect.height()],
            parent=type(editor.parentWidget()).__name__,
            focus=type(QApplication.focusWidget()).__name__ if QApplication.focusWidget() else "None",
            input_method_enabled=editor.testAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled),
            current_text=editor.toPlainText(),
            review_mode=self._review_mode,
            editor_show_ms=round((visible - started) * 1000, 2),
            editor_create_ms=round((created - started) * 1000, 2),
            editor_geometry_ms=round((geometry_ready - created) * 1000, 2),
            editor_focus_ms=round((focused - visible) * 1000, 2),
            ass_refresh_ms=0,
            mpv_reload_ms=0,
            qc_recompute_ms=0,
        )

    def _queue_edit_preview(self) -> None:
        if getattr(self, "_canvas_editor", None) is getattr(self, "subtitle_edit_input", None) and self.selected_cue_id:
            self._edit_preview_timer.start()

    def _apply_subtitle_edit_card_theme(self) -> None:
        """Token-driven sheet for the inline subtitle edit card (all themes)."""
        card = getattr(self, "subtitle_edit_card", None)
        if card is None:
            return
        from .theme_manager import theme_key

        theme = theme_definition(theme_key())
        card.setStyleSheet(
            f"QFrame#subtitleEditCard{{background:{theme.panel};border:1px solid {theme.border};"
            "border-radius:10px;}"
            f"QLabel#subtitleEditCardTitle{{color:{theme.text};font-size:14px;font-weight:700;}}"
            f"QLabel#subtitleEditCardHint{{color:{theme.text_muted};font-size:11px;}}"
            f"QPlainTextEdit#subtitleEditCardInput{{background:{theme.input_surface};color:{theme.text};"
            f"border:1px solid {theme.border};border-radius:8px;padding:10px 14px;"
            f"font-size:24px;font-weight:650;selection-background-color:{theme.accent};}}"
        )

    def _apply_teach_banner_theme(self) -> None:
        banner = getattr(self, "teach_banner", None)
        if banner is None:
            return
        from .theme_manager import theme_key

        theme = theme_definition(theme_key())
        banner.setStyleSheet(
            f"QFrame#studioTeachBanner {{ background:{theme.panel}; border-bottom:1px solid {theme.border}; }}"
            f"QLabel {{ color:{theme.text_secondary}; font-size:12px; }}"
        )

    def refresh_theme_palette(self) -> None:
        """Re-apply page-level themed surfaces after a theme switch."""
        self._apply_subtitle_edit_card_theme()
        self._apply_teach_banner_theme()

    def _flush_edit_preview(self) -> None:
        lock = getattr(self, '_review_edit_lock', None) or {}
        cue_id = lock.get('cue_id') or self.selected_cue_id
        if getattr(self, "_canvas_editor", None) is not self.subtitle_edit_input or not cue_id:
            return
        self._live_edit_text_overrides[cue_id] = self.subtitle_edit_input.toPlainText()
        cue = self._cue_lookup.get(cue_id)
        payload = (
            recipe_payload_for_style(self.project.style_recipes, cue.style_id)
            if self.project and cue else {}
        )
        if payload and route_recipe(payload).engine == "remotion":
            self._schedule_advanced_preview(payload, queue_fidelity=False)
        else:
            self._refresh_ass_preview()

    def _flush_transform_preview(self) -> None:
        if self._subtitle_transform_interactive:
            # Move the existing raster at a bounded cadence. No full-project
            # ASS compile, disk write or new glyph worker for each mouse delta.
            self.advanced_cue_overlay.set_transform_preview(
                self._live_transform_overrides.get(self.selected_cue_id, {})
            )
            self.ensure_active_subtitle_renderer(reason="transform_preview")
            return
        cue = self._cue_lookup.get(self.selected_cue_id)
        payload = (
            recipe_payload_for_style(self.project.style_recipes, cue.style_id)
            if self.project and cue else {}
        )
        if payload and route_recipe(payload).engine == "remotion":
            self._schedule_advanced_preview(payload, queue_fidelity=False)
        else:
            self._refresh_ass_preview()

    def _resize_canvas_inline_editor(self) -> None:
        editor = getattr(self, "_canvas_editor", None)
        if editor is None:
            return
        document = editor.document()
        document.setTextWidth(max(160, editor.width() - 20))
        height = max(getattr(editor, "_wysiwyg_min_height", 24), min(220, round(document.size().height()) + 6))
        rect = editor.geometry()
        rect.setHeight(height)
        rect.moveTop(max(6, min(self.height() - height - 6, rect.top())))
        editor.setGeometry(rect)

    def _commit_canvas_inline_edit(self, *, advance: bool = False) -> None:
        try:
            self._commit_canvas_inline_edit_impl(advance=bool(advance or self._review_mode),play_next=bool(advance))
        finally:
            self._review_fast_select=False

    def _commit_canvas_inline_edit_impl(self, *, advance: bool = False, play_next: bool = False) -> None:
        editor = getattr(self, "_canvas_editor", None)
        if editor is None and hasattr(self, "subtitle_edit_input"):
            editor = self.subtitle_edit_input
        if editor is None:
            return
        self._review_fast_select=bool(advance and self._review_mode)
        lock = getattr(self, "_review_edit_lock", None)
        cue_id = str(lock.get("cue_id")) if isinstance(lock, dict) and lock.get("cue_id") else self.selected_cue_id
        if cue_id and cue_id == getattr(self, "_pending_new_cue_id", ""):
            self._pending_new_cue_id = ""
            self._pending_new_cue_previous_id = ""
            self._pending_new_cue_undo_index = -1
        self._studio_trace("INLINE_COMMIT", cue_id=cue_id, advance=advance)
        value = editor.toPlainText()
        if cue_id:
            self._live_edit_text_overrides.pop(cue_id, None)
        card_editor = editor is getattr(self, "subtitle_edit_input", None)
        if not card_editor:
            editor.deleteLater()
        self._canvas_editor = None
        hint = getattr(self, "_canvas_editor_hint", None)
        if hint is not None:
            hint.deleteLater()
            self._canvas_editor_hint = None
        self.position_overlay._inline_editing = False
        if self._review_mode:
            self.review_dock_candidates.setEnabled(True)
        self._review_edit_lock = None
        previous_row = self.cue_model.row_for_cue_id(cue_id) if cue_id else -1
        target = self._cue_lookup.get(cue_id) if self.project else None
        changed_text = bool(target and target.speaker_id not in self.timeline.locked_speakers
                            and value != target.text)
        if card_editor:
            self._set_subtitle_editor_visible(False)
        if changed_text:
            if advance and self._review_mode:
                cue = cue_by_id(self.project, cue_id)
                self._manual_text_baselines.setdefault(cue_id, cue.text)
                self.undo_stack.push(AdoptReviewCandidateCommand(
                    self.project,
                    cue_id,
                    value,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    lambda cue_id=cue_id: self._cue_changed(cue_id, columns=(3, 4)),
                    command_text="编辑并确认字幕",
                    origin=MutationOrigin.USER_EDIT,
                ))
                self._manual_learning_timer.start()
            else:
                self.cue_controller.set_text(
                    cue_id,
                    value,
                    command_text="编辑字幕",
                    origin=MutationOrigin.USER_EDIT,
                )
        if card_editor:
            editor.clear()
        if not self._review_fast_select:
            self._refresh_ass_preview()
        if (
            self.position_edit_button.isChecked()
            and self.selected_cue_id
            and bool(getattr(self.video, "_paused", True))
        ):
            self._toggle_position_edit(True)
        if self.project and cue_id:
            cue_after = self._cue_lookup.get(cue_id)
            payload = self.project.style_recipes.get(cue_after.style_id, {}) if cue_after else {}
            if isinstance(payload, Mapping) and payload and route_recipe(payload).engine == "remotion":
                self._queue_advanced_preview(payload)
        if advance and self._review_mode:
            if changed_text:
                self._advance_review_after_resolution(previous_row, play=play_next)
            else:
                self._confirm_current_review(play_next=play_next)
        self._review_fast_select=False
        self._studio_trace("INLINE_END", cue_id=cue_id, result="committed")

    def _cancel_canvas_inline_edit(self) -> None:
        editor = getattr(self, "_canvas_editor", None)
        if editor is not None:
            lock = getattr(self, "_review_edit_lock", None)
            cue_id = str(lock.get("cue_id")) if isinstance(lock, dict) and lock.get("cue_id") else self.selected_cue_id
            self._studio_trace("INLINE_CANCEL", cue_id=cue_id)
            if cue_id:
                self._live_edit_text_overrides.pop(cue_id, None)
            card_editor = editor is getattr(self, "subtitle_edit_input", None)
            if card_editor:
                cue = self._cue_lookup.get(cue_id) if cue_id else None
                editor.setPlainText(cue.text if cue is not None else "")
                self._set_subtitle_editor_visible(False)
            else:
                editor.deleteLater()
            self._canvas_editor = None
            hint = getattr(self, "_canvas_editor_hint", None)
            if hint is not None:
                hint.deleteLater()
                self._canvas_editor_hint = None
            self.position_overlay._inline_editing = False
            self._refresh_ass_preview()
            cue = self._cue_lookup.get(cue_id) if cue_id else None
            payload = self.project.style_recipes.get(cue.style_id, {}) if self.project and cue else {}
            if isinstance(payload, Mapping) and payload and route_recipe(payload).engine == "remotion":
                self._queue_advanced_preview(payload)
            if self._review_mode:
                self.review_dock_candidates.setEnabled(True)
            self._review_edit_lock = None
            pending_id = getattr(self, "_pending_new_cue_id", "")
            if cue_id and cue_id == pending_id:
                previous_id = getattr(self, "_pending_new_cue_previous_id", "")
                expected_index = int(getattr(self, "_pending_new_cue_undo_index", -1))
                self._pending_new_cue_id = ""
                self._pending_new_cue_previous_id = ""
                self._pending_new_cue_undo_index = -1
                self.selected_cue_id = previous_id
                if self.undo_stack.index() == expected_index and self.undo_stack.canUndo():
                    self.undo_stack.undo()
                self.select_cue(previous_id)
                self.position_edit_button.setChecked(False)
                self.position_overlay.hide()
            elif self.position_edit_button.isChecked() and self.selected_cue_id:
                self._toggle_position_edit(True)
            self._studio_trace("INLINE_END", cue_id=cue_id, result="cancelled")

    def _position_overlay_moved(self, x: int, y: int) -> None:
        if not hasattr(self, "style_position_x"):
            return
        self._updating_style_ui = True
        try:
            self.style_position_x.setValue(x)
            self.style_position_y.setValue(y)
        finally:
            self._updating_style_ui = False
        if self.selected_cue_id:
            current = self._live_transform_overrides.setdefault(self.selected_cue_id, {})
            current.update({"position_x": int(x), "position_y": int(y)})
            if not self._transform_preview_timer.isActive():
                self._transform_preview_timer.start()

    def _position_overlay_committed(self, x: int, y: int) -> None:
        try:
            with self._interaction_runtime_audit.measure("Transform commit"):
                self._position_overlay_moved(x, y)
                self._flush_transform_preview()
                self._commit_canvas_style(position=(x, y))
                self._live_transform_overrides.pop(self.selected_cue_id, None)
                self._refresh_ass_preview()
        finally:
            self._finish_position_overlay_interaction()
