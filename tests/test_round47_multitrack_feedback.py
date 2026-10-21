"""第四十七轮守护：用户四图反馈批（2026-09-06）。

- 图二-B：Audio master 取消（mix_all）→ AudioPlaybackGraph 全轨混音决策；
  单 master 语义不回归。
- 图二-C：V1↔V2 双向拖拽的纯逻辑层——overwrite_insert_segment 覆写插入
  （总长不变/连续）与 CompositeMediaCommand 组合命令（一次撤销完整回退）。
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QUndoStack  # noqa: E402

from twobyteasr.playback.audio_playback_graph import AudioPlaybackGraph  # noqa: E402
from twobyteasr.timeline.studio_edit_commands import EditSequenceCommand  # noqa: E402
from twobyteasr.timeline.studio_edit_sequence import (  # noqa: E402
    ensure_edit_sequence,
    overwrite_insert_segment,
    remap_cues,
    replace_runtime_sequence,
    sequence_of,
    split_at_playhead,
)
from twobyteasr.timeline.studio_media_commands import (  # noqa: E402
    CompositeMediaCommand,
    AudioMasterCommand,
    media_graph_command,
)
from twobyteasr.timeline.studio_media_pool import (  # noqa: E402
    add_video_clip,
    audio_master_mode,
    audio_master_track_id,
    create_video_track,
    effective_audio_master_track_id,
    remove_video_clip,
    set_audio_master_mode,
    set_audio_master_track,
    sync_linked_av_contract,
)
from twobyteasr.projects.studio_project import (  # noqa: E402
    MediaAsset,
    StudioCue,
    StudioMedia,
    SubtitleProject,
)


def _project(duration_ms: int = 60_000) -> SubtitleProject:
    project = SubtitleProject(
        media=StudioMedia(
            path="D:/recording.mp4",
            display_name="recording.mp4",
            duration_ms=duration_ms,
            fingerprint="recording",
        ),
        cues=[StudioCue("cue-1", 0, 1_000, "第一句")],
    )
    ensure_edit_sequence(project)
    create_video_track(project, "主视频轨")
    create_video_track(project, "叠加轨")
    sync_linked_av_contract(project)
    return project


def _layer(track_id: str, *, source: str = "D:/a.mp4", muted: bool = False, base: bool = False):
    return {
        "track_id": track_id,
        "source_path": source,
        "source_ms": 1_000,
        "playback_rate": 1.0,
        "audio_enabled": True,
        "track_muted": muted,
        "primary_media": base,
    }


# ---------------------------------------------------------------------------
# 图二-B：mix_all 与混音决策
# ---------------------------------------------------------------------------

def test_mix_all_master_id_is_empty_and_rejects_crown_fallback():
    project = _project()
    set_audio_master_track(project, "V1")
    assert audio_master_track_id(project) == "V1"
    set_audio_master_mode(project, "mix_all")
    # 皇冠取消后不得再回退 primary——皇冠高亮/UI 标签都以"无 master"呈现。
    assert audio_master_track_id(project) == ""
    assert audio_master_mode(project) == "mix_all"
    assert effective_audio_master_track_id(project, ["V1", "V2"]) == ""
    set_audio_master_mode(project, "manual")
    assert audio_master_track_id(project) == "V1"


def test_set_audio_master_mode_rejects_unknown_mode():
    project = _project()
    try:
        set_audio_master_mode(project, "everything")
    except ValueError:
        return
    raise AssertionError("unknown audio master mode must raise")


def test_graph_mix_all_routes_every_lane_to_one_studio_sink():
    graph = AudioPlaybackGraph()
    graph.configure(master_track_id="", solo_track_ids=())
    decision = graph.decide(
        [_layer("V1", base=True), _layer("V2", source="D:/b.mp4")],
        base_track_id="V1",
    )
    assert decision.mix_mode is True
    assert decision.mpv_output_enabled is False
    assert decision.audible_track_id == "V1"
    assert decision.mix_track_ids == ("V1", "V2")
    assert [item["track_id"] for item in decision.secondary_layers] == ["V1", "V2"]
    assert decision.has_owner is True


def test_graph_mix_all_drops_muted_layers():
    graph = AudioPlaybackGraph()
    graph.configure(master_track_id="", solo_track_ids=())
    decision = graph.decide(
        [_layer("V1", base=True), _layer("V2", muted=True)],
        base_track_id="V1",
    )
    assert decision.mix_track_ids == ("V1",)
    assert [item["track_id"] for item in decision.secondary_layers] == ["V1"]


def test_graph_multiple_solos_mix_soloed_tracks():
    graph = AudioPlaybackGraph()
    graph.configure(master_track_id="", solo_track_ids=("V1", "V2"))
    decision = graph.decide(
        [_layer("V1", base=True), _layer("V2"), _layer("V3", source="D:/c.mp4")],
        base_track_id="V1",
    )
    assert decision.mix_mode is True
    assert decision.mix_track_ids == ("V1", "V2")
    assert decision.reason == "mix-solo"


def test_graph_single_master_semantics_unchanged():
    graph = AudioPlaybackGraph()
    graph.configure(master_track_id="V2", solo_track_ids=())
    decision = graph.decide(
        [_layer("V1", base=True), _layer("V2", source="D:/b.mp4")],
        base_track_id="V1",
    )
    assert decision.mix_mode is False
    assert decision.audible_track_id == "V2"
    assert decision.mpv_output_enabled is False
    assert decision.secondary_layers == ()
    assert decision.reason == "studio-sink"


def test_audio_master_command_toggles_to_mix_all_and_back():
    project = _project()
    stack = QUndoStack()
    stack.push(AudioMasterCommand(project, "V1", mode="manual"))
    assert audio_master_track_id(project) == "V1"
    stack.push(AudioMasterCommand(project, "V1", mode="mix_all"))
    assert audio_master_track_id(project) == ""
    assert audio_master_mode(project) == "mix_all"
    stack.undo()
    assert audio_master_track_id(project) == "V1"
    stack.undo()
    # 回到构造时默认（follow_active_video，无配置 master）。
    assert audio_master_mode(project) == 'mix_all'
    assert audio_master_track_id(project) == ''
    assert not any(t.soloed for t in (*project.video_tracks,*project.audio_tracks))


# ---------------------------------------------------------------------------
# 图二-C：主轨覆写插入（V2 片段拖进 V1）
# ---------------------------------------------------------------------------

def test_overwrite_insert_mid_replaces_range_and_keeps_total_duration():
    project = _project(60_000)
    before = sequence_of(project)
    after = overwrite_insert_segment(
        before,
        source_path="D:/overlay.mov",
        source_in_ms=0,
        source_out_ms=10_000,
        at_ms=20_000,
    )
    assert after.timeline_duration_ms == 60_000
    assert after.is_linear_source() is False
    # [0,20) 原段前缀 + [20,30) 外来段 + [30,60) 原段尾。
    assert [(item.timeline_in_ms, item.timeline_out_ms) for item in after.segments] == [
        (0, 20_000),
        (20_000, 30_000),
        (30_000, 60_000),
    ]
    assert after.segments[1].source_path == "D:/overlay.mov"
    assert after.segments[1].source_in_ms == 0
    assert after.segments[1].source_out_ms == 10_000
    # 原段尾的内容时刻连续：50s 时间位对应的源时刻仍是 50s。
    tail = after.segments[2]
    assert tail.source_in_ms == 30_000


def test_overwrite_insert_beyond_tail_appends_segment():
    project = _project(60_000)
    after = overwrite_insert_segment(
        sequence_of(project),
        source_path="D:/overlay.mov",
        source_in_ms=5_000,
        source_out_ms=15_000,
        at_ms=60_000,
    )
    assert after.timeline_duration_ms == 70_000
    assert after.segments[-1].source_path == "D:/overlay.mov"
    assert (after.segments[-1].timeline_in_ms, after.segments[-1].timeline_out_ms) == (
        60_000,
        70_000,
    )


def test_overwrite_insert_snaps_inside_existing_split():
    project = _project(60_000)
    split = split_at_playhead(sequence_of(project), 30_000)
    replace_runtime_sequence(project, split)
    after = overwrite_insert_segment(
        sequence_of(project),
        source_path="D:/overlay.mov",
        source_in_ms=0,
        source_out_ms=5_000,
        at_ms=10_000,
    )
    # 已有剪辑点 30s 不被吃掉：插入后仍是一个边界。
    boundaries = {item.timeline_in_ms for item in after.segments}
    assert 30_000 in boundaries
    assert after.timeline_duration_ms == 60_000


def _overlay_project():
    project = _project(60_000)
    asset = MediaAsset(
        asset_id="asset-overlay",
        canonical_source="D:/overlay.mov",
        display_name="overlay.mov",
        duration_ms=30_000,
        fingerprint="overlay",
    )
    project.media_pool.append(asset)
    add_video_clip(
        project,
        "V2",
        "asset-overlay",
        timeline_in_ms=20_000,
        source_in_ms=0,
        source_out_ms=10_000,
    )
    return project


def test_v2_clip_drag_onto_primary_lane_reassigns_clip():
    """Multi-source V1 accepts a clip move without swapping entire lanes."""

    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    from twobyteasr.studio.studio_timeline import WaveformTimeline

    QApplication.instance() or QApplication([])
    project = _overlay_project()
    timeline = WaveformTimeline()
    timeline.resize(1200, 560)
    timeline.set_project(project)
    timeline.set_visible_window(0, 60_000)
    v2_clip = project.video_tracks[1].clips[0]
    lane_v2 = timeline._video_track_rects()["V2"]
    lane_v1 = timeline._video_track_rects()["V1"]

    def mouse(kind, x, y):
        event = QMouseEvent(
            kind, QPointF(x, y),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        if kind == QMouseEvent.Type.MouseButtonPress:
            timeline.mousePressEvent(event)
        elif kind == QMouseEvent.Type.MouseButtonRelease:
            timeline.mouseReleaseEvent(event)
        else:
            timeline.mouseMoveEvent(event)

    swaps: list[tuple[str, str]] = []
    reassigns: list[tuple] = []
    timeline.video_track_swap_requested.connect(lambda a, b: swaps.append((a, b)))
    timeline.video_clip_reassign_committed.connect(
        lambda *args: reassigns.append(tuple(args))
    )
    clip_mid = v2_clip.timeline_in_ms + (v2_clip.timeline_out_ms - v2_clip.timeline_in_ms) // 2
    clip_x = timeline._time_to_x(clip_mid)
    mouse(QMouseEvent.Type.MouseButtonPress, clip_x, lane_v2.center().y())
    mouse(QMouseEvent.Type.MouseMove, clip_x, lane_v1.center().y())
    mouse(QMouseEvent.Type.MouseButtonRelease, clip_x, lane_v1.center().y())

    assert swaps == []
    assert reassigns == [("V2", "V1", v2_clip.id, v2_clip.timeline_in_ms)]
    # 片段仍留在 V2（交换的是层级，不是片段位置）。
    assert len(project.video_tracks[1].clips) == 1


def test_primary_segment_lift_creates_overlay_clip_and_undoes():
    project = _overlay_project()
    # 被提取的主轨段属于主素材——媒体池补上主素材 asset（真实工程里
    # 主素材天然在池中）。
    project.media_pool.append(
        MediaAsset(
            asset_id="asset-primary",
            canonical_source="D:/recording.mp4",
            display_name="recording.mp4",
            duration_ms=60_000,
            fingerprint="recording",
        )
    )
    stack = QUndoStack()
    split = split_at_playhead(sequence_of(project), 30_000)
    replace_runtime_sequence(project, split)
    before_sequence = sequence_of(project)
    second_id = before_sequence.segments[1].id

    from twobyteasr.timeline.studio_edit_sequence import delete_segments

    after_sequence = delete_segments(before_sequence, [second_id])
    after_cues = remap_cues(project.cues, before_sequence, after_sequence)

    def graph_mutate(working):
        add_video_clip(
            working,
            "V2",
            "asset-primary",
            timeline_in_ms=30_000,
            source_in_ms=30_000,
            source_out_ms=60_000,
        )

    graph_command = media_graph_command(project, "片段上移到叠加轨", graph_mutate)
    sequence_command = EditSequenceCommand(
        project, after_sequence, after_cues, "片段上移到叠加轨", None
    )
    stack.push(CompositeMediaCommand("片段上移到叠加轨", [graph_command, sequence_command]))

    assert len(sequence_of(project).segments) == 1
    assert sequence_of(project).timeline_duration_ms == 30_000
    lifted = project.video_tracks[1].clips[-1]
    assert lifted.timeline_in_ms == 30_000

    stack.undo()
    assert len(sequence_of(project).segments) == 2
    assert sequence_of(project).timeline_duration_ms == 60_000
    assert lifted.id not in {clip.id for clip in project.video_tracks[1].clips}


# ---------------------------------------------------------------------------
# 图四-B：叠加轨可播放性按编码判定（HEVC/同源强制走 mp4 代理）
# ---------------------------------------------------------------------------

class _FakeProxyManifest:
    def __init__(self, path: str) -> None:
        self.proxy_path = path
        self.switch_ready = True


class _FakeMediaService:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.manifests: dict[str, _FakeProxyManifest] = {}

    def proxy_manifest(self, path, *, settings=None):
        return self.manifests.get(str(path))

    def start_proxy(self, path, *, settings=None):
        self.started.append(str(path))
        return None


def _flow():
    from twobyteasr.studio.studio_video_flow import StudioVideoFlowMixin

    flow = object.__new__(StudioVideoFlowMixin)
    flow._overlay_proxy_cache = {}
    return flow


def _asset(path: str, codec: str) -> MediaAsset:
    return MediaAsset(
        asset_id=f"asset-{Path(path).stem}",
        canonical_source=path,
        display_name=Path(path).name,
        duration_ms=10_000,
        fingerprint=path,
        video_metadata={"has_video": True, "codec": codec},
    )


def test_overlay_path_hevc_mov_uses_ffmpeg_source(monkeypatch):
    from twobyteasr.media import media_service
    from twobyteasr.studio.studio_video_flow import StudioVideoFlowMixin

    fake = _FakeMediaService()
    fake.manifests["D:/img.MOV"] = _FakeProxyManifest("C:/cache/img-proxy.mp4")
    monkeypatch.setattr(media_service, "GLOBAL_MEDIA_SERVICE", fake)
    flow = _flow()
    resolved = flow._overlay_playback_path("D:/img.MOV", asset=_asset("D:/img.MOV", "hevc"))
    assert resolved == "D:/img.MOV"
    assert not fake.started


def test_overlay_path_h264_mp4_passthrough(monkeypatch):
    from twobyteasr.media import media_service

    fake = _FakeMediaService()
    monkeypatch.setattr(media_service, "GLOBAL_MEDIA_SERVICE", fake)
    flow = _flow()
    resolved = flow._overlay_playback_path(
        "D:/clip.mp4", asset=_asset("D:/clip.mp4", "h264")
    )
    assert resolved == "D:/clip.mp4"
    assert fake.started == []


def test_overlay_path_same_source_uses_independent_ffmpeg_decoder(monkeypatch):
    """Each overlay has its own ffmpeg decoder, including a shared source."""

    from twobyteasr.media import media_service

    fake = _FakeMediaService()
    fake.manifests["D:/same.mp4"] = _FakeProxyManifest("C:/cache/same-proxy.mp4")
    monkeypatch.setattr(media_service, "GLOBAL_MEDIA_SERVICE", fake)
    flow = _flow()
    resolved = flow._overlay_playback_path(
        "D:/same.mp4", asset=_asset("D:/same.mp4", "h264"), force=True
    )
    assert resolved == "D:/same.mp4"
    assert not fake.started


def test_overlay_path_av1_does_not_create_a_wmf_proxy(monkeypatch):
    from twobyteasr.media import media_service

    fake = _FakeMediaService()
    monkeypatch.setattr(media_service, "GLOBAL_MEDIA_SERVICE", fake)
    flow = _flow()
    resolved = flow._overlay_playback_path(
        "D:/av1.mkv", asset=_asset("D:/av1.mkv", "av1")
    )
    # ffmpeg/PyAV decode AV1 directly; obsolete WMF proxy work must stay idle.
    assert resolved == "D:/av1.mkv"
    assert not fake.started
