"""Token-driven QSS for interactive controls, popups, and scrollbars.

Appended LAST onto the application sheet and the Studio page sheet so
warm-authored STUDIO_QSS cannot collapse SURFACE_3 back into the panel.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from .tokens import BUTTON_SIZES, CONTROL_HEIGHTS, RADIUS_SCALE, WEIGHT_SCALE
from .presentation import BUTTON_ALIASES
from ..typography import UI_FONT_STACK

if TYPE_CHECKING:
    from ..ui_theme import ThemeDefinition

_CHECK_ICON = (Path(__file__).resolve().parents[2] / "assets" / "check-dark.png").as_posix()
_DOT_ICON = (Path(__file__).resolve().parents[2] / "assets" / "dot-dark.png").as_posix()


def build_control_qss(theme: ThemeDefinition) -> str:
    """SURFACE_3 controls, themed popups, thin scrollbars. No gradients."""
    bg0 = theme.app_background
    bg1 = theme.panel
    bg2 = theme.surface
    bg3 = theme.input_surface
    hover = theme.selected
    pressed = theme.accent_soft
    popup = theme.surface_elevated
    modal = theme.surface
    border = theme.border
    border_d = theme.border_strong
    focus = theme.accent
    text = theme.text
    muted = theme.text_muted
    disabled = theme.disabled
    accent = theme.accent
    accent_soft = theme.accent_soft
    assets = Path(__file__).resolve().parents[2] / 'assets' / 'controls'
    foreground = 'dark' if theme.key == 'warm' else 'light'
    on_accent = 'light' if theme.key in {'warm', 'grape'} else 'dark'
    arrow = (assets / f'chevron-{foreground}.svg').as_posix()
    submenu_arrow = (assets / f'right-{foreground}.svg').as_posix()
    check = (assets / f'check-{on_accent}.svg').as_posix()
    dot = (assets / f'dot-{on_accent}.svg').as_posix()
    return f"""
/* P9A control system — SURFACE_3 sits above panel/card. */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QAbstractSpinBox {{
    background: {bg3};
    color: {text};
    border: 1px solid {border_d};
    border-radius: {RADIUS_SCALE['control']}px;
    min-height: {CONTROL_HEIGHTS['compact']}px;
    max-height: {CONTROL_HEIGHTS['default']}px;
    padding: 0 8px;
    selection-background-color: {accent};
    selection-color: {theme.text_on_accent};
}}
QPlainTextEdit, QTextEdit {{
    background: {bg3};
    color: {text};
    border: 1px solid {border_d};
    border-radius: 6px;
    padding: 8px;
    selection-background-color: {accent};
    selection-color: {theme.text_on_accent};
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover,
QAbstractSpinBox:hover, QPlainTextEdit:hover, QTextEdit:hover {{
    border-color: {focus};
    background: {hover};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QAbstractSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {focus};
    background: {bg3};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled,
QAbstractSpinBox:disabled, QPlainTextEdit:disabled, QTextEdit:disabled {{
    color: {disabled};
    background: {bg1};
    border-color: {border};
}}
QComboBox::drop-down {{
    border: 0;
    width: 22px;
    background: transparent;
}}
QComboBox::down-arrow, QComboBox::down-arrow:on {{
    width: 12px;
    height: 12px;
    image: url({arrow});
}}
QComboBox QAbstractItemView, QComboBox QListView, QComboBox QTreeView {{
    background: {popup};
    color: {text};
    border: 1px solid {border_d};
    outline: 0;
    selection-background-color: {accent_soft};
    selection-color: {text};
}}
QComboBox QAbstractItemView::item, QComboBox QListView::item {{
    min-height: 28px;
    padding: 4px 8px;
    color: {text};
    background: {popup};
}}
QComboBox QAbstractItemView::item:hover, QComboBox QListView::item:hover {{
    background: {hover};
    color: {text};
}}
QComboBox QAbstractItemView::item:selected, QComboBox QListView::item:selected {{
    background: {accent_soft};
    color: {text};
}}
QAbstractItemView, QListView, QTreeView, QListWidget, QTreeWidget {{
    background: {bg2};
    color: {text};
    border: 1px solid {border};
    outline: 0;
    selection-background-color: {accent_soft};
    selection-color: {text};
    alternate-background-color: {bg1};
}}
QAbstractItemView::item:hover, QListView::item:hover, QTreeView::item:hover,
QListWidget::item:hover, QTreeWidget::item:hover {{
    background: {hover};
    color: {text};
}}
QAbstractItemView::item:selected, QListView::item:selected, QTreeView::item:selected,
QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {accent_soft};
    color: {text};
}}
QHeaderView::section {{
    background: {bg1};
    color: {muted};
    border: 0;
    border-bottom: 1px solid {border};
    padding: 8px 4px;
    font-weight: 600;
}}
QMenu {{
    background: {popup};
    color: {text};
    border: 1px solid {border_d};
    padding: 4px;
    font-family: {UI_FONT_STACK}; font-size: 13px; font-weight: 500;
}}
QMenu::item {{
    background: transparent;
    color: {text};
    padding: 6px 12px;
    min-height: 24px;
}}
QMenu::item:selected {{
    background: {accent_soft};
    color: {text};
}}
QMenu::item:disabled {{
    color: {disabled};
}}
QMenu::separator {{
    height: 1px;
    background: {border};
    margin: 4px 8px;
}}
QMenu::right-arrow {{ image: url({submenu_arrow}); width: 12px; height: 12px; }}
QToolTip {{
    background: {popup};
    color: {text};
    border: 1px solid {border_d};
    padding: 4px 8px;
}}
QDialog, QMessageBox {{
    background: {modal};
    color: {text};
}}
QWidget#studioModalScrim {{
    background: {theme.overlay_scrim};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
    border: 0;
}}
QScrollBar::handle:vertical {{
    background: {border};
    min-height: 24px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background: {border_d};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0;
    border: 0;
}}
QScrollBar::handle:horizontal {{
    background: {border};
    min-width: 24px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {border_d};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
    background: transparent;
    border: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}
QToolButton#studioTool {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    min-width: 32px;
    min-height: 32px;
    padding: 4px;
}}
QToolButton#studioTool:hover {{
    background: {hover};
    border-color: {border};
}}
QToolButton#studioTool:checked, QToolButton#studioTool:pressed {{
    background: {pressed};
    border-color: {accent};
}}
QTabWidget#contextDrawer QTabBar::tab {{
    min-height: 36px;
    min-width: 56px;
    padding: 4px 8px;
    color: {muted};
    background: transparent;
    border: 0;
}}
QTabWidget#contextDrawer QTabBar::tab:hover {{
    background: {hover};
    color: {text};
}}
QTabWidget#contextDrawer QTabBar::tab:selected {{
    color: {text};
    font-weight: 700;
    background: {pressed};
    border-bottom: 2px solid {accent};
}}
QCheckBox, QRadioButton {{
    color: {text};
    spacing: 8px;
    padding: 4px 0;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    background: {bg3};
    border: 1px solid {border_d};
}}
QCheckBox::indicator {{
    border-radius: 3px;
}}
QRadioButton::indicator {{
    border-radius: 8px;
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {focus};
}}
QCheckBox, QRadioButton {{
    spacing: 6px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    margin-right: 2px;
}}
QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
    image: url({check});
    image-position: center;
}}
QRadioButton::indicator:checked {{
    background: {accent};
    border: 1px solid {accent};
    image: url({dot});
    image-position: center;
}}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    background: {bg1};
    border-color: {border};
}}
""" + build_button_qss(theme)


def build_button_qss(t) -> str:
    """All variants and legacy semantic names share one state specification."""
    sheet = []
    variants = {
        "primary": (t.accent, t.text_on_accent, t.accent, t.accent_hover, t.accent_pressed),
        "secondary": (t.surface_elevated, t.text, t.border, t.selected, t.accent_soft),
        "ghost": ("transparent", t.text_secondary, "transparent", t.selected, t.accent_soft),
        "danger": (t.danger_soft, t.danger, t.danger, t.danger_soft, t.selected),
        "icon": ("transparent", t.text, "transparent", t.selected, t.accent_soft),
        "toolbar": ("transparent", t.text_secondary, "transparent", t.selected, t.accent_soft),
        "toggle": ("transparent", t.text_secondary, "transparent", t.selected, t.accent_soft),
    }
    # Plain Qt buttons inherit the secondary rule; variants follow it.
    sheet.append(f"QPushButton {{ background: {t.surface_elevated}; color: {t.text}; border: 1px solid {t.border}; border-radius: 8px; min-height: 28px; padding: 0 12px; font-size: 13px; font-weight: 500; }}")
    for role, (bg, fg, border, hover, pressed) in variants.items():
        selectors=[f'{kind}[buttonRole="{role}"]' for kind in ('QPushButton','QToolButton')]
        selectors += [f'{kind}#{name}' for name in BUTTON_ALIASES.get(role,()) for kind in ('QPushButton','QToolButton')]
        def rules(state, values):
            sheet.append(', '.join(s+state for s in selectors)+' { '+values+' }')
        padding = '0 4px' if role in {'icon','toolbar','toggle'} else '0 12px'
        weight = WEIGHT_SCALE['bold' if role == 'primary' else 'semibold' if role == 'danger' else 'medium']
        rules('',f'background: {bg}; color: {fg}; border: 1px solid {border}; border-radius: 8px; min-height: 28px; padding: {padding}; font-size: {14 if role == "primary" else 13}px; font-weight: {weight};')
        rules(':hover',f'background: {hover}; color: {fg}; border-color: {t.accent if role == "primary" else t.border_strong};')
        rules(':pressed',f'background: {pressed}; color: {fg}; border-color: {t.accent};')
        rules(':checked',f'background: {pressed}; color: {fg if role == "primary" else t.text}; border-color: {t.accent};')
        rules(':focus',f'border-color: {t.focus};')
        rules(':disabled',f'background: {t.panel}; color: {t.disabled}; border-color: {t.border};')
        # A lone [controlSize] selector loses to legacy #primary/#studioTool
        # rules. Qualify the same selectors so explicit sizes actually win.
        for size, (height, font_size, horizontal_padding) in BUTTON_SIZES.items():
            size_selectors = ', '.join(f'{s}[controlSize="{size}"]' for s in selectors)
            pad = 4 if role in {'icon', 'toolbar', 'toggle'} else horizontal_padding
            type_size = max(14, font_size) if role == 'primary' else font_size
            sheet.append(f'{size_selectors} {{ min-height: {height}px; max-height: {height}px; padding: 0 {pad}px; font-size: {type_size}px; }}')
    for size, height in CONTROL_HEIGHTS.items():
        sheet.append(f'QComboBox[controlSize="{size}"], QLineEdit[controlSize="{size}"], QAbstractSpinBox[controlSize="{size}"] {{ min-height: {height}px; max-height: {height}px; }}')
    return '\n'.join(sheet)
