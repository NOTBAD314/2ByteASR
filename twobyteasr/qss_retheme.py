"""Runtime QSS retheming.

The shipped stylesheets were authored against the warm (and, for the Project
Hub, plum) palette with colors baked into the CSS text.  Instead of forking
two drifting copies, ``retheme_qss`` rewrites every known warm/plum color
literal into the semantic token of the active theme, so one stylesheet
renders correctly under all four themes.  The warm theme maps back to values
that are visually equivalent to the original literals.

``#ffffff`` is deliberately left untouched (it is the on-accent text color)
except for explicit ``background: #ffffff`` declarations, which become the
elevated surface color.
"""

from __future__ import annotations

import re

from .ui_theme import ThemeDefinition, theme_definition

# warm palette constants + every literal used by APP_QSS / STUDIO_QSS /
# SECONDARY_SURFACE_QSS, classified to one semantic token each.
_HEX_TOKENS: dict[str, str] = {
    # --- warm palette constants (baked by f-strings at import time) ---
    "#faf7f1": "app_background",
    "#f5f0e7": "timeline",
    "#fffefa": "surface",
    "#f7f3eb": "panel",
    "#ffffff": "surface_elevated",  # only reached via background: rule below
    "#e1d7c8": "border",
    "#d2c3ae": "border_strong",
    "#9fbd9f": "focus",
    "#292a27": "text",
    "#494943": "text_secondary",
    "#65645d": "text_muted",
    "#87837a": "disabled",
    "#4f8557": "accent",
    "#43754b": "accent_hover",
    "#396641": "accent_pressed",
    "#e6efe2": "selected",
    "#f1f6ee": "accent_soft",
    "#bd8535": "warning",
    "#f7edd9": "warning_soft",
    "#b86555": "danger",
    "#30332f": "media",
    # --- plum Hub constants baked into the Hub stylesheet ---
    "#2b202e": "app_background",
    "#4b354c": "surface",
    "#60465d": "surface_elevated",
    "#6a4b63": "accent_soft",
    "#3b2a3d": "panel",
    "#563f57": "input_surface",
    "#795978": "selected",
    "#82647e": "border",
    "#9a7894": "border_strong",
    "#fff5f1": "text",
    "#d1bfcb": "text_muted",
    "#a990a7": "disabled",
    "#f47c68": "accent",
    "#ff927c": "accent_hover",
    "#dd6957": "accent_pressed",
    "#90c6a0": "success",
    "#f1bf73": "warning",
    # --- module-local studio constants baked into f-strings ---
    "#f0ece3": "panel",
    "#292d29": "text",
    "#4f825d": "accent",
    "#858981": "text_muted",
    "#f8f5ee": "app_background",
    "#3d403a": "text",
    # --- late stragglers ---
    "#ddd7cc": "border",
    "#ded7ca": "border",
    "#e3d2b7": "warning",
    "#c8b79f": "warning_soft",
    "#d8c9a3": "warning_soft",
    "#d8cdbc": "selected",
    # --- near-white raised surfaces ---
    "#fffaf1": "surface_elevated",
    "#fffaf2": "surface_elevated",
    "#fffdf8": "surface_elevated",
    "#fffdf9": "surface_elevated",
    "#fffdf8".upper(): "surface_elevated",
    # --- panel / muted fills ---
    "#fcfaf6": "panel",
    "#fbf8f0": "panel",
    "#fbf8f1": "panel",
    "#faf8f3": "panel",
    "#faf7f0": "panel",
    "#faf6ee": "panel",
    "#f8f7ef": "panel",
    "#f6f2ea": "panel",
    "#f5f1e9": "panel",
    "#f4f1ea": "panel",
    "#f1eee7": "panel",
    "#f1eee8": "panel",
    "#f0e9dc": "panel",
    "#f0e9de": "panel",
    "#eee9df": "panel",
    "#eee8de": "panel",
    "#eef2eb": "panel",
    "#edf0e9": "panel",
    "#edf0ea": "panel",
    "#edf2eb": "panel",
    "#f1f2ed": "panel",
    "#f0f2ec": "panel",
    "#f0f4ed": "panel",
    "#f0f6ed": "panel",
    "#f3f7ef": "panel",
    "#f3f7f0": "panel",
    "#f8faf5": "panel",
    "#f6f3ed": "panel",
    "#e9eee7": "panel",
    "#e8e1d6": "panel",
    "#f0fdf4": "accent_soft",
    "#f2f6ee": "accent_soft",
    # --- borders ---
    "#ece7de": "border",
    "#e3ded5": "border",
    "#e2ddd4": "border",
    "#e0dbd1": "border",
    "#e1ddd5": "border",
    "#ddd8ce": "border",
    "#d8d2c8": "border",
    "#d8d0c3": "border",
    "#d5d1c8": "border",
    "#d2cbc0": "border",
    "#cbd2c9": "border",
    "#cfc5b7": "border",
    "#b7b1a6": "border",
    "#d6d0c6": "border",
    "#d2d9d0": "border",
    "#e5ddd0": "border",
    "#eee7dc": "border",
    "#e2d9ca": "border",
    "#e3ddd1": "border",
    "#e4dccf": "border",
    "#e5dccd": "border",
    "#e6ddcf": "border",
    "#e8dfd2": "border",
    "#e9dfcf": "border",
    "#ece4d8": "border",
    "#ece5d8": "border",
    "#e4e0d6": "border",
    "#eee7d9": "border",
    "#eee8dc": "border",
    "#eeeae2": "border",
    "#efe8da": "border",
    "#efebe3": "border",
    "#ddd3c3": "border",
    "#ddd5c7": "border",
    "#d9d0c1": "border",
    "#d9d8c9": "border",
    # --- strong borders / disabled fills ---
    "#b8a990": "border_strong",
    "#b9ad9d": "border_strong",
    "#bdb8ae": "border_strong",
    "#c2b6a6": "border_strong",
    "#cfc2af": "border_strong",
    "#d6c5aa": "border_strong",
    "#aaa79e": "border_strong",
    "#a6a094": "border_strong",
    "#9d9a8f": "border_strong",
    "#aebbb0": "border_strong",
    "#777f77": "border_strong",
    "#7d867e": "border_strong",
    # --- selected / soft green fills ---
    "#e2eee2": "selected",
    "#d4e8d5": "selected",
    "#c5dec8": "selected",
    "#dfeadf": "selected",
    "#dfe5dd": "selected",
    "#e1eee1": "selected",
    "#e4ebdd": "selected",
    "#e5eee2": "selected",
    "#eef6ea": "selected",
    "#eef5ea": "selected",
    "#e2ecdf": "selected",
    "#e3ecdf": "selected",
    "#d4e0ce": "selected",
    "#d4e1cf": "selected",
    "#d5e0cb": "selected",
    "#dcead2": "selected",
    # --- focus borders ---
    "#b9c8b9": "focus",
    "#b9cfbb": "focus",
    "#a9c0ac": "focus",
    "#9eb8a2": "focus",
    "#aabdab": "focus",
    "#76a080": "focus",
    "#6f9a7d": "focus",
    "#6e9b73": "focus",
    "#709a78": "focus",
    "#71987a": "focus",
    "#9bbd9e": "focus",
    "#c8d2c6": "focus",
    "#9db092": "focus",
    "#9eaa98": "focus",
    "#9fb994": "focus",
    "#bfd2bd": "focus",
    "#c4d3ba": "focus",
    # --- accent greens (text + fills) ---
    "#4f8a61": "accent",
    "#3e714f": "accent_pressed",
    "#2f7349": "accent",
    "#27623e": "accent",
    "#2f6b42": "accent",
    "#2f5f3b": "accent",
    "#365b3e": "accent",
    "#315f3d": "accent",
    "#3a6d3e": "accent",
    "#355f3a": "accent",
    "#365f3a": "accent",
    "#6d8d67": "accent",
    # --- dark ink text ---
    "#252a27": "text",
    "#303732": "text",
    "#343a36": "text",
    "#39453e": "text",
    "#3d4d42": "text",
    "#233028": "text",
    "#213027": "text",
    "#28261f": "text",
    "#3d4639": "text",
    "#3f3b34": "text",
    # --- secondary text ---
    "#4b514d": "text_secondary",
    "#515953": "text_secondary",
    "#555d58": "text_secondary",
    "#566058": "text_secondary",
    "#5d665e": "text_secondary",
    "#5f6861": "text_secondary",
    "#626760": "text_secondary",
    "#667067": "text_secondary",
    "#68716a": "text_secondary",
    "#6b736e": "text_secondary",
    "#6d756e": "text_secondary",
    "#7b817b": "text_secondary",
    "#4d4a43": "text_secondary",
    "#5b564c": "text_secondary",
    "#5f5a51": "text_secondary",
    "#5f5d56": "text_secondary",
    "#6c6961": "text_secondary",
    "#746d61": "text_secondary",
    # --- warning family ---
    "#855b2d": "warning",
    "#8a622c": "warning",
    "#8a6524": "warning",
    "#8f6228": "warning",
    "#a67b37": "warning",
    "#b58d45": "warning",
    "#c39a49": "warning",
    "#d4b783": "warning",
    "#e4c36a": "warning",
    "#71551f": "warning",
    "#5b4a36": "warning",
    # --- warning soft fills ---
    "#f6ead8": "warning_soft",
    "#f4ecd9": "warning_soft",
    "#f4e7c7": "warning_soft",
    "#faf3e2": "warning_soft",
    "#fff6e8": "warning_soft",
    "#f0e4d1": "warning_soft",
    "#f0e7d8": "warning_soft",
    "#e6cf95": "warning_soft",
    "#eedcaf": "warning_soft",
    "#c7ad84": "warning_soft",
    "#e8d2a8": "warning_soft",
    # --- danger family ---
    "#955247": "danger",
    "#7b4035": "danger",
    "#663229": "danger",
    # --- danger soft fills ---
    "#f7e8e3": "danger_soft",
    "#f1d9d1": "danger_soft",
    "#f3e3dd": "danger_soft",
    "#e2b9ae": "danger_soft",
    "#d8b3a9": "danger_soft",
    # --- disabled ---
    "#9a978f": "disabled",
    "#99958d": "disabled",
    "#9b9890": "disabled",
    "#9a948a": "disabled",
    "#99968e": "disabled",
    "#8a857a": "disabled",
    # --- media / timeline chrome ---
    "#e4dac9": "timeline",
    "#151716": "media",
    "#181b19": "media",
    "#303430": "border_strong",
    "#343a38": "media",
    "#5e6963": "border_strong",
    # --- status pills ---
    "#477158": "success",
    "#725a66": "disabled",
    "#745246": "danger",
}

_BACKGROUND_WHITE = re.compile(r"background:\s*(?:#ffffff|white)\b", re.IGNORECASE)
_KEEP_WHITE = {"#fff2ed": "#ffffff"}


def retheme_qss(qss: str, theme: ThemeDefinition | None = None) -> str:
    """Rewrite warm/plum color literals in ``qss`` into ``theme`` tokens."""
    active = theme or theme_definition()
    table = {hexvalue: getattr(active, token) for hexvalue, token in _HEX_TOKENS.items()}
    result = _BACKGROUND_WHITE.sub(lambda m: "background: " + active.surface_elevated, qss)
    for hexvalue, replacement in _KEEP_WHITE.items():
        result = result.replace(hexvalue, replacement)
    for hexvalue, color in table.items():
        if hexvalue == "#ffffff":
            continue
        result = result.replace(hexvalue, color)
        upper = hexvalue.upper()
        if upper != hexvalue:
            result = result.replace(upper, color)
    return result
