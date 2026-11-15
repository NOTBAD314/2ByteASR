# SPDX-License-Identifier: GPL-3.0-only
"""Styles and status colours of the 字幕任务进度与结果 window.

2026-11-14 (user picked design A, 糖果计数): the same top-to-bottom order as
before (task → progress → counts → list → details → actions), with rounded
cards, a progress bar split by result, clickable count chips and status
badges. Every colour comes from the active theme.
"""
from __future__ import annotations

from .candy_chrome_qss import build_candy_chrome_qss
from .typography import emphasized

STATUS_ORDER = ('applied', 'unchanged', 'suggestion', 'review', 'failed', 'cancelled')
_SUGGESTION_LIGHT, _SUGGESTION_DARK = '#7652b3', '#b89cff'


def _blend(base, overlay, amount):
    from .ui_theme import blend_hex
    return blend_hex(base, overlay, amount)


def _readable(color, background, text, minimum=4.5):
    """Move ``color`` toward the theme's text until it reads on ``background``."""
    from .ui_theme import contrast_ratio
    ink, step = color, 0
    while contrast_ratio(ink, background) < minimum and step < 10:
        step += 1
        ink = _blend(color, text, step / 10)
    return ink


def status_tones(t) -> dict[str, tuple[str, str, str]]:
    """``status -> (solid, soft, ink)``: dot fill, badge fill, badge text."""
    light = t.is_light
    solids = {
        'applied': t.success, 'unchanged': t.text_muted,
        'suggestion': _SUGGESTION_LIGHT if light else _SUGGESTION_DARK,
        'review': t.warning, 'failed': t.danger, 'cancelled': _blend(t.text_muted, t.surface, .3),
        'running': t.accent, 'validated': t.accent, 'pending': t.text_muted, 'all': t.text_secondary,
    }
    from .ui_theme import contrast_ratio
    tones = {}
    for key, solid in solids.items():
        # A quieter fill when the theme's text cannot reach 4.5:1 on the first one.
        for amount in ((.15, .24) if light else (.24, .16, .08)):
            soft = t.input_surface if key in {'pending', 'all'} else _blend(t.surface_elevated, solid, amount)
            ink = _readable(solid, soft, t.text)
            if contrast_ratio(ink, soft) >= 4.5:
                break
        tones[key] = (solid, soft, ink)
    return tones


@emphasized
def build_task_panel_qss(t) -> str:
    tones = status_tones(t)
    hover = _blend(t.surface_elevated, t.text, .05 if t.is_light else .08)
    root = 'QDialog#subtitleTaskPanel'
    chips = []
    for key, (solid, soft, ink) in tones.items():
        chips.append(f"""{root} QPushButton#taskChip[status="{key}"] {{ background: {soft}; color: {ink}; }}
{root} QPushButton#taskChip[status="{key}"]:checked {{ border-color: {solid}; }}
{root} QPushButton#taskPill[status="{key}"]:checked {{ border-color: {solid}; }}""")
    for key in ('failed', 'review'):
        solid, soft, ink = tones[key]
        chips.append(f"""{root} QFrame#taskCause[status="{key}"] {{ background: {soft}; }}
{root} QFrame#taskCause[status="{key}"] QLabel#taskCauseCount {{ color: {ink}; }}""")
    for key, (solid, soft, ink) in tones.items():
        chips.append(f"""{root} QFrame#taskNext[status="{key}"] {{ background: {soft}; }}
{root} QFrame#taskNext[status="{key}"] QLabel#taskNextLead {{ color: {ink}; }}""")
    danger = tones['failed']
    return f"""
{build_candy_chrome_qss(root, t)}
{root} QFrame#taskHead, {root} QFrame#taskTableCard, {root} QFrame#taskDetailCard {{
    background: {t.surface_elevated}; border: 1px solid {t.border}; border-radius: 18px; }}
{root} QLabel#taskPhase {{ font-size: 18px; font-weight: 800; color: {t.text}; background: transparent; }}
{root} QLabel#taskFraction {{ font-size: 15px; color: {t.text_secondary}; background: transparent; }}
{root} QLabel#taskElapsed {{ background: {t.input_surface}; color: {t.text_muted}; border-radius: 12px;
    padding: 3px 11px; font-size: 12.5px; }}
{root} QPushButton#taskPill {{ min-height: 28px; max-height: 28px; padding: 0 12px 0 6px; border-radius: 14px;
    background: {t.surface_elevated}; color: {t.text}; border: 2px solid {t.border}; font-size: 13px; text-align: left; }}
{root} QPushButton#taskPill:hover {{ background: {hover}; }}
{root} QPushButton#taskPill:checked {{ background: {t.accent_soft}; color: {t.text}; font-weight: 700; }}
{root} QToolButton#taskMore {{ min-height: 28px; max-height: 28px; padding: 0 12px; border-radius: 14px;
    background: {t.input_surface}; color: {t.text_secondary}; border: 1px solid {t.border}; font-size: 13px; }}
{root} QToolButton#taskMore:hover {{ background: {hover}; color: {t.text}; }}
{root} QToolButton#taskMore::menu-indicator {{ image: none; }}
{root} QPushButton#taskChip {{ min-height: 28px; max-height: 28px; padding: 0 12px 0 5px; border-radius: 14px;
    border: 2px solid transparent; font-size: 13.5px; text-align: left; }}
{root} QPushButton#taskChip[plain="true"] {{ padding-left: 12px; }}
{root} QPushButton#taskChip:hover {{ border-color: {t.border_strong}; }}
{root} QPushButton#taskChip:checked {{ font-weight: 700; }}
{root} QFrame#taskCause {{ border-radius: 14px; border: 0; }}
{root} QFrame#taskCause QLabel {{ background: transparent; }}
{root} QLabel#taskCauseCount {{ font-weight: 800; font-size: 14px; }}
{root} QLabel#taskCauseText {{ color: {t.text_secondary}; font-size: 13.5px; }}
{root} QPushButton#taskCauseFilter {{ min-height: 26px; max-height: 26px; padding: 0 11px; border-radius: 12px;
    background: {t.surface_elevated}; color: {t.accent_text}; border: 0; font-size: 12.5px; font-weight: 700; }}
{root} QPushButton#taskCauseFilter:hover {{ background: {t.accent_soft}; }}
{root} QFrame#taskTableCard QHeaderView {{ background: transparent; border: 0; }}
{root} QFrame#taskTableCard QHeaderView::section {{ background: transparent; color: {t.text_muted}; border: 0;
    border-bottom: 1px solid {t.border}; padding: 0 12px; font-size: 12.5px; font-weight: 400; min-height: 30px; }}
{root} QTableView#taskTable {{ background: transparent; border: 0; outline: 0; gridline-color: transparent;
    selection-background-color: transparent; selection-color: {t.text}; font-size: 14px; }}
{root} QTableView#taskTable::item {{ border: 0; padding: 0; background: transparent; }}
{root} QLabel#taskDetailTitle {{ color: {t.text_muted}; font-size: 12.5px; background: transparent; }}
{root} QLabel#taskSegment {{ background: {t.input_surface}; color: {t.text}; border-radius: 10px; padding: 3px 10px;
    font-size: 13.5px; }}
{root} QLabel#taskDetailEmpty {{ color: {t.text_muted}; font-size: 13px; background: transparent; }}
{root} QLabel#taskPlaceholder {{ border: 2px dashed {t.border}; border-radius: 16px; color: {t.text_muted};
    font-size: 14px; background: transparent; }}
{root} QFrame#taskNext {{ border-radius: 14px; border: 0; }}
{root} QFrame#taskNext QLabel {{ background: transparent; }}
{root} QLabel#taskNextLead {{ font-weight: 800; font-size: 13.5px; }}
{root} QLabel#taskNextText {{ color: {t.text_secondary}; font-size: 13.5px; }}
{root} QPushButton#taskRawToggle {{ background: transparent; border: 0; color: {t.text_muted}; font-size: 12.5px;
    padding: 0 2px; min-height: 22px; text-align: left; }}
{root} QPushButton#taskRawToggle:hover {{ color: {t.accent_text}; }}
{root} QPlainTextEdit#taskRaw {{ background: {t.input_surface}; color: {t.text_secondary}; border: 0; border-radius: 14px;
    padding: 8px; font-family: Consolas, monospace; font-size: 12px; }}
{root} QScrollArea#taskSegments, {root} QWidget#taskSegmentsBody {{ background: transparent; border: 0; }}
{root} QLabel#taskWhy {{ color: {t.text_muted}; font-size: 13px; background: transparent; }}
{root} QPushButton#taskAction, {root} QPushButton#taskPrimary, {root} QPushButton#taskDanger {{
    min-height: 36px; max-height: 36px; padding: 0 16px; border-radius: 14px; font-size: 14px;
    background: {t.surface_elevated}; color: {t.text}; border: 2px solid {t.border}; }}
{root} QPushButton#taskAction:hover, {root} QPushButton#taskDanger:hover {{ border-color: {t.border_strong}; }}
{root} QPushButton#taskDanger {{ color: {danger[2]}; }}
{root} QPushButton#taskDanger:hover {{ background: {danger[1]}; border-color: {danger[0]}; }}
{root} QPushButton#taskPrimary {{ background: {t.accent}; color: {t.text_on_accent}; border-color: {t.accent}; font-weight: 700; }}
{root} QPushButton#taskPrimary:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover}; }}
{root} QPushButton#taskAction:disabled, {root} QPushButton#taskDanger:disabled {{ color: {t.disabled};
    background: {t.surface}; border-color: {t.border}; }}
{root} QPushButton#taskAction:focus, {root} QPushButton#taskPrimary:focus, {root} QPushButton#taskDanger:focus,
{root} QPushButton#taskChip:focus, {root} QPushButton#taskPill:focus {{ outline: 0; }}
""" + '\n'.join(chips)


__all__ = ['STATUS_ORDER', 'build_task_panel_qss', 'status_tones']
