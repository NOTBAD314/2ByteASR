"""Run a retained, real-media Subtitle Studio acceptance workflow."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from twobyteasr.ass_compiler import compile_ass, compile_txt
from twobyteasr.studio_commands import (
    SetCueFieldsCommand,
    SetCuePresentationCommand,
    split_cue_command,
)
from twobyteasr.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    load_project,
    save_project,
)
from twobyteasr.studio_render import RenderJob, RenderSettings, preview_job, run_render_job
from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.style_presets import BUILTIN_PRESETS


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
    output = ROOT / "tmp" / "p20-studio-e2e"
    # Qt may keep its process-local font cache locked briefly on Windows.
    # Reuse the isolated acceptance directory instead of recursively deleting it.
    output.mkdir(parents=True, exist_ok=True)
    os.environ["LOCALAPPDATA"] = str(output / "local-app-data")

    media = output / "studio-source.mp4"
    run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=30:duration=18",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=18",
            "-af",
            "volume=0.18+0.72*abs(sin(1.3*t)):eval=frame",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(media),
        ]
    )

    project = SubtitleProject(
        media=StudioMedia(str(media), "Studio acceptance video", 18_000),
        cues=[
            StudioCue("a", 400, 2200, "检测到异常能量波动。", speaker_id="S01", original_text="检测到异常能量波动。", evidence_refs=["e1"]),
            StudioCue("b", 1850, 3650, "又来一个？别担心。", speaker_id="S02", original_text="又来一个？别担心。", evidence_refs=["e2"]),
            StudioCue("c", 3900, 5350, "AI修改之前", speaker_id="S03", original_text="AI修改之前", evidence_refs=["e3"]),
            StudioCue("d", 5600, 7200, "路线已经标记。", speaker_id="S01", original_text="路线已经标记。", evidence_refs=["e1"]),
            StudioCue("e", 7350, 8900, "收到，现在出发。", speaker_id="S02", original_text="收到，现在出发。", evidence_refs=["e2"]),
            StudioCue("f", 9050, 10_500, "希望这次不会更糟。", speaker_id="S03", original_text="希望这次不会更糟。", evidence_refs=["e3"]),
            StudioCue("g", 10_650, 12_300, "前方区域信号不稳定。", speaker_id="S01", original_text="前方区域信号不稳定。", evidence_refs=["e1"]),
            StudioCue("h", 12_450, 13_700, "我会小心一点。", speaker_id="S02", original_text="我会小心一点。", evidence_refs=["e2"]),
            StudioCue("i", 13_850, 15_150, "等等，你听到了吗？", speaker_id="S03", original_text="等等，你听到了吗？", evidence_refs=["e3"]),
            StudioCue("j", 15_250, 16_250, "正在重新扫描。", speaker_id="S01", original_text="正在重新扫描。", evidence_refs=["e1"]),
            StudioCue("k", 16_300, 17_050, "有东西靠近。", speaker_id="S02", original_text="有东西靠近。", evidence_refs=["e2"]),
            StudioCue("l", 17_100, 17_900, "别回头。", speaker_id="S03", original_text="别回头。", evidence_refs=["e3"]),
        ],
        speakers=[
            StudioSpeaker("S01", name="MOSS", color="#6f9a78"),
            StudioSpeaker("S02", name="玩家", color="#6f91bd"),
            StudioSpeaker("S03", name="莉莉丝", color="#9a7baa"),
        ],
        generation_metadata={
            "translations": {
                "a": "An abnormal energy fluctuation is detected.",
                "b": "Another one? Do not worry.",
                "c": "I do not want to get pulled in again.",
                "d": "The route has been marked.",
                "e": "Copy. Moving out now.",
                "f": "I hope this does not get worse.",
                "g": "The signal ahead is unstable.",
                "h": "I will be careful.",
                "i": "Wait. Did you hear that?",
                "j": "Rescanning now.",
                "k": "Something is getting closer.",
                "l": "Do not look back.",
            }
        },
        asr_evidence={
            "e1": {"text": "这是第一句", "primary_source": "acceptance"},
            "e2": {"text": "这句将会拆分", "primary_source": "acceptance"},
            "e3": {"text": "AI修改之后", "primary_source": "acceptance"},
        },
        glossary_ids=["acceptance-glossary"],
    )
    project_path = save_project(project, output / "studio.2byteproj")
    undo = QUndoStack()
    undo.push(SetCueFieldsCommand(project, "a", {"text": "这是人工修正后的第一句"}, "Text Edit"))
    undo.push(SetCueFieldsCommand(project, "a", {"start_ms": 450, "end_ms": 2850}, "Timing"))
    undo.push(split_cue_command(project, "b", 2700, "又来一个？", "别担心。", None))
    game = BUILTIN_PRESETS["game"]
    undo.push(
        SetCuePresentationCommand(
            project,
            "a",
            cue_changes={"style_id": "game", "effect_id": "pop"},
            styles=[*project.styles, game],
            effects=project.effects,
            text="Speaker Style and Effect",
        )
    )
    undo.push(
        SetCuePresentationCommand(
            project,
            "c",
            cue_changes={"text": "AI修改之后", "effect_id": "fade"},
            effects=project.effects,
            text="AI Apply",
        )
    )
    undo.undo()
    assert next(cue for cue in project.cues if cue.id == "c").text == "AI修改之前"
    undo.redo()
    assert next(cue for cue in project.cues if cue.id == "c").text == "AI修改之后"
    project.studio_state.update(
        {
            "last_selected_cue": "g",
            "playhead_ms": 11_100,
            "zoom": 1.55,
            "scroll_ms": 3500,
            "bilingual_mode": True,
            "cue_statuses": {"e": "pending", "i": "issue"},
        }
    )
    save_project(project, project_path)

    reopened = load_project(project_path)
    assert len(reopened.cues) == 13
    assert reopened.studio_state["last_selected_cue"] == "g"
    ass = output / "studio.ass"
    txt = output / "studio.txt"
    ass.write_text(compile_ass(reopened), encoding="utf-8-sig", newline="\n")
    txt.write_text(compile_txt(reopened), encoding="utf-8", newline="\n")

    settings = RenderSettings(encoder="libx264", preset="ultrafast", quality=25)
    preview = output / "studio-preview-10s.mp4"
    final = output / "studio-final.mp4"
    run_render_job(
        FFMPEG,
        preview_job(str(media), str(ass), str(preview), settings, 6.0, 12.0),
    )
    run_render_job(FFMPEG, RenderJob(str(media), str(ass), str(final), settings))
    probe = json.loads(
        run(
            [
                str(FFPROBE),
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_name,width,height",
                "-of",
                "json",
                str(final),
            ]
        ).stdout
    )
    mpv_check = run(
        [
            str(MPV),
            "--no-config",
            "--vo=null",
            "--ao=null",
            "--frames=3",
            str(final),
        ]
    )

    app = QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    page.video.load = lambda *_args, **_kwargs: None
    page._generate_waveform = lambda *_args, **_kwargs: None
    page.open_project(project_path)
    screenshots = []
    for width, height in ((1366, 768), (1920, 1080)):
        page.resize(width, height)
        page.show()
        app.processEvents()
        target = output / f"studio-{width}x{height}.png"
        if not page.grab().save(str(target)):
            raise RuntimeError(f"could not save screenshot {target}")
        screenshots.append(str(target))
    page.close_page()
    page.close()
    app.processEvents()

    report = {
        "project": str(project_path),
        "media": str(media),
        "ass": str(ass),
        "txt": str(txt),
        "preview": str(preview),
        "final": str(final),
        "screenshots": screenshots,
        "cue_count": len(reopened.cues),
        "undo_redo_verified": True,
        "state_restored": reopened.studio_state,
        "ffprobe": probe,
        "mpv_decode_returncode": mpv_check.returncode,
    }
    (output / "acceptance-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
