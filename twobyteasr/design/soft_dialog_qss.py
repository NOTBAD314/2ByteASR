# SPDX-License-Identifier: GPL-3.0-only
"""Styles of the question-style Settings window and the 匹配文稿 wizard.

2026-11-12 (user picked design C for both): a rounded window, chunky
sidebar tiles, one light content sheet, question headings, pill chips and
painted switches. Every colour comes from the active theme, so dark themes
get the same shapes with their own tones.
"""
from .typography import TITLE_FONT_STACK, UI_FONT_STACK


def _tone(t, color, light, dark):
    from .ui_theme import blend_hex
    return blend_hex(t.surface, color, light if t.is_light else dark)


def build_settings_qss(t) -> str:
    selected = _tone(t, t.accent, 0.2, 0.3)
    hover = _tone(t, t.text, 0.05, 0.08)
    chip_hover = _tone(t, t.text, 0.06, 0.1)
    return f"""
QDialog#applicationSettings {{ background: transparent; color: {t.text}; }}
QWidget#settingsRoot {{ background: {t.surface}; border: 0; }}
QFrame#settingsSidebar {{ background: transparent; border: 0; }}
QLabel#settingsSidebarTitle {{ font-family: {TITLE_FONT_STACK}; font-size: 22px; font-weight: 900;
    color: {t.text}; background: transparent; padding: 4px 10px 8px; }}
QListWidget#settingsNavigation {{ background: transparent; border: 0; outline: 0; padding: 0; }}
QListWidget#settingsNavigation::item {{ min-height: 46px; padding: 0 8px; margin: 1px 0; border: 0;
    border-radius: 16px; color: {t.text_secondary}; font-size: 14px; }}
QListWidget#settingsNavigation::item:hover {{ background: {hover}; color: {t.text}; }}
QListWidget#settingsNavigation::item:selected {{ background: {selected}; color: {t.text}; }}
QWidget#settingsSheet {{ background: {t.surface_elevated}; border: 0; border-radius: 22px; }}
QFrame#settingsHeader {{ background: transparent; border: 0; }}
QLabel#settingsTip {{ background: {t.input_surface}; color: {t.text_secondary}; border-radius: 16px;
    padding: 9px 14px; font-size: 13px; font-weight: 400; }}
QPushButton#settingsClose {{ background: {t.input_surface}; color: {t.text}; border: 0; border-radius: 19px;
    min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px; padding: 0; font-size: 18px; }}
QPushButton#settingsClose:hover {{ background: {hover}; }}
QWidget#settingsPage, QScrollArea#settingsScroll, QWidget#settingsViewport {{ background: transparent; border: 0; }}
QFrame#settingsSection {{ background: transparent; border: 0; border-radius: 0; }}
QLabel#settingsQuestion {{ font-family: {UI_FONT_STACK}; color: {t.text}; font-size: 17px; font-weight: 700;
    background: transparent; }}
QLabel#settingsRowTitle {{ color: {t.text}; font-size: 14px; font-weight: 600; background: transparent; }}
QLabel#settingsDescription {{ color: {t.text_muted}; font-size: 12px; font-weight: 400; background: transparent; }}
QLabel#settingsChipCaption {{ color: {t.text_secondary}; font-size: 13px; background: transparent; }}
QPushButton#settingsChip {{ min-height: 32px; max-height: 32px; padding: 0 14px; border-radius: 16px;
    background: transparent; color: {t.text}; border: 1px solid {t.border}; font-size: 13px; font-weight: 500; }}
QPushButton#settingsChip:hover {{ background: {chip_hover}; }}
QPushButton#settingsChip:checked {{ background: {t.accent_soft}; border: 2px solid {t.accent}; font-weight: 700; }}
QPushButton#settingsChip:disabled {{ color: {t.disabled}; border-color: {t.border}; background: transparent; }}
QPushButton#settingsChip:focus {{ border-color: {t.focus}; }}
QFrame#settingsPathField {{ background: {t.input_surface}; border: 0; border-radius: 16px; }}
QFrame#settingsPathField QLineEdit {{ background: transparent; border: 0; padding: 0; min-height: 34px;
    font-size: 13px; color: {t.text}; }}
QFrame#settingsPathField QPushButton#settingsPathChange {{ background: {t.surface_elevated}; color: {t.accent};
    border: 1px solid {t.border}; border-radius: 11px; min-height: 34px; padding: 0 14px; font-weight: 700; }}
QFrame#settingsPathField QPushButton#settingsPathChange:hover {{ border-color: {t.accent}; }}
QFrame#settingsPathField QPushButton#settingsPathReset {{ background: transparent; color: {t.text_muted};
    border: 0; min-height: 34px; padding: 0 10px; }}
QFrame#settingsPathField QPushButton#settingsPathReset:hover {{ color: {t.text}; }}
QLabel#settingsLink {{ background: transparent; font-size: 12px; color: {t.text_muted}; }}
QFrame#settingsFooter {{ background: transparent; border: 0; }}
QPushButton#settingsReport {{ background: transparent; border: 0; color: {t.text_muted}; padding: 0 4px;
    min-height: 32px; font-size: 12px; text-decoration: none; }}
QPushButton#settingsReport:hover {{ color: {t.accent}; }}
"""


def build_script_match_qss(t) -> str:
    hover = _tone(t, t.text, 0.06, 0.1)
    done = t.success
    return f"""
QDialog#homeScriptMatchDialog {{ background: transparent; color: {t.text}; }}
QWidget#scriptWizardRoot {{ background: {t.surface}; border: 0; }}
QLabel#scriptWizardTitle {{ font-family: {TITLE_FONT_STACK}; font-size: 18px; font-weight: 900; color: {t.text};
    background: transparent; }}
QPushButton#scriptWizardClose {{ background: {_tone(t, t.text, 0.07, 0.12)}; color: {t.text}; border: 0;
    border-radius: 17px; min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px; padding: 0;
    font-size: 16px; }}
QPushButton#scriptWizardClose:hover {{ background: {_tone(t, t.text, 0.12, 0.18)}; }}
QLabel#scriptStepName {{ font-size: 13px; color: {t.text_muted}; background: transparent; }}
QLabel#scriptStepName[stepState="current"] {{ color: {t.accent}; font-weight: 700; }}
QLabel#scriptStepName[stepState="done"] {{ color: {done}; font-weight: 700; }}
QLabel#scriptStepDetail {{ font-size: 11px; color: {t.text_muted}; background: transparent; }}
QLabel#scriptWizardTip {{ background: {t.surface_elevated}; color: {t.text_secondary}; border-radius: 18px;
    border-bottom-left-radius: 6px; padding: 10px 14px; font-size: 13px; }}
QFrame#scriptDropZone {{ background: {t.surface_elevated}; border: 2px dashed {t.border_strong}; border-radius: 20px; }}
QFrame#scriptDropZone[dragging="true"] {{ border-color: {t.accent}; background: {t.accent_soft}; }}
QLabel#scriptDropTitle {{ font-size: 16px; font-weight: 700; color: {t.text}; background: transparent; }}
QLabel#scriptDropHint, QLabel#homeScriptMatchMedia {{ font-size: 12.5px; color: {t.text_muted}; background: transparent; }}
QFrame#scriptEditorFrame {{ background: {t.surface_elevated}; border: 2px solid {t.border}; border-radius: 20px; }}
QFrame#scriptEditorFrame[focused="true"] {{ border-color: {t.accent}; }}
QPlainTextEdit#homeScriptMatchInput {{ background: transparent; border: 0; padding: 8px 10px; font-size: 14px;
    color: {t.text}; selection-background-color: {t.accent_soft}; selection-color: {t.text}; }}
QPushButton#scriptEditorTool {{ background: {t.input_surface}; color: {t.text}; border: 0; border-radius: 15px;
    min-height: 30px; max-height: 30px; padding: 0 12px; font-size: 12.5px; }}
QPushButton#scriptEditorTool:hover {{ background: {hover}; }}
QLabel#scriptLineCount {{ font-size: 12px; color: {t.text_muted}; background: transparent; }}
QLabel#scriptLanguageCaption {{ font-size: 12.5px; font-weight: 600; color: {t.text_secondary}; background: transparent; }}
QPushButton#scriptLanguageChip {{ min-height: 30px; max-height: 30px; padding: 0 12px; border-radius: 15px;
    background: transparent; color: {t.text}; border: 1px solid {t.border}; font-size: 12.5px; }}
QPushButton#scriptLanguageChip:hover {{ background: {hover}; }}
QPushButton#scriptLanguageChip:checked {{ background: {t.text}; color: {t.surface}; border-color: {t.text}; font-weight: 700; }}
QPushButton#scriptLanguageChip:disabled {{ color: {t.disabled}; }}
QPushButton#scriptLanguageChip::menu-indicator {{ image: none; width: 0px; }}
QLabel#homeScriptMatchRuns {{ font-size: 12px; color: {t.text_muted}; background: transparent; }}
QLabel#homeScriptMatchStatus {{ font-size: 12.5px; color: {t.text_secondary}; background: transparent; }}
"""


__all__ = ['build_script_match_qss', 'build_settings_qss']
