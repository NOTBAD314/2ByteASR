"""第三十轮守护：剪辑对位与播放时间域。

剪头（非线性 EditSequence）后，mpv 画布时钟/seek/EOF 必须留在源时间域：
时间轴总长不得 override 画布时长，否则对保留段的 seek 全被钳到时间轴长度内
（用户看到"剩下的五分钟是素材 0~5 分"+结尾反复卡顿）。
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.timeline.studio_edit_sequence import (
    delete_timeline_range,
    ensure_edit_sequence,
    replace_runtime_sequence,
    sequence_of,
)
from twobyteasr.timeline.studio_media_pool import sync_primary_video_track_from_sequence
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.timeline.studio_sequence_mapper import restore_source_seconds
from twobyteasr.studio.studio_ui import SubtitleStudioPage


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    def __call__(self, *args, **kwargs) -> None:
        self.calls.append((args, kwargs))

    @property
    def flat(self) -> list[tuple]:
        return [args for args, _kwargs in self.calls]


def _project_with_media(tmp_path: Path, duration_ms: int) -> SubtitleProject:
    media = tmp_path / "recording.mp4"
    media.write_bytes(b"mp4")
    project = SubtitleProject(
        media=StudioMedia(
            path=str(media),
            display_name=media.name,
            duration_ms=duration_ms,
            fingerprint="recording",
            width=1920,
            height=1080,
        ),
        cues=[StudioCue("cue-1", 0, 1_000, "字幕")],
    )
    project.validate()
    return project


def _head_trimmed_project(tmp_path: Path) -> SubtitleProject:
    """60s 素材剪掉前 30s：单段 source[30,60] 铺在 timeline[0,30]。"""

    project = _project_with_media(tmp_path, 60_000)
    sequence = ensure_edit_sequence(project)
    trimmed = delete_timeline_range(sequence, 0, 30_000)
    replace_runtime_sequence(project, trimmed)
    sync_primary_video_track_from_sequence(project, trimmed)
    return project


def _page(project: SubtitleProject) -> SubtitleStudioPage:
    page = SubtitleStudioPage()
    page.project = project
    # 测试不启动真 mpv；一个"活着"的桩让 _seek/_position_changed 走完整链。
    page.video.controller = SimpleNamespace(running=True, set_raw_overlay=_Recorder(), remove_overlay=_Recorder())
    return page


def test_mapped_sequence_keeps_source_domain_duration(tmp_path):
    _app()
    project = _head_trimmed_project(tmp_path)
    page = _page(project)

    page._refresh_edit_playback_state()

    assert page._playback_mode == "mapped"
    assert page.video._duration_override == 0.0
    assert page.video._duration == 60.0
    page.close_page()
    page.deleteLater()


def test_linear_sequence_keeps_timeline_duration_override(tmp_path):
    _app()
    project = _project_with_media(tmp_path, 60_000)
    ensure_edit_sequence(project)
    page = _page(project)

    page._refresh_edit_playback_state()

    assert page._playback_mode == "source"
    assert page.video._duration_override == 60.0
    assert page.video._duration == 60.0
    page.close_page()
    page.deleteLater()


def test_seek_timeline_zero_lands_on_retained_head(tmp_path):
    _app()
    project = _head_trimmed_project(tmp_path)
    page = _page(project)
    page._refresh_edit_playback_state()
    recorder = _Recorder()
    page.video.seek = recorder

    page._seek(0.0)

    assert recorder.flat == [(30.0,)]
    assert recorder.calls[0][1].get("accurate") is True
    assert recorder.calls[0][1].get("project_ms") == 0
    page.close_page()
    page.deleteLater()


def test_position_in_deleted_head_bridges_to_retained_segment(tmp_path):
    _app()
    project = _head_trimmed_project(tmp_path)
    page = _page(project)
    page._refresh_edit_playback_state()
    page.video._paused = True
    page.timeline.set_playhead(5_000)
    recorder = _Recorder()
    page.video.seek = recorder

    # mpv 停在源 10s（已删除区）：应桥接 seek 到保留段头 30s，而不是播头跳 10s。
    page._position_changed(10.0)

    assert recorder.flat == [(30.0,)]
    assert page.timeline.playhead_ms == 5_000
    page.close_page()
    page.deleteLater()


def test_position_past_last_segment_pauses_at_timeline_end(tmp_path):
    _app()
    project = _head_trimmed_project(tmp_path)
    page = _page(project)
    page._refresh_edit_playback_state()
    page.video._paused = False
    seek = _Recorder()
    set_paused = _Recorder()
    set_eof = _Recorder()
    page.video.seek = seek
    page.video.set_paused = set_paused
    page.video._set_eof = set_eof

    # mpv 越过最后一段 source_out（60s）：时间轴已到终点，不得继续播删除尾段。
    page._position_changed(60.5, _bypass_throttle=True)

    assert seek.flat == []
    assert set_paused.flat == [(True,)]
    assert set_eof.flat == []  # source EOF would reanchor to 60s, not the 30s project end
    assert page.video.at_eof
    assert page.timeline.playhead_ms == sequence_of(project).timeline_duration_ms
    page.close_page()
    page.deleteLater()


def test_eof_restart_seeks_timeline_zero_not_source_zero(tmp_path):
    _app()
    project = _head_trimmed_project(tmp_path)
    page = _page(project)
    page._refresh_edit_playback_state()
    page.video._eof_reached = True
    seek = _Recorder()
    set_paused = _Recorder()
    page.video.seek = seek
    page.video.set_paused = set_paused

    page._toggle_playback()

    assert seek.flat == [(30.0,)]
    assert set_paused.flat == [(False,)]
    page.close_page()
    page.deleteLater()


def test_restore_source_seconds_mapping(tmp_path):
    _app()
    project = _head_trimmed_project(tmp_path)
    sequence = sequence_of(project)

    assert restore_source_seconds(sequence, 0) == 30.0
    assert restore_source_seconds(sequence, 5_000) == 35.0
    assert restore_source_seconds(sequence, 29_999) == 59.999

    two_cuts = delete_timeline_range(sequence, 5_000, 15_000)
    # source[30,60] 再删 timeline[5,15] → 两段 source[30,35]+source[45,60]
    assert [item.source_in_ms for item in two_cuts.segments] == [30_000, 45_000]
    assert restore_source_seconds(two_cuts, 1_000) == 31.0
    assert restore_source_seconds(two_cuts, 11_000) == 51.0

    linear = ensure_edit_sequence(_project_with_media(tmp_path, 60_000))
    assert restore_source_seconds(linear, 15_000) == 15.0


def test_canvas_seek_seeds_clock_in_source_domain_for_primary_route(tmp_path):
    _app()
    project = _head_trimmed_project(tmp_path)
    page = _page(project)
    page._refresh_edit_playback_state()
    page.video.controller = SimpleNamespace(running=True, seek=_Recorder())

    # 主轨（未启用 clip 映射）时钟=源域：seek 门控种子必须是源目标，
    # 否则 mpv 源域观测会被 ack 门拒收 2.5s（播头冻结在乐观值）。
    page.video.seek(30.0, accurate=True, project_ms=0)
    assert page.video._playback_clock._seek_target_ms == 30_000.0

    # 副轨（multitrack）映射启用后时钟=项目域：种子保持 project_ms。
    page.video.set_project_time_mapping(
        enabled=True, timeline_in_ms=0, source_in_ms=30_000, playback_rate=1.0,
    )
    page.video.seek(45.0, accurate=True, project_ms=5_000)
    assert page.video._playback_clock._seek_target_ms == 5_000.0
    page.close_page()
    page.deleteLater()


def test_pending_seek_display_maps_source_target_to_timeline(tmp_path):
    _app()
    project = _head_trimmed_project(tmp_path)
    page = _page(project)
    page._refresh_edit_playback_state()
    page.video._paused = True
    clock = page.video._playback_clock
    # 模拟越界桥接 seek（源 45s、无 project_ms）挂起期间：
    # 播头显示必须映射到时间轴，而不是闪现源毫秒。
    clock.begin_seek(45_000.0)
    page._position_changed(40.2)

    assert page.timeline.playhead_ms == 15_000
    page.close_page()
    page.deleteLater()
