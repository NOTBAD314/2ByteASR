"""P5.3 real-app screenshots, export progress log, and encoder benchmarks."""

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
from PySide6.QtWidgets import QApplication, QDialog

import subtitle_core as legacy

from twobyteasr.i18n import apply_ui_language
from twobyteasr.main_ui_dialogs import SpringDialog
from twobyteasr.studio_export_ui import StudioExportWorkspace
from twobyteasr.studio_find_replace import FindReplaceDialog
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.studio_render import (
    STAGE_ADVANCED_RENDER,
    STAGE_ENCODE,
    STAGE_MUX,
    STAGE_PREPARE_PROJECT,
    STAGE_PREPARE_SUBTITLES,
    RenderJob,
    RenderSettings,
    export_progress,
    run_render_job,
)
from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.theme_manager import apply_application_theme
from twobyteasr.ui import MainWindow


SHOTS = ROOT / "tmp" / "p53-accept"
SHOTS.mkdir(parents=True, exist_ok=True)
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
SOURCE = Path(Path.home() / "Desktop" / r"尼奈早稻机VLOG.mp4")


def pump(app, ms=160):
    deadline = time.perf_counter() + ms / 1000
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.01)


def grab(widget, name: str) -> Path:
    target = SHOTS / name
    pixmap = widget.grab()
    if pixmap.isNull() or not pixmap.save(str(target), "PNG"):
        raise RuntimeError(name)
    print("shot", target)
    return target


def ffprobe_duration(path: Path) -> float:
    completed = subprocess.run(
        [str(FFMPEG.with_name("ffprobe.exe")), "-v", "error", "-show_entries",
         "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        return float(completed.stdout.strip() or 0)
    except ValueError:
        return 0.0


def cut_range(source: Path, dest: Path, start: float, duration: float) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 1000:
        return dest
    subprocess.run(
        [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
         "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(source),
         "-c", "copy", str(dest)],
        check=True,
    )
    return dest


def write_ass(path: Path, width=1280, height=720, text="P53") -> Path:
    path.write_text(
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,48,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,24,24,32,1\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        f"Dialogue: 0,0:00:00.00,0:00:08.00,Default,,0,0,0,,{text}\n",
        encoding="utf-8",
    )
    return path


def capture_ui(app: QApplication) -> dict:
    from PySide6.QtWidgets import QLabel, QVBoxLayout

    apply_application_theme(app, "plum")
    facade = MainWindow([], legacy, object(), None)
    facade.resize(1440, 900)
    facade.show()
    pump(app, 500)
    shots = {}
    shots["recognition-plum-mascot"] = str(grab(facade, "recognition-plum-mascot.png"))
    shots["recognition-plum-header"] = str(grab(facade.app_header, "recognition-plum-header.png"))
    shots["recognition-plum-window-controls"] = str(grab(facade.window_title_bar, "recognition-plum-window-controls.png"))
    dialog = SpringDialog(facade)
    dialog.setWindowTitle("高级设置 / 任务设置")
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("高级设置 / 任务设置"))
    layout.addWidget(QLabel("统一管理对白覆盖、复核轨、说话人数、缓存刷新和已有字幕覆盖策略。"))
    dialog.resize(720, 420)
    dialog.show()
    pump(app, 200)
    shots["advanced-settings-plum"] = str(grab(dialog, "advanced-settings-plum.png"))
    dialog.close()

    apply_application_theme(app, "warm")
    pump(app, 250)
    shots["recognition-warm-mascot"] = str(grab(facade, "recognition-warm-mascot.png"))
    dialog = SpringDialog(facade)
    dialog.resize(720, 420)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("高级设置 / 任务设置"))
    dialog.show()
    pump(app, 160)
    shots["advanced-settings-warm"] = str(grab(dialog, "advanced-settings-warm.png"))
    dialog.close()

    apply_application_theme(app, "slate")
    pump(app, 200)
    shots["recognition-slate-window-controls"] = str(grab(facade.window_title_bar, "recognition-slate-window-controls.png"))
    shots["recognition-slate"] = str(grab(facade, "recognition-slate.png"))

    page = facade.studio_page
    facade.pages.setCurrentWidget(page)
    page.show()
    page.show_project_hub()
    pump(app, 300)
    shots["library-brand"] = str(grab(page, "library-brand.png"))
    shots["library-window-controls"] = str(grab(page.studio_toolbar, "library-window-controls.png"))

    project = SubtitleProject(
        media=StudioMedia(path=str(SOURCE if SOURCE.is_file() else ROOT / "tmp" / "p52-accept" / "bench" / "bench.mp4"), duration_ms=30_000, width=1920, height=1080),
        cues=[StudioCue("c0", 0, 2000, "它真的来了"), StudioCue("c1", 2000, 4000, "然后就是就是我们先过去看一下")],
    )
    workspace = StudioExportWorkspace(project, str(SHOTS / "preview.ass"))
    workspace.resize(1280, 800)
    workspace.show()
    workspace.pages.setCurrentWidget(workspace.exporting_page)
    workspace._advanced_route = True
    workspace._show_advanced_stage(True)
    workspace._apply_progress(-1, export_progress(STAGE_PREPARE_PROJECT, message="正在解析工程并检查输入文件…"))
    pump(app, 120)
    shots["export-stage-prepare"] = str(grab(workspace, "export-stage-prepare.png"))
    workspace._apply_progress(-1, export_progress(STAGE_ADVANCED_RENDER, message="正在准备高级字幕渲染…"))
    pump(app, 80)
    shots["export-stage-advanced"] = str(grab(workspace, "export-stage-advanced.png"))
    workspace._apply_progress(35, export_progress(
        STAGE_ENCODE, message="正在编码视频…", percent=35, indeterminate=False,
        out_time_us=str(round(3.08 * 1_000_000)), duration_seconds=9.02, fps="72", speed="1.2x",
    ))
    pump(app, 80)
    shots["export-stage-encode"] = str(grab(workspace, "export-stage-encode.png"))
    fake = SHOTS / "result-demo.mp4"
    fake.write_bytes(b"0" * 1024)
    workspace._started_at = time.monotonic() - 105
    workspace._show_success(str(fake))
    pump(app, 80)
    shots["export-result-card"] = str(grab(workspace, "export-result-card.png"))
    workspace.close()

    apply_application_theme(app, "plum")
    for language, name in (("zh", "i18n-zh"), ("en", "i18n-en"), ("ja", "i18n-ja")):
        apply_ui_language(facade, language)
        pump(app, 160)
        shots[name] = str(grab(facade, f"{name}.png"))

    page.show_project_hub()
    apply_ui_language(page, "en")
    pump(app, 160)
    shots["i18n-en-library"] = str(grab(page, "i18n-en-library.png"))
    apply_ui_language(page, "ja")
    pump(app, 160)
    shots["i18n-ja-library"] = str(grab(page, "i18n-ja-library.png"))

    demo = save_project(
        SubtitleProject(
            media=StudioMedia(path=str(SOURCE if SOURCE.is_file() else ROOT / "tmp" / "p52-accept" / "bench" / "bench.mp4"), duration_ms=4000),
            cues=[StudioCue("c0", 13333, 15000, "它真的来了"), StudioCue("c1", 16000, 18000, "它真的走了")],
        ),
        SHOTS / "preview-toolbox.2byteproj",
    )
    page.video.load = lambda *_a, **_k: None
    page._generate_waveform = lambda *_a, **_k: None
    page.open_project(demo)
    pump(app, 200)
    dialog = FindReplaceDialog(page, page)
    dialog.find_edit.setText("它")
    dialog.replace_edit.setText("她")
    dialog._do_preview()
    dialog.show()
    pump(app, 160)
    shots["batch-replace"] = str(grab(dialog, "batch-replace.png"))
    dialog.close()
    facade.close()
    return shots


def log_native_progress(media: Path, duration: float, name: str) -> dict:
    ass = write_ass(SHOTS / f"{name}.ass", text=name)
    output = SHOTS / "bench" / f"{name}.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    events = []
    started = time.perf_counter()

    def progress(payload: dict) -> None:
        events.append({"t": round(time.perf_counter() - started, 3), **dict(payload)})

    job = RenderJob(
        str(media), str(ass), str(output),
        RenderSettings(encoder="h264_nvenc", quality_mode="cq", quality=23, preset="p4"),
        start_seconds=0.0, duration_seconds=duration, overwrite_existing=True,
    )
    try:
        run_render_job(FFMPEG, job, progress=progress)
        wall = time.perf_counter() - started
        ok = output.is_file()
    except Exception as exc:
        wall = time.perf_counter() - started
        ok = False
        events.append({"t": round(wall, 3), "error": str(exc)})
    percents = []
    for event in events:
        if event.get("stage") == STAGE_ENCODE and event.get("percent"):
            try:
                percents.append(float(event["percent"]))
            except ValueError:
                pass
        elif event.get("out_time_ms") and event.get("stage") == STAGE_ENCODE:
            try:
                percents.append(float(event["out_time_ms"]) / 1_000_000 / max(0.05, duration) * 100)
            except (TypeError, ValueError):
                pass
    jump = 0.0
    for left, right in zip(percents, percents[1:]):
        jump = max(jump, right - left)
    stages = [event.get("stage") for event in events if event.get("stage")]
    payload = {
        "name": name, "duration": duration, "wall": round(wall, 3),
        "ok": ok, "size": output.stat().st_size if ok else 0,
        "first_events": events[:8], "stages": stages,
        "max_percent_jump": round(jump, 2),
        "stayed_zero": all(p < 1 for p in percents[:3]) if percents else True,
        "indeterminate_before_encode": any(event.get("stage") in {STAGE_PREPARE_PROJECT, STAGE_PREPARE_SUBTITLES} and event.get("indeterminate") == "1" for event in events),
    }
    (SHOTS / f"{name}-progress.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("progress", name, "wall", payload["wall"], "jump", payload["max_percent_jump"], "stages", stages)
    return payload


def gpu_stats() -> dict:
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,utilization.encoder,utilization.decoder,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8,
        )
        parts = [item.strip() for item in completed.stdout.split(",")]
        if len(parts) >= 4:
            return {
                "gpu": float(parts[0]), "nvenc": float(parts[1]),
                "nvdec": float(parts[2]), "vram_mb": float(parts[3]),
            }
    except Exception:
        pass
    return {}


def bench_native(media: Path, duration: float, label: str) -> list[dict]:
    rows = []
    ass = write_ass(SHOTS / f"bench-{label}.ass", text=label)
    encoders = ["libx264", "h264_nvenc", "hevc_nvenc", "av1_nvenc"]
    for encoder in encoders:
        output = SHOTS / "bench" / f"{label}-{encoder}.mp4"
        if output.exists():
            output.unlink()
        settings = RenderSettings(
            encoder=encoder,
            codec="hevc" if "hevc" in encoder else ("av1" if "av1" in encoder else "h264"),
            quality_mode="cq" if encoder.endswith("nvenc") else "crf",
            quality=23 if encoder.endswith("nvenc") else 20,
            preset="p4" if encoder.endswith("nvenc") else "veryfast",
        )
        job = RenderJob(str(media), str(ass), str(output), settings, 0.0, duration, True)
        started = time.perf_counter()
        gpu_before = gpu_stats()
        try:
            run_render_job(FFMPEG, job)
            error = ""
        except Exception as exc:
            error = str(exc)
        wall = time.perf_counter() - started
        gpu_after = gpu_stats()
        size = output.stat().st_size if output.is_file() else 0
        row = {
            "label": label, "encoder": encoder, "duration": duration,
            "wall": round(wall, 3), "realtime": round(duration / wall, 3) if wall else 0,
            "fps": round((duration * 30) / wall, 2) if wall else 0,
            "size": size, "error": error[:400],
            "gpu_before": gpu_before, "gpu_after": gpu_after,
        }
        rows.append(row)
        print("bench", label, encoder, f"{wall:.2f}s", f"{row['realtime']:.2f}x", error[:80])
    return rows


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    phase = os.environ.get("TWOBYTEASR_P53_PHASE", "all")
    if phase in {"all", "ui"}:
        shots = capture_ui(app)
        (SHOTS / "shots.json").write_text(json.dumps(shots, ensure_ascii=False, indent=2), encoding="utf-8")
    if phase == "ui":
        print("ui-only", SHOTS)
        return 0
    app  # keep Qt alive for consistency when phase=bench

    source = SOURCE if SOURCE.is_file() else ROOT / "tmp" / "p52-accept" / "bench" / "bench.mp4"
    clips = {
        "native-30s": (0.0, 30.0),
        "native-2min": (30.0, 120.0),
        "native-range-3min": (90.0, 180.0),
    }
    progress_rows = []
    bench_rows = []
    if source.is_file() and ffprobe_duration(source) >= 20:
        for name, (start, duration) in clips.items():
            clip = cut_range(source, SHOTS / "clips" / f"{name}.mp4", start, duration)
            progress_rows.append(log_native_progress(clip, duration, name))
            bench_rows.extend(bench_native(clip, duration, name))
    else:
        print("missing long source, using synthetic 8s")
        synth = SHOTS / "clips" / "synth.mp4"
        synth.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
             "-t", "8", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(synth)],
            check=True,
        )
        progress_rows.append(log_native_progress(synth, 8, "synth-8s"))
        bench_rows.extend(bench_native(synth, 8, "synth-8s"))

    (SHOTS / "progress-log.json").write_text(json.dumps(progress_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (SHOTS / "benchmark.json").write_text(json.dumps(bench_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", SHOTS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
