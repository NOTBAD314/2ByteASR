"""Soft filled controls for Subtitle Studio (2026-10-23).

The user picked these from the redesign canvas: fields are filled wells with
no outline; a dropdown carries a round accent chip with its arrow; a field
inside a :class:`~twobyteasr.design.soft_widgets.CaptionField` shows its
caption inside and a plain arrow; segments, filter chips, check boxes,
switches and buttons are tonal fills, the chosen item in the accent colour;
settings groups are cards without a frame. Appended last onto the Studio page
sheet (``build_studio_qss``) and onto the popup / dialog sheet, so these rules
win over the older outlined ones of the same specificity.

Qt draws a style sheet ``border-radius`` larger than half the box as a square
corner, so every radius here is at most half its box minus one.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .ui_theme import blend_hex, contrast_ratio

_ICON_DIR = Path(tempfile.gettempdir()) / "2byteasr-qss-icons"


@dataclass(frozen=True)
class SoftTokens:
    fill: str           # a field or secondary button on the panel
    fill_hover: str
    fill_strong: str    # switch track / slider groove / unchecked box
    fill_disabled: str
    card: str           # a settings card on the panel
    raised: str         # the chosen chip inside a filled track
    card_fill: str      # a field inside a card
    card_fill_hover: str
    chip: str           # accent wash: chosen tab, tinted button, arrow chip
    chip_hover: str
    primary_disabled: str
    ok: str
    ok_tint: str
    warn: str
    warn_tint: str


def soft_tokens(t) -> SoftTokens:
    light = t.is_light
    base = t.panel
    card = t.surface_elevated
    return SoftTokens(
        fill=blend_hex(base, t.text, 0.07 if light else 0.08),
        fill_hover=blend_hex(base, t.text, 0.11 if light else 0.13),
        fill_strong=blend_hex(base, t.text, 0.16 if light else 0.2),
        fill_disabled=blend_hex(base, t.text, 0.04),
        card=card,
        raised=card if light else blend_hex(base, t.text, 0.2),
        card_fill=blend_hex(card, t.text, 0.07 if light else 0.08),
        card_fill_hover=blend_hex(card, t.text, 0.11 if light else 0.13),
        chip=blend_hex(base, t.accent, 0.15 if light else 0.24),
        chip_hover=blend_hex(base, t.accent, 0.24 if light else 0.34),
        primary_disabled=blend_hex(base, t.accent, 0.42),
        ok=t.success, ok_tint=blend_hex(base, t.success, 0.16 if light else 0.2),
        warn=t.warning, warn_tint=blend_hex(base, t.warning, 0.16 if light else 0.2),
    )


def preview_stage(t) -> tuple[str, str]:
    """Top and bottom of a small video stage (motion previews, the 视频 canvas
    pad), from the theme instead of one navy for every theme (2026-10-24).

    Dark themes keep a dark stage, their video colour lifted with a little
    accent. Light themes get the lightest tone between their panel and video
    colour (warmed by the accent) on which white caption text still has
    4.5:1 contrast, so white fills and dark outlines both read.
    """
    if not t.is_light:
        return blend_hex(t.media, t.accent, 0.22), t.media
    tone = t.media
    for step in range(51):
        tone = blend_hex(blend_hex(t.panel, t.media, step / 50), t.accent, 0.18)
        if contrast_ratio("#ffffff", tone) >= 4.5:
            break
    return tone, blend_hex(tone, t.media, 0.35)


def qss_svg(name: str, svg: str) -> str:
    """Path of a small SVG for ``url()`` in a style sheet (written once to temp)."""
    digest = hashlib.sha1(svg.encode("utf-8")).hexdigest()[:12]
    path = _ICON_DIR / f"{name}-{digest}.svg"
    if not path.exists():
        _ICON_DIR.mkdir(parents=True, exist_ok=True)
        part = path.with_name(f"{path.stem}.{os.getpid()}.part")
        part.write_text(svg, "utf-8")
        os.replace(part, path)
    return path.as_posix()


def _chevron(color: str, up: bool = False) -> str:
    d = "M3.5 10 L8 5.5 L12.5 10" if up else "M3.5 6 L8 10.5 L12.5 6"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" '
            f'stroke-linejoin="round"/></svg>')


def _check(color: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
            f'<path d="M3.6 8.4 L6.6 11.3 L12.4 4.9" fill="none" stroke="{color}" stroke-width="2.2" '
            f'stroke-linecap="round" stroke-linejoin="round"/></svg>')


def _switch(track: str, knob: str, on: bool) -> str:
    cx = 26 if on else 10
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="36" height="20" viewBox="0 0 36 20">'
            f'<rect x="0" y="0" width="36" height="20" rx="10" fill="{track}"/>'
            f'<circle cx="{cx}" cy="10" r="7" fill="{knob}"/></svg>')


def _knob(ring: str, centre: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18">'
            f'<circle cx="9" cy="9" r="9" fill="{ring}"/><circle cx="9" cy="9" r="5" fill="{centre}"/></svg>')


def control_icons(t) -> dict[str, str]:
    k = soft_tokens(t)
    knob = "#ffffff" if t.is_light else blend_hex(t.text, t.panel, 0.08)
    return {
        "chevron": qss_svg("chevron", _chevron(t.accent_text)),
        "chevron_up": qss_svg("chevron", _chevron(t.accent_text, up=True)),
        "chevron_muted": qss_svg("chevron", _chevron(t.text_muted)),
        "chevron_disabled": qss_svg("chevron", _chevron(t.disabled)),
        "check": qss_svg("check", _check(t.text_on_accent)),
        "switch_off": qss_svg("switch", _switch(k.fill_strong, knob, False)),
        "switch_on": qss_svg("switch", _switch(t.accent, "#ffffff", True)),
        "switch_off_disabled": qss_svg("switch", _switch(k.fill_disabled, k.fill_strong, False)),
        "switch_on_disabled": qss_svg("switch", _switch(k.primary_disabled, "#ffffff", True)),
        "knob": qss_svg("knob", _knob(t.accent, "#ffffff")),
        "knob_disabled": qss_svg("knob", _knob(k.fill_strong, k.fill_disabled)),
    }


def _sel(scopes, *parts) -> str:
    return ",\n".join(f"{scope} {part}".strip() for scope in scopes for part in parts)


def build_soft_studio_qss(t) -> str:
    k = soft_tokens(t)
    icon = control_icons(t)
    # Every Studio area with input boxes; plain selectors cover the rest.
    areas = ("QFrame#contextPanel", "QFrame#cueListPanel", "QFrame#timelineHost", "QFrame#studioToolbar", "")
    fields = ("QComboBox", "QLineEdit", "QAbstractSpinBox")
    panel = "QFrame#contextPanel"
    card = f'{panel} QFrame[softCard="true"]'
    caption = "QFrame#softCaptionField"
    bar = "QFrame#studioToolbar QFrame#studioToolTrack"
    track = blend_hex(t.shell, t.text, 0.06 if t.is_light else 0.07)
    track_hover = blend_hex(t.shell, t.text, 0.11 if t.is_light else 0.13)
    track_pressed = blend_hex(t.shell, t.text, 0.15 if t.is_light else 0.18)
    return f"""
/* ---- fields: filled wells, no outline (A) ---- */
{_sel(areas, *fields)} {{
    background: {k.fill}; color: {t.text}; border: 1px solid transparent; border-radius: 9px;
    padding: 0 10px; selection-background-color: {t.accent}; selection-color: {t.text_on_accent};
}}
{_sel(areas, *(f + ':hover' for f in fields))} {{ background: {k.fill_hover}; border-color: transparent; }}
{_sel(areas, *(f + ':focus' for f in fields))} {{ background: {k.fill}; border-color: {t.accent}; }}
{_sel(areas, *(f + ':disabled' for f in fields))} {{ background: {k.fill_disabled}; color: {t.disabled}; border-color: transparent; }}
{_sel(areas, "QComboBox")} {{ padding-right: 4px; }}
{_sel(areas, "QComboBox::drop-down")} {{
    subcontrol-origin: padding; subcontrol-position: center right; width: 22px; height: 22px;
    margin-right: 5px; border: 0; border-radius: 10px; background: {k.chip};
}}
{_sel(areas, "QComboBox::drop-down:hover")} {{ background: {k.chip_hover}; }}
{_sel(areas, "QComboBox::down-arrow")} {{ image: url({icon['chevron']}); width: 10px; height: 10px; }}
{_sel(areas, "QComboBox::down-arrow:on")} {{ image: url({icon['chevron_up']}); }}
{_sel(areas, "QComboBox::drop-down:disabled")} {{ background: transparent; }}
{_sel(areas, "QComboBox::down-arrow:disabled")} {{ image: url({icon['chevron_disabled']}); }}
{_sel(areas, "QComboBox QLineEdit", "QComboBox QLineEdit:hover", "QComboBox QLineEdit:focus")} {{
    background: transparent; border: 0; padding: 0; border-radius: 0;
}}
{_sel(areas, "QAbstractSpinBox::up-button", "QAbstractSpinBox::down-button")} {{ width: 0; border: 0; }}
{_sel((card,), *fields)} {{ background: {k.card_fill}; }}
{_sel((card,), *(f + ':hover' for f in fields))} {{ background: {k.card_fill_hover}; }}
{_sel((panel,), "QPlainTextEdit", "QTextEdit")} {{
    background: {k.fill}; color: {t.text}; border: 1px solid transparent; border-radius: 12px; padding: 6px 8px;
    selection-background-color: {t.accent}; selection-color: {t.text_on_accent};
}}
{_sel((card,), "QPlainTextEdit", "QTextEdit")} {{ background: {k.card_fill}; }}
{_sel((panel,), "QPlainTextEdit:focus", "QTextEdit:focus")} {{ border-color: {t.accent}; }}

/* ---- caption inside the field (B) ---- */
{caption} {{ background: {k.fill}; border: 1px solid transparent; border-radius: 10px; }}
{caption}:hover {{ background: {k.fill_hover}; }}
{caption}[focused="true"] {{ border-color: {t.accent}; }}
{caption}:disabled, {caption}[off="true"] {{ background: {k.fill_disabled}; }}
{card} {caption}[off="true"] {{ background: {k.fill_disabled}; }}
{card} {caption} {{ background: {k.card_fill}; }}
{card} {caption}:hover {{ background: {k.card_fill_hover}; }}
{card} {caption}[focused="true"] {{ border-color: {t.accent}; }}
{caption} QLabel#softCaption {{ background: transparent; color: {t.text_muted}; font-size: 11px; font-weight: 600; }}
{caption} QLabel#softUnit, {caption} QLabel#softAxis {{ background: transparent; color: {t.text_muted}; font-size: 12px; font-weight: 600; }}
{_sel((panel, ""), *(f"{caption} {f}" for f in fields), *(f"{caption} {f}:hover" for f in fields),
      *(f"{caption} {f}:focus" for f in fields), *(f"{caption} {f}:disabled" for f in fields))} {{
    background: transparent; border: 0; border-radius: 0; padding: 0; min-height: 20px;
    font-weight: 600;
}}
{_sel((panel, ""), f"{caption} QComboBox")} {{ padding-right: 2px; }}
{_sel((panel, ""), f"{caption} QComboBox::drop-down")} {{
    subcontrol-origin: padding; subcontrol-position: center right; width: 14px; height: 14px;
    margin-right: 0; background: transparent; border: 0;
}}
{_sel((panel, ""), f"{caption} QComboBox::down-arrow")} {{ image: url({icon['chevron_muted']}); width: 11px; height: 11px; }}
{_sel((panel, ""), f"{caption} QComboBox::down-arrow:disabled")} {{ image: url({icon['chevron_disabled']}); }}

/* ---- buttons: tonal fills, primary in the accent (A) ---- */
{panel} QPushButton {{
    background: {k.fill}; color: {t.text}; border: 1px solid transparent; border-radius: 9px;
    min-height: 30px; max-height: 40px; padding: 0 12px; font-weight: 600;
}}
{panel} QPushButton:hover {{ background: {k.fill_hover}; color: {t.text}; border-color: transparent; }}
{panel} QPushButton:pressed {{ background: {k.fill_strong}; }}
{panel} QPushButton:checked {{ background: {k.chip}; color: {t.accent_text}; border-color: transparent; }}
{panel} QPushButton:focus {{ border-color: {t.focus}; }}
{panel} QPushButton:disabled {{ background: {k.fill_disabled}; color: {t.disabled}; border-color: transparent; }}
{card} QPushButton {{ background: {k.card_fill}; }}
{card} QPushButton:hover {{ background: {k.card_fill_hover}; }}
{_sel((panel,), 'QPushButton#studioPrimary', 'QPushButton#studioPrimaryButton', 'QPushButton[buttonRole="primary"]', 'QPushButton[softRole="primary"]')} {{
    background: {t.accent}; color: {t.text_on_accent}; border-color: transparent;
}}
{_sel((panel,), 'QPushButton#studioPrimary:hover', 'QPushButton#studioPrimaryButton:hover', 'QPushButton[buttonRole="primary"]:hover', 'QPushButton[softRole="primary"]:hover')} {{
    background: {t.accent_hover}; color: {t.text_on_accent};
}}
{_sel((panel,), 'QPushButton#studioPrimary:pressed', 'QPushButton#studioPrimaryButton:pressed', 'QPushButton[buttonRole="primary"]:pressed', 'QPushButton[softRole="primary"]:pressed')} {{
    background: {t.accent_pressed}; color: {t.text_on_accent};
}}
{_sel((panel,), 'QPushButton#studioPrimary:disabled', 'QPushButton#studioPrimaryButton:disabled', 'QPushButton[buttonRole="primary"]:disabled', 'QPushButton[softRole="primary"]:disabled')} {{
    background: {k.primary_disabled}; color: {t.text_on_accent};
}}
{panel} QPushButton[softRole="tint"], {panel} QPushButton#styleLibraryButton {{ background: {k.chip}; color: {t.accent_text}; }}
{panel} QPushButton[softRole="tint"]:hover, {panel} QPushButton#styleLibraryButton:hover {{ background: {k.chip_hover}; color: {t.accent_text}; }}
{panel} QPushButton[softRole="ghost"] {{ background: transparent; color: {t.text_secondary}; }}
{panel} QPushButton[softRole="ghost"]:hover {{ background: {k.fill}; color: {t.text}; }}
{panel} QPushButton[buttonRole="danger"] {{ background: {k.fill}; color: {t.danger}; }}

/* ---- segments and filter chips: the chosen one in the accent (A) ---- */
QFrame#softSegmented {{ background: {k.fill}; border: 0; border-radius: 10px; }}
{card} QFrame#softSegmented {{ background: {k.card_fill}; }}
QFrame#softSegmented[collapsed="true"], {card} QFrame#softSegmented[collapsed="true"] {{ background: transparent; }}
{_sel((panel, ""), "QFrame#softSegmented QPushButton")} {{
    background: transparent; color: {t.text_secondary}; border: 0; border-radius: 8px;
    min-height: 28px; max-height: 28px; padding: 0 8px; font-weight: 600;
}}
{_sel((panel, ""), "QFrame#softSegmented QPushButton:hover")} {{ background: {k.fill_hover}; color: {t.text}; }}
{_sel((panel, ""), "QFrame#softSegmented QPushButton:checked")} {{ background: {t.accent}; color: {t.text_on_accent}; }}
{_sel((panel, ""), "QFrame#softSegmented QPushButton:disabled")} {{ background: transparent; color: {t.disabled}; }}
{_sel((panel, ""), 'QFrame#softSegmented[tone="soft"] QPushButton:checked')} {{ background: {k.raised}; color: {t.accent_text}; }}
{_sel((panel, ""), "QFrame#softSegmented QPushButton:checked:disabled")} {{ background: {k.primary_disabled}; color: {t.text_on_accent}; }}

/* ---- check boxes and switches (A) ---- */
{panel} QCheckBox {{ background: transparent; color: {t.text}; spacing: 8px; }}
{panel} QCheckBox::indicator {{ width: 18px; height: 18px; border: 0; border-radius: 5px; background: {k.fill_strong}; image: none; }}
{panel} QCheckBox::indicator:hover {{ background: {blend_hex(k.fill_strong, t.text, 0.06)}; }}
{panel} QCheckBox::indicator:checked {{ background: {t.accent}; image: url({icon['check']}); }}
{panel} QCheckBox::indicator:disabled {{ background: {k.fill_disabled}; }}
{panel} QCheckBox::indicator:checked:disabled {{ background: {k.primary_disabled}; }}
{_sel((panel,), 'QCheckBox[softSwitch="true"]::indicator', 'QCheckBox#styleSwitch::indicator')} {{
    width: 36px; height: 20px; border: 0; border-radius: 0; background: transparent; image: url({icon['switch_off']});
}}
{_sel((panel,), 'QCheckBox[softSwitch="true"]::indicator:checked', 'QCheckBox#styleSwitch::indicator:checked')} {{
    background: transparent; image: url({icon['switch_on']});
}}
{_sel((panel,), 'QCheckBox[softSwitch="true"]::indicator:disabled', 'QCheckBox#styleSwitch::indicator:disabled')} {{
    background: transparent; image: url({icon['switch_off_disabled']});
}}
{_sel((panel,), 'QCheckBox[softSwitch="true"]::indicator:checked:disabled', 'QCheckBox#styleSwitch::indicator:checked:disabled')} {{
    background: transparent; image: url({icon['switch_on_disabled']});
}}

/* ---- sliders ---- */
{panel} QSlider::groove:horizontal {{ height: 4px; border: 0; border-radius: 2px; background: {k.fill_strong}; }}
{panel} QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
{panel} QSlider::add-page:horizontal {{ background: {k.fill_strong}; border-radius: 2px; }}
{panel} QSlider::handle:horizontal {{
    width: 18px; height: 18px; margin: -7px 0; border: 0; background: transparent; image: url({icon['knob']});
}}
{panel} QSlider::sub-page:horizontal:disabled {{ background: {k.fill_strong}; }}
{panel} QSlider::handle:horizontal:disabled {{ image: url({icon['knob_disabled']}); }}

/* ---- groups: a small heading and space, no frame (B); cards (A) ---- */
{panel} QGroupBox {{
    background: transparent; border: 0; border-radius: 0; margin-top: 20px; padding-top: 2px;
    color: {t.text}; font-weight: 700;
}}
{panel} QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left; left: 0; padding: 0;
    color: {t.text_secondary}; background: transparent;
}}
{panel} QFrame[softCard="true"] {{ background: {k.card}; border: 0; border-radius: 14px; }}
{_sel((panel,), "QPushButton#softFoldHeader", "QPushButton#softFoldHeader:hover", "QPushButton#softFoldHeader:pressed",
      "QPushButton#softFoldHeader:focus", "QPushButton#softFoldHeader:checked")} {{
    background: transparent; border: 0; border-radius: 0; padding: 0; min-height: 28px; max-height: 32px;
}}
{panel} QToolButton#softFoldArrow {{ background: transparent; border: 0; padding: 0; }}
/* ---- 视频 panel (C) ---- */
{panel} QFrame#videoClipChip {{ background: {k.chip}; border: 0; border-radius: 12px; }}
{panel} QLabel#videoClipIcon {{ background: {t.accent}; border-radius: 9px; }}
{panel} QLabel#videoSelectionSummary {{ background: transparent; color: {t.text}; font-size: 13px; font-weight: 700; padding: 0; border: 0; }}
{panel} QToolButton#videoScaleLink {{ background: {k.card_fill}; border: 0; border-radius: 9px; min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px; }}
{panel} QToolButton#videoScaleLink:checked {{ background: {k.chip}; }}
{panel} QToolButton#videoScaleLink:hover {{ background: {k.card_fill_hover}; }}
{panel} QToolButton#captionScaleLink {{ background: {k.card_fill}; border: 0; border-radius: 9px; min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px; }}
{panel} QToolButton#captionScaleLink:checked {{ background: {k.chip}; }}
{panel} QToolButton#captionScaleLink:hover {{ background: {k.card_fill_hover}; }}
{panel} QToolButton#captionScaleLink:disabled {{ background: {k.fill_disabled}; }}
{panel} QLabel#softCardTitle {{ background: transparent; color: {t.text}; font-size: 14px; font-weight: 700; }}
{panel} QLabel#softCardSummary {{ background: transparent; color: {t.text_muted}; font-size: 12px; font-weight: 600; }}
{panel} QLabel#softMeta {{ background: transparent; color: {t.text_muted}; font-size: 12px; }}
{panel} QLabel#softLabel {{ background: transparent; color: {t.text_secondary}; font-size: 13px; font-weight: 600; }}
{panel} QLabel#softStep {{
    background: {t.accent}; color: {t.text_on_accent}; border-radius: 11px;
    min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px; font-size: 12px; font-weight: 800;
}}
{panel} QLabel[softPill="ok"], {panel} QLabel[softPill="warn"], {panel} QLabel[softPill="off"], {panel} QLabel[softPill="accent"] {{
    border-radius: 11px; min-height: 22px; max-height: 22px; padding: 0 9px; font-size: 12px; font-weight: 700;
}}
{panel} QLabel[softPill="ok"] {{ background: {k.ok_tint}; color: {k.ok}; }}
{panel} QLabel[softPill="warn"] {{ background: {k.warn_tint}; color: {k.warn}; }}
{panel} QLabel[softPill="off"] {{ background: {k.fill}; color: {t.text_muted}; }}
{panel} QLabel[softPill="accent"] {{ background: {k.chip}; color: {t.accent_text}; }}

/* ---- button sizes ---- */
{panel} QPushButton[softSize="sm"] {{ min-height: 28px; max-height: 28px; padding: 0 10px; border-radius: 8px; font-size: 12px; }}
{panel} QPushButton[softSize="lg"] {{ min-height: 38px; max-height: 38px; padding: 0 14px; border-radius: 10px; font-size: 14px; font-weight: 700; }}
{panel} QComboBox[softSize="lg"] {{ min-height: 38px; max-height: 38px; border-radius: 10px; }}

/* ---- 动效 panel (A): stage track, chips, direction squares, tiles ---- */
{panel} QWidget#motionStageBar {{ background: {k.fill}; border-radius: 12px; }}
{panel} QPushButton#motionStage {{
    background: transparent; color: {t.text_secondary}; border: 0; border-radius: 9px;
    min-height: 44px; max-height: 44px; padding: 0;
}}
{panel} QPushButton#motionStage:hover {{ background: {k.fill_hover}; }}
{panel} QPushButton#motionStage:checked {{ background: {k.raised}; color: {t.accent_text}; }}
{panel} QPushButton#motionChip {{
    background: {k.fill}; color: {t.text_secondary}; border: 0; border-radius: 13px;
    min-height: 28px; max-height: 28px; padding: 0 12px; font-size: 12px; font-weight: 600;
}}
{panel} QPushButton#motionChip:hover {{ background: {k.fill_hover}; color: {t.text}; }}
{panel} QPushButton#motionChip:checked {{ background: {t.accent}; color: {t.text_on_accent}; }}
{panel} QPushButton#motionDirection {{
    background: {k.card_fill}; color: {t.text_secondary}; border: 0; border-radius: 8px;
    min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; padding: 0; font-weight: 700;
}}
{panel} QPushButton#motionDirection:hover {{ background: {k.card_fill_hover}; color: {t.text}; }}
{panel} QPushButton#motionDirection:checked {{ background: {t.accent}; color: {t.text_on_accent}; }}
{panel} QPushButton#motionEffectTile {{
    background: {k.fill}; border: 2px solid transparent; border-radius: 12px; padding: 0;
    min-height: 84px; max-height: 84px;
}}
{panel} QPushButton#motionEffectTile:hover {{ background: {k.fill_hover}; }}
{panel} QPushButton#motionEffectTile:checked {{ background: {k.chip}; border-color: {t.accent}; }}
{panel} QLabel#motionTileLabel {{ background: transparent; color: {t.text}; font-size: 12px; font-weight: 600; }}
{panel} QLabel#motionTileLabel[selected="true"] {{ color: {t.accent_text}; font-weight: 700; }}
{panel} QLabel#motionTileCheck {{ background: {t.accent}; border-radius: 8px; }}
{panel} QLabel#motionBadge {{
    font-size: 9px; font-weight: 700; color: #E8EEF5; background: rgba(9, 14, 20, 170);
    border-radius: 6px; padding: 0 5px;
}}

/* ---- 样式 panel: scope choices and B / I / U follow the soft controls ---- */
{panel} QFrame#styleScopeBar QRadioButton#scopeOption {{
    background: {k.fill}; color: {t.text_secondary}; border: 0; border-radius: 9px;
    min-height: 30px; padding: 0 5px; font-weight: 600; spacing: 0;
}}
{panel} QFrame#styleScopeBar QRadioButton#scopeOption::indicator {{
    width: 0; height: 0; margin: 0; border: 0; background: transparent; image: none;
}}
{panel} QFrame#styleScopeBar QRadioButton#scopeOption:hover {{ background: {k.fill_hover}; color: {t.text}; }}
{panel} QFrame#styleScopeBar QRadioButton#scopeOption:checked {{ background: {t.accent}; color: {t.text_on_accent}; }}
{_sel((panel,), "QToolButton#styleEmphasis", "QToolButton#styleAnchor")} {{
    background: {k.fill}; color: {t.text}; border: 0; border-radius: 8px;
}}
{_sel((panel,), "QToolButton#styleEmphasis:hover", "QToolButton#styleAnchor:hover")} {{ background: {k.fill_hover}; }}
{_sel((panel,), "QToolButton#styleEmphasis:checked", "QToolButton#styleAnchor:checked")} {{
    background: {k.chip}; color: {t.accent_text}; border: 0;
}}

/* ---- 剪辑 panel: tabs (B), cards (A), candidate cards (C) ---- */
{_sel((panel,), 'QPushButton[softTab="true"]')} {{ min-height: 34px; max-height: 34px; font-size: 13px; }}
{panel} QToolButton#highlightConfigToggle {{
    background: {k.fill}; color: {t.text}; border: 0; border-radius: 10px; min-height: 38px; max-height: 38px;
    padding: 0 12px; font-weight: 700;
}}
{panel} QToolButton#highlightConfigToggle:hover {{ background: {k.fill_hover}; }}
{panel} QToolButton#highlightLinkToggle {{
    background: transparent; color: {t.text}; border: 0; padding: 2px 0; font-weight: 700;
}}
{panel} QToolButton#highlightLinkToggle:hover {{ color: {t.accent_text}; }}
{panel} QToolButton#highlightDataIcon {{ background: {blend_hex(k.card, t.zone_colors.get("content", t.accent), 0.16)}; border: 0; border-radius: 9px; }}
{panel} QLabel#highlightScore {{
    background: {t.accent}; color: {t.text_on_accent}; border-radius: 18px; font-size: 14px; font-weight: 800;
}}
{panel} QLabel#highlightTitle {{ background: transparent; color: {t.text}; font-size: 14px; font-weight: 700; }}
{panel} QLabel#highlightWhy {{
    background: {blend_hex(k.card, t.accent, 0.12 if t.is_light else 0.2)}; color: {t.text}; border-radius: 10px;
    padding: 7px 10px; font-size: 12px;
}}
{panel} QLabel#highlightEvidence {{ background: {k.card_fill}; color: {t.text_secondary}; border-radius: 8px; padding: 6px 8px; font-size: 12px; }}
{panel} QLabel#highlightDetails {{ background: transparent; color: {t.text_muted}; font-size: 12px; }}
{panel} QLabel#highlightEmpty {{
    background: {k.fill}; color: {t.text_muted}; border-radius: 12px; padding: 14px; font-size: 12px;
}}
{panel} QFrame#highlightBinCard {{ background: {k.fill}; border: 0; border-radius: 10px; }}
{panel} QFrame#highlightBinCard QPushButton {{ background: transparent; min-height: 26px; max-height: 26px; padding: 0; border-radius: 8px; }}
{panel} QFrame#highlightBinCard QPushButton:hover {{ background: {k.fill_hover}; }}
{panel} QFrame#highlightSectionWhat QLabel {{ background: transparent; }}

/* ---- top bar: commands in tonal tracks by kind (B) ---- */
{bar} {{ background: {track}; border: 0; border-radius: 12px; }}
{bar} QPushButton, {bar} QToolButton {{
    background: transparent; color: {t.text_secondary}; border: 1px solid transparent; border-radius: 9px;
    min-height: 30px; max-height: 30px; padding: 0 10px; font-weight: 600;
}}
{bar} QToolButton {{ min-width: 32px; max-width: 32px; padding: 0; }}
{bar} QPushButton:hover, {bar} QToolButton:hover {{ background: {track_hover}; color: {t.text}; border-color: transparent; }}
{bar} QPushButton:pressed, {bar} QToolButton:pressed {{ background: {track_pressed}; color: {t.text}; }}
{bar} QPushButton:checked, {bar} QToolButton:checked {{ background: {t.surface_elevated}; color: {t.accent_text}; border-color: transparent; }}
{bar} QPushButton:focus, {bar} QToolButton:focus {{ border-color: {t.focus}; }}
{bar} QPushButton:disabled, {bar} QToolButton:disabled {{ background: transparent; color: {t.disabled}; }}
{bar} QPushButton[hasMenu="true"] {{ padding-right: 24px; }}
{bar} QPushButton[emphasis="accent"] {{ background: {t.accent}; color: {t.text_on_accent}; padding: 0 14px; }}
{bar} QPushButton[emphasis="accent"]:hover {{ background: {t.accent_hover}; color: {t.text_on_accent}; }}
{bar} QPushButton[emphasis="accent"]:pressed {{ background: {t.accent_pressed}; color: {t.text_on_accent}; }}

/* ---- tool panel tabs: a tinted pill for the open tab (A) ---- */
QTabWidget#contextDrawer::pane {{ background: {t.panel}; border: 0; }}
QTabWidget#contextDrawer QTabBar {{ background: transparent; }}
QTabWidget#contextDrawer QTabBar::tab {{
    background: transparent; color: {t.text_muted}; border: 0; border-radius: 10px;
    min-height: 32px; max-height: 32px; margin: 2px 1px 6px 1px; padding: 0 6px; font-weight: 600;
}}
QTabWidget#contextDrawer QTabBar::tab:hover {{ background: {k.fill}; color: {t.text}; }}
QTabWidget#contextDrawer QTabBar::tab:selected {{
    background: {k.chip}; color: {t.accent_text}; font-weight: 700; border: 0;
}}
"""


def build_soft_popup_qss(t) -> str:
    """Dropdown lists and menus opened from Studio (A): a raised sheet,
    rounded rows, the chosen row in the accent wash."""
    k = soft_tokens(t)
    hover = blend_hex(t.surface_elevated, t.text, 0.07 if t.is_light else 0.09)
    chip = blend_hex(t.surface_elevated, t.accent, 0.15 if t.is_light else 0.24)
    return f"""
QComboBox QAbstractItemView, QComboBox QListView {{
    background: {k.card}; color: {t.text}; border: 1px solid {t.hairline}; border-radius: 12px;
    padding: 5px; outline: 0; selection-background-color: {chip}; selection-color: {t.accent_text};
}}
QComboBox QAbstractItemView::item, QComboBox QListView::item {{
    min-height: 30px; padding: 0 10px; border-radius: 8px; background: transparent; color: {t.text};
}}
QComboBox QAbstractItemView::item:hover, QComboBox QListView::item:hover {{ background: {hover}; color: {t.text}; }}
QComboBox QAbstractItemView::item:selected, QComboBox QListView::item:selected {{
    background: {chip}; color: {t.accent_text}; font-weight: 700;
}}
QComboBox QAbstractItemView::item:disabled, QComboBox QListView::item:disabled {{ background: transparent; color: {t.disabled}; }}
QMenu {{ background: {k.card}; color: {t.text}; border: 1px solid {t.hairline}; padding: 6px; }}
QMenu::item {{ min-height: 30px; padding: 2px 30px 2px 10px; border-radius: 8px; }}
QMenu::item:selected {{ background: {hover}; color: {t.text}; }}
QMenu::item:disabled {{ background: transparent; color: {t.disabled}; }}
QMenu::separator {{ height: 1px; background: {t.hairline}; margin: 5px 8px; }}
"""
