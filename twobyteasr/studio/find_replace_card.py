"""Parts of the 批量替换 window, draft B 「软糖卡片」 (2026-11-02, user's pick).

The window has no Windows title bar: a rounded frame (``app/rounded_window``)
with its own title bar (the app's face, 批量替换, what will be searched and a
round close button). The match count sits at the end of the find field; the
options are capsules of one height; with nothing to list, the result card is
one line and the window is short. ``find_replace_qss`` styles everything in
the window from the active theme, so every theme gets the same shapes.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QWidget

from ..i18n import bind_text

RADIUS = 20


def _tokens(t) -> dict[str, str]:
    from ..design.ui_theme import blend_hex
    light = t.is_light
    win = t.surface
    return dict(
        win=win,
        well=blend_hex(win, t.text, 0.055 if light else 0.075),
        well_hover=blend_hex(win, t.text, 0.09 if light else 0.12),
        card=blend_hex(win, t.text, 0.03 if light else 0.045),
        row=t.surface_elevated if light else blend_hex(win, t.text, 0.085),
        on=blend_hex(win, t.accent, 0.15 if light else 0.26),
        on_hover=blend_hex(win, t.accent, 0.22 if light else 0.34),
        line=t.border,
        line_strong=t.border_strong,
        danger_wash=blend_hex(win, t.danger, 0.14 if light else 0.2),
        primary_off=blend_hex(win, t.accent, 0.4),
    )


def _svg(name: str, body: str, size: int = 16) -> str:
    from ..design.soft_qss import qss_svg
    return qss_svg(name, f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
                         f'viewBox="0 0 16 16">{body}</svg>')


def find_replace_qss(t) -> str:
    k = _tokens(t)
    chevron = _svg("replace-chevron", f'<path d="M4 6.2 L8 10 L12 6.2" fill="none" stroke="{t.text_muted}" '
                                      f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')
    check = _svg("replace-check", f'<path d="M3.8 8.3 L6.8 11.1 L12.2 5.2" fill="none" stroke="{t.text_on_accent}" '
                                  f'stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/>')
    return f"""
QWidget#replaceRoot {{ background: {k['win']}; color: {t.text}; }}
QFrame#replaceTitleBar {{ background: transparent; border: 0; }}
QLabel#replaceTitle {{ color: {t.text}; font-size: 15px; font-weight: 800; background: transparent; }}
QLabel#replaceSubtitle {{ color: {t.text_muted}; font-size: 12px; background: transparent; }}
QPushButton#replaceClose {{ background: transparent; border: 0; border-radius: 13px; padding: 0;
    min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; }}
QPushButton#replaceClose:hover {{ background: {k['danger_wash']}; }}

QFrame#targetSegments {{ background: {k['well']}; border: 1px solid {k['line']}; border-radius: 14px; }}
QPushButton#targetSegment {{ background: transparent; color: {t.text_secondary}; border: 0; border-radius: 11px;
    min-height: 26px; max-height: 26px; padding: 0 14px; font-size: 13px; font-weight: 500; }}
QPushButton#targetSegment:hover {{ color: {t.text}; }}
QPushButton#targetSegment:checked {{ background: {k['row']}; color: {t.text}; font-weight: 700; }}
QPushButton#targetSegment:disabled {{ color: {t.disabled}; }}
QComboBox#targetTrackTag, QComboBox#findScopeTag {{
    background: {k['well']}; color: {t.text}; border: 1px solid {k['line']}; border-radius: 13px;
    min-height: 30px; max-height: 30px; padding: 0 30px 0 14px; font-size: 13px; font-weight: 500; }}
QComboBox#targetTrackTag:hover, QComboBox#findScopeTag:hover {{ background: {k['well_hover']}; border-color: {k['line_strong']}; }}
QComboBox#targetTrackTag::drop-down, QComboBox#findScopeTag::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right; width: 22px; border: 0; background: transparent; }}
QComboBox#targetTrackTag::down-arrow, QComboBox#findScopeTag::down-arrow {{
    image: url("{chevron}"); width: 12px; height: 12px; }}

QLineEdit#findBigField {{ background: {k['well']}; color: {t.text}; border: 1.5px solid transparent;
    border-radius: 14px; min-height: 44px; max-height: 44px; padding: 0 10px; font-size: 15px;
    selection-background-color: {k['on_hover']}; selection-color: {t.text}; }}
QLineEdit#findBigField:hover {{ background: {k['well_hover']}; }}
QLineEdit#findBigField:focus {{ background: {k['win']}; border-color: {t.accent}; }}
QLineEdit#findBigField[regexError="true"] {{ border-color: {t.danger}; background: {k['danger_wash']}; }}
QLabel#findCountBadge {{ background: {k['on']}; color: {t.accent_text}; border-radius: 10px;
    min-height: 22px; max-height: 22px; min-width: 22px; padding: 0 7px; font-size: 12px; font-weight: 700; }}
QLabel#findCountBadge[zero="true"] {{ background: {k['well_hover']}; color: {t.text_muted}; }}
QPushButton#findSwapButton {{ background: {k['win']}; border: 1px solid {k['line']}; border-radius: 16px; padding: 0;
    min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px; }}
QPushButton#findSwapButton:hover {{ border-color: {t.accent}; }}

QPushButton#findOptionChip, QPushButton#findMoreChip {{
    background: {k['well']}; color: {t.text_secondary}; border: 1px solid {k['line']}; border-radius: 12px;
    min-height: 28px; max-height: 28px; padding: 0 12px; font-size: 13px; font-weight: 500; }}
QPushButton#findOptionChip:hover, QPushButton#findMoreChip:hover {{ color: {t.text}; border-color: {k['line_strong']}; }}
QPushButton#findOptionChip:checked {{ background: {k['on']}; color: {t.accent_text}; border-color: transparent; font-weight: 700; }}
QPushButton#findOptionChip:checked:hover {{ background: {k['on_hover']}; }}
QPushButton#findOptionChip:focus, QPushButton#findMoreChip:focus {{ border-color: {t.focus}; }}
QPushButton#findOptionChip:disabled {{ color: {t.disabled}; }}
QPushButton#findMoreChip {{ background: transparent; border-style: dashed; color: {t.text_muted}; }}

QFrame#findResultCard {{ background: {k['card']}; border: 1px solid {k['line']}; border-radius: 18px; }}
QLabel#findResultTitle {{ color: {t.text}; font-size: 13px; font-weight: 700; background: transparent; }}
QLabel#findResultTitle[error="true"] {{ color: {t.danger}; }}
QPushButton#findLinkButton {{ background: transparent; color: {t.text_secondary}; border: 0; border-radius: 10px;
    min-height: 24px; max-height: 24px; padding: 0 10px; font-size: 12px; font-weight: 500; }}
QPushButton#findLinkButton:hover {{ background: {k['well']}; color: {t.text}; }}
QFrame#findResultDivider {{ background: {k['line']}; border: 0; min-height: 1px; max-height: 1px; }}
QListView#findResultCards {{ background: transparent; border: 0; outline: 0; font-size: 14px; }}
QListView#findResultCards::item {{ background: {k['row']}; color: {t.text}; border: 1px solid transparent;
    border-radius: 12px; padding: 8px 10px; margin: 0 2px; }}
QListView#findResultCards::item:hover {{ border-color: {k['line_strong']}; }}
QListView#findResultCards::item:selected {{ background: {k['row']}; color: {t.text}; border-color: {t.accent}; }}
QListView#findResultCards::indicator {{ width: 18px; height: 18px; border-radius: 8px;
    border: 1.5px solid {k['line_strong']}; background: {k['win']}; }}
QListView#findResultCards::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; image: url("{check}"); }}
QListView#findResultCards QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 0; }}
QListView#findResultCards QScrollBar::handle:vertical {{ background: {k['line_strong']}; border-radius: 3px; min-height: 24px; }}
QListView#findResultCards QScrollBar::add-line:vertical, QListView#findResultCards QScrollBar::sub-line:vertical {{ height: 0; }}
QListView#findResultCards QScrollBar::add-page:vertical, QListView#findResultCards QScrollBar::sub-page:vertical {{ background: transparent; }}
QLabel#findEmptyIcon {{ background: {k['win']}; border: 1px solid {k['line']}; border-radius: 12px;
    min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px; }}
QLabel#findEmptyHint {{ color: {t.text_muted}; font-size: 12px; background: transparent; }}

QFrame#replaceFooter {{ background: {k['card']}; border: 0; border-top: 1px solid {k['line']};
    border-bottom-left-radius: {RADIUS - 1}px; border-bottom-right-radius: {RADIUS - 1}px; }}
QLabel#findKeyCap {{ background: {k['win']}; color: {t.text_secondary}; border: 1px solid {k['line']};
    border-bottom: 2px solid {k['line_strong']}; border-radius: 6px; padding: 0 6px; min-height: 18px; max-height: 18px;
    font-size: 11px; font-weight: 600; }}
QLabel#findKeyText {{ color: {t.text_muted}; font-size: 12px; background: transparent; }}
QPushButton#findQuietButton {{ background: transparent; color: {t.text_secondary}; border: 0; border-radius: 16px;
    min-height: 36px; max-height: 36px; padding: 0 16px; font-size: 13px; font-weight: 600; }}
QPushButton#findQuietButton:hover {{ background: {k['well']}; color: {t.text}; }}
QPushButton#findQuietButton:disabled {{ color: {t.disabled}; }}
QPushButton#findPrimaryButton {{ background: {t.accent}; color: {t.text_on_accent}; border: 0; border-radius: 16px;
    min-height: 36px; max-height: 36px; padding: 0 20px; font-size: 13px; font-weight: 700; }}
QPushButton#findPrimaryButton:hover {{ background: {t.accent_hover}; }}
QPushButton#findPrimaryButton:disabled {{ background: {k['primary_off']}; color: {k['win']}; }}
"""


def avatar_label(size: int = 26) -> QLabel:
    """The app's face in a circle, as in the window's title bar."""
    from ..app.ui_zoom import set_size
    from ..runtime_paths import detect_install_root
    label = QLabel()
    label.setObjectName("replaceAvatar")
    set_size(label, fixed_w=size, fixed_h=size)
    source = QPixmap(str(detect_install_root() / "assets" / "app_icon_256.png"))
    if source.isNull():
        return label
    from PySide6.QtWidgets import QApplication
    ratio = QApplication.instance().devicePixelRatio() if QApplication.instance() else 1.0
    side = max(1, round(size * 2 * ratio))
    canvas = QPixmap(side, side)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addEllipse(QRectF(0, 0, side, side))
    painter.setClipPath(clip)
    painter.drawPixmap(canvas.rect(), source)
    painter.end()
    canvas.setDevicePixelRatio(side / size)
    label.setPixmap(canvas)
    label.setScaledContents(True)
    return label


def title_bar(title: str, on_close) -> tuple[QFrame, QLabel, QPushButton]:
    """Face, title, a short line of what will be searched, round close button."""
    from ..design.themed_icons import install_themed_icon
    bar = QFrame()
    bar.setObjectName("replaceTitleBar")
    row = QHBoxLayout(bar)
    row.setContentsMargins(18, 12, 12, 8)
    row.setSpacing(10)
    row.addWidget(avatar_label())
    name = QLabel()
    name.setObjectName("replaceTitle")
    bind_text(name, title)
    row.addWidget(name)
    subtitle = QLabel()
    subtitle.setObjectName("replaceSubtitle")
    # A long track name is cut at the window edge (the tooltip has it all), never widens the window.
    subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    row.addWidget(subtitle, 1)
    close = QPushButton()
    close.setObjectName("replaceClose")
    install_themed_icon(close, "fa5s.times", "muted")
    close.setIconSize(QSize(14, 14))
    close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    close.setCursor(Qt.CursorShape.PointingHandCursor)
    bind_text(close, "关闭", property="toolTip")
    bind_text(close, "关闭", property="accessibleName")
    close.clicked.connect(on_close)
    row.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
    return bar, subtitle, close


class CountBadge(QObject):
    """A small count at the end of a line edit; the text stops before it."""

    def __init__(self, edit: QLineEdit):
        super().__init__(edit)
        self.edit = edit
        self.label = QLabel("0", edit)
        self.label.setObjectName("findCountBadge")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        edit.installEventFilter(self)
        self.shown = True
        self.set_count(0)

    def set_shown(self, shown: bool) -> None:
        """Hidden while the field is empty, so the placeholder has the whole width."""
        if shown != self.shown:
            self.shown = shown
            self.label.setVisible(shown)
            self._place()

    def set_count(self, count: int | None, tooltip: str = "") -> None:
        """``None`` marks a pattern that cannot be searched."""
        self.label.setText("!" if count is None else str(count))
        zero = not count
        if self.label.property("zero") != zero:
            self.label.setProperty("zero", zero)
            self.label.style().unpolish(self.label)
            self.label.style().polish(self.label)
        self.label.setToolTip(tooltip)
        self._place()

    def _place(self) -> None:
        self.label.adjustSize()
        hint = self.label.sizeHint()
        width, height = max(hint.width(), hint.height()), hint.height()
        right = max(8, (self.edit.height() - height) // 2 + 2)
        self.label.setGeometry(self.edit.width() - right - width, (self.edit.height() - height) // 2, width, height)
        margins = self.edit.textMargins()
        room = width + 6 if self.shown else 0
        if margins.right() != room:
            self.edit.setTextMargins(margins.left(), margins.top(), room, margins.bottom())

    def eventFilter(self, watched, event):
        if watched is self.edit and event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.StyleChange):
            self._place()
        return False


def key_hints(pairs) -> QWidget:
    """「↓ 切到替换  Enter 替换所选  Esc 关闭」 as small key caps and their words."""
    host = QWidget()
    host.setObjectName("findKeyHint")
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    host.words = []
    for index, (key, words) in enumerate(pairs):
        if index:
            row.addSpacing(8)
        cap = QLabel()
        cap.setObjectName("findKeyCap")
        bind_text(cap, key)   # Entrée, Intro, Échap… where keyboards say so
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(cap)
        text = QLabel()
        text.setObjectName("findKeyText")
        bind_text(text, words)
        row.addWidget(text)
        host.words.append(text)
    return host


def empty_row(icon: str = "fa5s.search") -> tuple[QFrame, QLabel]:
    """The one-line card body shown instead of an empty list."""
    from ..app.link_download_widgets import icon_label
    frame = QFrame()
    frame.setObjectName("findEmptyRow")
    row = QHBoxLayout(frame)
    row.setContentsMargins(14, 2, 14, 12)
    row.setSpacing(12)
    mark = icon_label(icon, 14, "accent", "findEmptyIcon")
    row.addWidget(mark)
    hint = QLabel()
    hint.setObjectName("findEmptyHint")
    hint.setWordWrap(True)
    row.addWidget(hint, 1)
    frame.icon = mark
    return frame, hint


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("findResultDivider")
    return line
