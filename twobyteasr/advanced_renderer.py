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
from pathlib import Path
from typing import Callable, Mapping

from .ass_compiler import compile_ass
from .export_validation import record_completion, publish_output, notify_after_publication
from .studio_project import SubtitleProject
from .studio_render import (
    RenderJob, STAGE_ADVANCED_RENDER, STAGE_ENCODE, STAGE_MUX,
    STAGE_PREPARE_PROJECT, STAGE_PREPARE_SUBTITLES, _quality_arguments,
    export_progress, parse_ffmpeg_out_time_seconds, select_encoder,
)
from .style_recipe import (
    FillSpec,
    StyleRecipe,
    normalize_glow_contract,
    normalize_motion_contract,
    normalize_shadow_contract,
    recipe_payload_for_style,
    route_recipe,
)
from .visual_snapshot import VisualCueSnapshot, build_visual_cue_snapshot
from .processes import popen_hidden_subprocess, renderer_node_command, renderer_child_environment


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
    }


def recipe_payload_for_cue(project: SubtitleProject, cue) -> Mapping[str, object] | None:
    return recipe_payload_for_style(project.style_recipes, cue.style_id)


def project_requires_advanced(project: SubtitleProject, *, start_ms=None, end_ms=None) -> bool:
    for cue in project.cues:
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
    value = str(Path(path).resolve()).replace("\\", "/")
    value = value.replace(":", r"\:").replace("'", r"\'")
    return f"'{value}'"


def _native_segment_project(project: SubtitleProject, start_ms: int, end_ms: int) -> SubtitleProject:
    native, _advanced = split_renderer_cues(project)
    segment = deepcopy(project)
    segment.cues = []
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
        segment.cues.append(cue)
    return segment


def _run_streaming_process(command: list[str], *, cwd: Path | None = None,
                           on_line: Callable[[str], None] | None = None,
                           cancelled: Callable[[], bool] | None = None,
                           stall_timeout: float | None = None) -> tuple[int, str]:
    import queue

    process = popen_hidden_subprocess(
        command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        purpose="advanced preview/render child",
        own_process_tree=True,
        env=renderer_child_environment() if command and Path(command[0]).name.lower() in {'node.exe','node'} else None,
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
                    from .processes import stop_process_tree
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

    def read_lines() -> None:
        try:
            for raw in iter(process.stdout.readline, ""):
                enqueue(raw)
                if finished.is_set():
                    return
        except BaseException as exc:
            enqueue(exc)
        finally:
            enqueue(eof)

    reader = threading.Thread(target=read_lines, daemon=True, name="advanced-render-output")
    reader.start()
    watchdog.start()
    try:
        while True:
            if cleanup_error is not None:
                raise cleanup_error
            if "watchdog_error" in state:
                raise state["watchdog_error"]
            try:
                raw = lines.get(timeout=.05)
            except queue.Empty:
                continue
            if raw is eof:
                break
            if isinstance(raw, BaseException):
                raise raw
            line = raw.strip()
            state["last_line"] = time.monotonic()
            if line:
                tail.append(line)
                del tail[:-120]
                if on_line:
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
            reader.join(timeout=.2)
    if state['cancelled'] or (cancelled and cancelled()):
        raise InterruptedError("render cancelled")
    if state["stall_killed"]:
        tail.append(f"[2ByteASR] 渲染进程超过 {stall_timeout:.0f}s 无输出，已终止（疑似挂死）。")
        raise RuntimeError("\n".join(tail[-12:]))
    return code, "\n".join(tail)


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
            "type": background_type,
            "color": _css_color(background.get("fill", background.get("color", recipe.colors.get("background"))), "#00000000"),
            "gradient": {
                "colors": gradient_colors,
                "angle": float(background_gradient.get("angle", 0) or 0),
            },
            "opacity": min(1.0, max(0.0, float(background.get("opacity", 1) or 0))),
            "paddingX": min(120.0, max(0.0, float(background.get("padding_x", background.get("paddingX", 22)) or 0))),
            "paddingY": min(80.0, max(0.0, float(background.get("padding_y", background.get("paddingY", 10)) or 0))),
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
    return scaled


def normalized_visual_snapshot(snapshot: VisualCueSnapshot) -> dict[str, object]:
    normalized = _normalized_recipe(snapshot.style_recipe)
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
        from .visual_design_graph import normalize_motion_graph_to_cue

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
        from .web_theme import effective_appearance

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
    recipes: dict[str, object] = {}
    cues = []
    for cue in project.cues:
        if cue.end_ms <= start_ms or cue.start_ms >= end_ms:
            continue
        payload = recipe_payload_for_cue(project, cue)
        if not payload or route_recipe(payload).engine != "remotion":
            continue
        snapshot = build_visual_cue_snapshot(
            project, cue.id, width=width, height=height, fps=fps,
        )
        visual = normalized_visual_snapshot(snapshot)
        # recipes 键按样式共享，保持无偏移的样式定义；偏移只进 per-cue visual。
        if cue.style_id not in recipes:
            recipes[cue.style_id] = visual
        cues.append({
            "id": cue.id,
            "text": snapshot.text,
            "speaker": next((str(item.name or '') for item in project.speakers
                             if item.id == cue.speaker_id), ''),
            "translation": getattr(snapshot, "translation", ""),
            "startMs": max(0, cue.start_ms - start_ms),
            "endMs": min(round(duration_seconds * 1000), cue.end_ms - start_ms),
            "styleId": cue.style_id,
            "visual": visual,
            "snapshotHash": snapshot.stable_hash(),
            "resolvedStyleHash": snapshot.resolved_caption.style_hash if snapshot.resolved_caption else "",
            "lineCount": 1,
        })
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
    encoded = json.dumps([_renderer_cache_fingerprint(), props], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha1(encoded).hexdigest()
    return _overlay_cache_dir() / f"{digest}.mov"


@lru_cache(maxsize=1)
def _renderer_cache_fingerprint() -> str:
    root = Path(__file__).resolve().parents[1]/'renderer'
    digest = hashlib.sha256()
    # Browser/driver changes invalidate pixels even when authored props match.
    digest.update(b'headless-shell-export-v2')
    for name in ('render-overlays.mjs','export-browser.mjs','resource-boundary.mjs'):
        runner=root/name
        if runner.is_file():digest.update(runner.read_bytes())
    for browser in sorted({_export_browser(root, web=True),_export_browser(root,web=False)}):
        if browser.is_file():
            stat = browser.stat()
            digest.update(f'{browser.name}:{stat.st_size}:{stat.st_mtime_ns}'.encode())
    for path in sorted([*root.joinpath('src').rglob('*'), *root.joinpath('public/fonts').glob('*')]):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _export_browser(root: Path, *, web: bool) -> Path:
    from .platform_browser import bundled_browser, system_browser
    bundled = bundled_browser(root)
    system = system_browser()
    for browser in ((bundled, system) if web else (system, bundled)):
        if browser.is_file():return browser
    raise RuntimeError('本地渲染浏览器缺失；请修复安装中的 Chromium 后重试（不会自动下载）。')


def _trim_overlay_cache() -> None:
    """Derived compressed overlays have a 2 GiB oldest-first disk budget."""
    files = sorted(_overlay_cache_dir().glob('*.mov'), key=lambda p:p.stat().st_mtime, reverse=True)
    used = 0
    for path in files:
        try:
            used += path.stat().st_size
            if used > 2*1024**3:
                path.unlink()
                path.with_suffix('.sha256').unlink(missing_ok=True)
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
    encoded = json.dumps(
        [_renderer_cache_fingerprint(), props, int(frame_start), int(frame_end)],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return _overlay_cache_dir() / f"{hashlib.sha1(encoded).hexdigest()}-seg.mov"


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
        self.root = Path(renderer_root or Path(__file__).resolve().parents[1] / "renderer").resolve()

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
    ) -> list[tuple[int, int, Path]]:
        """Render cue-active windows as parallel remotion segments.

        Each segment renders only `--frames=a-b` into its own ProRes mov
        (segment-cached), skipping blank stretches and multiplying
        throughput across processes. Progress aggregates global frames and
        computes ETA from measured throughput — Remotion's own
        "time remaining" is unreliable (stuck at 2s for minutes).
        """
        segment_specs: list[tuple[int, int, Path]] = []
        for index, (a, b) in enumerate(windows):
            seg_path = temp / f"overlay-seg{index}-{a}-{b}.mov"
            cached = _segment_cache_path(props, a, b)
            if _copy_verified_overlay(cached, seg_path):
                if trace:
                    trace("advanced_overlay_segment_cache", {"start": a, "end": b})
            else:
                seg_path = seg_path  # rendered below
            segment_specs.append((a, b, seg_path))
        missing = [
            (a, b, path) for a, b, path in segment_specs
            if not path.is_file() or path.stat().st_size <= 0
        ]
        if missing:
            if _web_theme_composition(props):
                pages=min(4,max(2,(os.cpu_count() or 4)//2))
                manifest=temp/'html-segments.json'
                manifest.write_text(json.dumps({'props':str(props_path),'browser':str(chrome),'referenceBrowser':str(_export_browser(self.root,web=False)),'pages':pages,
                    'segments':[{'start':a,'end':b,'output':str(path)} for a,b,path in missing]}),encoding='utf8')
                started=time.perf_counter()
                if trace:trace('advanced_overlay_parallelism',{'processes':1,'pages_per_process':pages,'total_pages':pages,'persistent_browser':True})
                def line(value):
                    try:row=json.loads(value)
                    except ValueError:return
                    if not isinstance(row,dict):return
                    if trace and row.get('type')!='progress':trace('html_renderer_stage',row)
                    if progress and row.get('total'):
                        progress(export_progress(STAGE_ADVANCED_RENDER,percent=2+97*row['done']/row['total'],
                            message=f"渲染 HTML 字幕帧 {row['done']}/{row['total']}",indeterminate=False))
                code,log=_run_streaming_process(renderer_node_command(self.root,self.root/'render-overlays.mjs',manifest),
                    cwd=self.root,on_line=line,cancelled=cancelled,stall_timeout=300.)
                if code:raise RuntimeError('HTML 分段渲染失败：'+log[-2000:])
                for a,b,path in missing:
                    if not path.is_file() or path.stat().st_size<=0:raise RuntimeError(f'HTML 字幕分段缺失：{a}-{b}')
                    _segment_cache_store(props,a,b,path)
                timings.update(remotion=time.perf_counter()-started,overlay_segments=len(missing),overlay_cache='segments')
                return sorted(segment_specs,key=lambda item:item[0])
            parallel = min(4, len(missing))
            cpu_count = os.cpu_count() or 8
            per_process = max(2, min(8, cpu_count // max(1, parallel)))
            if _web_theme_composition(props):
                # Full-stage HTML/filter/SVG pages have much higher compositor
                # pressure than text. Bound total pages, including segments.
                parallel = min(2, len(missing))
                page_budget = min(4, max(2, cpu_count//2)) if chrome.name=='chrome-headless-shell.exe' else 2
                per_process = max(1, page_budget // parallel)
            if trace:
                trace('advanced_overlay_parallelism', {'processes':parallel,
                    'pages_per_process':per_process,'total_pages':parallel*per_process})
            total_missing = sum(b - a + 1 for a, b, _path in missing)
            done_all = {"frames": 0}
            per_tag_done: dict[Path, int] = {}
            state_lock = threading.Lock()
            failure: dict[str, str] = {}
            render_started = time.perf_counter()
            last_reported = {"percent": -1.0, "trace": -1.0}

            def report() -> None:
                if progress is None:
                    return
                done = done_all["frames"]
                percent = 2.0 + 97.0 * done / max(1, total_missing)
                if percent <= last_reported["percent"] + 0.4:
                    return
                last_reported["percent"] = percent
                elapsed = max(0.5, time.perf_counter() - render_started)
                remaining = max(0, total_missing - done)
                eta_seconds = int(remaining * elapsed / max(1.0, done))
                eta = (
                    f"剩约 {eta_seconds // 60} 分 {eta_seconds % 60} 秒"
                    if eta_seconds >= 90 else f"剩约 {eta_seconds} 秒"
                )
                progress(export_progress(
                    STAGE_ADVANCED_RENDER,
                    message=(
                        f"{parallel} 路并行渲染高级字幕帧 {done}/{total_missing} · {eta}"
                    ),
                    percent=percent,
                    indeterminate=False,
                    speed="Remotion×并行",
                ))
                if trace is not None and percent - last_reported["trace"] >= 5.0:
                    last_reported["trace"] = percent
                    trace("advanced_overlay_progress", {
                        "frame": done, "total": total_missing,
                        "percent": round(percent, 1), "parallel": parallel,
                    })

            def segment_worker(a: int, b: int, seg_path: Path) -> None:
                seg_command = [
                    *renderer_node_command(self.root,self.root/'node_modules/@remotion/cli/remotion-cli.js'), "render", "src/index.ts", "SubtitleOverlay", str(seg_path),
                    f"--props={props_path}", "--codec=prores", "--prores-profile=4444",
                    "--pixel-format=yuva444p10le", "--image-format=png", "--log=verbose",
                    f"--frames={a}-{b}", f"--concurrency={per_process}",
                ]
                if chrome.is_file():
                    seg_command.append(f"--browser-executable={chrome}")
                if trace:
                    trace("advanced_overlay_segment_command",
                          {"start": a, "end": b, "frames": b - a + 1,
                           "concurrency": per_process})

                def on_line(line: str) -> None:
                    clean = re.sub(r"\x1b\[[0-9;]*m", "", line)
                    match = re.search(r"Rendered\s+(\d+)\s*/\s*(\d+)", clean)
                    if not match:
                        return
                    with state_lock:
                        previous = per_tag_done.get(seg_path, 0)
                        current = int(match.group(1))
                        if current > previous:
                            per_tag_done[seg_path] = current
                            done_all["frames"] += current - previous
                        report()

                def cancelled_or_failed() -> bool:
                    return bool(failure) or bool(cancelled and cancelled())

                try:
                    code, log = _run_streaming_process(
                        seg_command, cwd=self.root, on_line=on_line,
                        cancelled=cancelled_or_failed, stall_timeout=300.0,
                    )
                    if code != 0 or not seg_path.is_file() or seg_path.stat().st_size <= 0:
                        raise RuntimeError(
                            f"segment {a}-{b} render failed: {log[-2000:]}"
                        )
                    _segment_cache_store(props, a, b, seg_path)
                except BaseException as exc:  # noqa: BLE001 - first failure wins
                    with state_lock:
                        if not failure:
                            failure[f"{a}-{b}"] = f"{type(exc).__name__}: {exc}"[:500]

            if progress:
                estimate_minutes = max(
                    1, round(total_missing / 9.0 / 60.0 / parallel * 1.4),
                )
                progress(export_progress(
                    STAGE_ADVANCED_RENDER,
                    message=(
                        f"{parallel} 路并行渲染 {len(missing)} 段高级字幕"
                        f"（约 {total_missing} 帧，估 {estimate_minutes} 分钟）——"
                        "只渲染字幕出现的区间，请勿关闭应用"
                    ),
                ))
            from contextvars import copy_context
            threads = [
                threading.Thread(
                    target=copy_context().run, args=(segment_worker, a, b, path),
                    daemon=True, name=f"remotion-seg-{a}",
                )
                for a, b, path in missing
            ]
            # bounded start: at most `parallel` concurrent render processes
            started_threads: list[threading.Thread] = []
            queue = list(threads)
            while queue or any(t.is_alive() for t in started_threads):
                if failure or (cancelled and cancelled()):
                    break
                while queue and len([t for t in started_threads if t.is_alive()]) < parallel:
                    thread = queue.pop(0)
                    thread.start()
                    started_threads.append(thread)
                time.sleep(0.2)
            for thread in started_threads:
                thread.join(timeout=5.0)
            if failure:
                raise RuntimeError(f"Remotion 并行分段渲染失败：{list(failure.values())[0]}")
            timings["remotion"] = time.perf_counter() - render_started
            timings["overlay_segments"] = len(missing)
            timings["overlay_cache"] = "segments"
            if progress:
                progress(export_progress(
                    STAGE_ADVANCED_RENDER,
                    message="高级字幕分段渲染完成，正在合成…",
                    percent=99,
                    indeterminate=False,
                    speed="Remotion",
                ))
        else:
            timings["remotion"] = 0.0
            timings["overlay_cache"] = "segments-hit"
        return sorted(segment_specs, key=lambda item: item[0])

    @record_completion
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
        from .static_caption_export import static_graph_project, render_static_graph
        from .export_filtergraph import simple_video_clips
        if job.video_graph:
            from dataclasses import replace
            from .timeline_media import resolve_video_graph
            job = replace(job, video_graph=resolve_video_graph(job.video_graph, ffmpeg_path, cancelled=cancelled))
        if static_graph_project(project) and job.video_graph and simple_video_clips(job.video_graph) is not None:
            from dataclasses import replace
            source_fps=job.settings.fps or job.video_graph.get('fps')
            if not source_fps:
                from fractions import Fraction
                from .studio_render import _run_probe
                result=_run_probe([str(Path(ffmpeg_path).with_name('ffprobe.exe' if os.name=='nt' else 'ffprobe')),
                    '-v','error','-select_streams','v:0','-show_entries','stream=avg_frame_rate','-of','json',job.media_path])
                source_fps=float(Fraction(json.loads(result.stdout)['streams'][0]['avg_frame_rate']))
            prepared=replace(job,direct_video_graph=job.video_graph,video_graph=None,edit_segments=(),
                             settings=replace(job.settings,fps=float(source_fps)))
            return render_static_graph(project,ffmpeg_path,prepared,progress=progress,cancelled=cancelled,trace=trace)
        self.require_available()
        if job.video_graph:
            from .video_export import prepared_video_job
            with prepared_video_job(ffmpeg_path, job, cancelled=cancelled, progress=progress) as prepared:
                return self.render(project, ffmpeg_path, prepared, progress=progress,
                                   cancelled=cancelled, trace=trace)
        if cancelled and cancelled():
            raise InterruptedError("render cancelled")
        from .static_caption_export import static_graph_project, render_static_graph
        if not job.edit_segments and static_graph_project(project):
            return render_static_graph(project,ffmpeg_path,job,progress=progress,cancelled=cancelled,trace=trace)
        if progress and not job.composition_resolved:
            progress(export_progress(STAGE_PREPARE_PROJECT, message="正在解析高级字幕工程…"))
        started = time.perf_counter()
        timings: dict[str, float] = {}
        start = float(job.start_seconds or 0.0)
        duration = float(job.duration_seconds or project.media.duration_ms / 1000.0)
        overlay_start, overlay_duration = _advanced_overlay_window(project, start, duration)
        width = int(job.settings.width or project.media.width or 1920)
        height = int(job.settings.height or project.media.height or 1080)
        fps = float(job.settings.fps or getattr(project.media, "fps", 0.0) or 30.0)
        if progress:
            progress(export_progress(STAGE_PREPARE_SUBTITLES, message="正在准备 Advanced recipe 与 overlay 缓存…"))
        props = compile_composition_data(
            project, width=width, height=height, fps=fps,
            start_seconds=overlay_start, duration_seconds=overlay_duration,
        )
        output = Path(job.output_path).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        if trace:
            trace("advanced_window", {"start": overlay_start, "duration": overlay_duration, "job_start": start, "job_duration": duration})
        with tempfile.TemporaryDirectory(prefix="2byteasr-advanced-", dir=str(output.parent)) as temp_name:
            temp = Path(temp_name)
            props_path = temp / "recipe.json"
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
            chrome = _export_browser(self.root, web=_web_theme_composition(props))
            command = [
                *renderer_node_command(self.root,self.root/'node_modules/@remotion/cli/remotion-cli.js'), "render", "src/index.ts", "SubtitleOverlay", str(overlay),
                f"--props={props_path}", "--codec=prores", "--prores-profile=4444",
                "--pixel-format=yuva444p10le", "--image-format=png", "--log=verbose",
            ]
            if _web_theme_composition(props):
                command.append('--concurrency='+str(min(4,max(2,(os.cpu_count() or 4)//2)) if chrome.name=='chrome-headless-shell.exe' else 2))
            if chrome.is_file():
                command.append(f"--browser-executable={chrome}")
            if trace: trace("advanced_overlay_command", command)
            expected_frames = max(1, round(overlay_duration * fps))
            last_overlay_progress = -1.0
            last_overlay_trace = -1.0
            remotion_started = time.perf_counter()

            def _eta_text(seconds_text: str) -> str:
                try:
                    seconds = int(seconds_text)
                except (TypeError, ValueError):
                    return ""
                if seconds >= 90:
                    return f"剩约 {seconds // 60} 分 {seconds % 60} 秒"
                return f"剩约 {seconds} 秒"

            def overlay_line(line: str) -> None:
                nonlocal last_overlay_progress, last_overlay_trace
                clean = re.sub(r"\x1b\[[0-9;]*m", "", line)
                # Remotion 4 的帧进度行（verbose）：`Rendered 123/4145, time remaining: 42s`
                rendered = re.search(
                    r"Rendered\s+(\d+)\s*/\s*(\d+)(?:,\s*time remaining:\s*(\d+)s?)?", clean,
                )
                if rendered:
                    done, total = int(rendered.group(1)), max(1, int(rendered.group(2)))
                    eta = _eta_text(rendered.group(3) or "")
                    value = max(0.0, min(100.0, 2.0 + 97.0 * done / total))
                    if value <= last_overlay_progress + 0.4:
                        return
                    last_overlay_progress = value
                    message = f"正在渲染高级字幕帧 {done}/{total}"
                    if eta:
                        message += f" · {eta}"
                    if progress:
                        progress(export_progress(
                            STAGE_ADVANCED_RENDER,
                            message=message,
                            percent=value,
                            indeterminate=False,
                            speed="Remotion",
                        ))
                    if trace and value - last_overlay_trace >= 5.0:
                        last_overlay_trace = value
                        trace("advanced_overlay_progress", {
                            "frame": done, "total": total, "percent": round(value, 1),
                        })
                    return
                bundling = re.search(r"Bundling\s+(\d{1,3}(?:\.\d+)?)\s*%", clean)
                if bundling:
                    value = min(2.0, float(bundling.group(1)) / 100.0 * 2.0)
                    if value <= last_overlay_progress:
                        return
                    last_overlay_progress = value
                    if progress:
                        progress(export_progress(
                            STAGE_ADVANCED_RENDER,
                            message="正在打包渲染工程…",
                            percent=value,
                            indeterminate=False,
                            speed="Remotion",
                        ))
                    return
                percent_match = re.search(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%", clean)
                if percent_match:
                    value = max(0.0, min(2.0, float(percent_match.group(1)) / 100.0 * 2.0))
                    if value <= last_overlay_progress:
                        return
                    last_overlay_progress = value
                    if progress:
                        progress(export_progress(
                            STAGE_ADVANCED_RENDER,
                            message="正在准备高级字幕渲染…",
                            percent=value,
                            indeterminate=False,
                            speed="Remotion",
                        ))
            # ---- 十七轮提速：只渲染字幕活动窗口、多进程并行 ----
            # 旧版把整个 overlay 窗口逐帧渲染（含字幕间的长空白段），
            # 且 Remotion 自己的 "time remaining" 会长时间停在 2s。
            total_frames = int(props.get("durationInFrames") or expected_frames)
            windows = _overlay_active_windows(props, total_frames)
            covered = sum(b - a + 1 for a, b in windows) if windows else 0
            use_segments = bool(windows) and (
                len(windows) >= 2
                or covered < total_frames - max(30, int(total_frames * 0.05))
            )
            segment_overlays: list[tuple[int, int, Path]] = []
            if cache_hit:
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
            elif use_segments or _web_theme_composition(props):
                # 分段并行：每段一个 remotion 进程（--frames=a-b），段级缓存，
                # 进度按全局完成帧数聚合、剩余时间按实测吞吐自算。
                segment_overlays = self._render_overlay_segments(
                    props=props, props_path=props_path, temp=temp, windows=windows if use_segments else [(0, total_frames-1)],
                    cli=cli, chrome=chrome, fps=fps,
                    progress=progress, cancelled=cancelled, trace=trace,
                    timings=timings,
                )
            else:
                if progress:
                    hint = (
                        f"首次高级字幕渲染约需 {max(2, round(expected_frames / 8 / 60))} 分钟"
                        f"（{expected_frames} 帧），进度与剩余时间会实时显示，请勿关闭应用"
                        if expected_frames >= 2400
                        else "正在准备高级字幕渲染…"
                    )
                    progress(export_progress(
                        STAGE_ADVANCED_RENDER,
                        message=hint,
                    ))
                overlay_code, overlay_log = _run_streaming_process(
                    command, cwd=self.root, on_line=overlay_line, cancelled=cancelled,
                    stall_timeout=300.0,
                )
                if overlay_code != 0 or not overlay.is_file():
                    raise RuntimeError(f"Remotion overlay render failed: {overlay_log[-4000:]}")
                _store_overlay_cache(props, overlay)
                timings["remotion"] = time.perf_counter() - remotion_started
                timings["overlay_cache"] = "miss"
            if cancelled and cancelled():
                raise InterruptedError("render cancelled")
            start_ms, end_ms = round(start * 1000), round((start + duration) * 1000)
            native_project = _native_segment_project(project, start_ms, end_ms)
            if native_project.cues:
                native_ass.write_text(compile_ass(native_project), encoding="utf-8-sig")
            partial = Path(temp_name) / f"output.partial{output.suffix}"
            composite = [str(Path(ffmpeg_path).resolve()), "-hide_banner", "-loglevel", "info", "-y"]
            slices = [(float(a), float(b)) for a, b in (getattr(job, "edit_segments", ()) or ())]
            scale_chain = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
            if native_ass.is_file():
                scale_chain += f",ass=filename={_ffmpeg_filter_path(native_ass)}"
            delay = max(0.0, overlay_start - start)
            audio_map = "0:a?"
            if slices:
                from .studio_render import build_concat_filter_complex, media_has_audio
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
            prev_label = "base"
            parts = [filter_graph]
            for input_index, (window_start, window_end, overlay_path) in enumerate(overlay_inputs):
                input_id = input_index + 1
                stream_label = f"ov{input_index}"
                next_label = "v" if input_index == len(overlay_inputs) - 1 else f"m{input_index}"
                parts.append(
                    f";[{input_id}:v]setpts=PTS+{max(0.0, window_start):.5f}/TB[{stream_label}]"
                )
                enable = (
                    f"enable='between(t,{max(0.0, window_start):.5f},{window_end:.5f})'"
                    if segment_overlays else ""
                )
                overlay_filter = (
                    f"[{prev_label}][{stream_label}]overlay=0:0:format=auto:"
                    f"eof_action=pass{':' + enable if enable else ''}[{next_label}]"
                )
                parts.append(";" + overlay_filter)
                prev_label = next_label
            filter_graph = "".join(parts)
            encoder = select_encoder(ffmpeg_path, job.settings)
            quality = _quality_arguments(encoder, job.settings)
            pix = job.settings.pixel_format or "yuv420p"
            composite.extend(["-i", str(Path(job.media_path).resolve())])
            for _window_start, _window_end, overlay_path in overlay_inputs:
                composite.extend(["-i", str(overlay_path)])
            composite.extend(["-t", f"{duration:.3f}",
                              "-filter_complex", filter_graph, "-map", "[v]", "-map", audio_map,
                              "-c:v", encoder, *quality, "-pix_fmt", pix])
            if job.settings.preset:
                composite.extend(["-preset", job.settings.preset])
            if job.settings.fps>0:composite.extend(['-r',f'{job.settings.fps:.12g}'])
            if job.composition_resolved:
                from .video_export import composed_video_frame_count
                frames = composed_video_frame_count(job)
                if frames is not None:composite.extend(['-frames:v',str(frames)])
            if job.settings.profile:composite.extend(['-profile:v',job.settings.profile])
            if job.settings.level:composite.extend(['-level:v',job.settings.level])
            if job.settings.gop>0:composite.extend(['-g',str(job.settings.gop)])
            if job.settings.b_frames>=0:composite.extend(['-bf',str(job.settings.b_frames)])
            if job.settings.audio_codec == "none": composite.append("-an")
            elif job.settings.audio_codec == "copy" and not slices: composite.extend(["-c:a", "copy"])
            else: composite.extend(["-c:a", "libopus" if job.settings.audio_codec == "opus" else "aac", "-b:a", f"{job.settings.audio_bitrate_kbps}k"])
            composite.extend(["-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(partial)])
            if trace: trace("advanced_composite_command", composite)
            if progress:
                progress(export_progress(
                    STAGE_ENCODE,
                    message="正在合成视频并编码…",
                    duration_seconds=duration,
                ))
            encode_started = time.perf_counter()
            def composite_line(line: str) -> None:
                if not progress:
                    return
                if line.startswith("out_time_ms=") or line.startswith("out_time="):
                    key, _, value = line.partition("=")
                    payload = export_progress(
                        STAGE_ENCODE,
                        message="正在编码视频…",
                        out_time_us=value if key == "out_time_ms" else None,
                        duration_seconds=duration,
                        speed="FFmpeg",
                        indeterminate=False,
                    )
                    if key == "out_time":
                        payload["out_time"] = value
                    seconds = parse_ffmpeg_out_time_seconds(payload)
                    if seconds is not None:
                        payload["percent"] = f"{max(0.0, min(100.0, seconds / max(0.05, duration) * 100.0)):.3f}"
                    progress(payload)
            from .export_preview import run_streaming_with_preview
            composite_code, composite_log = run_streaming_with_preview(
                composite, job, _run_streaming_process, on_line=composite_line, cancelled=cancelled,
            )
            timings["ffmpeg_composite"] = time.perf_counter() - encode_started
            if composite_code != 0 or not partial.is_file() or partial.stat().st_size <= 0:
                raise RuntimeError(f"Advanced FFmpeg composite failed: {composite_log[-4000:]}")
            mux_started = time.perf_counter()
            if progress:
                progress(export_progress(STAGE_MUX, message="正在封装文件…"))
            from .export_validation import validate_output
            metadata = validate_output(ffmpeg_path, partial, duration=duration, fps=fps, cancelled=cancelled,preview_path=job.completion_preview_path)
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
        if trace:
            notify_after_publication(job, trace, "advanced_output_verified", {"exists": output.is_file(), "size": output.stat().st_size})
            notify_after_publication(job, trace, "advanced_timings", timings)
        return output
