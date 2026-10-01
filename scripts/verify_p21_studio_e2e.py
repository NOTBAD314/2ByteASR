"""Retained P21 Studio archive, review, style, and render acceptance."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from twobyteasr.ass_compiler import compile_ass  # noqa: E402
from twobyteasr.studio_project import (  # noqa: E402
    StudioCue,
    StudioMedia,
    SubtitleProject,
    load_project,
    project_archive_path,
    project_backup_path,
    save_project,
)
from twobyteasr.studio_render import RenderJob, RenderSettings, run_render_job  # noqa: E402
from twobyteasr.studio_review import store_review_risks  # noqa: E402
from twobyteasr.studio_ui import SubtitleStudioPage  # noqa: E402


FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
FFPROBE = ROOT / "tools" / "ffmpeg" / "bin" / "ffprobe.exe"
MPV = ROOT / "tools" / "mpv" / "mpv.exe"


def run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def main() -> int:
    output = ROOT / "tmp" / "p21-studio-e2e"
    output.mkdir(parents=True, exist_ok=True)
    os.environ["LOCALAPPDATA"] = str(output / "local-app-data")
    media = output / "p21-source.mp4"
    run(
        [
            str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24:duration=8",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=8",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(media),
        ]
    )

    project = SubtitleProject(
        media=StudioMedia(str(media), "P21 acceptance", 8_000),
        cues=[
            StudioCue("risk", 300, 650, "倾斜的天平现在开始快速移动", original_text="清晰的天平现在开始快速移动", evidence_refs=["risk:evidence"]),
            StudioCue("safe", 1800, 4300, "这是一条阅读速度正常的字幕", original_text="这是一条阅读速度正常的字幕", evidence_refs=["safe:evidence"]),
        ],
        asr_evidence={
            "risk:evidence": {"moss_text": "倾斜的天平", "qwen_asr_text": "清晰的天平", "confidence": 0.42},
            "safe:evidence": {"moss_text": "正常字幕", "qwen_asr_text": "正常字幕", "confidence": 0.98},
        },
        render_settings={"play_res_x": 640, "play_res_y": 360},
    )
    style = project.styles[0]
    style.font_size = 34
    style.position_x = 320
    style.position_y = 310
    style.primary_color = "#FFF4B8"
    style.outline_color = "#142019"
    style.back_color = "#80202822"
    style.outline_width = 3
    style.shadow = 2
    style.border_style = 3
    risks = store_review_risks(project)

    project_path = project_archive_path(output / "requested.srt", media)
    save_project(project, project_path)
    project.studio_state["acceptance_saved"] = True
    save_project(project, project_path)
    project = load_project(project_path)
    archive = project_path.parent
    ass = archive / "preview" / "p21-preview.ass"
    ass.write_text(compile_ass(project), encoding="utf-8-sig", newline="\n")

    mp4 = archive / "exports" / "p21-h264.mp4"
    mkv = archive / "exports" / "p21-hevc.mkv"
    run_render_job(
        FFMPEG,
        RenderJob(str(media), str(ass), str(mp4), RenderSettings(container="mp4", codec="h264", encoder="libx264", preset="ultrafast", quality=26)),
    )
    run_render_job(
        FFMPEG,
        RenderJob(str(media), str(ass), str(mkv), RenderSettings(container="mkv", codec="hevc", encoder="libx265", preset="ultrafast", quality=28)),
    )

    probes = {}
    decodes = {}
    for target in (mp4, mkv):
        probes[target.suffix] = json.loads(
            run([str(FFPROBE), "-v", "error", "-show_entries", "format=duration:stream=codec_name,width,height", "-of", "json", str(target)]).stdout
        )
        decodes[target.suffix] = run([str(MPV), "--no-config", "--vo=null", "--ao=null", "--frames=3", str(target)]).returncode

    app = QApplication.instance() or QApplication([])
    windows_cjk = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
    if windows_cjk.is_file():
        QFontDatabase.addApplicationFont(str(windows_cjk))
    app.setFont(QFont("Microsoft YaHei UI", 10))
    page = SubtitleStudioPage()
    page.video.load = lambda *_args, **_kwargs: None
    page._generate_waveform = lambda *_args, **_kwargs: None
    page.resize(1440, 900)
    page.show()
    page.open_project(project_path)
    page._activate_filter("priority")
    app.processEvents()
    review_shot = output / "p21-priority-review.png"
    if not page.grab().save(str(review_shot)):
        raise RuntimeError("could not capture priority review")
    page.context_drawer.setCurrentIndex(2)
    page.position_edit_button.setChecked(True)
    page.position_overlay.set_video_position(320, 310, 640, 360)
    app.processEvents()
    position_shot = output / "p21-video-position.png"
    if not page.grab().save(str(position_shot)):
        raise RuntimeError("could not capture video position")
    page.close_page()
    page.close()
    app.processEvents()

    report = {
        "project": str(project_path),
        "archive_directories": sorted(path.name for path in archive.iterdir() if path.is_dir()),
        "backup": str(project_backup_path(project_path)),
        "risk_example": risks["risk"].to_dict(),
        "safe_example": risks["safe"].to_dict(),
        "ass_has_position": r"\pos(320,310)" in ass.read_text(encoding="utf-8-sig"),
        "renders": {"mp4": str(mp4), "mkv": str(mkv)},
        "ffprobe": probes,
        "mpv_decode_returncodes": decodes,
        "screenshots": [str(review_shot), str(position_shot)],
    }
    report_path = output / "acceptance-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
