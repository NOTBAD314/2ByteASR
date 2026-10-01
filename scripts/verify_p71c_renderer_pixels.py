"""Render and measure P7.1C Motion/Gradient/Shadow pixel evidence."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tmp" / "p71c" / "renderer-pixels"
OUTPUT.mkdir(parents=True, exist_ok=True)
os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"] = str(OUTPUT / "child-processes.jsonl")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw

from twobyteasr.advanced_renderer import compile_composition_data
from twobyteasr.processes import run_hidden_subprocess
from twobyteasr.studio_project import (
    StudioCue,
    StudioMedia,
    SubtitleProject,
    SubtitleStyle,
)
from twobyteasr.style_recipe import FillSpec, StyleRecipe, normalize_shadow_contract


WIDTH = 960
HEIGHT = 540
FPS = 30.0
DURATION_SECONDS = 3.0
FRAMES = {"early": 3, "middle": 45, "late": 86}
SHADOW_STRENGTHS = (0.0, 0.1, 0.5, 1.0)


def progress(message: str) -> None:
    print(f"[p71c-pixels] {message}", flush=True)


def _fill(kind: str):
    if kind == "solid":
        return FillSpec.solid("#FFFFE45E").to_recipe_value()
    return FillSpec.linear(
        [
            {"color": "#FFFFE45E", "position": 0.0},
            {"color": "#FF20D9FF", "position": 1.0},
        ],
        angle=18.0,
    ).to_recipe_value()


def _props(
    *,
    fill_kind: str,
    motion: dict[str, object],
    shadow_strength: float,
    strokes: list[dict[str, object]],
    text: str,
) -> dict[str, object]:
    style = SubtitleStyle(
        id="visual",
        name="P7.1C pixel evidence",
        font_family="Microsoft YaHei UI",
        font_size=96,
        bold=True,
        alignment=5,
        position_x=960,
        position_y=540,
        shadow=0,
        outline_width=0,
    )
    recipe = StyleRecipe(
        name="P7.1C renderer pixel evidence",
        engine="remotion",
        typography={
            "fontFamily": "Microsoft YaHei UI",
            "fontSize": 96,
            "bold": True,
            "spacing": 0,
        },
        colors={"fill": _fill(fill_kind)},
        outline={
            "layers": strokes,
            "shadow": normalize_shadow_contract(shadow_strength),
        },
        motion=motion,
    )
    recipe.validate()
    project = SubtitleProject(
        media=StudioMedia(
            path="P7.1C-renderer-pixel-fixture.mp4",
            duration_ms=3_000,
            width=1920,
            height=1080,
        ),
        cues=[StudioCue("visual-cue", 0, 3_000, text, style_id="visual")],
        styles=[style],
        style_recipes={"visual": recipe.to_dict()},
        render_settings={"play_res_x": 1920, "play_res_y": 1080},
    )
    project.validate()
    return compile_composition_data(
        project,
        width=WIDTH,
        height=HEIGHT,
        fps=FPS,
        start_seconds=0,
        duration_seconds=DURATION_SECONDS,
    )


def _render(name: str, props: dict[str, object], frame: int) -> Path:
    renderer = ROOT / "renderer"
    target = OUTPUT / f"{name}.png"
    props_path = OUTPUT / f"{name}.json"
    props_path.write_text(
        json.dumps(props, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if target.exists():
        target.unlink()
    cli = renderer / "node_modules" / ".bin" / (
        "remotion.cmd" if os.name == "nt" else "remotion"
    )
    command = [
        str(cli),
        "still",
        "src/index.ts",
        "SubtitleOverlay",
        str(target),
        f"--props={props_path}",
        f"--frame={int(frame)}",
        "--log=error",
    ]
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if chrome.is_file():
        command.append(f"--browser-executable={chrome}")
    completed = run_hidden_subprocess(
        command,
        cwd=renderer,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        purpose="P7.1C renderer pixel evidence",
    )
    if completed.returncode != 0 or not target.is_file() or target.stat().st_size <= 0:
        details = (completed.stderr or completed.stdout or "")[-2000:]
        raise RuntimeError(f"Remotion still failed for {name}: {details}")
    return target


def _image_metrics(path: Path) -> dict[str, object]:
    image = Image.open(path).convert("RGBA")
    alpha = image.getchannel("A")
    values = list(alpha.getdata())
    return {
        "path": str(path),
        "sha256_pixels": hashlib.sha256(image.tobytes()).hexdigest(),
        "alpha_bounds": list(alpha.getbbox() or ()),
        "nontransparent_pixels": sum(value > 0 for value in values),
        "opaque_pixels": sum(value >= 250 for value in values),
        "max_alpha": max(values, default=0),
    }


def _foreground_comparison(baseline_path: Path, candidate_path: Path) -> dict[str, object]:
    baseline = Image.open(baseline_path).convert("RGBA")
    candidate = Image.open(candidate_path).convert("RGBA")
    baseline_pixels = list(baseline.getdata())
    candidate_pixels = list(candidate.getdata())
    foreground = [index for index, pixel in enumerate(baseline_pixels) if pixel[3] >= 250]
    changed = 0
    darkened = 0
    max_channel_delta = 0
    for index in foreground:
        before = baseline_pixels[index]
        after = candidate_pixels[index]
        delta = max(abs(after[channel] - before[channel]) for channel in range(3))
        max_channel_delta = max(max_channel_delta, delta)
        if delta > 1:
            changed += 1
        before_luma = before[0] * 0.2126 + before[1] * 0.7152 + before[2] * 0.0722
        after_luma = after[0] * 0.2126 + after[1] * 0.7152 + after[2] * 0.0722
        if after_luma + 1 < before_luma:
            darkened += 1
    extra_shadow = sum(
        before[3] == 0 and after[3] > 0
        for before, after in zip(baseline_pixels, candidate_pixels)
    )
    return {
        "foreground_pixels": len(foreground),
        "changed_foreground_pixels": changed,
        "darkened_foreground_pixels": darkened,
        "max_foreground_channel_delta": max_channel_delta,
        "extra_shadow_pixels": extra_shadow,
    }


def _checkerboard(size: tuple[int, int]) -> Image.Image:
    image = Image.new("RGBA", size, (37, 41, 45, 255))
    draw = ImageDraw.Draw(image)
    tile = 16
    for y in range(0, size[1], tile):
        for x in range(0, size[0], tile):
            if (x // tile + y // tile) % 2:
                draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill=(55, 60, 65, 255))
    return image


def _contact_sheet(rows: list[tuple[str, list[Path]]]) -> Path:
    thumb_size = (320, 180)
    caption_height = 24
    sheet = Image.new(
        "RGB",
        (thumb_size[0] * 4, (thumb_size[1] + caption_height) * len(rows)),
        (24, 27, 30),
    )
    draw = ImageDraw.Draw(sheet)
    for row_index, (label, paths) in enumerate(rows):
        for column, path in enumerate(paths):
            source = Image.open(path).convert("RGBA")
            checker = _checkerboard(source.size)
            checker.alpha_composite(source)
            checker.thumbnail(thumb_size, Image.Resampling.LANCZOS)
            x = column * thumb_size[0]
            y = row_index * (thumb_size[1] + caption_height)
            sheet.paste(checker.convert("RGB"), (x, y))
            draw.text(
                (x + 8, y + thumb_size[1] + 5),
                f"{label} | shadow {SHADOW_STRENGTHS[column]:g}",
                fill=(235, 239, 242),
            )
    target = OUTPUT / "shadow-matrix-contact-sheet.png"
    sheet.save(target)
    return target


def _child_records() -> list[dict[str, object]]:
    path = Path(os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"])
    rows: list[dict[str, object]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def main() -> int:
    child_log = Path(os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"])
    if child_log.exists():
        child_log.unlink()
    result: dict[str, object] = {
        "schema": "2byteasr.p71c-renderer-pixels.v1",
        "evidence_class": "ACTUAL REMOTION PIXEL VERIFIED",
        "real_user_click": False,
        "renderer_chain": (
            "StyleRecipe -> VisualCueSnapshot -> normalized_visual_snapshot "
            "-> Remotion SubtitleOverlay/TrustedSubtitle"
        ),
    }

    progress("rendering Gradient + Motion None at early/middle/late")
    static_props = _props(
        fill_kind="gradient",
        motion={"mode": "none"},
        shadow_strength=0,
        strokes=[{"color": "#FF101317", "width": 3}],
        text="STATIC GRADIENT",
    )
    static_paths = {
        name: _render(f"gradient-none-{name}", static_props, frame)
        for name, frame in FRAMES.items()
    }
    static_metrics = {name: _image_metrics(path) for name, path in static_paths.items()}
    static_hashes = {item["sha256_pixels"] for item in static_metrics.values()}
    result["gradient_motion_none"] = {
        "frames": static_metrics,
        "identical_pixel_hashes": len(static_hashes) == 1,
    }

    progress("rendering Gradient + explicit entrance/exit motion")
    motion_props = _props(
        fill_kind="gradient",
        motion={
            "mode": "explicit",
            "entrance": {"type": "fade", "duration_ms": 600},
            "hold": {},
            "exit": {"type": "fade", "duration_ms": 600},
        },
        shadow_strength=0,
        strokes=[{"color": "#FF101317", "width": 3}],
        text="EXPLICIT MOTION",
    )
    motion_paths = {
        name: _render(f"gradient-explicit-{name}", motion_props, frame)
        for name, frame in FRAMES.items()
    }
    motion_metrics = {name: _image_metrics(path) for name, path in motion_paths.items()}
    motion_hashes = {item["sha256_pixels"] for item in motion_metrics.values()}
    result["gradient_explicit_motion"] = {
        "frames": motion_metrics,
        "different_pixel_hashes": len(motion_hashes) == len(FRAMES),
        "middle_more_opaque_than_ends": bool(
            motion_metrics["middle"]["nontransparent_pixels"]
            > motion_metrics["early"]["nontransparent_pixels"]
            and motion_metrics["middle"]["nontransparent_pixels"]
            > motion_metrics["late"]["nontransparent_pixels"]
        ),
    }

    combinations = {
        "solid": ("solid", [], "SOLID"),
        "gradient": ("gradient", [], "GRADIENT"),
        "stroke": ("solid", [{"color": "#FF101317", "width": 5}], "STROKE"),
        "gradient-stroke": (
            "gradient",
            [{"color": "#FFFFFFFF", "width": 6}, {"color": "#FF101317", "width": 3}],
            "GRADIENT + STROKE",
        ),
        "multiline": (
            "gradient",
            [{"color": "#FF101317", "width": 4}],
            "MULTI LINE\nSHADOW LAYER",
        ),
    }
    matrix_rows: list[tuple[str, list[Path]]] = []
    shadow_result: dict[str, object] = {}
    for label, (fill_kind, strokes, text) in combinations.items():
        progress(f"rendering shadow matrix: {label}")
        paths = []
        metrics: dict[str, object] = {}
        for strength in SHADOW_STRENGTHS:
            props = _props(
                fill_kind=fill_kind,
                motion={"mode": "none"},
                shadow_strength=strength,
                strokes=strokes,
                text=text,
            )
            path = _render(
                f"shadow-{label}-{strength:g}".replace(".", "p"),
                props,
                FRAMES["middle"],
            )
            paths.append(path)
            metrics[f"{strength:g}"] = _image_metrics(path)
        baseline = paths[0]
        comparisons = {
            f"{strength:g}": _foreground_comparison(baseline, path)
            for strength, path in zip(SHADOW_STRENGTHS[1:], paths[1:])
        }
        foreground_intact = all(
            item["changed_foreground_pixels"] == 0
            and item["darkened_foreground_pixels"] == 0
            for item in comparisons.values()
        )
        shadow_result[label] = {
            "frames": metrics,
            "comparisons_to_off": comparisons,
            "foreground_intact": foreground_intact,
        }
        matrix_rows.append((label, paths))

    result["shadow_matrix"] = shadow_result
    result["shadow_contact_sheet"] = str(_contact_sheet(matrix_rows))
    result["child_process_records"] = _child_records()
    result["pass"] = bool(
        result["gradient_motion_none"]["identical_pixel_hashes"]
        and result["gradient_explicit_motion"]["different_pixel_hashes"]
        and result["gradient_explicit_motion"]["middle_more_opaque_than_ends"]
        and all(item["foreground_intact"] for item in shadow_result.values())
    )
    target = OUTPUT / "result.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
