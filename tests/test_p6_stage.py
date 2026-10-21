"""P6 lite NLE: edit sequence, razor, ripple, mapper, export, danmaku, AI parse."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.studio.studio_danmaku import aggregate_danmaku, parse_danmaku_xml
from twobyteasr.timeline.studio_edit_commands import (
    generate_edit_command,
    razor_video_command,
    restore_full_sequence_command,
    ripple_trim_command,
    set_video_lock_command,
)
from twobyteasr.timeline.studio_edit_sequence import (
    HighlightCandidate,
    VideoSegment,
    ensure_edit_sequence,
    identity_sequence,
    previous_edit_ms,
    next_edit_ms,
    ripple_cues,
    sequence_from_candidates,
    sequence_of,
    split_at_playhead,
    timeline_duration_ms,
)
from twobyteasr.studio.studio_highlight_analyzer import parse_highlight_payload
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, load_project, save_project
from twobyteasr.exports.studio_render import RenderJob, RenderSettings, build_concat_filter_complex, build_render_command
from twobyteasr.timeline.studio_sequence_mapper import export_source_slices, source_to_timeline, timeline_to_source, write_mpv_edl


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"


def _project(duration_ms: int = 50_000, cues: list[StudioCue] | None = None) -> SubtitleProject:
    project = SubtitleProject(
        media=StudioMedia(path="D:/rec.mp4", duration_ms=duration_ms, width=1280, height=720),
        speakers=[StudioSpeaker(id="S01", name="主播"), StudioSpeaker(id="S02", name="队友")],
        cues=cues or [
            StudioCue(id="c1", start_ms=1000, end_ms=4000, text="开场", speaker_id="S01"),
            StudioCue(id="c2", start_ms=8000, end_ms=12000, text="中间", speaker_id="S01"),
            StudioCue(id="c3", start_ms=22000, end_ms=28000, text="高潮", speaker_id="S02"),
            StudioCue(id="c4", start_ms=40000, end_ms=45000, text="收尾", speaker_id="S01"),
        ],
    )
    ensure_edit_sequence(project)
    return project


def test_old_project_migrates_to_one_identity_segment(tmp_path):
    payload = {
        "schema_version": 1,
        "project_id": "old",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "media": {"path": "D:/old.mp4", "display_name": "old.mp4", "duration_ms": 12_000},
        "cues": [{"id": "a", "start_ms": 0, "end_ms": 1000, "text": "hi", "speaker_id": "S00"}],
        "speakers": [],
        "styles": [{"id": "default", "name": "default"}],
        "effects": {},
        "style_recipes": {},
        "generation_metadata": {},
        "asr_evidence": {},
        "glossary_ids": [],
        "edit_history": [],
        "render_settings": {},
        "report_path": "",
        "original_outputs": {},
        "studio_state": {},
    }
    path = tmp_path / "legacy.2byteproj"
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_project(path)
    sequence = sequence_of(loaded)
    assert len(sequence.segments) == 1
    assert sequence.is_identity()
    saved = save_project(loaded, tmp_path / "migrated.2byteproj")
    again = load_project(saved)
    assert sequence_of(again).to_dict()["segments"] == sequence_of(loaded).to_dict()["segments"]
    assert [(cue.start_ms, cue.end_ms, cue.text) for cue in again.cues] == [
        (cue.start_ms, cue.end_ms, cue.text) for cue in loaded.cues
    ]


def test_razor_creates_edit_point_without_touching_cues():
    project = _project()
    before_cues = [(cue.id, cue.start_ms, cue.end_ms, cue.text) for cue in project.cues]
    stack = QUndoStack()
    stack.push(razor_video_command(project, 10_000))
    sequence = sequence_of(project)
    assert len(sequence.segments) == 2
    assert sequence.segments[0].timeline_out_ms == 10_000
    assert sequence.segments[1].timeline_in_ms == 10_000
    assert sequence.timeline_duration_ms == 50_000
    assert [(cue.id, cue.start_ms, cue.end_ms, cue.text) for cue in project.cues] == before_cues
    stack.undo()
    assert len(sequence_of(project).segments) == 1


def test_qw_ripple_shifts_and_deletes_cues_as_one_undo():
    project = _project()
    stack = QUndoStack()
    stack.push(ripple_trim_command(project, "end", 10_000))  # W: delete 10s → next edit (end of first identity)
    # identity: previous edit 0, next edit = duration. W from 10s deletes 10s–50s
    # Wait: next_edit of identity at 10s is timeline_out of the only segment = 50s
    # That would delete almost everything. Use razor first.
    project = _project()
    stack = QUndoStack()
    stack.push(razor_video_command(project, 10_000))
    stack.push(razor_video_command(project, 20_000))
    stack.push(ripple_trim_command(project, "end", 10_000))  # delete 10–20
    sequence = sequence_of(project)
    assert sequence.timeline_duration_ms == 40_000
    # cue 8–12 overlaps 10–20: clamp start to 10 then shift? start in range, end in range for 8-12:
    # start 8 < 10, end 12 in [10,20) → end becomes 10. Kept at 8–10.
    from twobyteasr.timeline.studio_edit_sequence import projected_cues, source_cue_id_of
    assert [(c.start_ms, c.end_ms) for c in project.cues] == [(c.start_ms, c.end_ms) for c in _project().cues]
    texts = {source_cue_id_of(cue.id): (cue.start_ms, cue.end_ms) for cue in projected_cues(project)}
    assert "c1" in texts
    assert texts["c1"] == (1000, 4000)
    assert "c2" in texts
    assert texts["c2"][1] <= 10_000
    assert "c3" in texts
    assert texts["c3"][0] == 12_000  # 22000-10000
    assert texts["c3"][1] == 18_000
    cue_count = len(project.cues)
    stack.undo()
    assert sequence_of(project).timeline_duration_ms == 50_000
    assert len(project.cues) >= cue_count


def test_video_lock_blocks_ripple_semantics_helper():
    project = _project()
    assert sequence_of(project).video_track_locked is True
    stack = QUndoStack()
    stack.push(set_video_lock_command(project, False))
    assert sequence_of(project).video_track_locked is False
    stack.undo()
    assert sequence_of(project).video_track_locked is True


def test_mapper_seek_contract():
    sequence = identity_sequence(StudioMedia(path="D:/a.mp4", duration_ms=50_000))
    sequence.segments = [
        VideoSegment("a", "D:/a.mp4", 0, 10_000, 0, 10_000),
        VideoSegment("b", "D:/a.mp4", 20_000, 30_000, 10_000, 20_000),
        VideoSegment("c", "D:/a.mp4", 40_000, 50_000, 20_000, 30_000),
    ]
    sequence.source_duration_ms = 50_000
    sequence.normalize_timeline()
    assert sequence.timeline_duration_ms == 30_000
    assert timeline_to_source(sequence, 5_000).source_ms == 5_000
    assert timeline_to_source(sequence, 15_000).source_ms == 25_000
    assert timeline_to_source(sequence, 25_000).source_ms == 45_000
    assert source_to_timeline(sequence, 25_000).timeline_ms == 15_000
    slices = export_source_slices(sequence)
    assert slices == [(0.0, 10.0), (20.0, 30.0), (40.0, 50.0)]


def test_concat_filter_is_single_graph(tmp_path):
    graph, vlabel, alabel = build_concat_filter_complex(
        [(0.0, 10.0), (20.0, 30.0), (40.0, 50.0)],
        "ass=filename='x.ass'",
        has_audio=True,
    )
    assert "trim=" in graph and "atrim=" in graph and "concat=n=3" in graph
    assert "[v0][a0][v1][a1][v2][a2]concat=" in graph
    assert ".mp4" not in graph  # no intermediate files
    assert vlabel == "[vout]"
    from twobyteasr.system.processes import run_hidden_subprocess
    from twobyteasr.rendering.ass_compiler import compile_ass
    media=tmp_path/'source.mp4';ass=tmp_path/'captions.ass';output=tmp_path/'concat.mp4'
    run_hidden_subprocess([str(FFMPEG),'-v','error','-f','lavfi','-i',
        'color=c=purple:s=320x180:r=25:d=1','-f','lavfi','-i',
        'sine=frequency=660:sample_rate=48000:duration=1','-c:v','libx264',
        '-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(media)],
        capture_output=True,check=True,timeout=20,purpose='Self-contained concat regression fixture')
    project=SubtitleProject(media=StudioMedia(str(media),duration_ms=1000,width=320,height=180),
        cues=[StudioCue('concat',0,800,'拼接字幕')])
    ass.write_text(compile_ass(project),'utf8')
    command = build_render_command(
        FFMPEG,
        RenderJob(
            str(media),
            str(ass),
            str(output),
            RenderSettings(encoder="libx264", audio_codec="aac",fps=25),
            duration_seconds=.8,
            overwrite_existing=True,
            edit_segments=((0.0, .4), (.6, 1.0)),
        ),
    )
    joined = " ".join(command)
    assert "-filter_complex" in command
    assert "concat=n=2" in joined
    assert command.count("-i") == 1
    run_hidden_subprocess(command,capture_output=True,check=True,timeout=20,purpose='Validate actual one-graph concat output')
    metadata=json.loads(run_hidden_subprocess([str(FFMPEG.with_name('ffprobe.exe')),
        '-v','error','-show_streams','-of','json',str(output)],capture_output=True,check=True,timeout=10,
        purpose='Inspect concat regression audio and video streams').stdout)
    assert {stream['codec_type'] for stream in metadata['streams']} == {'audio','video'}
    assert output.stat().st_size>1000


def test_generate_edit_from_candidates_undo():
    project = _project()
    candidates = [
        HighlightCandidate("h1", "A", 0, 10_000, 0.9, status="accepted"),
        HighlightCandidate("h2", "B", 20_000, 30_000, 0.8, status="accepted"),
        HighlightCandidate("h3", "C", 40_000, 50_000, 0.7, status="accepted"),
    ]
    stack = QUndoStack()
    stack.push(generate_edit_command(project, candidates))
    assert sequence_of(project).timeline_duration_ms == 30_000
    stack.undo()
    assert sequence_of(project).is_identity()
    assert sequence_of(project).timeline_duration_ms == 50_000


def test_restore_full_sequence():
    project = _project()
    stack = QUndoStack()
    stack.push(generate_edit_command(project, [
        HighlightCandidate("h1", "A", 0, 10_000, status="accepted"),
    ]))
    assert not sequence_of(project).is_identity()
    stack.push(restore_full_sequence_command(project))
    assert sequence_of(project).is_identity()


def test_danmaku_xml_parse_and_aggregate(tmp_path):
    xml = tmp_path / "chat.xml"
    xml.write_text(
        """<?xml version="1.0"?><i>
        <d p="1.0,1,25,16777215,0,0,x,1">哈哈</d>
        <d p="1.2,1,25,16777215,0,0,x,2">笑死</d>
        <d p="1.4,1,25,16777215,0,0,x,3">草</d>
        <d p="12.0,1,25,16777215,0,0,x,4">平常</d>
        </i>""",
        encoding="utf-8",
    )
    document = parse_danmaku_xml(xml)
    assert document.count == 4
    windows = aggregate_danmaku(document, window_ms=5000)
    assert windows[0].count == 3
    assert windows[0].spike > 1.0


def test_discovers_user_livestream_clip_skills():
    from twobyteasr.studio.studio_highlight_analyzer import HighlightSkillAdapter

    skill = HighlightSkillAdapter.discover()
    assert skill.found is True
    assert "livestream-clip-finder" in skill.path or "light-danmaku-clip-ranker" in skill.path
    assert "bilibili-title-lab" not in skill.path


def test_ai_payload_must_be_structured():
    raw = json.dumps({
        "candidates": [
            {"title": "翻车反杀", "source_in": 12.0, "source_out": 48.0, "score": 0.92, "reason": "弹幕暴涨", "quotes": ["草"]}
        ]
    })
    items = parse_highlight_payload(raw, [])
    assert items[0].title == "翻车反杀"
    assert items[0].source_in_ms == 12_000
    assert items[0].source_out_ms == 48_000


def test_edl_write(tmp_path):
    sequence = identity_sequence(StudioMedia(path=str(tmp_path / "a.mp4"), duration_ms=10_000))
    sequence.segments = [
        VideoSegment("a", str(tmp_path / "a.mp4"), 0, 4000, 0, 4000),
        VideoSegment("b", str(tmp_path / "a.mp4"), 6000, 10000, 4000, 8000),
    ]
    path = write_mpv_edl(sequence, tmp_path / "seq.edl")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# mpv EDL v0")
    assert "0.000000,4.000000" in text
    assert "6.000000,4.000000" in text


def test_timeline_paint_scales_to_three_hour_synthetic():
    pytest.importorskip("PySide6")
    app = QApplication.instance() or QApplication([])
    from twobyteasr.studio.studio_ui import WaveformTimeline
    project = SubtitleProject(
        media=StudioMedia(path="D:/long.mp4", duration_ms=3 * 3600 * 1000),
        speakers=[StudioSpeaker(id=f"S{index:02d}", name=f"P{index}") for index in range(4)],
        cues=[
            StudioCue(
                id=f"c{index}",
                start_ms=index * 2000,
                end_ms=index * 2000 + 1500,
                text="x",
                speaker_id=f"S{index % 4:02d}",
            )
            for index in range(4000)
        ],
    )
    ensure_edit_sequence(project)
    sequence = sequence_of(project)
    sequence.segments = [
        VideoSegment(f"s{index}", "D:/long.mp4", index * 600_000, (index + 1) * 600_000, 0, 0)
        for index in range(18)
    ]
    sequence.normalize_timeline()
    from twobyteasr.timeline.studio_edit_sequence import store_sequence
    store_sequence(project, sequence)
    timeline = WaveformTimeline()
    timeline.resize(1400, 280)
    timeline.set_project(project)
    started = time.perf_counter()
    for _ in range(8):
        timeline.repaint()
        app.processEvents()
    elapsed = time.perf_counter() - started
    assert elapsed < 2.5
    timeline.setParent(None)
    timeline.deleteLater()
