"""Media-pool and multi-video-track operations for Subtitle Studio projects."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any, Mapping

from .studio_project import (
    MediaAsset,
    SubtitleProject,
    VideoClip,
    VideoTrack,
    sync_linked_av_contract,
)


def validate_media_graph(project: SubtitleProject) -> None:
    """Validate the media graph without traversing cues or visual recipes."""

    sync_linked_av_contract(project)
    asset_ids: set[str] = set()
    for asset in project.media_pool:
        asset.validate()
        if asset.asset_id in asset_ids:
            raise ValueError(f"duplicate media asset id {asset.asset_id}")
        asset_ids.add(asset.asset_id)
    track_ids: set[str] = set()
    clip_ids: set[str] = set()
    for index, track in enumerate(project.video_tracks):
        track.validate()
        if track.id in track_ids:
            raise ValueError(f"duplicate video track id {track.id}")
        track_ids.add(track.id)
        track.z_index = index
        for clip in track.clips:
            if clip.id in clip_ids:
                raise ValueError(f"duplicate video clip id {clip.id}")
            if clip.asset_id not in asset_ids:
                raise ValueError(
                    f"video clip {clip.id} references missing asset {clip.asset_id}"
                )
            clip_ids.add(clip.id)
    audio_track_ids: set[str] = set()
    audio_clip_ids: set[str] = set()
    for track in project.audio_tracks:
        track.validate()
        if track.id in audio_track_ids:
            raise ValueError(f"duplicate audio track id {track.id}")
        audio_track_ids.add(track.id)
        for clip in track.clips:
            if clip.id in audio_clip_ids:
                raise ValueError(f"duplicate audio clip id {clip.id}")
            if clip.asset_id not in asset_ids:
                raise ValueError(
                    f"audio clip {clip.id} references missing asset {clip.asset_id}"
                )
            audio_clip_ids.add(clip.id)
    for group in project.av_track_groups:
        group.validate()
        if group.video_track_id and group.video_track_id not in track_ids:
            raise ValueError(f"missing linked video track {group.video_track_id}")
        if group.audio_track_id not in audio_track_ids:
            raise ValueError(f"missing linked audio track {group.audio_track_id}")


def _asset_id(source: str, fingerprint: str = "") -> str:
    identity = str(fingerprint or Path(source).resolve())
    return "asset-" + hashlib.sha1(identity.encode("utf-8", "replace")).hexdigest()[:12]


def asset_by_id(project: SubtitleProject, asset_id: str) -> MediaAsset:
    for asset in project.media_pool:
        if asset.asset_id == asset_id:
            return asset
    raise KeyError(asset_id)


def track_by_id(project: SubtitleProject, track_id: str) -> VideoTrack:
    for track in project.video_tracks:
        if track.id == track_id:
            return track
    raise KeyError(track_id)


def primary_video_track_id(project: SubtitleProject) -> str:
    configured = str(project.studio_state.get("primary_video_track_id") or "")
    ids = {track.id for track in project.video_tracks}
    if configured in ids:
        return configured
    if "V1" in ids:
        return "V1"
    return project.video_tracks[0].id if project.video_tracks else ""


def media_graph_duration_ms(project: SubtitleProject) -> int:
    """Return the editable multi-track extent, including disabled clips."""

    linked_audio = {g.audio_track_id for g in project.av_track_groups if g.linked}
    tracks = list(project.video_tracks) + [t for t in project.audio_tracks if t.id not in linked_audio]
    return max(
        (
            int(clip.timeline_out_ms)
            for track in tracks
            for clip in track.clips
        ),
        default=0,
    )


def sync_primary_video_track_from_sequence(project: SubtitleProject, sequence) -> None:
    """Keep the legacy V1 edit surface and the media graph structurally aligned.

    EditSequence remains the compatibility truth for Razor/ripple operations.
    The primary VideoTrack is its project-schema projection; secondary tracks
    remain independent and are never rewritten here.
    """

    track_id = primary_video_track_id(project)
    if not track_id:
        return
    track = track_by_id(project, track_id)
    assets_by_source: dict[str, MediaAsset] = {}
    for asset in project.media_pool:
        try:
            key = str(Path(asset.canonical_source).resolve())
        except (OSError, ValueError):
            key = str(asset.canonical_source)
        assets_by_source[key] = asset

    originals = {clip.id: clip for clip in track.clips}
    projected: list[VideoClip] = []
    for segment in sequence.segments:
        source = str(segment.source_path or project.media.path or "")
        try:
            source_key = str(Path(source).resolve())
        except (OSError, ValueError):
            source_key = source
        asset = assets_by_source.get(source_key)
        if asset is None:
            asset = add_media_asset(
                project,
                source,
                duration_ms=max(
                    int(sequence.source_duration_ms),
                    int(segment.source_out_ms),
                ),
            )
            assets_by_source[source_key] = asset
        import copy
        original = originals.get(segment.id)
        if original is None:
            original = next((originals[key] for key in sequence.segment_lineage.get(segment.id, []) if key in originals), None)
        clip = copy.deepcopy(original) if original else VideoClip(id=str(segment.id), asset_id=asset.asset_id)
        clip.id, clip.asset_id = str(segment.id), asset.asset_id
        clip.source_in_ms, clip.source_out_ms = int(segment.source_in_ms), int(segment.source_out_ms)
        clip.timeline_in_ms, clip.timeline_out_ms = int(segment.timeline_in_ms), int(segment.timeline_out_ms)
        clip.playback_rate = segment.source_duration_ms / max(1, segment.duration_ms)
        projected.append(clip)
    track.clips = projected
    track.locked = bool(sequence.video_track_locked)
    sync_linked_av_contract(project)


def add_media_asset(
    project: SubtitleProject,
    source: str | Path,
    *,
    fingerprint: str = "",
    duration_ms: int = 0,
    video_metadata: Mapping[str, Any] | None = None,
    audio_metadata: Mapping[str, Any] | None = None,
    proxy_identity: str = "",
) -> MediaAsset:
    canonical = str(Path(source).resolve())
    for existing in project.media_pool:
        if fingerprint and existing.fingerprint == fingerprint:
            return existing
        try:
            same_source = Path(existing.canonical_source).resolve() == Path(canonical)
        except (OSError, ValueError):
            same_source = existing.canonical_source == canonical
        if same_source:
            return existing
    asset = MediaAsset(
        asset_id=_asset_id(canonical, fingerprint),
        canonical_source=canonical,
        display_name=Path(canonical).name,
        fingerprint=fingerprint,
        duration_ms=duration_ms,
        video_metadata=dict(video_metadata or {}),
        audio_metadata=dict(audio_metadata or {}),
        proxy_identity=proxy_identity,
        offline=not Path(canonical).is_file(),
    )
    asset.validate()
    project.media_pool.append(asset)
    sync_linked_av_contract(project, materialize_unreferenced_audio={asset.asset_id})
    return asset


def create_video_track(
    project: SubtitleProject,
    name: str | None = None,
    *,
    enabled: bool = True,
    muted: bool = False,
    locked: bool = False,
) -> VideoTrack:
    number = len(project.video_tracks) + 1
    existing = {track.id for track in project.video_tracks}
    track_id = f"V{number}"
    while track_id in existing:
        number += 1
        track_id = f"V{number}"
    track = VideoTrack(
        id=track_id,
        name=str(name or track_id),
        enabled=enabled,
        muted=muted,
        locked=locked,
        z_index=len(project.video_tracks),
    )
    project.video_tracks.append(track)
    sync_linked_av_contract(project)
    return track


def rename_video_track(project: SubtitleProject, track_id: str, name: str) -> None:
    if track_by_id(project, track_id).locked:
        raise ValueError('视频轨道已锁定，请先解锁')
    clean = str(name or "").strip()
    if not clean:
        raise ValueError("track name cannot be empty")
    track_by_id(project, track_id).name = clean


def add_video_clip(
    project: SubtitleProject,
    track_id: str,
    asset_id: str,
    *,
    timeline_in_ms: int | None = None,
    source_in_ms: int = 0,
    source_out_ms: int | None = None,
) -> VideoClip:
    track = track_by_id(project, track_id)
    if track.locked:
        raise ValueError(f"track {track_id} is locked")
    asset = asset_by_id(project, asset_id)
    source_in = max(0, int(source_in_ms))
    source_out = asset.duration_ms if source_out_ms is None else int(source_out_ms)
    source_out = min(asset.duration_ms or source_out, max(source_in, source_out))
    if source_out <= source_in:
        raise ValueError("clip source range is empty")
    if timeline_in_ms is None:
        timeline_in = max((clip.timeline_out_ms for clip in track.clips), default=0)
    else:
        timeline_in = max(0, int(timeline_in_ms))
    clip = VideoClip(
        id="clip-" + uuid.uuid4().hex[:12],
        asset_id=asset.asset_id,
        source_in_ms=source_in,
        source_out_ms=source_out,
        timeline_in_ms=timeline_in,
        timeline_out_ms=timeline_in + source_out - source_in,
    )
    clip.validate()
    track.clips.append(clip)
    track.clips.sort(key=lambda item: (item.timeline_in_ms, item.id))
    sync_linked_av_contract(project)
    return clip


def remove_video_clip(project: SubtitleProject, track_id: str, clip_id: str) -> None:
    track = track_by_id(project, track_id)
    if track.locked:
        raise ValueError(f"track {track_id} is locked")
    before = len(track.clips)
    track.clips = [clip for clip in track.clips if clip.id != clip_id]
    if len(track.clips) == before:
        raise KeyError(clip_id)
    sync_linked_av_contract(project)


def move_video_clip(project: SubtitleProject, track_id: str, clip_id: str, timeline_in_ms: int) -> None:
    track = track_by_id(project, track_id)
    if track.locked:
        raise ValueError(f"track {track_id} is locked")
    clip = next((item for item in track.clips if item.id == clip_id), None)
    if clip is None:
        raise KeyError(clip_id)
    duration = clip.timeline_out_ms - clip.timeline_in_ms
    clip.timeline_in_ms = max(0, int(timeline_in_ms))
    clip.timeline_out_ms = clip.timeline_in_ms + duration
    track.clips.sort(key=lambda item: (item.timeline_in_ms, item.id))
    sync_linked_av_contract(project)


def reassign_video_clip(
    project: SubtitleProject,
    source_track_id: str,
    target_track_id: str,
    clip_id: str,
    *,
    timeline_in_ms: int | None = None,
    collision_policy: str = "reject",
) -> None:
    """Move a video clip between lanes and migrate its linked audio group."""
    from .studio_clip_edit import reassign_clips_command
    if str(collision_policy or 'reject') != 'reject':
        raise ValueError('unsupported video-track collision policy')
    source = track_by_id(project, source_track_id)
    clip = next((c for c in source.clips if c.id == clip_id), None)
    if clip is None:
        raise KeyError(clip_id)
    command = reassign_clips_command(project, source_track_id, target_track_id, [clip_id],
        start=clip.timeline_in_ms if timeline_in_ms is None else timeline_in_ms)
    # This older mutation API retains references held by its caller; it still
    # uses the same validated graph/sequence as the undoable Studio operation.
    for original, after in ((project.video_tracks, command.after[0]), (project.audio_tracks, command.after[1])):
        clips = {c.id: c for t in original for c in t.clips}
        for track, result in zip(original, after):
            track.clips = []
            for value in result.clips:
                item = clips.get(value.id, value)
                item.__dict__.update(value.__dict__)
                track.clips.append(item)
    from .studio_edit_sequence import replace_runtime_sequence
    replace_runtime_sequence(project, command.after[3])
    if command.after_bindings is not None:
        project.studio_state['caption_bound_clip_ids'] = command.after_bindings


def trim_video_clip_edges(
    project: SubtitleProject,
    track_id: str,
    clip_id: str,
    *,
    timeline_in_ms: int | None = None,
    timeline_out_ms: int | None = None,
) -> None:
    """Trim on the project timeline while keeping source mapping consistent."""

    from .clip_time_mapper import clip_timing_from, trimmed_left, trimmed_right

    track = track_by_id(project, track_id)
    if track.locked:
        raise ValueError(f"track {track_id} is locked")
    clip = next((item for item in track.clips if item.id == clip_id), None)
    if clip is None:
        raise KeyError(clip_id)
    timing = clip_timing_from(clip)
    if timeline_in_ms is not None:
        timing = trimmed_left(timing, timeline_in_ms)
    if timeline_out_ms is not None:
        timing = trimmed_right(timing, timeline_out_ms)
    clip.timeline_in_ms = timing.timeline_in_ms
    clip.timeline_out_ms = timing.timeline_out_ms
    clip.source_in_ms = timing.source_in_ms
    clip.source_out_ms = timing.source_out_ms
    clip.validate()
    sync_linked_av_contract(project)


def trim_video_clip(
    project: SubtitleProject,
    track_id: str,
    clip_id: str,
    *,
    source_in_ms: int,
    source_out_ms: int,
) -> None:
    track = track_by_id(project, track_id)
    if track.locked:
        raise ValueError(f"track {track_id} is locked")
    clip = next((item for item in track.clips if item.id == clip_id), None)
    if clip is None:
        raise KeyError(clip_id)
    asset = asset_by_id(project, clip.asset_id)
    source_in = max(0, int(source_in_ms))
    source_out = min(asset.duration_ms or int(source_out_ms), int(source_out_ms))
    if source_out <= source_in:
        raise ValueError("clip source range is empty")
    clip.source_in_ms = source_in
    clip.source_out_ms = source_out
    clip.timeline_out_ms = clip.timeline_in_ms + source_out - source_in
    sync_linked_av_contract(project)


def set_video_clip_enabled(
    project: SubtitleProject,
    track_id: str,
    clip_id: str,
    enabled: bool,
) -> None:
    track = track_by_id(project, track_id)
    if track.locked:
        raise ValueError(f"track {track_id} is locked")
    clip = next((item for item in track.clips if item.id == clip_id), None)
    if clip is None:
        raise KeyError(clip_id)
    clip.enabled = bool(enabled)
    sync_linked_av_contract(project)


def reorder_video_track(project: SubtitleProject, track_id: str, new_index: int) -> None:
    track = track_by_id(project, track_id)
    old_index=project.video_tracks.index(track)
    new_index=max(0,min(int(new_index),len(project.video_tracks)-1))
    if any(t.locked for t in project.video_tracks[min(old_index,new_index):max(old_index,new_index)+1]):
        raise ValueError('涉及的轨道已锁定，请先解锁')
    project.video_tracks.remove(track)
    project.video_tracks.insert(max(0, min(int(new_index), len(project.video_tracks))), track)
    for index, item in enumerate(project.video_tracks):
        item.z_index = index
    sync_linked_av_contract(project)


def set_video_track_state(
    project: SubtitleProject,
    track_id: str,
    *,
    enabled: bool | None = None,
    muted: bool | None = None,
    soloed: bool | None = None,
    solo: bool | None = None,
    locked: bool | None = None,
) -> None:
    track = track_by_id(project, track_id)
    if track.locked and any(value is not None for value in (enabled,muted,soloed,solo)):
        raise ValueError('视频轨道已锁定，请先解锁')
    if enabled is not None:
        track.enabled = bool(enabled)
    if muted is not None:
        track.muted = bool(muted)
    if solo is not None:
        soloed = solo
    if soloed is not None:
        track.soloed = bool(soloed)
    if locked is not None:
        track.locked = bool(locked)
    group = next(
        (item for item in project.av_track_groups if item.video_track_id == track_id),
        None,
    )
    audio_track = next(
        (item for item in project.audio_tracks if group is not None and item.id == group.audio_track_id),
        None,
    )
    if audio_track is not None and group is not None and group.linked:
        if muted is not None:
            audio_track.muted = bool(muted)
        if soloed is not None:
            audio_track.soloed = bool(soloed)
        if locked is not None:
            audio_track.locked = bool(locked)
    if soloed is not None:
        # Retire the legacy duplicate representation only for the edited lane.
        aliases = {track_id, str(getattr(audio_track, 'id', ''))}
        project.studio_state['audio_solo_track_ids'] = [key for key in project.studio_state.get('audio_solo_track_ids', []) if key not in aliases]


def active_video_clip(project: SubtitleProject, timeline_ms: int) -> tuple[VideoTrack, VideoClip] | None:
    """Return the topmost enabled clip in the V1 -> Vn composition."""

    matches = active_video_clips(project, timeline_ms)
    return matches[-1] if matches else None


def active_video_clips(
    project: SubtitleProject,
    timeline_ms: int,
) -> list[tuple[VideoTrack, VideoClip]]:
    """Return active clips in stable bottom-to-top z-order."""

    time_ms = max(0, int(timeline_ms))
    ordered = sorted(project.video_tracks, key=lambda item: item.z_index)
    assets = {asset.asset_id: asset for asset in project.media_pool}
    matches: list[tuple[VideoTrack, VideoClip]] = []
    for track in ordered:
        if not track.enabled:
            continue
        for clip in reversed(track.clips):
            asset = assets.get(clip.asset_id)
            if (
                clip.enabled
                and asset is not None
                and not asset.offline
                and clip.timeline_in_ms <= time_ms < clip.timeline_out_ms
            ):
                matches.append((track, clip))
                break
    return matches


def update_video_clip_transform(
    project: SubtitleProject,
    track_id: str,
    clip_id: str,
    values: Mapping[str, Any],
) -> None:
    """Update composition only; source timing is intentionally untouched."""

    track = track_by_id(project, track_id)
    if track.locked:
        raise ValueError(f"track {track_id} is locked")
    clip = next((item for item in track.clips if item.id == clip_id), None)
    if clip is None:
        raise KeyError(clip_id)
    allowed = {
        "position_x", "position_y", "scale_x", "scale_y", "rotation",
        "opacity", "anchor_x", "anchor_y", "fit_mode",
    }
    for name, value in values.items():
        if name in allowed:
            setattr(clip.transform, name, value)
    clip.transform.validate()


def set_video_clip_effects(project: SubtitleProject, track_id: str, clip_id: str, effects: Mapping[str, object]) -> None:
    """ADR-0005（四十五轮）：写入素材效果（混合模式/绿幕抠像）。"""
    from .studio_project import normalize_clip_effects

    track = track_by_id(project, track_id)
    if track.locked:
        raise ValueError('轨道已锁定，请先解锁')
    clip = next((item for item in track.clips if item.id == clip_id), None)
    if clip is None:
        raise KeyError(clip_id)
    clip.effects = normalize_clip_effects(dict(effects))


def set_video_clip_audio_enabled(
    project: SubtitleProject,
    track_id: str,
    clip_id: str,
    enabled: bool,
) -> None:
    track = track_by_id(project, track_id)
    if track.locked:
        raise ValueError(f"track {track_id} is locked")
    clip = next((item for item in track.clips if item.id == clip_id), None)
    if clip is None:
        raise KeyError(clip_id)
    clip.audio_enabled = bool(enabled)
    sync_linked_av_contract(project)


_AUDIO_MASTER_MODES = {"follow_active_video", "manual", "mix_all"}


def audio_master_track_id(project: SubtitleProject) -> str:
    # Only an explicitly persisted manual choice has legacy exclusive meaning.
    # Automatic/default follow-video fields never become user Solo intent.
    if audio_master_mode(project) != 'manual':
        return ''
    return str(project.studio_state.get('audio_master_track_id') or '')


def audio_master_mode(project: SubtitleProject) -> str:
    return 'manual' if project.studio_state.get('audio_master_mode') == 'manual' else 'mix_all'


def set_audio_master_mode(project: SubtitleProject, mode: str) -> None:
    value = str(mode or "")
    if value not in _AUDIO_MASTER_MODES:
        raise ValueError(f"unsupported audio master mode: {mode}")
    project.studio_state["audio_master_mode"] = value


def effective_audio_master_track_id(
    project: SubtitleProject,
    visible_track_ids: list[str] | tuple[str, ...],
    *,
    selected_track_id: str = "",
) -> str:
    if audio_master_mode(project) == "mix_all":
        return ""
    if audio_master_mode(project) == "manual":
        return audio_master_track_id(project)
    visible = [str(item) for item in visible_track_ids if str(item)]
    selected = str(selected_track_id or "")
    if selected and selected in visible:
        return selected
    if visible:
        return visible[0]
    return audio_master_track_id(project)


def set_audio_master_track(project: SubtitleProject, track_id: str) -> None:
    track_by_id(project, track_id)
    project.studio_state["audio_master_track_id"] = str(track_id)
    # This legacy setter is an explicit user/command choice. Import and
    # hydration never call it; their default remains mix_all.
    project.studio_state["audio_master_mode"] = "manual"


def media_usage(project: SubtitleProject) -> dict[str, bool]:
    used = {
        clip.asset_id for track in project.video_tracks for clip in track.clips
    } | {
        clip.asset_id for track in project.audio_tracks for clip in track.clips
    }
    return {asset.asset_id: asset.asset_id in used for asset in project.media_pool}


def relink_media_asset(
    project: SubtitleProject,
    asset_id: str,
    source: str | Path,
    *,
    fingerprint: str = "",
    identity: Mapping[str, Any] | None = None,
) -> MediaAsset:
    asset = asset_by_id(project, asset_id)
    asset.canonical_source = str(Path(source).absolute())
    if fingerprint:
        asset.fingerprint = fingerprint
    asset.display_name = Path(asset.canonical_source).name
    # UI callers validate the candidate asynchronously before this mutation.
    asset.offline = False
    asset.relink_state = "relinked"
    asset.proxy_identity = ''
    if identity is not None:
        asset.duration_ms=max(0,int(identity.get('duration_ms') or 0))
        for kind in ('video','audio'):
            metadata=dict(getattr(asset,kind+'_metadata'))
            metadata.update(has_video=bool(identity.get('has_video'))) if kind=='video' else metadata.update(has_audio=bool(identity.get('has_audio')))
            for key in ('width','height','fps','rotation') if kind=='video' else ('sample_rate','channels'):
                metadata[key]=identity.get(key,0)
            metadata.update(codec=identity.get(kind+'_codec',''),timebase=identity.get(kind+'_timebase',''),
                start_time_ms=identity.get(kind+'_start_ms',0),first_pts_ms=identity.get(kind+'_first_pts_ms',0),
                source_start_ms=identity.get('source_start_ms',identity.get('container_start_ms',0)))
            if kind=='audio':metadata['sample_timeline_origin_ms']=identity.get('sample_timeline_origin_ms',metadata['start_time_ms'])
            setattr(asset,kind+'_metadata',metadata)
    return asset


def remove_unused_media(project: SubtitleProject) -> list[str]:
    usage = media_usage(project)
    removed = [asset.asset_id for asset in project.media_pool if not usage[asset.asset_id]]
    project.media_pool = [asset for asset in project.media_pool if usage[asset.asset_id]]
    sync_linked_av_contract(project)
    return removed
