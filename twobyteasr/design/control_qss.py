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
    ring = theme.focus
    border_hover = theme.control_border_hover
    assets = Path(__file__).resolve().parents[2] / 'assets' / 'controls'
    foreground = 'dark' if theme.is_light else 'light'
    on_accent = 'light' if theme.on_accent_is_light else 'dark'
    arrow = (assets / f'chevron-{foreground}.svg').as_posix()
    submenu_arrow = (assets / f'right-{foreground}.svg').as_posix()
    check = (assets / f'check-{on_accent}.svg').as_posix()
    dot = (assets / f'dot-{on_accent}.svg').as_posix()
    return f"""
/* P9A control system — SURFACE_3 sits above panel/card. 2026-10-07: inputs
   change border (not fill) on hover; keyboard focus uses the info ring;
   selection is a neutral lift, never a brand/status wash. */
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
    border-color: {border_hover};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QAbstractSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {ring};
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
    selection-background-color: {hover};
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
    background: {hover};
    color: {text};
}}
QAbstractItemView, QListView, QTreeView, QListWidget, QTreeWidget {{
    background: {bg2};
    color: {text};
    border: 1px solid {border};
    outline: 0;
    selection-background-color: {hover};
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
    background: {hover};
    color: {text};
}}
/* A header is an item view too; without this it inherited the view border
   above and drew a second rounded box inside every table (2026-10-14). */
QHeaderView {{
    background: transparent;
    border: 0;
}}
QHeaderView::section {{
    background: {bg1};
    color: {muted};
    border: 0;
    border-bottom: 1px solid {border};
    padding: 8px 6px;
    font-size: 12px;
    font-weight: 500;
}}
QMenu {{
    background: {popup};
    color: {text};
    border: 1px solid {border_d};
    border-radius: {RADIUS_SCALE['control']}px;
    padding: 5px;
    font-family: {UI_FONT_STACK}; font-size: 13px; font-weight: 500;
}}
QMenu::item {{
    background: transparent;
    color: {text};
    padding: 6px 24px 6px 12px;
    min-height: 24px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background: {hover};
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
    padding: 6px 10px;
    font-family: {UI_FONT_STACK}; font-size: 12px; font-weight: 500;
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
    background: {border_d};
    min-height: 28px;
    border-radius: 3px;
    margin: 2px 1px;
}}
QScrollBar::handle:vertical:hover {{
    background: {muted};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0;
    border: 0;
}}
QScrollBar::handle:horizontal {{
    background: {border_d};
    min-width: 28px;
    border-radius: 3px;
    margin: 1px 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {muted};
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
    background: {theme.accent_tint};
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
    font-weight: 600;
    background: transparent;
    border-bottom: 2px solid {accent};
}}
QTabWidget::pane {{
    background: {bg2};
    border: 1px solid {border};
    border-radius: {RADIUS_SCALE['control']}px;
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {theme.text_secondary};
    border: 0;
    border-bottom: 2px solid transparent;
    padding: 7px 14px;
    margin-right: 2px;
    font-family: {UI_FONT_STACK}; font-size: 13px; font-weight: 500;
}}
QTabBar::tab:hover {{ color: {text}; background: {hover}; }}
QTabBar::tab:selected {{ color: {text}; border-bottom: 2px solid {accent}; font-weight: 600; }}
QTabBar::tab:disabled {{ color: {disabled}; }}
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
    border-radius: 4px;
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
/* Check boxes inside list rows share the same indicator as QCheckBox. */
QListView::indicator, QListWidget::indicator, QTreeView::indicator, QTableView::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    background: {bg3}; border: 1px solid {border_d};
}}
QListView::indicator:hover, QListWidget::indicator:hover, QTreeView::indicator:hover,
QTableView::indicator:hover {{ border-color: {border_hover}; }}
QListView::indicator:checked, QListWidget::indicator:checked, QTreeView::indicator:checked,
QTableView::indicator:checked {{ background: {accent}; border-color: {accent}; image: url({check}); }}
""" + build_button_qss(theme)


def build_button_qss(t) -> str:
    """All variants and legacy semantic names share one state specification.

    Weight rule (2026-10-07): primary 600, every other role 500. The bundled
    UI face is Medium; 600 is the single synthetic emphasis and Heavy is
    reserved for display titles, so buttons never mix three "bold" looks.
    """
    from ..ui_theme import blend_hex
    sheet = []
    # Danger stays findable but quiet at rest: half-strength outline, full
    # colour and a soft wash only on hover/press.
    danger_rest = blend_hex(t.surface, t.danger, 0.55)
    variants = {
        "primary": (t.accent, t.text_on_accent, t.accent, t.accent_hover, t.accent_pressed),
        "secondary": (t.surface_elevated, t.text, t.border_strong, t.selected, t.border),
        "ghost": ("transparent", t.text_secondary, "transparent", t.selected, t.border),
        "danger": ("transparent", t.danger, danger_rest, t.danger_soft, t.danger_soft),
        "icon": ("transparent", t.text, "transparent", t.selected, t.border),
        "toolbar": ("transparent", t.text_secondary, "transparent", t.selected, t.border),
        "toggle": ("transparent", t.text_secondary, "transparent", t.selected, t.border),
    }
    hover_border = {"primary": t.accent_hover, "danger": t.danger, "secondary": t.text_muted}
    # Plain Qt buttons inherit the secondary rule; variants follow it.
    sheet.append(f"QPushButton {{ background: {t.surface_elevated}; color: {t.text}; border: 1px solid {t.border_strong}; border-radius: 8px; min-height: 28px; padding: 0 12px; font-size: 13px; font-weight: 500; }}")
    for role, (bg, fg, border, hover, pressed) in variants.items():
        selectors=[f'{kind}[buttonRole="{role}"]' for kind in ('QPushButton','QToolButton')]
        selectors += [f'{kind}#{name}' for name in BUTTON_ALIASES.get(role,()) for kind in ('QPushButton','QToolButton')]
        def rules(state, values):
            sheet.append(', '.join(s+state for s in selectors)+' { '+values+' }')
        padding = '0 4px' if role in {'icon','toolbar','toggle'} else '0 12px'
        weight = WEIGHT_SCALE['semibold' if role == 'primary' else 'medium']
        active_fg = t.text if role in {'ghost', 'toolbar', 'toggle'} else fg
        rules('',f'background: {bg}; color: {fg}; border: 1px solid {border}; border-radius: 8px; min-height: 28px; padding: {padding}; font-size: {14 if role == "primary" else 13}px; font-weight: {weight};')
        rules(':hover',f'background: {hover}; color: {active_fg}; border-color: {hover_border.get(role, "transparent")};')
        rules(':pressed',f'background: {pressed}; color: {active_fg}; border-color: {t.accent_pressed if role == "primary" else hover_border.get(role, "transparent")};')
        rules(':checked',f'background: {t.accent_pressed if role == "primary" else t.accent_tint}; color: {fg if role == "primary" else t.text}; border-color: {t.accent};')
        # Keyboard focus: info ring; on the berry primary a light brand ring
        # reads as focus without clashing with the fill.
        rules(':focus',f'border-color: {t.accent_text if role == "primary" else t.focus};')
        rules(':disabled',f'background: {t.panel if role in {"primary", "secondary"} else "transparent"}; color: {t.disabled}; border-color: {t.border if role in {"primary", "secondary", "danger"} else "transparent"};')
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
