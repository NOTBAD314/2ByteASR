"""Capture actual ice-caption pixels and seek/export evidence, without model calls.

Run --quick first for a static review. A full run adds finite movies and runtime
comparisons. This script never rates the artwork or substitutes for Studio UI QA.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SIZE = (1920, 1080)
TEXT = "这块石头这么圆 一定能推吧？"
LAYERS = {
    "01-depth": ("ice-depth",),
    "02-volume": ("ice-volume", "ice-interior"),
    "03-glyph-shadow-bevel": ("ice-shadow", "ice-bevel"),
    "04-glyph-face": ("ice-copy",),
    "05-front-shell": ("ice-frost", "ice-shell"),
    "06-cracks": ("ice-cracks",),
    "07-rim-reflection": ("ice-rim", "ice-reflection"),
}
ALL_LAYERS = tuple(name for names in LAYERS.values() for name in names)
SELECTORS = [".ice-layout", ".ice-wiggle", ".ice-shiver", ".ice-body",
             ".ice-piece-0", *["." + name for name in ALL_LAYERS]]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf8")


def clean_text(text):
    return "".join(str(text).split())


def premultiplied(image):
    import numpy as np
    values = np.asarray(image.convert("RGBA"), dtype=np.float32)
    values[:, :, :3] *= values[:, :, 3:] / 255
    return values


def difference(a, b):
    import numpy as np
    delta = np.abs(premultiplied(a) - premultiplied(b))
    return {"mean": float(delta.mean()), "max": float(delta.max()),
            "alpha_max": float(delta[:, :, 3].max()),
            "pixels_over_one": int(np.count_nonzero(delta.max(axis=2) > 1))}


def padded_box(box, padding=24):
    return (max(0, box[0] - padding), max(0, box[1] - padding),
            min(SIZE[0], box[2] + padding), min(SIZE[1], box[3] + padding))


def union_box(boxes):
    boxes = [box for box in boxes if box]
    return (min(box[0] for box in boxes), min(box[1] for box in boxes),
            max(box[2] for box in boxes), max(box[3] for box in boxes)) if boxes else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--theme-json", type=Path, help="Already generated theme; provenance remains explicit")
    parser.add_argument("--source-origin", default="codex_authored_component_v7")
    parser.add_argument("--old-html", type=Path)
    parser.add_argument("--game-background", type=Path)
    parser.add_argument("--text", default=TEXT)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / "tmp"):
        raise ValueError("Output must stay within repository tmp")
    out.mkdir(parents=True, exist_ok=True)
    os.environ["TWOBYTEASR_TEST_ROOT"] = str(out / "isolation")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from twobyteasr.test_isolation import install
    install()
    from PIL import Image, ImageDraw, ImageFont
    from twobyteasr.caption_components import compose
    from twobyteasr.renderer_service import RendererJob, RendererService
    from twobyteasr.style_recipe import StyleRecipe
    from twobyteasr.theme_direction_preview import render_motion_preview
    from twobyteasr.web_theme import (WebThemeDocument, export_theme_archive,
                                    import_theme_archive, theme_archive_html)

    theme = (import_theme_archive(args.theme_json) if args.theme_json else
             WebThemeDocument.from_dict(dict(
                 name="冰河世纪 · 冰中封字", id="ice-age-encased-v7",
                 notes="本轮本地组件设计；此验收脚本不调用模型，不声明审美通过。",
                 **compose(dict(version=7, wiggle="weak", wiggleSeed=1703)),
             )).to_dict())
    old = (import_theme_archive(args.old_html) if args.old_html else
           WebThemeDocument.from_dict(dict(name="冰河世纪 · v6对照", id="ice-age-v6-control",
                                           **compose(dict(version=6)))).to_dict())
    # Comparison is explicitly normalized to the candidate's font identity/size.
    original_old_appearance = copy.deepcopy(old.get("appearance"))
    old["appearance"] = copy.deepcopy(theme["appearance"])
    write_json(out / "theme.json", theme)
    write_json(out / "old-comparison-theme.json", old)
    result = {"source_origin": args.source_origin, "external_model_calls_by_this_script": 0,
              "mode": "quick" if args.quick else "full", "canvas": list(SIZE),
              "text": args.text, "appearance": theme["appearance"],
              "old_original_appearance": original_old_appearance,
              "old_source": str(args.old_html) if args.old_html else "unchanged compose(version=6)",
              "checks": {}, "captures": {}, "unverified": [
                  "aesthetic approval (requires viewing actual frames and movies)",
                  "Studio adopt / ordinary subtitle restore / project save-reopen UI (separate audit)",
                  "new provider response and normal generation request (separate audit)",
                  "physical monitor playback and sound"],
              "note": "RGBA internal composition does not refract unknown background video."}
    source_paths = [ROOT / name for name in ("twobyteasr/caption_ice.py", "twobyteasr/caption_ice_legacy.py",
                    "twobyteasr/caption_components.py", "twobyteasr/motion_spec.py",
                    "renderer/src/webThemeMotion.js", "renderer/src/webThemeClock.js")]
    result["source_sha256"] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in source_paths if path.is_file()}
    result["expanded_theme_sha256"] = hashlib.sha256(
        json.dumps(theme, ensure_ascii=False, sort_keys=True).encode("utf8")).hexdigest()
    backgrounds = {name: Image.new("RGBA", SIZE, color) for name, color in
                   (("neutral", "#20262e"), ("light", "#e3e6e8"), ("dark", "#080c12"))}
    game = args.game_background or ROOT / "tmp/artifact-speaker-20260924/new-artwork-continue/game-frame.png"
    if game.is_file():
        with Image.open(game) as image:
            backgrounds["game"] = image.convert("RGBA").resize(SIZE)
        result["game_background"] = {"path": str(game.resolve()),
                                     "description": "Existing game livestream frame; original UI/chat/streamer artwork may remain"}
    else:
        result["unverified"].append("game background (no source image supplied or available)")
    try:
        label_font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 22)
    except OSError:
        label_font = ImageFont.load_default()

    service = RendererService()
    heroes = {}

    def save_result():
        result["runtime_checks_passed"] = all(result["checks"].values())
        result["failed_checks"] = [key for key, value in result["checks"].items() if not value]
        write_json(out / "result.json", result)

    def check(name, passed):
        result["checks"][name] = bool(passed)
        if not passed:
            print("CHECK FAILED:", name, flush=True)

    def html_for(item, text=None, duration=6):
        return theme_archive_html(item, sample_text=text if text is not None else args.text,
                                  duration_seconds=duration, auto_replay=False)

    def load(item, text=None, duration=6):
        html = html_for(item, text, duration)
        service.live_set(html, width=SIZE[0], height=SIZE[1])
        return html

    def frame(ms, destination=None):
        png = service.live_pause(cue_ms=ms, stage_ms=ms, timeout=20)
        image = Image.open(BytesIO(png)).convert("RGBA")
        if destination:
            destination.parent.mkdir(parents=True, exist_ok=True)
            image.save(destination)
        return image

    def diagnostic():
        return service._live_request({"type": "live_diagnostics", "selectors": SELECTORS,
                                      "include_fonts": True}, timeout=20)["diagnostics"]

    def semantic_check(diag, text):
        # Decorative copies legitimately repeat the line; do not join every text node.
        runs = diag.get("semantic_text_runs", [])
        combined = clean_text("".join(run["text"] for run in runs))
        wanted = clean_text(text)
        return bool(runs) and wanted in combined and not diag["script_errors"] and diag["fonts_ready"]

    def save_composites(image, folder, stem):
        for name, background in backgrounds.items():
            Image.alpha_composite(background, image).convert("RGB").save(folder / f"{stem}-{name}.png")

    def montage(images, labels, path, crop=None):
        # One common crop, at original pixel scale, preserves size comparison.
        size = (crop[2] - crop[0], crop[3] - crop[1]) if crop else SIZE
        canvas = Image.new("RGB", (size[0], (size[1] + 36) * len(images)), "#20262e")
        draw = ImageDraw.Draw(canvas)
        for index, (image, label) in enumerate(zip(images, labels)):
            top = index * (size[1] + 36)
            draw.text((12, top + 6), label, fill="#f0f2f5", font=label_font)
            composite = Image.alpha_composite(backgrounds["neutral"], image).convert("RGB")
            canvas.paste(composite.crop(crop) if crop else composite, (0, top + 36))
        canvas.save(path)

    try:
        print("Capturing original-size old/new hero frames", flush=True)
        for name, item in (("old-v6", old), ("new-v7", theme)):
            folder = out / name
            folder.mkdir(exist_ok=True)
            html = load(item)
            (folder / "theme.html").write_text(html, "utf8")
            image = frame(1500, folder / "hero-rgba-1920x1080.png")
            heroes[name] = image
            save_composites(image, folder, "hero")
            diag = diagnostic()
            write_json(folder / "hero-dom.json", diag)
            box = image.getchannel("A").getbbox()
            result["captures"][name] = {"bbox": box, "rgba": str(folder / "hero-rgba-1920x1080.png"),
                                         "semantic_runs": diag.get("semantic_text_runs", [])}
            check(name + "-semantic-text-font-ready", semantic_check(diag, args.text))
            check(name + "-external-canvas-transparent", box is not None and box[0] > 0 and box[1] > 0
                  and box[2] < SIZE[0] and box[3] < SIZE[1])
        common = padded_box(union_box([image.getchannel("A").getbbox() for image in heroes.values()]))
        montage(list(heroes.values()), ["OLD v6 / same text, font, size", "NEW v7 / same text, font, size"],
                out / "old-new-full-frame.png")
        montage(list(heroes.values()), ["OLD v6 / 1:1 common crop", "NEW v7 / 1:1 common crop"],
                out / "old-new-subject-1to1.png", common)
        for name, image in heroes.items():
            crop = image.crop(common)
            crop.save(out / name / "subject-rgba-1to1.png")
            Image.alpha_composite(Image.new("RGBA", crop.size, "#20262e"), crop).convert("RGB").save(
                out / name / "subject-neutral-1to1.png")
            # Pixel enlargement is explicitly labeled; this is not the normal-size approval image.
            detail_box = (max(common[0], (common[0] + common[2]) // 2 - 230), common[1],
                          min(common[2], (common[0] + common[2]) // 2 + 230), common[3])
            detail = image.crop(detail_box)
            detail = Image.alpha_composite(Image.new("RGBA", detail.size, "#20262e"), detail)
            detail.resize((detail.width * 3, detail.height * 3), Image.Resampling.NEAREST).save(
                out / name / "glyph-detail-3x.png")

        print("Capturing material layers in the same coordinate system", flush=True)
        layers_folder = out / "layers"
        layers_folder.mkdir(exist_ok=True)
        layer_images = []
        for name, visible in LAYERS.items():
            item = copy.deepcopy(theme)
            # A turbulence filter can generate paint without SourceGraphic.
            # Remove other layer boxes from painting, not just their glyph visibility.
            hidden = [layer for layer in ALL_LAYERS if layer not in visible]
            item["cueCss"] += "\n" + ",".join("." + layer for layer in hidden) + "{display:none!important}"
            load(item)
            image = frame(1500, layers_folder / (name + "-rgba.png"))
            layer_images.append(image)
            Image.alpha_composite(backgrounds["neutral"], image).convert("RGB").save(
                layers_folder / (name + "-neutral.png"))
            write_json(layers_folder / (name + "-dom.json"), diagnostic())
        montage(layer_images, list(LAYERS), layers_folder / "layer-sheet-1to1.png", common)
        result["layers"] = {name: list(classes) for name, classes in LAYERS.items()}
        if not args.theme_json:
            result["wiggle_variants"] = []
            for level, label in (("off", "关闭"), ("weak", "弱"), ("medium", "中"), ("strong", "强")):
                variant = WebThemeDocument.from_dict(dict(
                    name="冰中封字 · 抖动" + label, id="ice-encased-wiggle-" + level,
                    notes="现有v7组件编译的抖动档位；独立归档，不覆盖已采用主题。",
                    **compose(dict(version=7, wiggle=level, wiggleSeed=1703)),
                )).to_dict()
                path = export_theme_archive(variant, out / "wiggle-archives", sample_text=args.text)
                check("wiggle-archive-roundtrip-" + level, import_theme_archive(path) == variant)
                result["wiggle_variants"].append(dict(level=level, label=label, archive=str(path),
                    verification="compiled and archive reopened; weak is fully rendered in this run",
                    samplers=[track for track in variant["motionSpec"]["tracks"] if track.get("wiggle")]))
        save_result()
        if args.quick:
            result["unverified"].extend(["full 6s/1.5s motion (quick mode)", "random/reverse seek (quick mode)",
                                         "production render parity (quick mode)", "archive reopen (quick mode)"])
        else:
            print("Running the normal AI draft production preflight (including composed text probes)", flush=True)
            from twobyteasr.theme_draft import ThemeDraft, validate_draft_frames
            draft = ThemeDraft("encased-ice-review", 1, "ice-review", args.text,
                               provider="local-review", model="").with_theme(theme)
            result["production_draft_validation"] = validate_draft_frames(
                draft, out / "production-draft-validation", service=service,
                deadline_seconds=120, cancel_check=lambda: False)
            check("normal-production-draft-preflight", True)
            print("Capturing finite movement, substitutions, and seek/export comparisons", flush=True)
            load(theme)
            stamps = [0, 80, 160, 320, 560, 1500, 2780, 3404.8, 3440, 3510, 3584.8,
                      4200, 5620, 5780, 5900, 5999, 6000]
            def stamp_name(ms):
                return f"{ms:07.1f}".replace(".", "p")
            samples = {}
            for ms in stamps:
                samples[ms] = frame(ms, out / "timeline" / f"{stamp_name(ms)}.png")
                write_json(out / "timeline" / f"{stamp_name(ms)}-dom.json", diagnostic())
            check("first-frame-transparent", samples[0].getchannel("A").getbbox() is None)
            check("terminal-frame-transparent", samples[6000].getchannel("A").getbbox() is None)
            montage([samples[t] for t in (80, 160, 320, 560, 1500, 5780, 5900)],
                    [f"{t} ms / same crop" for t in (80, 160, 320, 560, 1500, 5780, 5900)],
                    out / "timeline" / "motion-sheet-1to1.png", common)
            seek_order = stamps[:]
            random.Random(260926).shuffle(seek_order)
            seek_order += list(reversed(stamps))
            result["seek_comparisons"] = []
            for index, ms in enumerate(seek_order):
                actual = frame(ms)
                delta = difference(actual, samples[ms])
                passed = delta["mean"] < .01 and delta["max"] <= 16 and delta["alpha_max"] <= 2
                result["seek_comparisons"].append(dict(index=index, time_ms=ms, passed=passed, **delta))
                if not passed:
                    actual.save(out / "timeline" / f"seek-{index:02}-{stamp_name(ms)}-actual.png")
                    write_json(out / "timeline" / f"seek-{index:02}-{stamp_name(ms)}-dom.json", diagnostic())
            check("random-and-reverse-seek-repeatable", all(row["passed"] for row in result["seek_comparisons"]))

            # Disable only the continuous wiggle sampler; authored entry/exit and cold burst stay intact.
            off = copy.deepcopy(theme)
            samplers = [track for track in off.get("motionSpec", {}).get("tracks", []) if track.get("wiggle")]
            result["wiggle_sampler_contract"] = copy.deepcopy(samplers)
            if not samplers:
                raise ValueError("No motionSpec tracks with wiggle in candidate; cannot honestly compare wiggle on/off")
            for sampler in samplers:
                if sampler.get("selector") == ".ice-wiggle":
                    sampler["wiggle"]["intensity"] = 0
            load(off)
            off_image = frame(2780, out / "wiggle-off-rgba.png")
            off_diag = diagnostic()
            load(theme)
            on_image = frame(2780, out / "wiggle-on-rgba.png")
            on_diag = diagnostic()
            montage([off_image, on_image], ["WIGGLE OFF at 2780 ms", "WIGGLE ON at 2780 ms"],
                    out / "wiggle-off-on.png", common)
            result["wiggle_comparison"] = {"time_ms": 2780, "pixel_difference": difference(off_image, on_image),
                                            "off_roots": off_diag["roots"], "on_roots": on_diag["roots"]}
            check("wiggle-affects-visible-caption-pixels", result["wiggle_comparison"]["pixel_difference"]["pixels_over_one"] > 20)

            cases = [("replacement", 6000, "寒风把最后一句话也封进了冰里"),
                     ("explicit-lines", 3000, "第一行留在冰里\n第二行仍然清楚"),
                     ("long-wrap", 6000, "就算这句话很长也应该完整呈现每一个中文字，不应裁掉后半句，这是最后六个字"),
                     ("short", 1500, args.text), ("ultrashort", 500, "冻住了")]
            result["replacement_cases"] = []
            load(theme)
            for name, duration_ms, caption in cases:
                service.live_text(text=caption, duration_ms=duration_ms)
                image = frame(duration_ms / 2, out / "text-cases" / (name + "-rgba.png"))
                diag = diagnostic()
                passed = semantic_check(diag, caption)
                check(name + "-semantic-replacement", passed)
                runs = diag.get("semantic_text_runs", [])
                in_bounds = all(run["rect"][0] >= 0 and run["rect"][1] >= 0
                                and sum(run["rect"][::2]) <= SIZE[0]
                                and sum(run["rect"][1::2]) <= SIZE[1] for run in runs)
                check(name + "-text-in-viewport", in_bounds)
                save_composites(image, out / "text-cases", name)
                result["replacement_cases"].append({"name": name, "duration_ms": duration_ms,
                                                      "text": caption, "diagnostics": diag})
                check(name + "-terminal-clear", frame(duration_ms).getchannel("A").getbbox() is None)

            archive = export_theme_archive(theme, out / "archive", sample_text=args.text)
            reopened = import_theme_archive(archive)
            check("archive-roundtrip-source-and-motion", reopened == theme)
            load(reopened)
            reopened_image = frame(1500, out / "archive-reopened-rgba.png")
            result["archive_reopen_difference"] = difference(reopened_image, heroes["new-v7"])
            check("archive-reopen-pixels", result["archive_reopen_difference"]["mean"] < .01)
            result["archive"] = str(archive)

            recipe = StyleRecipe(name=theme["name"], engine="remotion", web_theme=theme).to_dict()
            props = dict(schemaVersion=1, width=1920, height=1080, fps=30, durationInFrames=180,
                         cues=[dict(id="ice-review", text=args.text, startMs=0, endMs=6000,
                                    styleId="theme", visual=recipe)], recipes={"theme": recipe})
            jobs = [RendererJob(str(out / f"production-frame-{index}.png"), props, index,
                                job_kind="production") for index in (45, 106, 174)]
            rendered = service.render(jobs, timeout=180)
            check("production-render-status", rendered.status == "OK")
            result["production_parity"] = []
            load(theme)
            for job in jobs:
                live = frame(job.frame * 1000 / 30, out / f"live-production-frame-{job.frame}.png")
                with Image.open(job.output) as exported:
                    delta = difference(live, exported)
                result["production_parity"].append(dict(frame=job.frame, **delta))
                check(f"live-production-parity-{job.frame}", delta["mean"] < .05)
            save_result()

            movies = out / "movies"
            movies.mkdir(exist_ok=True)
            result["movies"] = {}
            for name, duration_ms in (("six-second", 6000), ("short-1p5-second", 1500)):
                print("Rendering", name, flush=True)
                result["movies"][name] = render_motion_preview(
                    service, html_for(theme, duration=duration_ms / 1000), movies, name,
                    duration_ms=duration_ms, progress=lambda message: print(message, flush=True))
                movie = result["movies"][name]
                last_index = movie["frame_count"] - 1
                last_path = Path(movie["transparent_frames"]) / f"{last_index:04d}.png"
                with Image.open(last_path) as last_frame:
                    alpha = last_frame.convert("RGBA").getchannel("A")
                    movie["last_encoded_source_frame"] = dict(index=last_index,
                        time_ms=last_index * 1000 / movie["fps"], rgba_path=str(last_path),
                        alpha_max=alpha.getextrema()[1], alpha_bbox=alpha.getbbox())
                check(name + "-last-encoded-rgba-frame-clear", movie["last_encoded_source_frame"]["alpha_max"] == 0)
                # Decode the actual MP4, preserving the distinction that MP4 has
                # opaque neutral pixels while its corresponding RGBA source is empty.
                from twobyteasr.audio_engine import studio_ffmpeg_path
                from twobyteasr.processes import run_hidden_subprocess
                run_hidden_subprocess([str(studio_ffmpeg_path()), "-v", "error", "-i", movie["video"],
                    "-f", "null", "-"], check=True, capture_output=True, timeout=45,
                    purpose="decode finite ice review movie")
                movie["full_mp4_decode"] = "passed"
                save_result()
            result["movie_resolution_note"] = "Existing review renderer: 960x540 full RGBA frames; hero/layers/export are 1920x1080."
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["checks"]["script-completed"] = False
        raise
    finally:
        service.shutdown()
        final_sha = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in source_paths if path.is_file()}
        result["source_changed_during_run"] = final_sha != result["source_sha256"]
        if result["source_changed_during_run"]:
            result["unverified"].append("Source changed while capturing; rerun before final acceptance")
        save_result()
        # A local review index makes actual-size images and videos easy to inspect.
        import html as html_module
        cards = []
        variants = result.get("wiggle_variants", [])
        if variants:
            links = []
            for variant in variants:
                relative = Path(variant["archive"]).relative_to(out).as_posix()
                links.append('<li>' + html_module.escape(variant["label"]) + ': <a href="'
                    + html_module.escape(relative + "/theme.html", quote=True) + '">transparent theme</a> · <a href="'
                    + html_module.escape(relative + "/theme.json", quote=True) + '">importable theme JSON</a></li>')
            cards.append('<p>Wiggle choices, compiled by the existing v7 component (independent archives):</p><ul>'
                         + "".join(links) + '</ul>')
        for path in (out / "new-v7/hero-neutral.png", out / "old-new-subject-1to1.png",
                     out / "new-v7/glyph-detail-3x.png", out / "layers/layer-sheet-1to1.png",
                     out / "new-v7/hero-light.png", out / "new-v7/hero-dark.png", out / "new-v7/hero-game.png",
                     out / "wiggle-off-on.png", out / "timeline/motion-sheet-1to1.png"):
            if path.exists():
                relative = path.relative_to(out).as_posix()
                cards.append(f'<figure><figcaption>{html_module.escape(relative)}</figcaption><a href="{relative}"><img src="{relative}"></a></figure>')
        for movie in result.get("movies", {}).values():
            relative = Path(movie["video"]).relative_to(out).as_posix()
            cards.append(f'<figure><figcaption>{html_module.escape(relative)}</figcaption><video controls loop src="{relative}"></video></figure>')
        (out / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>Encased ice review</title>'
            '<style>body{background:#161b22;color:#e7edf5;font:16px system-ui;margin:24px}figure{margin:24px 0}img,video{max-width:100%;height:auto}figcaption{margin:8px 0}a{color:#9dcfff}</style>'
            '<h1>Encased ice: actual render evidence</h1><p>Open an image for its original size. The page scales to the browser width.</p>'
            '<p>Runtime evidence does not constitute aesthetic approval. No model request was made by this script.</p>'
            '<p><a href="result.json">Result / measured comparisons / unverified items</a></p>' + "".join(cards), "utf8")
    print(json.dumps({"output": str(out), "runtime_checks_passed": result["runtime_checks_passed"],
                      "failed_checks": result["failed_checks"]}, ensure_ascii=False), flush=True)
    return 0 if result["runtime_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
