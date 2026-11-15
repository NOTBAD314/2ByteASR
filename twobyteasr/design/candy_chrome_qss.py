"""Styles of ``app/candy_chrome.CandyChrome``: the candy windows' own round frame (2026-11-15).

``root`` is the dialog's selector (``QDialog#subtitleTaskPanel``). The dialog itself stays
transparent (its shadow margin must be see-through); the rounded ``candyRoot`` carries the surface.
"""
from __future__ import annotations


def build_candy_chrome_qss(root: str, t) -> str:
    from .ui_theme import blend_hex
    button = t.input_surface
    hover = t.accent_soft
    return f"""
{root} {{ background: transparent; color: {t.text}; }}
{root} QFrame#candyRoot {{ background: {t.surface}; border: 0; }}
{root} QWidget#candyBody {{ background: transparent; }}
{root} QFrame#candyTitleBar {{ background: transparent; border: 0; }}
{root} QLabel#candyMark {{ background: {t.accent}; border-radius: 14px; }}
{root} QLabel#candyTitle {{ color: {t.text}; font-size: 15px; font-weight: 800; background: transparent; }}
{root} QFrame#candyTitleBar QPushButton#windowControl, {root} QFrame#candyTitleBar QPushButton#windowControlClose {{
    background: {button}; border: 1px solid {blend_hex(button, t.border, .6)}; border-radius: 15px; padding: 0; }}
{root} QFrame#candyTitleBar QPushButton#windowControl:hover {{ background: {hover}; border-color: {t.accent}; }}
{root} QFrame#candyTitleBar QPushButton#windowControlClose:hover {{ background: {t.danger_soft}; border-color: {t.danger}; }}
{root} QFrame#candyTitleBar QPushButton#windowControl:pressed {{ background: {blend_hex(hover, t.accent, .25)}; }}
{root} QFrame#candyTitleBar QPushButton#windowControlClose:pressed {{ background: {blend_hex(t.danger_soft, t.danger, .3)}; }}
"""


__all__ = ['build_candy_chrome_qss']
