"""P9A surface / color / spacing aliases over ThemeDefinition.

Do not add dataclass fields to ThemeDefinition: TOKEN_FIELDS in
tests/test_theme_manager.py is the frozen contract. Aliases live here
and as properties on ThemeDefinition.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from ..typography import REGULAR, MEDIUM, SEMIBOLD, BOLD, HEAVY

if TYPE_CHECKING:
    from ..ui_theme import ThemeDefinition

# Spec scale. ui_theme still has SPACE_5 = 20 for legacy callers.
SPACE_SCALE = (4, 8, 12, 16, 24, 32)
RADIUS_SCALE = {"small": 4, "control": 8, "surface": 12, "modal": 16}
CONTROL_HEIGHTS = {"compact": 28, "default": 36, "large": 44}
# Button content height, type size and horizontal padding. Page CTAs opt in
# to large; field heights keep their independent, denser scale.
BUTTON_SIZES = {
    "compact": (CONTROL_HEIGHTS["compact"], 13, 12),
    "default": (CONTROL_HEIGHTS["default"], 13, 16),
    "large": (48, 16, 24),
}
FIELD_WIDTHS = {"numeric": (80, 144), "compact": (120, 240),
                "preferred": (180, 360), "large": (240, 520), "expanding": (120, 16777215)}

WEIGHT_SCALE = {
    "regular": REGULAR, "medium": MEDIUM, "semibold": SEMIBOLD,
    "bold": BOLD, "heavy": HEAVY,
}

# Pixel sizes and weights are separate: Heavy is reserved for title roles.
# 五十二轮（用户"正文/说明偏小，缩成一团"）：正文/次级/角标整体 +1px，
# 建立 body 14 > small 13 > caption 12 的可读层级（2K/4K 高 DPI 下更明显）。
TYPE_SCALE = {
    "display": 28,
    "heading1": 22,
    "heading2": 18,
    "section": 14,
    "body": 14,
    "small": 13,
    "caption": 12,
    "mono": 13,
}


def p9a_tokens(theme: ThemeDefinition) -> dict[str, str]:
    """Canonical P9A token map used by generated control QSS."""
    return {
        "bg.app": theme.app_background,
        "bg.panel": theme.panel,
        "bg.card": theme.surface,
        "bg.control": theme.surface_elevated,
        "bg.control_hover": theme.selected,
        "bg.control_pressed": theme.accent_soft,
        "bg.popup": theme.surface_elevated,
        "bg.modal": theme.surface,
        "border.subtle": theme.border,
        "border.default": theme.border_strong,
        "border.focus": theme.accent,
        "text.primary": theme.text,
        "text.secondary": theme.text_secondary,
        "text.muted": theme.text_muted,
        "text.disabled": theme.disabled,
        "text.onAccent": theme.text_on_accent,
        "accent.primary": theme.accent,
        "accent.hover": theme.accent_hover,
        "accent.pressed": theme.accent_pressed,
        "accent.soft": theme.accent_soft,
        "success": theme.success,
        "warning": theme.warning,
        "danger": theme.danger,
        "info": theme.focus,
    }
