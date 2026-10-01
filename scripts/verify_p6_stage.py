"""P6 real-app screenshots, concat export, XML, and AI highlight evidence."""

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
os.environ.setdefault("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack

from twobyteasr.studio_danmaku import aggregate_danmaku, parse_danmaku_xml
from twobyteasr.studio_edit_commands import (
    generate_edit_command,
    razor_video_command,
    restore_full_sequence_command,
    ripple_trim_command,
    set_video_lock_command,
)
from twobyteasr.studio_edit_sequence import (
    HighlightCandidate,
    ensure_edit_sequence,
    sequence_of,
    store_sequence,
)
from twobyteasr.studio_highlight_analyzer import analyze_highlights
from twobyteasr.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    load_project,
    save_project,
)
from twobyteasr.studio_render import RenderJob, RenderSettings, run_render_job
from twobyteasr.studio_sequence_mapper import export_source_slices, write_mpv_edl
from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.settings import load_runtime_settings
from twobyteasr.ass_compiler import compile_ass

SHOTS = ROOT / "tmp" / "p6-accept"
SHOTS.mkdir(parents=True, exist_ok=True)
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
FFPROBE = FFMPEG.with_name("ffprobe.exe")
CLIP = ROOT / "tmp" / "p53-accept" / "clips" / "native-30s.mp4"


def pump(app, ms=200):
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
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        return float(completed.stdout.strip() or 0)
    except ValueError:
        return 0.0


def write_xml(path: Path) -> Path:
    lines = ['<?xml version="1.0" encoding="UTF-8"?><i>']
    bursts = (
        (1.0, "笑死", 40),
        (8.5, "草", 28),
        (18.0, "卧槽", 22),
        (24.0, "？？？", 18),
    )
    serial = 0
    for start, word, count in bursts:
        for index in range(count):
            t = start + index * 0.05
            lines.append(f'<d p="{t:.2f},1,25,16777215,0,0,u,{serial}">{word}</d>')
            serial += 1
    for index in range(20):
        lines.append(f'<d p="{12.0 + index * 0.3:.2f},1,25,16777215,0,0,u,{serial}">平常</d>')
        serial += 1
    lines.append("</i>")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def build_project(media: Path) -> SubtitleProject:
    duration = round(ffprobe_duration(media) * 1000)
    project = SubtitleProject(
        media=StudioMedia(path=str(media), display_name=media.name, duration_ms=duration, width=1280, height=720),
        speakers=[StudioSpeaker("S01", "主播"), StudioSpeaker("S02", "队友")],
        cues=[
            StudioCue("c1", 800, 3500, "今天这把有点悬", "S01"),
            StudioCue("c2", 5000, 8200, "不是吧又翻车了", "S01"),
            StudioCue("c3", 11000, 15500, "等一下我还能反杀", "S02"),
            StudioCue("c4", 18000, 23000, "笑死 这波太离谱", "S01"),
            StudioCue("c5", 25000, 29000, "收工收工", "S01"),
        ],
    )
    ensure_edit_sequence(project)
    return project


def export_sequence(project: SubtitleProject, dest: Path) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    ass = dest.with_suffix(".ass")
    ass.write_text(compile_ass(project), encoding="utf-8-sig")
    sequence = sequence_of(project)
    slices = tuple(export_source_slices(sequence))
    duration = sequence.timeline_duration_ms / 1000.0
    job = RenderJob(
        project.media.path,
        str(ass),
        str(dest),
        RenderSettings(encoder="h264_nvenc", codec="h264", quality_mode="cq", quality=23, audio_codec="aac", width=1280, height=720),
        start_seconds=None if sequence.is_linear_source() else 0.0,
        duration_seconds=duration,
        overwrite_existing=True,
        edit_segments=() if sequence.is_linear_source() else slices,
    )
    events = []
    run_render_job(FFMPEG, job, progress=lambda payload: events.append(dict(payload)))
    probed = ffprobe_duration(dest)
    return {
        "output": str(dest),
        "size": dest.stat().st_size if dest.is_file() else 0,
        "expected": duration,
        "probed": probed,
        "delta": abs(probed - duration),
        "slices": slices,
        "linear": sequence.is_linear_source(),
        "stages": [item.get("stage") for item in events if item.get("stage")],
    }


def main() -> int:
    if not CLIP.is_file():
        raise SystemExit(f"missing clip {CLIP}")
    app = QApplication.instance() or QApplication([])
    evidence: dict = {}

    project = build_project(CLIP)
    project_path = save_project(project, SHOTS / "p6-edit.2byteproj")

    page = SubtitleStudioPage()
    page.video.load = lambda *_a, **_k: None
    page._generate_waveform = lambda *_a, **_k: None
    page.resize(1440, 920)
    page.show()
    page.open_project(project_path)
    pump(app, 400)
    evidence["video-track"] = str(grab(page.timeline, "video-track.png"))
    evidence["studio"] = str(grab(page, "studio-video-track.png"))
    page._open_clip_assistant()
    pump(app, 200)
    evidence["assistant"] = str(grab(page.highlight_panel, "highlight-assistant.png"))
    evidence["studio-assistant"] = str(grab(page, "studio-clip-assistant.png"))

    # Unlock, razor twice, Q then W.
    page.undo_stack.push(set_video_lock_command(page.project, False, page._changed))
    page.undo_stack.push(razor_video_command(page.project, 8_000, page._changed))
    page.undo_stack.push(razor_video_command(page.project, 18_000, page._changed))
    page.timeline.reindex_project()
    pump(app, 150)
    evidence["razor"] = str(grab(page.timeline, "razor-boundaries.png"))
    before = sequence_of(page.project).to_dict()
    page.timeline.set_playhead(8_000)
    page.undo_stack.push(ripple_trim_command(page.project, "end", 8_000, page._changed))
    page.timeline.reindex_project()
    pump(app, 150)
    evidence["ripple-w"] = str(grab(page.timeline, "ripple-w.png"))
    page.timeline.set_playhead(4_000)
    page.undo_stack.push(ripple_trim_command(page.project, "start", 4_000, page._changed))
    page.timeline.reindex_project()
    pump(app, 150)
    evidence["ripple-qw"] = str(grab(page.timeline, "ripple-qw.png"))
    after_edit = sequence_of(page.project).to_dict()
    cue_after = [(cue.id, cue.start_ms, cue.end_ms) for cue in page.project.cues]
    page.undo_stack.undo()
    page.undo_stack.undo()
    undone = sequence_of(page.project).to_dict()
    page.undo_stack.redo()
    page.undo_stack.redo()
    redone = sequence_of(page.project).to_dict()
    evidence["undo"] = {
        "before_segments": len(before["segments"]),
        "after_segments": len(after_edit["segments"]),
        "after_duration": after_edit.get("segments", [])[-1]["timeline_out_ms"] if after_edit.get("segments") else 0,
        "cues_after": cue_after,
        "undo_restored_segments": len(undone["segments"]),
        "redo_segments": len(redone["segments"]),
    }
    page.undo_stack.push(set_video_lock_command(page.project, True, page._changed))
    page.timeline.update()
    pump(app, 120)
    evidence["lock"] = str(grab(page.timeline, "video-lock.png"))

    saved = save_project(page.project, SHOTS / "p6-edited.2byteproj")
    reopened = load_project(saved)
    evidence["reopen"] = {
        "segments": sequence_of(reopened).to_dict()["segments"],
        "cues": [(cue.start_ms, cue.end_ms, cue.text) for cue in reopened.cues],
        "duration": sequence_of(reopened).timeline_duration_ms,
    }

    # Mapper sequence 0-10 / 20-30 / 40-50 on a synthetic 50s project, export 30s from 30s clip using 0-8 + 18-28.
    mapper_project = build_project(CLIP)
    mapper_project.undo = None
    stack = QUndoStack()
    stack.push(set_video_lock_command(mapper_project, False))
    stack.push(razor_video_command(mapper_project, 10_000))
    stack.push(razor_video_command(mapper_project, 20_000))
    stack.push(ripple_trim_command(mapper_project, "end", 10_000))  # drop 10-20
    edl = write_mpv_edl(sequence_of(mapper_project), SHOTS / "edited.edl")
    evidence["edl"] = edl.read_text(encoding="utf-8")
    evidence["mapper_slices"] = export_source_slices(sequence_of(mapper_project))
    evidence["mapper_duration_ms"] = sequence_of(mapper_project).timeline_duration_ms
    export_info = export_sequence(mapper_project, SHOTS / "edited-timeline.mp4")
    evidence["export"] = export_info

    xml = write_xml(SHOTS / "danmaku.xml")
    document = parse_danmaku_xml(xml)
    windows = aggregate_danmaku(document, window_ms=5000)
    evidence["xml"] = {
        "count": document.count,
        "duration_ms": document.duration_ms,
        "windows": [
            {"start": w.start_ms, "count": w.count, "spike": round(w.spike, 2), "top": w.top_texts[:3]}
            for w in windows[:4]
        ],
    }

    ai_project = build_project(CLIP)
    sequence = sequence_of(ai_project)
    sequence.danmaku_path = str(xml)
    store_sequence(ai_project, sequence)
    settings, _path, _warnings = load_runtime_settings()
    try:
        result = analyze_highlights(
            ai_project,
            danmaku_path=str(xml),
            mode="subtitles_xml",
            runtime_settings=settings,
            target_count=8,
            min_seconds=8,
            max_seconds=40,
        )
        evidence["ai"] = {
            "ok": True,
            "skill_found": result["skill_found"],
            "skill_path": result["skill_path"],
            "local_count": result["local_count"],
            "danmaku_count": result["danmaku_count"],
            "candidates": [item.to_dict() for item in result["candidates"]],
        }
        if result["candidates"]:
            for item in result["candidates"][:3]:
                item.status = "accepted"
            stack = QUndoStack()
            stack.push(generate_edit_command(ai_project, result["candidates"][:3]))
            gen = export_sequence(ai_project, SHOTS / "highlight-reel.mp4")
            evidence["generate_export"] = gen
            stack.push(restore_full_sequence_command(ai_project))
            evidence["restore_identity"] = sequence_of(ai_project).is_identity()
            page.project.edit_sequence = sequence_of(ai_project).to_dict()
            # show candidates on the visible page
            visible = sequence_of(page.project)
            visible.clip_candidates = result["candidates"]
            store_sequence(page.project, visible)
            page.highlight_panel.set_project_status(page.project, str(xml))
            page.timeline.update()
            pump(app, 250)
            evidence["candidates-timeline"] = str(grab(page.timeline, "candidate-lane.png"))
            evidence["highlight-bin"] = str(grab(page.highlight_panel, "highlight-bin.png"))
            evidence["assistant-results"] = str(grab(page.highlight_panel, "highlight-assistant-results.png"))
            evidence["studio-results"] = str(grab(page, "studio-clip-results.png"))
    except Exception as exc:
        evidence["ai"] = {"ok": False, "error": str(exc)}

    page.close_page()
    page.deleteLater()
    (SHOTS / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: (v if not isinstance(v, str) or not v.endswith(".png") else v) for k, v in evidence.items() if k != "edl"}, ensure_ascii=False, indent=2)[:4000])
    if export_info["delta"] > 0.4:
        raise SystemExit(f"export duration mismatch {export_info}")
    print("P6 verify wrote", SHOTS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
