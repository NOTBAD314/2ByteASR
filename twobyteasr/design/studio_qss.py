"""Single owner for frequently edited Studio component styles.

Colors derive from ThemeDefinition; dimensions and typography live in one
dataclass. Legacy retheme mappings never see these generated declarations.
"""
from dataclasses import dataclass
from .tokens import TYPE_SCALE, RADIUS_SCALE
from ..typography import MONO_FONT_STACK, UI_FONT_STACK


@dataclass(frozen=True)
class StudioComponentTokens:
    control_radius: int = RADIUS_SCALE["control"]
    field_height: int = 34
    timecode_size: int = 15
    label_size: int = TYPE_SCALE["small"]
    caption_size: int = TYPE_SCALE["caption"]
    toggle_width: int = 31
    toggle_height: int = 36
    input_padding: int = 8


def build_studio_component_qss(theme, tokens: StudioComponentTokens | None = None) -> str:
    t = tokens or StudioComponentTokens()
    return f"""
QLabel#projectRowStatus {{
    background: transparent; border: 0; color: {theme.text_muted};
    font-family: {UI_FONT_STACK}; font-size: {t.caption_size}px; font-weight: 500;
    padding: 0 8px; min-width: 74px;
}}
QLabel#projectRowStatus[status="offline"] {{ color: {theme.warning}; }}
QLabel#projectRowStatus[status="missing"] {{ color: {theme.danger}; }}
QPushButton#projectRowOpen {{
    background: {theme.accent_soft}; color: {theme.text}; border: 1px solid {theme.border_strong};
    border-radius: {t.control_radius}px; min-height: 34px; padding: 0 14px;
    font-family: {UI_FONT_STACK}; font-size: {t.label_size}px; font-weight: 500;
}}
QPushButton#projectRowOpen:hover, QPushButton#projectRowOpen:focus {{ background: {theme.selected}; border-color: {theme.focus}; }}
QPushButton#projectRowOpen:pressed {{ background: {theme.accent_pressed}; color: {theme.text_on_accent}; }}
QFrame#reviewSummaryStrip {{
    background: {theme.panel}; border-top: 1px solid {theme.border}; border-bottom: 1px solid {theme.border};
    min-height: 44px; max-height: 360px;
}}
QFrame#reviewSummaryStrip QLabel, QFrame#reviewSummaryStrip QPushButton {{
    font-family: {UI_FONT_STACK}; font-size: {t.label_size}px; font-weight: 500;
}}
QLabel#reviewIssueSummary {{ color: {theme.warning}; padding: 2px 4px; }}
QLabel#reviewReason {{ color: {theme.text_secondary}; padding: 2px 4px; }}
QLabel#reviewQueueCount {{ color: {theme.text}; padding: 2px 4px; font-weight: 600; }}
QLabel#reviewLegend {{ color: {theme.text_muted}; padding: 3px 4px; font-size: {t.caption_size}px; }}
QToolButton#reviewCollapseButton {{ background: transparent; border: 0; color: {theme.text_secondary}; min-width: 24px; }}
QToolButton#reviewCollapseButton:hover {{ background: {theme.selected}; border-radius: 4px; }}
QFrame#reviewCard {{ background: {theme.surface}; border: 1px solid {theme.border}; border-radius: 8px; }}
QFrame#reviewCard:hover {{ background: {theme.surface_elevated}; border-color: {theme.focus}; }}
QFrame#reviewCard[selected="true"] {{ background: {theme.accent_soft}; border: 2px solid {theme.focus}; }}
QFrame#reviewCard QLabel#reviewCandidateText {{ color: {theme.text}; font-family: {UI_FONT_STACK}; font-size: 15px; font-weight: 500; }}
QFrame#reviewCard QLabel#reviewCardNum {{ background: {theme.selected}; color: {theme.text}; border-radius: 5px; font-size: 15px; font-weight: 600; }}
QFrame#reviewCard QLabel#reviewSourceBadge {{ background: {theme.panel}; color: {theme.text_muted}; border-radius: 4px; padding: 2px 6px; font-size: {t.caption_size}px; }}
QFrame#reviewCard QLabel#reviewSourceBadge[current="true"] {{ background: {theme.selected}; color: {theme.text}; }}
QLineEdit#timelineTimecodeInput {{
    background: {theme.input_surface}; color: {theme.text}; border: 1px solid {theme.border_strong};
    border-radius: {t.control_radius}px; min-height: {t.field_height}px;
    min-width: 118px; max-width: 132px; padding: 0 {t.input_padding}px;
    font-family: {MONO_FONT_STACK}; font-size: {t.timecode_size}px; font-weight: 700;
    letter-spacing: 0.3px; selection-background-color: {theme.accent}; selection-color: {theme.text_on_accent};
}}
QLineEdit#timelineTimecodeInput:hover {{ border-color: {theme.focus}; background: {theme.surface_elevated}; }}
QLineEdit#timelineTimecodeInput:focus {{ border-color: {theme.accent}; background: {theme.input_surface}; }}
QLabel#timelineDuration {{
    color: {theme.text_muted}; font-family: {MONO_FONT_STACK};
    font-size: {t.caption_size}px; font-weight: 600; padding: 0 2px 0 6px;
}}
QToolButton#styleEmphasis, QToolButton#styleAnchor {{
    background: {theme.input_surface}; color: {theme.text}; border: 1px solid {theme.border};
    border-radius: {t.control_radius // 2}px; min-width: {t.toggle_width}px; max-width: {t.toggle_width}px;
    min-height: {t.toggle_height}px; max-height: {t.toggle_height}px; padding: 0; font-weight: 700;
}}
QToolButton#styleEmphasis:hover, QToolButton#styleAnchor:hover {{ border-color: {theme.accent}; }}
QToolButton#styleEmphasis:checked, QToolButton#styleAnchor:checked {{
    background: {theme.selected}; color: {theme.accent}; border-color: {theme.accent};
}}
QToolButton#motionPreset {{
    background: {theme.input_surface}; color: {theme.text_secondary}; border: 1px solid {theme.border};
    border-radius: {t.control_radius}px; min-height: {t.field_height}px;
    padding: 0 {t.input_padding}px; text-align: left;
}}
QToolButton#motionPreset:hover {{ background: {theme.selected}; border-color: {theme.accent}; color: {theme.text}; }}
QToolButton#motionPreset:checked {{ background: {theme.selected}; border-color: {theme.accent}; color: {theme.accent}; font-weight: 700; }}
QFrame#stylePropertyRow {{ background: {theme.surface}; border: 1px solid {theme.border}; border-radius: {t.control_radius}px; }}
QFrame#stylePropertyRow:hover {{ border-color: {theme.accent}; }}
QFrame#stylePropertyRow[expanded="true"] {{ background: {theme.surface}; border-color: {theme.accent}; }}
QLabel#stylePropertyRowTitle {{ background: transparent; color: {theme.text}; font-size: {t.label_size}px; font-weight: 700; }}
QLabel#stylePropertyRowSummary, QLabel#stylePropertyRowChevron {{ background: transparent; color: {theme.text_muted}; font-size: {t.caption_size}px; }}
QWidget#stylePropertyRowContent {{ background: transparent; border: 0; }}
QLineEdit#mediaPoolSearch {{
    background: {theme.input_surface}; color: {theme.text}; border: 1px solid {theme.border};
    border-radius: {t.control_radius}px; min-height: {t.field_height}px; padding: 0 {t.input_padding}px;
    selection-background-color: {theme.accent}; selection-color: {theme.text_on_accent};
}}
QLineEdit#mediaPoolSearch:focus {{ border-color: {theme.accent}; }}
QDialog#studioPerformance {{ background: {theme.panel}; color: {theme.text}; }}
QDialog#studioPerformance QLabel {{ color: {theme.text}; background: transparent; }}
QPlainTextEdit#performanceDetails {{
    background: {theme.input_surface}; color: {theme.text}; border: 1px solid {theme.border};
    border-radius: {t.control_radius}px; padding: {t.input_padding}px; font-family: {MONO_FONT_STACK};
    font-size: {t.label_size}px;
}}
"""
