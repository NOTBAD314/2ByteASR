"""One look and one way of opening for every dropdown list (2026-10-26).

User report (link window and home page): some lists opened upward, one ran
from the top of the screen to the bottom, one hid its first row under a
scroll arrow, and rounded lists sat inside a square frame with a shadow.
Fusion's default combo popup is menu-like: it centres the current row on the
box and ignores the row limit; its container paints a square background and
gets the system drop shadow.

Every QComboBox (plain or StudioComboBox) is prepared the first time it is
shown (``prepare_combo``): a list popup (``combobox-popup: 0`` in the window
sheet), rows drawn by a styled delegate, a transparent container without a
system shadow. Its popup is placed when shown (``place_native_popup``). The
home page's own popup (``main_ui_popup``) uses the same sheet, row height and
placement (``popup_qss``, ``ROW``, ``below_rect``).

Placement: below the box. Short of room, the list gets shorter; only when not
even ``MIN_ROWS`` rows fit below does it open above.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QStyledItemDelegate, QWidget

ROW = 34          # row height in logical px at 100% interface zoom
MAX_ROWS = 10
MIN_ROWS = 3      # the user asked for downward lists wherever it is usable
GAP = 4           # between the box and its list
PAD = 5           # inside the list's rounded border
RADIUS = 12
EDGE = 4          # kept free at the screen's edge
CONTAINER = "QComboBoxPrivateContainer"
READY = "_comboPopupReady"   # set by combos that own their popup (FramelessPopupCombo)
_DEFAULT_DELEGATES = frozenset({"QComboBoxDelegate", "QComboMenuDelegate"})


def popup_qss(theme) -> str:
    """The list sheet, set on the popup window itself so no page or dialog
    sheet above it can change its rows (the closest sheet wins in Qt)."""
    from .soft_qss import soft_tokens
    from .ui_theme import blend_hex
    k = soft_tokens(theme)
    hover = blend_hex(theme.surface_elevated, theme.text, 0.07 if theme.is_light else 0.09)
    chip = blend_hex(theme.surface_elevated, theme.accent, 0.15 if theme.is_light else 0.24)
    return f"""
QComboBoxPrivateContainer, QFrame#comboPopupWindow {{ background: transparent; border: 0; margin: 0; padding: 0; }}
QAbstractItemView {{
    background: {k.card}; color: {theme.text}; border: 1px solid {theme.hairline}; border-radius: {RADIUS}px;
    padding: {PAD}px; outline: 0; selection-background-color: {chip}; selection-color: {theme.accent_text};
}}
QAbstractItemView::item {{
    min-height: {ROW}px; padding: 0 10px; margin: 0; border: 0; border-radius: 8px;
    background: transparent; color: {theme.text};
}}
QAbstractItemView::item:hover {{ background: {hover}; color: {theme.text}; }}
QAbstractItemView::item:selected {{ background: {chip}; color: {theme.accent_text}; }}
QAbstractItemView::item:disabled {{ background: transparent; color: {theme.disabled}; }}
QScrollBar:vertical {{ background: transparent; border: 0; width: 10px; margin: 6px 2px 6px 0; }}
QScrollBar::handle:vertical {{ background: {theme.border_strong}; border-radius: 3px; min-height: 28px; margin: 0 2px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: 0; background: transparent; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


def style_popup(window: QWidget) -> None:
    """Give a popup window the shared sheet; nothing to do when the theme and
    zoom are the ones it already has."""
    from ..app import ui_zoom
    from .theme_manager import theme_definition, theme_key
    theme = theme_definition(theme_key())
    key = f"{theme.key}:{ui_zoom.zoom_percent()}"
    if window.property("_comboPopupSheet") != key:
        window.setProperty("_comboPopupSheet", key)
        ui_zoom.set_sheet(window, popup_qss(theme))


def prepare_combo(combo: QComboBox) -> None:
    """First show of a box: make its popup window transparent, frameless and
    shadowless and its rows styled. Before the popup ever opens, so the native
    window is created that way (changing a shown window recreates it and
    flashes).

    Frameless too (2026-10-27, user: black corners around many lists): Windows
    only makes a see-through window layered when it has no native frame, and
    Qt's combo popup is a plain ``Popup``. Without the flag the corners outside
    the rounded border came out black."""
    if combo.property(READY):
        return
    combo.setProperty(READY, True)
    view = combo.view()
    container = view.window()
    if container is not combo.window() and not container.isVisible():
        # A hidden window that already exists is recreated on its next show.
        container.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        container.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        container.setAutoFillBackground(False)
    delegate = combo.itemDelegate()
    if delegate is None or delegate.metaObject().className() in _DEFAULT_DELEGATES:
        combo.setItemDelegate(QStyledItemDelegate(view))
    style_popup(container)


def below_rect(anchor: QWidget, width: int, height: int, min_height: int) -> QRect:
    """Global rectangle for a list under ``anchor`` (see the module note)."""
    from ..app.ui_zoom import px
    screen = (anchor.screen() or QGuiApplication.primaryScreen()).availableGeometry()
    # Points inside the box: an edge pixel can belong to the next monitor,
    # which converts it with that monitor's scale (2026-10-26, maximized window).
    top_left = anchor.mapToGlobal(QPoint(0, 0))
    bottom = anchor.mapToGlobal(QPoint(0, max(0, anchor.height() - 1))).y() + 1
    edge, gap = px(EDGE), px(GAP)
    width = max(1, min(int(width), screen.width() - 2 * edge))
    x = max(screen.left() + edge, min(top_left.x(), screen.right() + 1 - edge - width))
    y = bottom + gap
    room = screen.bottom() + 1 - edge - y
    if room >= min(height, min_height):
        return QRect(x, y, width, max(1, min(height, room)))
    above = top_left.y() - gap - (screen.top() + edge)
    if above > room:
        h = max(1, min(height, above))
        return QRect(x, top_left.y() - gap - h, width, h)
    return QRect(x, y, width, max(1, room))


def content_width(combo: QComboBox, font_metrics) -> int:
    """Width that shows the longest item without eliding."""
    from ..app.ui_zoom import px
    text = max((font_metrics.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())), default=0)
    icon = combo.iconSize().width() + px(6) if any(
        not combo.itemIcon(i).isNull() for i in range(min(combo.count(), 64))) else 0
    return text + icon + px(64)


def place_native_popup(container: QWidget) -> None:
    """Shown Qt combo popup: as wide as its longest item, below its box."""
    combo = container.parentWidget()
    if not isinstance(combo, QComboBox):
        return
    style_popup(container)   # the theme or zoom may have changed since the box was shown
    view = combo.view()
    if not isinstance(view, QAbstractItemView):
        return
    # Qt sets the scroll bars once, when the container is made: a box built
    # before its window had the theme sheet (StudioComboBox calls view() in
    # its constructor) kept the menu-style "never" and showed no scroll bar.
    view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    hidden = getattr(view, "isRowHidden", None)
    rows = [row for row in range(combo.count()) if not (callable(hidden) and hidden(row))][:combo.maxVisibleItems()]
    chrome = max(0, container.height() - view.viewport().height())
    heights = [max(1, view.sizeHintForRow(row)) for row in rows]
    natural = chrome + sum(heights)
    least = chrome + sum(heights[:MIN_ROWS])
    width = max(container.width(), min(content_width(combo, view.fontMetrics()), combo.width() * 3))
    container.setGeometry(below_rect(combo, width, natural, least))
