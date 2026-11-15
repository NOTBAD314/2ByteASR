# SPDX-License-Identifier: GPL-3.0-only
"""Styles and step colours of the API 用量与估算费用 window.

2026-11-14 (user picked design 3, 日历糖果): the same rounded cards, candy
chips and status badges as the 字幕任务 window, with a calendar of daily
spend and a task list. Every colour comes from the active theme.
"""
from __future__ import annotations

from .task_panel_qss import _blend, _readable, _SUGGESTION_DARK, _SUGGESTION_LIGHT, status_tones
from .candy_chrome_qss import build_candy_chrome_qss
from .typography import emphasized

STEPS = ('断句', '校对', '翻译', '连接测试', '其他')
STEP_KEYS = {'断句': 'seg', '校对': 'proof', '翻译': 'tr', '连接测试': 'test', '其他': 'other'}


def step_tones(t) -> dict[str, tuple[str, str, str]]:
    """``step -> (solid, soft, ink)`` for bars, chips and badges."""
    from .ui_theme import contrast_ratio
    solids = {'断句': t.focus, '校对': t.success, '翻译': t.accent,
              '连接测试': _SUGGESTION_LIGHT if t.is_light else _SUGGESTION_DARK, '其他': t.text_muted}
    tones = {}
    for step, solid in solids.items():
        for amount in ((.15, .24) if t.is_light else (.24, .16, .08)):
            soft = _blend(t.surface_elevated, solid, amount)
            ink = _readable(solid, soft, t.text)
            if contrast_ratio(ink, soft) >= 4.5:
                break
        tones[step] = (solid, soft, ink)
    return tones


@emphasized
def build_usage_dialog_qss(t) -> str:
    root = 'QDialog#apiUsageDialog'
    steps, status = step_tones(t), status_tones(t)
    hover = _blend(t.surface_elevated, t.text, .05 if t.is_light else .08)
    rules = []
    for step, (solid, soft, ink) in steps.items():
        key = STEP_KEYS[step]
        rules.append(f"""{root} QPushButton#usageChip[tone="{key}"] {{ background: {soft}; color: {ink}; }}
{root} QPushButton#usageChip[tone="{key}"]:checked {{ border-color: {solid}; }}""")
    warn = status['review']
    rules.append(f"""{root} QPushButton#usageChip[tone="warn"] {{ background: {warn[1]}; color: {warn[2]}; }}
{root} QPushButton#usageChip[tone="warn"]:hover {{ border-color: transparent; }}""")
    for key, tone in (('note', None), ('row', None), ('warn', warn)):
        soft, ink = (tone[1], tone[2]) if tone else (t.panel, t.accent_text)
        rules.append(f"""{root} QFrame#usageNext[tone="{key}"] {{ background: {soft}; }}
{root} QFrame#usageNext[tone="{key}"] QLabel#usageNextLead {{ color: {ink}; }}""")
    danger = status['failed']
    return f"""
{build_candy_chrome_qss(root, t)}
{root} QFrame#usageHead, {root} QFrame#usageRail, {root} QFrame#usageTableCard {{
    background: {t.surface_elevated}; border: 1px solid {t.border}; border-radius: 18px; }}
{root} QFrame#usageHead QLabel, {root} QFrame#usageRail QLabel {{ background: transparent; }}
{root} QLabel#usageScopeTitle {{ font-size: 18px; font-weight: 800; color: {t.accent_text}; }}
{root} QLabel#usageRangeTitle {{ font-size: 14px; color: {t.text_muted}; }}
{root} QLabel#usageMoney {{ font-size: 30px; font-weight: 800; color: {t.accent_text}; }}
{root} QLabel#usageFacts {{ font-size: 13.5px; color: {t.text_secondary}; }}
{root} QLabel#usageHint {{ font-size: 12.5px; color: {t.text_muted}; }}
{root} QLabel#usageRailTitle {{ font-size: 12px; color: {t.text_muted}; padding: 4px 6px 0 6px; }}
{root} QPushButton#usageRangeSeg {{ min-height: 24px; max-height: 24px; padding: 0 9px; border-radius: 12px; border: 0;
    background: {t.input_surface}; color: {t.text_secondary}; font-size: 12px; }}
{root} QPushButton#usageRangeSeg:hover {{ background: {t.selected}; }}
{root} QPushButton#usageRangeSeg:checked {{ background: {t.accent}; color: {t.text_on_accent}; font-weight: 700; }}
{root} QPushButton#usageChip {{ min-height: 28px; max-height: 28px; padding: 0 12px 0 6px; border-radius: 14px;
    border: 2px solid transparent; font-size: 13.5px; text-align: left; }}
{root} QPushButton#usageChip[tone="all"] {{ padding-left: 12px; background: {t.input_surface}; color: {t.text_secondary}; }}
{root} QPushButton#usageChip[tone="all"]:checked {{ border-color: {t.text_secondary}; }}
{root} QPushButton#usageChip:hover {{ border-color: {t.border_strong}; }}
{root} QPushButton#usageChip:checked {{ font-weight: 700; }}
{root} QPushButton#usageTodo {{ min-height: 30px; max-height: 30px; padding: 0 14px; border-radius: 15px;
    border: 2px solid {danger[0]}; background: {danger[1]}; color: {danger[2]}; font-size: 13.5px; font-weight: 700; }}
{root} QPushButton#usageTodo:checked {{ background: {danger[0]}; color: {t.surface_elevated}; }}
{root} QListWidget#usageTasks {{ background: transparent; border: 0; outline: 0; }}
{root} QListWidget#usageTasks::item {{ border: 0; background: transparent; }}
{root} QFrame#usageTableCard QHeaderView {{ background: transparent; border: 0; }}
{root} QFrame#usageTableCard QHeaderView::section {{ background: transparent; color: {t.text_muted}; border: 0;
    border-bottom: 1px solid {t.border}; padding: 0 12px; font-size: 12.5px; font-weight: 400; min-height: 30px; }}
{root} QTableView#usageTable {{ background: transparent; border: 0; outline: 0; gridline-color: transparent;
    selection-background-color: transparent; selection-color: {t.text}; font-size: 14px; }}
{root} QTableView#usageTable::item {{ border: 0; padding: 0; background: transparent; }}
{root} QFrame#usageNext {{ border-radius: 14px; border: 0; }}
{root} QFrame#usageNext QLabel {{ background: transparent; }}
{root} QLabel#usageNextLead {{ font-weight: 800; font-size: 13.5px; }}
{root} QLabel#usageNextText {{ color: {t.text_secondary}; font-size: 13.5px; }}
{root} QPushButton#usageLink {{ background: transparent; border: 0; color: {t.text_muted}; font-size: 12.5px; padding: 0 2px; min-height: 22px; }}
{root} QPushButton#usageLink:hover {{ color: {t.accent_text}; }}
{root} QPushButton#usageAction, {root} QPushButton#usagePrimary {{
    min-height: 36px; max-height: 36px; padding: 0 16px; border-radius: 14px; font-size: 14px;
    background: {t.surface_elevated}; color: {t.text}; border: 2px solid {t.border}; }}
{root} QPushButton#usageAction:hover {{ border-color: {t.border_strong}; background: {hover}; }}
{root} QPushButton#usageAction:disabled {{ color: {t.disabled}; background: {t.surface}; border-color: {t.border}; }}
{root} QPushButton#usagePrimary {{ background: {t.accent}; color: {t.text_on_accent}; border-color: {t.accent}; font-weight: 700; }}
{root} QPushButton#usagePrimary:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover}; }}
{root} QPushButton#usageAction:focus, {root} QPushButton#usagePrimary:focus, {root} QPushButton#usageChip:focus,
{root} QPushButton#usageRangeSeg:focus, {root} QPushButton#usageTodo:focus {{ outline: 0; }}
""" + '\n'.join(rules)


__all__ = ['STEPS', 'STEP_KEYS', 'build_usage_dialog_qss', 'step_tones']
