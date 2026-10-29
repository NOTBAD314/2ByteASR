"""Semantic state layer appended after legacy, warm-authored page sheets.

The legacy sheets were written in the warm cream/green palette, where green
meant both "brand" and "success". ``retheme_qss`` maps those literals by
colour, so on other themes success pills inherited the brand accent and
decorative "active" borders inherited the focus ring. These rules restate the
meaning explicitly (2026-10-07 visual system):

  * navigation selection  → quiet brand tint, primary text
  * success / warning / danger / info → their own status roles
  * classification chips  → neutral
"""
from __future__ import annotations

from .typography import UI_FONT_STACK


def build_semantic_qss(t) -> str:
    chip = "border-radius: 8px; padding: 3px 8px; font-size: 12px; font-weight: 500; border: 0;"
    pill = "border-radius: 9px; padding: 4px 10px; font-size: 12px; font-weight: 500; border: 0;"
    return f"""
QPushButton#workspaceNav {{ color: {t.text_secondary}; font-weight: 500; }}
QPushButton#workspaceNav:hover {{ background: {t.selected}; color: {t.text}; }}
QPushButton#workspaceNav:checked {{ background: {t.accent_tint}; color: {t.text}; font-weight: 600; }}
QFrame#historySidebar {{ background: {t.panel}; border: 1px solid {t.border}; }}
QFrame#historyContent {{ background: {t.surface}; border: 1px solid {t.border}; }}
QFrame#historyCard {{ background: {t.surface}; border: 1px solid {t.border}; }}
QFrame#historyCard:hover {{ background: {t.surface_elevated}; border-color: {t.border_strong}; }}
QFrame#historyMetric {{ background: {t.panel}; border: 1px solid {t.border}; }}
QFrame#historyPipelineStrip {{ background: {t.panel}; border: 1px solid {t.border}; }}
QLabel#historyTitle {{ color: {t.text}; font-size: 22px; font-weight: 800; }}
QLabel#historyItemTitle {{ color: {t.text}; font-weight: 600; }}
QLabel#historyMetaChip, QLabel#historySummaryPill, QLabel#historyResourcePill {{
    background: {t.surface_elevated}; color: {t.text_secondary}; {chip} }}
QLabel#historyMetaChipWarn, QLabel#historyMetaChipReview, QLabel#historyReviewPill,
QLabel#historyStageStatusWarn {{ background: {t.warning_soft}; color: {t.warning}; {chip} }}
QLabel#historyStageStatusGood {{ background: {t.success_soft}; color: {t.success}; {chip} }}
QLabel#historyStageStatusError {{ background: {t.danger_soft}; color: {t.danger}; {chip} }}
QLabel#historyStatusGood {{ background: {t.success_soft}; color: {t.success}; {pill} }}
QLabel#historyStatusWarn {{ background: {t.warning_soft}; color: {t.warning}; {pill} }}
QLabel#historyStatusError {{ background: {t.danger_soft}; color: {t.danger}; {pill} }}
QPushButton#historyDetails, QPushButton#historySecondary {{
    background: {t.surface_elevated}; color: {t.text}; border: 1px solid {t.border_strong};
    border-radius: 8px; padding: 7px 14px; font-weight: 500; }}
QPushButton#historyDetails:hover, QPushButton#historySecondary:hover {{ background: {t.selected}; border-color: {t.text_muted}; }}
QPushButton#historyPrimary {{ background: {t.accent}; color: {t.text_on_accent}; border: 1px solid {t.accent};
    border-radius: 8px; padding: 7px 14px; font-weight: 600; }}
QPushButton#historyPrimary:hover {{ background: {t.accent_hover}; }}
QPushButton#historyRawToggle {{ background: transparent; color: {t.danger}; border: 1px solid {t.border_strong};
    border-radius: 8px; padding: 6px 11px; font-weight: 500; }}
QFrame#historyInfoSection {{ background: {t.panel}; border: 1px solid {t.border}; }}
QFrame#historyReviewSection {{ background: {t.warning_soft}; border: 1px solid {t.border}; border-left: 3px solid {t.warning}; }}
QLabel#categoryChip {{ background: {t.surface_elevated}; color: {t.text_secondary}; {chip} }}
QLabel#statusBadgeGood {{ background: {t.success_soft}; color: {t.success}; {chip} }}
QLabel#statusBadgeWarn {{ background: {t.warning_soft}; color: {t.warning}; {chip} }}
QLabel#statusBadgeMuted {{ background: {t.surface_elevated}; color: {t.text_muted}; {chip} }}
QLabel#termLibraryBadge {{ background: {t.surface_elevated}; color: {t.text_secondary}; {chip} }}
QFrame#termGameRow[selected="true"] {{ background: {t.accent_tint}; border-color: {t.accent}; }}
QFrame#termGameRow:hover {{ border-color: {t.border_strong}; }}
QFrame#batchStrip {{ background: {t.panel}; border: 1px solid {t.border}; }}
QLabel#termSidebarSync {{ color: {t.text_muted}; }}
QPushButton#glossaryChip {{ background: {t.surface_elevated}; color: {t.text}; border: 1px solid {t.border_strong};
    border-radius: 8px; font-family: {UI_FONT_STACK}; font-weight: 500; }}
QPushButton#glossaryChip:hover {{ background: {t.selected}; border-color: {t.text_muted}; }}
"""


def pill_palette(t) -> dict[str, tuple[str, str, str]]:
    """(fill, text, border) for painted table pills, by semantic state."""
    return {
        "category": (t.surface_elevated, t.text_secondary, t.border),
        "confirmed": (t.success_soft, t.success, t.success_soft),
        "reference": (t.surface_elevated, t.text_secondary, t.border),
        "hidden": (t.panel, t.disabled, t.border),
    }
