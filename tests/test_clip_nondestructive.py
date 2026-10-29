"""非破坏式剪辑投影（2026-09-19 P0）。

历史缺陷（用户实测 496→15 条）：generate/restore 通过 remap_cues 物理改写
project.cues——生成剪辑丢弃区间外字幕、"返回完整录播"只能映射回幸存子集、
自动保存把片段子集写成完整工程数据、剪辑模式 ASS 是序列时间而 mpv 时钟在
源域（视频无字幕）。现在 project.cues 永远是全集+源时间，剪辑=纯视图投影。
"""

import copy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


def _project(tmp_path, cue_count=40, span_ms=600_000):
    from twobyteasr.projects.studio_project import (
        StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project,
    )

    project = SubtitleProject(media=StudioMedia(path="m.flv", duration_ms=span_ms))
    project.speakers.append(StudioSpeaker(id="S01", name="主播"))
    for index in range(cue_count):
        start = 10_000 + index * (span_ms - 20_000) // max(1, cue_count)
        project.cues.append(
            StudioCue(id=f"c{index}", start_ms=start, end_ms=start + 3500,
                      text=f"第{index}句", speaker_id="S01")
        )
    return project


def _accept(project, in_ms, out_ms, cid="h1"):
    from twobyteasr.timeline.studio_edit_sequence import HighlightCandidate, sequence_of

    sequence_of(project).clip_candidates = [
        HighlightCandidate(id=cid, title="t", source_in_ms=in_ms,
                           source_out_ms=out_ms, status="accepted")
    ]


def test_generate_keeps_full_cue_set_and_projects_view():
    from twobyteasr.timeline.studio_edit_commands import generate_edit_command
    from twobyteasr.timeline.studio_edit_sequence import projected_cues, sequence_of

    project = _project(None, cue_count=40, span_ms=600_000)
    _accept(project, 120_000, 300_000)
    generate_edit_command(project).redo()

    # 数据边界：全集永不被改写。
    assert len(project.cues) == 40
    assert min(c.start_ms for c in project.cues) >= 10_000
    # 视图：timeline 域投影（120s 起点段 → 局部时间从 0 附近开始）。
    view = projected_cues(project, domain="timeline")
    expected = [c for c in project.cues if c.end_ms > 120_000 and c.start_ms < 300_000]
    assert len(view) == len(expected)
    source_first = min(expected, key=lambda c: c.start_ms)
    view_first = min(view, key=lambda c: c.start_ms)
    assert view_first.start_ms == source_first.start_ms - 120_000
    assert view[0].id.startswith(source_first.id.split("#")[0] + "#") or "#" in view_first.id
    # source 域投影（mpv ASS）：源时间，供原生字幕命中。
    source_view = projected_cues(project, domain="source")
    assert all(c.start_ms >= 120_000 - 4000 for c in source_view)
    assert len(source_view) == len(expected)
    # 派生 id 可解析回源 id；命令查找作用于源 cue。
    from twobyteasr.timeline.studio_edit_sequence import source_cue_id_of
    from twobyteasr.timeline.studio_commands import cue_by_id
    assert source_cue_id_of(view_first.id) == source_first.id
    assert cue_by_id(project, view_first.id) is source_first


def test_restore_returns_full_view_without_losing_cues():
    from twobyteasr.timeline.studio_edit_commands import generate_edit_command, restore_full_sequence_command
    from twobyteasr.timeline.studio_edit_sequence import projected_cues

    project = _project(None)
    _accept(project, 120_000, 300_000)
    generate_edit_command(project).redo()
    snapshot = copy.deepcopy(project.cues)
    restore_full_sequence_command(project).redo()

    assert project.cues == snapshot  # 逐字段一致，无漂移/丢失/重复
    view = projected_cues(project, domain="timeline")
    assert view is project.cues  # identity 直通


def test_roundtrip_ten_times_is_stable():
    from twobyteasr.timeline.studio_edit_commands import generate_edit_command, restore_full_sequence_command

    project = _project(None)
    _accept(project, 120_000, 300_000)
    baseline = copy.deepcopy(project.cues)
    for _ in range(10):
        generate = generate_edit_command(project); generate.redo()
        assert len(project.cues) == len(baseline)
        restore = restore_full_sequence_command(project); restore.redo()
        restore.undo(); generate.undo()
    assert project.cues == baseline


def test_clip_mode_edit_survives_restore():
    from twobyteasr.timeline.studio_edit_commands import generate_edit_command, restore_full_sequence_command
    from twobyteasr.timeline.studio_edit_sequence import projected_cues, source_cue_id_of
    from twobyteasr.timeline.studio_commands import SetCueFieldsCommand

    project = _project(None)
    _accept(project, 120_000, 300_000)
    generate_edit_command(project).redo()
    view = projected_cues(project, domain="timeline")
    target = view[0]
    command = SetCueFieldsCommand(project, target.id, {"text": "人工改写"}, "编辑字幕")
    command.redo()
    restore_full_sequence_command(project).redo()
    source_cue = next(c for c in project.cues if c.id == source_cue_id_of(target.id))
    assert source_cue.text == "人工改写"  # 合法人工修改不被恢复操作抹掉


def test_clip_mode_save_reload_and_return():
    from twobyteasr.timeline.studio_edit_commands import generate_edit_command, restore_full_sequence_command
    from twobyteasr.projects.studio_project import load_project, save_project
    from twobyteasr.timeline.studio_edit_sequence import projected_cues

    project = _project(None)
    _accept(project, 120_000, 300_000)
    generate_edit_command(project).redo()
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "clip.2byteproj"
        save_project(project, path)
        loaded = load_project(path)
        # 剪辑状态持久化，但字幕全集仍在。
        assert len(loaded.cues) == 40
        view = projected_cues(loaded, domain="timeline")
        assert len(view) < 40
        restore_full_sequence_command(loaded).redo()
        assert projected_cues(loaded, domain="timeline") is loaded.cues


def test_multi_segment_and_boundary_and_duplicate():
    from twobyteasr.timeline.studio_edit_sequence import (
        VideoSegment, projected_cues, sequence_of, replace_runtime_sequence,
    )

    project = _project(None, cue_count=20, span_ms=600_000)
    # 两个非相邻段：[120,180) 与 [420,480)；重复使用同源 [120,180) 第三次。
    sequence = copy.deepcopy(sequence_of(project))
    base = sequence.segments[0]
    seg1 = VideoSegment(id="s1", source_path=base.source_path, source_in_ms=120_000, source_out_ms=180_000,
                        timeline_in_ms=0, timeline_out_ms=60_000)
    seg2 = VideoSegment(id="s2", source_path=base.source_path, source_in_ms=420_000, source_out_ms=480_000,
                        timeline_in_ms=60_000, timeline_out_ms=120_000)
    seg3 = VideoSegment(id="s3", source_path=base.source_path, source_in_ms=120_000, source_out_ms=180_000,
                        timeline_in_ms=120_000, timeline_out_ms=180_000)
    sequence.segments = [seg1, seg2, seg3]
    replace_runtime_sequence(project, sequence, validate=False)
    # 一条跨入点边界的字幕：源 [115,125)。
    from twobyteasr.projects.studio_project import StudioCue
    project.cues.append(StudioCue(id="edge", start_ms=115_000, end_ms=125_000, text="跨界", speaker_id="S01"))
    view = projected_cues(project, domain="timeline")
    edge_rows = [c for c in view if c.id.startswith("edge#")]
    assert len(edge_rows) == 2  # seg1 裁边 + seg3 重复使用，各一实例
    for cue in edge_rows:
        assert cue.end_ms - cue.start_ms == 5_000  # 只显示 [120,125) 裁边
    # seg2 的字幕按各自映射（不减第一个起点）。
    seg2_rows = [c for c in view if c.id.endswith("#s2")]
    assert all(60_000 <= c.start_ms < 120_000 for c in seg2_rows)
    # source 域去重：同源 cue 只留一个事件。
    source_view = projected_cues(project, domain="source")
    assert len([c for c in source_view if c.id.startswith("edge#")]) == 1
    # 全集未动。
    assert any(c.id == "edge" and c.start_ms == 115_000 for c in project.cues)


def test_export_matches_active_sequence_domain():
    from twobyteasr.timeline.studio_edit_commands import generate_edit_command
    from twobyteasr.exports.studio_subtitle_export import compile_srt, _compile_format

    project = _project(None)
    _accept(project, 120_000, 300_000)
    compile_srt(project.cues)  # 全集可编译
    generate_edit_command(project).redo()
    srt = _compile_format(project, "srt")
    first_time_line = next(line for line in srt.splitlines() if "-->" in line)
    assert first_time_line.startswith("00:00:") or first_time_line.startswith("00:0")
    ass = _compile_format(project, "ass")
    assert "Dialogue:" in ass


def test_revision_store_render_source_domain_and_persistence_full():
    from twobyteasr.timeline.studio_edit_commands import generate_edit_command
    from twobyteasr.projects.studio_revisions import StudioRevisionStore

    project = _project(None)
    _accept(project, 120_000, 300_000)
    generate_edit_command(project).redo()
    store = StudioRevisionStore(project)
    render_ids = {cue.id for cue in store.render.cues}
    # 渲染（mpv 域）只含投影；持久化含全集。
    assert len(store.render.cues) < 40
    assert len(store._cues) == 40
    # source 域投影时间不小于段入点减 cue 跨界容差。
    assert all(c.start_ms >= 116_000 for c in store.render.cues)
