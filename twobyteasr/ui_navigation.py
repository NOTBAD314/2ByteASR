"""Shared management navigation for the desktop workbench.

The recognition home remains the primary work area.  Deep-management screens
reuse this compact navigation so the same destination is never represented by
different labels or different callbacks.
"""

from __future__ import annotations

import qtawesome as qta
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from twobyteasr.ui_theme import GREEN, INK, MUTED


# Pages that share this sidebar (Model Workshop, Term Library, History) used
# different page/sidebar stylesheets, so switching between them changed the
# title size and the navigation height. Sizes live here; colours stay themed by
# each page. A widget's own style sheet wins over its ancestors' sheets.
PAGE_TITLE_QSS = "font-size: 24px; font-weight: 800;"
SIDEBAR_HEADING_QSS = "font-size: 14px; font-weight: 600;"

# 2026-10-12: one sidebar column for all three pages. Its width is constant
# (logical px, scaled by the interface zoom) whatever a page adds below the
# navigation, so switching pages never moves the sidebar or the content edge.
SIDEBAR_WIDTH = 232
SIDEBAR_MARGIN = 12
SIDEBAR_SPACING = 6
NAV_ITEM_HEIGHT = 42


def _active_theme():
    from .theme_manager import theme_key
    from .ui_theme import theme_definition

    return theme_definition(theme_key())


def navigation_item_qss(theme) -> str:
    """Complete nav item style, set on the navigation itself.

    Being the nearest style sheet, it wins over every page / control sheet
    rule for these buttons (Qt prefers the closer sheet regardless of
    selector specificity), so geometry, border and selection colour are the
    same on every page. Border is always 1px (transparent unless focused):
    22 + 2 * 9 + 2 * 1 = 42 px rows.
    """
    return f"""
QPushButton#workspaceNav {{
    background: transparent; color: {theme.text_secondary};
    border: 1px solid transparent; border-radius: 10px;
    padding: 9px 12px; margin: 0px;
    min-height: 22px; max-height: 22px;
    font-size: 13px; font-weight: 500; text-align: left;
}}
QPushButton#workspaceNav:hover, QPushButton#workspaceNav:pressed {{
    background: {theme.selected}; color: {theme.text}; border-color: transparent;
}}
QPushButton#workspaceNav:checked {{
    background: {theme.accent_tint}; color: {theme.text}; font-weight: 600; border-color: transparent;
}}
QPushButton#workspaceNav:focus {{ border-color: {theme.focus}; }}
"""


def sidebar_frame_qss(object_name: str, theme) -> str:
    return f"""
QFrame#{object_name} {{
    background: {theme.panel}; border: 1px solid {theme.border}; border-radius: 16px;
}}
QLabel#workspaceSidebarHeading {{ color: {theme.text_muted}; background: transparent; border: 0; }}
"""


def style_workspace_page_title(label):
    from .ui_zoom import set_sheet
    set_sheet(label, PAGE_TITLE_QSS)
    return label


def style_workspace_sidebar_heading(label):
    from .ui_zoom import set_sheet
    set_sheet(label, SIDEBAR_HEADING_QSS)
    return label


class WorkspaceNavigation(QWidget):
    recognition_requested = Signal()
    workshop_requested = Signal()
    terms_requested = Signal()
    history_requested = Signal()

    ITEMS = (
        ("recognition", "返回字幕识别", "fa5s.arrow-left"),
        ("workshop", "模型工坊", "fa5s.cubes"),
        ("terms", "术语库", "fa5s.book-open"),
        ("history", "识别记录", "fa5s.history"),
    )

    def __init__(self, active: str, parent=None):
        super().__init__(parent)
        from .ui_zoom import set_size

        self.buttons: dict[str, QPushButton] = {}
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for key, label, icon_name in self.ITEMS:
            button = QPushButton(label)
            button.setObjectName("workspaceNav")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            # A mouse click must not leave a focus ring on the page left behind.
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            button.setIconSize(QSize(18, 18))
            # The column has one width; never let a label pin it wider.
            button.setProperty("flexibleWidth", True)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            set_size(button, fixed_h=NAV_ITEM_HEIGHT)
            button.clicked.connect(lambda _checked=False, value=key: self._activate(value))
            self.group.addButton(button)
            self.buttons[key] = button
            layout.addWidget(button)
        self.refresh_theme_palette()
        self.set_active(active)

    def refresh_theme_palette(self) -> None:
        from .ui_zoom import set_sheet
        set_sheet(self, navigation_item_qss(_active_theme()))

    def set_active(self, key: str):
        for item_key, _label, icon_name in self.ITEMS:
            checked = item_key == key
            button = self.buttons[item_key]
            button.setChecked(checked)
            button.setIcon(
                qta.icon(
                    icon_name,
                    color=GREEN if checked else MUTED,
                    color_active=GREEN,
                )
            )

    def _activate(self, key: str):
        signal = {
            "recognition": self.recognition_requested,
            "workshop": self.workshop_requested,
            "terms": self.terms_requested,
            "history": self.history_requested,
        }[key]
        signal.emit()


class WorkspaceSidebar(QFrame):
    """The sidebar column of Model Workshop, Recognition History and Term Library.

    Fixed width (zoom-aware), same margins, heading and navigation on every
    page. A page adds its own sections to ``body`` below the navigation; they
    word-wrap inside the column instead of widening it.
    """

    def __init__(self, active: str, *, object_name: str = "workspaceSidebar", parent=None):
        super().__init__(parent)
        from .i18n import current_language, translate
        from .ui_zoom import set_size

        self.setObjectName(object_name)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        set_size(self, fixed_w=SIDEBAR_WIDTH)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(SIDEBAR_MARGIN, SIDEBAR_MARGIN, SIDEBAR_MARGIN, SIDEBAR_MARGIN)
        self.body.setSpacing(SIDEBAR_SPACING)
        self.heading = QLabel(translate("工作台", current_language()))
        self.heading.setObjectName("workspaceSidebarHeading")
        style_workspace_sidebar_heading(self.heading)
        self.body.addWidget(self.heading)
        self.navigation = WorkspaceNavigation(active)
        self.body.addWidget(self.navigation)
        self.refresh_theme_palette()

    def refresh_theme_palette(self) -> None:
        from .ui_zoom import set_sheet
        set_sheet(self, sidebar_frame_qss(self.objectName(), _active_theme()))


NAVIGATION_QSS = f"""
QPushButton#workspaceNav {{
    background: transparent;
    color: {INK};
    border: 0;
    border-radius: 10px;
    padding: 10px 12px;
    min-height: 22px;
    text-align: left;
    font-weight: 600;
}}
QPushButton#workspaceNav:hover {{
    background: #eeeae2;
}}
QPushButton#workspaceNav:checked {{
    background: #e6efe2;
    color: {GREEN};
    font-weight: 700;
}}
"""
