"""P8B LIVE/Remotion golden motion and canonical stroke pixel evidence.

This is automated real-process evidence. It does not represent user acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


ARGS = _arguments()
RUN = (ARGS.output or ROOT / "tmp" / "p8b" / (
    "visual-fidelity-" + datetime.now().strftime("%Y%m%d-%H%M%S")
)).resolve()
RUN.mkdir(parents=True, exist_ok=False)
os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"] = str(RUN / "child-processes.jsonl")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QImage, QPainter
from PySide6.QtWidgets import QApplication

from twobyteasr.advanced_live_renderer import (
    composite_live_scene_layers,
    render_live_layers,
    render_live_snapshot,
)
from twobyteasr.advanced_renderer import compile_composition_data
from twobyteasr.renderer_service import RendererJob, RendererService
from twobyteasr.studio_project import (
    StudioCue,
    StudioMedia,
    SubtitleProject,
    SubtitleStyle,
)
from twobyteasr.visual_design_graph import (
    GOLDEN_VISUAL_GRAPHS,
    CompiledLiveScene,
    VisualDesignGraph,
    clean_subtitle_graph,
    motion_phases,
    style_recipe_from_graph,
)
from twobyteasr.visual_snapshot import build_visual_cue_snapshot


APP = QApplication.instance() or QApplication([])
GOLDEN_WIDTH = 640
GOLDEN_HEIGHT = 360
STROKE_WIDTH = 960
STROKE_HEIGHT = 540
FPS = 30.0
PANEL_PRIMITIVES = (
    "CUT_CORNER", "ANGLED_PLATE", "RIBBON", "BRACKET_FRAME",
    "TECH_FRAME", "COMIC_BUBBLE", "BADGE", "UNDERLINE_SLAB",
)


def _resolve_graph_font(graph: VisualDesignGraph, text: str) -> dict[str, object]:
    families = {item.casefold(): item for item in QFontDatabase.families()}
    requested = str(graph.text_layer.font.get("family") or "").strip()
    resolved = families.get(requested.casefold())
    if resolved is None:
        for fallback in (
            "Noto Sans SC", "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Arial",
        ):
            resolved = families.get(fallback.casefold())
            if resolved:
                break
    resolved = resolved or QFont().defaultFamily()
    graph.text_layer.font["family"] = resolved
    font = QFont(resolved)
    font.setPixelSize(max(1, round(float(graph.text_layer.font.get("size", 56)))))
    metrics = QFontMetrics(font)
    missing = [character for character in text if not character.isspace() and not metrics.inFontUcs4(ord(character))]
    return {
        "requested": requested,
        "resolved": resolved,
        "missing_characters": missing,
        "glyphs_supported": not missing,
        "available_family_count": len(families),
    }


def _project_for_graph(
    graph: VisualDesignGraph,
    *,
    text: str,
    duration_ms: int = 2_400,
) -> SubtitleProject:
    graph.validate()
    recipe = style_recipe_from_graph(graph)
    stroke = graph.text_layer.strokes[0] if graph.text_layer.strokes else {
        "color": "#FF000000", "width": 0,
    }
    fill = graph.text_layer.fill
    primary = str(fill.get("color") or "#FFFFFFFF")
    style = SubtitleStyle(
        "graph", graph.name,
        font_family=str(graph.text_layer.font.get("family") or "Arial"),
        font_size=float(graph.text_layer.font.get("size", 56)),
        primary_color=primary,
        outline_color=str(stroke.get("color") or "#FF000000"),
        outline_width=float(stroke.get("width", 0)),
        bold=int(graph.text_layer.font.get("weight", 700)) >= 700,
        alignment=5,
        position_x=960,
        position_y=540,
    )
    project = SubtitleProject(
        media=StudioMedia(
            path="fixture.mp4", duration_ms=duration_ms,
            width=1920, height=1080,
        ),
        styles=[style],
        cues=[StudioCue("cue", 0, duration_ms, text, style_id="graph")],
        style_recipes={"graph": recipe.to_dict()},
    )
    project.validate()
    return project


def _snapshot(
    graph: VisualDesignGraph,
    *,
    text: str,
    width: int,
    height: int,
):
    project = _project_for_graph(graph, text=text)
    return build_visual_cue_snapshot(
        project, "cue", width=width, height=height, fps=FPS,
    )


def _props(
    graph: VisualDesignGraph,
    *,
    text: str,
    width: int,
    height: int,
) -> dict[str, object]:
    return compile_composition_data(
        _project_for_graph(graph, text=text),
        width=width, height=height, fps=FPS,
        start_seconds=0, duration_seconds=2.4,
    )


def _phase_frames(graph: VisualDesignGraph) -> dict[str, int]:
    phases = motion_phases(graph)
    values = {
        "entrance": max(1, round(phases.entrance_end_ms * 0.5)),
        "impact": max(1, phases.entrance_end_ms),
        "hold": round((phases.hold_start_ms + phases.hold_end_ms) * 0.5),
        "exit": round((phases.exit_start_ms + phases.exit_end_ms) * 0.5),
    }
    return {
        name: max(0, min(round(graph.motion_graph.duration_ms / 1000 * FPS) - 1,
                         round(value / 1000 * FPS)))
        for name, value in values.items()
    }


def _rgba(image: QImage) -> tuple[QImage, bytes]:
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return converted, bytes(converted.constBits())[:converted.sizeInBytes()]


def _metrics(path: Path) -> dict[str, object]:
    source = QImage(str(path))
    if source.isNull():
        raise RuntimeError(f"unreadable image: {path}")
    image, data = _rgba(source)
    line = image.bytesPerLine()
    xs: list[int] = []
    ys: list[int] = []
    dark_pixels = 0
    white_pixels = 0
    cyan_pixels = 0
    visible_pixels = 0
    alpha_sum = 0
    for y in range(image.height()):
        row = y * line
        for x in range(image.width()):
            offset = row + x * 4
            red, green, blue, alpha = data[offset:offset + 4]
            if alpha > 8:
                xs.append(x)
                ys.append(y)
                visible_pixels += 1
                alpha_sum += alpha
            if alpha > 64 and (red * 299 + green * 587 + blue * 114) / 1000 < 90:
                dark_pixels += 1
            # Core fill excludes antialiased edge coverage. The outside-stroke
            # contract is that this fully covered glyph body stays unchanged.
            if alpha > 240 and min(red, green, blue) > 240:
                white_pixels += 1
            if alpha > 96 and blue > red + 30 and green > red + 20:
                cyan_pixels += 1
    bounds = None if not xs else [min(xs), min(ys), max(xs), max(ys)]
    return {
        "path": str(path),
        "sha256_pixels": hashlib.sha256(data).hexdigest(),
        "alpha_bounds": bounds,
        "visible_pixels": visible_pixels,
        "dark_outline_pixels": dark_pixels,
        "white_fill_pixels": white_pixels,
        "cyan_panel_pixels": cyan_pixels,
        "mean_visible_alpha": round(alpha_sum / max(1, visible_pixels), 3),
    }


def _radius_from_bounds(bounds: list[int], base: list[int]) -> float:
    left = max(0, base[0] - bounds[0])
    top = max(0, base[1] - bounds[1])
    right = max(0, bounds[2] - base[2])
    bottom = max(0, bounds[3] - base[3])
    return round(statistics.mean((left, top, right, bottom)), 3)


def _bounds_parity(left: list[int], right: list[int]) -> dict[str, object]:
    left_width = left[2] - left[0] + 1
    left_height = left[3] - left[1] + 1
    right_width = right[2] - right[0] + 1
    right_height = right[3] - right[1] + 1
    center_delta = math.hypot(
        (left[0] + left[2] - right[0] - right[2]) / 2,
        (left[1] + left[3] - right[1] - right[3]) / 2,
    )
    width_ratio = right_width / max(1, left_width)
    height_ratio = right_height / max(1, left_height)
    return {
        "live_size": [left_width, left_height],
        "remotion_size": [right_width, right_height],
        "width_ratio": round(width_ratio, 3),
        "height_ratio": round(height_ratio, 3),
        "center_delta_px": round(center_delta, 3),
        "accepted": bool(
            0.60 <= width_ratio <= 1.60
            and 0.60 <= height_ratio <= 1.60
            and center_delta <= 28.0
        ),
    }


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
    return round(ordered[index], 3)


def _contact_sheet(
    paths: list[tuple[str, Path]],
    target: Path,
    *,
    columns: int = 4,
) -> None:
    cell_width = 320
    cell_height = 205
    rows = math.ceil(len(paths) / columns)
    sheet = QImage(
        cell_width * columns, cell_height * rows,
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    sheet.fill(QColor("#FF17191D"))
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.setFont(QFont("Microsoft YaHei UI", 10))
    for index, (label, path) in enumerate(paths):
        column = index % columns
        row = index // columns
        x = column * cell_width
        y = row * cell_height
        painter.setPen(QColor("#FFE8EBF0"))
        painter.drawText(QRect(x + 8, y + 4, cell_width - 16, 23),
                         Qt.AlignmentFlag.AlignLeft, label)
        image = QImage(str(path))
        if not image.isNull():
            painter.drawImage(QRect(x, y + 27, cell_width, 178), image)
    painter.end()
    if not sheet.save(str(target)):
        raise RuntimeError(f"failed to save contact sheet: {target}")


def _stroke_graph(width: float) -> VisualDesignGraph:
    graph = clean_subtitle_graph()
    graph.name = f"Stroke {width:g}"
    graph.text_layer.font = {
        "family": "Arial", "size": 115, "weight": 700,
    }
    graph.text_layer.fill = {"type": "solid", "color": "#FFFFFFFF"}
    graph.text_layer.strokes = [] if width == 0 else [{
        "color": "#FF000000", "width": width, "opacity": 1,
    }]
    graph.text_layer.shadow = {}
    graph.text_layer.glow = {}
    return graph.validate()


def _shadow_graph(enabled: bool) -> VisualDesignGraph:
    graph = _stroke_graph(10)
    graph.name = f"Shadow {'on' if enabled else 'off'}"
    graph.text_layer.shadow = ({
        "enabled": True,
        "color": "#FF000000",
        "opacity": 0.8,
        "offset_x": 12,
        "offset_y": 12,
        "blur_radius": 12,
        "blur": 12,
        "spread": 2,
    } if enabled else {})
    return graph.validate()


def _panel_graph(primitive: str) -> VisualDesignGraph:
    graph = _stroke_graph(4)
    graph.name = f"Panel {primitive}"
    graph.text_layer.font["size"] = 90
    graph.panel_layer.primitive = primitive
    graph.panel_layer.params = ({
        "color": "#CC00BDEB",
        "paddingX": 32,
        "paddingY": 18,
    } if primitive != "NONE" else {})
    # BRACKET_FRAME and TECH_FRAME intentionally omit outlineColor and
    # outlineWidth: this fixture verifies their canonical visible defaults.
    return graph.validate()


def _bounds_growth(on: list[int] | None, off: list[int] | None) -> list[int]:
    if on is None or off is None:
        return [0, 0, 0, 0]
    return [off[0] - on[0], off[1] - on[1], on[2] - off[2], on[3] - off[3]]


def main() -> int:
    golden_root = RUN / "golden"
    stroke_root = RUN / "stroke"
    shadow_root = RUN / "shadow"
    panel_root = RUN / "panels"
    for route in ("live", "remotion"):
        (golden_root / route).mkdir(parents=True)
        (stroke_root / route).mkdir(parents=True)
        (shadow_root / route).mkdir(parents=True)
        (panel_root / route).mkdir(parents=True)

    service = RendererService()
    remotion_jobs: list[RendererJob] = []
    golden_paths: dict[str, dict[str, dict[str, Path]]] = {}
    golden_records: dict[str, object] = {}
    composite_times: list[float] = []
    card_first_frames: dict[str, float] = {}
    font_evidence_by_name: dict[str, dict[str, object]] = {}

    for name, factory in GOLDEN_VISUAL_GRAPHS.items():
        graph = factory()
        font_evidence = _resolve_graph_font(graph, "高能时刻")
        font_evidence_by_name[name] = font_evidence
        frames = _phase_frames(graph)
        props = _props(
            graph, text="高能时刻", width=GOLDEN_WIDTH, height=GOLDEN_HEIGHT,
        )
        snapshot = _snapshot(
            graph, text="高能时刻", width=GOLDEN_WIDTH, height=GOLDEN_HEIGHT,
        )
        started = time.perf_counter()
        layers = render_live_layers(
            snapshot, width=GOLDEN_WIDTH, height=GOLDEN_HEIGHT,
        )
        scene = CompiledLiveScene.compile(graph)
        golden_paths[name] = {"live": {}, "remotion": {}}
        for phase, frame_number in frames.items():
            local_ms = round(frame_number / FPS * 1000)
            composite_started = time.perf_counter()
            image, _sample = composite_live_scene_layers(layers, scene, local_ms)
            composite_times.append((time.perf_counter() - composite_started) * 1000)
            live_path = golden_root / "live" / f"{name}-{phase}.png"
            if not image.save(str(live_path)):
                raise RuntimeError(f"failed to save LIVE frame: {live_path}")
            golden_paths[name]["live"][phase] = live_path
            fidelity_path = golden_root / "remotion" / f"{name}-{phase}.png"
            golden_paths[name]["remotion"][phase] = fidelity_path
            remotion_jobs.append(RendererJob(str(fidelity_path), props, frame_number))
        card_first_frames[name] = round((time.perf_counter() - started) * 1000, 3)

    stroke_props: dict[float, dict[str, object]] = {}
    for width in (0.0, 1.0, 5.0, 10.0, 20.0):
        graph = _stroke_graph(width)
        snapshot = _snapshot(
            graph, text="H", width=STROKE_WIDTH, height=STROKE_HEIGHT,
        )
        live_path = stroke_root / "live" / f"stroke-{width:g}.png"
        live_image = render_live_snapshot(
            snapshot, width=STROKE_WIDTH, height=STROKE_HEIGHT,
        )
        if not live_image.save(str(live_path)):
            raise RuntimeError(f"failed to save LIVE stroke frame: {live_path}")
        props = _props(
            graph, text="H", width=STROKE_WIDTH, height=STROKE_HEIGHT,
        )
        stroke_props[width] = props
        fidelity_path = stroke_root / "remotion" / f"stroke-{width:g}.png"
        remotion_jobs.append(RendererJob(str(fidelity_path), props, round(FPS)))

    for enabled in (False, True):
        graph = _shadow_graph(enabled)
        snapshot = _snapshot(
            graph, text="H", width=STROKE_WIDTH, height=STROKE_HEIGHT,
        )
        label = "on" if enabled else "off"
        live_path = shadow_root / "live" / f"shadow-{label}.png"
        live_image = render_live_snapshot(
            snapshot, width=STROKE_WIDTH, height=STROKE_HEIGHT,
        )
        if not live_image.save(str(live_path)):
            raise RuntimeError(f"failed to save LIVE shadow frame: {live_path}")
        fidelity_path = shadow_root / "remotion" / f"shadow-{label}.png"
        remotion_jobs.append(RendererJob(
            str(fidelity_path),
            _props(graph, text="H", width=STROKE_WIDTH, height=STROKE_HEIGHT),
            round(FPS),
        ))

    for primitive in ("NONE", *PANEL_PRIMITIVES):
        graph = _panel_graph(primitive)
        snapshot = _snapshot(
            graph, text="P8C", width=STROKE_WIDTH, height=STROKE_HEIGHT,
        )
        live_path = panel_root / "live" / f"panel-{primitive.casefold()}.png"
        live_image = render_live_snapshot(
            snapshot, width=STROKE_WIDTH, height=STROKE_HEIGHT,
        )
        if not live_image.save(str(live_path)):
            raise RuntimeError(f"failed to save LIVE panel frame: {live_path}")
        fidelity_path = panel_root / "remotion" / f"panel-{primitive.casefold()}.png"
        remotion_jobs.append(RendererJob(
            str(fidelity_path),
            _props(graph, text="P8C", width=STROKE_WIDTH, height=STROKE_HEIGHT),
            round(FPS),
        ))

    render_started = time.perf_counter()
    try:
        render_result = service.render(
            remotion_jobs,
            generation=1,
            snapshot_identity="p8c-visual-fidelity-fixtures",
            render_type="p8c_visual_fidelity_frames",
            resolution=(GOLDEN_WIDTH, GOLDEN_HEIGHT),
            batch_group="p8c-visual-fidelity-fixtures",
            timeout=180.0,
        )
        telemetry = list(service.telemetry())
    finally:
        service.shutdown()
    remotion_wall_ms = round((time.perf_counter() - render_started) * 1000, 3)

    live_sheet: list[tuple[str, Path]] = []
    remotion_sheet: list[tuple[str, Path]] = []
    for name, routes in golden_paths.items():
        route_records: dict[str, object] = {}
        for route, phases in routes.items():
            phase_metrics = {phase: _metrics(path) for phase, path in phases.items()}
            route_records[route] = {
                "frames": phase_metrics,
                "nonblank": all(item["visible_pixels"] > 0 for item in phase_metrics.values()),
                "distinct_phases": len({
                    item["sha256_pixels"] for item in phase_metrics.values()
                }),
            }
            destination = live_sheet if route == "live" else remotion_sheet
            destination.extend((f"{name} / {phase}", path) for phase, path in phases.items())
        golden_records[name] = {
            "structure": {
                "panel": GOLDEN_VISUAL_GRAPHS[name]().panel_layer.primitive,
                "decorations": [
                    item.primitive for item in GOLDEN_VISUAL_GRAPHS[name]().decoration_layers
                ],
                "effects": [
                    item.primitive for item in GOLDEN_VISUAL_GRAPHS[name]().effect_layers
                ],
                "motion_tracks": len(GOLDEN_VISUAL_GRAPHS[name]().motion_graph.tracks),
            },
            "card_first_frame_ms": card_first_frames[name],
            "font": font_evidence_by_name[name],
            "hold_bounds_parity": _bounds_parity(
                route_records["live"]["frames"]["hold"]["alpha_bounds"],
                route_records["remotion"]["frames"]["hold"]["alpha_bounds"],
            ),
            **route_records,
        }

    _contact_sheet(live_sheet, RUN / "golden-live-contact-sheet.png")
    _contact_sheet(remotion_sheet, RUN / "golden-remotion-contact-sheet.png")

    stroke_records: dict[str, object] = {}
    for route in ("live", "remotion"):
        metrics = {
            width: _metrics(stroke_root / route / f"stroke-{width:g}.png")
            for width in (0.0, 1.0, 5.0, 10.0, 20.0)
        }
        base_bounds = metrics[0.0]["alpha_bounds"]
        base_dark = int(metrics[0.0]["dark_outline_pixels"])
        base_white = int(metrics[0.0]["white_fill_pixels"])
        levels = {}
        for width in (1.0, 5.0, 10.0, 20.0):
            bounds = metrics[width]["alpha_bounds"]
            levels[f"{width:g}"] = {
                **metrics[width],
                "estimated_outward_radius_px": _radius_from_bounds(bounds, base_bounds),
                "outline_area_over_fill": max(
                    0, int(metrics[width]["dark_outline_pixels"]) - base_dark,
                ),
                "inner_white_ratio": round(
                    int(metrics[width]["white_fill_pixels"]) / max(1, base_white), 4,
                ),
            }
        stroke_records[route] = {"baseline": metrics[0.0], "levels": levels}

    stroke_checks: dict[str, bool] = {}
    for route, record in stroke_records.items():
        levels = record["levels"]
        areas = [levels[key]["outline_area_over_fill"] for key in ("1", "5", "10", "20")]
        radii = [levels[key]["estimated_outward_radius_px"] for key in ("1", "5", "10", "20")]
        stroke_checks[f"{route}_area_strict_order"] = all(
            left < right for left, right in zip(areas, areas[1:])
        )
        stroke_checks[f"{route}_radius_order"] = all(
            left <= right for left, right in zip(radii, radii[1:])
        ) and radii[-1] > radii[0]
        stroke_checks[f"{route}_stroke20_not_thin"] = radii[-1] >= 7.0
        stroke_checks[f"{route}_inner_white_stable"] = all(
            0.97 <= float(levels[key]["inner_white_ratio"]) <= 1.03
            for key in ("1", "5", "10", "20")
        )

    live20 = stroke_records["live"]["levels"]["20"]["estimated_outward_radius_px"]
    fidelity20 = stroke_records["remotion"]["levels"]["20"]["estimated_outward_radius_px"]
    stroke_checks["stroke20_live_fidelity_close"] = abs(live20 - fidelity20) <= 2.5

    shadow_records: dict[str, object] = {}
    shadow_checks: dict[str, bool] = {}
    for route in ("live", "remotion"):
        off = _metrics(shadow_root / route / "shadow-off.png")
        on = _metrics(shadow_root / route / "shadow-on.png")
        growth = {
            "dark_pixels": int(on["dark_outline_pixels"]) - int(off["dark_outline_pixels"]),
            "visible_pixels": int(on["visible_pixels"]) - int(off["visible_pixels"]),
            "bounds": _bounds_growth(on["alpha_bounds"], off["alpha_bounds"]),
            "inner_white_ratio": round(
                int(on["white_fill_pixels"]) / max(1, int(off["white_fill_pixels"])), 4,
            ),
        }
        shadow_records[route] = {"off": off, "on": on, "growth": growth}
        shadow_checks[f"{route}_shadow_visible"] = bool(
            growth["dark_pixels"] > 0
            and growth["visible_pixels"] > 0
            and max(growth["bounds"]) > 0
            and 0.97 <= growth["inner_white_ratio"] <= 1.03
        )

    panel_records: dict[str, object] = {}
    panel_checks: dict[str, bool] = {}
    for route in ("live", "remotion"):
        baseline = _metrics(panel_root / route / "panel-none.png")
        levels = {}
        for primitive in PANEL_PRIMITIVES:
            metrics = _metrics(
                panel_root / route / f"panel-{primitive.casefold()}.png"
            )
            levels[primitive] = {
                **metrics,
                "visible_growth": int(metrics["visible_pixels"]) - int(baseline["visible_pixels"]),
                "bounds_growth": _bounds_growth(
                    metrics["alpha_bounds"], baseline["alpha_bounds"],
                ),
            }
        panel_records[route] = {"baseline": baseline, "levels": levels}
        panel_checks[f"{route}_all_panels_visible"] = all(
            item["visible_pixels"] > 0 and item["visible_growth"] > 0
            for item in levels.values()
        )
        panel_checks[f"{route}_panels_structurally_distinct"] = (
            len({item["sha256_pixels"] for item in levels.values()})
            == len(PANEL_PRIMITIVES)
        )
        panel_checks[f"{route}_frame_default_outline_visible"] = all(
            levels[name]["cyan_panel_pixels"] > 0
            for name in ("BRACKET_FRAME", "TECH_FRAME")
        )
    panel_checks["panel_live_remotion_bounds_close"] = all(
        _bounds_parity(
            panel_records["live"]["levels"][primitive]["alpha_bounds"],
            panel_records["remotion"]["levels"][primitive]["alpha_bounds"],
        )["accepted"]
        for primitive in PANEL_PRIMITIVES
    )

    _contact_sheet(
        [
            (f"LIVE {primitive}", panel_root / "live" / f"panel-{primitive.casefold()}.png")
            for primitive in PANEL_PRIMITIVES
        ],
        RUN / "p8c-panels-live-contact-sheet.png",
    )
    _contact_sheet(
        [
            (f"Remotion {primitive}", panel_root / "remotion" / f"panel-{primitive.casefold()}.png")
            for primitive in PANEL_PRIMITIVES
        ],
        RUN / "p8c-panels-remotion-contact-sheet.png",
    )

    checks = {
        "six_golden_families": len(golden_records) == 6,
        "all_live_phases_nonblank": all(
            item["live"]["nonblank"] for item in golden_records.values()
        ),
        "all_remotion_phases_nonblank": all(
            item["remotion"]["nonblank"] for item in golden_records.values()
        ),
        "all_live_motion_changes_pixels": all(
            item["live"]["distinct_phases"] >= 3 for item in golden_records.values()
        ),
        "all_remotion_motion_changes_pixels": all(
            item["remotion"]["distinct_phases"] >= 3 for item in golden_records.values()
        ),
        "all_live_fixture_glyphs_supported": all(
            item["font"]["glyphs_supported"] for item in golden_records.values()
        ),
        "all_hold_layouts_live_remotion_close": all(
            item["hold_bounds_parity"]["accepted"] for item in golden_records.values()
        ),
        "card_first_frame_under_150ms": max(card_first_frames.values()) < 150.0,
        "live_composite_p95_under_40ms": _percentile(composite_times, 0.95) < 40.0,
        **stroke_checks,
        **shadow_checks,
        **panel_checks,
    }
    result = {
        "evidence_class": "AUTOMATED LIVE PIXELS + REAL REMOTION PROCESS",
        "real_user_click": False,
        "output": str(RUN),
        "golden": golden_records,
        "stroke": stroke_records,
        "shadow": shadow_records,
        "panels": panel_records,
        "performance": {
            "card_first_frame_ms": card_first_frames,
            "card_first_frame_max_ms": max(card_first_frames.values()),
            "live_composite_samples": len(composite_times),
            "live_composite_p95_ms": _percentile(composite_times, 0.95),
            "remotion_batch_wall_ms": remotion_wall_ms,
            "remotion_service_render_ms": render_result.render_ms,
        },
        "telemetry": telemetry,
        "checks": checks,
        "accepted": all(checks.values()),
    }
    (RUN / "runtime-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps({
        "accepted": result["accepted"],
        "output": str(RUN),
        "checks": checks,
        "performance": result["performance"],
        "stroke20": {"live": live20, "remotion": fidelity20},
    }, ensure_ascii=False, indent=2))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
