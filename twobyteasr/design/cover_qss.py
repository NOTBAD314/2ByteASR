"""Styles of the cover template picker and cover editor (2026-11-27, drafts B 大圖預覽 + A 圓角工具箱).

Emphasis (2026-11-27, user: labels in the plain face were hard to read and nothing stood
out): every rule with font-weight 800 goes through ``emphasis_qss`` and so uses the real
思源黑体 Heavy face; body text stays Medium.

``root`` is the dialog selector (``QDialog#coverTemplatePicker`` / ``QDialog#coverEditor``). Both
windows sit in ``app/candy_chrome.CandyChrome``; its frame is styled by ``candy_chrome_qss``.
Everything is rounded: 12 px buttons, 10 px inputs, 16 px cards, pills for chips and the zoom bar.
"""
from __future__ import annotations


def _parts(t):
    from .ui_theme import blend_hex
    soft = t.accent_soft
    card = t.surface_elevated
    sunk = blend_hex(t.surface, t.app_background, .55)
    hover = blend_hex(card, t.text, .06 if t.is_light else .08)
    line = t.border
    return soft, card, sunk, hover, line


def build_cover_common_qss(root: str, t) -> str:
    from .typography import UI_FONT_STACK, emphasis_qss
    from .ui_theme import blend_hex
    soft, card, sunk, hover, line = _parts(t)
    deep = t.accent_pressed
    return emphasis_qss(f"""
{root} QWidget {{ font-family: {UI_FONT_STACK}; font-size: 13px; color: {t.text}; }}
{root} QLabel {{ background: transparent; border: 0; padding: 0; }}
{root} QPushButton#coverButton, {root} QPushButton#coverGhost, {root} QPushButton#coverSoft, {root} QPushButton#coverPrimary {{
    min-height: 32px; padding: 0 14px; border-radius: 12px; border: 1px solid {line}; background: {card}; font-weight: 800; }}
{root} QPushButton#coverButton:hover {{ border-color: {t.border_strong}; background: {hover}; }}
{root} QPushButton#coverButton:pressed {{ background: {soft}; }}
{root} QPushButton#coverButton:disabled, {root} QPushButton#coverGhost:disabled {{ color: {t.disabled}; }}
{root} QPushButton#coverGhost {{ background: transparent; border-color: transparent; color: {t.text_secondary}; }}
{root} QPushButton#coverGhost:hover {{ background: {hover}; }}
{root} QPushButton#coverSoft {{ background: {soft}; border-color: transparent; color: {blend_hex(t.accent, t.text, .12 if t.is_light else .5)}; }}
{root} QPushButton#coverSoft:hover {{ background: {blend_hex(soft, t.accent, .12)}; }}
{root} QPushButton#coverPrimary {{ background: {t.accent}; border: 0; border-bottom: 2px solid {deep}; color: {t.surface if t.is_light else '#fff6f9'}; font-weight: 800; }}
{root} QPushButton#coverPrimary:hover {{ background: {t.accent_hover}; }}
{root} QPushButton#coverPrimary:pressed {{ background: {deep}; }}
{root} QPushButton#coverPrimary:disabled {{ background: {blend_hex(t.accent, t.surface, .55)}; border-bottom-color: transparent; }}
{root} QToolButton#coverIconButton {{ border: 0; border-radius: 10px; background: transparent; }}
{root} QToolButton#coverIconButton:hover {{ background: {hover}; }}
{root} QToolButton#coverIconButton:checked {{ background: {soft}; }}
{root} QToolButton#coverIconButton:disabled {{ background: transparent; }}
{root} QFrame#coverSegmented {{ background: {sunk}; border: 1px solid {line}; border-radius: 11px; }}
{root} QPushButton#coverSegment {{ min-height: 26px; padding: 0 7px; border: 0; border-radius: 9px; background: transparent; color: {t.text_muted}; font-size: 12px; }}
{root} QPushButton#coverSegment:hover {{ color: {t.text}; }}
{root} QPushButton#coverSegment:checked {{ background: {card}; color: {t.text}; font-weight: 800; }}
{root} QLineEdit, {root} QPlainTextEdit, {root} QComboBox, {root} QDoubleSpinBox, {root} QSpinBox {{
    background: {t.input_surface}; border: 1px solid {line}; border-radius: 10px; padding: 4px 8px; selection-background-color: {t.accent}; }}
{root} QLineEdit:focus, {root} QPlainTextEdit:focus, {root} QComboBox:focus, {root} QDoubleSpinBox:focus {{ border-color: {t.accent}; }}
{root} QComboBox::drop-down {{ border: 0; width: 22px; }}
{root} QDoubleSpinBox::up-button, {root} QDoubleSpinBox::down-button {{ width: 0; border: 0; }}
{root} QSlider#coverSlider::groove:horizontal {{ height: 4px; border-radius: 2px; background: {t.border_strong}; }}
{root} QSlider#coverSlider::sub-page:horizontal {{ height: 4px; border-radius: 2px; background: {t.accent}; }}
{root} QSlider#coverSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -6px 0; border-radius: 8px; background: #ffffff; border: 2px solid {t.accent}; }}
{root} QLabel#coverSliderValue {{ color: {t.text_secondary}; font-size: 12px; }}
{root} QLabel#coverRowLabel {{ color: {t.text_secondary}; font-size: 12px; font-weight: 800; }}
{root} QLabel#coverSectionTitle {{ font-weight: 800; font-size: 14px; }}
{root} QLabel#coverDialogTitle {{ font-weight: 800; font-size: 18px; }}
{root} QLabel#coverHint {{ color: {t.text_muted}; font-size: 12px; }}
{root} QCheckBox {{ background: transparent; spacing: 6px; }}
{root} QScrollArea, {root} QScrollArea > QWidget > QWidget, {root} QStackedWidget, {root} QStackedWidget > QWidget {{ background: transparent; border: 0; }}
{root} QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
{root} QScrollBar::handle:vertical {{ background: {t.border_strong}; border-radius: 3px; min-height: 30px; }}
{root} QScrollBar::add-line, {root} QScrollBar::sub-line {{ height: 0; width: 0; }}
{root} QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
{root} QScrollBar::handle:horizontal {{ background: {t.border_strong}; border-radius: 3px; min-width: 30px; }}
{root} QMenu {{ background: {card}; border: 1px solid {line}; border-radius: 12px; padding: 6px; }}
{root} QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 8px; }}
{root} QMenu::item:selected {{ background: {hover}; }}
{root} QMenu::separator {{ height: 1px; background: {line}; margin: 4px 8px; }}
""")


def build_picker_qss(root: str, t) -> str:
    from .typography import emphasis_qss
    from .ui_theme import blend_hex
    soft, card, sunk, hover, line = _parts(t)
    return emphasis_qss(build_cover_common_qss(root, t) + f"""
{root} QFrame#pickerLeft {{ background: {blend_hex(t.surface, t.app_background, .35)}; border: 0; border-top-left-radius: 0; border-right: 1px solid {line}; }}
{root} QLineEdit#pickerSearch {{ min-height: 34px; border-radius: 17px; padding: 0 14px; background: {card}; }}
{root} QPushButton#pickerChip {{ min-height: 28px; padding: 0 12px; border-radius: 14px; border: 1px solid {line}; background: transparent; color: {t.text_secondary}; font-size: 12px; }}
{root} QPushButton#pickerChip:hover {{ border-color: {t.border_strong}; }}
{root} QPushButton#pickerChip:checked {{ background: {soft}; border-color: transparent; color: {t.accent}; font-weight: 800; }}
{root} QPushButton#pickerNew {{ min-height: 58px; border: 1.5px dashed {t.border_strong}; border-radius: 13px; background: transparent; text-align: left; padding: 0 12px; color: {t.text}; font-weight: 800; }}
{root} QPushButton#pickerNew:hover {{ background: {card}; }}
{root} QListWidget#pickerList {{ background: transparent; border: 0; outline: 0; }}
{root} QListWidget#pickerList::item {{ border: 1px solid transparent; border-radius: 13px; padding: 2px; margin: 1px 0; color: {t.text}; }}
{root} QListWidget#pickerList::item:hover {{ background: {card}; }}
{root} QListWidget#pickerList::item:selected {{ background: {card}; border-color: {t.accent}; color: {t.text}; }}
{root} QLabel#pickerName {{ font-size: 17px; font-weight: 800; }}
{root} QLineEdit#pickerNameEdit {{ font-size: 16px; font-weight: 700; padding: 2px 8px; }}
{root} QLabel#pickerSize {{ color: {t.text_muted}; font-size: 12px; }}
{root} QFrame#pickerStage {{ background: {sunk}; border: 1px solid {line}; border-radius: 18px; }}
{root} QFrame#pickerConfirm {{ background: {card}; border: 1px solid {line}; border-radius: 16px; }}
{root} QLabel#pickerFieldLabel {{ color: {t.text_secondary}; font-size: 12.5px; font-weight: 800; }}
{root} QLabel#pickerFieldHint {{ color: {t.text_muted}; font-size: 12px; }}
{root} QLabel#pickerKeepTitle, {root} QLabel#pickerFootTitle {{ color: {t.text}; font-weight: 800; }}
{root} QLabel#pickerFootNote {{ color: {t.text_muted}; font-size: 12px; }}
{root} QLabel#pickerKeep {{ background: {blend_hex(t.surface, t.success, .16)}; color: {t.success}; border-radius: 10px; padding: 2px 9px; font-size: 12px; font-weight: 800; }}
{root} QLabel#pickerSwap {{ background: {blend_hex(t.surface, t.accent, .14)}; color: {t.accent}; border-radius: 10px; padding: 2px 9px; font-size: 12px; font-weight: 800; }}
{root} QFrame#pickerFoot {{ background: {blend_hex(t.surface, t.app_background, .35)}; border: 0; border-top: 1px solid {line}; }}
{root} QLabel#pickerEmpty {{ color: {t.text_muted}; }}
""")


def build_editor_qss(root: str, t) -> str:
    from .typography import emphasis_qss
    from .ui_theme import blend_hex
    soft, card, sunk, hover, line = _parts(t)
    return emphasis_qss(build_cover_common_qss(root, t) + f"""
{root} QFrame#coverToolGroup {{ background: {blend_hex(t.surface, t.app_background, .4)}; border: 1px solid {line}; border-radius: 13px; }}
{root} QFrame#coverToolGroup QToolButton {{ min-height: 30px; padding: 0 10px; border: 0; border-radius: 10px; background: transparent; color: {t.text}; font-weight: 800; }}
{root} QFrame#coverToolGroup QToolButton:hover {{ background: {card}; color: {t.text}; }}
{root} QFrame#coverToolGroup QToolButton::menu-indicator {{ image: none; width: 0; }}
{root} QToolBar#coverToolbar {{ background: transparent; border: 0; spacing: 10px; padding: 0; }}
{root} QFrame#coverRail {{ background: transparent; border: 0; }}
{root} QFrame#coverRail QToolButton#coverIconButton {{ border-radius: 14px; }}
{root} QFrame#coverRailSeparator {{ background: {line}; }}
{root} QFrame#coverMat {{ background: {sunk}; border: 0; border-top-left-radius: 18px; border-top-right-radius: 18px; }}
{root} QGraphicsView#coverCanvas {{ background: transparent; border: 0; }}
{root} QFrame#coverZoomPill, {root} QFrame#coverFeedCard {{ background: {card}; border: 1px solid {line}; border-radius: 14px; }}
{root} QLabel#coverZoomValue {{ color: {t.text}; font-size: 12px; font-weight: 800; }}
{root} QPushButton#coverPillText {{ min-height: 26px; padding: 0 8px; border: 0; border-radius: 9px; background: transparent; color: {t.text_secondary}; font-size: 12px; font-weight: 800; }}
{root} QPushButton#coverPillText:hover {{ background: {hover}; }}
{root} QPushButton#coverPillText:checked {{ background: {soft}; color: {t.accent}; }}
{root} QFrame#coverPillSeparator {{ background: {line}; }}
{root} QLabel#coverFeedCaption {{ color: {t.text_secondary}; font-size: 11.5px; font-weight: 800; }}
{root} QToolButton#coverFeedIcon {{ border: 0; background: transparent; }}
{root} QFrame#coverCard {{ background: {card}; border: 1px solid {line}; border-radius: 16px; }}
{root} QListWidget#coverLayers {{ background: transparent; border: 0; outline: 0; }}
{root} QListWidget#coverLayers::item {{ border-radius: 11px; color: {t.text}; }}
{root} QListWidget#coverLayers::item:hover {{ background: {hover}; }}
{root} QListWidget#coverLayers::item:selected {{ background: {soft}; color: {t.text}; }}
{root} QListWidget#coverLayers QLineEdit {{ padding: 1px 4px; border-radius: 6px; }}
{root} QFrame#coverStatusBar {{ border: 0; border-top: 1px solid {line}; background: transparent; }}
{root} QLabel#coverStatus {{ color: {t.text_muted}; font-size: 12px; }}
{root} QSplitter::handle {{ background: transparent; width: 6px; }}
""")


__all__ = ['build_cover_common_qss', 'build_editor_qss', 'build_picker_qss']
