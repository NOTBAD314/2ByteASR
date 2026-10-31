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
from ..timeline.studio_commands import (AdoptReviewCandidateCommand, MutationOrigin, cue_by_id)
from ..caption_style.style_recipe import (recipe_payload_for_style, route_recipe)
from ..design.ui_theme import theme_definition

from ..i18n import bind_text

from .caption_editor import CaptionEditorMixin

class StudioCanvasEditMixin(CaptionEditorMixin):
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
        if getattr(self,'_caption_transform_retired',False):return
        if getattr(self,'_caption_layer_canvas',False):
            panel=self.caption_transform_panel
            panel._gesture_mode='ratio'
            before=panel._canvas_values
            factor=float(value)/max(.01,float(self.position_overlay._origin_font_size))
            panel.apply({'scale_x':before['scale_x']*factor,'scale_y':before['scale_y']*factor})
            return
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
        self._caption_transform_retired=False
        panel=getattr(self,'caption_transform_panel',None)
        if panel is not None:
            from ..caption_style.caption_layer_transform import resolved_values
            targets=panel.targets()
            if not targets:
                from .presentation_scope import report_scope
                report_scope(self,panel._scope_snapshot,applied=0)
                self._caption_transform_retired=True
                return
            cue=next((c for c in targets if c.id==self.selected_cue_id),targets[0])
            self._remember_canvas_edit_target(cue.id,panel.language.currentData())
            values=resolved_values(self.project,cue,panel.language.currentData()) if cue else None
            if values is not None:
                self._caption_layer_canvas=True
                panel.begin_gesture();panel._canvas_values=values
                panel._canvas_undo_index=self.undo_stack.index()
                return
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
        if payload and payload.get('webTheme'):
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
        if getattr(self,'_caption_layer_canvas',False):
            self._caption_layer_canvas=False
            self.caption_transform_panel.end_gesture()
            self.caption_transform_panel.refresh()
            self.ensure_active_subtitle_renderer(reason='caption_transform_finished')
            return
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
        if getattr(self,'_caption_transform_retired',False):return
        if getattr(self,'_caption_layer_canvas',False):
            self._position_overlay_font_preview(value)
            self._finish_position_overlay_interaction()
            return
        try:
            self._position_overlay_font_preview(value)
            self._flush_transform_preview()
            self._commit_canvas_style(font_size=value)
            self._live_transform_overrides.pop(self.selected_cue_id, None)
            self._refresh_ass_preview()
        finally:
            self._finish_position_overlay_interaction()

    def _position_overlay_cancelled(self) -> None:
        if getattr(self,'_caption_layer_canvas',False):
            panel=self.caption_transform_panel
            panel.end_gesture(cancel=True)
            self._finish_position_overlay_interaction()
            return
        self._live_transform_overrides.pop(self.selected_cue_id, None)
        self.advanced_cue_overlay.set_transform_preview({})
        if self.project and self.selected_cue_id:
            self._load_style_inspector()
            self._refresh_ass_preview()
        self._finish_position_overlay_interaction()

    def _clear_video_gdi(self, screen_rect) -> None:
        """Clear a vacated area in the GDI layer under mpv's swapchain (Windows).

        A hidden native card leaves its pixels in the window surface that the
        compositor shows under the video whenever mpv's swapchain is being
        resized (entering Review shrank the video and the old edit card
        reappeared for a few frames). mpv never paints that GDI layer itself;
        black is what mpv shows there anyway. Nothing visible is covered.
        """
        import ctypes
        from ctypes import wintypes as W
        parent = int(getattr(self, "video", None).internalWinId() or 0) if getattr(self, "video", None) else 0
        if not parent:
            return
        user, gdi = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
        enum_proc = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        user.EnumChildWindows.argtypes = [W.HWND, enum_proc, W.LPARAM]
        user.MapWindowPoints.argtypes = [W.HWND, W.HWND, ctypes.POINTER(W.POINT), W.UINT]
        user.GetDC.argtypes, user.GetDC.restype = [W.HWND], W.HDC
        user.ReleaseDC.argtypes = [W.HWND, W.HDC]
        user.FillRect.argtypes = [W.HDC, ctypes.POINTER(W.RECT), W.HBRUSH]
        gdi.GetStockObject.argtypes, gdi.GetStockObject.restype = [ctypes.c_int], W.HGDIOBJ
        handles = [parent]
        callback = enum_proc(lambda hwnd, _param: handles.append(int(hwnd)) or True)
        user.EnumChildWindows(W.HWND(parent), callback, 0)
        brush = gdi.GetStockObject(4)  # BLACK_BRUSH
        for hwnd in handles:
            rect = W.RECT(*screen_rect)
            points = ctypes.cast(ctypes.pointer(rect), ctypes.POINTER(W.POINT))
            user.MapWindowPoints(None, W.HWND(hwnd), points, 2)
            dc = user.GetDC(W.HWND(hwnd))
            if dc:
                user.FillRect(dc, ctypes.byref(rect), brush)
                user.ReleaseDC(W.HWND(hwnd), dc)

    def _set_subtitle_editor_visible(self, visible: bool) -> None:
        card = getattr(self, "subtitle_edit_card", None)
        if card is None:
            return
        dock = getattr(self, "subtitle_edit_dock", card)
        if visible and hasattr(dock, 'fit_to_workspace'):
            dock.fit_to_workspace()
        dock.setVisible(bool(visible))
        if visible:
            card.updateGeometry()
            if card.layout() is not None:
                card.layout().activate()

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
        attach_canvas = getattr(host, "set_canvas", None)
        if callable(attach_canvas):
            attach_canvas(video)
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
            return
        if getattr(self, '_caption_following', False):
            return
        # The timeline clock has already passed the current edit-sequence
        # mapping. Do not reinterpret source time or resurrect a stale row.
        preferences = self._studio_preferences()
        if preferences.get('caption_pause_on_edit', True) is not False:
            self.video.set_paused(True)
        position = self.timeline.playhead_ms
        selected_target = self._resolve_caption_edit_target()
        cue = self.cue_controller.sync_playhead_target(position, force=True)
        self._caption_follow_track = (selected_target.track_id if selected_target is not None else
                                      cue.speaker_id if cue else self.session.preferred_subtitle_speaker)
        layer = str(preferences.get('caption_default_layer', 'translation'))
        self._caption_follow_layer = layer if layer in {'original', 'translation'} else 'translation'
        self._caption_follow_fallback_original = self._caption_follow_layer == 'translation'
        self._caption_following = True
        self._caption_edit_locked = False
        self._follow_caption_editor(position, force=True)
        self._set_subtitle_editor_visible(True)
        self.timeline.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _begin_canvas_inline_edit(self) -> None:
        return self._open_caption_editor()

    def _queue_edit_preview(self) -> None:
        if getattr(self, '_caption_editor_opening', False):
            return
        if getattr(self, '_caption_draft', None) is not None:
            self._lock_caption_editor()
        if getattr(self, "_caption_draft", None) is not None:
            self._refresh_editor_suggestions()
        draft = getattr(self, '_caption_draft', None)
        cue_id = draft.target.cue_id if draft else self.selected_cue_id
        if getattr(self, "_canvas_editor", None) is getattr(self, "subtitle_edit_input", None) and cue_id:
            recovery = getattr(self, "_draft_recovery", None)
            if recovery is not None:
                recovery.changed()
            # Bounded throttle: long key repeat must not starve preview.
            if not self._edit_preview_timer.isActive():
                # Native preview is derived work; five updates/second leaves
                # space for long-project compile/IPC and continuous typing.
                self._edit_preview_timer.start(200)
                self._edit_preview_queued_at = perf_counter()
                self._studio_trace('EDIT_PREVIEW_QUEUED', cue_id=cue_id, queue_length=1)

    def _apply_subtitle_edit_card_theme(self) -> None:
        card = getattr(self, "subtitle_edit_card", None)
        if card is None:
            return
        from ..design.theme_manager import theme_key
        card.refresh_theme_palette(theme_definition(theme_key()))

    def _apply_teach_banner_theme(self) -> None:
        banner = getattr(self, "teach_banner", None)
        if banner is None:
            return
        from ..design.theme_manager import theme_key

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
        if getattr(self, "_caption_draft", None) is not None:
            return self._flush_caption_editor_preview()
        if __import__("os").environ.get("TWOBYTEASR_DIAGNOSTIC_NO_EDIT_PREVIEW") == "1":
            return
        lock = getattr(self, '_review_edit_lock', None) or {}
        cue_id = lock.get('cue_id') or self.selected_cue_id
        if getattr(self, "_canvas_editor", None) is not self.subtitle_edit_input or not cue_id:
            return
        self._studio_trace('EDIT_PREVIEW_START', cue_id=cue_id,
                           queue_ms=(perf_counter()-getattr(self, '_edit_preview_queued_at', perf_counter()))*1000)
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
        if getattr(self, '_caption_following', False) or getattr(self, "_caption_draft", None) is not None:
            return self._end_caption_editor(keep_open=False)
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
        self._edit_preview_timer.stop()
        self._draft_recovery.discard()
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
        self._caption_following = False
        self._caption_edit_locked = False
        self._set_subtitle_editor_visible(False)
        draft = getattr(self, "_caption_draft", None)
        if draft is not None:
            self._live_edit_text_overrides.pop(draft.target.render_id, None)
            self._caption_draft = None
            self._reset_caption_input_method()
        editor = getattr(self, "_canvas_editor", None)
        if editor is not None:
            self._canvas_editor = None
            self._edit_preview_timer.stop()
            self._draft_recovery.discard()
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
        if getattr(self,'_caption_transform_retired',False):return
        if getattr(self,'_caption_layer_canvas',False):
            self.caption_transform_panel._gesture_mode='delta'
            self.caption_transform_panel.apply({'position_x':int(x),'position_y':int(y)})
            return
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
        if getattr(self,'_caption_transform_retired',False):return
        if getattr(self,'_caption_layer_canvas',False):
            self._position_overlay_moved(x,y)
            self._finish_position_overlay_interaction()
            return
        try:
            with self._interaction_runtime_audit.measure("Transform commit"):
                self._position_overlay_moved(x, y)
                self._flush_transform_preview()
                self._commit_canvas_style(position=(x, y))
                self._live_transform_overrides.pop(self.selected_cue_id, None)
                self._refresh_ass_preview()
        finally:
            self._finish_position_overlay_interaction()
