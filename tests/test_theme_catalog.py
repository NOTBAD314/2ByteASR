"""2026-10-14 theme catalog: every theme is readable, named in every UI
language, grouped for the picker, and fully described without key branches."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from twobyteasr.ui_theme import (THEME_FAMILIES, THEME_ORDER, THEME_TRAITS, THEMES, contrast_ratio,
                                 ordered_themes, theme_display_label, theme_family_label, theme_mood)

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = {"grape", "warm", "plum", "lavender", "slate"}
NEW = set(THEMES) - ORIGINAL
LANGUAGES = ("zh", "zh-Hant", "en", "ja", "ko")

# (foreground, background, minimum) — the bar every 2026-10-14 theme meets.
READABILITY = (
    ("text", "app_background", 7.0), ("text", "surface", 7.0), ("text", "surface_elevated", 7.0),
    ("text", "input_surface", 7.0), ("text", "selected", 6.0), ("text", "accent_soft", 6.0),
    ("text_secondary", "surface", 6.0), ("text_secondary", "surface_elevated", 5.5),
    ("text_muted", "surface", 4.5), ("text_muted", "surface_elevated", 4.5), ("text_muted", "app_background", 4.5),
    ("text_on_accent", "accent", 4.5), ("text_on_accent", "accent_hover", 4.5), ("text_on_accent", "accent_pressed", 4.5),
    ("accent", "surface", 3.0), ("accent_text", "surface", 4.5), ("focus", "surface", 3.0),
    ("success", "surface", 4.5), ("warning", "surface", 4.5), ("danger", "surface", 4.5),
    ("warning", "warning_soft", 4.5), ("danger", "danger_soft", 4.5),
    ("border_strong", "surface", 2.2), ("border_strong", "input_surface", 2.2),
)


def test_catalog_has_the_requested_directions():
    assert len(NEW) >= 9
    assert THEMES["frost"].is_light and THEMES["frost"].family == "light"      # white tech
    assert not THEMES["obsidian"].is_light                                     # yellow / black
    assert contrast_ratio(THEMES["obsidian"].accent, "#f2c230") < 1.2
    assert THEMES["contrast"].family == "contrast" and not THEMES["contrast"].is_light
    assert THEMES["paper"].family == "contrast" and THEMES["paper"].is_light


@pytest.mark.parametrize("key", sorted(NEW))
def test_new_theme_meets_readability_bar(key):
    theme = THEMES[key]
    failures = [f"{a}/{b}={contrast_ratio(getattr(theme, a), getattr(theme, b)):.2f}<{minimum}"
                for a, b, minimum in READABILITY
                if contrast_ratio(getattr(theme, a), getattr(theme, b)) < minimum]
    assert not failures, failures


@pytest.mark.parametrize("key", sorted(THEMES))
def test_every_theme_has_visible_layers(key):
    theme = THEMES[key]
    assert contrast_ratio(theme.surface, theme.app_background) >= 1.05
    assert contrast_ratio(theme.selected, theme.surface) >= 1.15
    assert contrast_ratio(theme.border, theme.surface) >= 1.15
    assert contrast_ratio(theme.text, theme.surface) >= 7.0
    assert contrast_ratio(theme.text_on_accent, theme.accent) >= 4.3


def test_light_or_dark_comes_from_the_background_not_the_key():
    assert {key for key, theme in THEMES.items() if theme.is_light} == {"warm", "frost", "sand", "paper"}
    for theme in THEMES.values():
        assert theme.on_accent_is_light == (contrast_ratio("#ffffff", theme.text_on_accent) < 2)


def test_every_theme_is_named_and_described_in_every_language():
    for theme in THEMES.values():
        for language in LANGUAGES:
            assert theme.labels.get(language), (theme.key, language)
            assert theme_mood(theme, language), (theme.key, language)
        assert theme_display_label(theme, "zh-Hant") != theme.label  # not the English fallback
    assert len({theme_display_label(theme, "zh") for theme in THEMES.values()}) == len(THEMES)
    for family, _labels in THEME_FAMILIES:
        for language in LANGUAGES:
            assert theme_family_label(family, language)


def test_picker_order_covers_every_theme_once_and_groups_are_known():
    assert sorted(THEME_ORDER) == sorted(THEMES)
    assert [theme.key for theme in ordered_themes()] == list(THEME_ORDER)
    families = {name for name, _ in THEME_FAMILIES}
    assert {theme.family for theme in THEMES.values()} <= families
    assert set(THEME_TRAITS) == set(THEMES)


def test_original_five_keep_their_previous_character():
    # The values their old ``key ==`` branches returned (pre 2026-10-14).
    assert THEMES["grape"].text_on_accent == "#fff6f9"
    assert THEMES["warm"].text_on_accent == "#ffffff"
    for key in ("plum", "lavender", "slate"):
        assert THEMES[key].text_on_accent == THEMES[key].app_background
    assert THEMES["warm"].role_wash == (0.12, 0.18, 0.5)
    assert THEMES["grape"].role_wash == (0.08, 0.13, 0.32)
    assert THEMES["warm"].zone_colors["studio"] == "#b25a80"
    assert THEMES["grape"].zone_colors["studio"] == "#cc7f9e"
    assert THEMES["warm"].log_background == "#2b2d29"
    assert THEMES["slate"].log_background == THEMES["slate"].media
    assert THEMES["warm"].on_vivid == "#ffffff" and THEMES["plum"].on_vivid == THEMES["plum"].app_background


def test_no_module_branches_on_a_theme_key():
    """Light/dark and per-theme values come from ThemeDefinition, never ``theme.key == ...``."""
    offenders = []
    for path in (ROOT / "twobyteasr").rglob("*.py"):
        if path.name.endswith("_audit.py") or "selftest" in path.name or path.name == "ui_theme.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare) and isinstance(node.left, ast.Attribute) and node.left.attr == "key":
                values = [c.value for c in node.comparators if isinstance(c, ast.Constant)]
                values += [e.value for c in node.comparators if isinstance(c, (ast.Set, ast.Tuple, ast.List))
                           for e in c.elts if isinstance(e, ast.Constant)]
                if any(value in THEMES for value in values):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, offenders


@pytest.mark.parametrize("key", sorted(THEMES))
def test_timeline_palette_follows_theme_brightness_and_reads(key):
    from twobyteasr.timeline_theme import timeline_palette

    palette = timeline_palette(key)
    theme = THEMES[key]
    assert palette.key == key
    assert palette.dark == (not theme.is_light)
    assert contrast_ratio(palette.clip_text, palette.track_background) >= 4.5
    assert contrast_ratio(palette.playhead, palette.background) >= 2.5
    assert contrast_ratio(palette.playhead_label_text, palette.playhead) >= 4.0
    assert len(palette.speaker_accents) >= 5


def test_selection_over_video_stays_visible_in_every_theme():
    for key, theme in THEMES.items():
        assert contrast_ratio(theme.media_accent, theme.media) >= 2.5, key
    assert THEMES["paper"].media_accent == THEMES["paper"].focus      # ink accent would vanish on video
    assert THEMES["grape"].media_accent == THEMES["grape"].accent      # others keep their brand colour
