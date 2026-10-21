"""Stylesheet of the redesigned term library page (2026-10-17, v2).

v2 after the user found v1 unbalanced: one accent (the theme's), neutral
surfaces in three steps, hairlines instead of nested boxes, underline tabs
(painted by ``glossary_page_parts.PageTab``), a flat library list and a quiet
table.  Every color is a role of the active theme.  Appended to the window
sheet by ``theme_manager.apply_theme``, so its rules also override the older
page rules in ``main_ui_theme.APP_QSS``.
"""
from __future__ import annotations

from .ui_theme import ThemeDefinition, hex_luminance


def _mix(first: str, second: str, amount: float) -> str:
    a = [int(first.lstrip("#")[index:index + 2], 16) for index in (0, 2, 4)]
    b = [int(second.lstrip("#")[index:index + 2], 16) for index in (0, 2, 4)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(a, b))


def build_glossary_page_qss(theme: ThemeDefinition) -> str:
    t = theme
    hair = _mix(t.surface, t.border, 0.55)
    hover = _mix(t.surface, t.selected, 0.5)
    on_accent = "#ffffff" if hex_luminance(t.accent) < 0.45 else t.app_background
    accent_text = t.accent if t.is_light else _mix(t.accent, "#ffffff", 0.35)
    accent_edge = _mix(t.accent_soft, t.accent, 0.45)
    # A calm fill one step off the card: elevated on dark themes, the input tone on light ones.
    notice = t.input_surface if t.is_light else t.surface_elevated
    return f"""
QLabel#termPageIntro {{ color: {t.text_muted}; font-size: 14px; padding-bottom: 4px; background: transparent; }}
QFrame#termTabBar {{ background: transparent; border: 0; border-bottom: 1px solid {t.border}; }}

QFrame#termLibrarySidebar {{ background: transparent; border: 0; }}
QLineEdit#termSidebarSearch, QLineEdit#termToolSearch, QLineEdit#termHubSearch {{
    background: {t.input_surface}; color: {t.text}; border: 1px solid {t.border}; border-radius: 8px;
    padding: 0 10px; min-height: 32px; font-size: 13px;
}}
QLineEdit#termSidebarSearch:focus, QLineEdit#termToolSearch:focus, QLineEdit#termHubSearch:focus {{ border-color: {t.border_strong}; }}
QListWidget#termGameList {{ background: transparent; border: 0; outline: 0; padding: 0; }}
QListWidget#termGameList::item, QListWidget#termGameList::item:hover, QListWidget#termGameList::item:selected {{
    background: transparent; border: 0;
}}
QFrame#termGameRow {{ background: transparent; border: 0; border-left: 3px solid transparent; border-radius: 8px; }}
QFrame#termGameRow:hover {{ background: {hover}; }}
QFrame#termGameRow[selected="true"] {{ background: {t.selected}; border: 0; border-left: 3px solid {t.accent}; }}
QLabel#termGameRowName {{ color: {t.text}; font-size: 14px; font-weight: 500; background: transparent; }}
QFrame#termGameRow[selected="true"] QLabel#termGameRowName {{ color: {t.text}; font-weight: 600; }}
QLabel#termGameRowCount {{ color: {t.text_muted}; font-size: 12px; font-weight: 400; background: transparent; }}
QFrame#termNewLibrary {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 10px; }}

QFrame#termLibraryContent {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 14px; }}
QFrame#termLibraryContentHeader {{ background: transparent; border: 0; }}
QWidget#termQuickAdd {{ background: transparent; }}
QFrame#termLibraryBody {{ background: transparent; border: 0; border-top: 1px solid {t.border}; }}
QFrame#termLibraryFooter {{
    background: {t.panel}; border: 0; border-top: 1px solid {t.border};
    border-bottom-left-radius: 14px; border-bottom-right-radius: 14px;
}}
QLabel#termLibraryName {{ color: {t.text}; font-size: 21px; font-weight: 700; background: transparent; }}
QLabel#termTypeTag {{
    background: {notice}; color: {t.text_secondary}; border-radius: 6px;
    padding: 1px 8px; font-size: 12px; font-weight: 500;
}}
QLabel#termMeta {{ color: {t.text_muted}; font-size: 13px; font-weight: 400; background: transparent; }}
QLabel#termHint {{ color: {t.text_muted}; font-size: 12px; font-weight: 400; background: transparent; }}
QLabel#termTableTitle {{ color: {t.text_secondary}; font-size: 12px; font-weight: 600; background: transparent; padding-top: 4px; }}

QFrame#termComposer {{ background: {t.input_surface}; border: 1px solid {t.border_strong}; border-radius: 10px; }}
QLineEdit#termComposerInput {{
    background: transparent; border: 0; color: {t.text}; padding: 0 14px; min-height: 42px; font-size: 14px;
}}
QLabel#termComposerArrow {{ color: {t.text_muted}; padding: 0 2px; background: transparent; font-size: 15px; }}
QFrame#termComposerDivider {{ background: {t.border}; border: 0; }}
QComboBox#termComposerCombo {{
    background: transparent; border: 0; color: {t.text_secondary}; padding: 0 10px; min-height: 42px; font-size: 13px;
}}

QPushButton#termAccentButton {{
    background: {t.accent}; color: {on_accent}; border: 0; border-radius: 8px;
    padding: 0 18px; min-height: 34px; font-size: 14px; font-weight: 600;
}}
QPushButton#termAccentButton:hover {{ background: {t.accent_hover}; }}
QPushButton#termAccentButton:pressed {{ background: {t.accent_pressed}; }}
QPushButton#termAccentButton:disabled {{ background: {t.surface_elevated}; color: {t.disabled}; }}
QPushButton#termToolButton, QPushButton#termIconButton {{
    background: transparent; color: {t.text_secondary}; border: 1px solid {t.border}; border-radius: 8px;
    padding: 0 12px; min-height: 32px; font-size: 13px; font-weight: 500;
}}
QPushButton#termIconButton {{ padding: 0; font-size: 16px; }}
QPushButton#termToolButton:hover, QPushButton#termIconButton:hover {{ background: {hover}; color: {t.text}; border-color: {t.border_strong}; }}
QPushButton#termToolButton:disabled, QPushButton#termIconButton:disabled {{ color: {t.disabled}; border-color: {t.border}; background: transparent; }}
QPushButton#termGhostButton {{
    background: transparent; color: {t.text_secondary}; border: 0; border-radius: 8px;
    padding: 0 10px; min-height: 32px; font-size: 13px; font-weight: 500;
}}
QPushButton#termGhostButton:hover {{ background: {hover}; color: {t.text}; }}
QPushButton#termGhostButton:disabled {{ color: {t.disabled}; }}
QPushButton#termLinkButton {{
    background: transparent; color: {accent_text}; border: 0; padding: 2px 6px; font-size: 13px; font-weight: 600;
}}
QPushButton#termLinkButton:hover {{ text-decoration: underline; }}
QPushButton#termLinkButton:disabled {{ color: {t.disabled}; }}
QPushButton#termDangerButton {{
    background: transparent; color: {t.danger}; border: 1px solid {t.danger}; border-radius: 8px;
    padding: 0 12px; min-height: 32px; font-size: 13px; font-weight: 600;
}}
QPushButton#termDangerButton:hover {{ background: {t.danger_soft}; }}
QPushButton#termDangerButton:disabled {{ color: {t.disabled}; border-color: {t.border}; }}
QComboBox#termToolCombo {{
    background: transparent; color: {t.text_secondary}; border: 1px solid {t.border}; border-radius: 8px;
    padding: 0 10px; min-height: 30px; font-size: 13px;
}}
QComboBox#termToolCombo:hover {{ border-color: {t.border_strong}; }}

QFrame#termNotice {{ background: {notice}; border: 0; border-radius: 8px; }}
QFrame#termNotice QLabel {{ background: transparent; color: {t.text}; }}
QFrame#termNotice QLabel#termHint {{ color: {t.text_muted}; }}
QLabel#termNoticeStrong {{ color: {t.text}; font-size: 13px; font-weight: 600; background: transparent; }}
QFrame#termNotice QLabel#termDot {{ background: {t.accent}; border-radius: 4px; }}
QListWidget#termLearningList {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 8px; }}

QTableView#termMappingTable {{
    background: transparent; border: 0; outline: 0; font-size: 14px;
    selection-background-color: {t.selected}; selection-color: {t.text};
}}
QTableView#termMappingTable::item {{ background: transparent; border: 0; border-bottom: 1px solid {hair}; padding: 0 8px; }}
QTableView#termMappingTable::item:hover {{ background: {hover}; }}
QTableView#termMappingTable::item:selected {{ background: {t.selected}; color: {t.text}; }}
QTableView#termMappingTable QHeaderView {{ background: transparent; border: 0; }}
QTableView#termMappingTable QHeaderView::section, QTableView#termMappingTable QTableCornerButton::section {{
    background: transparent; color: {t.text_muted}; border: 0; border-bottom: 1px solid {t.border};
    padding: 0 8px; font-size: 12px; font-weight: 600;
}}
QTableView#termMappingTable QHeaderView::section:hover {{ background: transparent; color: {t.text_secondary}; }}
QLabel#termEmptyTitle {{ color: {t.text}; font-size: 17px; font-weight: 700; background: transparent; }}
QLabel#termEmptyHint {{ color: {t.text_muted}; font-size: 13px; background: transparent; }}
QFrame#termStartCardHub {{ background: {t.accent_soft}; border: 1px solid {accent_edge}; border-radius: 12px; }}
QFrame#termStartCard {{ background: {t.panel}; border: 1px solid {t.border}; border-radius: 12px; }}
QLabel#termStartTitle {{ color: {t.text}; font-size: 16px; font-weight: 700; background: transparent; }}
QLabel#termStartText {{ color: {t.text_secondary}; font-size: 13px; background: transparent; }}
QLabel#termStartPill {{
    background: {t.accent}; color: {on_accent}; border-radius: 9px; padding: 1px 8px; font-size: 12px; font-weight: 600;
}}

QWidget#termHubPanel, QWidget#termHubGrid, QScrollArea#termHubScroll {{ background: transparent; }}
QFrame#termHubCard {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 12px; }}
QFrame#termHubCard:hover {{ border-color: {t.border_strong}; }}
QFrame#termHubAddCard {{ background: transparent; border: 1px dashed {t.border_strong}; border-radius: 12px; }}
QFrame#termHubCard QLabel, QFrame#termHubAddCard QLabel {{ background: transparent; }}
QLabel#termHubCardTitle {{ color: {t.text}; font-size: 16px; font-weight: 700; }}
QLabel#termHubCardNote {{ color: {t.text_secondary}; font-size: 13px; }}
QLabel#termHubCardMeta {{ color: {t.text_muted}; font-size: 12px; }}
QFrame#termHubCardDivider {{ background: {hair}; border: 0; }}
QLabel#termHubPillInstalled {{ color: {t.success}; font-size: 12px; font-weight: 600; }}
QLabel#termHubPillUpdate {{
    background: {t.accent_soft}; color: {accent_text}; border-radius: 6px; padding: 1px 8px; font-size: 12px; font-weight: 600;
}}
QPushButton#termHubAction {{
    background: transparent; color: {t.text}; border: 1px solid {t.border_strong}; border-radius: 8px;
    padding: 0 14px; min-height: 30px; font-size: 13px; font-weight: 600;
}}
QPushButton#termHubAction:hover {{ background: {hover}; }}
QPushButton#termHubAction:disabled {{ color: {t.disabled}; border-color: {t.border}; }}
QPushButton#termHubActionStrong {{
    background: {t.accent}; color: {on_accent}; border: 0; border-radius: 8px;
    padding: 0 14px; min-height: 30px; font-size: 13px; font-weight: 600;
}}
QPushButton#termHubActionStrong:hover {{ background: {t.accent_hover}; }}
QPushButton#termHubQuiet {{
    background: transparent; color: {t.text_muted}; border: 0; border-radius: 8px;
    padding: 0 8px; min-height: 30px; font-size: 13px;
}}
QPushButton#termHubQuiet:hover {{ color: {t.text}; background: {hover}; }}
QPushButton#termHubLink {{ background: transparent; color: {accent_text}; border: 0; padding: 2px 0; font-size: 13px; font-weight: 600; }}
QPushButton#termHubLink:hover {{ text-decoration: underline; }}

QStackedWidget#termSubmitStack, QWidget#termSubmitPage {{ background: transparent; }}
QPushButton#termSubmitLink {{
    background: transparent; color: {accent_text}; border: 0; padding: 0; min-width: 0; min-height: 0;
    font-size: 13px; font-weight: 600; text-align: left;
}}
QPushButton#termSubmitLink:hover {{ text-decoration: underline; }}
QLabel#termSubmitTitle {{ color: {t.text}; font-size: 16px; font-weight: 700; background: transparent; }}
QLabel#termSubmitText {{ color: {t.text_secondary}; font-size: 13px; background: transparent; }}
QLabel#termSubmitStepNumber {{
    background: transparent; color: {t.text_muted}; border: 1px solid {t.border_strong}; border-radius: 10px;
    font-size: 11px; font-weight: 600;
}}
QFrame#termSubmitStep {{ background: transparent; border: 0; }}
QFrame#termSubmitStep[state="on"] QLabel#termSubmitStepNumber {{ background: {t.accent}; color: {on_accent}; border-color: {t.accent}; }}
QFrame#termSubmitStep[state="done"] QLabel#termSubmitStepNumber {{ background: {t.selected}; color: {t.success}; border-color: {t.selected}; }}
QLabel#termSubmitStepText {{ color: {t.text_muted}; font-size: 13px; background: transparent; }}
QFrame#termSubmitStep[state="on"] QLabel#termSubmitStepText {{ color: {t.text}; font-weight: 700; }}
QFrame#termSubmitStep[state="done"] QLabel#termSubmitStepText {{ color: {t.text_secondary}; text-decoration: underline; }}
QFrame#termSubmitStepLine {{ background: {t.border_strong}; border: 0; }}
QFrame#termSubmitLibrary {{ background: {t.panel}; border: 1px solid {t.border}; border-radius: 10px; }}
QFrame#termSubmitLibrary[available="true"]:hover {{ border-color: {t.border_strong}; }}
QFrame#termSubmitLibrary[selected="true"] {{ background: {t.accent_soft}; border-color: {accent_edge}; }}
QFrame#termSubmitLibrary QLabel, QFrame#termSubmitLibrary QRadioButton {{ background: transparent; }}
QRadioButton#termSubmitLibraryName {{ color: {t.text}; font-size: 14px; font-weight: 600; spacing: 8px; }}
QRadioButton#termSubmitLibraryName:disabled {{ color: {t.disabled}; }}
QLabel#termSubmitLibraryMeta {{ color: {t.text_muted}; font-size: 12px; }}
QLabel#termSubmitPill {{ color: {accent_text}; border: 1px solid {accent_edge}; border-radius: 9px; padding: 0 8px; font-size: 12px; }}
QLabel#termSubmitPillQuiet {{ color: {t.text_secondary}; border: 1px solid {t.border_strong}; border-radius: 9px; padding: 0 8px; font-size: 12px; }}
QFrame#termSubmitNotice {{ background: {t.warning_soft}; border: 0; border-radius: 10px; }}
QFrame#termSubmitNotice[level="block"] {{ background: {t.danger_soft}; }}
QFrame#termSubmitNotice QLabel {{ background: transparent; }}
QFrame#termSubmitNotice QLabel#termSubmitNoticeIcon {{
    background: {t.warning}; color: {t.warning_soft}; border-radius: 9px; font-size: 12px; font-weight: 700;
}}
QFrame#termSubmitNotice[level="block"] QLabel#termSubmitNoticeIcon {{ background: {t.danger}; color: {t.danger_soft}; }}
QLabel#termSubmitNoticeText {{ color: {t.text}; font-size: 13px; font-weight: 600; }}
QLabel#termSubmitNoticeMore {{ color: {t.text_secondary}; font-size: 13px; }}
QPushButton#termSubmitChip {{
    background: transparent; color: {t.text_secondary}; border: 1px solid {t.border}; border-radius: 13px;
    padding: 0 12px; min-height: 26px; font-size: 12px;
}}
QPushButton#termSubmitChip:hover {{ border-color: {t.border_strong}; color: {t.text}; }}
QPushButton#termSubmitChip:checked {{ background: {t.selected}; color: {t.text}; border-color: {t.border_strong}; font-weight: 600; }}
QTableView#termSubmitTable {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: 10px; outline: 0; font-size: 13px;
    selection-background-color: {t.selected}; selection-color: {t.text};
}}
QTableView#termSubmitTable::item {{ background: transparent; border: 0; border-bottom: 1px solid {hair}; padding: 0 8px; }}
QTableView#termSubmitTable::item:hover {{ background: {hover}; }}
QTableView#termSubmitTable::item:selected {{ background: {t.selected}; color: {t.text}; }}
QTableView#termSubmitTable QHeaderView {{ background: transparent; border: 0; }}
QTableView#termSubmitTable QHeaderView::section, QTableView#termSubmitTable QTableCornerButton::section {{
    background: {t.panel}; color: {t.text_muted}; border: 0; border-bottom: 1px solid {t.border};
    padding: 4px 8px; font-size: 12px; font-weight: 600;
}}
QLabel#termSubmitStatus {{ color: {t.danger}; font-size: 12px; background: transparent; }}
QFrame#termSubmitSummary {{ background: {t.panel}; border: 1px solid {t.border}; border-radius: 10px; }}
QFrame#termSubmitSummary QLabel {{ background: transparent; }}
QLabel#termSubmitSummaryTitle {{ color: {t.text}; font-size: 14px; font-weight: 700; }}
QLineEdit#termSubmitField, QPlainTextEdit#termSubmitField {{
    background: {t.input_surface}; color: {t.text}; border: 1px solid {t.border_strong}; border-radius: 8px;
    padding: 6px 10px; font-size: 13px;
}}
QLineEdit#termSubmitField:focus, QPlainTextEdit#termSubmitField:focus {{ border-color: {t.focus}; }}
QCheckBox#termSubmitConsent {{ color: {t.text}; font-size: 13px; spacing: 8px; background: transparent; }}

QFrame#termActionPopup {{ background: {t.surface_elevated}; border: 1px solid {t.border_strong}; border-radius: 10px; }}
QPushButton#termPopupItem, QPushButton#termPopupItemDanger {{
    text-align: left; padding: 7px 12px; border: 0; border-radius: 6px;
    background: transparent; color: {t.text}; font-weight: 500;
}}
QPushButton#termPopupItemDanger {{ color: {t.danger}; }}
QPushButton#termPopupItem:hover, QPushButton#termPopupItemDanger:hover {{ background: {t.selected}; }}
QPushButton#termPopupItem:disabled, QPushButton#termPopupItemDanger:disabled {{ color: {t.disabled}; background: transparent; }}
QLabel#termPopupCaption {{ color: {t.text_muted}; font-size: 12px; padding: 4px 8px 0 8px; background: transparent; }}
QFrame#termPopupSeparator {{ background: {t.border}; border: 0; margin: 4px 2px; }}
"""
