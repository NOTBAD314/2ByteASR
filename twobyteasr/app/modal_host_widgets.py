"""In-window modal host: dims the main window and shows a card inside it
instead of opening a separate native window (model workshop details,
term library, smart glossary).

Split out of ``app/ui.py`` on 2026-10-15; ``ui`` still exports ``ModalHost``.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QWidget

from ..design.main_ui_dialogs import DialogSurface
from .main_ui_helpers import _active_theme_definition, GUI_PROFILE_ENABLED


class _ModalBackdrop(QFrame):
    """Lightweight backdrop whose paint alpha can change without restyling Qt."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._alpha = 0.0
        self.setObjectName("modalBackdrop")
        self.setAutoFillBackground(False)

    @property
    def alpha(self) -> float:
        return self._alpha

    def set_alpha(self, value) -> None:
        alpha = max(0.0, min(1.0, float(value)))
        if abs(alpha - self._alpha) < 0.001:
            return
        self._alpha = alpha
        self.update()

    def paintEvent(self, event):
        if self._alpha <= 0.0:
            return
        color = QColor(_active_theme_definition().app_background)
        color.setAlphaF(self._alpha)
        painter = QPainter(self)
        painter.fillRect(event.rect(), color)


class ModalHost(QFrame):
    """MainWindow-internal overlay for app popups.

    Eliminates new top-level native windows (SpringDialog / QDialog) for:
    Model Picker, Term Library, Technical Info, Edit/Delete Term, Smart Glossary.

    - Backdrop: direct-painted 0.27 alpha, shown and hidden immediately.
    - Dialog card: always 100% opaque, shown at FINAL size immediately.
    - No geometry/resize/scale/minHeight animation on the card.
    - Three close affordances: X (host header), click backdrop outside card, Esc.
    - Content is a plain QWidget placed into the card body.
    - Only Download/Repair truly independent windows stay as separate top-level.
    """

    closed = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("appModalHost")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        # Host must be fully transparent container. Only its backdrop child dims the main UI.
        self.setStyleSheet("QFrame#appModalHost { background: transparent; border: 0; }")
        self.hide()

        self._current_content: QWidget | None = None
        self._retain_current_content = False
        self._on_closed = None
        self._click_ts: float | None = None

        # Full-size host that covers the window content area.
        # We draw nothing ourselves; backdrop + card are children.

        # Direct painting avoids per-frame stylesheet parsing and keeps the large
        # content tree free of QGraphicsOpacityEffect.
        self.backdrop = _ModalBackdrop(self)
        self._backdrop_target_alpha = 0.27

        # One shared opaque surface owns the modal chrome. Keeping Header,
        # Body, and Footer in one primitive prevents transparent edge drift.
        self.surface = DialogSurface(self, close_callback=self._request_close)
        self.card = self.surface
        self.header = self.surface.header
        self.title_label = self.surface.header_title
        self.xbtn = self.surface.close_button
        self.body = self.surface.body
        self.body.setObjectName("modalCardBody")
        self.body_lay = self.surface.body_layout
        self.surface.footer.hide()
        from .window_constraints import EmbeddedCardInteraction
        self._card_interaction = EmbeddedCardInteraction(self.card, self.header)
        from PySide6.QtGui import QShortcut, QKeySequence
        self._escape_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._escape_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._escape_shortcut.activated.connect(self._request_close)

        # Outside click closes.
        self.backdrop.mousePressEvent = lambda event: event.accept()
        self.backdrop.mouseReleaseEvent = self._backdrop_pressed
        self.backdrop.show()
        self.backdrop.lower()

        # Esc on card.
        self.card.installEventFilter(self)
        self.refresh_theme_palette()

    def refresh_theme_palette(self) -> None:
        self.surface.refresh_theme_palette()
        self.backdrop.update()

    def eventFilter(self, obj, ev):
        if obj is self.card and ev.type() == QEvent.Type.KeyPress:
            if ev.key() == Qt.Key.Key_Escape:
                self._request_close()
                return True
        return super().eventFilter(obj, ev)

    def _backdrop_pressed(self, e):
        e.accept()
        if not self.card.geometry().contains(e.position().toPoint()):
            self._request_close()

    def _request_close(self):
        # Record close click time for real desktop "close click → dialog gone" measurement.
        self._close_click_ts = time.perf_counter() if GUI_PROFILE_ENABLED else None
        self.hide_content()
        self.closed.emit()
        if self._on_closed:
            try:
                self._on_closed()
            except Exception:
                pass
            self._on_closed = None

    def show_content(
        self,
        content: QWidget,
        title: str = "",
        size=None,
        min_size=None,
        on_closed=None,
        *,
        retain_content: bool = False,
    ):
        """Show the card and stable backdrop at their final state immediately."""
        from ..design.native_surfaces import cover_native_video
        cover_native_video(self)
        self._click_ts = time.perf_counter() if GUI_PROFILE_ENABLED else None
        self._first_paint = False
        self._first_paint_marked = False

        # Cached picker/technical widgets remain children of the modal body.
        # Reparenting a large styled tree on every open forces a full polish and
        # layout pass even though none of its content changed.
        if self._current_content is not None:
            self.body_lay.removeWidget(self._current_content)
            self._current_content.hide()
            if not self._retain_current_content:
                self._current_content.setParent(None)
        self._current_content = content
        self._retain_current_content = bool(retain_content)
        self._on_closed = on_closed

        self.title_label.setText(title or "")

        # Swap body content
        while self.body_lay.count():
            it = self.body_lay.takeAt(0)
            w = it.widget()
            if w and w is not content:
                w.hide()
                w.setParent(None)
        if content.parentWidget() is not self.body:
            content.setParent(self.body)
        self.body_lay.addWidget(content, 1)
        from ..design.presentation import prepare_controls
        prepare_controls(content)
        content.show()
        content.setMinimumSize(0, 0)
        from PySide6.QtWidgets import QLayout
        self.surface.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)

        # The body belongs to the shared host, not to any hosted page.  Restore
        # it defensively so one page's stale visibility state cannot blank the
        # next dialog shown through this host.
        self.body.show()

        # Explicitly sized production modals do not need an expensive
        # adjustSize()/sizeHint() traversal over every card or benchmark row.
        if size is None:
            content.adjustSize()
            sh = content.sizeHint()
            hinted_w, hinted_h = sh.width(), sh.height()
        else:
            hinted_w = hinted_h = 0
        target_w = max((size and size[0]) or hinted_w or 520, (min_size and min_size[0]) or 420)
        target_h = max((size and size[1]) or hinted_h or 420, (min_size and min_size[1]) or 320)

        parent = self.parentWidget()
        if parent:
            pr = parent.rect()
            cw = min(target_w, max(1, pr.width() - 24))
            ch = min(target_h, max(1, pr.height() - 24))
            cx = (pr.width() - cw) // 2
            cy = max(12, (pr.height() - ch) // 2)
            self.card.setGeometry(cx, cy, cw, ch)
            self.setGeometry(pr)
        else:
            self.card.setGeometry(60, 60, target_w, target_h)
            self.setGeometry(self.card.geometry())

        # Card is already at its final geometry and remains fully opaque.
        self.show()
        self.raise_()
        self.card.show()
        self.card.raise_()

        # Real-desktop verification showed a short fade coalescing into 2-4
        # large paint steps under production content. Use the final alpha at
        # once; stable response is preferable to a segmented fade.
        self.backdrop.setGeometry(self.rect())
        self.backdrop.set_alpha(self._backdrop_target_alpha)
        self.backdrop.show()
        self.backdrop.raise_()
        self.card.raise_()
        self.raise_()

        # Record real desktop timing: click → backdrop visible
        try:
            if self._click_ts is not None:
                dt_bd = (time.perf_counter() - self._click_ts) * 1000
                print(f"[perf] backdrop visible ~{int(dt_bd)}ms title={title!r}")
        except Exception:
            pass

        # Critical stacking
        def _force_stack():
            try:
                self.raise_()
            except Exception:
                pass
            try:
                self.backdrop.raise_()
            except Exception:
                pass
            try:
                self.card.raise_()
            except Exception:
                pass
        QTimer.singleShot(0, _force_stack)

        # Schedule the first paint without forcing a nested event loop.
        self.card.update()

    def paintEvent(self, event):
        # Mark first paint relative to the click timestamp captured in show_content.
        try:
            if not getattr(self, "_first_paint_marked", False) and self._click_ts is not None:
                dt = (time.perf_counter() - self._click_ts) * 1000
                title = getattr(self, "title_label", None)
                t = title.text() if title else ""
                print(f"[perf] modal paintEvent first-frame ~{int(dt)}ms title={t!r}")
                self._first_paint_marked = True
        except Exception:
            pass
        super().paintEvent(event)

    def hide_content(self):
        # Card, content, and backdrop disappear together. No large-area effect
        # or coalesced alpha animation is kept alive after the close action.
        _now = time.perf_counter() if GUI_PROFILE_ENABLED else 0.0
        dirty_rect = self.geometry()
        try:
            self.card.hide()
        except Exception:
            pass
        if self._current_content is not None:
            try:
                self.body_lay.removeWidget(self._current_content)
                self._current_content.hide()
                if not self._retain_current_content:
                    self._current_content.setParent(None)
            except Exception:
                pass
            self._current_content = None
        if GUI_PROFILE_ENABLED:
            try:
                base = getattr(self, "_close_click_ts", None) or getattr(self, "_click_ts", None)
                if base is not None:
                    dt = (_now - base) * 1000
                    src = "close_click" if getattr(self, "_close_click_ts", None) else "open_click_fallback"
                    print(f"[perf] close (dialog gone) ~{int(dt)}ms src={src}")
            except Exception:
                pass
        self.backdrop.set_alpha(0.0)
        self.backdrop.hide()
        self.hide()
        parent = self.parentWidget()
        if parent is not None:
            # Embedded D3D video surfaces do not always invalidate the Qt
            # backing store after an in-window modal disappears. Force the
            # vacated card/backdrop area to repaint so no stale dialog pixels
            # remain over the Studio preview.
            parent.update(dirty_rect)
            parent.repaint(dirty_rect)
        self._retain_current_content = False
        self._close_click_ts = None

    def resize_to_parent(self):
        parent = self.parentWidget()
        if not parent:
            return
        self.setGeometry(parent.rect())
        if self.card.isVisible():
            cr = self.card.geometry()
            pr = parent.rect()
            width = min(cr.width(), max(1, pr.width()-24))
            height = min(cr.height(), max(1, pr.height()-24))
            cx = max(12, (pr.width() - width) // 2)
            cy = max(12, (pr.height() - height) // 2)
            self.card.setGeometry(cx, cy, width, height)
        if self.backdrop.isVisible():
            self.backdrop.setGeometry(self.rect())
