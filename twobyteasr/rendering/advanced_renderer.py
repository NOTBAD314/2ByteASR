"""Safe Python boundary for the trusted Remotion subtitle renderer."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from .caption_asset_identity import renderer_identity_scope,current_identity_cache
from pathlib import Path
from typing import Callable, Mapping

from .ass_compiler import compile_ass
from ..exports.export_validation import record_completion, publish_output, notify_after_publication
from ..projects.studio_project import SubtitleProject
from ..exports.studio_render import (
    RenderJob, STAGE_ADVANCED_RENDER, STAGE_ENCODE, STAGE_MUX,
    STAGE_PREPARE_PROJECT, STAGE_PREPARE_SUBTITLES, _quality_arguments,
    encoder_preset, export_progress, parse_ffmpeg_out_time_seconds, select_encoder,
)
from ..caption_style.style_recipe import (
    FillSpec,
    StyleRecipe,
    normalize_glow_contract,
    normalize_motion_contract,
    normalize_shadow_contract,
    recipe_payload_for_style,
    route_recipe,
    background_padding,
)
from ..caption_style.visual_snapshot import VisualCueSnapshot, build_visual_cue_snapshot
from ..system.processes import popen_hidden_subprocess, renderer_node_command, renderer_child_environment


TRUSTED_COMPONENTS = frozenset({
    "TextLayer", "GradientFill", "StrokeLayer", "GlowLayer", "ShadowLayer",
    "HUDFrame", "Scanline", "GlitchSlice", "AccentLine", "ParticleLite",
    "Fade", "Pop", "Scale", "Slide", "Bounce", "Glitch", "Flicker",
    "Tracking", "Reveal",
})
TRUSTED_DECORATIONS = frozenset({
    "corner_brackets", "left_bracket", "right_bracket", "scanline",
    "side_line", "underline", "accent_line", "particle_lite", "vignette",
    "film_perforation", "speech_tail", "tape", "registration_marks",
})
TRUSTED_BACKGROUND_TYPES = frozenset({
    "none", "solid", "paper", "film_card", "speech_bubble", "label_strip",
    "pixel_panel", "neon_frame", "tv_plate", "glitch_terminal",
})
TRUSTED_TEXTURES = frozenset({
    "none", "paper_grain", "film_grain", "halftone", "scanlines", "pixel_grid", "noise",
})
TRUSTED_MASKS = frozenset({"none", "wipe", "radial", "ink", "paper_tear", "glitch_slices"})


class AdvancedRendererUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class AdvancedRendererStatus:
    available: bool
    reason: str = ""


def project_color_to_css(value: object, fallback: str = "#FFFFFF") -> str:
    """Convert canonical Qt ``#AARRGGBB`` into CSS ``#RRGGBBAA``."""
    text = str(value or fallback)
    if len(text) == 9 and text.startswith("#"):
        return f"#{text[3:]}{text[1:3]}"
    return text if len(text) == 7 and text.startswith("#") else fallback


def css_color_to_project(value: object, fallback: str = "#FFFFFFFF") -> str:
    """Convert CSS ``#RRGGBBAA`` back into canonical Qt ``#AARRGGBB``."""
    text = str(value or fallback)
    if len(text) == 9 and text.startswith("#"):
        return f"#{text[7:9]}{text[1:7]}"
    return text if len(text) == 7 and text.startswith("#") else fallback


def _css_color(value: object, fallback: str) -> str:
    return project_color_to_css(value, fallback)


def _css_color_with_opacity(value: object, fallback: str, opacity: float) -> str:
    color = _css_color(value, fallback)
    alpha = max(0.0, min(1.0, float(opacity)))
    if len(color) == 7 and color.startswith("#"):
        return f"{color}{round(alpha * 255):02X}"
    if len(color) == 9 and color.startswith("#"):
        source_alpha = int(color[7:9], 16) / 255.0
        return f"{color[:7]}{round(source_alpha * alpha * 255):02X}"
    return color


def normalize_shadow(value: object) -> dict[str, object]:
    """Compile legacy strength or canonical fields to one renderer contract."""

    raw = normalize_shadow_contract(value)
    normalized = {
        "enabled": bool(raw["enabled"]),
        "color": _css_color(raw["color"], "#000000"),
        "opacity": float(raw["opacity"]),
        "offsetX": float(raw["offset_x"]),
        "offsetY": float(raw["offset_y"]),
        "blur": float(raw["blur"]),
        "spread": float(raw["spread"]),
        **({'paint': deepcopy(raw['paint'])} if raw.get('paint') else {}),
    }
    return normalized


def normalize_glow(value: object) -> dict[str, object]:
    raw = normalize_glow_contract(value)
    enabled = bool(raw["enabled"])
    opacity = min(1.0, float(raw["opacity"]) * float(raw["intensity"])) if enabled else 0.0
    return {
        "color": _css_color_with_opacity(raw["color"], "#20D6E8", opacity),
        "blur": float(raw["radius"]) if enabled else 0.0,
        "opacity": opacity,
        **({'paint': deepcopy(raw['paint'])} if raw.get('paint') else {}),
    }


def recipe_payload_for_cue(project: SubtitleProject, cue) -> Mapping[str, object] | None:
    from ..caption_style.style_resolution import recipe_for_cue
    return recipe_for_cue(project.style_recipes, cue)


def project_requires_advanced(project: SubtitleProject, *, start_ms=None, end_ms=None) -> bool:
    hidden = project.hidden_speaker_ids()
    for cue in project.cues:
        if cue.speaker_id in hidden:continue
        if start_ms is not None and cue.end_ms <= start_ms:continue
        if end_ms is not None and cue.start_ms >= end_ms:continue
        payload = recipe_payload_for_cue(project, cue)
        if payload and route_recipe(payload).engine == "remotion":
            return True
    return False


def split_renderer_cues(project: SubtitleProject) -> tuple[list, list]:
    """Return native and advanced cues without changing their project order."""
    native, advanced = [], []
    for cue in project.cues:
        payload = recipe_payload_for_cue(project, cue)
        if payload and route_recipe(payload).engine == "remotion":
            advanced.append(cue)
        else:
            native.append(cue)
    return native, advanced


def advanced_preview_cache_key(
    recipe: Mapping[str, object], cue_text: str, *, width: int, height: int,
    fps: float, duration_seconds: float, font: str,
) -> str:
    """Stable key for low-cost Remotion previews; all visual inputs participate."""
    import hashlib
    payload = {
        "recipe": StyleRecipe.from_dict(recipe).to_dict(),
        "cueText": str(cue_text), "resolution": [int(width), int(height)],
        "fps": float(fps), "duration": float(duration_seconds), "font": str(font),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def cue_visual_cache_key(snapshot: VisualCueSnapshot) -> str:
    """Cue previews and gallery thumbnails intentionally use different keys."""
    import hashlib
    return hashlib.sha256(("cue-visual-v1:" + snapshot.stable_hash()).encode("utf-8")).hexdigest()


def _ffmpeg_filter_path(path: str | os.PathLike[str]) -> str:
    from ..exports.ffmpeg_paths import filter_path
    return filter_path(path)


def _native_segment_project(project: SubtitleProject, start_ms: int, end_ms: int) -> SubtitleProject:
    native, _advanced = split_renderer_cues(project)
    segment = deepcopy(project)
    segment.cues = []
    segment._word_animation_plans = {}
    from ..caption_style.bilingual_layout import project_display_cues
    from ..caption_style.collision_layout import project_layout_schedule
    schedule = project_layout_schedule(project, project_display_cues(project))
    segment._subtitle_layout_schedule = {
        key: [(max(0, a-start_ms), min(end_ms-start_ms, b-start_ms), offset)
              for a, b, offset in spans if a < end_ms and b > start_ms]
        for key, spans in schedule.items()}
    # 三十八轮：隐藏的说话人轨不进高保真预览（与导出/压制一致）。
    hidden = getattr(project, "hidden_speaker_ids", None)
    hidden_ids = hidden() if callable(hidden) else frozenset()
    for source in native:
        if source.speaker_id in hidden_ids:
            continue
        if source.end_ms <= start_ms or source.start_ms >= end_ms:
            continue
        cue = deepcopy(source)
        cue.start_ms = max(0, source.start_ms - start_ms)
        cue.end_ms = min(end_ms - start_ms, source.end_ms - start_ms)
        from ..caption_style.word_animation import build_word_animation
        plan = build_word_animation(project, source)
        if plan:
            cut = max(0, start_ms-source.start_ms)
            plan = deepcopy(plan)
            plan['original_duration_ms'] = plan['duration_ms']
            plan['clock_offset_ms'] = cut
            plan['duration_ms'] = cue.end_ms-cue.start_ms
            for span in plan['spans']:
                span['start_ms'] -= cut
                span['end_ms'] -= cut
            segment._word_animation_plans[cue.id] = plan
        segment.cues.append(cue)
    return segment


def _run_streaming_process(command: list[str], *, cwd: Path | None = None,
                           on_line: Callable[[str], None] | None = None,
                           cancelled: Callable[[], bool] | None = None,
                           stall_timeout: float | None = None,
                           purpose: str = "advanced preview/render child") -> tuple[int, str]:
    if command and Path(command[0]).name.lower() in {'node.exe', 'node'}:
        from .renderer_export_temp import renderer_temporary_environment
        with renderer_temporary_environment(renderer_child_environment()) as child_env:
            return _run_streaming_process_impl(command, cwd=cwd, on_line=on_line,
                cancelled=cancelled, stall_timeout=stall_timeout, purpose=purpose, child_env=child_env)
    return _run_streaming_process_impl(command, cwd=cwd, on_line=on_line,
        cancelled=cancelled, stall_timeout=stall_timeout, purpose=purpose)


def _run_streaming_process_impl(command, *, cwd=None, on_line=None, cancelled=None,
                                stall_timeout=None, purpose="advanced preview/render child", child_env=None):
    import queue
    from ..exports.export_failure import ErrorEvidence, ProcessEvidence
    separate = Path(str(command[0])).stem.lower().startswith('ffmpeg')
    evidence = ErrorEvidence()

    process = popen_hidden_subprocess(
        command, cwd=cwd, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE if separate else subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        purpose=purpose,
        own_process_tree=True,
        env=child_env,
    )
    tail: list[str] = []
    state = {"last_line": time.monotonic(), "stall_killed": False, "cancelled": False}
    finished = threading.Event()
    cleanup_lock = threading.Lock()
    cleanup_done = False
    cleanup_error = None

    def cleanup() -> None:
        nonlocal cleanup_done, cleanup_error
        with cleanup_lock:
            if cleanup_error is not None:
                raise cleanup_error
            if cleanup_done:
                return
            try:
                job = getattr(process, "_request_job", None)
                if job is not None:
                    # A parent exit does not release ownership of descendants.
                    job.close(timeout=3)
                else:
                    from ..system.processes import stop_process_tree
                    stop_process_tree(process)
            except BaseException as exc:
                cleanup_error = exc
                raise
            cleanup_done = True

    def stall_watchdog() -> None:
        # Remotion 正常时每帧都打 "Rendered N/M"（行级心跳）；静默超过
        # stall_timeout 且进程仍存活 = 真挂死，主动终止让导出给出明确
        # 报错而不是永远停在"高级字幕渲染"。
        try:
            while not finished.wait(.05):
                if cancelled and cancelled():
                    state['cancelled'] = True
                    cleanup()
                    return
                if process.poll() is not None:
                    # Descendants can still hold stdout after the root exits.
                    cleanup()
                    return
                if stall_timeout and time.monotonic() - state["last_line"] > float(stall_timeout):
                    state["stall_killed"] = True
                    cleanup()
                    return
        except BaseException as exc:
            # The consumer must observe failure even if a child holds the pipe.
            state["watchdog_error"] = exc

    watchdog = threading.Thread(
        target=stall_watchdog, daemon=True, name="advanced-render-stall-watchdog"
    )
    assert process.stdout is not None
    lines = queue.Queue(maxsize=256)
    eof = object()

    def enqueue(value) -> None:
        while not finished.is_set():
            try:
                lines.put(value, timeout=.05)
                return
            except queue.Full:
                continue

    def read_lines(stream, channel) -> None:
        try:
            for raw in iter(stream.readline, ""):
                enqueue((channel, raw))
                if finished.is_set():
                    return
        except BaseException as exc:
            enqueue(exc)
        finally:
            enqueue((channel, eof))

    readers = [threading.Thread(target=read_lines, args=(process.stdout, 'stdout'),
               daemon=True, name='advanced-render-stdout')]
    if separate:
        readers.append(threading.Thread(target=read_lines, args=(process.stderr, 'stderr'),
                       daemon=True, name='advanced-render-stderr'))
    for reader in readers:
        reader.start()
    watchdog.start()
    try:
        remaining = len(readers)
        while remaining:
            if cleanup_error is not None:
                raise cleanup_error
            if "watchdog_error" in state:
                raise state["watchdog_error"]
            try:
                raw = lines.get(timeout=.05)
            except queue.Empty:
                continue
            if isinstance(raw, BaseException):
                raise raw
            channel, raw = raw
            if raw is eof:
                remaining -= 1
                continue
            line = raw.strip()
            state["last_line"] = time.monotonic()
            if line:
                if separate:
                    evidence.feed(channel, line)
                else:
                    evidence.feed('stderr',line)
                    tail.append(line)
                    del tail[:-120]
                if on_line and (not separate or channel == 'stdout'):
                    on_line(line)
        while True:
            if cleanup_error is not None:
                raise cleanup_error
            if "watchdog_error" in state:
                raise state["watchdog_error"]
            try:
                code = process.wait(timeout=.05)
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        finished.set()
        try:
            cleanup()
        finally:
            watchdog.join(timeout=3.5)
            for reader in readers:
                reader.join(timeout=.2)
            # A failed Job close can leave another thread inside readline.
            # Closing its TextIOWrapper here would wait on that read lock.
            if not readers[0].is_alive():
                process.stdout.close()
            if separate and not readers[1].is_alive():
                process.stderr.close()
    if state['cancelled'] or (cancelled and cancelled()):
        raise InterruptedError("render cancelled")
    if state["stall_killed"]:
        tail.append(f"[2ByteASR] 渲染进程超过 {stall_timeout:.0f}s 无输出，已终止（疑似挂死）。")
        raise RuntimeError("\n".join(tail[-12:]))
    return code, evidence.result() if separate else ProcessEvidence("\n".join(tail), errors=evidence.errors)


def _normalized_recipe(payload: Mapping[str, object]) -> dict[str, object]:
    recipe = StyleRecipe.from_dict(payload)
    if route_recipe(recipe).engine != "remotion":
        raise ValueError("advanced renderer received a Native-only recipe")
    typography, outline = recipe.typography, recipe.outline
    fill_spec = recipe.fill_spec()
    if fill_spec.kind != "solid":
        stops = [
            {"color": _css_color(stop.get("color"), "#FFFFFF"), "pos": float(stop.get("position", 0))}
            for stop in fill_spec.stops
        ]
        fill: object = {
            "type": "gradient",
            "kind": "radial" if fill_spec.kind == "radial-gradient" else "linear",
            "radius": fill_spec.radius,
            "angle": float(fill_spec.angle), "stops": stops,
        }
    else:
        fill = {"type": "solid", "color": _css_color(fill_spec.color, "#FFFFFF")}
    layers = outline.get("layers") if isinstance(outline.get("layers"), list) else None
    if layers:
        strokes = [
            {"color": _css_color(layer.get("color"), "#000000"), "width": min(30.0, max(0.0, float(layer.get("width", 0))))}
            for layer in layers if isinstance(layer, Mapping)
        ][:4]
    else:
        strokes = [{
            "color": _css_color(outline.get("color", recipe.colors.get("outline")), "#000000"),
            "width": min(30.0, max(0.0, float(outline.get("width", 3)))),
            "alignment": "OUTSIDE",
        }]
    raw_marks = list(recipe.background.get("marks", []))
    effects = recipe.effects if isinstance(recipe.effects, Mapping) else {}
    raw_marks.extend(effects.get("decorations", []) if isinstance(effects.get("decorations"), list) else [])
    decorations = []
    for item in raw_marks:
        value = str(item.get("type") if isinstance(item, Mapping) else item)
        if value in TRUSTED_DECORATIONS and value not in decorations:
            decorations.append(value)
    decorations = decorations[:16]
    glow = normalize_glow(effects.get("glow", {}))
    background = recipe.background if isinstance(recipe.background, Mapping) else {}
    padding_top, padding_right, padding_bottom, padding_left = background_padding(background)
    background_type = str(background.get("type", background.get("style", "solid" if background.get("enabled") else "none")))
    if background_type not in TRUSTED_BACKGROUND_TYPES:
        background_type = "solid" if background.get("enabled") else "none"
    background_gradient = background.get("gradient") if isinstance(background.get("gradient"), Mapping) else {}
    gradient_colors = [
        _css_color(item, "#00000000")
        for item in background_gradient.get("colors", [])
        if str(item)
    ][:3]
    border = background.get("border") if isinstance(background.get("border"), Mapping) else {}
    background_shadow = background.get("shadow") if isinstance(background.get("shadow"), Mapping) else {}
    background_texture = background.get("texture") if isinstance(background.get("texture"), Mapping) else {}
    if not background_texture and isinstance(effects.get("texture"), Mapping):
        background_texture = effects.get("texture", {})
    texture_type = str(background_texture.get("type") or "none")
    if texture_type not in TRUSTED_TEXTURES:
        texture_type = "none"
    background_transform = background.get("transform") if isinstance(background.get("transform"), Mapping) else {}
    mask = effects.get("mask") if isinstance(effects.get("mask"), Mapping) else {}
    mask_type = str(mask.get("type") or "none")
    if mask_type not in TRUSTED_MASKS:
        mask_type = "none"
    shadow_value = outline.get("shadow", effects.get("shadow", 0))
    shadow = shadow_value if isinstance(shadow_value, Mapping) else {"distance": shadow_value}
    motion = normalize_motion_contract(
        recipe.motion if isinstance(recipe.motion, Mapping) else {}
    )
    normalized_shadow = normalize_shadow(shadow)
    normalized = {
        "name": recipe.name,
        "components": sorted(TRUSTED_COMPONENTS),
        "typography": {
            "fontFamily": str(typography.get("fontFamily") or "Microsoft YaHei UI"),
            "fontSize": min(220.0, max(12.0, float(typography.get("fontSize", 58)))),
            "bold": bool(typography.get("bold", True)),
            "italic": bool(typography.get("italic", False)),
            "spacing": min(30.0, max(-5.0, float(typography.get("spacing", 0)))),
        },
        "fill": fill,
        "strokes": strokes,
        "glow": glow,
        "shadow": normalized_shadow,
        "background": {
            "enabled": bool(background.get("enabled", False)),
            **({'paint': deepcopy(background['paint'])} if background.get('paint') else {}),
            "type": background_type,
            "color": _css_color(background.get("fill", background.get("color", recipe.colors.get("background"))), "#00000000"),
            "gradient": {
                "colors": gradient_colors,
                "angle": float(background_gradient.get("angle", 0) or 0),
            },
            "opacity": min(1.0, max(0.0, float(background.get("opacity", 1) or 0))),
            "paddingX": padding_right,
            "paddingY": padding_top,
            "paddingTop": padding_top,
            "paddingRight": padding_right,
            "paddingBottom": padding_bottom,
            "paddingLeft": padding_left,
            "radius": min(40.0, max(0.0, float(background.get("radius", 8) or 0))),
            "border": {
                "color": _css_color(border.get("color"), "#00000000"),
                "width": min(16.0, max(0.0, float(border.get("width", 0) or 0))),
            },
            "shadow": {
                "color": _css_color(background_shadow.get("color"), "#00000055"),
                "offsetX": float(background_shadow.get("offset_x", 0) or 0),
                "offsetY": float(background_shadow.get("offset_y", 2) or 0),
                "blur": min(40.0, max(0.0, float(background_shadow.get("blur", 8) or 0))),
            },
            "texture": {
                "type": texture_type,
                "opacity": min(1.0, max(0.0, float(background_texture.get("opacity", 0) or 0))),
                "scale": min(8.0, max(0.25, float(background_texture.get("scale", 1) or 1))),
                "seed": int(background_texture.get("seed", 0) or 0) % 10000,
            },
            "transform": {
                "rotation": min(12.0, max(-12.0, float(background_transform.get("rotation", 0) or 0))),
                "scale": min(1.4, max(0.7, float(background_transform.get("scale", 100) or 100) / 100.0)),
                "offsetX": min(200.0, max(-200.0, float(background_transform.get("offset_x", 0) or 0))),
                "offsetY": min(200.0, max(-200.0, float(background_transform.get("offset_y", 0) or 0))),
            },
        },
        "mask": {
            "type": mask_type,
            "softness": min(1.0, max(0.0, float(mask.get("softness", 0) or 0))),
            "direction": str(mask.get("direction") or "left"),
        },
        "decorations": decorations,
        "motion": motion,
        "layout": {
            "alignment": int(recipe.layout.get("alignment", 2)),
            "marginV": int(recipe.layout.get("marginV", 64)),
        },
    }
    if recipe.visual_graph:
        normalized["visualGraph"] = deepcopy(recipe.visual_graph)
    if recipe.web_theme:
        # Web themes carry their own stage sizing; only the text-appearance
        # tokens ride along and are re-bound to the snapshot in
        # normalized_visual_snapshot.
        normalized["webTheme"] = deepcopy(recipe.web_theme)
    return normalized


def scale_visual_for_composition(visual: dict[str, object], composition_width: int) -> dict[str, object]:
    """Rescale play-resolution absolute pixels to a preview composition width.

    TrustedSubtitle positions text with playRes-relative percentages, but
    font size, stroke widths, glow blur and letter spacing are absolute play-
    resolution pixels. Rendering those unchanged into a 640px preview
    composition magnifies the type by playRes/width (e.g. 3x for 1920),
    which is the "giant vertical subtitle" regression. The final render uses
    the real video resolution, where this scale factor is exactly 1.
    """
    # Graph and HTML renderers perform their own stage conversion.
    if visual.get('visualGraph') or visual.get('webTheme'):
        return visual
    layout = visual.get("layout") if isinstance(visual.get("layout"), Mapping) else {}
    play_res_x = int(layout.get("playResX") or 1920)
    composition_width = max(1, int(composition_width))
    if play_res_x <= 0 or abs(play_res_x - composition_width) < 1:
        return visual
    scale = composition_width / play_res_x

    scaled = deepcopy(visual)
    typography = scaled.get("typography") if isinstance(scaled.get("typography"), Mapping) else {}
    if "fontSize" in typography:
        typography["fontSize"] = max(6.0, float(typography["fontSize"]) * scale)
    if "spacing" in typography:
        typography["spacing"] = float(typography["spacing"]) * scale
    # Web appearance stays in authored 1080p units. tokenStyle()/vh owns
    # the single conversion at the actual stage height.
    strokes = scaled.get("strokes")
    if isinstance(strokes, list):
        for stroke in strokes:
            if isinstance(stroke, Mapping) and "width" in stroke:
                stroke["width"] = max(0.0, float(stroke["width"]) * scale)
    glow = scaled.get("glow") if isinstance(scaled.get("glow"), Mapping) else {}
    if "blur" in glow:
        glow["blur"] = max(0.0, float(glow["blur"]) * scale)
    shadow = scaled.get("shadow") if isinstance(scaled.get("shadow"), Mapping) else {}
    for field in ("offsetX", "offsetY", "blur", "spread"):
        if field in shadow:
            shadow[field] = float(shadow[field]) * scale
    for field in ('lineHeightPx', 'maxWidthPx'):
        if field in scaled.get('layout', {}):
            scaled['layout'][field] *= scale
    panel = scaled.get('background', {})
    for field in ('paddingX', 'paddingY', 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'radius'):
        if field in panel:
            panel[field] *= scale
    for section, fields in (('border', ('width',)), ('shadow', ('offsetX', 'offsetY', 'blur')),
                            ('transform', ('offsetX', 'offsetY'))):
        for field in fields:
            if field in panel.get(section, {}):
                panel[section][field] *= scale
    return scaled


def normalized_visual_snapshot(snapshot: VisualCueSnapshot) -> dict[str, object]:
    normalized = _normalized_recipe(snapshot.style_recipe)
    normalized['wordAnimation'] = deepcopy(getattr(snapshot, 'word_animation', None) or {})
    normalized['wordAnimation']['marks'] = deepcopy(getattr(snapshot, 'text_marks', None) or [])
    normalized["typography"] = {
        "fontFamily": snapshot.font_family,
        "fontSize": snapshot.font_size,
        "bold": snapshot.font_weight >= 700,
        "fontWeight": snapshot.font_weight,
        "italic": snapshot.italic,
        "spacing": snapshot.letter_spacing,
    }
    snapshot_fill = FillSpec.from_value(snapshot.fill)
    normalized["fill"] = (
        {"type": "solid", "color": _css_color(snapshot_fill.color, "#FFFFFF")}
        if snapshot_fill.kind == "solid"
        else {
            "type": "gradient",
            "kind": "radial" if snapshot_fill.kind == "radial-gradient" else "linear",
            "radius": snapshot_fill.radius,
            "angle": snapshot_fill.angle,
            "stops": [
                {
                    "color": _css_color(stop.get("color"), "#FFFFFF"),
                    "pos": float(stop.get("position", 0)),
                }
                for stop in snapshot_fill.stops
            ],
        }
    )
    normalized["layout"] = {
        "alignment": snapshot.alignment,
        "positionX": snapshot.position_x,
        "positionY": snapshot.position_y,
        "playResX": snapshot.playres_x,
        "playResY": snapshot.playres_y,
        "anchorX": snapshot.anchor_x,
        "anchorY": snapshot.anchor_y,
        "scaleX": snapshot.scale_x,
        "scaleY": snapshot.scale_y,
        "rotation": snapshot.rotation,
    }
    # The measured display lines belong to the canonical snapshot. Replacing
    # this object used to discard the width/line height and tell the browser
    # to independently lay out the same cue a second time.
    layout = snapshot.style_recipe.get('layout', {})
    for field in ('singleLine', 'fitLocked', 'lineCount', 'lineHeightPx',
                  'maxWidthPx'):
        if field in layout:
            normalized['layout'][field] = deepcopy(layout[field])
    caption = getattr(snapshot, 'resolved_caption', None)
    if caption is not None:
        normalized['layout']['captionLayout'] = caption.layout
    if snapshot.style_recipe.get('webTheme'):
        normalized['layout']['webPlacement'] = deepcopy(snapshot.style_recipe.get('layout', {}).get('webPlacement', {}))
    normalized["motion"] = normalize_motion_contract(snapshot.motion_recipe)
    # Canonical stroke_width is the outward outline radius in reference-video
    # pixels at the project PlayRes. Both renderer routes must consume the
    # current snapshot, never a stale AI graph copy. CSS converts the radius to
    # its full centered stroke width at the renderer boundary.
    normalized["strokes"] = [deepcopy(dict(item)) for item in snapshot.strokes]
    normalized["shadow"] = normalize_shadow(snapshot.shadow)
    normalized["glow"] = normalize_glow(snapshot.glow)
    graph = normalized.get("visualGraph")
    if isinstance(graph, dict):
        text_layer = graph.get("textLayer")
        if isinstance(text_layer, dict):
            font = text_layer.setdefault("font", {})
            if isinstance(font, dict):
                font.update({
                    "family": snapshot.font_family,
                    "size": snapshot.font_size,
                    "weight": snapshot.font_weight,
                    "italic": snapshot.italic,
                })
            # Do not leak the snapshot/dataclass representation (`kind`) into
            # VisualDesignGraph, whose trusted compiler contract uses `type`.
            # Keep project ARGB colors here; cssColor() converts them once at
            # the Remotion boundary.
            text_layer["fill"] = snapshot_fill.to_dict()
            text_layer["strokes"] = [
                deepcopy(dict(item)) for item in snapshot.strokes
            ]
            text_layer["shadow"] = deepcopy(snapshot.shadow)
            text_layer["glow"] = deepcopy(snapshot.glow)
            text_layer["letterSpacing"] = snapshot.letter_spacing
            text_layer["alignment"] = snapshot.alignment
        # Bind the motion graph to the cue span once, at the export boundary,
        # so the Remotion sampler and the Python LIVE sampler see the same
        # ENTRANCE -> HOLD -> EXIT structure with the exit at the cue end.
        from ..caption_design.visual_design_graph import normalize_motion_graph_to_cue

        normalized["visualGraph"] = normalize_motion_graph_to_cue(
            graph, max(1, int(snapshot.end_ms) - int(snapshot.start_ms))
        ).to_dict()
    web_theme = normalized.get("webTheme")
    if isinstance(web_theme, dict):
        # Theme-first appearance (十八轮)：主题自带的设计意图（字体栈/文字色/
        # 描边）逐键优先，工程快照只补缺——否则 AI 主题的字色永远被工程默认
        # 外观覆盖（"暗底黑字黑边"根因）。旧主题无 appearance 时行为不变。
        snapshot_strokes = [deepcopy(dict(item)) for item in snapshot.strokes]
        primary_stroke = snapshot_strokes[0] if snapshot_strokes else {}
        secondary_stroke = snapshot_strokes[1] if len(snapshot_strokes) > 1 else {}
        from ..caption_design.web_theme import effective_appearance

        web_theme["appearance"] = effective_appearance(
            web_theme,
            {
                "fontFamily": snapshot.font_family,
                "fontSize": snapshot.font_size,
                "bold": snapshot.font_weight >= 700,
                "fontWeight": snapshot.font_weight,
                "italic": snapshot.italic,
                "color": _css_color(snapshot_fill.color, "#FFFFFF"),
                "strokeColor": _css_color(primary_stroke.get("color"), "#000000"),
                "strokeWidth": min(30.0, max(0.0, float(primary_stroke.get("width", 0) or 0))),
                "stroke2Color": _css_color(secondary_stroke.get("color"), ""),
                "stroke2Width": min(30.0, max(0.0, float(secondary_stroke.get("width", 0) or 0))),
                "letterSpacing": snapshot.letter_spacing,
            },
        )
    return normalized


def compile_composition_data(
    project: SubtitleProject,
    *,
    width: int,
    height: int,
    fps: float,
    start_seconds: float,
    duration_seconds: float,
) -> dict[str, object]:
    start_ms = round(start_seconds * 1000)
    end_ms = start_ms + round(duration_seconds * 1000)
    from ..caption_style.bilingual_layout import materialize_display_project
    project = materialize_display_project(project)
    from ..caption_style.collision_layout import project_layout_schedule, shifted_snapshot, visible_subtitle_cues
    from copy import copy
    project = copy(project)
    project.cues = visible_subtitle_cues(project)
    schedule = project_layout_schedule(project)
    recipes: dict[str, object] = {}
    cues = []
    font_faces={}
    font_identities={}
    seen_font_faces=set()
    for cue in project.cues:
        if cue.end_ms <= start_ms or cue.start_ms >= end_ms:
            continue
        payload = recipe_payload_for_cue(project, cue)
        if not payload or route_recipe(payload).engine != "remotion":
            continue
        snapshot = build_visual_cue_snapshot(
            project, cue.id, width=width, height=height, fps=fps, resolved_cue=cue,
        )
        from .export_font_assets import font_asset,font_identity
        face_key=(snapshot.font_family,snapshot.font_weight,snapshot.italic,
                  getattr(snapshot.resolved_caption,'font_face_json',''))
        if face_key not in seen_font_faces:
            # One job freezes each face once, including a font larger than
            # the persistent cache budget. Never re-encode it for every cue.
            seen_font_faces.add(face_key)
            font_identities[face_key]=font_identity(snapshot)
            asset=font_asset(snapshot)
            if asset is not None:font_faces[(asset['family'],asset['weight'],asset['style'])]=asset
        visual = scale_visual_for_composition(normalized_visual_snapshot(snapshot), width)
        # recipes 键按样式共享，保持无偏移的样式定义；偏移只进 per-cue visual。
        if cue.style_id not in recipes:
            recipes[cue.style_id] = visual
        from ..caption_style.speaker_labels import template_speaker
        row = {
            "id": cue.id,
            "text": snapshot.text,
            "speaker": template_speaker(project, cue),
            "translation": getattr(snapshot, "translation", ""),
            "startMs": max(0, cue.start_ms - start_ms),
            "endMs": min(round(duration_seconds * 1000), cue.end_ms - start_ms),
            "localOffsetMs": max(0, start_ms-cue.start_ms),
            "cueDurationMs": cue.end_ms-cue.start_ms,
            "styleId": cue.style_id,
            "visual": visual,
            "snapshotHash": snapshot.stable_hash(),
            "resolvedStyleHash": snapshot.resolved_caption.style_hash if snapshot.resolved_caption else "",
            "fontIdentity": font_identities.get(face_key),
            "lineCount": snapshot.resolved_caption.line_count if snapshot.resolved_caption else len(snapshot.text.split("\n")),
            "layout": snapshot.resolved_caption.layout if snapshot.resolved_caption else {},
        }
        for index, (a, b, offset) in enumerate(schedule.get(cue.id, [(cue.start_ms, cue.end_ms, 0.)])):
            a, b = max(a, start_ms), min(b, end_ms)
            if b <= a:
                continue
            placed = shifted_snapshot(snapshot, offset)
            spans = schedule.get(cue.id, ())
            cues.append({**row, 'id': cue.id if len(spans) == 1 else f'{cue.id}@layout{index}', 'sourceId': cue.id,
                'layoutOffsetY': offset, 'startMs': a-start_ms, 'endMs': b-start_ms,
                'localOffsetMs': a-cue.start_ms,
                'visual': scale_visual_for_composition(normalized_visual_snapshot(placed), width),
                'snapshotHash': placed.stable_hash()})
    if not cues:
        used = [cue.style_id for cue in project.cues]
        available = list(project.style_recipes)
        raise ValueError(
            "高级渲染路由没有找到使用 Advanced Style 的字幕"
            f"（cue.style_id={used[:16]}, recipes={available[:16]}）"
        )
    return {
        "schemaVersion": 1,
        "width": int(width), "height": int(height), "fps": float(fps),
        "durationInFrames": max(1, round(duration_seconds * fps)),
        "cues": cues, "recipes": recipes,
        "fontFaces": list(font_faces.values()),
        "debug": {
            "projectColorEncoding": "#AARRGGBB",
            "rendererColorEncoding": "#RRGGBBAA",
        },
    }


def _advanced_overlay_window(project: SubtitleProject, start: float, duration: float) -> tuple[float, float]:
    """Render Remotion only across Advanced cues, not the whole export range."""
    _native, advanced = split_renderer_cues(project)
    if not advanced:
        return start, duration
    first = min(cue.start_ms for cue in advanced) / 1000.0
    last = max(cue.end_ms for cue in advanced) / 1000.0
    window_start = max(start, first - 0.12)
    window_end = min(start + duration, last + 0.12)
    if window_end - window_start < 0.2:
        return start, duration
    if (window_end - window_start) >= duration * 0.92:
        return start, duration
    return window_start, max(0.2, window_end - window_start)


def _overlay_cache_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    path = root / "2ByteASR" / "SubtitleStudio" / "advanced-overlay-cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _overlay_cache_path(props: Mapping[str, object]) -> Path:
    from .caption_asset_identity import asset_key
    digest = asset_key(props)
    return _overlay_cache_dir() / f"{digest}.mov"


def _renderer_cache_fingerprint() -> str:
    scoped=current_identity_cache()
    if scoped is not None and 'fingerprint' in scoped:return scoped['fingerprint']
    result=_compute_renderer_cache_fingerprint()
    if scoped is not None:scoped['fingerprint']=result
    return result


def _compute_renderer_cache_fingerprint() -> str:
    root = Path(__file__).resolve().parents[2]/'renderer'
    digest = hashlib.sha256()
    # Browser/driver changes invalidate pixels even when authored props match.
    digest.update(b'headless-shell-export-v3-local-assets')
    for name in ('render-overlays.mjs','render-caption-stills.mjs','export-browser.mjs','resource-boundary.mjs',
                 'export-bundle.mjs','export_bootstrap.cjs','navigation_response.cjs','process_policy.cjs','package-lock.json'):
        runner=root/name
        if runner.is_file():
            from .caption_asset_identity import file_digest
            digest.update(file_digest(runner).encode())
    for browser in sorted({_export_browser(root, web=True),_export_browser(root,web=False)}):
        if browser.is_file():
            from .caption_asset_identity import file_digest
            digest.update(file_digest(browser).encode())
    for path in sorted(root.joinpath('src').rglob('*')):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode())
            digest.update(file_digest(path).encode())
    for package in ('@remotion/bundler','@remotion/renderer','remotion','react','react-dom','gsap'):
        for path in sorted((root/'node_modules'/package).rglob('*')):
            if path.is_file() and path.suffix in {'.js','.mjs','.cjs','.json'}:
                digest.update(path.relative_to(root/'node_modules').as_posix().encode())
                digest.update(file_digest(path).encode())
    for path in (root/'node_modules/.package-lock.json',root.parent/'tools/node/node.exe'):
        if path.is_file():digest.update(file_digest(path).encode())
    return digest.hexdigest()


def _export_browser(root: Path, *, web: bool) -> Path:
    from .platform_browser import bundled_browser, system_browser
    bundled = bundled_browser(root)
    system = system_browser()
    # All Remotion compositions need the tested headless runtime. Modern
    # system Chrome can refuse CDP on its default profile even for non-web
    # animations; selecting it first made ordinary fade exports time out.
    for browser in (bundled, system):
        if browser.is_file():return browser
    raise RuntimeError('本地渲染浏览器缺失；请修复安装中的 Chromium 后重试（不会自动下载）。')


def _composition_browser(root: Path, props: Mapping[str, object]) -> Path:
    # Numeric glyph motion uses explicit resolved font faces. Prefer the
    # installed render runtime; system Chrome can reject cold CDP launches.
    letter_motion = any(cue.get('visual', {}).get('wordAnimation', {}).get('units')
                        for cue in props.get('cues', []))
    return _export_browser(root, web=_web_theme_composition(props) or letter_motion)


def _trim_overlay_cache() -> None:
    """Derived compressed overlays have a 2 GiB oldest-first disk budget."""
    files = sorted([*_overlay_cache_dir().glob('*.mov'), *_overlay_cache_dir().glob('*.still.png')], key=lambda p:p.stat().st_mtime, reverse=True)
    used = 0
    for path in files:
        try:
            used += path.stat().st_size
            if used > 2*1024**3:
                path.unlink()
                path.with_suffix('.sha256').unlink(missing_ok=True)
                path.with_suffix('.roi.json').unlink(missing_ok=True)
                path.with_suffix('.geometry.json').unlink(missing_ok=True)
        except OSError:
            pass


def _restore_overlay_cache(props: Mapping[str, object], overlay: Path) -> bool:
    cached = _overlay_cache_path(props)
    return _copy_verified_overlay(cached,overlay)


def _overlay_digest(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def _copy_verified_overlay(cached: Path, destination: Path) -> bool:
    try:
        expected=cached.with_suffix('.sha256').read_text('ascii').strip()
        if cached.stat().st_size<=0 or _overlay_digest(cached)!=expected:return False
        shutil.copy2(cached,destination)
        return True
    except (OSError,UnicodeError):return False


def _cache_overlay(source: Path, cached: Path) -> None:
    import uuid
    staged=cached.with_suffix('.'+uuid.uuid4().hex+'.tmp')
    try:
        shutil.copy2(source,staged)
        checksum=_overlay_digest(staged)
        os.replace(staged,cached)
        cached.with_suffix('.sha256').write_text(checksum,encoding='ascii')
    finally:staged.unlink(missing_ok=True)


def _store_overlay_cache(props: Mapping[str, object], overlay: Path) -> None:
    if not overlay.is_file() or overlay.stat().st_size <= 0:
        return
    try:
        _cache_overlay(overlay, _overlay_cache_path(props))
        _trim_overlay_cache()
    except OSError:
        pass


def _segment_cache_path(props: Mapping[str, object], frame_start: int, frame_end: int) -> Path:
    from .caption_asset_identity import asset_key
    return _overlay_cache_dir() / f"{asset_key(props,int(frame_start),int(frame_end))}-seg.mov"


def _segment_cache_store(props: Mapping[str, object], frame_start: int, frame_end: int, segment: Path) -> None:
    if not segment.is_file() or segment.stat().st_size <= 0:
        return
    try:
        _cache_overlay(segment, _segment_cache_path(props, frame_start, frame_end))
        _trim_overlay_cache()
    except OSError:
        pass


def _overlay_active_windows(
    props: Mapping[str, object], total_frames: int,
) -> list[tuple[int, int]]:
    """Merged cue-active frame windows (inclusive) of the overlay composition.

    Rendering only these windows skips the blank stretches between subtitles
    (a 138s timeline with 55 cues still has long gaps) and allows parallel
    segment processes.
    """
    spans: list[tuple[int, int]] = []
    fps = float(props.get("fps") or 30.0)
    for cue in props.get("cues") or []:
        if not isinstance(cue, Mapping):
            continue
        try:
            start_ms, end_ms = int(cue.get("startMs", 0)), int(cue.get("endMs", 0))
        except (TypeError, ValueError):
            continue
        a = max(0, int(start_ms * fps / 1000.0) - 8)
        b = min(total_frames - 1, int(end_ms * fps / 1000.0 + 0.999) + 8)
        if b >= a:
            spans.append((a, b))
    if not spans:
        return []
    spans.sort()
    merged: list[list[int]] = []
    merge_gap = int(1.5 * fps)
    for a, b in spans:
        if merged and a - merged[-1][1] <= merge_gap:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def _web_theme_composition(props: Mapping[str, object]) -> bool:
    return any(isinstance(recipe, Mapping) and recipe.get('webTheme')
               for recipe in (props.get('recipes') or {}).values()) or any(
        isinstance(cue, Mapping) and isinstance(cue.get('visual'), Mapping)
        and cue['visual'].get('webTheme') for cue in (props.get('cues') or []))


class AdvancedRendererBackend:
    def __init__(self, renderer_root: str | os.PathLike[str] | None = None):
        self.root = Path(renderer_root or Path(__file__).resolve().parents[2] / "renderer").resolve()

    def status(self) -> AdvancedRendererStatus:
        cli = self.root / "node_modules" / ".bin" / ("remotion.cmd" if os.name == "nt" else "remotion")
        if not self.root.joinpath("package.json").is_file():
            return AdvancedRendererStatus(False, "renderer/package.json 不存在")
        if not cli.is_file():
            return AdvancedRendererStatus(False, "Remotion 依赖尚未安装")
        try:renderer_node_command(self.root)
        except RuntimeError as exc:return AdvancedRendererStatus(False,str(exc))
        try:_export_browser(self.root, web=True)
        except RuntimeError as exc:return AdvancedRendererStatus(False,str(exc))
        return AdvancedRendererStatus(True)

    def require_available(self) -> None:
        status = self.status()
        if not status.available:
            raise AdvancedRendererUnavailable(
                f"高级字幕渲染环境尚未安装：{status.reason}\n请使用“安装渲染环境”后重试。"
            )

    def _render_overlay_segments(
        self, *, props, props_path: Path, temp: Path, windows, cli: Path,
        chrome: Path, fps: float, progress, cancelled, trace, timings: dict,
        stills_manifest=None, still_line=None,
    ) -> list[tuple[int, int, Path]]:
        """One job-owned browser, at most two render pages, bounded batches.

        Static PNGs and animated ProRes windows share the same bundle/browser.
        Each window retains the existing frame clock and verified cache key.
        The process is always closed at the end of the export batch.
        """
        segment_specs = []
        for index, (a, b) in enumerate(windows):
            target = temp / f'overlay-seg{index}-{a}-{b}.mov'
            if _copy_verified_overlay(_segment_cache_path(props, a, b), target) and trace:
                trace('advanced_overlay_segment_cache', {'start': a, 'end': b})
            segment_specs.append((a, b, target))
        missing = [(a, b, target) for a, b, target in segment_specs
                   if not target.is_file() or target.stat().st_size <= 0]
        timings.update(dynamic_assets=len(segment_specs),dynamic_assets_rendered=len(missing),
                       dynamic_asset_cache_hits=len(segment_specs)-len(missing))
        if missing or stills_manifest:
            pages = 2
            manifest = temp / 'html-segments.json'
            data = dict(props=str(props_path), browser=str(chrome),
                referenceBrowser=str(_export_browser(self.root, web=False)), pages=pages,
                segments=[dict(start=a, end=b, output=str(target)) for a, b, target in missing])
            if stills_manifest: data['stillsManifest'] = str(stills_manifest)
            manifest.write_text(json.dumps(data), encoding='utf8')
            started = time.perf_counter()
            if trace:
                trace('advanced_overlay_parallelism', dict(processes=1, pages_per_process=pages,
                    total_pages=pages, persistent_browser=True, static_batch=bool(stills_manifest)))
            def line(value):
                try: row = json.loads(value)
                except ValueError: return
                if not isinstance(row, dict): return
                kind = row.get('type')
                if kind not in {'progress','still'}:timings.setdefault('browser_stages',[]).append(row)
                if kind == 'still' and still_line: still_line(value)
                elif kind not in {'progress', 'still'}:
                    if trace: trace('browser_renderer_stage', row)
                if progress and kind == 'progress' and row.get('total'):
                    progress(export_progress(STAGE_ADVANCED_RENDER,
                        percent=25+74*row['done']/row['total'],
                        message=f"渲染高级字幕帧 {row['done']}/{row['total']}", indeterminate=False))
            code, logs = _run_streaming_process(
                renderer_node_command(self.root, self.root/'render-overlays.mjs', manifest),
                cwd=self.root, on_line=line, cancelled=cancelled, stall_timeout=300.)
            if code:
                from ..exports.export_failure import renderer_failure
                raise renderer_failure(code, logs)
            for a, b, target in missing:
                if not target.is_file() or target.stat().st_size <= 0:
                    raise RuntimeError(f'高级字幕分段缺失：{a}-{b}')
                _segment_cache_store(props, a, b, target)
            timings.update(remotion=time.perf_counter()-started, overlay_segments=len(missing),
                           overlay_cache='segments', browser_processes=1, browser_pages=pages)
        else:
            timings.update(remotion=0., overlay_cache='segments-hit', browser_processes=0)
        return sorted(segment_specs, key=lambda item: item[0])

    @record_completion
    @renderer_identity_scope
    def render(
        self,
        project: SubtitleProject,
        ffmpeg_path: str | os.PathLike[str],
        job: RenderJob,
        *,
        progress: Callable[[dict[str, str]], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        trace: Callable[[str, object], None] | None = None,
    ) -> Path:
        from ..exports.static_caption_export import static_graph_project, render_static_graph
        from ..exports.export_filtergraph import simple_video_clips
        from ..caption_style.bilingual_layout import materialize_display_project
        from ..exports.caption_integrity import require_confirmed_empty_sources
        require_confirmed_empty_sources(project,start_ms=round((job.start_seconds or 0)*1000),
            end_ms=round(((job.start_seconds or 0)+job.duration_seconds)*1000) if job.duration_seconds is not None else None)
        from dataclasses import replace
        from copy import copy
        from ..exports.export_run_log import note_export
        # Route only visible cues that can contribute to this export range.
        start = float(job.start_seconds or 0)
        duration = float(job.duration_seconds or project.media.duration_ms/1000-start)
        visible = copy(project)
        hidden = project.hidden_speaker_ids()
        visible.cues = [c for c in project.cues if c.speaker_id not in hidden
                        and c.end_ms > start*1000 and c.start_ms < (start+duration)*1000]
        project = materialize_display_project(visible)
        if not project_requires_advanced(project):
            from ..exports.studio_render import run_render_job
            return run_render_job(ffmpeg_path, job, progress=progress, cancelled=cancelled, trace=trace)
        from ..exports.export_acceleration import advanced_selection
        advanced_selection(job)
        from ..exports.parallel_video_export import requested_segments
        if requested_segments(job) > 1:
            note_export('parallel_selection', dict(requested_segments=2, segments=1,
                reason='advanced captions use their dedicated compositor; native video partitioning is not enabled'))
            if progress: progress({'notice':'高级字幕使用专用合成路线，本次不启用双路视频加速。'})
        if job.video_graph:
            from ..exports.timeline_media import resolve_video_graph, export_range_graph
            graph = export_range_graph(job.video_graph, start, duration)
            job = replace(job, video_graph=resolve_video_graph(graph, ffmpeg_path, cancelled=cancelled, seekable=True))
        if job.video_graph and simple_video_clips(job.video_graph) is not None:
            source_fps = job.settings.fps or job.video_graph.get('fps')
            if not source_fps:
                from fractions import Fraction
                from ..exports.studio_render import _run_probe
                result = _run_probe([str(Path(ffmpeg_path).with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')),
                    '-v','error','-select_streams','v:0','-show_entries','stream=avg_frame_rate','-of','json',job.media_path])
                source_fps = float(Fraction(json.loads(result.stdout)['streams'][0]['avg_frame_rate']))
            job = replace(job, direct_video_graph=job.video_graph, video_graph=None, edit_segments=(),
                          duration_seconds=duration, settings=replace(job.settings, fps=float(source_fps)))
            note_export('export_route', dict(route='advanced_direct_filtergraph',
                reason='supported video clock/geometry, subtitle renderer independent',
                timestamp_index='not_required', intermediate_video=False))
        if not job.video_graph and not job.edit_segments and static_graph_project(project):
            return render_static_graph(project, ffmpeg_path, job, progress=progress, cancelled=cancelled, trace=trace)
        self.require_available()
        if job.video_graph:
            from ..exports.video_export import prepared_video_job
            with prepared_video_job(ffmpeg_path, job, cancelled=cancelled, progress=progress) as prepared:
                return self.render(project, ffmpeg_path, prepared, progress=progress, cancelled=cancelled, trace=trace)
        if cancelled and cancelled():
            raise InterruptedError('render cancelled')
        if progress and not job.composition_resolved:
            progress(export_progress(STAGE_PREPARE_PROJECT, message="正在解析高级字幕工程…"))
        started = time.perf_counter()
        timings: dict[str, float] = {}
        start = float(job.start_seconds or 0.0)
        duration = float(job.duration_seconds or project.media.duration_ms / 1000.0-start)
        from ..exports.mixed_caption_export import split_mixed_captions, prepare_mixed_stills
        mixed = split_mixed_captions(project) if not job.edit_segments else None
        still_project, moving_project = mixed if mixed else (None, project)
        overlay_start, overlay_duration = _advanced_overlay_window(moving_project, start, duration)
        width = int(job.settings.width or project.media.width or 1920)
        height = int(job.settings.height or project.media.height or 1080)
        fps = float(job.settings.fps or getattr(project.media, "fps", 0.0) or 30.0)
        if mixed:
            # Reducing a mixed composition's window must not change which
            # authored animation frame reaches an output frame (e.g. its fade).
            from fractions import Fraction
            import math
            rate = Fraction(str(fps)).limit_denominator(100100)
            first = math.floor(Fraction(str(overlay_start-start))*rate)
            last = math.ceil(Fraction(str(overlay_start+overlay_duration-start))*rate)
            overlay_start = start+float(Fraction(first)/rate)
            overlay_duration = min(start+duration, start+float(Fraction(last)/rate))-overlay_start
        if progress:
            progress(export_progress(STAGE_PREPARE_SUBTITLES, message="正在准备 Advanced recipe 与 overlay 缓存…"))
        props = compile_composition_data(
            moving_project, width=width, height=height, fps=fps,
            start_seconds=overlay_start, duration_seconds=overlay_duration,
        )
        output = Path(job.output_path).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        if trace:
            trace("advanced_window", {"start": overlay_start, "duration": overlay_duration, "job_start": start, "job_duration": duration})
        with tempfile.TemporaryDirectory(prefix="2byteasr-advanced-", dir=str(output.parent)) as temp_name:
            temp = Path(temp_name)
            props_path = temp / "recipe.json"
            props_path.write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")
            batch_segments = []
            def render_browser_batch(manifest, on_line):
                from ..exports.export_performance import export_phase
                total = int(props.get('durationInFrames') or max(1, round(overlay_duration*fps)))
                from .caption_asset_identity import asset_windows
                windows = asset_windows(props, total)
                with export_phase('mixed_browser_batch', overlaps='static stills, moving frames and encoding share one browser'):
                    batch_segments.extend(self._render_overlay_segments(
                        props=props, props_path=props_path, temp=temp, windows=windows or [(0,total-1)],
                        cli=self.root/'node_modules/.bin/remotion', chrome=_composition_browser(self.root,props),
                        fps=fps, progress=progress, cancelled=cancelled, trace=trace, timings=timings,
                        stills_manifest=manifest, still_line=on_line))
            sparse = prepare_mixed_stills(still_project, self.root, temp, width=width, height=height,
                fps=fps, start=start, duration=duration, cancelled=cancelled, progress=progress, trace=trace,
                render_stills=render_browser_batch) if still_project else None
            overlay = temp / "subtitle-overlay.mov"
            native_ass = temp / "native-subtitles.ass"
            props_path.write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")
            from .web_caption_preflight import preflight_web_captions
            if _web_theme_composition(props) and progress:
                progress(export_progress(STAGE_ADVANCED_RENDER, message="预检 HTML 首句与最长字幕的实际像素…"))
            preflight_web_captions(props, self.root, temp, cancelled=cancelled, trace=trace)
            cache_hit = _restore_overlay_cache(props, overlay)
            if trace:
                trace("advanced_overlay_cache", {"hit": cache_hit})
            cli = self.root / "node_modules" / ".bin" / ("remotion.cmd" if os.name == "nt" else "remotion")
            chrome = _composition_browser(self.root, props)
            expected_frames = max(1, round(overlay_duration * fps))
            # ---- 十七轮提速：只渲染字幕活动窗口、多进程并行 ----
            # 旧版把整个 overlay 窗口逐帧渲染（含字幕间的长空白段），
            # 且 Remotion 自己的 "time remaining" 会长时间停在 2s。
            total_frames = int(props.get("durationInFrames") or expected_frames)
            from .caption_asset_identity import asset_windows
            windows = asset_windows(props, total_frames)
            segment_overlays: list[tuple[int, int, Path]] = []
            if batch_segments:
                segment_overlays = batch_segments
            elif cache_hit:
                timings["remotion"] = 0.0
                timings["overlay_cache"] = "hit"
                if progress:
                    progress(export_progress(
                        STAGE_ADVANCED_RENDER,
                        message="已命中高级字幕 overlay 缓存",
                        percent=100,
                        indeterminate=False,
                        speed="cache",
                    ))
            else:
                # One owned batch renders only missing cue-overlap groups;
                # all cached windows retain the original composition clock.
                segment_overlays = self._render_overlay_segments(
                    props=props, props_path=props_path, temp=temp, windows=windows or [(0, total_frames-1)],
                    cli=cli, chrome=chrome, fps=fps,
                    progress=progress, cancelled=cancelled, trace=trace,
                    timings=timings,
                )
            if cancelled and cancelled():
                raise InterruptedError("render cancelled")
            if mixed and not job.composition_resolved and job.settings.pixel_format == 'yuv420p':
                from ..exports.caption_composite_region import moving_alpha_bounds
                from ..exports.export_performance import export_phase
                regions = {}
                with export_phase('moving_alpha_bounds', coverage='every alpha sample in each short mixed window'):
                    for a, b, path in segment_overlays:
                        bounds = moving_alpha_bounds(path, width=width, height=height, frames=b-a+1,
                            cached=_segment_cache_path(props,a,b), cancelled=cancelled)
                        if bounds: regions[str(path)] = bounds
                job.export_context['overlay_alpha_bounds'] = regions
                note_export('caption_compositing', dict(mode='local straight-RGBA before final YUV420 conversion',
                    static_bounds=sparse['bounds'] if sparse else None, moving_bounds=regions,
                    canvas=[width,height], global_and_large_layers='full canvas'))
            start_ms, end_ms = round(start * 1000), round((start + duration) * 1000)
            native_project = _native_segment_project(project, start_ms, end_ms)
            if native_project.cues:
                native_ass.write_text(compile_ass(native_project), encoding="utf-8-sig")
            partial = Path(temp_name) / f"output.partial{output.suffix}"
            composite = [str(Path(ffmpeg_path).resolve()), "-hide_banner", "-loglevel", "level+info", "-xerror", "-y"]
            slices = [(float(a), float(b)) for a, b in (getattr(job, "edit_segments", ()) or ())]
            scale_chain = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
            if native_ass.is_file():
                scale_chain += f",ass=filename={_ffmpeg_filter_path(native_ass)}"
            delay = max(0.0, overlay_start - start)
            audio_map = "0:a?"
            if slices:
                from ..exports.studio_render import build_concat_filter_complex, media_has_audio
                has_audio = job.settings.audio_codec != "none" and media_has_audio(ffmpeg_path, job.media_path)
                graph, _video_label, audio_label = build_concat_filter_complex(
                    slices, scale_chain, has_audio=has_audio, scale="", ass_origin=start,
                )
                graph = graph.rsplit("[vout]", 1)[0] + "[base]"
                filter_graph = graph
                if audio_label:
                    audio_map = audio_label
            else:
                if start > 0 and not job.composition_resolved:
                    composite.extend(["-ss", f"{start:.3f}"])
                filter_graph = f"[0:v]{scale_chain}[base]"
            # ---- overlay chain: 单段（整窗 mov）走旧路径；分段则逐段 setpts
            # 偏移 + enable 时间窗叠加（段外透出底图，段间空隙自然留白）。
            overlay_inputs: list[tuple[float, float, Path]] = []
            if segment_overlays:
                for seg_a, seg_b, seg_path in segment_overlays:
                    seg_start_sec = delay + seg_a / fps
                    seg_end_sec = delay + (seg_b + 1) / fps
                    overlay_inputs.append((seg_start_sec, seg_end_sec, seg_path))
            elif overlay.is_file() and overlay.stat().st_size > 0:
                overlay_inputs.append((delay, duration + 1.0, overlay))
            from ..exports.export_filtergraph import overlay_pts_shift
            prev_label = "base"
            parts = [filter_graph]
            static_inputs = []
            if sparse:
                from ..exports.static_caption_timeline import caption_input, caption_filter
                static_inputs = caption_input(sparse)
                pre, static_label = caption_filter(sparse, '[1:v]', fps)
                x, y, *_ = sparse['bounds']
                if pre:parts.append(pre.rstrip(';'))
                from ..exports.caption_composite_region import append_region_overlay
                prev_label=append_region_overlay(parts,'[base]',static_label,bounds=sparse['bounds'],
                    width=width,height=height,pixel_format=job.settings.pixel_format if not job.composition_resolved else '',
                    tag='mixedstatic')[1:-1]
            for input_index, (window_start, window_end, overlay_path) in enumerate(overlay_inputs):
                input_id = input_index + 1 + bool(sparse)
                stream_label = f"ov{input_index}"
                next_label = "v" if input_index == len(overlay_inputs) - 1 else f"m{input_index}"
                parts.append(
                    f"[{input_id}:v]setpts={overlay_pts_shift(max(0.0,window_start),fps)}[{stream_label}]"
                )
                enable = (
                    f"enable='between(t,{max(0.0, window_start):.5f},{window_end:.5f})'"
                    if segment_overlays else ""
                )
                from ..exports.caption_composite_region import append_region_overlay
                bounds=(job.export_context.get('overlay_alpha_bounds') or {}).get(str(overlay_path)) or (0,0,width,height)
                prev_label=append_region_overlay(parts,f'[{prev_label}]',f'[{stream_label}]',bounds=bounds,
                    width=width,height=height,pixel_format=job.settings.pixel_format if not job.composition_resolved else '',
                    tag=f'advancedmoving{input_index}',eof_action='pass',enable=enable,full_canvas=True)[1:-1]
            filter_graph = ";".join(parts)
            encoder = select_encoder(ffmpeg_path, job.settings)
            quality = _quality_arguments(encoder, job.settings)
            pix = job.settings.pixel_format or "yuv420p"
            if job.direct_video_graph:
                from ..exports.export_filtergraph import compile_video_filtergraph
                native_filter = f'ass=filename={_ffmpeg_filter_path(native_ass)}' if native_ass.is_file() else None
                composite.extend(compile_video_filtergraph(ffmpeg_path, job, 'null',
                    caption_filter=native_filter, caption_overlays=[sparse] if sparse else (), video_overlays=overlay_inputs))
            else:
                from ..exports.studio_render import video_input_acceleration
                composite.extend([*video_input_acceleration(job), "-i", str(Path(job.media_path).resolve()), *static_inputs])
                for _window_start, _window_end, overlay_path in overlay_inputs:
                    composite.extend(["-i", str(overlay_path)])
                composite.extend(["-t", f"{duration:.9f}", "-filter_complex", filter_graph, "-map", f"[{prev_label}]", "-map", audio_map])
            composite.extend(["-c:v", encoder, *quality, "-pix_fmt", pix])
            preset = encoder_preset(encoder, job.settings.preset)
            if preset:
                composite.extend(["-preset", preset])
            if job.settings.fps>0:composite.extend(['-r',f'{job.settings.fps:.12g}'])
            if job.composition_resolved:
                from ..exports.video_export import composed_video_frame_count
                frames = composed_video_frame_count(job)
                if frames is not None:composite.extend(['-frames:v',str(frames)])
            if job.settings.profile:composite.extend(['-profile:v',job.settings.profile])
            if job.settings.level:composite.extend(['-level:v',job.settings.level])
            if job.settings.gop>0:composite.extend(['-g',str(job.settings.gop)])
            if job.settings.b_frames>=0:composite.extend(['-bf',str(job.settings.b_frames)])
            if job.settings.audio_codec == "none": composite.append("-an")
            elif job.settings.audio_codec == "copy" and not slices and not job.direct_video_graph: composite.extend(["-c:a", "copy"])
            else: composite.extend(["-c:a", "libopus" if job.settings.audio_codec == "opus" else "aac", "-b:a", f"{job.settings.audio_bitrate_kbps}k"])
            if job.settings.container in {"mp4", "mov"}:composite.extend(["-movflags", "+faststart"])
            composite.extend(["-progress", "pipe:1", "-nostats", str(partial)])
            if trace: trace("advanced_composite_command", composite)
            if progress:
                progress(export_progress(
                    STAGE_ENCODE,
                    message="正在合成视频并编码…",
                    duration_seconds=duration,
                ))
            encode_started = time.perf_counter()
            current = {}
            def composite_line(line: str) -> None:
                key, separator, value = line.partition('=')
                if separator:current[key] = value
                if key == 'progress':
                    if progress:
                        progress(export_progress(STAGE_ENCODE, message='正在编码视频…',
                            out_time_us=current.get('out_time_us') or current.get('out_time_ms'),
                            frame=current.get('frame', ''), fps=current.get('fps', ''), speed=current.get('speed', ''),
                            duration_seconds=duration, indeterminate=False))
                    current.clear()
            from ..exports.export_preview import run_streaming_with_preview
            composite_code, composite_log = run_streaming_with_preview(
                composite, job, _run_streaming_process, on_line=composite_line, cancelled=cancelled,
                warning=(lambda text:progress({'notice':text})) if progress else None,
            )
            timings["ffmpeg_composite"] = time.perf_counter() - encode_started
            if composite_code != 0 or not partial.is_file() or partial.stat().st_size <= 0:
                from ..exports.export_failure import ffmpeg_failure
                raise ffmpeg_failure(composite_code, composite_log,
                    encoder=composite[composite.index('-c:v')+1],fps=fps)
            mux_started = time.perf_counter()
            if progress:
                progress(export_progress("validate", message="检查成片…"))
            from ..exports.export_validation import validate_output, output_validation_options
            metadata = validate_output(ffmpeg_path, partial, duration=duration, fps=fps, cancelled=cancelled,preview_path=job.completion_preview_path, **output_validation_options(job))
            metadata['caption_assets']=dict(dynamic_total=timings.get('dynamic_assets',0),
                dynamic_rendered=timings.get('dynamic_assets_rendered',0),
                dynamic_hits=timings.get('dynamic_asset_cache_hits',0),
                static=(sparse or {}).get('asset_cache',{}))
            metadata['renderer_preparation']=dict(browser_stages=timings.get('browser_stages',[]),
                remotion_seconds=timings.get('remotion',0),encode_and_mux_seconds=timings.get('ffmpeg_composite',0))
            if trace:
                trace("validated_output", metadata)
            publish_output(partial, output, job, metadata, cancelled=cancelled)
            timings["mux"] = time.perf_counter() - mux_started
        timings["wall"] = time.perf_counter() - started
        if progress:
            notify_after_publication(job, progress, export_progress(
                STAGE_MUX,
                message="封装完成",
                percent=100,
                indeterminate=False,
                out_time_us=str(round(duration * 1_000_000)),
                duration_seconds=duration,
                frame=str(round(duration * fps)),
                speed="1.0x",
            ))
        note_export("advanced_timings", timings)
        if trace:
            notify_after_publication(job, trace, "advanced_output_verified", {"exists": output.is_file(), "size": output.stat().st_size})
            notify_after_publication(job, trace, "advanced_timings", timings)
        return output
