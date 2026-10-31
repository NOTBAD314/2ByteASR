"""Single owner for frequently edited Studio component styles.

Colors derive from ThemeDefinition; dimensions and typography live in one
dataclass. Legacy retheme mappings never see these generated declarations.
"""
from dataclasses import dataclass
from .tokens import TYPE_SCALE, RADIUS_SCALE
from .typography import MONO_FONT_STACK, UI_FONT_STACK
from .ui_theme import blend_hex


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
/* Timeline geometry belongs to this bar, independently of dialog controls. */
QWidget#studioTimelineCommandBar QToolButton#studioTool {{
    min-width: 32px; min-height: 34px; max-height: 34px;
    padding: 0; font-family: {UI_FONT_STACK}; font-size: {t.label_size}px;
}}
QWidget#studioTimelineCommandBar QPushButton#studioButton {{
    min-height: 34px; max-height: 34px; padding: 0 10px;
    font-family: {UI_FONT_STACK}; font-size: {t.label_size}px; font-weight: 600;
}}
QWidget#studioTimelineCommandBar QCheckBox {{
    min-height: 34px; padding: 0; spacing: 8px;
    font-family: {UI_FONT_STACK}; font-size: {t.label_size}px;
}}
QWidget#studioTimelineCommandBar QComboBox {{
    min-height: 32px; max-height: 32px; padding: 0 8px;
    font-family: {UI_FONT_STACK}; font-size: {t.label_size}px;
}}
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
    /* The workspace owns the 128 px outer width. A CSS content minimum plus
       padding can exceed it after polish and overlap the duration label. */
    padding: 0 {t.input_padding}px;
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
/* 2026-10-07 visual system: Studio chrome stays quiet so preview, timeline
   and the user's subtitles carry the colour. Toolbar text commands are ghost
   until hovered; panel toggles show a neutral "on" lift, never a pink wash. */
QFrame#studioToolbar QPushButton[buttonRole="secondary"], QFrame#studioToolbar QPushButton[buttonRole="ghost"],
QFrame#studioToolbar QPushButton[buttonRole="toggle"] {{
    background: transparent; color: {theme.text_secondary}; border: 1px solid transparent;
    border-radius: {t.control_radius}px; min-height: 32px; max-height: 32px; padding: 0 10px;
    font-family: {UI_FONT_STACK}; font-size: {t.label_size}px; font-weight: 500;
}}
QFrame#studioToolbar QPushButton[buttonRole="secondary"]:hover, QFrame#studioToolbar QPushButton[buttonRole="ghost"]:hover,
QFrame#studioToolbar QPushButton[buttonRole="toggle"]:hover {{ background: {theme.selected}; color: {theme.text}; border-color: transparent; }}
QFrame#studioToolbar QPushButton[buttonRole="toggle"]:checked {{
    background: {theme.surface_elevated}; color: {theme.text}; border-color: {theme.border_strong}; }}
QFrame#studioToolbar QPushButton[buttonRole="secondary"]:focus, QFrame#studioToolbar QPushButton[buttonRole="ghost"]:focus,
QFrame#studioToolbar QPushButton[buttonRole="toggle"]:focus {{ border-color: {theme.focus}; }}
QFrame#studioToolbar QPushButton[buttonRole="primary"] {{ min-height: 32px; max-height: 32px; padding: 0 14px; font-size: {t.label_size}px; }}
QFrame#studioToolbar QPushButton[emphasis="accent"] {{ color: {theme.accent_text}; font-weight: 600; }}
QFrame#studioToolbar QPushButton[emphasis="accent"]:hover {{ background: {theme.accent_tint}; color: {theme.accent_text}; }}
QFrame#studioToolbar QPushButton[emphasis="warning"] {{ color: {theme.warning}; border-color: {theme.warning}; }}
QFrame#studioToolbar QPushButton[emphasis="warning"]:hover {{ background: {theme.warning_soft}; color: {theme.warning}; border-color: {theme.warning}; }}
QFrame#studioToolbar QPushButton[hasMenu="true"] {{ padding-right: 24px; }}
QFrame#studioToolbar QPushButton[hasMenu="true"]::menu-indicator {{
    subcontrol-origin: padding; subcontrol-position: right center; right: 8px; width: 8px; height: 8px; }}
QFrame#studioToolbar QToolButton[hideMenuIndicator="true"]::menu-indicator {{ image: none; width: 0; height: 0; }}
QFrame#studioToolbar QLabel#studioFilename {{ color: {theme.text}; font-family: {UI_FONT_STACK}; font-size: 15px; font-weight: 600; }}
QFrame#studioToolbar QLabel#studioSaveState {{ color: {theme.text_muted}; font-size: {t.caption_size}px; font-weight: 500; }}
QWidget#studioTimelineCommandBar QPushButton#studioButton {{
    background: transparent; color: {theme.text_secondary}; border: 1px solid {theme.border};
    border-radius: {t.control_radius}px; font-weight: 500;
}}
QWidget#studioTimelineCommandBar QPushButton#studioButton:hover {{ background: {theme.selected}; color: {theme.text}; border-color: {theme.border_strong}; }}
QWidget#studioTimelineCommandBar QPushButton#studioButton:checked {{ background: {theme.accent_tint}; color: {theme.text}; border-color: {theme.accent}; }}
QPushButton#filterChip {{
    background: transparent; color: {theme.text_secondary}; border: 1px solid {theme.border};
    border-radius: {t.control_radius}px; min-height: 32px; padding: 0 10px;
    font-family: {UI_FONT_STACK}; font-size: {t.label_size}px; font-weight: 500;
}}
QPushButton#filterChip:hover {{ background: {theme.selected}; color: {theme.text}; border-color: {theme.border_strong}; }}
QPushButton#filterChip:checked {{ background: {theme.surface_elevated}; color: {theme.text}; border-color: {theme.text_muted}; font-weight: 600; }}
QPushButton#filterChip:focus {{ border-color: {theme.focus}; }}
QPushButton#reviewEntryButton {{
    background: {theme.accent_tint}; color: {theme.accent_text}; border: 1px solid transparent;
    border-radius: {t.control_radius}px; min-height: 32px; padding: 0 10px;
    font-family: {UI_FONT_STACK}; font-size: {t.label_size}px; font-weight: 600;
}}
QPushButton#reviewEntryButton:hover {{ background: {theme.accent}; color: {theme.text_on_accent}; }}
QPushButton#reviewEntryButton:pressed {{ background: {theme.accent_pressed}; color: {theme.text_on_accent}; }}
QPushButton#reviewEntryButton:focus {{ border-color: {theme.focus}; }}
/* 2026-10-08 timeline command bar: centred transport pill with an accent
   play button, view tools as one icon family, display switches as chips,
   range row as outlined segments with icon actions. */
QWidget#studioTimelineCommandBar QWidget[commandGroup="transport"] {{
    background: {theme.surface}; border: 1px solid {theme.border}; border-radius: 12px; }}
QWidget#studioTimelineCommandBar QToolButton#studioTool[transportRole="play"] {{
    background: {theme.accent}; color: {theme.text_on_accent}; border: 0; border-radius: 16px; padding: 0;
    min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; }}
QWidget#studioTimelineCommandBar QWidget[commandGroup="transport"] QLineEdit#timelineTimecodeInput,
QWidget#studioTimelineCommandBar QWidget[commandGroup="transport"] QComboBox {{
    min-height: 30px; max-height: 30px; }}
QWidget#studioTimelineCommandBar QToolButton#studioTool[transportRole="play"]:hover {{ background: {theme.accent_hover}; }}
QWidget#studioTimelineCommandBar QToolButton#studioTool[transportRole="play"]:pressed {{ background: {theme.accent_pressed}; }}
QWidget#studioTimelineCommandBar QCheckBox#timelineToggleChip, QWidget#projectRangeBar QCheckBox#timelineToggleChip {{
    background: transparent; color: {theme.text_secondary}; border: 1px solid {theme.border};
    border-radius: 8px; padding: 0 12px; spacing: 0; min-height: 34px; max-height: 34px;
    font-family: {UI_FONT_STACK}; font-size: {t.label_size}px; font-weight: 500; }}
QWidget#studioTimelineCommandBar QCheckBox#timelineToggleChip::indicator, QWidget#projectRangeBar QCheckBox#timelineToggleChip::indicator {{
    width: 0; height: 0; border: 0; }}
QWidget#studioTimelineCommandBar QCheckBox#timelineToggleChip:hover, QWidget#projectRangeBar QCheckBox#timelineToggleChip:hover {{
    border-color: {theme.border_strong}; color: {theme.text}; }}
QWidget#studioTimelineCommandBar QCheckBox#timelineToggleChip:checked, QWidget#projectRangeBar QCheckBox#timelineToggleChip:checked {{
    background: {theme.surface_elevated}; color: {theme.text}; border-color: {theme.border_strong}; font-weight: 600; }}
QWidget#studioTimelineCommandBar QCheckBox#timelineToggleChip:focus, QWidget#projectRangeBar QCheckBox#timelineToggleChip:focus {{
    border-color: {theme.focus}; }}
QWidget#studioTimelineCommandBar QCheckBox#timelineToggleChip {{ padding: 0 10px 0 8px; }}
/* 2026-10-21: icon-only display switches; the "+" above the track names. */
QWidget#studioTimelineCommandBar QCheckBox#timelineToggleChip[iconOnly="true"] {{
    padding: 0 8px; min-width: 16px; }}
QToolButton#timelineAddTrackButton {{ background: transparent; border: 1px solid {theme.border};
    border-radius: 6px; padding: 0; }}
QToolButton#timelineAddTrackButton:hover {{ background: {theme.selected}; border-color: {theme.border_strong}; }}
QToolButton#timelineAddTrackButton:pressed {{ background: {theme.surface_elevated}; }}
QToolButton#timelineAddTrackButton::menu-indicator {{ image: none; width: 0; }}
/* 2026-10-09 (M16): save frame / cover / options as icon buttons in the bar. */
QWidget#studioTimelineCommandBar QToolButton#rangeAction {{ background: transparent; color: {theme.text_secondary};
    border: 1px solid {theme.border}; border-radius: 8px; min-height: 34px; max-height: 34px; min-width: 34px;
    padding: 0 6px; font-size: {t.label_size}px; }}
QWidget#studioTimelineCommandBar QToolButton#rangeAction:hover {{ background: {theme.selected}; border-color: {theme.border_strong}; color: {theme.text}; }}
/* 2026-10-30 (user, draft B): editing / zoom / display / output are pills like the
   transport; inside them every control is a flat icon, an "on" switch takes the accent tint. */
QWidget#studioTimelineCommandBar QWidget[commandGroup="editing"],
QWidget#studioTimelineCommandBar QWidget[commandGroup="view"],
QWidget#studioTimelineCommandBar QWidget[commandGroup="display"],
QWidget#studioTimelineCommandBar QWidget[commandGroup="output"] {{
    background: {theme.surface}; border: 1px solid {theme.border}; border-radius: 12px; }}
QWidget#studioTimelineCommandBar QWidget[commandGroup="editing"] QLabel {{ background: transparent; border: 0; padding-left: 6px; }}
QWidget#studioTimelineCommandBar QWidget[commandGroup="display"] QCheckBox#timelineToggleChip[iconOnly="true"] {{
    background: transparent; border: 1px solid transparent; border-radius: 8px;
    min-width: 18px; min-height: 32px; max-height: 32px; padding: 0 7px; }}
QWidget#studioTimelineCommandBar QWidget[commandGroup="display"] QCheckBox#timelineToggleChip[iconOnly="true"]:hover {{
    background: {theme.selected}; border-color: transparent; }}
QWidget#studioTimelineCommandBar QWidget[commandGroup="display"] QCheckBox#timelineToggleChip[iconOnly="true"]:checked {{
    background: {theme.accent_tint}; border-color: transparent; }}
QWidget#studioTimelineCommandBar QWidget[commandGroup="display"] QCheckBox#timelineToggleChip[iconOnly="true"]:focus {{
    border-color: {theme.focus}; }}
QWidget#studioTimelineCommandBar QWidget[commandGroup="output"] QToolButton#rangeAction {{
    background: transparent; border: 1px solid transparent; min-height: 32px; max-height: 32px; }}
QWidget#studioTimelineCommandBar QWidget[commandGroup="output"] QToolButton#rangeAction:hover {{
    background: {theme.selected}; border-color: transparent; }}
QWidget#studioTimelineCommandBar QWidget[commandGroup="view"] QToolButton#studioTool,
QWidget#studioTimelineCommandBar QWidget[commandGroup="output"] QToolButton#studioTool,
QWidget#studioTimelineCommandBar QWidget[commandGroup="editing"] QToolButton#studioTool {{
    min-height: 32px; max-height: 32px; }}
QSlider#timelineZoomSlider::groove:horizontal {{ height: 4px; border-radius: 2px; background: {theme.border_strong}; }}
QSlider#timelineZoomSlider::sub-page:horizontal {{ height: 4px; border-radius: 2px; background: {theme.text_muted}; }}
QSlider#timelineZoomSlider::handle:horizontal {{ width: 12px; height: 12px; margin: -5px 0; border-radius: 7px;
    background: {theme.surface_elevated}; border: 1.5px solid {theme.text_secondary}; }}
QSlider#timelineZoomSlider::handle:horizontal:hover {{ border-color: {theme.accent}; }}
QSlider#timelineZoomSlider:disabled::handle:horizontal {{ border-color: {theme.disabled}; }}
/* 2026-10-18 (user): no divider inside 保存当前帧; the cover button beside it has none. */
QWidget#studioTimelineCommandBar QToolButton#rangeAction::menu-button {{ border: 0; width: 16px; }}
QWidget#studioTimelineCommandBar QToolButton#rangeAction[menuOnly="true"] {{ padding-right: 18px; }}
QWidget#studioTimelineCommandBar QToolButton#rangeAction[splitMenu="true"] {{ padding: 0 16px 0 0; }}
QWidget#studioTimelineCommandBar QToolButton#rangeAction::menu-indicator {{
    subcontrol-origin: padding; subcontrol-position: right center; right: 5px; }}
QFrame#rangeSegment {{ background: {theme.input_surface}; border: 1px solid {theme.border}; border-radius: 8px; }}
QFrame#rangeSegment:hover {{ border-color: {theme.border_strong}; }}
QFrame#rangeSegment QPushButton#rangeMark {{ background: {theme.surface_elevated}; color: {theme.text}; border: 0;
    border-right: 1px solid {theme.border}; border-top-left-radius: 7px; border-bottom-left-radius: 7px;
    border-top-right-radius: 0; border-bottom-right-radius: 0;
    min-height: 32px; max-height: 32px; padding: 0 12px; font-size: {t.label_size}px; font-weight: 600; }}
QFrame#rangeSegment QPushButton#rangeMark:hover {{ background: {theme.accent_tint}; color: {theme.accent_text}; }}
QFrame#rangeSegment QLineEdit#rangeField {{ background: transparent; color: {theme.text}; border: 0; border-radius: 0;
    min-height: 32px; max-height: 32px; padding: 0 10px; font-family: {MONO_FONT_STACK}; font-size: {t.label_size}px; }}
QFrame#rangeSegment QPushButton#rangeJump {{ background: transparent; border: 0; border-left: 1px solid {theme.border};
    border-top-right-radius: 7px; border-bottom-right-radius: 7px; border-top-left-radius: 0; border-bottom-left-radius: 0;
    min-height: 32px; max-height: 32px; padding: 0; }}
QFrame#rangeSegment QPushButton#rangeJump:hover {{ background: {theme.selected}; }}
QLabel#rangeStatus {{ color: {theme.text_muted}; font-size: {t.caption_size}px; font-variant-numeric: tabular-nums; background: transparent; }}
QWidget#projectRangeBar QPushButton#rangeClear {{ background: transparent; color: {theme.text_secondary};
    border: 1px solid {theme.border}; border-radius: 8px; min-height: 32px; max-height: 32px; padding: 0 12px; }}
QWidget#projectRangeBar QPushButton#rangeClear:hover {{ background: {theme.selected}; color: {theme.text}; border-color: {theme.border_strong}; }}
QWidget#projectRangeBar QToolButton#rangeAction {{ background: {theme.surface_elevated}; color: {theme.text};
    border: 1px solid {theme.border_strong}; border-radius: 8px; min-height: 32px; max-height: 32px;
    padding: 0 12px; font-size: {t.label_size}px; font-weight: 500; }}
QWidget#projectRangeBar QToolButton#rangeAction:hover {{ background: {theme.selected}; border-color: {theme.text_muted}; }}
QWidget#projectRangeBar QToolButton#rangeAction::menu-button {{ border: 0; border-left: 1px solid {theme.border}; width: 20px; }}
QWidget#projectRangeBar QToolButton#rangeAction[menuOnly="true"] {{ padding-right: 24px; }}
QWidget#projectRangeBar QToolButton#rangeAction::menu-indicator {{
    subcontrol-origin: padding; subcontrol-position: right center; right: 8px; }}
/* 2026-10-08 style inspector: flat sections with clear headers, quiet field
   captions, flat property rows (no card-in-card), brand accent only on the
   row being edited and on checked emphasis toggles. */
QFrame#styleSection {{ background: transparent; border: 0; border-top: 1px solid {theme.hairline}; border-radius: 0; }}
QToolButton#styleSectionHeader {{ background: transparent; border: 0; color: {theme.text};
    font-family: {UI_FONT_STACK}; font-size: 14px; font-weight: 600; padding: 2px 0; text-align: left; }}
QToolButton#styleSectionHeader:hover {{ color: {theme.accent_text}; }}
QLabel#styleFieldLabel {{ color: {theme.text_muted}; font-size: 12px; font-weight: 500; background: transparent; }}
/* 2026-10-09 (M16): compact style panel — scope chips on top, inline
   captions, one-line property rows with small switches. */
QFrame#styleScopeBar, QFrame#styleInlineSection {{ background: transparent; border: 0; }}
QLabel#styleInlineLabel {{ color: {theme.text_muted}; font-size: 12px; font-weight: 600; background: transparent; }}
/* 2026-10-17: every checkbox of the style tab shares one look. */
QCheckBox#styleInlineCheck {{ color: {theme.text_secondary}; font-size: 13px; font-weight: 500;
    spacing: 8px; background: transparent; }}
QFrame#styleScopeBar QRadioButton#scopeOption {{ color: {theme.text_secondary}; background: {theme.surface};
    border: 1px solid {theme.border}; border-radius: 7px; padding: 2px 6px; min-height: 26px; spacing: 0; }}
QFrame#styleScopeBar QRadioButton#scopeOption::indicator {{ width: 0; height: 0; margin: 0; }}
QFrame#styleScopeBar QRadioButton#scopeOption:hover {{ border-color: {theme.border_strong}; color: {theme.text}; }}
QFrame#styleScopeBar QRadioButton#scopeOption:checked {{ background: {theme.accent_tint}; color: {theme.accent_text};
    border-color: {theme.accent}; font-weight: 700; }}
QCheckBox#styleSwitch {{ background: transparent; spacing: 0; }}
QCheckBox#styleSwitch::indicator {{ width: 30px; height: 16px; border-radius: 8px; border: 1px solid {theme.border_strong};
    background: {theme.input_surface}; }}
QCheckBox#styleSwitch::indicator:checked {{ background: {theme.accent}; border-color: {theme.accent}; image: none; }}
QToolButton#stylePreviewSample {{ background: rgba(0,0,0,0.28); color: #f4f0ea; border: 1px solid rgba(255,255,255,0.28);
    border-radius: 6px; font-size: 11px; font-weight: 700; padding: 0; }}
QToolButton#stylePreviewSample:checked {{ background: {theme.accent}; border-color: {theme.accent}; color: {theme.text_on_accent}; }}
QToolButton#styleEmphasis:checked, QToolButton#styleAnchor:checked {{
    background: {theme.accent_tint}; color: {theme.accent_text}; border-color: {theme.accent_text}; }}
/* The compact button role's side padding made B/I/U 41 px instead of the
   31 px above, and 字号 / 字距 / B I U no longer fit one row. */
QToolButton#styleEmphasis[controlSize="compact"], QToolButton#styleAnchor[controlSize="compact"] {{ padding: 0; }}
QFrame#stylePropertyRow {{ background: transparent; border: 0; border-top: 1px solid {theme.hairline};
    border-left: 3px solid transparent; border-radius: 0; }}
QFrame#stylePropertyRow:hover {{ background: {theme.surface}; }}
QFrame#stylePropertyRow[expanded="true"] {{ background: {theme.surface}; border-left: 3px solid {theme.accent_text}; }}
/* 2026-10-17: one style for every left-column label of the style tab
   (应用到, 预设, 字体, 字号, 填充…发光, 对齐, X, 边距). */
QLabel#stylePropertyRowTitle {{ color: {theme.text_secondary}; font-size: 13px; font-weight: 600; }}
QLabel#stylePropertyRowSummary {{ font-size: 12px; }}
QFrame#resumeProjectCard {{ background: {blend_hex(theme.surface, theme.accent_text, 0.07)};
    border: 1px solid {blend_hex(theme.surface, theme.accent_text, 0.40)}; }}
QLabel#resumeProjectEyebrow {{ color: {theme.accent_text}; font-size: 13px; font-weight: 600; }}
QLabel#resumeProjectStatus {{ color: {theme.text_secondary}; font-size: 14px; font-weight: 500; }}
QLabel#resumeProjectStatusPill, QLabel#projectCardStatus, QLabel#projectRowStatus {{
    background: {theme.surface_elevated}; color: {theme.text_secondary}; border: 0; border-radius: 6px;
    padding: 2px 10px; font-size: 12px; font-weight: 600; }}
QLabel#resumeProjectStatusPill[status="ready"], QLabel#projectRowStatus[status="ready"] {{ background: {theme.success_soft}; color: {theme.success}; }}
QLabel#resumeProjectStatusPill[status="offline"], QLabel#projectRowStatus[status="offline"] {{ background: {theme.warning_soft}; color: {theme.warning}; }}
QLabel#resumeProjectStatusPill[status="missing"], QLabel#projectRowStatus[status="missing"] {{ background: {theme.danger_soft}; color: {theme.danger}; }}
/* Badges over cover art need a solid chip to stay legible on any image. */
QLabel#projectCardStatus[status="ready"] {{ background: {theme.success}; color: {theme.on_vivid}; }}
QLabel#projectCardStatus[status="offline"] {{ background: {theme.warning}; color: {theme.on_vivid}; }}
QLabel#projectCardStatus[status="missing"] {{ background: {theme.danger}; color: {theme.on_vivid}; }}
QToolButton#recentProjectCard:hover {{ border-color: {theme.accent_text}; }}
"""
