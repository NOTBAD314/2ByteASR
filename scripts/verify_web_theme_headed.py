"""Headed visual verification for web visual themes (2byte.web-visual-theme v1).

Renders the built-in Balatro Joker theme at entrance / hold / exit moments
plus one frame with an overridden appearance token set, then checks the
frames are non-empty and visually differentiated (entrance vs hold) at the
pixel level. Produces PNGs under tmp/web-theme-verify/ for human review.

Run:  .venv-main/Scripts/python.exe scripts/verify_web_theme_headed.py
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from twobyteasr.renderer_service import GLOBAL_RENDERER_SERVICE, RendererJob  # noqa: E402
from twobyteasr.web_theme import builtin_web_themes  # noqa: E402

OUT_DIR = ROOT / "tmp" / "web-theme-verify"
WIDTH, HEIGHT, FPS = 1920, 1080, 30
CUE_SECONDS = 4.0


def composition_props(theme: dict, text: str, appearance: dict | None = None) -> dict:
    payload = dict(theme)
    if appearance:
        payload["appearance"] = appearance
    return {
        "schemaVersion": 1,
        "width": WIDTH,
        "height": HEIGHT,
        "fps": FPS,
        "durationInFrames": int(CUE_SECONDS * FPS),
        "cues": [{
            "id": "verify-cue",
            "text": text,
            "speaker": "主播",
            "startMs": 0,
            "endMs": int(CUE_SECONDS * 1000),
            "styleId": "verify-style",
            "visual": {"webTheme": payload},
        }],
        "recipes": {"verify-style": {"webTheme": payload}},
    }


def stats(png_path: Path) -> dict:
    from PIL import Image

    image = Image.open(png_path).convert("RGBA")
    if image.size != (WIDTH, HEIGHT):
        raise SystemExit(f"unexpected frame size: {image.size}")
    pixels = image.getdata()
    total = len(pixels)
    opaque = 0
    warm = 0
    redish = 0
    for r, g, b, alpha in pixels:
        if alpha > 40:
            opaque += 1
            if r > 170 and g > 120 and b < 140:
                warm += 1
            if r > 120 and g < 110 and b < 110:
                redish += 1
    return {
        "coverage": opaque / total,
        "warm": warm / total,
        "red": redish / total,
    }


def pixel_diff(path_a: Path, path_b: Path) -> int:
    from PIL import Image, ImageChops

    image_a = Image.open(path_a).convert("RGBA")
    image_b = Image.open(path_b).convert("RGBA")
    return sum(1 for values in ImageChops.difference(image_a, image_b).getdata() if any(v > 8 for v in values))


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(["verify-web-theme"])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    theme = builtin_web_themes()["balatro-joker"].to_dict()
    base_appearance = {
        "fontFamily": "Microsoft YaHei UI",
        "fontSize": 66,
        "bold": True,
        "italic": False,
        "color": "#FFE9B8",
        "strokeColor": "#5C1408",
        "strokeWidth": 5.0,
        "stroke2Color": "#FFD86B",
        "stroke2Width": 1.5,
        "letterSpacing": 1.0,
    }
    blue_appearance = dict(base_appearance, color="#9FD8FF", strokeColor="#0B2A55", fontSize=52)

    moments = {
        "entrance": (0.18, composition_props(theme, "这就是小丑牌字幕！", base_appearance)),
        "hold": (1.6, composition_props(theme, "这就是小丑牌字幕！", base_appearance)),
        "exit": (CUE_SECONDS - 0.12, composition_props(theme, "这就是小丑牌字幕！", base_appearance)),
        "hold-blue-tokens": (1.6, composition_props(theme, "改字体颜色后的样子", blue_appearance)),
    }

    jobs = []
    for name, (seconds, props) in moments.items():
        frame = max(0, min(int(CUE_SECONDS * FPS) - 1, round(seconds * FPS)))
        jobs.append(RendererJob(
            str(OUT_DIR / f"balatro-{name}.png"),
            props,
            frame,
            job_kind="diagnostic",
            cue_id="verify-cue",
            project_id="web-theme-verify",
        ))
    started = time.monotonic()
    result = GLOBAL_RENDERER_SERVICE.render(
        jobs,
        render_type="still",
        resolution=(WIDTH, HEIGHT),
        batch_group="web-theme-verify",
        timeout=240.0,
    )
    print(f"render wall time: {time.monotonic() - started:.1f}s")

    failures = [] if str(result.status).upper() in {"OK", "DONE"} else [f"renderer result status={result.status}"]
    for job in jobs:
        produced = Path(job.output).is_file() and Path(job.output).stat().st_size > 0
        print(f"{Path(job.output).name}: produced={produced}")
        if not produced:
            failures.append(f"{job.output}: not produced")

    metrics = {}
    for name in moments:
        path = OUT_DIR / f"balatro-{name}.png"
        if path.is_file():
            metrics[name] = stats(path)
            print(f"  {name}: {metrics[name]}")

    checks = []
    hold = metrics.get("hold", {})
    entrance = metrics.get("entrance", {})
    blue = metrics.get("hold-blue-tokens", {})
    checks.append(("hold frame has visible pixels", hold.get("coverage", 0) > 0.02))
    checks.append(("card red visible in hold", hold.get("red", 0) > 0.001))
    checks.append(("warm gold accents visible", hold.get("warm", 0) > 0.0))
    entrance_hold_diff = pixel_diff(OUT_DIR / "balatro-entrance.png", OUT_DIR / "balatro-hold.png")
    hold_exit_diff = pixel_diff(OUT_DIR / "balatro-hold.png", OUT_DIR / "balatro-exit.png")
    print(f"  entrance-vs-hold differing pixels: {entrance_hold_diff}")
    print(f"  hold-vs-exit differing pixels: {hold_exit_diff}")
    checks.append(("entrance differs from hold (card sweep)", entrance_hold_diff > 2000))
    checks.append(("exit differs from hold (card flip-out)", hold_exit_diff > 2000))
    blue_diff = pixel_diff(OUT_DIR / "balatro-hold.png", OUT_DIR / "balatro-hold-blue-tokens.png")
    print(f"  token-override differing pixels: {blue_diff}")
    checks.append(("token override changes pixels", blue_diff > 2000))

    for label, ok in checks:
        print(("PASS  " if ok else "FAIL  ") + label)
        if not ok:
            failures.append(label)

    if failures:
        print("\nVERIFY FAILED:")
        for item in failures:
            print(" -", item)
        return 1
    print("\nVERIFY OK — inspect PNGs in tmp/web-theme-verify/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
