"""Small studio card/editor widgets shared by the AI panel, review flow,
and canvas inline editing."""

from __future__ import annotations

import difflib
import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
)

from ..subtitle_rules.studio_qc import QCCandidate

class AIDesignVariantCard(QFrame):
    """Clickable AI design card: clicking anywhere on the card selects it."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiDesignVariant")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("selected", False)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ReviewCandidateCard(QFrame):
    """Distinct selectable card for a review candidate.

    Shows:
    - Large keyboard number badge
    - Source badges (secondary)
    - Full readable candidate text
    - Click to adopt
    Visual states: hover ring, selected green border.

    2026-10-15: card 1 (the current caption) may carry click-to-fix marks
    (``subtitle_rules.review_suggestions``): a click on a mark changes only
    that part (``suggestion_activated``), right-click or a mark with several
    options asks (``suggestion_menu_requested``); a click elsewhere still
    adopts the whole card.

    2026-10-17: the marks are drawn as ruby (``review_marked_text``): the
    questioned characters stay in the sentence, each alternative is a chip
    above them, and a click on a chip writes that alternative.
    """
    clicked = Signal(int)
    suggestion_activated = Signal(int, int)  # mark index, option index
    suggestion_menu_requested = Signal(int, object)  # mark index, global QPoint

    def __init__(
        self,
        index: int,
        candidate: "QCCandidate",
        is_current: bool = False,
        current_text: str = "",
        parent=None,
        suggestions=(),
        key_text=None,
    ):
        super().__init__(parent)
        self._index = index
        # The page's ``_shortcut_key_text``: the pronoun tip names the current key.
        self._key_text = key_text
        self._candidate = candidate
        self._current_text = current_text
        self._is_current = is_current
        self._selected = bool(is_current)
        self._suggestions = tuple(suggestions or ())
        self._pressed_hit = None
        self._hover_hit = False
        self.setObjectName("reviewCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(86)
        # Ruby chips need a band above each marked line.
        self.setMaximumHeight(168 if self._suggestions else 124)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 9, 10, 9)
        lay.setSpacing(9)

        # Number badge
        num = QLabel(str(index + 1))
        num.setObjectName("reviewCardNum")
        num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        num.setFixedSize(30, 30)
        lay.addWidget(num, 0, Qt.AlignmentFlag.AlignTop)

        # Body
        body = QVBoxLayout()
        # Card 1 with ruby chips keeps within the review row's fixed height.
        body.setSpacing(3 if self._suggestions else 5)

        # Source row (badges)
        src_row = QHBoxLayout()
        src_row.setSpacing(4)
        for src in (candidate.sources or ("?",)):
            label = "当前" if str(src) == "Current" else str(src)
            badge = QLabel(label)
            badge.setObjectName("reviewSourceBadge")
            badge.setProperty("current", label == "当前")
            src_row.addWidget(badge, 0)
        if candidate.context_only:
            context = QLabel("原始段上下文 · 仅供参考")
            context.setObjectName("reviewSourceContext")
            src_row.addWidget(context, 0)
            self.setEnabled(False)
            self.setToolTip("包含未能精确对齐本条的原始段落，请结合原音编辑。")
        src_row.addStretch(1)
        body.addLayout(src_row)

        # Text (readable size, not crushed)
        if self._suggestions:
            from .review_marked_text import ReviewMarkedText
            self.text_label = ReviewMarkedText(self._current_text or candidate.text or "", self._suggestions)
            # The card hit-tests the marks itself (``_hit_at``); the label only paints.
            self.text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.setMouseTracking(True)
        else:
            self.text_label = QLabel(self._markup())
            self.text_label.setTextFormat(Qt.TextFormat.RichText)
            self.text_label.setWordWrap(True)
            self.text_label.setMinimumHeight(34)
            self.text_label.setMaximumHeight(62)
        self.text_label.setObjectName("reviewCandidateText")
        body.addWidget(self.text_label)

        lay.addLayout(body, 1)

        # Click anywhere adopts
        self.set_selected(self._selected)

    @staticmethod
    def _diff_markup(candidate: str, current: str) -> str:
        if not current or candidate == current:
            return html.escape(candidate).replace("\n", "<br>")
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition
        theme = theme_definition(theme_key())
        chunks: list[str] = []
        matcher = difflib.SequenceMatcher(None, current, candidate, autojunk=False)
        for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
            text = html.escape(candidate[j1:j2]).replace("\n", "<br>")
            if tag == "equal":
                chunks.append(text)
            elif text:
                chunks.append(f"<span style='background:{theme.warning_soft}; color:{theme.warning}; border-radius:3px; padding:1px 2px;'>{text}</span>")
        return "".join(chunks)

    def _markup(self) -> str:
        return self._diff_markup(self._candidate.text or "", self._current_text)

    # click-to-fix marks ------------------------------------------------------
    def _hit_at(self, pos):
        """``(mark, option)`` under ``pos`` (card coordinates) or None; option
        is a chip's alternative, ``MORE`` ("+n") or ``BASE`` (the span)."""
        if not self._suggestions:
            return None
        return self.text_label.hit_at(self.text_label.mapFrom(self, pos))

    def _mark_at(self, pos) -> int:
        """Index of the mark under ``pos`` (span or one of its chips), or -1."""
        hit = self._hit_at(pos)
        return hit[0] if hit else -1

    def _mark_tip(self, index: int, option: int | None = None) -> str:
        # ``tr(source, **arguments)`` cannot take a ``source=`` placeholder (it
        # raised TypeError on hover since 2026-10-15), so these two templates
        # are translated first and formatted afterwards.
        from ..i18n import tr, translate
        from .review_marked_text import MORE
        row = self._suggestions[index]
        if row.kind == "pronoun":
            return tr("点一下：{old} → {new}；右键选择 他 / 她 / 它；按 {key} 切换整条的人称",
                      old=row.original, new=row.options[0].text, key=self._flip_key_text())
        chosen = option if option is not None and option >= 0 else None
        options = (row.options[chosen],) if chosen is not None else row.options
        sources = " · ".join(dict.fromkeys(source for item in options for source in item.sources))
        label = tr("词库规范写法") if row.kind == "glossary" else (sources or tr("其他识别结果"))
        if chosen is None and (len(row.options) > 1 or option == MORE):
            return translate("{source}：这里有 {count} 种写法，点一下选择（可撤销）").format(
                source=label, count=len(row.options))
        return translate("{source}：「{old}」→「{new}」，点一下只改这一处（可撤销）").format(
            source=label, old=row.original or "∅", new=options[0].text or "∅")

    def _flip_key_text(self):
        if self._key_text is not None:
            return self._key_text("review_flip_pronoun")
        from ..i18n import tr
        from . import shortcut_registry as keys
        key = keys.key_for("review_flip_pronoun")  # a card on its own reads the store
        return keys.display(key) if key else tr("未绑定")

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._suggestions:
            hit = self._hit_at(event.position().toPoint())
            if hit != self._hover_hit:
                self._hover_hit = hit
                self.text_label.set_hover(hit)
                self.setToolTip(self._mark_tip(*hit) if hit else "")
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._suggestions:
            self._hover_hit = None
            self.text_label.set_hover(None)
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            hit = self._hit_at(event.position().toPoint())
            if hit:
                # A mark acts on release, so a press never also adopts the card.
                self._pressed_hit = hit
                event.accept()
                return
            self.clicked.emit(self._index)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        pressed, self._pressed_hit = self._pressed_hit, None
        if pressed and event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            if self._hit_at(event.position().toPoint()) != pressed:
                return
            from .review_marked_text import MORE
            mark, option = pressed
            row = self._suggestions[mark]
            if option >= 0:
                self.suggestion_activated.emit(mark, option)        # a chip: that alternative
            elif option == MORE or (row.kind != "pronoun" and len(row.options) > 1):
                self.suggestion_menu_requested.emit(mark, event.globalPosition().toPoint())
            else:
                self.suggestion_activated.emit(mark, 0)
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        index = self._mark_at(event.pos())
        if index >= 0:
            self.suggestion_menu_requested.emit(index, event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    def set_selected(self, on: bool):
        self._selected = bool(on)
        self.setProperty("selected", bool(on))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def refresh_theme_palette(self):
        if self._suggestions:
            self.text_label.refresh()
        else:
            self.text_label.setText(self._markup())



from ..diagnostics.input_latency import InputLatencyTextEdit


class _SubtitleEditCardEditor(InputLatencyTextEdit):
    """IME-safe editor hosted in the Qt layout, never over mpv's HWND."""

    commit_requested = Signal(bool)
    cancel_requested = Signal()

    def inputMethodEvent(self, event) -> None:
        self._preediting = bool(event.preeditString())
        super().inputMethodEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (getattr(self, "_preediting", False)
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape)):
            # The platform IME consumes candidate keys first. Never turn a
            # remaining candidate-confirm key into a newline or project edit.
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            self.commit_requested.emit(bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier))
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _CanvasInlineEdit(QPlainTextEdit):
    """Visible Studio canvas editor with explicit IME diagnostics."""

    input_method_received = Signal(str, str, str)
    diagnostic = Signal(str, object)

    def inputMethodEvent(self, event) -> None:
        preedit = str(event.preeditString())
        commit = str(event.commitString())
        super().inputMethodEvent(event)
        self.input_method_received.emit(preedit, commit, self.toPlainText())
