"""Capture P5.2 naming, editor, fill, export presets, and encoder matrix."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_ui import FillEditorDialog, SubtitleStudioPage
from twobyteasr.studio_render import (
    RenderJob,
    RenderSettings,
    load_encoder_capabilities,
    probe_encoder_detail,
    run_render_job,
    scan_encoder_capabilities,
    VIDEO_ENCODERS,
)
from twobyteasr.ass_compiler import compile_ass
from twobyteasr.studio_project import load_project


SHOTS = ROOT / "tmp" / "p52-accept"
SHOTS.mkdir(parents=True, exist_ok=True)
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"


def pump(app, ms=120):
    deadline = time.perf_counter() + ms / 1000
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.01)


def grab(widget, name: str) -> Path:
    target = SHOTS / name
    pixmap = widget.grab()
    if pixmap.isNull() or not pixmap.save(str(target), "PNG"):
        raise RuntimeError(name)
    return target


def write_encoder_matrix() -> dict:
    payload = scan_encoder_capabilities(FFMPEG)
    matrix = {}
    for codec, names in VIDEO_ENCODERS.items():
        for name in names:
            detail = (payload.get("probes") or {}).get(name) or probe_encoder_detail(str(FFMPEG), name)
            listed = name in set(payload.get("video_encoders") or [])
            status = "AVAILABLE / functional" if detail.get("functional") else (
                "LISTED / probe failed" if listed else "UNAVAILABLE"
            )
            matrix[name] = {
                "codec": codec,
                "status": status,
                "listed": listed,
                "functional": bool(detail.get("functional")),
                "returncode": detail.get("returncode"),
                "frame_size": detail.get("frame_size"),
                "stderr": str(detail.get("stderr") or "")[:400],
                "elapsed_ms": detail.get("elapsed_ms"),
                "driver": detail.get("driver") or payload.get("nvidia_driver") or "",
            }
    (SHOTS / "encoder-matrix.json").write_text(
        json.dumps({"matrix": matrix, "probe_frame_size": payload.get("probe_frame_size"),
                    "ffmpeg": payload.get("ffmpeg_version"), "hwaccels": payload.get("hwaccels")},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("encoder matrix")
    for name, row in matrix.items():
        print(f"  {name:14} {row['status']}")
    return matrix


def _short_media(tmp: Path) -> tuple[Path, Path]:
    media = tmp / "bench.mp4"
    if not media.is_file():
        subprocess.run(
            [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=black:s=1280x720:r=24",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
             "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(media)],
            check=True,
        )
    ass = tmp / "bench.ass"
    ass.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,42,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,24,1\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:01.80,Default,,0,0,0,,P52 bench\n",
        encoding="utf-8",
    )
    return media, ass


def bench(matrix: dict) -> None:
    tmp = SHOTS / "bench"
    tmp.mkdir(exist_ok=True)
    media, ass = _short_media(tmp)
    rows = []
    jobs = [("libx264", "software-h264.mp4")]
    if matrix.get("h264_nvenc", {}).get("functional"):
        jobs.append(("h264_nvenc", "hardware-h264.mp4"))
    if matrix.get("hevc_nvenc", {}).get("functional"):
        jobs.append(("hevc_nvenc", "hardware-hevc.mp4"))
    if matrix.get("av1_nvenc", {}).get("functional"):
        jobs.append(("av1_nvenc", "hardware-av1.mp4"))
    for encoder, name in jobs:
        output = tmp / name
        if output.exists():
            output.unlink()
        codec = "hevc" if "hevc" in encoder else "av1" if "av1" in encoder else "h264"
        started = time.perf_counter()
        settings = RenderSettings(
            codec=codec,
            encoder=encoder,
            quality_mode="crf" if encoder.startswith("lib") else "cq",
            quality=20,
            width=1280,
            height=720,
            fps=24,
        )
        run_render_job(
            FFMPEG,
            RenderJob(str(media), str(ass), str(output), settings, overwrite_existing=True),
        )
        elapsed = time.perf_counter() - started
        size = output.stat().st_size if output.is_file() else 0
        rows.append({
            "encoder": encoder, "codec": codec, "resolution": "1280x720", "duration": 2,
            "wall_s": round(elapsed, 3), "realtime_factor": round(2 / max(0.001, elapsed), 3),
            "file_bytes": size, "quality": 20,
        })
        print("bench", encoder, f"{elapsed:.2f}s", size)
    (SHOTS / "native-benchmark.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    matrix = write_encoder_matrix()
    try:
        bench(matrix)
    except Exception as exc:
        print("bench failed", exc)
        (SHOTS / "native-benchmark.json").write_text(json.dumps({"error": str(exc)}), encoding="utf-8")

    page = SubtitleStudioPage()
    page.show()
    pump(app, 160)
    page.show_project_hub()
    pump(app, 160)
    page.resize(1600, 960)
    pump(app, 160)
    grab(page, "library-brand.png")
    print("library", page.project_library_title.text(), page.project_library_brand.text())

    project = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "2ByteASR" / r"Projects\尼奈早稻机VLOG\尼奈早稻机VLOG.2byteproj"
    if project.is_file():
        page.open_project(project)
        pump(app, 2500)
        page.select_cue(page.project.cues[0].id)
        pump(app, 200)
        grab(page, "studio-editor-hidden.png")
        print("editor_hidden", page.subtitle_edit_card.isVisible())
        page._begin_canvas_inline_edit()
        pump(app, 120)
        grab(page, "studio-editor-e.png")
        grab(page.subtitle_edit_card, "subtitle-edit-card.png")
        print("editor_e", page.subtitle_edit_card.isVisible())
        page._cancel_canvas_inline_edit()
        pump(app, 80)

        page._open_render_dialog()
        pump(app, 400)
        if page.export_workspace is not None:
            grab(page, "export-page.png")
            grab(page.export_workspace, "export-presets.png")
            print("export_preset", page.export_workspace.preset.currentText())
            page._close_export_workspace()
            pump(app, 200)
            grab(page, "export-back-studio.png")
            print("after_back_export", page.export_workspace is None, "splitter", not page.workspace_splitter.isHidden())

        page._request_return_library()
        pump(app, 200)
        grab(page, "library-from-studio.png")
        print("hub", page._project_view_state, page.project is None)

        page.open_project(project)
        pump(app, 1800)
        grab(page, "library-reopen-studio.png")
        print("reopen_export", page.export_workspace)

    solid = FillEditorDialog("#FFFF4DA3")
    solid.show(); pump(app, 80); grab(solid, "fill-solid.png"); solid.close()
    linear = FillEditorDialog({
        "type": "linear-gradient", "angle": 18,
        "stops": [{"color": "#FFFF5E5E", "position": 0.0}, {"color": "#FF5EC8FF", "position": 1.0}],
    })
    linear.show(); linear.mode_group.button(1).setChecked(True)
    pump(app, 80); grab(linear, "fill-linear.png"); linear.close()
    radial = FillEditorDialog({
        "type": "radial-gradient",
        "stops": [{"color": "#FFFFFFFF", "position": 0.0}, {"color": "#FF20D6E8", "position": 1.0}],
    })
    radial.show(); radial.mode_group.button(2).setChecked(True)
    pump(app, 80); grab(radial, "fill-radial.png"); radial.close()

    page.close_page()
    page.deleteLater()
    pump(app, 60)
    print("shots", SHOTS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
