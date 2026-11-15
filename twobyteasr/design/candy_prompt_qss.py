"""Styles of ``app/candy_prompt.CandyPrompt`` and its two windows (2026-11-15).

「三颗糖」 (save before leaving): three big rounded tiles in clearly different colours — the accent
for 保存 (with a thicker bottom edge, like a pressable candy), soft red for 不保存, plain for 取消.
「两张卡片」 (recovery): two version cards; the newer autosave is the tinted one.
"""
from __future__ import annotations

from .candy_chrome_qss import build_candy_chrome_qss


def build_candy_prompt_qss(root: str, t) -> str:
    from .ui_theme import blend_hex
    hover_plain = blend_hex(t.input_surface, t.text, .05 if t.is_light else .08)
    accent_low = blend_hex(t.accent, '#000000', .22)
    return build_candy_chrome_qss(root, t) + f"""
{root} QLabel {{ background: transparent; }}
{root} QLabel#candyHeading {{ color: {t.text}; font-size: 20px; font-weight: 800; }}
{root} QLabel#candySub {{ color: {t.text_secondary}; font-size: 14px; }}
{root} QLabel#candyMuted {{ color: {t.text_muted}; font-size: 13px; }}
{root} QLabel#candyError {{ color: {t.danger}; background: {t.danger_soft}; border-radius: 12px; padding: 6px 12px;
    font-size: 13px; }}

{root} QPushButton#candyTile {{ border-radius: 18px; border: 2px solid transparent; padding: 0; text-align: center;
    min-height: 64px; max-height: 16777215px; min-width: 0; }}
{root} QPushButton#candyTile[tone="save"] {{ background: {t.accent}; border-color: {t.accent};
    border-bottom: 5px solid {accent_low}; }}
{root} QPushButton#candyTile[tone="save"]:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover};
    border-bottom: 5px solid {accent_low}; }}
{root} QPushButton#candyTile[tone="save"]:pressed {{ background: {t.accent_pressed}; border-bottom: 2px solid {accent_low}; }}
{root} QPushButton#candyTile[tone="save"] QLabel {{ color: {t.text_on_accent}; }}
{root} QPushButton#candyTile[tone="drop"] {{ background: {t.danger_soft}; border-color: {blend_hex(t.danger_soft, t.danger, .35)}; }}
{root} QPushButton#candyTile[tone="drop"]:hover {{ border-color: {t.danger}; }}
{root} QPushButton#candyTile[tone="drop"]:pressed {{ background: {blend_hex(t.danger_soft, t.danger, .2)}; }}
{root} QPushButton#candyTile[tone="drop"] QLabel {{ color: {t.danger}; }}
{root} QPushButton#candyTile[tone="back"] {{ background: {t.input_surface}; border-color: {t.border}; }}
{root} QPushButton#candyTile[tone="back"]:hover {{ background: {hover_plain}; border-color: {t.border_strong}; }}
{root} QPushButton#candyTile[tone="back"]:pressed {{ background: {blend_hex(hover_plain, t.text, .06)}; }}
{root} QPushButton#candyTile[tone="back"] QLabel {{ color: {t.text_secondary}; }}
{root} QPushButton#candyTile:focus {{ outline: 0; }}
{root} QPushButton#candyTile[tone="back"]:focus, {root} QPushButton#candyTile[tone="drop"]:focus {{ border-color: {t.focus}; }}
{root} QLabel#candyTileTitle {{ font-size: 16px; font-weight: 800; }}
{root} QLabel#candyTileNote {{ font-size: 12px; }}
{root} QLabel#candyBadge {{ background: {t.warning_soft}; color: {t.warning}; border: 1px solid {t.warning};
    border-radius: 8px; padding: 1px 8px; font-size: 11.5px; font-weight: 700; }}

{root} QPushButton[card="true"] {{ border-radius: 22px; border: 2px solid {t.border}; background: {t.surface_elevated};
    padding: 0; text-align: left; min-height: 140px; max-height: 16777215px; min-width: 0; }}
{root} QPushButton[card="true"]:hover {{ border-color: {t.accent}; }}
{root} QPushButton[card="true"]:pressed {{ background: {t.selected}; }}
{root} QPushButton[card="true"]:focus {{ outline: 0; border-color: {t.accent}; }}
{root} QPushButton[card="true"][newer="true"] {{ background: {t.accent_soft}; border-color: {t.accent};
    border-bottom: 5px solid {blend_hex(t.accent, t.surface, .45)}; }}
{root} QPushButton[card="true"][newer="true"]:pressed {{ border-bottom: 2px solid {blend_hex(t.accent, t.surface, .45)}; }}
{root} QPushButton[card="true"][newer="true"]:focus {{ border-color: {t.accent}; }}
{root} QLabel#recoveryKind {{ color: {t.text_muted}; font-size: 13px; }}
{root} QLabel#recoveryTime {{ color: {t.text}; font-size: 28px; font-weight: 800; }}
{root} QLabel#recoveryDay {{ color: {t.text_secondary}; font-size: 13px; }}
{root} QLabel#recoveryGo {{ color: {t.accent_text}; font-size: 14.5px; font-weight: 800; }}
{root} QLabel#recoveryRibbon {{ background: {t.accent}; color: {t.text_on_accent}; border-radius: 8px; padding: 1px 10px;
    font-size: 12px; font-weight: 700; }}
{root} QCheckBox#recoveryAlways {{ color: {t.text_secondary}; font-size: 13.5px; spacing: 8px; background: transparent; }}
{root} QCheckBox#recoveryAlways::indicator {{ width: 18px; height: 18px; border-radius: 7px; border: 2px solid {t.border_strong};
    background: {t.surface_elevated}; }}
{root} QCheckBox#recoveryAlways::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; }}
{root} QPushButton#recovery_ignore {{ background: transparent; border: 0; color: {t.text_muted}; font-size: 13.5px;
    text-decoration: underline; padding: 4px 6px; min-height: 0; min-width: 0; }}
{root} QPushButton#recovery_ignore:hover {{ color: {t.danger}; }}
{root} QPushButton#recovery_ignore:focus {{ outline: 0; color: {t.danger}; }}
"""


__all__ = ['build_candy_prompt_qss']
