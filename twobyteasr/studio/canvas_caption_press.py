"""Press a caption on the picture to select it and drag it in one gesture.

2026-11-14 (user report: captions could not be dragged on the picture).
Before: only a caption that was already selected, paused, on the chosen
language layer and under the playhead had a drag box. A press on any other
visible caption did nothing and said nothing. Now a single press on a visible
caption pauses playback, selects it, follows the layer that was hit, and the
same gesture keeps dragging once the box is measured.

The drag itself is still the position overlay's: this only delivers the press
the overlay could not receive, then forwards the rest of the gesture.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QToolTip

from ..i18n import tr

DRAG_SLOP_PX = 4
_SELECTION_MODIFIERS = (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
                        | Qt.KeyboardModifier.MetaModifier)


def drag_off_hint() -> str:
    return tr('「在画面中拖动字幕」已关闭，打开它就能直接拖动')


def not_ready_hint() -> str:
    return tr('这条字幕的位置还在计算，稍等一下再拖')


class CanvasCaptionPress:
    def __init__(self, page):
        self.page = page
        self.pending: dict | None = None
        self._dispatching = False
        # The first click of a double-click that selected a caption here.
        self._selected_by_press: tuple[str, float] | None = None

    # -- events from the video canvas -------------------------------------
    def press(self, event) -> bool:
        if self._dispatching:
            return False
        page = self.page
        self.pending = None
        if event.button() != Qt.MouseButton.LeftButton or event.modifiers() & _SELECTION_MODIFIERS:
            return False
        if (getattr(page, 'project', None) is None or getattr(page, '_canvas_editor', None) is not None
                or getattr(page, 'export_workspace', None) is not None):
            return False
        from .canvas_visibility import visible_object_at
        point = QPointF(event.position())
        hit = visible_object_at(page, point)
        if hit is None:
            return False
        cue_id, layer = hit
        self._pause()
        changed = self._select(cue_id, layer)
        self._selected_by_press = (cue_id, time.monotonic()) if changed else None
        button = getattr(page, 'position_edit_button', None)
        if button is not None and not button.isChecked():
            QToolTip.showText(event.globalPosition().toPoint(), drag_off_hint(), page.video)
            return True
        self.pending = dict(point=point, global_point=QPointF(event.globalPosition()),
                            modifiers=event.modifiers(), started=False, moved=False)
        sync = getattr(page, '_sync_canvas_selection', None)
        if callable(sync):
            sync()
        self._try_start()
        return True

    def move(self, event) -> bool:
        if self._dispatching:
            return False
        pending = self.pending
        if pending is None:
            return False
        if (QPointF(event.position()) - pending['point']).manhattanLength() > DRAG_SLOP_PX:
            pending['moved'] = True
        if not pending['started']:
            self._try_start()
        if pending['started']:
            self._forward(QEvent.Type.MouseMove, event, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
            if not self.page.position_overlay._dragging:
                pending['started'] = False
        return True

    def release(self, event) -> bool:
        if self._dispatching:
            return False
        pending, self.pending = self.pending, None
        if pending is None or event.button() != Qt.MouseButton.LeftButton:
            return pending is not None
        if pending['started']:
            self._forward(QEvent.Type.MouseButtonRelease, event, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
        elif pending['moved']:
            QToolTip.showText(event.globalPosition().toPoint(), not_ready_hint(), self.page.video)
        return True

    def claim_double_click(self) -> str:
        """Cue selected by the first click of this double-click, else ''.

        Double-clicking a caption that was not selected opened the AI caption
        workshop before this change; that stays so even though the first click
        now shows the drag box (whose own double-click edits the text)."""
        record, self._selected_by_press = self._selected_by_press, None
        if record is None:
            return ''
        cue_id, at = record
        within = time.monotonic() - at <= QApplication.doubleClickInterval() / 1000.0
        return cue_id if within and cue_id == getattr(self.page, 'selected_cue_id', '') else ''

    # -- helpers -------------------------------------------------------------
    def _pause(self) -> None:
        video = self.page.video
        if getattr(video, 'controller', None) and getattr(video, 'playback_intended', not getattr(video, '_paused', True)):
            video.set_paused(True)
            sync_button = getattr(self.page, '_sync_play_button', None)
            if callable(sync_button):
                sync_button(True)

    def _select(self, cue_id: str, layer: str) -> bool:
        page = self.page
        changed = page.selected_cue_id != cue_id
        page.timeline.set_subtitle_layer(layer)
        if changed:
            page.select_cue(cue_id)
        panel = getattr(page, 'caption_transform_panel', None)
        if panel is not None and panel.language.currentData() not in (layer, 'linked'):
            index = panel.language.findData(layer)
            if index >= 0:
                panel.language.setCurrentIndex(index)
        return changed

    def _try_start(self) -> None:
        pending = self.pending
        overlay = getattr(self.page, 'position_overlay', None)
        if pending is None or pending['started'] or overlay is None or not overlay.isVisible():
            return
        local = QPointF(overlay.mapFrom(self.page.video, pending['point'].toPoint()))
        rect = overlay._subtitle_rect()
        if rect.isEmpty() or not (rect.contains(local) or overlay._handle_at(local.toPoint())):
            return
        self._send(overlay, QMouseEvent(
            QEvent.Type.MouseButtonPress, local, pending['global_point'],
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, pending['modifiers']))
        pending['started'] = bool(overlay._dragging)
        if pending['started']:
            overlay.setFocus(Qt.FocusReason.MouseFocusReason)

    def _forward(self, kind, event, button, buttons) -> None:
        overlay = self.page.position_overlay
        local = QPointF(overlay.mapFrom(self.page.video, QPointF(event.position()).toPoint()))
        self._send(overlay, QMouseEvent(
            kind, local, QPointF(event.globalPosition()), button, buttons, event.modifiers()))

    def _send(self, overlay, event) -> None:
        # Qt propagates an ignored overlay event back to its parent canvas.
        # A stale geometry guard must not forward that event recursively.
        self._dispatching = True
        try:
            QApplication.sendEvent(overlay, event)
        finally:
            self._dispatching = False
