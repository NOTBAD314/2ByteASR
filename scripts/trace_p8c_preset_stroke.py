"""Capture the real Studio widget path for repeated preset/stroke changes.

This is headed Qt evidence (offscreen by default), not a human acceptance
claim.  Each step records the persisted appearance transaction and every
renderer-facing representation so a lost stroke can be attributed to a
specific mutation or stale result.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from twobyteasr.advanced_live_renderer import render_live_snapshot
from twobyteasr.studio_ai import style_recipe_for_prompt
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleStyle
from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.style_presets import StylePresetStore
from twobyteasr.style_recipe import route_recipe
from twobyteasr.visual_design_graph import VisualDesignGraph, clean_subtitle_graph, compile_live_scene
from twobyteasr.visual_snapshot import build_visual_cue_snapshot
from twobyteasr.runtime_trace import GLOBAL_STUDIO_TRACE


def _hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _stroke_values(value: object) -> list[dict[str, object]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if isinstance(value, tuple):
        return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _pixel_metrics(image) -> dict[str, object]:
    xs: list[int] = []
    ys: list[int] = []
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 8:
                xs.append(x)
                ys.append(y)
    return {
        "visible_pixels": len(xs),
        "alpha_bounds": [min(xs), min(ys), max(xs), max(ys)] if xs else None,
    }


def _trace_step(page: SubtitleStudioPage, label: str) -> dict[str, object]:
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    project = page.project
    cue = page._cue_lookup[page.selected_cue_id]
    style = next(item for item in project.styles if item.id == cue.style_id)
    recipe = project.style_recipes.get(cue.style_id, {})
    graph = recipe.get("visualGraph", {}) if isinstance(recipe, dict) else {}
    graph_strokes = []
    live_compiler: dict[str, object] = {"route": "native"}
    if isinstance(graph, dict) and graph:
        visual_graph = VisualDesignGraph.from_dict(graph)
        graph_strokes = copy.deepcopy(visual_graph.text_layer.strokes)
        sample = compile_live_scene(visual_graph).sample(0).values
        live_compiler = {"route": "advanced", "sample": dict(sample)}
    else:
        live_compiler = {"route": "native", "outline_width": float(style.outline_width)}
    snapshot = build_visual_cue_snapshot(project, cue.id, width=640, height=360, fps=30.0)
    identity = page._advanced_preview_state.identity
    identity_payload = asdict(identity) if identity is not None else None
    fidelity = {
        "route": route_recipe(recipe).engine if isinstance(recipe, dict) and recipe else "native",
        "identity": identity_payload,
        "generation": int(page._advanced_preview_state.generation),
        "state_phase": str(page._advanced_preview_state.phase.value),
        "source_kind": str(getattr(page, "_advanced_canvas_source_kind", "none")),
    }
    pixels = _pixel_metrics(render_live_snapshot(snapshot, width=640, height=360))
    return {
        "label": label,
        "base_preset_id": str(cue.base_preset_id),
        "style_id": str(cue.style_id),
        "appearance_override": copy.deepcopy(cue.appearance_override),
        "appearance_generation": int(cue.appearance_generation),
        "canonical_style": asdict(style),
        "canonical_style_hash": _hash(asdict(style)),
        "recipe_hash": _hash(recipe),
        "visual_graph_text_layer_strokes": graph_strokes,
        "visual_graph_strokes_hash": _hash(graph_strokes),
        "snapshot_strokes": copy.deepcopy(snapshot.strokes),
        "snapshot_hash": snapshot.stable_hash(),
        "snapshot_appearance_generation": int(snapshot.appearance_generation),
        "live_compiler": live_compiler,
        "fidelity_compiler": fidelity,
        "pixels": pixels,
    }


def _apply_preset(page: SubtitleStudioPage, preset_id: str) -> None:
    index = page.style_preset.findData(preset_id)
    if index < 0:
        raise RuntimeError(f"preset not present in Studio: {preset_id}")
    page.style_preset.setCurrentIndex(index)
    page._preset_activated(index)


def run(output: Path) -> Path:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ["LOCALAPPDATA"] = str(output / "localappdata")
    store = StylePresetStore()
    advanced = copy.deepcopy(store.all()["livestream"])
    advanced.id = "advanced-c"
    advanced.name = "Trace Advanced"
    recipe = style_recipe_for_prompt("黄色到青色渐变游戏字幕")
    recipe.engine = "remotion"
    recipe.visual_graph = clean_subtitle_graph().to_dict()
    store.upsert(advanced, recipe.to_dict(), source="p8c-trace")

    app = QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    page._create_blank_studio()
    page.project.media = StudioMedia(path="fixture.mp4", duration_ms=60_000, width=640, height=360)
    page.project.render_settings.update({"play_res_x": 640, "play_res_y": 360})
    page.project.cues = [StudioCue("cue", 0, 30_000, "0 8 B 中 口 回", style_id="default")]
    page.cue_controller.model_changed()
    page.timeline.reindex_project()
    page.timeline.set_playhead(1_000)
    page.select_cue("cue")
    page._media_ingest_state = "READY"
    page._empty_playback_state = False
    page.video._paused = True
    # Keep the real request/identity path, but do not spawn a Remotion child
    # process for this ownership trace.
    page._queue_advanced_preview_job = lambda *_args, **_kwargs: None
    apply_log: list[dict[str, object]] = []
    original_apply_style = page._apply_style

    def traced_apply_style(*, replace_preset: bool = False):
        before = int(page._cue_lookup[page.selected_cue_id].appearance_generation)
        result = original_apply_style(replace_preset=replace_preset)
        after = int(page._cue_lookup[page.selected_cue_id].appearance_generation)
        apply_log.append({
            "replace_preset": bool(replace_preset),
            "before_generation": before,
            "after_generation": after,
        })
        return result

    page._apply_style = traced_apply_style

    steps: list[dict[str, object]] = []
    steps.append(_trace_step(page, "initial"))
    _apply_preset(page, "clean-white")
    steps.append(_trace_step(page, "preset-clean-white"))
    page.style_outline_width.setValue(20)
    page._apply_style()
    steps.append(_trace_step(page, "stroke-20"))
    _apply_preset(page, "game")
    steps.append(_trace_step(page, "preset-game"))
    _apply_preset(page, "clean-white")
    steps.append(_trace_step(page, "preset-clean-white-again"))
    page.style_outline_width.setValue(20)
    page._apply_style()
    steps.append(_trace_step(page, "custom-stroke-20"))
    _apply_preset(page, "advanced-c")
    steps.append(_trace_step(page, "preset-advanced-c"))
    _apply_preset(page, "game")
    steps.append(_trace_step(page, "preset-game-back"))
    payload = {
        "kind": "p8c-r2-preset-stroke-trace",
        "automated": True,
        "human_verified": False,
        "steps": steps,
        "final_generation": int(page._advanced_preview_state.generation),
        "apply_log": apply_log,
    }
    target = output / "preset-stroke-trace.json"
    payload["runtime_trace"] = [
        dict(item) for item in GLOBAL_STUDIO_TRACE.recent()
        if str(item.get("event")) in {
            "ADVANCED_REVOKE", "FIDELITY_CONTRACT_REJECT", "WORKER_STALE",
            "RENDERER_OWNER_CHANGED", "SUBTITLE_VISIBILITY",
        }
    ]
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    page.close_page()
    app.processEvents()
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(run(args.output))


if __name__ == "__main__":
    main()
