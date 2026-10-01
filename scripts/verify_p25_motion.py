"""Headless visual smoke check for the P25.0-P25.2 motion surfaces."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402
from PIL import Image, ImageChops  # noqa: E402

import twobyteasr.ui as ui  # noqa: E402
from twobyteasr.effect_dsl import builtin_effects  # noqa: E402
from twobyteasr.ass_compiler import compile_ass  # noqa: E402
from twobyteasr.studio_project import (  # noqa: E402
    StudioCue,
    StudioMedia,
    SubtitleProject,
    save_project,
)
from twobyteasr.studio_ui import SubtitleStudioPage  # noqa: E402


def main() -> int:
    output = ROOT / "tmp" / "p25-acceptance"
    output.mkdir(parents=True, exist_ok=True)
    os.environ["LOCALAPPDATA"] = str(output / "local")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setStyleSheet(ui.APP_QSS)
    ui._register_bundled_fonts()
    app.setFont(ui._app_font())
    page = SubtitleStudioPage()
    project_path = output / "synthetic.2byteproj"
    ffmpeg = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    subprocess.run(
        [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "color=c=black:s=1280x720:r=30:d=4", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "synthetic.mp4"],
        cwd=output, check=True,
    )
    save_project(
        SubtitleProject(
            media=StudioMedia(path=str(output / "synthetic.mp4"), duration_ms=4000, width=1280, height=720),
            cues=[StudioCue("sample", 500, 3500, "示例字幕：高能时刻")],
            render_settings={"play_res_x": 1280, "play_res_y": 720},
        ),
        project_path,
    )
    page.video.load = lambda *_args, **_kwargs: None
    page._generate_waveform = lambda *_args, **_kwargs: None
    page.resize(1500, 1000)
    page.show()
    page.open_project(project_path)
    page.context_drawer.setCurrentIndex(2)
    page._show_context_panel()
    page.motion_preset.setCurrentIndex(page.motion_preset.findData("quick_pop"))
    app.processEvents()
    scroll = page.context_drawer.widget(2)
    if isinstance(scroll, QScrollArea):
        scroll.ensureWidgetVisible(page.motion_preset, 8, 8)
    app.processEvents()
    screenshot = output / "motion-panel.png"
    pixmap = page.grab()
    if pixmap.isNull() or not pixmap.save(str(screenshot), "PNG"):
        raise RuntimeError(f"could not save {screenshot}")
    report = {
        "motion_presets": [page.motion_preset.itemData(index) for index in range(page.motion_preset.count())],
        "selected": page.effect_preset.currentData(),
        "entry_duration_ms": page.effect_duration.value(),
        "strength": page.effect_strength.currentData(),
        "curve": page.effect_curve.currentData(),
        "advanced_hidden_by_default": page.motion_advanced.isHidden(),
        "native_effect_count": len(builtin_effects()),
        "screenshot": str(screenshot),
    }
    ass_path = output / "preview.ass"
    ass_path.write_text(compile_ass(page.project), encoding="utf-8")
    samples = {"entry": 0.50, "peak": 0.61, "hold": 1.00, "exit": 3.45}
    frame_metrics = {}
    for name, seconds in samples.items():
        frame = output / f"motion-{name}.png"
        subprocess.run(
            [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
             "-i", "synthetic.mp4", "-ss", str(seconds), "-vf", "ass=preview.ass",
             "-frames:v", "1", frame.name],
            cwd=output, check=True,
        )
        image = Image.open(frame).convert("L")
        mask = image.point(lambda value: 255 if value > 20 else 0)
        bbox = ImageChops.difference(mask, Image.new("L", mask.size)).getbbox()
        frame_metrics[name] = {
            "bbox": list(bbox or (0, 0, 0, 0)),
            "width": 0 if bbox is None else bbox[2] - bbox[0],
            "luma_sum": sum(value * count for value, count in enumerate(image.histogram())),
            "frame": str(frame),
        }
    report["libass_frames"] = frame_metrics
    if not (
        frame_metrics["entry"]["width"] < frame_metrics["peak"]["width"]
        and frame_metrics["peak"]["width"] > frame_metrics["hold"]["width"]
        and frame_metrics["exit"]["luma_sum"] < frame_metrics["hold"]["luma_sum"]
    ):
        raise RuntimeError(f"libass motion frame check failed: {frame_metrics}")
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    page.close_page()
    page.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
