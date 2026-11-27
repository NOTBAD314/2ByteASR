# SPDX-License-Identifier: GPL-3.0-only
"""Parts of the 「匹配文稿」 wizard (2026-11-12, design C; 2026-11-25 reference
correction & inline glossary capture).

Step badges (todo / current / done), the line between them, the drop zone,
the 2-way mode switcher (``整稿替换`` | ``参考纠错``), the script editor with
selection-to-term capture, and the flat inline glossary capture strip. Colours
come from the active theme at paint/refresh time.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from ..design.typography import UI_FONT_STACK, weighted_font
from ..design.ui_theme import blend_hex
from ..i18n import tr


def _theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


def _px(value: float) -> int:
    from .ui_zoom import px
    return px(value)


def resolve_glossary_options(
    legacy: Any,
    preferred_ids: Sequence[str] = (),
) -> tuple[list[tuple[str, str]], str]:
    """Return ``([(id, display_name), ...], default_id)`` from ``legacy``."""
    if legacy is None or not hasattr(legacy, 'glossary_catalog'):
        return [], ''
    try:
        catalog = list(legacy.glossary_catalog() or ())
    except Exception:
        return [], ''
    options: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in catalog:
        if not isinstance(row, dict):
            continue
        lib_id = str(row.get('id') or '').strip()
        name = str(row.get('name') or lib_id).strip()
        if lib_id and lib_id not in seen:
            seen.add(lib_id)
            options.append((lib_id, name))
    if not options:
        return [], ''
    id_set = {lib_id for lib_id, _ in options}
    resolve = getattr(legacy, 'resolve_glossary_identity', None)
    for pref in preferred_ids or ():
        raw = str(pref or '').strip()
        if not raw:
            continue
        resolved = str(resolve(raw) or raw).strip() if callable(resolve) else raw
        if resolved in id_set:
            return options, resolved
    return options, options[0][0]


class StepBadge(QWidget):
    """A numbered circle; ``current`` wears a soft ring, ``done`` a check mark."""

    def __init__(self, number: int, parent=None):
        super().__init__(parent)
        self.number = number
        self.state = 'todo'
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_state(self, state: str):
        if state != self.state:
            self.state = state
            self.update()

    def sizeHint(self):
        return QSize(_px(36), _px(36))

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        t = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = _px(26)
        circle = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        painter.setPen(Qt.PenStyle.NoPen)
        if self.state == 'current':
            painter.setBrush(QColor(t.accent_soft))
            painter.drawEllipse(circle.adjusted(-_px(5), -_px(5), _px(5), _px(5)))
            fill, ink = t.accent, t.text_on_accent
        elif self.state == 'done':
            fill, ink = t.success, '#ffffff'
        else:
            fill, ink = t.border, t.text_muted
        painter.setBrush(QColor(fill))
        painter.drawEllipse(circle)
        if self.state == 'done':
            pen = QPen(QColor(ink), max(2.0, _px(2.6)))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            c = circle.center()
            u = side / 26
            path = QPainterPath(QPointF(c.x() - 5.5 * u, c.y() + 0.5 * u))
            path.lineTo(QPointF(c.x() - 1.5 * u, c.y() + 4.5 * u))
            path.lineTo(QPointF(c.x() + 6 * u, c.y() - 4 * u))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        else:
            font = self.font()
            font.setPixelSize(_px(13))
            weighted_font(font, 700)
            painter.setFont(font)
            painter.setPen(QColor(ink))
            painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, str(self.number))
        painter.end()


class StepLine(QWidget):
    """The rounded bar between two steps; green once the step before is done."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.done = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(_px(24))

    def set_done(self, done: bool):
        if bool(done) != self.done:
            self.done = bool(done)
            self.update()

    def sizeHint(self):
        return QSize(_px(60), _px(36))

    def paintEvent(self, event):
        t = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t.success if self.done else t.border))
        h = max(2, _px(3))
        painter.drawRoundedRect(QRectF(0, (self.height() - h) / 2, self.width(), h), h / 2, h / 2)
        painter.end()


class ModeSegmentBar(QWidget):
    """Compact 2-way segmented toggle: ``整稿替换`` | ``参考纠错``."""

    mode_changed = Signal(str)

    def __init__(self, parent=None, *, default_mode: str = 'replace'):
        super().__init__(parent)
        self.setObjectName('scriptModeBar')
        self._mode = 'reference' if default_mode == 'reference' else 'replace'

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.track = QFrame(self)
        self.track.setObjectName('scriptModeTrack')
        row = QHBoxLayout(self.track)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)

        self.replace_btn = QPushButton(tr('整稿替换'), self.track)
        self.replace_btn.setObjectName('scriptModeOption')
        self.replace_btn.setCheckable(True)
        self.replace_btn.setAutoDefault(False)
        self.replace_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.replace_btn.setToolTip(tr('已有按句分好的逐字稿，按字级时间直接对齐覆盖字幕'))

        self.reference_btn = QPushButton(tr('参考纠错'), self.track)
        self.reference_btn.setObjectName('scriptModeOption')
        self.reference_btn.setCheckable(True)
        self.reference_btn.setAutoDefault(False)
        self.reference_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reference_btn.setToolTip(tr('贴大纲、设定或参考稿，只挑出同音错字与专名，不删改即兴口播'))

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.addButton(self.replace_btn)
        self._group.addButton(self.reference_btn)

        row.addWidget(self.replace_btn)
        row.addWidget(self.reference_btn)
        outer.addWidget(self.track, 0, Qt.AlignmentFlag.AlignLeft)

        self.replace_btn.clicked.connect(lambda _=False: self.set_mode('replace'))
        self.reference_btn.clicked.connect(lambda _=False: self.set_mode('reference'))

        self.replace_btn.setChecked(self._mode == 'replace')
        self.reference_btn.setChecked(self._mode == 'reference')
        self.refresh_theme()

    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        normalized = 'reference' if str(mode) == 'reference' else 'replace'
        self.replace_btn.setChecked(normalized == 'replace')
        self.reference_btn.setChecked(normalized == 'reference')
        if normalized != self._mode:
            self._mode = normalized
            self.mode_changed.emit(normalized)

    def refresh_theme(self) -> None:
        t = _theme()
        hover = blend_hex(t.input_surface, t.text, 0.08 if t.is_light else 0.12)
        self.setStyleSheet(f"""
            QWidget#scriptModeBar {{
                background: transparent;
                border: 0;
            }}
            QFrame#scriptModeTrack {{
                background: {t.input_surface};
                border: 1px solid {t.border};
                border-radius: 17px;
            }}
            QPushButton#scriptModeOption {{
                background: transparent;
                color: {t.text_secondary};
                border: 0;
                border-radius: 14px;
                min-height: 28px;
                max-height: 28px;
                padding: 0 16px;
                font-family: {UI_FONT_STACK};
                font-size: 13px;
                font-weight: 500;
            }}
            QPushButton#scriptModeOption:hover {{
                background: {hover};
                color: {t.text};
            }}
            QPushButton#scriptModeOption:checked {{
                background: {t.text};
                color: {t.surface};
                font-weight: 700;
            }}
            QPushButton#scriptModeOption:disabled {{
                color: {t.disabled};
            }}
        """)


class DropZone(QFrame):
    """Accepts one dropped audio or video file and hands its path to ``on_media``."""

    def __init__(self, on_media, parent=None):
        super().__init__(parent)
        self.on_media = on_media
        self.setObjectName('scriptDropZone')
        self.setAcceptDrops(True)

    @staticmethod
    def _media_path(event):
        from .main_ui_helpers import SUPPORTED_MEDIA_SUFFIXES
        mime = event.mimeData()
        if not mime.hasUrls():
            return ''
        for url in mime.urls():
            path = Path(url.toLocalFile())
            if url.isLocalFile() and path.suffix.lower() in SUPPORTED_MEDIA_SUFFIXES:
                return str(path)
        return ''

    def _mark(self, dragging: bool):
        self.setProperty('dragging', 'true' if dragging else 'false')
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event):
        if self.isEnabled() and self._media_path(event):
            self._mark(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._mark(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._mark(False)
        path = self._media_path(event)
        if path:
            event.acceptProposedAction()
            self.on_media(path)


def repolish(widget, name: str, value) -> None:
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class WizardDialog(QDialog):
    """The rounded wizard window (no Windows title bar): a title, × and ``body``.

    ×, Esc and 取消 wait while ``busy()`` is true. Call ``finish()`` once the
    content is built: it themes the controls and makes the window rounded.
    """

    def __init__(self, parent, *, object_name: str, title: str, busy=None,
                 minimum=(560, 520), size=(700, 640)):
        super().__init__(parent)
        from .rounded_window import SHADOW
        self.busy = busy or (lambda: False)
        self.setObjectName(object_name)
        self.setWindowTitle(title)
        self.setMinimumSize(minimum[0] + 2 * SHADOW, minimum[1] + 2 * SHADOW)
        self.resize(size[0] + 2 * SHADOW, size[1] + 2 * SHADOW)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.root = QWidget()
        self.root.setObjectName('scriptWizardRoot')
        self.root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer.addWidget(self.root)
        self.body = QVBoxLayout(self.root)
        self.body.setContentsMargins(26, 16, 22, 20)
        self.body.setSpacing(10)
        self.header = QFrame()
        self.header.setObjectName('scriptWizardHeader')
        top = QHBoxLayout(self.header)
        top.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(title)
        self.title_label.setObjectName('scriptWizardTitle')
        self.close_button = QPushButton('×')
        self.close_button.setObjectName('scriptWizardClose')
        self.close_button.setToolTip(tr('关闭'))
        self.close_button.setAccessibleName(tr('关闭'))
        self.close_button.setAutoDefault(False)
        self.close_button.clicked.connect(self.reject)
        top.addWidget(self.title_label)
        top.addStretch(1)
        top.addWidget(self.close_button)
        self.body.addWidget(self.header)

    SURFACE_MOTION = True

    def done(self, result):
        from ..design.transitions import animate_done
        if not animate_done(self, result):
            super().done(result)

    def reject(self):
        if not self.busy():
            super().reject()

    def finish(self):
        from ..design.studio_theme import apply_secondary_surface_theme
        from .rounded_window import RoundedWindow
        apply_secondary_surface_theme(self)
        for child in self.findChildren(QWidget):
            if hasattr(child, 'refresh_theme') and callable(child.refresh_theme):
                child.refresh_theme()
        self.chrome = RoundedWindow(self, self.root, title_areas=[self.header], radius=26, maximizable=False)
        for grip in self.findChildren(QSizeGrip):
            grip.setMaximumSize(0, 0)


def build_stepper(names, details=None):
    """①──②──③: the row layout, its badges, captions and lines.
    ``details`` maps a step number to a small widget under its caption."""
    details = details or {}
    stepper = QHBoxLayout()
    stepper.setSpacing(8)
    badges, captions, lines = [], [], []
    for number, name in enumerate(names, 1):
        badge = StepBadge(number)
        caption = QLabel(tr(name))
        caption.setObjectName('scriptStepName')
        words = QVBoxLayout()
        words.setSpacing(0)
        words.addStretch(1)
        words.addWidget(caption)
        if number in details:
            words.addWidget(details[number])
        words.addStretch(1)
        stepper.addWidget(badge)
        stepper.addLayout(words)
        badges.append(badge)
        captions.append(caption)
        if number < len(names):
            line = StepLine()
            lines.append(line)
            stepper.addWidget(line, 1)
    return stepper, badges, captions, lines


def show_step_states(badges, captions, lines, states) -> None:
    for badge, caption, value in zip(badges, captions, states):
        badge.set_state(value)
        repolish(caption, 'stepState', value)
    for line, value in zip(lines, states):
        line.set_done(value == 'done')


def bunny_tip(text: str):
    """The bunny with a speech bubble (rich text); returns (row layout, bubble)."""
    from .settings_widgets import Bunny
    row = QHBoxLayout()
    row.setSpacing(6)
    row.addWidget(Bunny(54), 0, Qt.AlignmentFlag.AlignBottom)
    bubble = QLabel(text)
    bubble.setObjectName('scriptWizardTip')
    bubble.setWordWrap(True)
    bubble.setTextFormat(Qt.TextFormat.RichText)
    row.addWidget(bubble, 1, Qt.AlignmentFlag.AlignBottom)
    return row, bubble


class ScriptEditor(QFrame):
    """The rounded script box: the text, its line count, 指定词条, 从文件读取… and 粘贴.

    Selecting text in ``input`` and clicking ``指定词条`` (or choosing ``指定词条``
    from the right-click menu) emits ``term_picked(selected_text)``.
    """

    term_picked = Signal(str)

    def __init__(self, input_name: str, parent=None):
        super().__init__(parent)
        self._mode = 'replace'
        self.setObjectName('scriptEditorFrame')
        lines = QVBoxLayout(self)
        lines.setContentsMargins(8, 6, 10, 10)
        lines.setSpacing(4)
        self.input = QPlainTextEdit()
        self.input.setObjectName(input_name)
        self.input.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.input.customContextMenuRequested.connect(self._show_context_menu)
        self.input.setPlaceholderText(tr('每行一条字幕，例如：\n大家好，欢迎回来\n今天我们继续打洛克王国'))
        lines.addWidget(self.input, 1)
        self.tools = QHBoxLayout()
        self.tools.setSpacing(8)
        self.line_count = QLabel()
        self.line_count.setObjectName('scriptLineCount')
        self.pick_term = QPushButton(tr('指定词条'))
        self.pick_term.setObjectName('scriptEditorTool')
        self.pick_term.setToolTip(tr('把框里划选的词加入下方待入库清单'))
        self.load = QPushButton(tr('从文件读取…'))
        self.load.setObjectName('scriptEditorTool')
        self.paste = QPushButton(tr('粘贴'))
        self.paste.setObjectName('scriptEditorTool')
        for button in (self.pick_term, self.load, self.paste):
            button.setAutoDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tools.addSpacing(6)
        self.tools.addWidget(self.line_count)
        self.tools.addStretch(1)
        self.tools.addWidget(self.pick_term)
        self.tools.addWidget(self.load)
        self.tools.addWidget(self.paste)
        lines.addLayout(self.tools)
        self.pick_term.clicked.connect(self._emit_selected_term)
        self.paste.clicked.connect(self.input.paste)
        self.input.textChanged.connect(self.count_lines)
        self.input.installEventFilter(self)
        self.count_lines()

    def set_mode(self, mode: str) -> None:
        self._mode = 'reference' if str(mode) == 'reference' else 'replace'
        if self._mode == 'reference':
            self.input.setPlaceholderText(
                tr('贴参考稿、提纲、角色设定或资料，不必逐句对齐；\n'
                   '划选任意专名后点「指定词条」可直接收进词库。')
            )
        else:
            self.input.setPlaceholderText(
                tr('每行一条字幕，例如：\n大家好，欢迎回来\n今天我们继续打洛克王国')
            )
        self.count_lines()

    def selected_word(self) -> str:
        return str(self.input.textCursor().selectedText() or '').replace('\u2029', ' ').strip()

    def _emit_selected_term(self) -> None:
        word = self.selected_word()
        if word:
            self.term_picked.emit(word)
        else:
            self.input.setFocus()

    def _show_context_menu(self, pos) -> None:
        menu = self.input.createStandardContextMenu()
        word = self.selected_word()
        if word:
            first_action = menu.actions()[0] if menu.actions() else None
            pick_action = menu.addAction(tr('指定词条'))
            pick_action.triggered.connect(lambda _=False, w=word: self.term_picked.emit(w))
            if first_action is not None:
                menu.insertAction(first_action, pick_action)
                menu.insertSeparator(first_action)
        menu.exec(self.input.mapToGlobal(pos))

    def count_lines(self) -> int:
        from ..recognition.script_match import parse_script
        raw = self.input.toPlainText()
        count = len(parse_script(raw))
        if self._mode == 'reference':
            chars = len(''.join(raw.split()))
            self.line_count.setText(
                tr('{lines} 段 · {chars} 字', lines=count, chars=chars) if count else tr('还没有参考稿')
            )
        else:
            self.line_count.setText(
                tr('{count} 行 → {count} 条字幕', count=count) if count else tr('还没有文稿')
            )
        return count

    def eventFilter(self, watched, event):
        if watched is self.input and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            repolish(self, 'focused', 'true' if event.type() == QEvent.Type.FocusIn else 'false')
        return False


class TermCapturePanel(QWidget):
    """Flat, borderless-grouped inline glossary capture strip (no box-in-box).

    Separated from content above by a single 1px hairline divider. Supports:
      - Selected words picked from ``ScriptEditor``
      - Manual ``错词 -> 正词`` or canonical-word entry
      - Auto-populated homophone correction pairs from reference/replace runs
      - Dangerous single-char aliases unchecked by default with ``单字慎用`` tag
      - One-click atomic write via ``quick_term_capture.commit_candidates``
    """

    committed = Signal(dict)

    def __init__(
        self,
        *,
        legacy: Any = None,
        preferred_ids: Sequence[str] = (),
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName('scriptTermCapture')
        self.legacy = legacy
        self._candidates: list[Any] = []
        self._row_checks: list[tuple[QCheckBox, Any]] = []
        self._feedback_text = ''
        self._feedback_kind = 'muted'

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 0)
        root.setSpacing(6)

        self.divider = QFrame(self)
        self.divider.setObjectName('scriptTermDivider')
        self.divider.setFixedHeight(1)
        root.addWidget(self.divider)

        header = QHBoxLayout()
        header.setContentsMargins(0, 2, 0, 0)
        header.setSpacing(8)

        self.title_label = QLabel(tr('收进词库'), self)
        self.title_label.setObjectName('scriptTermTitle')
        header.addWidget(self.title_label)

        self.count_label = QLabel('', self)
        self.count_label.setObjectName('scriptTermMeta')
        self.count_label.hide()
        header.addWidget(self.count_label)

        header.addStretch(1)

        self.manual_input = QLineEdit(self)
        self.manual_input.setObjectName('scriptTermInput')
        self.manual_input.setPlaceholderText(tr('错词 -> 正词 或 规范词'))
        self.manual_input.setMinimumWidth(155)
        self.manual_input.setMaximumWidth(210)
        self.manual_input.returnPressed.connect(self._add_manual)
        header.addWidget(self.manual_input)

        self.add_btn = QPushButton(tr('添加'), self)
        self.add_btn.setObjectName('scriptTermAdd')
        self.add_btn.setAutoDefault(False)
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setToolTip(tr('解析输入的词条并加入待入库清单'))
        self.add_btn.clicked.connect(self._add_manual)
        header.addWidget(self.add_btn)

        self.library_combo = QComboBox(self)
        self.library_combo.setObjectName('scriptTermCombo')
        self.library_combo.setMinimumWidth(110)
        self.library_combo.setMaximumWidth(155)
        self.library_combo.setToolTip(tr('选择目标词库'))
        header.addWidget(self.library_combo)

        self.commit_btn = QPushButton(tr('加入词库'), self)
        self.commit_btn.setObjectName('scriptTermCommit')
        self.commit_btn.setAutoDefault(False)
        self.commit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.commit_btn.setToolTip(tr('把勾选词条原子写入所选词库，自动跳过重复项'))
        self.commit_btn.clicked.connect(self.commit)
        header.addWidget(self.commit_btn)

        root.addLayout(header)

        self.scroll = QScrollArea(self)
        self.scroll.setObjectName('scriptTermScroll')
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setObjectName('scriptTermViewport')
        self.list_host = QWidget(self.scroll)
        self.list_host.setObjectName('scriptTermListHost')
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 2, 0)
        self.list_layout.setSpacing(2)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list_host)
        self.scroll.hide()
        root.addWidget(self.scroll)

        options, default_id = resolve_glossary_options(legacy, preferred_ids)
        self.set_libraries(options, default_id)
        self._refresh_header_state()
        self.refresh_theme()

    def set_libraries(self, libraries: Sequence[tuple[str, str]], default_id: str = '') -> None:
        self.library_combo.clear()
        for lib_id, name in libraries:
            self.library_combo.addItem(str(name), str(lib_id))
        if default_id:
            idx = self.library_combo.findData(str(default_id))
            if idx >= 0:
                self.library_combo.setCurrentIndex(idx)
        has_libs = self.library_combo.count() > 0
        self.library_combo.setVisible(has_libs)
        self._refresh_header_state()

    def selected_library_id(self) -> str:
        return str(self.library_combo.currentData() or self.library_combo.currentText() or '').strip()

    def candidates(self) -> list[Any]:
        return list(self._candidates)

    def _add_manual(self) -> None:
        raw = self.manual_input.text().strip()
        if not raw:
            return
        self.add_specified_text(raw)
        self.manual_input.clear()

    def add_specified_text(self, text: str) -> int:
        from ..recognition.script_reference import extract_specified_terms
        rows = extract_specified_terms(text)
        return self.merge_term_candidates(rows)

    def add_selected_word(self, word: str) -> int:
        from ..recognition.script_reference import extract_specified_terms
        rows = extract_specified_terms('', selected_words=[word])
        return self.merge_term_candidates(rows)

    def merge_term_candidates(self, items: Sequence[Any]) -> int:
        from ..glossary.quick_term_capture import QuickTermCandidate
        from ..recognition.script_reference import extract_specified_terms

        incoming: list[QuickTermCandidate] = []
        dict_items: list[Any] = []
        for item in items or ():
            if isinstance(item, QuickTermCandidate):
                incoming.append(item)
            else:
                dict_items.append(item)
        if dict_items:
            incoming.extend(extract_specified_terms('', pairs=dict_items))

        existing_keys = {(c.source.casefold(), c.target.casefold()) for c in self._candidates}
        added = 0
        for cand in incoming:
            key = (cand.source.casefold(), cand.target.casefold())
            if key in existing_keys:
                continue
            existing_keys.add(key)
            self._candidates.append(cand)
            added += 1
        if added:
            self._feedback_text = ''
            self._rebuild_rows()
        return added

    def clear_candidates(self) -> None:
        self._candidates.clear()
        self._feedback_text = ''
        self._rebuild_rows()

    def _remove_candidate(self, target_cand: Any) -> None:
        self._candidates = [c for c in self._candidates if c is not target_cand]
        self._rebuild_rows()

    def _toggle_candidate(self, cand: Any, checked: bool) -> None:
        cand.checked = bool(checked)
        self._refresh_header_state()

    def _clear_row_widgets(self) -> None:
        self._row_checks.clear()
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _rebuild_rows(self) -> None:
        self._clear_row_widgets()
        for cand in self._candidates:
            row = QWidget(self.list_host)
            row.setObjectName('scriptTermRow')
            row.setFixedHeight(32)
            row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            lay = QHBoxLayout(row)
            lay.setContentsMargins(2, 0, 2, 0)
            lay.setSpacing(8)

            label = f'{cand.source} → {cand.target}' if cand.is_alias else cand.target
            cb = QCheckBox(label, row)
            cb.setObjectName('scriptTermCheck')
            cb.setChecked(bool(cand.checked))
            cb.toggled.connect(lambda checked, c=cand: self._toggle_candidate(c, checked))
            lay.addWidget(cb)
            self._row_checks.append((cb, cand))

            meta_text = cand.note or (tr('规范词') if not cand.is_alias else '')
            if meta_text:
                meta = QLabel(meta_text, row)
                meta.setObjectName('scriptTermRowMeta')
                lay.addWidget(meta)

            if cand.dangerous or cand.warnings:
                warn = QLabel(tr('单字慎用'), row)
                warn.setObjectName('scriptTermWarnTag')
                warn.setToolTip('；'.join(cand.warnings) if cand.warnings else tr('单字别名易误伤正常句子，默认不勾'))
                lay.addWidget(warn)

            lay.addStretch(1)

            rm = QPushButton('×', row)
            rm.setObjectName('scriptTermRowRemove')
            rm.setAutoDefault(False)
            rm.setCursor(Qt.CursorShape.PointingHandCursor)
            rm.setToolTip(tr('移除此项'))
            rm.clicked.connect(lambda _=False, c=cand: self._remove_candidate(c))
            lay.addWidget(rm)

            self.list_layout.insertWidget(self.list_layout.count() - 1, row)

        count = len(self._candidates)
        if count > 0:
            visible_rows = min(4, count)
            self.scroll.setFixedHeight(visible_rows * 34 + 4)
            self.list_host.adjustSize()
            self.scroll.show()
        else:
            self.scroll.hide()
        self._refresh_header_state()
        self.scroll.updateGeometry()
        self.updateGeometry()
        if self.layout() is not None:
            self.layout().activate()
        parent = self.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().activate()

    def _refresh_header_state(self) -> None:
        checked_count = sum(1 for c in self._candidates if c.checked)
        has_target = self.legacy is None or bool(self.selected_library_id())
        self.commit_btn.setEnabled(checked_count > 0 and has_target)
        if self._feedback_text:
            self.count_label.setText(self._feedback_text)
            repolish(self.count_label, 'tone', self._feedback_kind)
            self.count_label.show()
        elif self._candidates:
            self.count_label.setText(tr('{checked}/{total} 项', checked=checked_count, total=len(self._candidates)))
            repolish(self.count_label, 'tone', 'muted')
            self.count_label.show()
        else:
            self.count_label.hide()

    def commit(self) -> dict[str, Any]:
        from ..glossary.quick_term_capture import commit_candidates

        selected = [c for c in self._candidates if c.checked]
        if not selected:
            return {'added': 0, 'skipped': 0, 'library': self.selected_library_id(), 'warnings': []}
        lib_id = self.selected_library_id()
        if self.legacy is None:
            result = {'added': len(selected), 'skipped': 0, 'library': lib_id or '通用词库',
                      'library_id': lib_id, 'warnings': []}
            self._feedback_text = tr('已准备 {n} 条', n=len(selected))
            self._feedback_kind = 'ok'
            self._refresh_header_state()
            self.committed.emit(result)
            return result
        if not lib_id:
            self._feedback_text = tr('请先选词库')
            self._feedback_kind = 'warn'
            self._refresh_header_state()
            return {'added': 0, 'skipped': 0, 'library': '', 'warnings': ['未选择目标词库']}
        try:
            result = commit_candidates(self.legacy, lib_id, selected, origin='参考文稿')
        except Exception as exc:
            self._feedback_text = tr('写入失败')
            self._feedback_kind = 'warn'
            self.count_label.setToolTip(str(exc))
            self._refresh_header_state()
            return {'added': 0, 'skipped': 0, 'library': lib_id, 'warnings': [str(exc)]}

        added = int(result.get('added') or 0)
        skipped = int(result.get('skipped') or 0)
        if added and skipped:
            self._feedback_text = tr('已加 {a} · 跳过 {s}', a=added, s=skipped)
        elif added:
            self._feedback_text = tr('已加入 {a} 条', a=added)
        else:
            self._feedback_text = tr('均已存在')
        self._feedback_kind = 'ok'
        self.count_label.setToolTip(
            '；'.join(result.get('warnings') or ())
            or tr('已写入《{name}》', name=result.get('library') or lib_id)
        )
        self._refresh_header_state()
        self.committed.emit(result)
        return result

    def refresh_theme(self) -> None:
        t = _theme()
        hover = blend_hex(t.surface, t.text, 0.07 if t.is_light else 0.12)
        warn_bg = t.warning_soft
        warn_fg = t.warning
        self.setStyleSheet(f"""
            QWidget#scriptTermCapture {{
                background: transparent;
                border: 0;
            }}
            QFrame#scriptTermDivider {{
                background: {t.border};
                border: 0;
            }}
            QLabel#scriptTermTitle {{
                background: transparent;
                color: {t.text};
                font-family: {UI_FONT_STACK};
                font-size: 13px;
                font-weight: 700;
            }}
            QLabel#scriptTermMeta {{
                background: transparent;
                color: {t.text_muted};
                font-family: {UI_FONT_STACK};
                font-size: 12px;
            }}
            QLabel#scriptTermMeta[tone="ok"] {{
                color: {t.success};
                font-weight: 600;
            }}
            QLabel#scriptTermMeta[tone="warn"] {{
                color: {t.warning};
                font-weight: 600;
            }}
            QLineEdit#scriptTermInput {{
                background: {t.input_surface};
                color: {t.text};
                border: 1px solid {t.border};
                border-radius: 14px;
                min-height: 28px;
                max-height: 28px;
                padding: 0 10px;
                font-family: {UI_FONT_STACK};
                font-size: 12px;
            }}
            QLineEdit#scriptTermInput:focus {{
                border-color: {t.accent};
            }}
            QPushButton#scriptTermAdd {{
                background: {t.input_surface};
                color: {t.text};
                border: 1px solid {t.border};
                border-radius: 14px;
                min-height: 28px;
                max-height: 28px;
                padding: 0 11px;
                font-family: {UI_FONT_STACK};
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton#scriptTermAdd:hover {{
                background: {hover};
            }}
            QComboBox#scriptTermCombo {{
                background: {t.input_surface};
                color: {t.text};
                border: 1px solid {t.border};
                border-radius: 14px;
                min-height: 28px;
                max-height: 28px;
                padding: 0 10px;
                font-family: {UI_FONT_STACK};
                font-size: 12px;
            }}
            QComboBox#scriptTermCombo:hover {{
                border-color: {t.border_strong};
            }}
            QComboBox#scriptTermCombo::drop-down {{
                border: 0;
                width: 20px;
            }}
            QComboBox#scriptTermCombo QAbstractItemView {{
                background: {t.surface_elevated};
                color: {t.text};
                border: 1px solid {t.border};
                selection-background-color: {t.accent_soft};
                selection-color: {t.text};
                outline: 0;
            }}
            QPushButton#scriptTermCommit {{
                background: {t.accent};
                color: {t.text_on_accent};
                border: 0;
                border-radius: 14px;
                min-height: 28px;
                max-height: 28px;
                padding: 0 13px;
                font-family: {UI_FONT_STACK};
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton#scriptTermCommit:hover {{
                background: {t.accent_hover};
            }}
            QPushButton#scriptTermCommit:disabled {{
                background: {t.border};
                color: {t.text_muted};
            }}
            QScrollArea#scriptTermScroll,
            QWidget#scriptTermViewport,
            QWidget#scriptTermListHost {{
                background: transparent;
                border: 0;
            }}
            QWidget#scriptTermRow {{
                background: transparent;
                border: 0;
                border-bottom: 1px solid {t.border};
            }}
            QCheckBox#scriptTermCheck {{
                background: transparent;
                color: {t.text};
                font-family: {UI_FONT_STACK};
                font-size: 12.5px;
                spacing: 6px;
            }}
            QLabel#scriptTermRowMeta {{
                background: transparent;
                color: {t.text_muted};
                font-family: {UI_FONT_STACK};
                font-size: 11.5px;
            }}
            QLabel#scriptTermWarnTag {{
                background: {warn_bg};
                color: {warn_fg};
                border-radius: 8px;
                padding: 1px 7px;
                font-family: {UI_FONT_STACK};
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton#scriptTermRowRemove {{
                background: transparent;
                color: {t.text_muted};
                border: 0;
                border-radius: 10px;
                min-width: 20px;
                max-width: 20px;
                min-height: 20px;
                max-height: 20px;
                padding: 0;
                font-size: 13px;
            }}
            QPushButton#scriptTermRowRemove:hover {{
                background: {hover};
                color: {t.text};
            }}
        """)


__all__ = [
    'DropZone',
    'ModeSegmentBar',
    'ScriptEditor',
    'StepBadge',
    'StepLine',
    'TermCapturePanel',
    'WizardDialog',
    'build_stepper',
    'bunny_tip',
    'repolish',
    'resolve_glossary_options',
    'show_step_states',
]
