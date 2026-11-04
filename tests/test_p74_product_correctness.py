import json

from twobyteasr.rendering.ass_compiler import compile_ass
from twobyteasr.projects.autosave_deadline import AutosaveDeadline
from twobyteasr.projects.project_dirty_guard import DirtyGuardChoice, ProjectDirtyGuard
from twobyteasr.playback.playback_clock import PlaybackClock
from twobyteasr.timeline.studio_media_pool import (
    active_video_clip,
    add_media_asset,
    add_video_clip,
    create_video_track,
    media_usage,
    move_video_clip,
    remove_unused_media,
    rename_video_track,
    reorder_video_track,
    set_video_track_state,
    trim_video_clip,
)
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    SubtitleProject,
    SubtitleStyle,
    load_project,
    save_project,
)
from twobyteasr.caption_style.style_resolution import resolve_cue_visual
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot


def _project(tmp_path):
    media = tmp_path / "first.mp4"
    media.write_bytes(b"first")
    return SubtitleProject(
        media=StudioMedia(
            path=str(media),
            display_name=media.name,
            duration_ms=10_000,
            fingerprint="first-fingerprint",
            width=1920,
            height=1080,
        ),
        cues=[StudioCue(id="c1", start_ms=0, end_ms=1000, text="空中打拳")],
    )


def test_legacy_single_media_project_migrates_to_pool_and_v1_roundtrip(tmp_path):
    project = _project(tmp_path)
    payload = project.to_dict()
    payload.pop("media_pool", None)
    payload.pop("video_tracks", None)
    path = tmp_path / "legacy.2byteproj"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    migrated = load_project(path)
    assert len(migrated.media_pool) == 1
    assert migrated.media_pool[0].canonical_source == migrated.media.path
    assert [track.id for track in migrated.video_tracks] == ["V1"]
    assert migrated.video_tracks[0].clips[0].asset_id == migrated.media_pool[0].asset_id

    reopened = load_project(save_project(migrated, tmp_path / "roundtrip.2byteproj"))
    assert reopened.media_pool == migrated.media_pool
    assert reopened.video_tracks == migrated.video_tracks


def test_media_pool_and_multi_track_operations_are_real_project_data(tmp_path):
    project = _project(tmp_path)
    project.validate()
    project.video_tracks[0].locked = False
    second = tmp_path / "second.mp4"
    second.write_bytes(b"second")
    asset = add_media_asset(project, second, fingerprint="second", duration_ms=8_000)
    v2 = create_video_track(project, "B-roll")
    clip = add_video_clip(project, v2.id, asset.asset_id, timeline_in_ms=1000)
    rename_video_track(project, v2.id, "反应画面")
    move_video_clip(project, v2.id, clip.id, 1500)
    trim_video_clip(project, v2.id, clip.id, source_in_ms=500, source_out_ms=4000)
    set_video_track_state(project, v2.id, muted=True, locked=True)
    reorder_video_track(project, v2.id, 0)

    project.validate()
    assert project.video_tracks[0].name == "反应画面"
    assert project.video_tracks[0].muted is True
    # Track index 0 is the bottom layer; V1 remains topmost after this reorder.
    assert active_video_clip(project, 1600)[0].id == "V1"
    assert media_usage(project)[asset.asset_id] is True
    assert remove_unused_media(project) == []


def test_continuous_edits_cannot_push_autosave_past_hard_interval():
    deadline = AutosaveDeadline(interval_seconds=120, idle_seconds=5)
    deadline.mark_dirty(0)
    assert deadline.delay_seconds(0) == 5
    for now in range(4, 120, 4):
        deadline.mark_dirty(now)
    assert deadline.delay_seconds(119) == 1
    assert deadline.due(120)


class _Stack:
    def __init__(self, clean=False):
        self.clean = clean

    def isClean(self):
        return self.clean


class _GuardPage:
    def __init__(self):
        self.project = object()
        self.undo_stack = _Stack(False)
        self._recovered_autosave_pending = False
        self.saved = 0

    def save(self):
        self.saved += 1
        self.undo_stack.clean = True


def test_dirty_guard_has_save_discard_cancel_semantics():
    page = _GuardPage()
    guard = ProjectDirtyGuard(page)
    assert guard.confirm("replace", choice_provider=lambda _action: DirtyGuardChoice.CANCEL) is False
    assert guard.confirm("replace", choice_provider=lambda _action: DirtyGuardChoice.DISCARD) is True
    assert guard.confirm("replace", choice_provider=lambda _action: DirtyGuardChoice.SAVE) is True
    assert page.saved == 1


def test_transform_delta_does_not_capture_or_restore_stale_appearance(tmp_path):
    project = _project(tmp_path)
    project.styles.append(SubtitleStyle(
        id="comic",
        name="Comic",
        font_family="Source Han Sans CN",
        primary_color="#FFCC00",
        outline_width=8,
    ))
    cue = project.cues[0]
    cue.style_id = "comic"
    cue.transform = {"position_x": 820, "position_y": 910, "scale_x": 112, "rotation": -3}
    resolved = resolve_cue_visual(project, cue)

    assert resolved.style.primary_color == "#FFCC00"
    assert resolved.style.outline_width == 8
    assert resolved.style.position_x == 820
    assert resolved.style.scale_x == 112
    assert "primary_color" not in cue.transform

    snapshot = build_visual_cue_snapshot(project, cue.id)
    assert snapshot.position_x == 820
    assert snapshot.rotation == -3
    ass = compile_ass(project)
    import re
    pos = re.search(r'\\pos\(([^,]+),([^\)]+)\)', ass)
    assert float(pos[1]) == 820
    cue.transform['position_y'] += 100
    moved_pos = re.search(r'\\pos\(([^,]+),([^\)]+)\)', compile_ass(project))
    assert float(moved_pos[2]) - float(pos[2]) == 100
    cue.transform['position_y'] -= 100
    assert r"\fscx112" in ass
    assert r"\frz-3" in ass


def test_speed_reset_matrix_reanchors_presentation_at_requested_rate():
    for fast_rate in (2.0, 1.5, 0.5):
        clock = PlaybackClock(now=0.0)
        clock.force_position(10_000, paused=False, playback_rate=1.0, now=0.0, reason="fixture")
        fast = clock.set_local_state(
            10_000,
            playback_rate=fast_rate,
            now=0.1,
            reason="local_speed_state",
        )
        assert fast.playback_rate == fast_rate
        assert clock.sample_presentation(now=0.3).presentation_media_ms == 10_000 + fast_rate * 200

        reset_position = clock.presentation_position_ms(now=0.3)
        reset = clock.set_local_state(
            reset_position,
            playback_rate=1.0,
            now=0.3,
            reason="local_speed_state",
        )
        assert reset.playback_rate == 1.0
        assert clock.sample_presentation(now=0.5).presentation_media_ms == reset_position + 200


def test_speed_reset_while_paused_and_rapid_changes_do_not_reuse_stale_rate():
    clock = PlaybackClock(now=0.0)
    clock.force_position(5_000, paused=False, playback_rate=2.0, now=0.0, reason="fixture")
    paused = clock.set_local_state(5_400, paused=True, now=0.2, reason="local_pause_state")
    assert paused.paused
    reset = clock.set_local_state(
        paused.presentation_media_ms,
        playback_rate=1.0,
        now=0.21,
        reason="local_speed_state",
    )
    assert reset.paused and reset.playback_rate == 1.0
    resumed = clock.set_local_state(
        reset.presentation_media_ms,
        paused=False,
        now=0.22,
        reason="local_pause_state",
    )
    assert clock.sample_presentation(now=0.42).presentation_media_ms == resumed.presentation_media_ms + 200

    for index, rate in enumerate((2.0, 1.5, 0.5, 2.0, 1.0), start=1):
        current = clock.presentation_position_ms(now=0.42 + index * 0.01)
        snapshot = clock.set_local_state(
            current,
            playback_rate=rate,
            now=0.42 + index * 0.01,
            reason="local_speed_state",
        )
        assert snapshot.playback_rate == rate
    assert clock.playback_rate == 1.0
