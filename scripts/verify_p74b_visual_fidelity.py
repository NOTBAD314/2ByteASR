"""Render VisualDesignGraph fidelity evidence through the production service.

This is automated real-process evidence, not user acceptance.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
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
RUN = ARGS.output or ROOT / "tmp" / "p74b" / (
    "visual-fidelity-" + datetime.now().strftime("%Y%m%d-%H%M%S")
)
RUN = RUN.resolve()
RUN.mkdir(parents=True, exist_ok=False)
os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"] = str(RUN / "child-processes.jsonl")

from PySide6.QtGui import QImage

from twobyteasr.advanced_renderer import compile_composition_data
from twobyteasr.renderer_service import RendererJob, RendererService
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.visual_design_graph import (
    VisualDesignGraph,
    comic_burst_graph,
    glitch_graph,
    streamer_gaming_graph,
    style_recipe_from_graph,
)


WIDTH = 640
HEIGHT = 360
FPS = 30.0
FRAME_TIMES_MS = (0, 100, 267, 800, 2_167, 2_367)


def _props(graph: VisualDesignGraph) -> dict[str, object]:
    project = SubtitleProject(
        media=StudioMedia(
            path="fixture.mp4", duration_ms=2_400, width=1920, height=1080,
        ),
        cues=[
            StudioCue(
                id="graph-cue", start_ms=0, end_ms=2_400,
                text="VISUAL GRAPH", style_id="graph",
            ),
        ],
        style_recipes={"graph": style_recipe_from_graph(graph).to_dict()},
    )
    project.validate()
    return compile_composition_data(
        project, width=WIDTH, height=HEIGHT, fps=FPS,
        start_seconds=0, duration_seconds=2.4,
    )


def _ablate(graph: VisualDesignGraph, surface: str) -> VisualDesignGraph:
    payload = copy.deepcopy(graph.to_dict())
    if surface == "panel":
        payload["panelLayer"] = {"id": "panel", "primitive": "NONE", "params": {}}
    elif surface == "decorations":
        removed = {item["id"] for item in payload["decorationLayers"]}
        payload["decorationLayers"] = []
        payload["motionGraph"]["tracks"] = [
            item for item in payload["motionGraph"]["tracks"]
            if item["target"] not in removed
        ]
    elif surface == "effects":
        removed = {item["id"] for item in payload["effectLayers"]}
        payload["effectLayers"] = []
        payload["motionGraph"]["tracks"] = [
            item for item in payload["motionGraph"]["tracks"]
            if item["target"] not in removed
        ]
    elif surface == "motion":
        payload["motionGraph"]["tracks"] = []
    else:
        raise ValueError(surface)
    payload["name"] = f"{payload['name']} without {surface}"
    return VisualDesignGraph.from_dict(payload)


def _image_data(path: Path) -> tuple[QImage, bytes]:
    image = QImage(str(path)).convertToFormat(QImage.Format.Format_RGBA8888)
    if image.isNull():
        raise RuntimeError(f"renderer output is unreadable: {path}")
    return image, bytes(image.constBits())[: image.sizeInBytes()]


def _metrics(path: Path) -> dict[str, object]:
    image, data = _image_data(path)
    line = image.bytesPerLine()
    xs: list[int] = []
    ys: list[int] = []
    nontransparent = 0
    for y in range(image.height()):
        row = y * line
        for x in range(image.width()):
            if data[row + x * 4 + 3]:
                nontransparent += 1
                xs.append(x)
                ys.append(y)
    bounds = None if not xs else [min(xs), min(ys), max(xs), max(ys)]
    return {
        "path": str(path),
        "sha256_pixels": hashlib.sha256(data).hexdigest(),
        "nontransparent_pixels": nontransparent,
        "alpha_bounds": bounds,
    }


def _pixel_difference(left: Path, right: Path) -> int:
    left_image, left_data = _image_data(left)
    right_image, right_data = _image_data(right)
    if left_image.size() != right_image.size():
        raise RuntimeError("ablation images have different dimensions")
    return sum(
        left_data[index:index + 4] != right_data[index:index + 4]
        for index in range(0, min(len(left_data), len(right_data)), 4)
    )


def main() -> int:
    graphs = {
        "comic_burst": comic_burst_graph(),
        "glitch": glitch_graph(),
        "streamer_gaming": streamer_gaming_graph(),
    }
    service = RendererService()
    jobs: list[RendererJob] = []
    outputs: dict[str, list[Path]] = {}
    props_by_name: dict[str, dict[str, object]] = {}
    for name, graph in graphs.items():
        props = _props(graph)
        props_by_name[name] = props
        outputs[name] = []
        for time_ms in FRAME_TIMES_MS:
            target = RUN / f"{name}-{time_ms:04d}ms.png"
            outputs[name].append(target)
            jobs.append(RendererJob(str(target), props, round(time_ms / 1000 * FPS)))

    ablation_outputs: dict[str, Path] = {}
    ablation_specs = {
        "comic_without_panel": ("comic_burst", "panel"),
        "comic_without_decorations": ("comic_burst", "decorations"),
        "comic_without_effects": ("comic_burst", "effects"),
        "comic_without_motion": ("comic_burst", "motion"),
        "glitch_without_effects": ("glitch", "effects"),
        "glitch_without_motion": ("glitch", "motion"),
    }
    evidence_frame_ms = 267
    for name, (source_name, surface) in ablation_specs.items():
        target = RUN / f"{name}-{evidence_frame_ms:04d}ms.png"
        ablation_outputs[name] = target
        jobs.append(RendererJob(
            str(target), _props(_ablate(graphs[source_name], surface)),
            round(evidence_frame_ms / 1000 * FPS),
        ))

    started = time.perf_counter()
    try:
        render_result = service.render(
            jobs,
            generation=1,
            snapshot_identity="p74b-visual-graph-fidelity",
            render_type="p74b_visual_graph_frames",
            resolution=(WIDTH, HEIGHT),
            batch_group="p74b-visual-graph-fidelity",
            timeout=120.0,
        )
        telemetry = list(service.telemetry())
    finally:
        service.shutdown()

    result: dict[str, object] = {
        "evidence_class": "AUTOMATED REAL PROCESS RUNTIME",
        "real_user_click": False,
        "output": str(RUN),
        "render_total_ms": round((time.perf_counter() - started) * 1000, 3),
        "service_render_ms": render_result.render_ms,
        "graphs": {},
        "ablations": {},
        "telemetry": telemetry,
    }
    graph_results: dict[str, object] = {}
    for name, paths in outputs.items():
        frames = [_metrics(path) for path in paths]
        hashes = [item["sha256_pixels"] for item in frames]
        nonblank = [int(item["nontransparent_pixels"]) > 0 for item in frames]
        graph_results[name] = {
            "visual_graph_in_recipe_props": bool(
                props_by_name[name]["recipes"]["graph"].get("visualGraph")
            ),
            "visual_graph_in_cue_props": bool(
                props_by_name[name]["cues"][0]["visual"].get("visualGraph")
            ),
            "structural": {
                "panel": graphs[name].panel_layer.primitive,
                "decorations": [item.primitive for item in graphs[name].decoration_layers],
                "effects": [item.primitive for item in graphs[name].effect_layers],
                "motion_tracks": len(graphs[name].motion_graph.tracks),
            },
            "frames": frames,
            "nonblank_after_entry": all(nonblank[1:]),
            "distinct_frame_hashes": len(set(hashes)),
            "motion_pixel_change": len(set(hashes)) >= 3,
        }
    result["graphs"] = graph_results

    full_paths = {
        "comic_burst": outputs["comic_burst"][2],
        "glitch": outputs["glitch"][2],
    }
    ablations: dict[str, object] = {}
    for name, path in ablation_outputs.items():
        source_name = ablation_specs[name][0]
        difference = _pixel_difference(full_paths[source_name], path)
        ablations[name] = {
            "metrics": _metrics(path),
            "different_pixels_from_full": difference,
            "surface_affects_pixels": difference > 0,
        }
    result["ablations"] = ablations

    result["checks"] = {
        "all_props_keep_visual_graph": all(
            item["visual_graph_in_recipe_props"] and item["visual_graph_in_cue_props"]
            for item in graph_results.values()
        ),
        "all_graphs_nonblank": all(item["nonblank_after_entry"] for item in graph_results.values()),
        "all_graphs_animate": all(item["motion_pixel_change"] for item in graph_results.values()),
        "all_ablation_surfaces_affect_pixels": all(
            item["surface_affects_pixels"] for item in ablations.values()
        ),
    }
    result["accepted"] = all(result["checks"].values())
    (RUN / "runtime-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps({
        "accepted": result["accepted"],
        "output": str(RUN),
        "checks": result["checks"],
        "render_total_ms": result["render_total_ms"],
    }, ensure_ascii=False, indent=2))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
