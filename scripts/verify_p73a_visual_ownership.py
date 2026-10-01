"""Formal headed P7.3A ownership and LIVE/Fidelity visual evidence.

This drives the production MainWindow and real mpv compositor. It is automated
headed evidence, never a claim of real-user acceptance.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get(
    "TWOBYTEASR_P73A_OUTPUT",
    str(ROOT / "tmp" / "p73a" / "visual-ownership"),
)).resolve()
MEDIA = ROOT / "tmp" / "p72" / "media" / "p72-av-8s.mp4"
PROJECT = OUTPUT / "p73a-visual-fixtures.2byteproj"
OUTPUT.mkdir(parents=True, exist_ok=True)
os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ["LOCALAPPDATA"] = str(OUTPUT / f"localappdata-{os.getpid()}")
os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"] = str(OUTPUT / "child-processes.jsonl")
Path(os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"]).unlink(missing_ok=True)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    pass

import psutil
from PIL import Image
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QImage, QPixmap, QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import moss_firered_pipeline
import subtitle_core
from twobyteasr import ui
from twobyteasr.advanced_preview import AdvancedPreviewResidency
from twobyteasr.p64_runtime_audit import _print_window, _window_bounds
from twobyteasr.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    SubtitleStyle,
    save_project,
)
from twobyteasr.style_recipe import (
    FillSpec,
    normalize_glow_contract,
    normalize_shadow_contract,
)
from twobyteasr.visual_runtime import VisualOwner


FIXTURES = (
    ("native", 500),
    ("gradient", 1_700),
    ("shadow", 2_900),
    ("glow", 4_100),
    ("combined", 5_300),
)
SAMPLE_OFFSETS_MS = (0, 16, 33, 50, 100, 500)


def progress(message: str) -> None:
    print(f"[p73a-visual] {message}", flush=True)


def pump(app: QApplication, milliseconds: int = 0) -> None:
    deadline = time.perf_counter() + max(0, milliseconds) / 1000.0
    while True:
        app.processEvents()
        if time.perf_counter() >= deadline:
            return
        QTest.qWait(min(5, max(1, round((deadline - time.perf_counter()) * 1000))))


def wait_until(app: QApplication, predicate, timeout: float, label: str) -> float:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        app.processEvents()
        if predicate():
            return (time.perf_counter() - started) * 1000.0
        QTest.qWait(5)
    raise TimeoutError(f"{label} was not ready within {timeout:.1f}s")


def descendants() -> set[int]:
    result = {os.getpid()}
    try:
        result.update(item.pid for item in psutil.Process().children(recursive=True))
    except (psutil.Error, OSError):
        pass
    return result


def gradient_fill() -> dict[str, object]:
    return FillSpec.linear([
        {"color": "#FF168BFF", "position": 0.0},
        {"color": "#FFFFD84A", "position": 1.0},
    ]).to_dict()


def advanced_recipe(
    name: str,
    *,
    shadow: float = 0.0,
    glow: float = 0.0,
    strokes: bool = False,
) -> dict[str, object]:
    outline: dict[str, object] = {
        "width": 0,
        "shadow": normalize_shadow_contract(shadow),
    }
    if strokes:
        outline["layers"] = [
            {"color": "#FF071018", "width": 5.0, "opacity": 1.0},
            {"color": "#FFFFFFFF", "width": 1.5, "opacity": 0.9},
        ]
    return {
        "name": name,
        "engine": "remotion",
        "typography": {},
        "colors": {"fill": gradient_fill()},
        "outline": outline,
        "background": {},
        "effects": {
            "glow": normalize_glow_contract({
                "enabled": glow > 0,
                "color": "#FF00FFFF",
                "radius": glow,
                "opacity": 0.72 if glow > 0 else 0.0,
                "intensity": 1.0,
            }),
        },
        "layout": {},
        "motion": {"mode": "none"},
        "ass": {},
    }


def fixture_project() -> Path:
    if not MEDIA.is_file():
        raise FileNotFoundError(MEDIA)
    styles = [
        SubtitleStyle(
            fixture, fixture.title(), font_family="Arial", font_size=104,
            bold=True, outline_width=0, shadow=0,
            position_x=960, position_y=540,
        )
        for fixture, _milliseconds in FIXTURES
    ]
    project = SubtitleProject(
        media=StudioMedia(
            path=str(MEDIA), display_name=MEDIA.name, duration_ms=8_000,
            width=640, height=360,
        ),
        cues=[
            StudioCue(
                fixture, milliseconds - 300, milliseconds + 700,
                "BLUE YELLOW", style_id=fixture,
            )
            for fixture, milliseconds in FIXTURES
        ],
        speakers=[StudioSpeaker("S00", "Speaker")],
        styles=styles,
        style_recipes={
            "gradient": advanced_recipe("Blue Yellow Gradient"),
            "shadow": advanced_recipe("Gradient Shadow", shadow=1.0),
            "glow": advanced_recipe("Gradient Cyan Glow", glow=10.0),
            "combined": advanced_recipe(
                "Gradient Stroke Shadow Glow",
                shadow=1.0,
                glow=10.0,
                strokes=True,
            ),
        },
        render_settings={"play_res_x": 1920, "play_res_y": 1080},
    )
    project.validate()
    return save_project(project, PROJECT)


def qimage_to_pil(image: QImage) -> Image.Image:
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    raw = bytes(converted.bits()[: converted.sizeInBytes()])
    return Image.frombuffer(
        "RGBA", (converted.width(), converted.height()), raw, "raw", "RGBA",
        converted.bytesPerLine(), 1,
    ).copy()


def alpha_bounds(image: QImage) -> list[int]:
    if image.isNull():
        return [0, 0, 0, 0]
    region = QRegion(QPixmap.fromImage(image).mask())
    return list(region.boundingRect().getRect())


def image_metrics(image: QImage) -> dict[str, object]:
    if image.isNull():
        return {
            "nonblank": False,
            "correct_gradient": False,
            "blue_pixels": 0,
            "yellow_pixels": 0,
            "cyan_pixels": 0,
            "dark_pixels": 0,
            "opaque_pixels": 0,
            "bounds": [0, 0, 0, 0],
        }
    blue = yellow = cyan = dark = opaque = 0
    for y in range(0, image.height(), 4):
        for x in range(0, image.width(), 4):
            color = image.pixelColor(x, y)
            if color.alpha() < 24:
                continue
            opaque += 1
            blue += color.blue() > color.red() + 20 and color.blue() > 130
            yellow += color.red() > 165 and color.green() > 125 and color.blue() < 165
            cyan += color.green() > color.red() + 30 and color.blue() > color.red() + 30
            dark += max(color.red(), color.green(), color.blue()) < 58
    return {
        "nonblank": opaque > 0,
        "correct_gradient": bool(blue > 2 and yellow > 2),
        "blue_pixels": int(blue),
        "yellow_pixels": int(yellow),
        "cyan_pixels": int(cyan),
        "dark_pixels": int(dark),
        "opaque_pixels": int(opaque),
        "bounds": alpha_bounds(image),
    }


def current_visual_image(page, cue_id: str) -> QImage:
    canvas = page.advanced_cue_overlay
    snapshot = getattr(canvas, "_snapshot", None)
    source = getattr(canvas, "_source", QPixmap())
    if (
        snapshot is None
        or snapshot.cue_id != cue_id
        or source.isNull()
        or not canvas.isVisible()
    ):
        return QImage()
    return source.toImage().convertToFormat(QImage.Format.Format_ARGB32)


def ownership_sample(page, cue_id: str, elapsed_ms: float) -> dict[str, object]:
    trace = page.subtitle_visibility_trace(reason="p73a_sample")
    canvas = page.advanced_cue_overlay
    snapshot = getattr(canvas, "_snapshot", None)
    source = getattr(canvas, "_source", QPixmap())
    if (
        snapshot is None
        or snapshot.cue_id != cue_id
        or source.isNull()
        or not canvas.isVisible()
    ):
        source = QPixmap()
    return {
        "elapsed_ms": round(float(elapsed_ms), 3),
        "owner": trace["foreground_owner"],
        "owner_count": trace["foreground_owner_count"],
        "native_desired": trace["native_track_visible"],
        "native_observed": trace["native_track_observed_visible"],
        "native_overlay_visible": trace["native_overlay_visible"],
        "live_visible": trace["advanced_live_visible"],
        "fidelity_visible": trace["advanced_fidelity_visible"],
        "overlay_ids": trace["mpv_compositor_overlay_ids"],
        "mpv_applied_visual_state": trace["mpv_applied_visual_state"],
        "pixels": {
            "nonblank": not source.isNull(),
            "correct_gradient": None,
        },
        "_pixmap": QPixmap(source),
    }


def save_samples(cue_id: str, samples: list[dict[str, object]]) -> None:
    for index, sample in enumerate(samples):
        pixmap = sample.pop("_pixmap")
        image = (
            pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
            if not pixmap.isNull() else QImage()
        )
        sample["pixels"] = image_metrics(image)
        target = OUTPUT / f"{cue_id}-t{index}-{round(sample['elapsed_ms'])}ms.png"
        if image.isNull():
            blank = QImage(640, 360, QImage.Format.Format_ARGB32)
            blank.fill(Qt.GlobalColor.transparent)
            blank.save(str(target))
        else:
            image.save(str(target))
        sample["path"] = str(target)


def capture_composite(window, page, name: str) -> str:
    hwnd = int(window.winId())
    bounds = _window_bounds(hwnd)
    base = _print_window(hwnd).convert("RGBA")
    canvas = page.advanced_cue_overlay
    if canvas.isVisible():
        layer = qimage_to_pil(canvas.grab().toImage())
        dpr = float(canvas.devicePixelRatioF() or 1.0)
        origin = canvas.mapToGlobal(QPoint(0, 0))
        base.alpha_composite(
            layer,
            dest=(
                round(origin.x() * dpr - bounds[0]),
                round(origin.y() * dpr - bounds[1]),
            ),
        )
    target = OUTPUT / f"{name}.png"
    base.convert("RGB").save(target)
    return str(target)


def advanced_visible(page, cue_id: str, *, after_overlay_sequence: int) -> bool:
    ownership = page._visual_ownership.current
    canvas = page.advanced_cue_overlay
    snapshot = getattr(canvas, "_snapshot", None)
    source = getattr(canvas, "_source", QPixmap())
    controller = page.video.controller
    applied = controller.applied_visual_state() if controller is not None else {}
    subtitle = applied.get("subtitle", {})
    overlays = applied.get("overlays", {})
    overlay = overlays.get(page.video.ADVANCED_OVERLAY_ID, {})
    return bool(
        ownership.cue_id == cue_id
        and ownership.owner in {
            VisualOwner.ADVANCED_LIVE, VisualOwner.ADVANCED_FIDELITY,
        }
        and ownership.foreground_owner_count == 1
        and subtitle.get("visible") is False
        and int(subtitle.get("sequence", 0)) > 0
        and overlay.get("visible") is True
        and int(overlay.get("sequence", 0)) > max(
            int(subtitle.get("sequence", 0)), int(after_overlay_sequence)
        )
        and page.video.ADVANCED_OVERLAY_ID
        in page.video.active_compositor_overlay_ids()
        and snapshot is not None
        and snapshot.cue_id == cue_id
        and canvas.isVisible()
        and not source.isNull()
    )


def sample_advanced(
    app: QApplication,
    window,
    page,
    cue_id: str,
    milliseconds: int,
) -> dict[str, object]:
    started = time.perf_counter()
    started_monotonic = time.perf_counter()
    controller = page.video.controller
    before_applied = (
        controller.applied_visual_state() if controller is not None else {}
    )
    before_overlay = before_applied.get("overlays", {}).get(
        page.video.ADVANCED_OVERLAY_ID, {}
    )
    before_overlay_sequence = int(before_overlay.get("sequence", 0))
    page._seek(milliseconds / 1000.0)
    samples: list[dict[str, object]] = []
    first_visible: dict[str, object] | None = None
    for target_ms in SAMPLE_OFFSETS_MS:
        while (time.perf_counter() - started) * 1000.0 < target_ms:
            app.processEvents()
            elapsed = (time.perf_counter() - started) * 1000.0
            if first_visible is None and advanced_visible(
                page, cue_id, after_overlay_sequence=before_overlay_sequence
            ):
                first_visible = ownership_sample(page, cue_id, elapsed)
            QTest.qWait(1)
        sample = ownership_sample(
            page, cue_id, (time.perf_counter() - started) * 1000.0,
        )
        samples.append(sample)
        if first_visible is None and advanced_visible(
            page, cue_id, after_overlay_sequence=before_overlay_sequence
        ):
            first_visible = ownership_sample(
                page, cue_id, (time.perf_counter() - started) * 1000.0,
            )
    wait_until(
        app,
        lambda: advanced_visible(
            page, cue_id, after_overlay_sequence=before_overlay_sequence
        ),
        2.0,
        f"{cue_id} LIVE",
    )
    if first_visible is None:
        first_visible = ownership_sample(
            page, cue_id, (time.perf_counter() - started) * 1000.0,
        )
    detected_elapsed_ms = float(first_visible["elapsed_ms"])
    overlay_applied = first_visible["mpv_applied_visual_state"]["overlays"][
        page.video.ADVANCED_OVERLAY_ID
    ]
    first_visible["detected_elapsed_ms"] = round(detected_elapsed_ms, 3)
    first_visible["elapsed_ms"] = round(
        max(
            0.0,
            (
                float(
                    overlay_applied.get(
                        "perf_counter", overlay_applied["monotonic"],
                    )
                )
                - started_monotonic
            )
            * 1000.0,
        ),
        3,
    )
    first_visible["timing_source"] = "mpv_overlay_ack"
    first_visible["previous_overlay_sequence"] = before_overlay_sequence
    first_pixmap = first_visible["_pixmap"]
    live_image = first_pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    live_owner = first_visible["owner"]
    live_overlay_ids = list(first_visible["overlay_ids"])
    composite_live_owner = page._visual_ownership.current.owner.value
    composite_live = capture_composite(window, page, f"{cue_id}-post-series-composite")
    wait_until(
        app,
        lambda: (
            page._advanced_preview_state.residency
            in {
                AdvancedPreviewResidency.FIDELITY,
                AdvancedPreviewResidency.CACHED_FIDELITY,
            }
            and page._visual_ownership.current.owner
            == VisualOwner.ADVANCED_FIDELITY
        ),
        120.0,
        f"{cue_id} Fidelity",
    )
    fidelity_ms = (time.perf_counter() - started) * 1000.0
    fidelity_image = current_visual_image(page, cue_id).copy()
    fidelity_overlay_ids = page.video.active_compositor_overlay_ids()
    composite_fidelity = capture_composite(window, page, f"{cue_id}-fidelity-composite")
    first_visible.pop("_pixmap")
    first_image = live_image
    first_visible["pixels"] = image_metrics(first_image)
    first_target = OUTPUT / f"{cue_id}-first-visible.png"
    first_image.save(str(first_target))
    first_visible["path"] = str(first_target)
    save_samples(cue_id, samples)
    return {
        "cue_id": cue_id,
        "first_visible": first_visible,
        "time_series": samples,
        "live_owner": live_owner,
        "live_overlay_ids": live_overlay_ids,
        "live_metrics": image_metrics(live_image),
        "live_path": str(OUTPUT / f"{cue_id}-live.png"),
        "fidelity_visible_ms": round(fidelity_ms, 3),
        "fidelity_owner": page._visual_ownership.current.owner.value,
        "fidelity_overlay_ids": fidelity_overlay_ids,
        "fidelity_metrics": image_metrics(fidelity_image),
        "fidelity_path": str(OUTPUT / f"{cue_id}-fidelity.png"),
        "live_composite": composite_live,
        "post_series_composite_owner": composite_live_owner,
        "fidelity_composite": composite_fidelity,
        "_live_image": live_image,
        "_fidelity_image": fidelity_image,
    }


def effect_difference(baseline: QImage, candidate: QImage) -> dict[str, int]:
    if baseline.isNull() or candidate.isNull() or baseline.size() != candidate.size():
        return {"extra_pixels": 0, "cyan_halo_pixels": 0, "dark_effect_pixels": 0, "foreground_corrupted": -1}
    extra = cyan = dark = corrupted = 0
    for y in range(0, baseline.height(), 2):
        for x in range(0, baseline.width(), 2):
            before = baseline.pixelColor(x, y)
            after = candidate.pixelColor(x, y)
            if before.alpha() == 0 and after.alpha() > 0:
                extra += 1
                cyan += after.green() > after.red() + 25 and after.blue() > after.red() + 25
                dark += max(after.red(), after.green(), after.blue()) < 70
            if before.alpha() == 255:
                before_rgb = before.getRgb()[:3]
                after_rgb = after.getRgb()[:3]
                if (
                    sum(before_rgb) - sum(after_rgb) > 24
                    or max(abs(before_rgb[index] - after_rgb[index]) for index in range(3)) > 16
                ):
                    corrupted += 1
    return {
        "extra_pixels": int(extra),
        "cyan_halo_pixels": int(cyan),
        "dark_effect_pixels": int(dark),
        "foreground_corrupted": int(corrupted),
    }


def strip_private_images(row: dict[str, object]) -> None:
    row.pop("_live_image", None)
    row.pop("_fidelity_image", None)


def main() -> int:
    project_path = fixture_project()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("2ByteASR P7.3A Visual Ownership")
    ui._register_bundled_fonts()
    app.setFont(ui._app_font())
    ui.apply_application_theme(app)
    result: dict[str, object] = {
        "schema": "2byteasr.p73a-visual-ownership.v1",
        "evidence_class": "FORMAL HEADED PRODUCTION MAINWINDOW",
        "real_user_click": False,
        "project": str(project_path),
        "media": str(MEDIA),
        "pid": os.getpid(),
    }
    window = None
    before_pids = descendants()
    traces: list[dict[str, object]] = []
    try:
        progress("constructing production MainWindow")
        window = ui.MainWindow([], subtitle_core, moss_firered_pipeline, None)
        window.setWindowTitle("2ByteASR P7.3A Visual Ownership")
        window.resize(1800, 1050)
        window.show()
        window.activateWindow()
        pump(app, 500)
        window.open_studio_project(project_path, source="p73a-visual-ownership")
        page = window.studio_page
        wait_until(
            app,
            lambda: page.video.controller is not None and page.video.controller.running,
            25.0,
            "real mpv",
        )
        wait_until(
            app,
            lambda: bool(page.video.controller._studio_subtitle_path),
            10.0,
            "Native ASS attached",
        )
        original_trace = page._studio_trace

        def capture_trace(event: str, **fields: object) -> None:
            traces.append({
                "event": str(event),
                "monotonic_ms": round(time.perf_counter() * 1000.0, 3),
                **fields,
            })
            original_trace(event, **fields)

        page._studio_trace = capture_trace
        page.follow_playhead_toggle.setChecked(True)
        page.video.set_paused(True)

        progress("validating Native owner")
        page._seek(FIXTURES[0][1] / 1000.0)
        wait_until(
            app,
            lambda: (
                page._visual_ownership.current.owner == VisualOwner.NATIVE
                and page.video.controller.observed_property("sub-visibility", None) is True
                and page.video.ADVANCED_OVERLAY_ID
                not in page.video.active_compositor_overlay_ids()
            ),
            5.0,
            "Native owner",
        )
        result["native"] = page.subtitle_visibility_trace(reason="p73a_native")

        advanced_rows: dict[str, dict[str, object]] = {}
        for cue_id, milliseconds in FIXTURES[1:]:
            progress(f"capturing {cue_id}")
            advanced_rows[cue_id] = sample_advanced(
                app, window, page, cue_id, milliseconds,
            )

        gradient_live = advanced_rows["gradient"]["_live_image"]
        gradient_fidelity = advanced_rows["gradient"]["_fidelity_image"]
        effect_rows = {}
        for cue_id in ("shadow", "glow", "combined"):
            effect_rows[cue_id] = {
                "live": effect_difference(
                    gradient_live, advanced_rows[cue_id]["_live_image"],
                ),
                "fidelity": effect_difference(
                    gradient_fidelity, advanced_rows[cue_id]["_fidelity_image"],
                ),
            }
        result["effect_differences"] = effect_rows
        result["advanced"] = advanced_rows
        result["trace"] = traces

        for row in advanced_rows.values():
            row["_live_image"].save(row["live_path"])
            row["_fidelity_image"].save(row["fidelity_path"])

        all_first_frames_correct = all(
            row["first_visible"]["pixels"]["correct_gradient"]
            for row in advanced_rows.values()
        )
        no_double_owner = all(
            sample["owner_count"] == 1
            and sample["owner"] in {"advanced_live", "advanced_fidelity"}
            and sample["native_desired"] is False
            and sample["native_overlay_visible"] is False
            and sample["mpv_applied_visual_state"]["subtitle"]["visible"] is False
            and sample["mpv_applied_visual_state"]["overlays"][
                page.video.ADVANCED_OVERLAY_ID
            ]["visible"] is True
            and sample["mpv_applied_visual_state"]["subtitle"]["sequence"]
            < sample["mpv_applied_visual_state"]["overlays"][
                page.video.ADVANCED_OVERLAY_ID
            ]["sequence"]
            for row in advanced_rows.values()
            for sample in [row["first_visible"]]
        )
        same_overlay_id = all(
            page.video.ADVANCED_OVERLAY_ID in row["live_overlay_ids"]
            and page.video.ADVANCED_OVERLAY_ID in row["fidelity_overlay_ids"]
            for row in advanced_rows.values()
        )
        effect_checks = {
            "shadow_live_pixels": effect_rows["shadow"]["live"]["dark_effect_pixels"] > 0,
            "shadow_fidelity_pixels": effect_rows["shadow"]["fidelity"]["dark_effect_pixels"] > 0,
            "glow_live_pixels": effect_rows["glow"]["live"]["cyan_halo_pixels"] > 0,
            "glow_fidelity_pixels": effect_rows["glow"]["fidelity"]["cyan_halo_pixels"] > 0,
            "combined_live_pixels": (
                effect_rows["combined"]["live"]["dark_effect_pixels"] > 0
                and effect_rows["combined"]["live"]["cyan_halo_pixels"] > 0
            ),
            "foreground_intact": all(
                values[renderer]["foreground_corrupted"] == 0
                for values in effect_rows.values()
                for renderer in ("live", "fidelity")
            ),
        }
        result["checks"] = {
            "native_owner_only": (
                result["native"]["foreground_owner"] == "native"
                and result["native"]["foreground_owner_count"] == 1
                and result["native"]["native_track_observed_visible"] is True
                and page.video.ADVANCED_OVERLAY_ID
                not in result["native"]["mpv_compositor_overlay_ids"]
            ),
            "all_first_frames_correct": all_first_frames_correct,
            "all_first_correct_lt_100": all(
                row["first_visible"]["elapsed_ms"] < 100.0
                for row in advanced_rows.values()
            ),
            "no_double_owner": no_double_owner,
            "live_fidelity_same_overlay_id": same_overlay_id,
            "live_fidelity_gradient_family": all(
                row["live_metrics"]["correct_gradient"]
                and row["fidelity_metrics"]["correct_gradient"]
                for row in advanced_rows.values()
            ),
            **effect_checks,
        }
        result["pass"] = all(result["checks"].values())
        for row in advanced_rows.values():
            strip_private_images(row)
    except Exception as exc:
        result["fatal_error"] = f"{type(exc).__name__}: {exc}"
        result["pass"] = False
    finally:
        if window is not None:
            window.close()
            window.deleteLater()
            pump(app, 800)
        remaining = descendants() - before_pids - {os.getpid()}
        result["remaining_child_pids"] = sorted(remaining)
        result["no_remaining_children"] = not remaining
        result["pass"] = bool(result.get("pass") and result["no_remaining_children"])
    target = OUTPUT / "runtime-result.json"
    target.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(target, flush=True)
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
