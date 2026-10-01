"""Validated Native ASS motion DSL and deterministic override compilation.

Only this audited Native ASS vocabulary can reach libass. Complex visual
recipes are routed to the advanced renderer by :mod:`style_recipe` instead of
accepting arbitrary ASS or renderer code here.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


EFFECT_TYPES = {
    "none",
    "fade", "pop", "slide", "scale",  # P24 compatibility
    "soft_fade", "soft_pop", "punch", "float_up", "drop_in",
    "slide_soft", "blur_reveal", "emphasis", "karaoke_highlight",
    "bounce_lite",
}
EASING_PRESETS = {
    "linear": 1.0,
    "soft": 0.72,
    "smooth": 0.82,
    "snappy": 0.48,
    "ease_in": 1.65,
    "ease_out": 0.58,
    "ease_in_out": 0.78,
}
STRENGTH_PRESETS = {"low": 0.72, "medium": 1.0, "high": 1.28}
POSITION_EFFECT_TYPES = {"slide", "float_up", "drop_in", "slide_soft"}
TEXT_EFFECT_TYPES = {"emphasis", "karaoke_highlight"}
_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


class EffectValidationError(ValueError):
    pass


def _bounded_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise EffectValidationError(f"{name} must be an integer") from exc
    if not minimum <= number <= maximum:
        raise EffectValidationError(f"{name} must be between {minimum} and {maximum}")
    return number


def _bounded_float(value: Any, name: str, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise EffectValidationError(f"{name} must be a number") from exc
    if not minimum <= number <= maximum:
        raise EffectValidationError(f"{name} must be between {minimum} and {maximum}")
    return round(number, 3)


def _choice(value: Any, name: str, choices: set[str], default: str) -> str:
    text = str(value or default).strip().lower()
    if text not in choices:
        raise EffectValidationError(f"unsupported {name}: {text}")
    return text


def _color(value: Any, name: str, default: str) -> str:
    text = str(value or default).strip().upper()
    if not _HEX_COLOR.fullmatch(text):
        raise EffectValidationError(f"{name} must be #RRGGBB or #AARRGGBB")
    return text


def _terms(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise EffectValidationError("terms must be a list")
    result: list[str] = []
    for item in value:
        term = str(item or "").strip()
        if term and term not in result:
            result.append(term)
    if len(result) > 64:
        raise EffectValidationError("terms must contain at most 64 items")
    return result


def validate_effect_part(value: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = dict(value or {})
    effect_type = str(payload.get("type") or "none").strip().lower()
    if effect_type not in EFFECT_TYPES:
        raise EffectValidationError(f"unsupported effect type: {effect_type}")
    allowed = {
        "type", "duration", "delay", "easing", "accel", "strength",
        "scale_from", "scale_to", "overshoot", "offset_x", "offset_y",
        "blur", "color", "terms", "granularity",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise EffectValidationError(f"unknown effect fields: {sorted(unknown)}")
    result: dict[str, Any] = {"type": effect_type}
    if effect_type == "none":
        return result

    result["duration"] = _bounded_int(payload.get("duration", 180), "duration", 1, 4000)
    result["delay"] = _bounded_int(payload.get("delay", 0), "delay", 0, 2000)
    result["easing"] = _choice(payload.get("easing"), "easing", set(EASING_PRESETS), "soft")
    result["accel"] = _bounded_float(
        payload.get("accel", EASING_PRESETS[result["easing"]]), "accel", 0.1, 5.0
    )
    result["strength"] = _choice(
        payload.get("strength"), "strength", set(STRENGTH_PRESETS), "medium"
    )

    if effect_type in {"pop", "scale", "soft_pop", "punch", "bounce_lite", "emphasis"}:
        defaults = {
            "pop": (85, 100, 100), "scale": (92, 100, 100),
            "soft_pop": (95, 100, 103), "punch": (80, 100, 108),
            "bounce_lite": (90, 100, 105), "emphasis": (100, 100, 112),
        }[effect_type]
        result["scale_from"] = _bounded_int(payload.get("scale_from", defaults[0]), "scale_from", 10, 400)
        result["scale_to"] = _bounded_int(payload.get("scale_to", defaults[1]), "scale_to", 10, 400)
        result["overshoot"] = _bounded_int(payload.get("overshoot", defaults[2]), "overshoot", 10, 400)
    if effect_type in POSITION_EFFECT_TYPES:
        defaults = {
            "slide": (0, 80), "float_up": (0, 28),
            "drop_in": (0, -34), "slide_soft": (-52, 0),
        }[effect_type]
        result["offset_x"] = _bounded_int(payload.get("offset_x", defaults[0]), "offset_x", -1000, 1000)
        result["offset_y"] = _bounded_int(payload.get("offset_y", defaults[1]), "offset_y", -1000, 1000)
    if effect_type == "blur_reveal":
        result["blur"] = _bounded_float(payload.get("blur", 6.0), "blur", 0.0, 30.0)
    if effect_type in TEXT_EFFECT_TYPES:
        result["color"] = _color(payload.get("color"), "color", "#FFD166")
    if effect_type == "emphasis":
        result["terms"] = _terms(payload.get("terms"))
    if effect_type == "karaoke_highlight":
        result["granularity"] = _choice(
            payload.get("granularity"), "granularity", {"word", "character"}, "word"
        )
    return result


def validate_effect(value: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = dict(value or {})
    if "entry" in payload or "exit" in payload or "word_highlight" in payload:
        unknown = set(payload) - {"entry", "exit", "word_highlight"}
        if unknown:
            raise EffectValidationError(f"unknown effect fields: {sorted(unknown)}")
        result = {
            "entry": validate_effect_part(payload.get("entry")),
            "exit": validate_effect_part(payload.get("exit")),
        }
        if "word_highlight" in payload:
            highlight = validate_effect_part(payload.get("word_highlight"))
            if highlight["type"] not in TEXT_EFFECT_TYPES | {"none"}:
                raise EffectValidationError("word_highlight must be emphasis or karaoke_highlight")
            result["word_highlight"] = highlight
        return result
    return {"entry": validate_effect_part(payload), "exit": {"type": "none"}}


def builtin_effects() -> dict[str, dict[str, Any]]:
    """Return restrained presets suitable for long-form subtitle defaults."""
    raw = {
        "none": {"type": "none"},
        "fade": {"entry": {"type": "fade", "duration": 180}, "exit": {"type": "fade", "duration": 150}},
        "pop": {"type": "pop", "duration": 180, "scale_from": 85, "scale_to": 100},
        "slide": {"type": "slide", "duration": 200, "offset_y": 70},
        "scale": {"type": "scale", "duration": 180, "scale_from": 92, "scale_to": 100},
        "soft_fade": {"entry": {"type": "soft_fade", "duration": 180}, "exit": {"type": "soft_fade", "duration": 140, "easing": "ease_in"}},
        "soft_pop": {"entry": {"type": "soft_pop", "duration": 220}, "exit": {"type": "soft_fade", "duration": 130}},
        "punch": {"entry": {"type": "punch", "duration": 180, "easing": "snappy"}, "exit": {"type": "soft_fade", "duration": 120}},
        "float_up": {"entry": {"type": "float_up", "duration": 240}, "exit": {"type": "soft_fade", "duration": 140}},
        "drop_in": {"entry": {"type": "drop_in", "duration": 240}, "exit": {"type": "soft_fade", "duration": 140}},
        "slide_soft": {"entry": {"type": "slide_soft", "duration": 240}, "exit": {"type": "soft_fade", "duration": 140}},
        "blur_reveal": {"entry": {"type": "blur_reveal", "duration": 240, "blur": 6}, "exit": {"type": "soft_fade", "duration": 140}},
        "emphasis": {"entry": {"type": "emphasis", "duration": 240, "color": "#FFD166"}, "exit": {"type": "none"}},
        "karaoke_highlight": {"entry": {"type": "karaoke_highlight", "duration": 180, "color": "#7DD3FC"}, "exit": {"type": "none"}},
        "bounce_lite": {"entry": {"type": "bounce_lite", "duration": 280}, "exit": {"type": "soft_fade", "duration": 130}},
    }
    return {effect_id: validate_effect(value) for effect_id, value in raw.items()}


def _number(value: float) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.3f}".rstrip("0").rstrip(".")


def _transform(start: int, end: int, accel: float, tags: str) -> str:
    return f"\\t({start},{end},{_number(accel)},{tags})"


def _scaled(value: int, strength: str, origin: int = 100) -> int:
    return round(origin + (int(value) - origin) * STRENGTH_PRESETS[strength])


def _scale_tags(value: int) -> str:
    return f"\\fscx{value}\\fscy{value}"


def _ass_color(value: str) -> str:
    digits = value.lstrip("#")[-6:]
    red, green, blue = digits[0:2], digits[2:4], digits[4:6]
    return f"&H{blue}{green}{red}&"


def compile_effect_override(
    effect: Mapping[str, Any] | None,
    *,
    cue_duration_ms: int,
    play_res_x: int,
    play_res_y: int,
    target_position: tuple[int, int] | None = None,
) -> str:
    normalized = validate_effect(effect)
    entry = normalized["entry"]
    exit_effect = normalized["exit"]
    cue_duration = max(1, int(cue_duration_ms))
    tags: list[str] = []

    fade_in = entry.get("duration", 0) if entry["type"] == "fade" else 0
    fade_out = exit_effect.get("duration", 0) if exit_effect["type"] == "fade" else 0
    if fade_in or fade_out:
        tags.append(f"\\fad({min(cue_duration, fade_in)},{min(cue_duration, fade_out)})")

    entry_type = entry["type"]
    if entry_type == "soft_fade":
        start = min(cue_duration, entry["delay"])
        end = min(cue_duration, start + entry["duration"])
        tags.extend(("\\alpha&HFF&", _transform(start, end, entry["accel"], "\\alpha&H00&")))
    elif entry_type in {"pop", "scale"}:
        duration = min(cue_duration, entry["duration"])
        tags.extend((_scale_tags(entry["scale_from"]), f"\\t(0,{duration},{_scale_tags(entry['scale_to'])})"))
    elif entry_type in {"soft_pop", "punch", "bounce_lite"}:
        start = min(cue_duration, entry["delay"])
        end = min(cue_duration, start + entry["duration"])
        duration = max(1, end - start)
        first = start + round(duration * (0.56 if entry_type != "bounce_lite" else 0.42))
        scale_from = _scaled(entry["scale_from"], entry["strength"])
        overshoot = _scaled(entry["overshoot"], entry["strength"])
        target = entry["scale_to"]
        tags.append(_scale_tags(scale_from))
        tags.append(_transform(start, first, entry["accel"], _scale_tags(overshoot)))
        if entry_type == "bounce_lite":
            second = start + round(duration * 0.74)
            settle = _scaled(98, entry["strength"])
            tags.append(_transform(first, second, 1.45, _scale_tags(settle)))
            tags.append(_transform(second, end, 0.68, _scale_tags(target)))
        else:
            tags.append(_transform(first, end, 1.55, _scale_tags(target)))
    elif entry_type in POSITION_EFFECT_TYPES:
        duration = min(cue_duration, entry["duration"])
        target_x, target_y = target_position or (
            max(0, int(play_res_x) // 2), max(0, int(play_res_y) - 90)
        )
        factor = STRENGTH_PRESETS[entry["strength"]]
        offset_x = round(entry["offset_x"] * factor)
        offset_y = round(entry["offset_y"] * factor)
        delay = min(cue_duration, entry["delay"])
        tags.append(
            f"\\move({target_x + offset_x},{target_y + offset_y},{target_x},{target_y},{delay},{min(cue_duration, delay + duration)})"
        )
        if entry_type != "slide":
            tags.extend(("\\alpha&HFF&", _transform(delay, min(cue_duration, delay + duration), entry["accel"], "\\alpha&H00&")))
    elif entry_type == "blur_reveal":
        start = min(cue_duration, entry["delay"])
        end = min(cue_duration, start + entry["duration"])
        blur = entry["blur"] * STRENGTH_PRESETS[entry["strength"]]
        tags.extend((f"\\blur{_number(blur)}\\alpha&HFF&", _transform(start, end, entry["accel"], "\\blur0\\alpha&H00&")))

    if exit_effect["type"] == "soft_fade":
        duration = min(cue_duration, exit_effect["duration"])
        end = max(0, cue_duration - min(cue_duration, exit_effect["delay"]))
        start = max(0, end - duration)
        tags.append(_transform(start, end, exit_effect["accel"], "\\alpha&HFF&"))
    elif exit_effect["type"] in {"pop", "scale", "soft_pop", "punch", "bounce_lite"}:
        duration = min(cue_duration, exit_effect["duration"])
        end = max(0, cue_duration - min(cue_duration, exit_effect["delay"]))
        start = max(0, end - duration)
        target = _scaled(exit_effect["scale_from"], exit_effect["strength"])
        tags.append(_transform(start, end, exit_effect["accel"], _scale_tags(target)))
    return "".join(tags)


def compile_position_motion_segments(
    effect: Mapping[str, Any] | None,
    *,
    cue_duration_ms: int,
    target_position: tuple[int, int],
) -> list[tuple[int, int, str]]:
    """Approximate eased ASS movement with four short, gap-free events.

    libass intentionally keeps ``\\move`` linear and does not animate
    ``\\pos`` inside ``\\t``. Splitting only the restrained entry interval
    gives Float/Drop/Slide Soft an actual curve while the remainder of a long
    subtitle stays a single inexpensive event.
    """
    normalized = validate_effect(effect)
    entry = normalized["entry"]
    if entry["type"] not in {"float_up", "drop_in", "slide_soft"}:
        return []
    cue_duration = max(1, int(cue_duration_ms))
    delay = min(cue_duration, entry["delay"])
    duration = min(max(0, cue_duration - delay), entry["duration"])
    if duration <= 0:
        return []
    target_x, target_y = target_position
    factor = STRENGTH_PRESETS[entry["strength"]]
    origin_x = target_x + round(entry["offset_x"] * factor)
    origin_y = target_y + round(entry["offset_y"] * factor)
    boundaries = [0, round(duration * 0.24), round(duration * 0.52), round(duration * 0.78), duration]
    boundaries = sorted(set(boundaries))
    frames: list[tuple[int, int, str]] = []
    for start, end in zip(boundaries, boundaries[1:]):
        p0 = (start / duration) ** entry["accel"]
        p1 = (end / duration) ** entry["accel"]
        x0 = round(origin_x + (target_x - origin_x) * p0)
        y0 = round(origin_y + (target_y - origin_y) * p0)
        x1 = round(origin_x + (target_x - origin_x) * p1)
        y1 = round(origin_y + (target_y - origin_y) * p1)
        local_duration = max(1, end - start)
        alpha0 = max(0, min(255, round(255 * (1.0 - p0))))
        alpha1 = max(0, min(255, round(255 * (1.0 - p1))))
        override = f"\\move({x0},{y0},{x1},{y1},0,{local_duration})"
        override += f"\\alpha&H{alpha0:02X}&\\t(0,{local_duration},1,\\alpha&H{alpha1:02X}&)"
        frames.append((delay + start, delay + end, override))
    return frames


def compile_effect_text(
    escaped_text: str,
    effect: Mapping[str, Any] | None,
    *,
    cue_duration_ms: int,
) -> str:
    """Add audited emphasis/karaoke tags to already escaped cue text."""
    normalized = validate_effect(effect)
    entry = normalized.get("word_highlight", normalized["entry"])
    if entry["type"] == "emphasis" and entry["terms"]:
        terms = sorted(entry["terms"], key=len, reverse=True)
        pattern = re.compile("(" + "|".join(re.escape(item) for item in terms) + ")", re.IGNORECASE)
        color = _ass_color(entry["color"])
        peak = _scaled(entry["overshoot"], entry["strength"])
        duration = min(max(1, int(cue_duration_ms)), entry["duration"])
        prefix = "{\\1c" + color + _scale_tags(100) + _transform(0, duration // 2, entry["accel"], _scale_tags(peak)) + _transform(duration // 2, duration, 1.45, _scale_tags(100)) + "}"
        return pattern.sub(lambda match: prefix + match.group(0) + "{\\r}", escaped_text)
    if entry["type"] == "karaoke_highlight":
        units = (
            re.findall(r"\\N|.", escaped_text, re.DOTALL)
            if entry["granularity"] == "character"
            else re.findall(r"\\N|\s+|[^\s]+", escaped_text)
        )
        visible = [unit for unit in units if unit and not unit.isspace() and unit != r"\N"]
        if not visible:
            return escaped_text
        per_unit = max(1, max(1, int(cue_duration_ms)) // 10 // len(visible))
        output = ["{\\1c" + _ass_color(entry["color"]) + "}"]
        for unit in units:
            output.append(unit if (not unit or unit.isspace() or unit == r"\N") else f"{{\\kf{per_unit}}}{unit}")
        output.append("{\\r}")
        return "".join(output)
    return escaped_text
