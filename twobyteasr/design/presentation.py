"""Presentation roles. These helpers never own values, commands or settings."""
from __future__ import annotations

from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit, QSizePolicy, QWidget
from .tokens import CONTROL_HEIGHTS, FIELD_WIDTHS

BUTTON_ALIASES = {
    "primary": ("primary", "studioPrimary", "hubPrimary", "projectCardOpen", "compactPrimary", "workshopPrimary"),
    "secondary": ("outline", "softAction", "secondaryCTA", "studioButton", "hubSecondary", "studioFooterButton", "hubToolbarButton", "workshopSecondary"),
    "ghost": ("flat", "projectCardMore", "dialogSurfaceClose", "toolDialogClose"),
    "danger": ("danger", "dangerButton"),
    "toolbar": ("studioTool", "windowControl", "studioWindowControl", "windowControlClose", "studioWindowControlClose"),
    "toggle": ("projectViewButton", "styleEmphasis", "styleAnchor", "workspaceNav"),
}


def button_role(button: QAbstractButton, role: str = "secondary", *, icon: str = "", size: str = "default"):
    button.setProperty("buttonRole", role)
    button.setProperty("controlSize", size)
    if not button.accessibleName():
        button.setAccessibleName(button.text() or button.toolTip())
    if icon:
        from ..themed_icons import install_themed_icon
        install_themed_icon(button, icon, "on_accent" if role == "primary" else "primary")
    return button


def glyph_button(button: QAbstractButton, *, size: int = 32, glyph: int = 22):
    """A square button labelled by one glyph, such as a dialog's ×.

    The role/size rules pad every button by 16 px a side and set a 36 px
    minimum height: in a 32 px square the × had no width left (nothing was
    painted) and the square grew to 38 px tall (2026-10-13). The widget's own
    sheet wins over those rules; the role keeps its colours, hover and focus.
    """
    inner = size - 2  # the role rules draw a 1 px border
    button.setStyleSheet(f"padding: 0; min-width: {inner}px; max-width: {inner}px; "
                         f"min-height: {inner}px; max-height: {inner}px; font-size: {glyph}px;")
    return button


def field_width(field: QWidget, role: str = "preferred", *, size: str = "default"):
    low, high = FIELD_WIDTHS[role]
    field.setProperty("fieldWidth", role)
    field.setProperty("controlSize", size)
    field.setMinimumWidth(low)
    field.setMaximumWidth(high)
    field.setSizePolicy(QSizePolicy.Policy.Expanding if role == "expanding" else QSizePolicy.Policy.Preferred,
                        QSizePolicy.Policy.Fixed)
    field.setMinimumHeight(CONTROL_HEIGHTS[size])
    field.setMaximumHeight(CONTROL_HEIGHTS[size])
    return field


def prepare_controls(root: QWidget) -> None:
    """Classify existing builders once, before display; explicit roles win."""
    aliases = {name:role for role,names in BUTTON_ALIASES.items() for name in names}
    for widget in root.findChildren(QWidget):
        if isinstance(widget, QAbstractButton) and not widget.property("buttonRole"):
            role = aliases.get(widget.objectName())
            if role:
                button_role(widget, role, size="compact" if role in {"toolbar", "toggle"} else "default")
        if widget.property("fieldWidth") or widget.minimumWidth() == widget.maximumWidth():
            continue
        if isinstance(widget, QAbstractSpinBox):
            field_width(widget, "numeric", size="compact")
        elif isinstance(widget, QComboBox):
            field_width(widget, "preferred", size="compact" if root.objectName()=="subtitleStudio" else "default")
        # Text fields need their builder to distinguish path / key / search.
