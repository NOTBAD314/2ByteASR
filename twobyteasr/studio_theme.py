"""Shared styling for Studio dialogs, menus, tooltips, and popup views."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QCursor, QFontMetrics, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QComboBox,
    QDialog,
    QMenu,
    QMessageBox,
    QStyle,
    QWidget,
)

from .ui_theme import (
    AMBER,
    AMBER_SOFT,
    BACKGROUND,
    BACKGROUND_ALT,
    BORDER,
    BORDER_ACTIVE,
    BORDER_STRONG,
    CORAL,
    GREEN,
    GREEN_HOVER,
    GREEN_PRESSED,
    GREEN_SOFT,
    GREEN_SUBTLE,
    INK,
    MUTED,
    MUTED_LIGHT,
    SURFACE,
    SURFACE_MUTED,
    ThemeDefinition,
    theme_definition,
)
from .qss_retheme import retheme_qss
from .typography import MONO_FONT_STACK, UI_FONT_STACK

from .i18n import bind_text


# Product display name. Internal modules/classes/objectNames stay unchanged.
BRAND_DISPLAY_NAME = "兔白字幕"

# Studio-only semantic surface roles.  Keep these local: the main application
# still owns its existing palette and must not inherit Export/Studio changes.
SURFACE_APP = "#F8F5EE"
SURFACE_PANEL = "#FCFAF6"
SURFACE_CARD = "#FFFDF8"
SURFACE_ELEVATED = "#FFFEFA"
SURFACE_INPUT = "#FFFEFA"
SURFACE_MUTED = "#F0ECE3"
SURFACE_DARK_PREVIEW = "#30332F"
TEXT_PRIMARY = "#292D29"
TEXT_SECONDARY = "#626760"
TEXT_MUTED = "#858981"
BORDER_SOFT = "#D8D0C3"
BORDER_ACTIVE = "#71987A"
ACCENT_GREEN = "#4F825D"
ACCENT_YELLOW = "#B97B20"
ACCENT_BLUE = "#4E7798"
ACCENT_PURPLE = "#79669A"
ACCENT_RED = "#9A4D47"


SECONDARY_SURFACE_QSS = f"""
QDialog, QMessageBox {{ background: {SURFACE_APP}; color: {TEXT_PRIMARY}; }}
QDialog QLabel, QMessageBox QLabel {{ color: {INK}; background: transparent; }}
QMenu {{
    background: {SURFACE}; color: {INK}; border: 1px solid {BORDER};
    border-radius: 6px; padding: 5px;
}}
QMenu::item {{ min-height: 28px; padding: 2px 30px 2px 10px; border-radius: 4px; }}
QMenu::item:selected {{ background: #e2ecdf; color: #213027; }}
QMenu::item:disabled {{ color: #9a978f; background: transparent; }}
QMenu::separator {{ height: 1px; background: #e8e1d6; margin: 5px 7px; }}
QMenu::indicator {{ width: 16px; height: 16px; }}
QToolTip {{
    background: #fffdf8; color: {INK}; border: 1px solid #cfc5b7;
    border-radius: 4px; padding: 5px 7px;
}}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QKeySequenceEdit {{
    background: {SURFACE_INPUT}; color: {TEXT_PRIMARY}; border: 1px solid #d5d1c8;
    border-radius: 6px; min-height: 32px; padding: 0 8px;
    selection-background-color: {GREEN}; selection-color: white;
}}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QKeySequenceEdit:focus {{ border-color: #71987a; }}
QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QKeySequenceEdit:disabled {{ background: #f1eee7; color: #99968e; border-color: #e1ddd5; }}
QComboBox::drop-down {{ border: 0; width: 26px; }}
QAbstractItemView {{
    background: {SURFACE_INPUT}; color: {TEXT_PRIMARY}; border: 1px solid #d5d1c8;
    border-radius: 6px; padding: 4px; outline: 0;
    selection-background-color: #dfeadf; selection-color: #233028;
}}
QAbstractItemView::item {{ min-height: 30px; padding: 2px 8px; border-radius: 4px; }}
QAbstractItemView::item:hover {{ background: #eef2eb; color: {INK}; }}
QAbstractItemView::item:selected {{ background: #dfeadf; color: #233028; }}
QAbstractItemView::item:disabled {{ color: #9a978f; background: transparent; }}
QFrame#fillPickerSurface {{
    background: {SURFACE_ELEVATED}; border: 1px solid {BORDER_SOFT}; border-radius: 10px;
}}
QComboBox#fillModeCombo {{
    min-height: 34px; font-weight: 650; padding: 0 10px;
}}
QPushButton#fillModeButton {{
    background: {SURFACE_INPUT}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_SOFT};
    border-radius: 8px; min-height: 36px; padding: 4px 12px; font-weight: 650;
}}
QPushButton#fillModeButton:hover {{ background: #edf0ea; border-color: {BORDER_ACTIVE}; }}
QPushButton#fillModeButton:pressed {{ background: #dfe5dd; }}
QPushButton#fillModeButton:checked {{
    background: {GREEN}; color: white; border-color: {GREEN}; font-weight: 800;
}}
QLabel#fillFieldLabel {{ color: {TEXT_SECONDARY}; font-weight: 750; font-size: 11px; }}
QWidget#fillNumericFields QLineEdit, QWidget#fillNumericFields QSpinBox {{
    min-height: 22px; max-height: 26px; font-size: 12px; font-weight: 650;
    padding: 0 4px;
}}
QRadioButton#fillChannelRadio {{
    color: {TEXT_PRIMARY}; font-size: 11px; font-weight: 650; spacing: 3px;
    min-height: 22px; max-width: 28px; padding: 0; margin: 0; background: transparent;
}}
QRadioButton#fillChannelRadio::indicator {{
    width: 11px; height: 11px; border-radius: 6px; margin: 0 2px 0 0;
    border: 1px solid #b7b1a6; background: #fffdf9;
}}
QRadioButton#fillChannelRadio::indicator:checked {{
    background: {GREEN}; border-color: {GREEN};
}}
QSlider#fillControlSlider::groove:horizontal {{
    height: 4px; background: #d8d0c3; border-radius: 2px;
}}
QSlider#fillControlSlider::handle:horizontal {{
    width: 12px; height: 12px; margin: -5px 0; border-radius: 6px;
    background: {GREEN}; border: 1px solid #3e714f;
}}
QSlider#fillControlSlider::sub-page:horizontal {{ background: {GREEN}; border-radius: 2px; }}
QToolButton#fillEyedropper {{
    background: #fffdf9; border: 1px solid #d6d0c6; border-radius: 6px;
    min-width: 28px; min-height: 28px; padding: 0;
}}
QToolButton#fillEyedropper:hover {{ background: #edf0ea; border-color: #c8d2c6; }}
QPushButton#fillDeleteStop {{ min-height: 28px; padding: 1px 10px; }}
QFrame#fillEditorRight {{
    background: {SURFACE_CARD}; border: 1px solid {BORDER_SOFT}; border-radius: 12px;
}}
QLabel#styleLayerLabel {{ color: {TEXT_SECONDARY}; font-size: 12px; font-weight: 750; }}
QPushButton {{
    background: #fffdf9; color: {INK}; border: 1px solid #d6d0c6;
    border-radius: 6px; min-height: 32px; padding: 1px 12px; font-weight: 600;
}}
QPushButton:hover {{ background: #edf0ea; border-color: #c8d2c6; }}
QPushButton:pressed {{ background: #dfe5dd; }}
QPushButton:disabled {{ background: #f1eee8; color: #9b9890; border-color: #e1ddd5; }}
QPushButton[studioPrimary="true"] {{ background: {GREEN}; color: white; border-color: #3e714f; }}
QPushButton[studioPrimary="true"]:hover {{ background: {GREEN_HOVER}; }}
QPushButton[studioPrimary="true"]:pressed {{ background: {GREEN_PRESSED}; }}
QPushButton[studioPrimary="true"]:disabled {{ background: #aebbb0; color: #f4f5f2; }}
QTextEdit, QPlainTextEdit {{
    background: {SURFACE_INPUT}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_SOFT};
    border-radius: 7px; padding: 6px; selection-background-color: {ACCENT_GREEN};
    selection-color: white;
}}
QTextEdit:disabled, QPlainTextEdit:disabled {{
    background: {SURFACE_MUTED}; color: {TEXT_MUTED}; border-color: #E1DDD5;
}}
QGroupBox {{
    background: #fcfaf6; color: {INK}; border: 1px solid #e2ddd4;
    border-radius: 6px; margin-top: 10px; padding-top: 8px; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
QProgressBar {{ background: #ece7de; border: 0; border-radius: 4px; min-height: 8px; max-height: 8px; }}
QProgressBar::chunk {{ background: {GREEN}; border-radius: 4px; }}
QScrollBar:vertical {{ background: #eee9df; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #aaa79e; min-height: 28px; border-radius: 4px; }}
QScrollBar::handle:vertical:hover {{ background: #7d867e; }}
QScrollBar:horizontal {{ background: #eee9df; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #aaa79e; min-width: 28px; border-radius: 4px; }}
QScrollBar::handle:horizontal:hover {{ background: #7d867e; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
"""


def _secondary_theme_override(theme: ThemeDefinition) -> str:
    return f"""
QDialog, QMessageBox, QMenu {{ background: {theme.surface}; color: {theme.text}; border-color: {theme.border}; }}
QDialog QLabel, QMessageBox QLabel, QMenu::item {{ color: {theme.text}; }}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QKeySequenceEdit,
QTextEdit, QPlainTextEdit {{ background: {theme.input_surface}; color: {theme.text}; border-color: {theme.border}; }}
QAbstractItemView {{ background: {theme.input_surface}; color: {theme.text}; border-color: {theme.border}; }}
QAbstractItemView::item {{ color: {theme.text}; }}
QAbstractItemView::item:hover {{ background: {theme.surface_elevated}; color: {theme.text}; }}
QAbstractItemView::item:selected, QMenu::item:selected {{ background: {theme.selected}; color: {theme.text}; }}
QAbstractItemView::item:disabled {{ background: transparent; color: {theme.disabled}; }}
QScrollBar:vertical, QScrollBar:horizontal {{ background: {theme.panel}; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{ background: {theme.border_strong}; }}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{ background: {theme.text_muted}; }}
QPushButton {{ background: {theme.surface_elevated}; color: {theme.text}; border-color: {theme.border}; }}
QPushButton:hover {{ background: {theme.selected}; border-color: {theme.accent}; }}
QPushButton[studioPrimary="true"] {{ background: {theme.accent}; color: {theme.text_on_accent}; border-color: {theme.accent}; }}
QDialog#toolDialog {{ background: {theme.surface}; color: {theme.text}; border-radius: 4px; }}
QDialog#toolDialog QGroupBox, QDialog#toolDialog QFrame#findResultFrame {{
    background: {theme.surface_elevated}; color: {theme.text};
    border: 1px solid {theme.border_strong}; border-radius: 4px;
}}
QDialog#toolDialog QLabel#findResultTitle {{ color: {theme.text}; font-weight: 750; }}
QDialog#toolDialog QListWidget#findResultList {{
    background: {theme.input_surface}; color: {theme.text};
    border: 1px solid {theme.border}; border-radius: 4px;
}}
QDialog#toolDialog QListWidget#findResultList::item {{
    padding: 8px 10px; margin: 2px 0; border-radius: 4px;
    background: {theme.surface}; border: 1px solid {theme.border};
}}
QDialog#toolDialog QListWidget#findResultList::item:selected {{
    background: {theme.selected}; border-color: {theme.accent}; color: {theme.text};
}}
QWidget#studioVideoEmptyHost {{ background: {theme.panel}; }}
QFrame#studioVideoDropZone {{
    background: {theme.surface_muted}; border: 2px dashed {theme.border}; border-radius: 8px;
}}
QLabel#studioVideoEmptyHint {{
    color: {theme.text}; background: transparent; padding: 4px 8px;
    font-size: 15px; font-weight: 650;
}}
QLabel#studioVideoEmptyNote {{
    color: {theme.text_muted}; background: transparent; border: 0;
    padding: 2px 6px; font-size: 12px; font-weight: 500;
}}
QLabel#motionLibraryTitle {{ color: {theme.text}; font-size: 18px; font-weight: 750; }}
QFrame#motionCard {{ background: {theme.surface_elevated}; border: 1px solid {theme.border}; border-radius: 9px; }}
QFrame#motionCard:hover {{ border-color: {theme.accent}; }}
QFrame#aiDesignVariant {{ background: {theme.surface_elevated}; border: 1px solid {theme.border}; border-radius: 9px; }}
QFrame#aiDesignVariant:hover {{ border-color: {theme.accent}; }}
QFrame#aiDesignVariant[selected="true"] {{
    border: 2px solid {theme.accent}; background: {theme.accent_soft}; border-radius: 9px;
}}
QLabel#motionCardName {{ background: transparent; color: {theme.text}; font-size: 13px; font-weight: 700; }}
QLabel#motionCardType {{ background: transparent; color: {theme.text_muted}; font-size: 11px; }}
QLabel#motionCardBadge {{
    background: {theme.selected}; color: {theme.text}; border: 1px solid {theme.border_strong};
    border-radius: 8px; padding: 1px 8px; font-size: 10px; font-weight: 650;
}}
QLabel#motionCardBadge[builtIn="false"] {{ background: {theme.accent_soft}; color: {theme.text}; border-color: {theme.accent}; }}
QToolButton#motionCardFavorite, QToolButton#motionCardTool {{
    background: transparent; color: {theme.text_secondary}; border: 0; border-radius: 4px;
    font-size: 13px; padding: 1px 5px;
}}
QToolButton#motionCardFavorite:hover, QToolButton#motionCardTool:hover {{ background: {theme.selected}; color: {theme.text}; }}
QPushButton#motionFilter {{
    background: transparent; color: {theme.text_secondary}; border: 1px solid {theme.border};
    border-radius: 12px; padding: 3px 14px; font-weight: 650;
}}
QPushButton#motionFilter:hover {{ border-color: {theme.accent}; color: {theme.text}; }}
QPushButton#motionFilter:checked {{ background: {theme.accent}; color: {theme.text_on_accent}; border-color: {theme.accent}; }}
"""


def _active_theme(theme: ThemeDefinition | None) -> ThemeDefinition:
    """Resolve the persisted theme when the caller did not pin one."""
    if theme is not None:
        return theme
    from .theme_manager import theme_key

    return theme_definition(theme_key())


# Stylesheet text only depends on the theme key; rebuilds are pure string
# churn that re-polishes nothing but wastes milliseconds on every switch.
_QSS_CACHE: dict[str, str] = {}


def _cached_qss(cache_key: str, build) -> str:
    sheet = _QSS_CACHE.get(cache_key)
    if sheet is None:
        sheet = build()
        _QSS_CACHE[cache_key] = sheet
    return sheet


def studio_status_colors() -> dict[str, tuple[str, str]]:
    """Badge fill/text pairs for cue review states, following the active theme."""
    t = _active_theme(None)
    return {
        "pending": (t.warning_soft, t.warning),
        "issue": (t.danger_soft, t.danger),
        "done": (t.success_soft, t.success),
    }


def build_secondary_surface_qss(theme: ThemeDefinition | None = None) -> str:
    active = _active_theme(theme)
    from .design.control_qss import build_control_qss
    from .design.surface_qss import build_surface_qss
    return _cached_qss(
        f"secondary:{active.key}",
        lambda: retheme_qss(SECONDARY_SURFACE_QSS, active) + _secondary_theme_override(active)
        + build_control_qss(active) + build_surface_qss(active),
    )


def _studio_theme_override(theme: ThemeDefinition) -> str:
    control = theme.input_surface or theme.surface_elevated
    return f"""
QWidget#subtitleStudio {{ background: {theme.app_background}; color: {theme.text}; }}
QFrame#contextPanel {{ background: {theme.panel}; }}
QTabWidget#contextDrawer::pane {{ background: {theme.panel}; border-top: 1px solid {theme.border}; }}
QTabWidget#contextDrawer QTabBar::tab {{
    min-height: 44px; padding: 2px 6px; min-width: 44px; max-width: 92px;
    color: {theme.text_muted}; background: transparent;
}}
QTabWidget#contextDrawer QTabBar::tab:hover {{ background: {theme.selected}; color: {theme.text}; }}
QTabWidget#contextDrawer QTabBar::tab:selected {{
    color: {theme.accent}; font-weight: 700; border-bottom: 2px solid {theme.accent};
}}
QTabWidget#contextDrawer[tabMode="icon"] QTabBar::tab {{
    min-width: 44px; max-width: 44px; min-height: 44px; padding: 0;
}}
QFrame#styleSection {{ background: {theme.surface}; border: 1px solid {theme.border}; }}
QToolButton#styleSectionHeader {{ color: {theme.text}; }}
QLabel#styleFieldLabel {{ color: {theme.text_muted}; }}



QFrame#styleSection QComboBox, QFrame#styleSection QSpinBox, QFrame#styleSection QDoubleSpinBox,
QFrame#styleSection QLineEdit, QFrame#styleSection QToolButton#styleColorButton {{
    background: {control}; color: {theme.text}; border: 1px solid {theme.border_strong};
}}
QFrame#styleSection QComboBox:hover, QFrame#styleSection QSpinBox:hover,
QFrame#styleSection QDoubleSpinBox:hover, QFrame#styleSection QLineEdit:hover,
QFrame#styleSection QToolButton#styleColorButton:hover {{
    background: {theme.selected}; border-color: {theme.accent};
}}
QFrame#styleSection QComboBox:focus, QFrame#styleSection QSpinBox:focus,
QFrame#styleSection QDoubleSpinBox:focus, QFrame#styleSection QLineEdit:focus {{
    border-color: {theme.accent}; background: {control};
}}
QSpinBox, QDoubleSpinBox {{ background: {control}; color: {theme.text}; border: 1px solid {theme.border_strong}; }}






QFrame#studioToolbar {{ background: {theme.shell}; border-color: {theme.shell_border}; }}
QFrame#studioToolbar[hubMode="true"] {{ background: {theme.shell}; border-color: {theme.shell_border}; }}
QFrame#studioTeachBanner, QFrame#cueListPanel, QFrame#cueEditor, QFrame#contextCard {{
	    background: {theme.surface_muted}; color: {theme.text}; border-color: {theme.border};
	}}
QFrame#videoSurface, QWidget#videoSurface {{ background: {theme.media}; }}
QLabel#studioVideoEmptyHint {{
    color: {theme.text}; background: transparent; border: 0;
    padding: 4px 8px; font-size: 15px; font-weight: 650;
}}
QLabel#studioVideoEmptyNote {{
    color: {theme.text_muted}; background: transparent; border: 0;
    padding: 2px 6px; font-size: 12px; font-weight: 500;
}}
QFrame#timelineHost {{ background: {theme.timeline_background}; border-color: {theme.timeline_grid}; }}
QTableView#cueTable {{ background: {theme.surface}; alternate-background-color: {theme.panel};
    color: {theme.text}; border-color: {theme.border}; selection-background-color: {theme.selected}; }}
QHeaderView::section {{ background: {theme.panel}; color: {theme.text_muted}; border-color: {theme.border}; }}
QLineEdit#cueSearch, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit#cueText {{
    background: {theme.input_surface}; color: {theme.text}; border-color: {theme.border};
    selection-background-color: {theme.accent};
}}
QLabel#sectionTitle, QLabel#fieldLabel, QLabel#cardTitle, QLabel#contextValue,
QLabel#styleSectionHeader, QLabel#stylePanelHeaderTitle {{ color: {theme.text}; }}
QLabel#styleSectionHint, QLabel#stylePanelHeaderMeta, QLabel#fieldLabel,
QLabel#cardMeta, QLabel#projectLibrarySubtitle {{ color: {theme.text_muted}; }}
QToolButton#studioTool, QPushButton#studioButton {{ color: {theme.text}; border-color: transparent; }}
QToolButton#studioTool:hover, QPushButton#studioButton:hover {{ background: {theme.selected}; border-color: {theme.accent}; }}
QPlainTextEdit#aiStreamConsole {{
    background: {theme.app_background}; color: {theme.accent};
    border: 1px solid {theme.border_strong}; border-radius: 6px;
    font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 11px;
    padding: 6px;
}}
QPushButton#studioPrimary {{ background: {theme.accent}; border-color: {theme.accent}; color: {theme.text_on_accent}; }}
QPushButton#studioPrimary:hover {{ background: {theme.accent_hover}; border-color: {theme.accent_hover}; }}
QPushButton#studioPrimary:pressed {{ background: {theme.accent_pressed}; border-color: {theme.accent_pressed}; }}
QFrame#studioEmptyState, QScrollArea#projectLibraryScroll, QWidget#projectLibraryViewport,
QWidget#projectLibraryPage, QWidget#projectGridHost, QWidget#projectListHost {{
    background: {theme.app_background}; color: {theme.text};
}}
QLabel#projectLibraryBrand {{ color: {theme.text}; font-size: 32px; font-weight: 850; }}
QLabel#projectLibraryBrand, QLabel#projectLibraryTitle, QLabel#projectLibrarySectionTitle,
QLabel#resumeProjectTitle, QLabel#projectCardTitle, QLabel#projectListTitle {{ color: {theme.text}; }}
QToolButton#studioWindowControl, QToolButton#studioWindowControlClose {{
    background: transparent; color: {theme.text}; border: 0; border-radius: 6px;
}}
QToolButton#studioWindowControl:hover {{ background: {theme.selected}; color: {theme.text}; }}
QToolButton#studioWindowControl:pressed {{ background: {theme.border}; color: {theme.text}; }}
QToolButton#studioWindowControl:disabled {{ color: {theme.disabled}; }}
QToolButton#studioWindowControlClose:hover {{ background: {theme.danger}; color: #ffffff; }}
QToolButton#studioWindowControlClose:pressed {{ background: {theme.danger}; color: #ffffff; }}
QPushButton#projectLibraryHome {{
    background: transparent; color: {theme.text}; border: 1px solid {theme.border};
    border-radius: 8px; padding: 6px 12px; font-size: 13px; font-weight: 650;
}}
QPushButton#projectLibraryHome:hover {{ background: {theme.selected}; border-color: {theme.accent}; }}
QLabel#projectLibraryBrandMeta, QLabel#projectLibrarySubtitle, QLabel#resumeProjectMeta,
QLabel#projectCardMeta, QLabel#projectListMeta {{ color: {theme.text_muted}; }}
QLabel#projectLibraryEyebrow, QLabel#resumeProjectEyebrow {{ color: {theme.accent}; }}
QFrame#resumeProjectCard, QFrame#projectCard,
QToolButton#projectListRow, QFrame#projectCardMedia {{ background: {theme.surface}; border-color: {theme.border}; }}
QToolButton#projectListRow:hover {{ background: {theme.surface_elevated}; border-color: {theme.accent}; }}
QLabel#projectListTitle {{ color: {theme.text}; }}
QComboBox#projectSort {{ background: {theme.input_surface}; color: {theme.text}; border-color: {theme.border_strong}; }}
QComboBox#projectSort:hover {{ border-color: {theme.accent}; }}
QLineEdit#projectLibrarySearch {{ background: {theme.input_surface}; color: {theme.text}; border-color: {theme.border_strong}; }}
QLineEdit#projectLibrarySearch:focus {{ border-color: {theme.accent}; }}
QFrame#projectViewSwitcher {{ background: {theme.panel}; border-color: {theme.border}; }}
QFrame#resumeProjectPreview {{ background: transparent; border: 0; }}
QLabel#resumeProjectPreviewImage, QLabel#projectCardCover {{ background: {theme.media}; }}
QToolButton#projectViewButton {{ color: {theme.text_muted}; }}
QToolButton#projectViewButton:hover, QToolButton#projectViewButton:checked {{
    background: {theme.selected}; color: {theme.text}; border-color: {theme.accent};
}}
QPushButton#hubPrimary, QPushButton#projectCardOpen {{ color: {theme.text_on_accent}; font-weight: 600; }}
QPushButton#hubPrimary {{ background: {theme.accent}; border-color: {theme.accent}; }}
QPushButton#hubPrimary:hover {{ background: {theme.accent_hover}; border-color: {theme.accent_hover}; }}
QPushButton#projectCardOpen {{ background: {theme.accent}; border-color: {theme.accent}; color: {theme.text_on_accent}; }}
QPushButton#projectCardOpen:hover {{ background: {theme.accent_hover}; border-color: {theme.accent_hover}; color: {theme.text_on_accent}; }}
QPushButton#hubSecondary {{ color: {theme.accent}; border-color: {theme.border}; }}
QPushButton#hubSecondary:hover {{ background: {theme.selected}; border-color: {theme.accent}; }}
QLabel#projectCardStatus {{ background: {theme.selected}; color: {theme.text}; border-color: {theme.border}; }}
QFrame#highlightCandidateCard {{
    background: {theme.surface}; border: 1px solid {theme.border}; border-radius: 7px;
}}
QLabel#highlightGrade {{
    background: {theme.accent_soft}; color: {theme.accent}; border: 1px solid {theme.accent};
    border-radius: 5px; padding: 3px 7px; font-weight: 800;
}}
QLabel#highlightTitle {{ color: {theme.text}; font-size: 14px; font-weight: 800; }}
QLabel#highlightReason {{ color: {theme.text}; font-size: 13px; }}
QLabel#highlightEvidence {{ color: {theme.text_secondary}; font-size: 13px; background: {theme.panel}; border-radius: 5px; padding: 6px; }}
QLabel#highlightDetails {{ color: {theme.text_muted}; padding-top: 4px; }}
QWidget#highlightAssistant {{ background: transparent; }}
/* 五十二轮（用户反馈）：剪辑 tab 曾用 surface_elevated（warm=纯白）+radius 6
   的孤立卡片系统，与相邻 tab 不是一个视觉体系。统一到 t.surface+radius 12
   分组卡（对齐视频 tab 的 videoInspectorSection 语言）。选择器挂上
   QFrame#contextPanel 以压过 surface_qss 的同名扁平规则（同特异度时后拼
   接者胜）。 */
QFrame#contextPanel QWidget#highlightAssistant QGroupBox {{
    background: {theme.surface}; color: {theme.text};
    border: 1px solid {theme.border}; border-radius: 12px; margin-top: 16px;
}}
QFrame#contextPanel QWidget#highlightAssistant QGroupBox::title {{
    color: {theme.text}; background: {theme.surface}; subcontrol-origin: margin;
    left: 12px; padding: 0 5px;
}}
QFrame#contextPanel QWidget#highlightAssistant QLabel {{ color: {theme.text_secondary}; }}
QFrame#contextPanel QWidget#highlightAssistant QLabel#sectionTitle,
QFrame#contextPanel QWidget#highlightAssistant QLabel#highlightTitle {{ color: {theme.text}; }}
QFrame#contextPanel QWidget#highlightAssistant QComboBox,
QFrame#contextPanel QWidget#highlightAssistant QSpinBox,
QFrame#contextPanel QWidget#highlightAssistant QDoubleSpinBox {{
    background: {theme.surface_input}; color: {theme.text}; border-color: {theme.border};
    selection-background-color: {theme.accent};
}}
QFrame#contextPanel QWidget#highlightAssistant QPushButton#studioButton {{
    background: {theme.surface}; color: {theme.text}; border: 1px solid {theme.border};
}}
QFrame#contextPanel QWidget#highlightAssistant QPushButton#studioButton:hover {{
    background: {theme.selected}; border-color: {theme.accent};
}}
"""


def build_studio_qss(theme: ThemeDefinition | None = None) -> str:
    active = _active_theme(theme)
    from .design.control_qss import build_control_qss
    from .design.surface_qss import build_surface_qss
    from .design.studio_qss import build_studio_component_qss

    return _cached_qss(
        f"studio:{active.key}:p9a",
        lambda: retheme_qss(STUDIO_QSS, active) + _studio_theme_override(active) + build_control_qss(active) + build_surface_qss(active) + build_studio_component_qss(active),
    )


def apply_secondary_surface_theme(widget: QWidget) -> QWidget:
    """Apply the Studio popup/dialog theme at the top-level ownership boundary."""
    from .design.presentation import prepare_controls
    prepare_controls(widget)
    widget._secondary_theme_surface = True
    refresh_secondary_surface_theme(widget)
    return widget


def refresh_secondary_surface_theme(widget: QWidget) -> None:
    """Refresh a reused popup before paint, without reclassifying its controls."""
    active = _active_theme(None)
    if getattr(widget, "_secondary_theme_key", None) != active.key:
        widget._secondary_theme_key = active.key
        widget.setStyleSheet(build_secondary_surface_qss(active))


def create_studio_menu(parent: QWidget | None = None) -> QMenu:
    menu = QMenu(parent)
    apply_secondary_surface_theme(menu)
    menu.aboutToShow.connect(lambda: refresh_secondary_surface_theme(menu))
    return menu


class StudioComboBox(QComboBox):
    """A consistently sized and themed popup across Windows DPI settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaxVisibleItems(12)
        self.view().setUniformItemSizes(True)
        self.view().setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.refresh_theme_palette()

    def refresh_theme_palette(self) -> None:
        from .theme_manager import theme_key

        theme = theme_definition(theme_key())
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor(theme.input_surface))
        palette.setColor(QPalette.ColorRole.Button, QColor(theme.input_surface))
        palette.setColor(QPalette.ColorRole.Window, QColor(theme.input_surface))
        palette.setColor(QPalette.ColorRole.Text, QColor(theme.text))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(theme.text))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(theme.selected))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(theme.text))
        palette.setColor(QPalette.ColorRole.Link, QColor(theme.accent))
        palette.setColor(QPalette.ColorRole.BrightText, QColor(theme.text_on_accent))
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.Text,
            QColor(theme.disabled),
        )
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.ButtonText,
            QColor(theme.disabled),
        )
        self.setPalette(palette)
        self.view().setPalette(palette)
        if self.lineEdit() is not None:
            self.lineEdit().setPalette(palette)

    def showPopup(self) -> None:
        metrics = QFontMetrics(self.view().font())
        content_width = max(
            (metrics.horizontalAdvance(self.itemText(index)) for index in range(self.count())),
            default=0,
        )
        scrollbar = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        self.view().setMinimumWidth(max(self.width(), content_width + scrollbar + 34))
        self.refresh_theme_palette()
        apply_secondary_surface_theme(self.view())
        popup = self.view().window()
        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        popup.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
        popup.setAutoFillBackground(True)
        popup_palette = popup.palette()
        popup_palette.setColor(QPalette.ColorRole.Window, self.palette().color(QPalette.ColorRole.Base))
        popup_palette.setColor(QPalette.ColorRole.Base, self.palette().color(QPalette.ColorRole.Base))
        popup.setPalette(popup_palette)
        super().showPopup()
        popup = self.view().window()
        # Mutating native flags after show destroys/recreates the popup HWND,
        # which caused a visible flash and a mostly transparent paint surface.
        screen = QApplication.screenAt(QCursor.pos()) or self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            below = self.mapToGlobal(QPoint(0, self.height()))
            above = self.mapToGlobal(QPoint(0, 0))
            height = popup.height()
            x = min(max(available.left(), below.x()), available.right() - popup.width() + 1)
            if available.bottom() - below.y() + 1 >= height:
                popup.move(x, below.y())
            elif above.y() - available.top() >= height:
                popup.move(x, above.y() - height)

    def wheelEvent(self, event) -> None:
        if self.hasFocus() or self.view().isVisible():
            super().wheelEvent(event)
            return
        event.ignore()

    def setCurrentText(self, text: str) -> None:
        index = self.findText(text)
        if index < 0:
            wanted = str(text).strip().lower()
            index = next(
                (
                    item
                    for item in range(self.count())
                    if str(self.itemData(item) or "").strip().lower() == wanted
                ),
                -1,
            )
        if index >= 0:
            self.setCurrentIndex(index)


def studio_message_box(
    parent: QWidget | None,
    icon: QMessageBox.Icon,
    title: str,
    text: str,
    buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
    default_button: QMessageBox.StandardButton = QMessageBox.StandardButton.NoButton,
) -> QMessageBox.StandardButton:
    from .i18n import bind_text
    box = QMessageBox(icon, str(title), str(text), buttons, parent)
    bind_text(box, title, property="windowTitle")
    bind_text(box, text)
    apply_secondary_surface_theme(box)
    if default_button != QMessageBox.StandardButton.NoButton:
        box.setDefaultButton(default_button)
    return QMessageBox.StandardButton(box.exec())


STUDIO_ACCENT = GREEN
STUDIO_ACCENT_SOFT = GREEN_SOFT
STUDIO_BORDER = BORDER
STUDIO_BORDER_SOFT = BORDER_STRONG
STUDIO_SURFACE = SURFACE
STUDIO_MUTED = MUTED
STUDIO_WARNING = AMBER
STUDIO_ERROR = CORAL
STUDIO_RADIUS = 6
STYLE_INPUT_SURFACE = "#fffefa"
STYLE_FIELD_HEIGHT = 38
STYLE_FIELD_RADIUS = 5
MIN_CUE_DURATION_MS = 50

# Project Hub visual tokens.  The Hub is the first surface to adopt the
# selected Plum / Coral direction; keeping the values here makes the layout
# independent from concrete color literals and leaves room for the later
# application-wide theme registry.
HUB_BACKGROUND = "#2b202e"
HUB_SURFACE = "#4b354c"
HUB_SURFACE_ELEVATED = "#60465d"
HUB_SURFACE_CARD = "#6a4b63"
HUB_SURFACE_MUTED = "#3b2a3d"
HUB_INPUT = "#563f57"
HUB_SELECTED = "#795978"
HUB_BORDER = "#82647e"
HUB_TEXT = "#fff5f1"
HUB_TEXT_MUTED = "#d1bfcb"
HUB_TEXT_SUBTLE = "#a990a7"
HUB_CORAL = "#f47c68"
HUB_CORAL_HOVER = "#ff927c"
HUB_CORAL_PRESSED = "#dd6957"
HUB_SUCCESS = "#90c6a0"
HUB_WARNING = "#f1bf73"

MOTION_UI_PRESETS = {
    "none": {"entry": "none", "exit": "none", "duration": 180, "out": 140, "strength": "low", "curve": "soft"},
    "soft_dialogue": {"entry": "soft_fade", "exit": "soft_fade", "duration": 180, "out": 140, "strength": "low", "curve": "soft"},
    "game_energy": {"entry": "punch", "exit": "soft_fade", "duration": 150, "out": 120, "strength": "medium", "curve": "snappy"},
    "quick_pop": {"entry": "soft_pop", "exit": "soft_fade", "duration": 140, "out": 120, "strength": "medium", "curve": "snappy"},
    "light_float": {"entry": "float_up", "exit": "soft_fade", "duration": 210, "out": 150, "strength": "low", "curve": "soft"},
    "emphasis": {"entry": "emphasis", "exit": "soft_fade", "duration": 180, "out": 130, "strength": "medium", "curve": "snappy"},
    "word_highlight": {"entry": "karaoke_highlight", "exit": "soft_fade", "duration": 180, "out": 140, "strength": "low", "curve": "soft"},
}


from .studio_shortcuts import STUDIO_COMMANDS
STUDIO_MEDIA_SUFFIXES = {".mp4", ".mkv", ".mov", ".webm", ".flv", ".avi", ".wav", ".mp3", ".m4a", ".flac", ".aac"}

STUDIO_QSS = f"""
QWidget#subtitleStudio {{ background: {BACKGROUND}; color: {INK}; font-size: 13px; }}
QFrame#studioToolbar {{ background: {STUDIO_SURFACE}; border-bottom: 1px solid {STUDIO_BORDER}; }}
QFrame#studioToolbar[hubMode="true"] {{ background: {HUB_BACKGROUND}; border-bottom: 1px solid {HUB_BORDER}; }}
QFrame#studioToolbar[hubMode="true"] QLabel#studioFilename {{ color: {HUB_TEXT}; }}
QFrame#studioToolbar[hubMode="true"] QLabel#studioSaveState {{ color: {HUB_TEXT_MUTED}; }}
QFrame#studioToolbar[hubMode="true"] QToolButton#studioTool {{ color: {HUB_TEXT_MUTED}; border-color: transparent; }}
QFrame#studioToolbar[hubMode="true"] QToolButton#studioTool:hover {{ background: {HUB_SELECTED}; color: {HUB_TEXT}; border-color: {HUB_CORAL}; }}
QLabel#studioFilename {{ font-size: 15px; font-weight: 700; }}
QLabel#studioSaveState {{ color: {STUDIO_MUTED}; font-size: 12px; }}
QFrame#toolbarDivider {{ background: {BORDER}; min-width: 1px; max-width: 1px; min-height: 22px; max-height: 22px; }}
QToolButton#studioTool, QPushButton#studioButton {{
    background: {GREEN_SUBTLE}; border: 1px solid {BORDER}; border-radius: {STUDIO_RADIUS}px;
    min-height: 34px; padding: 1px 9px; color: {INK}; font-weight: 600;
}}
QToolButton#studioTool:hover, QPushButton#studioButton:hover {{ background: {GREEN_SUBTLE}; border-color: {BORDER_ACTIVE}; }}
QToolButton#studioTool:pressed, QPushButton#studioButton:pressed {{ background: {GREEN_SOFT}; }}
QToolButton#studioTool:focus, QPushButton#studioButton:focus {{ border-color: {BORDER_ACTIVE}; }}
QToolButton#studioTool:disabled, QPushButton#studioButton:disabled {{ color: {MUTED_LIGHT}; background: transparent; border-color: transparent; }}
QPushButton#studioPrimary {{
    background: {STUDIO_ACCENT}; color: white; border: 1px solid #3e714f; border-radius: {STUDIO_RADIUS}px;
    min-height: 34px; padding: 1px 14px; font-weight: 700;
}}
QPushButton#studioPrimary:hover {{ background: {GREEN_HOVER}; }}
QPushButton#studioPrimary:pressed {{ background: {GREEN_PRESSED}; }}
QPushButton#studioPrimary:disabled {{ background: #aebbb0; border-color: #aebbb0; color: #f4f5f2; }}
QFrame#videoSurface {{ background: #151716; border: 0; }}
QFrame#playbackBar {{ background: #181b19; border-top: 1px solid #303430; color: white; }}
QFrame#playbackBar QToolButton {{ min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; padding: 0; }}
QFrame#cueEditor, QFrame#cueListPanel {{ background: {SURFACE}; border: 0; }}
QFrame#contextPanel {{ background: {SURFACE_MUTED}; border: 0; }}
QLabel#sectionTitle {{ font-family: {UI_FONT_STACK}; font-size: 14px; font-weight: 600; color: #252a27; }}
QLabel#fieldLabel {{ color: #6b736e; font-size: 12px; font-weight: 600; }}
QLabel#timelineTimecode {{ color: #39453e; font-family: {MONO_FONT_STACK}; font-weight: 700; font-size: 13px; }}
/* 五十二轮：时间码是编辑器高频读数——tabular 等宽、清晰但不抢播放主视觉。
   当前时间（可输入 chip）+ 总时长（muted）构成信息层级。 */




QPlainTextEdit#cueText {{
    background: #fffefa; border: 1px solid #cbd2c9; border-radius: {STUDIO_RADIUS}px;
    padding: 9px; selection-background-color: {STUDIO_ACCENT}; font-size: 15px;
}}
QPlainTextEdit#cueText:focus {{ border: 1px solid #709a78; }}
QFrame#timelineHost {{ background: {BACKGROUND_ALT}; border-top: 1px solid {BORDER_STRONG}; }}
QTabWidget#contextDrawer::pane {{ border: 0; border-top: 1px solid {BORDER}; background: {SURFACE_MUTED}; }}
QTabWidget#contextDrawer QTabBar::tab {{ min-height: 36px; padding: 4px 8px; min-width: 56px; color: #555d58; background: transparent; }}
QTabWidget#contextDrawer QTabBar::tab:hover {{ background: #f1f2ed; }}
QTabWidget#contextDrawer QTabBar::tab:selected {{ color: #2f7349; font-weight: 700; border-bottom: 2px solid #4f8a61; }}
QTableView#cueTable {{ background: {SURFACE}; alternate-background-color: #fcfaf6; border: 1px solid {BORDER}; gridline-color: transparent; selection-background-color: {GREEN_SOFT}; selection-color: {INK}; outline: 0; }}
QTableView#cueTable::item {{ padding: 6px 4px; border-bottom: 1px solid #eee8de; }}
QTableView#cueTable::item:hover {{ background: #f5f1e9; }}
QTableView#cueTable::item:selected {{ background: {GREEN_SOFT}; color: {INK}; }}
QTableView#cueTable:focus {{ border-color: {BORDER_ACTIVE}; }}
QHeaderView::section {{ background: #f6f3ed; color: #5f6861; border: 0; border-bottom: 1px solid #e0dbd1; padding: 8px 4px; font-weight: 600; }}
QPushButton#filterChip {{ background: #faf8f3; border: 1px solid #e0dbd1; border-radius: {STUDIO_RADIUS}px; min-height: 34px; padding: 1px 9px; color: #4b514d; }}
QPushButton#filterChip:hover {{ background: #f0f2ec; border-color: #d2d9d0; }}
QPushButton#filterChip:checked {{ background: {STUDIO_ACCENT_SOFT}; border-color: #b9cfbb; color: #27623e; font-weight: 700; }}
QPushButton#reviewEntryButton {{ background: #e2eee2; color: #2f6b42; border: 1px solid #9bbd9e; border-radius: 6px; min-height: 32px; padding: 1px 10px; font-weight: 700; }}
QPushButton#reviewEntryButton:hover {{ background: #d4e8d5; border-color: #6e9b73; }}
QPushButton#reviewEntryButton:pressed {{ background: #c5dec8; }}
QLineEdit#cueSearch, QComboBox, QSpinBox, QDoubleSpinBox {{ background: {STYLE_INPUT_SURFACE}; color: {INK}; border: 1px solid #d5d1c8; border-radius: {STUDIO_RADIUS}px; min-height: 32px; padding: 0 8px; selection-background-color: {STUDIO_ACCENT}; }}
QLineEdit#cueSearch:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: #71987a; }}
QWidget#studioMediaPoolPanel {{ background: {SURFACE_MUTED}; }}
QLabel#mediaPoolMeta {{ color: {STUDIO_MUTED}; font-size: 11px; }}
QLabel#mediaPoolPreviewContract {{ color: {STUDIO_MUTED}; background: {GREEN_SUBTLE}; border: 1px solid {BORDER}; border-radius: {STUDIO_RADIUS}px; padding: 6px 8px; font-size: 11px; }}


QTreeWidget#mediaPoolAssets {{ background: {SURFACE}; color: {INK}; border: 1px solid {BORDER}; border-radius: {STUDIO_RADIUS}px; outline: 0; }}
QTreeWidget#mediaPoolAssets::item {{ min-height: 34px; padding: 2px 4px; border-bottom: 1px solid #eee8de; }}
QTreeWidget#mediaPoolAssets::item:hover {{ background: #f5f1e9; }}
QTreeWidget#mediaPoolAssets::item:selected {{ background: {GREEN_SOFT}; color: {INK}; }}
QFrame#mediaPoolDivider {{ color: {BORDER}; }}
QComboBox#mediaPoolTrackSelector {{ min-height: 34px; }}
QFrame#contextCard {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {STUDIO_RADIUS}px; }}
QFrame#styleSection {{ background: #fffaf2; border: 1px solid #e5ddd0; border-radius: 8px; padding: 2px; }}
QToolButton#styleSectionHeader {{ background: transparent; border: 0; min-height: 24px; max-height: 26px; padding: 0; color: #303732; font-weight: 700; text-align: left; }}
QToolButton#styleSectionHeader:hover {{ color: #2f7349; }}
QLabel#styleSectionHint {{ color: #7b817b; font-size: 11px; padding: 0 0 2px 22px; }}
QLabel#styleFieldLabel {{ color: #68716a; font-size: 11px; font-weight: 600; }}
QFrame#stylePanelHeader {{ background: transparent; border: 0; border-bottom: 1px solid {BORDER}; border-radius: 0; }}
QLabel#stylePanelHeaderTitle {{ color: #2f5f3b; font-size: 12px; font-weight: 800; }}
QLabel#stylePanelHeaderMeta {{ color: #6d756e; font-size: 11px; }}















QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0px; border: 0; }}
QSpinBox, QDoubleSpinBox {{ padding-right: 8px; background: #fffaf2; }}
QFrame#styleSection QComboBox, QFrame#styleSection QSpinBox, QFrame#styleSection QDoubleSpinBox,
QFrame#styleSection QLineEdit, QFrame#styleSection QToolButton#styleColorButton {{
    background: {STYLE_INPUT_SURFACE}; color: {INK}; border: 1px solid #d5d1c8;
    border-radius: {STYLE_FIELD_RADIUS}px; min-height: {STYLE_FIELD_HEIGHT - 2}px;
    max-height: {STYLE_FIELD_HEIGHT - 2}px; padding: 0 8px;
}}
QFrame#styleSection QComboBox:focus, QFrame#styleSection QSpinBox:focus,
QFrame#styleSection QDoubleSpinBox:focus, QFrame#styleSection QLineEdit:focus,
QFrame#styleSection QToolButton#styleColorButton:hover {{ border-color: #71987a; }}
QLabel#cardTitle {{ color: #343a36; font-size: 13px; font-weight: 700; }}
QLabel#cardMeta {{ color: {STUDIO_MUTED}; font-size: 12px; }}
QPlainTextEdit#contextText {{ background: transparent; border: 0; padding: 1px; selection-background-color: {STUDIO_ACCENT}; }}
QLabel#contextValue {{ color: #343a36; padding: 2px 0; }}
QLabel#contextEmpty {{ color: {MUTED}; padding: 10px 2px; }}
QLabel#checkPass {{ color: {GREEN}; background: {GREEN_SUBTLE}; border-radius: 4px; padding: 7px 8px; }}
QLabel#checkWarning {{ color: #8a622c; background: {AMBER_SOFT}; border-radius: 4px; padding: 7px 8px; }}
QLabel#checkBlocking {{ color: #955247; background: #f7e8e3; border-radius: 4px; padding: 7px 8px; }}
QRadioButton#scopeOption {{ color: #566058; spacing: 0; min-height: 28px; padding: 4px 9px; border: 1px solid #d8d2c8; border-radius: 5px; background: #fffefa; }}
QRadioButton#scopeOption::indicator {{ width: 0px; height: 0px; margin: 0px; }}
QRadioButton#scopeOption:hover {{ color: {GREEN_HOVER}; border-color: #a9c0ac; background: #f8faf5; }}
QRadioButton#scopeOption:checked {{ color: #27623e; border-color: #76a080; background: #e1eee1; font-weight: 700; }}
QRadioButton#scopeOption:focus {{ color: {GREEN}; border-color: {GREEN}; }}
QCheckBox {{ color: {INK}; spacing: 6px; padding: 2px 0; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid #cfc5b7; border-radius: 4px; background: #fffdf8; }}
QCheckBox::indicator:hover {{ border-color: #71987a; background: #f3f7f0; }}
QCheckBox::indicator:checked {{ border-color: #71987a; background: #71987a; image: none; }}
QCheckBox:focus {{ color: #365b3e; }}
QWidget#stylePreview {{ background: #343a38; border: 1px solid #5e6963; border-radius: 5px; }}
QFrame#panelDivider {{ background: #e3ded5; min-height: 1px; max-height: 1px; }}
QScrollArea#contextScroll, QScrollArea#contextScroll QWidget#qt_scrollarea_viewport {{ background: {SURFACE_MUTED}; border: 0; }}
QWidget#contextViewport, QWidget#contextContent {{ background: {SURFACE_MUTED}; }}
QSplitter::handle {{ background: #ddd8ce; }}
QSplitter::handle:hover {{ background: #9eb8a2; }}
QScrollBar#timelineHorizontalScroll:horizontal {{ background: #e4dac9; height: 16px; margin: 1px 0; }}
QScrollBar#timelineHorizontalScroll::handle:horizontal {{ background: #9d9a8f; min-width: 36px; border-radius: 4px; margin: 2px; }}
QScrollBar#timelineHorizontalScroll::handle:horizontal:hover {{ background: #777f77; }}
QScrollBar#timelineTrackScroll:vertical {{ background: #e4dac9; width: 14px; }}
QScrollBar#timelineTrackScroll::handle:vertical {{ background: #a6a094; min-height: 28px; border-radius: 4px; margin: 2px; }}
QScrollBar#timelineHorizontalScroll::add-line, QScrollBar#timelineHorizontalScroll::sub-line,
QScrollBar#timelineTrackScroll::add-line, QScrollBar#timelineTrackScroll::sub-line {{ width: 0; height: 0; }}
QToolTip {{ background: #fffdf8; color: {INK}; border: 1px solid #cfc5b7; border-radius: 4px; padding: 5px 7px; }}
QFrame#studioWindowControls {{ background: transparent; border: 0; }}
QToolButton#studioWindowControl, QToolButton#studioWindowControlClose {{
    background: transparent; color: {INK}; border: 0; border-radius: 6px;
    min-width: 28px; max-width: 28px; min-height: 26px; max-height: 26px; padding: 0;
}}
QToolButton#studioWindowControl:hover {{ background: #e9eee7; }}
QToolButton#studioWindowControl:pressed {{ background: #e3ddd1; }}
QToolButton#studioWindowControlClose:hover {{ background: {CORAL}; color: #ffffff; }}
QToolButton#studioWindowControlClose:pressed {{ background: {CORAL}; color: #ffffff; }}

/* Project Library / Plum Hub */
QFrame#studioEmptyState {{ background: {HUB_BACKGROUND}; color: {HUB_TEXT}; border: 0; }}
QScrollArea#projectLibraryScroll, QWidget#projectLibraryViewport,
QWidget#projectLibraryPage, QWidget#projectGridHost, QWidget#projectListHost {{
    background: transparent; color: {HUB_TEXT}; border: 0;
}}
QFrame#projectLibraryHeader {{ background: transparent; border: 0; }}
QLabel#projectLibraryBrand {{ color: {HUB_TEXT}; font-size: 32px; font-weight: 850; letter-spacing: 0.4px; }}
QLabel#projectLibraryBrandMeta {{ color: {HUB_TEXT_MUTED}; font-size: 13px; }}
QLabel#projectLibraryEyebrow {{ color: {HUB_CORAL}; font-size: 11px; font-weight: 800; letter-spacing: 1px; }}
QLabel#projectLibraryTitle {{ color: {HUB_TEXT}; font-size: 27px; font-weight: 800; }}
QLabel#projectLibrarySubtitle {{ color: {HUB_TEXT_MUTED}; font-size: 13px; }}
QFrame#resumeProjectCard {{
    background: {HUB_SURFACE}; border: 1px solid {HUB_BORDER}; border-radius: 14px;
}}
QFrame#resumeProjectInfo {{ background: transparent; border: 0; }}
QLabel#resumeProjectEyebrow {{ color: {HUB_CORAL}; font-size: 13px; font-weight: 800; letter-spacing: 0.6px; }}
QLabel#resumeProjectTitle {{ color: {HUB_TEXT}; font-size: 34px; font-weight: 850; }}
QLabel#resumeProjectMeta {{ color: {HUB_TEXT_MUTED}; font-size: 16px; font-weight: 650; }}
QLabel#resumeProjectStatus {{ color: {HUB_SUCCESS}; font-size: 15px; font-weight: 750; }}
QFrame#resumeProjectPreview {{ background: transparent; border: 0; }}
QLabel#resumeProjectPreviewImage {{ background: {HUB_SURFACE_MUTED}; border: 0; border-radius: 10px; padding: 0; }}
QToolButton#resumeProjectPreviewPlay {{
    background: {HUB_SURFACE_ELEVATED}; color: {HUB_TEXT}; border: 1px solid {HUB_BORDER};
    border-radius: 17px; min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px; padding: 0;
}}
QToolButton#resumeProjectPreviewPlay:hover {{ background: {HUB_CORAL}; border-color: {HUB_CORAL}; }}
QPushButton#hubPrimary {{
    background: {HUB_CORAL}; color: white; border: 1px solid {HUB_CORAL}; border-radius: 9px;
    min-height: 42px; padding: 4px 20px; font-weight: 800; font-size: 13px;
}}
QPushButton#hubPrimary:hover {{ background: {HUB_CORAL_HOVER}; border-color: {HUB_CORAL_HOVER}; }}
QPushButton#hubPrimary:pressed {{ background: {HUB_CORAL_PRESSED}; border-color: {HUB_CORAL_PRESSED}; }}
QPushButton#hubSecondary {{
    background: transparent; color: {HUB_CORAL}; border: 1px solid {HUB_BORDER}; border-radius: 9px;
    min-height: 42px; padding: 4px 18px; font-weight: 750;
}}
QPushButton#hubSecondary:hover {{ background: {HUB_SELECTED}; border-color: {HUB_CORAL}; }}
QPushButton#hubToolbarButton {{
    background: transparent; color: {HUB_TEXT}; border: 1px solid {HUB_BORDER}; border-radius: 9px;
    min-height: 42px; padding: 4px 16px; font-weight: 700; font-size: 13px;
}}
QPushButton#hubToolbarButton:hover {{ background: {HUB_SELECTED}; color: {HUB_TEXT}; border-color: {HUB_CORAL}; }}
QToolButton#projectViewButton {{
    background: transparent; color: {HUB_TEXT}; border: 1px solid transparent; border-radius: 8px;
    min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px; padding: 0;
}}
QToolButton#projectViewButton:hover {{ background: {HUB_SELECTED}; color: {HUB_TEXT}; }}
QToolButton#projectViewButton:checked {{ background: {HUB_CORAL}; color: white; border-color: {HUB_CORAL}; }}
QFrame#projectViewSwitcher {{ background: {HUB_SURFACE_MUTED}; border: 1px solid {HUB_BORDER}; border-radius: 10px; }}
QComboBox#projectSort {{
    background: {HUB_INPUT}; color: {HUB_TEXT}; border: 1px solid {HUB_BORDER};
    border-radius: 10px; min-height: 40px; padding: 0 12px; font-weight: 600;
}}
QComboBox#projectSort:hover {{ border-color: {HUB_CORAL}; }}
QComboBox#projectSort::drop-down {{ border: 0; width: 24px; }}
QLineEdit#projectLibrarySearch {{
    background: {HUB_INPUT}; color: {HUB_TEXT}; border: 1px solid {HUB_BORDER}; border-radius: 10px;
    min-height: 40px; padding: 0 12px; selection-background-color: {HUB_CORAL}; font-size: 13px;
}}
QLineEdit#projectLibrarySearch:focus {{ border-color: {HUB_CORAL}; }}
QLabel#projectLibrarySectionTitle {{ color: {HUB_TEXT}; font-size: 16px; font-weight: 800; }}
QFrame#projectCard {{ background: {HUB_SURFACE}; border: 1px solid {HUB_BORDER}; border-radius: 10px; }}
QFrame#projectCard:hover {{ background: {HUB_SURFACE_ELEVATED}; border-color: {HUB_CORAL}; }}
QToolButton#recentProjectCard {{ background: {HUB_SURFACE}; color: {HUB_TEXT}; border: 1px solid {HUB_BORDER}; border-radius: 10px; padding: 0; text-align: left; }}
QToolButton#recentProjectCard:hover {{ background: {HUB_SURFACE_ELEVATED}; border-color: {HUB_CORAL}; }}
QToolButton#recentProjectCard:pressed {{ background: {HUB_SELECTED}; border-color: {HUB_CORAL}; }}
QLabel#projectCardCover {{ background: {HUB_SURFACE_MUTED}; border: 0; border-radius: 7px; }}
QLabel#projectCardStatus {{ background: {HUB_SELECTED}; color: {HUB_TEXT}; border: 1px solid {HUB_BORDER}; border-radius: 5px; padding: 2px 6px; font-size: 10px; font-weight: 800; }}
QLabel#projectCardStatus[status="ready"] {{ background: #477158; color: white; border-color: #6f9a7d; }}
QLabel#projectCardStatus[status="offline"] {{ background: #725a66; color: {HUB_TEXT}; }}
QLabel#projectCardStatus[status="missing"] {{ background: #745246; color: #fff2ed; }}
QLabel#projectCardTitle {{ color: {HUB_TEXT}; font-size: 15px; font-weight: 650; }}
QLabel#projectCardMeta {{ color: {HUB_TEXT_MUTED}; font-size: 12px; }}
QPushButton#projectCardOpen {{
    background: {HUB_CORAL}; color: white; border: 1px solid {HUB_CORAL}; border-radius: 7px;
    min-height: 34px; padding: 2px 14px; font-size: 13px; font-weight: 800;
}}
QPushButton#projectCardOpen:hover {{ background: {HUB_CORAL_HOVER}; border-color: {HUB_CORAL_HOVER}; color: white; }}
QPushButton#projectCardOpen:pressed {{ background: {HUB_CORAL_PRESSED}; border-color: {HUB_CORAL_PRESSED}; color: white; }}
QToolButton#projectCardMore {{ background: transparent; color: {HUB_TEXT_MUTED}; border: 0; min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; padding: 0; }}
QToolButton#projectCardMore:hover {{ background: {HUB_SELECTED}; color: {HUB_TEXT}; border-radius: 5px; }}
QToolButton#projectListRow {{
    background: {HUB_SURFACE}; border: 1px solid {HUB_BORDER}; border-radius: 10px; padding: 0;
    text-align: left; min-height: 76px;
}}
QToolButton#projectListRow:hover {{ background: {HUB_SURFACE_ELEVATED}; border-color: {HUB_CORAL}; }}
QToolButton#projectListRow:pressed {{ background: {HUB_SELECTED}; }}
QLabel#projectListTitle {{ color: {HUB_TEXT}; font-size: 15px; font-weight: 650; }}
QLabel#projectListMeta {{ color: {HUB_TEXT_MUTED}; font-size: 12px; }}
"""
