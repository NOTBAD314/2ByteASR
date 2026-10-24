"""Drop derived subtitle styles that no subtitle or speaker uses any more.

A scoped style edit derives copies such as ``<preset>-cue-<hash>`` or
``<preset>-scope-<hash>``. Until 2026-10-21 a batch apply with 「已选」 made one
copy per selected subtitle and a later apply never removed them: a 2,000-cue
project kept 2,001 styles and recipes, and every later commit froze, thawed and
copied all of them (about 2.5 s per Enter, memory growing with each edit).

Only derived ids (the tokens below, as ``recipe_payload_for_style`` reads them)
that nothing references are removed; base presets and ``default`` always stay.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

DERIVED_TOKENS = ("-fill-", "-scope-", "-cue-", "-canvas-")


def is_derived_style_id(style_id: object) -> bool:
    text = str(style_id or "")
    return any(token in text for token in DERIVED_TOKENS)


def referenced_style_ids(project: Any) -> set[str]:
    """Style ids a subtitle or a speaker points at."""
    ids = {str(cue.style_id) for cue in getattr(project, "cues", ()) or ()}
    ids.update(str(speaker.style_id) for speaker in getattr(project, "speakers", ()) or ())
    ids.update(layer_style_ids(getattr(project,'cues',())))
    return ids


def layer_style_ids(cues):
    ids=set()
    for cue in cues or ():
        transform=cue.get('transform',{}) if isinstance(cue,Mapping) else getattr(cue,'transform',{})
        layers=transform.get('language_layers',{}) if isinstance(transform,Mapping) else {}
        for value in layers.values() if isinstance(layers,Mapping) else ():
            if isinstance(value,Mapping) and value.get('style_id'):ids.add(str(value['style_id']))
    return ids


def without_unused_derived(styles: Iterable[Any], recipes: Mapping[str, Any] | None,
                           referenced: set[str]) -> tuple[list[Any], dict[str, Any], set[str]]:
    """``(styles, recipes, removed ids)`` keeping every base style and every referenced copy."""
    kept_styles, removed = [], set()
    for style in styles:
        if is_derived_style_id(style.id) and style.id not in referenced:
            removed.add(style.id)
        else:
            kept_styles.append(style)
    kept_recipes = {}
    for style_id, payload in (recipes or {}).items():
        if is_derived_style_id(style_id) and style_id not in referenced:
            removed.add(style_id)
        else:
            kept_recipes[style_id] = payload
    return kept_styles, kept_recipes, removed


def prune_unused_derived_payload(payload: dict[str, Any]) -> set[str]:
    """The same rule on raw project data, before dead entries become objects.

    Building thousands of dead recipes deep-copies each one; inside the running
    app that took 6–13 s for a 2,000-cue project (about 1 s on its own).
    """
    styles, recipes = payload.get("styles"), payload.get("style_recipes")
    if not isinstance(styles, list):
        return set()
    referenced = {
        str(item.get("style_id") or "default").strip() or "default"
        for key in ("cues", "speakers") for item in payload.get(key) or () if isinstance(item, Mapping)
    }
    referenced.update(layer_style_ids(payload.get('cues',())))
    removed = set()
    kept_styles = []
    for style in styles:
        style_id = str(style.get("id") or "") if isinstance(style, Mapping) else ""
        if is_derived_style_id(style_id) and style_id not in referenced:
            removed.add(style_id)
        else:
            kept_styles.append(style)
    if isinstance(recipes, Mapping):
        kept_recipes = {style_id: recipe for style_id, recipe in recipes.items()
                        if not (is_derived_style_id(style_id) and str(style_id) not in referenced)}
        removed.update(str(style_id) for style_id in recipes if str(style_id) not in kept_recipes)
        if len(kept_recipes) != len(recipes):
            payload["style_recipes"] = kept_recipes
    if len(kept_styles) != len(styles):
        payload["styles"] = kept_styles
    return removed


def prune_unused_derived_styles(project: Any) -> set[str]:
    """Remove unused derived styles from a loaded project in place; returns removed ids."""
    styles, recipes, removed = without_unused_derived(
        project.styles, project.style_recipes, referenced_style_ids(project))
    if removed:
        project.styles = styles
        project.style_recipes = recipes
    return removed
