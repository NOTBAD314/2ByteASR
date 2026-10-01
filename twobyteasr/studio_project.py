"""Versioned Subtitle Studio project model and crash-safe persistence."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from PySide6.QtGui import QColor


PROJECT_SCHEMA_VERSION = 1
PROJECT_SUFFIX = ".2byteproj"
STUDIO_DATA_DIRNAME = "SubtitleStudioPreview"
PROJECT_ARCHIVE_DIRNAME = "2ByteASR Projects"
PROJECT_LIBRARY_DIRNAME = "Projects"

_SUBTITLE_TIMECODE_RE = re.compile(r"^(\d+):(\d{1,2}):(\d{1,2})[.,](\d{1,3})$")
_ASS_OVERRIDE_TAG_RE = re.compile(r"\{[^}]*\}")


def parse_subtitle_timecode_ms(value: str) -> int | None:
    """Parse ASS ``H:MM:SS.cc`` / SRT ``HH:MM:SS,mmm`` into milliseconds."""
    match = _SUBTITLE_TIMECODE_RE.match(str(value or "").strip())
    if match is None:
        return None
    hours, minutes, seconds, fraction = match.groups()
    fraction_ms = int(fraction) * {1: 100, 2: 10, 3: 1}[len(fraction)]
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + fraction_ms


def parse_ass_dialogue_line(line: str) -> tuple[int, int, str, str, str] | None:
    """Parse one ASS ``Dialogue:`` line into (start_ms, end_ms, style, actor, text).

    Text has override tags stripped and ``\\N`` line breaks flattened to
    spaces. Returns ``None`` for malformed lines.
    """
    fields = line.split(",", 9)
    if len(fields) < 10:
        return None
    start_ms = parse_subtitle_timecode_ms(fields[1])
    end_ms = parse_subtitle_timecode_ms(fields[2])
    if start_ms is None or end_ms is None:
        return None
    text = _ASS_OVERRIDE_TAG_RE.sub("", fields[9]).replace(r"\N", " ").strip()
    return start_ms, end_ms, fields[3].strip(), fields[4].strip(), text


class ProjectValidationError(ValueError):
    """Raised when a project cannot be safely loaded or saved."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_id(value: Any, field_name: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ProjectValidationError(f"{field_name} must not be empty")
    return cleaned


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _mapping(value: Any) -> dict[str, Any]:
    return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}


@dataclass
class StudioMedia:
    path: str
    display_name: str = ""
    duration_ms: int = 0
    fingerprint: str = ""
    width: int = 0
    height: int = 0

    def validate(self) -> None:
        self.path = str(self.path or "").strip()
        self.display_name = str(self.display_name or (Path(self.path).name if self.path else "未命名工程"))
        self.duration_ms = max(0, int(self.duration_ms or 0))
        self.fingerprint = str(self.fingerprint or "").strip()
        self.width = max(0, int(self.width or 0))
        self.height = max(0, int(self.height or 0))


@dataclass
class MediaAsset:
    """Stable project media identity independent from an absolute file path."""

    asset_id: str
    canonical_source: str
    display_name: str = ""
    fingerprint: str = ""
    duration_ms: int = 0
    video_metadata: dict[str, Any] = field(default_factory=dict)
    audio_metadata: dict[str, Any] = field(default_factory=dict)
    proxy_identity: str = ""
    offline: bool = False
    relink_state: str = "linked"

    def validate(self) -> None:
        self.asset_id = _clean_id(self.asset_id, "media_asset.asset_id")
        self.canonical_source = str(self.canonical_source or "").strip()
        self.display_name = str(
            self.display_name
            or (Path(self.canonical_source).name if self.canonical_source else self.asset_id)
        )
        self.fingerprint = str(self.fingerprint or "").strip()
        self.duration_ms = max(0, int(self.duration_ms or 0))
        self.video_metadata = _mapping(self.video_metadata)
        self.audio_metadata = _mapping(self.audio_metadata)
        self.proxy_identity = str(self.proxy_identity or "").strip()
        self.offline = bool(self.offline)
        self.relink_state = str(
            self.relink_state or ("offline" if self.offline else "linked")
        ).strip()
        if self.relink_state not in {"linked", "offline", "relinked", "proxy"}:
            self.relink_state = "offline" if self.offline else "linked"

    @classmethod
    def from_legacy(cls, media: StudioMedia) -> "MediaAsset":
        identity = media.fingerprint or str(Path(media.path)) or media.display_name
        asset_id = "asset-" + hashlib.sha1(identity.encode("utf-8", "replace")).hexdigest()[:12]
        asset = cls(
            asset_id=asset_id,
            canonical_source=media.path,
            display_name=media.display_name,
            fingerprint=media.fingerprint,
            duration_ms=media.duration_ms,
            video_metadata={"width": media.width, "height": media.height},
            offline=bool(media.path and not Path(media.path).is_file()),
        )
        asset.validate()
        return asset


@dataclass
class VideoTransform:
    """Clip-local composition transform in normalized canvas coordinates."""

    position_x: float = 0.5
    position_y: float = 0.5
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0
    opacity: float = 1.0
    anchor_x: float = 0.5
    anchor_y: float = 0.5
    fit_mode: str = "contain"

    def validate(self) -> None:
        self.position_x = max(-4.0, min(5.0, float(self.position_x)))
        self.position_y = max(-4.0, min(5.0, float(self.position_y)))
        self.scale_x = max(0.01, min(20.0, float(self.scale_x)))
        self.scale_y = max(0.01, min(20.0, float(self.scale_y)))
        self.rotation = float(self.rotation) % 360.0
        self.opacity = max(0.0, min(1.0, float(self.opacity)))
        self.anchor_x = max(0.0, min(1.0, float(self.anchor_x)))
        self.anchor_y = max(0.0, min(1.0, float(self.anchor_y)))
        self.fit_mode = str(self.fit_mode or "contain").strip().lower()
        if self.fit_mode not in {"contain", "cover", "stretch"}:
            self.fit_mode = "contain"


@dataclass
class VideoClip:
    id: str
    asset_id: str
    source_in_ms: int = 0
    source_out_ms: int = 0
    timeline_in_ms: int = 0
    timeline_out_ms: int = 0
    playback_rate: float = 1.0
    enabled: bool = True
    audio_enabled: bool = True
    transform: VideoTransform = field(default_factory=VideoTransform)
    # ADR-0005（四十五轮）：素材效果——混合模式 + 绿幕抠像。缺省空=无效果
    # （旧工程向后兼容）。序列化经 asdict 自动携带。
    effects: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        self.id = _clean_id(self.id, "video_clip.id")
        self.asset_id = _clean_id(self.asset_id, "video_clip.asset_id")
        self.source_in_ms = max(0, int(self.source_in_ms or 0))
        self.source_out_ms = max(self.source_in_ms, int(self.source_out_ms or 0))
        self.timeline_in_ms = max(0, int(self.timeline_in_ms or 0))
        self.playback_rate = max(0.01, min(8.0, float(self.playback_rate or 1.0)))
        expected_out = self.timeline_in_ms + int(
            round((self.source_out_ms - self.source_in_ms) / self.playback_rate)
        )
        self.timeline_out_ms = max(self.timeline_in_ms, int(self.timeline_out_ms or expected_out))
        # Integer source/project endpoints each quantize to milliseconds. A
        # split at a fractional rate must not move its shared project edge.
        if abs((self.timeline_out_ms - self.timeline_in_ms) * self.playback_rate - (self.source_out_ms - self.source_in_ms)) > max(1.0, self.playback_rate):
            self.timeline_out_ms = expected_out
        self.enabled = bool(self.enabled)
        self.audio_enabled = bool(self.audio_enabled)
        if isinstance(self.transform, Mapping):
            self.transform = VideoTransform(**dict(self.transform))
        self.transform.validate()
        self.effects = normalize_clip_effects(self.effects)


def normalize_clip_effects(value: object) -> dict[str, Any]:
    """素材效果契约（ADR-0005）：blendMode + chromaKey，全部字段钳制。"""
    effects = dict(value) if isinstance(value, Mapping) else {}
    blend = str(effects.get("blendMode") or "normal")
    if blend not in {"normal", "screen", "multiply", "overlay", "softLight", "addition"}:
        blend = "normal"
    effects["blendMode"] = blend
    raw_key = effects.get("chromaKey")
    key = dict(raw_key) if isinstance(raw_key, Mapping) else {}

    def _unit(name: str, default: float) -> float:
        try:
            return max(0.0, min(1.0, float(key.get(name, default) or 0.0)))
        except (TypeError, ValueError):
            return default

    color = str(key.get("color") or "#00FF00").strip()
    if not QColor.isValidColor(color):
        color = "#00FF00"
    effects["chromaKey"] = {
        "enabled": bool(key.get("enabled")),
        "color": color,
        "similarity": _unit("similarity", 0.32),
        "smoothness": _unit("smoothness", 0.10),
        "spillSuppression": bool(key.get("spillSuppression", True)),
    }
    return effects


@dataclass
class VideoTrack:
    id: str
    name: str
    clips: list[VideoClip] = field(default_factory=list)
    enabled: bool = True
    muted: bool = False
    soloed: bool = False
    locked: bool = False
    z_index: int = 0
    kind: str = "video"

    def validate(self) -> None:
        self.id = _clean_id(self.id, "video_track.id")
        self.name = str(self.name or self.id)
        self.enabled = bool(self.enabled)
        self.muted = bool(self.muted)
        self.soloed = bool(self.soloed)
        self.locked = bool(self.locked)
        self.z_index = int(self.z_index or 0)
        self.kind = str(self.kind or "video").strip().lower()
        if self.kind != "video":
            raise ProjectValidationError(f"video track {self.id} has invalid kind {self.kind}")
        seen: set[str] = set()
        for clip in self.clips:
            clip.validate()
            if clip.id in seen:
                raise ProjectValidationError(f"duplicate video clip id {clip.id}")
            seen.add(clip.id)
        self.clips.sort(key=lambda item: (item.timeline_in_ms, item.timeline_out_ms, item.id))


@dataclass
class AudioClip:
    """Timeline audio component linked to one source asset and, normally, one video clip."""

    id: str
    asset_id: str
    source_in_ms: int = 0
    source_out_ms: int = 0
    timeline_in_ms: int = 0
    timeline_out_ms: int = 0
    stream_index: int = 0
    linked_video_clip_id: str = ""
    link_group_id: str = ""
    enabled: bool = True
    playback_rate: float = 1.0
    gain_db: float = 0.0

    def validate(self) -> None:
        self.id = _clean_id(self.id, "audio_clip.id")
        self.asset_id = _clean_id(self.asset_id, "audio_clip.asset_id")
        self.source_in_ms = max(0, int(self.source_in_ms or 0))
        self.source_out_ms = max(self.source_in_ms, int(self.source_out_ms or 0))
        self.timeline_in_ms = max(0, int(self.timeline_in_ms or 0))
        self.playback_rate = max(0.01, min(8.0, float(self.playback_rate or 1.0)))
        self.gain_db = max(-60.0, min(24.0, float(self.gain_db or 0.0)))
        expected_out = self.timeline_in_ms + round((self.source_out_ms - self.source_in_ms) / self.playback_rate)
        self.timeline_out_ms = max(self.timeline_in_ms, int(self.timeline_out_ms or expected_out))
        if (not self.linked_video_clip_id
                and abs((self.timeline_out_ms - self.timeline_in_ms) * self.playback_rate
                        - (self.source_out_ms - self.source_in_ms)) > max(1.0, self.playback_rate)):
            self.timeline_out_ms = expected_out
        self.stream_index = max(0, int(self.stream_index or 0))
        self.linked_video_clip_id = str(self.linked_video_clip_id or "").strip()
        self.link_group_id = str(self.link_group_id or "").strip()
        self.enabled = bool(self.enabled)


@dataclass
class AudioTrack:
    id: str
    name: str
    clips: list[AudioClip] = field(default_factory=list)
    enabled: bool = True
    muted: bool = False
    soloed: bool = False
    locked: bool = False
    z_index: int = 0
    linked_video_track_id: str = ""
    kind: str = "audio"

    def validate(self) -> None:
        self.id = _clean_id(self.id, "audio_track.id")
        self.name = str(self.name or self.id)
        self.enabled = bool(self.enabled)
        self.muted = bool(self.muted)
        self.soloed = bool(self.soloed)
        self.locked = bool(self.locked)
        self.z_index = int(self.z_index or 0)
        self.linked_video_track_id = str(self.linked_video_track_id or "").strip()
        self.kind = str(self.kind or "audio").strip().lower()
        if self.kind != "audio":
            raise ProjectValidationError(f"audio track {self.id} has invalid kind {self.kind}")
        seen: set[str] = set()
        for clip in self.clips:
            clip.validate()
            if clip.id in seen:
                raise ProjectValidationError(f"duplicate audio clip id {clip.id}")
            seen.add(clip.id)
        self.clips.sort(key=lambda item: (item.timeline_in_ms, item.timeline_out_ms, item.id))


@dataclass
class AVTrackGroup:
    """Explicit identity link between a video lane and its compact audio lane."""

    id: str
    video_track_id: str = ""
    audio_track_id: str = ""
    linked: bool = True

    def validate(self) -> None:
        self.id = _clean_id(self.id, "av_track_group.id")
        self.video_track_id = str(self.video_track_id or "").strip()
        self.audio_track_id = _clean_id(self.audio_track_id, "av_track_group.audio_track_id")
        self.linked = bool(self.linked)


@dataclass
class StudioCue:
    id: str
    start_ms: int
    end_ms: int
    text: str
    speaker_id: str = "S00"
    style_id: str = "default"
    base_preset_id: str = ""
    effect_id: str = "none"
    original_text: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    raw_ass_override: str = ""
    appearance_override: dict[str, Any] = field(default_factory=dict)
    appearance_generation: int = 0
    transform: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        self.id = _clean_id(self.id, "cue.id")
        self.start_ms = int(self.start_ms)
        self.end_ms = int(self.end_ms)
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ProjectValidationError(
                f"cue {self.id} has invalid timing {self.start_ms}..{self.end_ms}"
            )
        self.text = str(self.text or "")
        self.speaker_id = str(self.speaker_id or "S00").strip() or "S00"
        self.style_id = str(self.style_id or "default").strip() or "default"
        self.base_preset_id = (
            str(self.base_preset_id or self.style_id).strip() or "default"
        )
        self.effect_id = str(self.effect_id or "none").strip() or "none"
        self.original_text = str(self.original_text or self.text)
        self.evidence_refs = _string_list(self.evidence_refs)
        self.raw_ass_override = str(self.raw_ass_override or "")
        self.appearance_override = _mapping(self.appearance_override)
        self.appearance_generation = max(0, int(self.appearance_generation or 0))
        self.transform = _mapping(self.transform)


@dataclass
class StudioSpeaker:
    id: str
    name: str = ""
    style_id: str = "default"
    color: str = ""
    # 三十八轮：diarization 说话人轨。hidden=从成片/导出/高保真预览中排除
    # （编辑器仍可见可改）；is_host=使用者人工指定主讲（无自动身份推断，
    # speaker id 是 file-local 的，不承诺跨文件同一人）。
    hidden: bool = False
    is_host: bool = False

    def validate(self) -> None:
        self.id = _clean_id(self.id, "speaker.id")
        self.name = str(self.name or self.id)
        self.style_id = str(self.style_id or "default").strip() or "default"
        self.color = str(self.color or "").strip()
        self.hidden = bool(self.hidden)
        self.is_host = bool(self.is_host)


@dataclass
class SubtitleStyle:
    id: str
    name: str
    font_family: str = "Microsoft YaHei UI"
    font_size: float = 52.0
    primary_color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_width: float = 3.0
    # Optional second stroke layer painted over the first (e.g. black outer +
    # white inner). Empty color / zero width keeps the single-layer contract.
    outline2_color: str = ""
    outline2_width: float = 0.0
    shadow: float = 1.0
    bold: bool = False
    italic: bool = False
    underline: bool = False
    back_color: str = "#000000"
    border_style: int = 1
    spacing: float = 0.0
    alignment: int = 2
    margin_l: int = 40
    margin_r: int = 40
    margin_v: int = 42
    position_x: int | None = None
    position_y: int | None = None
    scale_x: float = 100.0
    scale_y: float = 100.0

    # Optional authored face identity. Empty/0 preserves legacy family+bold;
    # resolved fallbacks are never written here.
    font_style_name: str = ""
    font_weight: int = 0
    font_file: str = ""
    font_face_index: int = 0

    def validate(self) -> None:
        self.id = _clean_id(self.id, "style.id")
        self.name = str(self.name or self.id)
        self.font_family = str(self.font_family or "Microsoft YaHei UI")
        self.font_style_name = str(self.font_style_name or "")
        self.font_weight = max(0, min(1000, int(self.font_weight)))
        self.font_file = str(self.font_file or "")
        self.font_face_index = max(0, int(self.font_face_index))
        from .font_metadata import restore_legacy_heavy_identity
        restore_legacy_heavy_identity(self)
        self.font_size = max(1.0, float(self.font_size))
        self.primary_color = str(self.primary_color or "#FFFFFF")
        self.outline_color = str(self.outline_color or "#000000")
        self.outline_width = max(0.0, float(self.outline_width))
        self.outline2_color = str(self.outline2_color or "")
        self.outline2_width = max(0.0, float(self.outline2_width))
        if self.outline2_width > 0 and not self.outline2_color:
            self.outline2_color = "#000000"
        self.shadow = max(0.0, float(self.shadow))
        self.bold = bool(self.bold)
        self.italic = bool(self.italic)
        self.underline = bool(self.underline)
        self.back_color = str(self.back_color or "#000000")
        self.border_style = 3 if int(self.border_style) == 3 else 1
        self.spacing = float(self.spacing)
        self.alignment = min(9, max(1, int(self.alignment)))
        self.margin_l = max(0, int(self.margin_l))
        self.margin_r = max(0, int(self.margin_r))
        self.margin_v = max(0, int(self.margin_v))
        self.position_x = None if self.position_x is None else max(0, int(self.position_x))
        self.position_y = None if self.position_y is None else max(0, int(self.position_y))
        self.scale_x = max(1.0, float(self.scale_x))
        self.scale_y = max(1.0, float(self.scale_y))

    def stroke_layers(self) -> list[dict[str, object]]:
        """Paint order for Qt/Remotion previews: outermost layer first."""
        layers = [{"color": self.outline_color, "width": float(self.outline_width)}]
        if self.outline2_width > 0:
            layers.append({"color": self.outline2_color or "#000000", "width": float(self.outline2_width)})
        return layers


def default_style() -> SubtitleStyle:
    from .font_system import resolve_source_han_heavy

    face = resolve_source_han_heavy()
    return SubtitleStyle(
        id="default",
        name="2Byte 默认",
        font_family=face.family,
        font_size=56.0,
        primary_color="#FFFFFF",
        outline_color="#000000",
        outline_width=4.0,
        shadow=2.0,
        bold=face.weight >= 700,
        alignment=2,
        margin_v=54,
    )


def default_effects() -> dict[str, Any]:
    from .effect_dsl import builtin_effects

    return builtin_effects()


def _normalized_media_source(value: str) -> str:
    source = str(value or "").strip()
    if not source:
        return ""
    try:
        return os.path.normcase(os.path.abspath(os.fspath(Path(source).expanduser())))
    except (OSError, ValueError):
        return os.path.normcase(source)


def _asset_has_audio(asset: MediaAsset) -> bool:
    metadata = _mapping(asset.audio_metadata)
    if "has_audio" in metadata:
        return bool(metadata.get("has_audio"))
    if (
        metadata.get("codec")
        or metadata.get("audio_codec")
        or int(metadata.get("channels", 0) or 0) > 0
        or int(metadata.get("sample_rate", 0) or 0) > 0
    ):
        return True
    # Recognition graphs often persist an empty audio_metadata object. Assume
    # audio until a later probe records has_audio=False so A1 is not dropped.
    return True


def _primary_media_asset(project: SubtitleProject) -> MediaAsset | None:
    wanted = _normalized_media_source(project.media.path)
    if wanted:
        for asset in project.media_pool:
            if _normalized_media_source(asset.canonical_source) == wanted:
                return asset
    primary_track = next((track for track in project.video_tracks if track.id == "V1"), None)
    if primary_track and primary_track.clips:
        asset_id = primary_track.clips[0].asset_id
        return next((asset for asset in project.media_pool if asset.asset_id == asset_id), None)
    return project.media_pool[0] if project.media_pool else None


def _repair_primary_media_contract(project: SubtitleProject) -> None:
    """Repair legacy split-brain StudioMedia/MediaAsset state without changing valid edits."""

    asset = _primary_media_asset(project)
    if asset is None:
        return
    if project.media.path and not asset.canonical_source:
        asset.canonical_source = project.media.path
    if asset.canonical_source and not project.media.path:
        project.media.path = asset.canonical_source
    if project.media.display_name and not asset.display_name:
        asset.display_name = project.media.display_name
    if asset.display_name and not project.media.display_name:
        project.media.display_name = asset.display_name
    if project.media.fingerprint and not asset.fingerprint:
        asset.fingerprint = project.media.fingerprint
    if asset.fingerprint and not project.media.fingerprint:
        project.media.fingerprint = asset.fingerprint
    sequence = _mapping(project.edit_sequence)
    duration_ms = max(
        int(project.media.duration_ms or 0),
        int(asset.duration_ms or 0),
        int(sequence.get("source_duration_ms", 0) or 0),
    )
    for segment in sequence.get("segments", ()) if isinstance(sequence.get("segments"), list) else ():
        if not isinstance(segment, Mapping):
            continue
        duration_ms = max(
            duration_ms,
            int(segment.get("source_out_ms", 0) or 0),
            int(segment.get("timeline_out_ms", 0) or 0),
        )
    if duration_ms:
        project.media.duration_ms = duration_ms
        asset.duration_ms = duration_ms
    video_metadata = _mapping(asset.video_metadata)
    if project.media.width and not int(video_metadata.get("width", 0) or 0):
        video_metadata["width"] = int(project.media.width)
    if project.media.height and not int(video_metadata.get("height", 0) or 0):
        video_metadata["height"] = int(project.media.height)
    project.media.width = max(int(project.media.width or 0), int(video_metadata.get("width", 0) or 0))
    project.media.height = max(int(project.media.height or 0), int(video_metadata.get("height", 0) or 0))
    asset.video_metadata = video_metadata

    # Only expand the zero-length migration artifact. A real user trim remains untouched.
    for track in project.video_tracks:
        for clip in track.clips:
            if clip.asset_id != asset.asset_id or duration_ms <= 0:
                continue
            if clip.source_out_ms <= clip.source_in_ms and clip.timeline_out_ms <= clip.timeline_in_ms:
                clip.source_out_ms = clip.source_in_ms + duration_ms
                clip.timeline_out_ms = clip.timeline_in_ms + duration_ms

    sequence = _mapping(project.edit_sequence)
    if sequence:
        if project.media.path and not str(sequence.get("source_path") or "").strip():
            sequence["source_path"] = project.media.path
        if duration_ms and int(sequence.get("source_duration_ms", 0) or 0) <= 0:
            sequence["source_duration_ms"] = duration_ms
        for segment in sequence.get("segments", ()) if isinstance(sequence.get("segments"), list) else ():
            if not isinstance(segment, dict):
                continue
            if project.media.path and not str(segment.get("source_path") or "").strip():
                segment["source_path"] = project.media.path
            source_in = max(0, int(segment.get("source_in_ms", 0) or 0))
            source_out = max(source_in, int(segment.get("source_out_ms", 0) or 0))
            timeline_in = max(0, int(segment.get("timeline_in_ms", 0) or 0))
            timeline_out = max(timeline_in, int(segment.get("timeline_out_ms", 0) or 0))
            if duration_ms and source_out <= source_in and timeline_out <= timeline_in:
                segment["source_out_ms"] = source_in + duration_ms
                segment["timeline_out_ms"] = timeline_in + duration_ms
        object.__setattr__(project, "edit_sequence", sequence)


def _audio_track_number(track_id: str) -> int:
    match = re.fullmatch(r"A(\d+)", str(track_id or ""), flags=re.IGNORECASE)
    return int(match.group(1)) if match else 0


def _next_audio_track_id(project: SubtitleProject, preferred: int = 0) -> str:
    used = {track.id for track in project.audio_tracks}
    if preferred > 0 and f"A{preferred}" not in used:
        return f"A{preferred}"
    index = max([_audio_track_number(item) for item in used] + [0]) + 1
    while f"A{index}" in used:
        index += 1
    return f"A{index}"


def _ensure_linked_av_contract(project: SubtitleProject, *, materialize_unreferenced_audio=False) -> None:
    """Materialize explicit V/A lane identity and keep linked clip edits in lockstep."""

    valid_video_ids = {track.id for track in project.video_tracks}
    removed_audio_ids = {
        group.audio_track_id
        for group in project.av_track_groups
        if group.linked and group.video_track_id and group.video_track_id not in valid_video_ids
    }
    project.av_track_groups = [
        group
        for group in project.av_track_groups
        if not group.video_track_id or group.video_track_id in valid_video_ids
    ]
    if removed_audio_ids:
        project.audio_tracks = [
            track for track in project.audio_tracks
            if track.id not in removed_audio_ids
        ]
    assets = {asset.asset_id: asset for asset in project.media_pool}
    audio_tracks = {track.id: track for track in project.audio_tracks}
    group_by_video = {
        group.video_track_id: group
        for group in project.av_track_groups
        if group.video_track_id
    }
    detached_tracks = {g.audio_track_id for g in project.av_track_groups if not g.linked}
    detached_clip_ids = {c.linked_video_clip_id for t in project.audio_tracks
                         if t.id in detached_tracks for c in t.clips if c.linked_video_clip_id}
    for video_index, video_track in enumerate(project.video_tracks, 1):
        group = group_by_video.get(video_track.id)
        audio_track = audio_tracks.get(group.audio_track_id) if group else None
        # Detached audio owns its timing/content. Validation must not recreate,
        # trim or delete its clips when the former video changes.
        if group is not None and not group.linked:
            continue
        if audio_track is None:
            audio_id = _next_audio_track_id(project, video_index)
            audio_track = AudioTrack(
                id=audio_id,
                name=audio_id,
                linked_video_track_id=video_track.id,
                z_index=video_index - 1,
            )
            project.audio_tracks.append(audio_track)
            audio_tracks[audio_id] = audio_track
            if group is None:
                group = AVTrackGroup(
                    id=f"av-{video_track.id.lower()}-{audio_id.lower()}",
                    video_track_id=video_track.id,
                    audio_track_id=audio_id,
                    linked=True,
                )
                project.av_track_groups.append(group)
                group_by_video[video_track.id] = group
            else:
                group.audio_track_id = audio_id
        audio_track.linked_video_track_id = video_track.id
        existing_by_video = {
            clip.linked_video_clip_id: clip
            for clip in audio_track.clips
            if clip.linked_video_clip_id
        }
        video_clip_ids = {clip.id for clip in video_track.clips}
        audio_track.clips = [
            clip for clip in audio_track.clips
            if not clip.linked_video_clip_id or clip.linked_video_clip_id in video_clip_ids
        ]
        for video_clip in video_track.clips:
            if video_clip.id in detached_clip_ids:
                continue
            asset = assets.get(video_clip.asset_id)
            if asset is None or not _asset_has_audio(asset):
                continue
            audio_clip = existing_by_video.get(video_clip.id)
            if audio_clip is None:
                audio_clip = AudioClip(
                    id=f"audio-{video_clip.id}",
                    asset_id=video_clip.asset_id,
                    linked_video_clip_id=video_clip.id,
                    link_group_id=group.id,
                )
                audio_track.clips.append(audio_clip)
            if group.linked:
                audio_clip.asset_id = video_clip.asset_id
                audio_clip.source_in_ms = video_clip.source_in_ms
                audio_clip.source_out_ms = video_clip.source_out_ms
                audio_clip.timeline_in_ms = video_clip.timeline_in_ms
                audio_clip.timeline_out_ms = video_clip.timeline_out_ms
                audio_clip.playback_rate = video_clip.playback_rate
                audio_clip.link_group_id = group.id
        # enabled belongs to the user; validation must not unmute/reenable it.

    # Pure-audio assets receive a standalone compact lane and no fake video lane.
    # Allocation belongs to import/legacy hydration, not graph validation.
    # Otherwise deleting a track would recreate it from the retained asset.
    if not materialize_unreferenced_audio:return
    video_asset_ids = {clip.asset_id for track in project.video_tracks for clip in track.clips}
    audio_asset_ids = {clip.asset_id for track in project.audio_tracks for clip in track.clips}
    for asset in project.media_pool:
        if materialize_unreferenced_audio is not True and asset.asset_id not in materialize_unreferenced_audio:continue
        video_metadata = _mapping(asset.video_metadata)
        # Missing dimensions are unknown, not evidence of pure audio. A
        # metadata-less video import must not gain a duplicate standalone A.
        has_video = video_metadata.get("has_video") is not False
        if not _asset_has_audio(asset) or asset.asset_id in video_asset_ids or asset.asset_id in audio_asset_ids:
            continue
        if has_video:
            continue
        audio_id = _next_audio_track_id(project)
        track = AudioTrack(id=audio_id, name=audio_id, z_index=len(project.audio_tracks))
        if asset.duration_ms:
            track.clips.append(AudioClip(
                id=f"audio-{asset.asset_id}",
                asset_id=asset.asset_id,
                source_out_ms=asset.duration_ms,
                timeline_out_ms=asset.duration_ms,
            ))
        project.audio_tracks.append(track)


def sync_linked_av_contract(project: SubtitleProject, *, materialize_unreferenced_audio=False) -> None:
    """Public mutation boundary used by media commands and timeline edits."""

    _ensure_linked_av_contract(project, materialize_unreferenced_audio=materialize_unreferenced_audio)


def hydrate_media_contract(
    project: SubtitleProject,
    identity: Mapping[str, Any],
    *,
    source_path: str | os.PathLike[str] | None = None,
    asset_id: str = "",
) -> MediaAsset:
    """Apply one probe snapshot to StudioMedia, MediaAsset, clips and linked audio lanes."""

    source = str(Path(source_path or identity.get("source_path") or identity.get("path") or project.media.path).expanduser().resolve())
    target = next((asset for asset in project.media_pool if asset.asset_id == asset_id), None) if asset_id else None
    if target is None:
        normalized = _normalized_media_source(source)
        target = next(
            (asset for asset in project.media_pool if _normalized_media_source(asset.canonical_source) == normalized),
            None,
        )
    if target is None:
        seed = str(identity.get("fingerprint") or source)
        target = MediaAsset(
            asset_id="asset-" + hashlib.sha1(seed.encode("utf-8", "replace")).hexdigest()[:12],
            canonical_source=source,
        )
        project.media_pool.append(target)
    duration_ms = max(0, int(identity.get("duration_ms", 0) or 0))
    target.canonical_source = source
    target.display_name = Path(source).name
    target.fingerprint = str(identity.get("fingerprint") or target.fingerprint)
    target.duration_ms = duration_ms or target.duration_ms
    target.video_metadata = {
        "has_video": bool(identity.get("has_video")),
        "codec": str(identity.get("video_codec") or ""),
        "width": max(0, int(identity.get("width", 0) or 0)),
        "height": max(0, int(identity.get("height", 0) or 0)),
        "fps": max(0.0, float(identity.get("fps", 0.0) or 0.0)),
        "timebase": str(identity.get("video_timebase") or identity.get("timebase") or ""),
        "rotation": int(identity.get("rotation", 0) or 0),
        "start_time_ms": float(identity.get("video_start_ms", 0.0) or 0.0),
        "first_pts_ms": float(identity.get("video_first_pts_ms", 0.0) or 0.0),
        "best_effort_timestamp_ms": float(identity.get("video_best_effort_timestamp_ms", 0.0) or 0.0),
        "source_start_ms": float(identity.get("source_start_ms", identity.get("container_start_ms", identity.get("format_start_ms", 0.0))) or 0.0),
    }
    target.audio_metadata = {
        "has_audio": bool(identity.get("has_audio")),
        "codec": str(identity.get("audio_codec") or ""),
        "sample_rate": max(0, int(identity.get("sample_rate", 0) or 0)),
        "channels": max(0, int(identity.get("channels", 0) or 0)),
        "timebase": str(identity.get("audio_timebase") or identity.get("timebase") or ""),
        "stream_index": max(0, int(identity.get("audio_stream_index", 0) or 0)),
        "audio_stream_index": max(0, int(identity.get("audio_stream_index", 0) or 0)),
        "start_time_ms": float(identity.get("audio_start_ms", 0.0) or 0.0),
        "first_pts_ms": float(identity.get("audio_first_pts_ms", 0.0) or 0.0),
        "best_effort_timestamp_ms": float(identity.get("audio_best_effort_timestamp_ms", 0.0) or 0.0),
        "sample_timeline_origin_ms": float(identity.get("sample_timeline_origin_ms", identity.get("audio_start_ms", 0.0)) or 0.0),
        "source_start_ms": float(identity.get("source_start_ms", identity.get("container_start_ms", identity.get("format_start_ms", 0.0))) or 0.0),
    }
    project.studio_state["media_time_mapping"] = {
        "container_start_ms": float(identity.get("container_start_ms", identity.get("format_start_ms", 0.0)) or 0.0),
        "source_start_ms": float(identity.get("source_start_ms", identity.get("container_start_ms", identity.get("format_start_ms", 0.0))) or 0.0),
        "video_start_ms": float(identity.get("video_start_ms", 0.0) or 0.0),
        "audio_start_ms": float(identity.get("audio_start_ms", 0.0) or 0.0),
        "duration_ms": int(target.duration_ms or 0),
        "video_timebase": str(identity.get("video_timebase") or identity.get("timebase") or ""),
        "audio_timebase": str(identity.get("audio_timebase") or identity.get("timebase") or ""),
        "sample_rate": int(identity.get("sample_rate", 0) or 0),
        "sample_timeline_origin_ms": float(identity.get("sample_timeline_origin_ms", identity.get("audio_start_ms", 0.0)) or 0.0),
    }
    target.offline = False
    target.relink_state = "relinked" if target.fingerprint else "linked"

    primary = _primary_media_asset(project)
    if primary is None or primary.asset_id == target.asset_id or _normalized_media_source(project.media.path) == _normalized_media_source(source):
        project.media.path = source
        project.media.display_name = Path(source).name
        project.media.duration_ms = target.duration_ms
        project.media.fingerprint = target.fingerprint
        project.media.width = int(target.video_metadata.get("width", 0) or 0)
        project.media.height = int(target.video_metadata.get("height", 0) or 0)
    _repair_primary_media_contract(project)
    # Re-probing an existing asset must not restore a deliberately deleted lane.
    _ensure_linked_av_contract(project)
    return target


@dataclass
class SubtitleProject:
    media: StudioMedia
    media_pool: list[MediaAsset] = field(default_factory=list)
    video_tracks: list[VideoTrack] = field(default_factory=list)
    audio_tracks: list[AudioTrack] = field(default_factory=list)
    av_track_groups: list[AVTrackGroup] = field(default_factory=list)
    cues: list[StudioCue] = field(default_factory=list)
    speakers: list[StudioSpeaker] = field(default_factory=list)
    styles: list[SubtitleStyle] = field(default_factory=lambda: [default_style()])
    effects: dict[str, Any] = field(default_factory=default_effects)
    style_recipes: dict[str, Any] = field(default_factory=dict)
    generation_metadata: dict[str, Any] = field(default_factory=dict)
    asr_evidence: dict[str, Any] = field(default_factory=dict)
    glossary_ids: list[str] = field(default_factory=list)
    edit_history: list[dict[str, Any]] = field(default_factory=list)
    render_settings: dict[str, Any] = field(default_factory=dict)
    report_path: str = ""
    original_outputs: dict[str, str] = field(default_factory=dict)
    studio_state: dict[str, Any] = field(default_factory=dict)
    edit_sequence: dict[str, Any] = field(default_factory=dict)
    project_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    schema_version: int = PROJECT_SCHEMA_VERSION

    def __setattr__(self, name: str, value: Any) -> None:
        """Invalidate only the runtime sequence on an external schema replace.

        Normal persistence uses a guard so serializing the canonical runtime
        does not tear down its indexes.  This keeps direct compatibility
        assignments (older tests/importers) correct without polling/comparing a
        full dict on every read.
        """

        if name == "edit_sequence" and not bool(
            getattr(self, "_persisting_edit_sequence", False)
        ):
            self.__dict__.pop("_edit_sequence_runtime", None)
            state = self.__dict__.get("_studio_state_runtime")
            if state is not None:
                state._sequence_runtime = None
        object.__setattr__(self, name, value)

    def validate(self) -> None:
        if int(self.schema_version) != PROJECT_SCHEMA_VERSION:
            raise ProjectValidationError(
                f"unsupported project schema_version {self.schema_version}"
            )
        initialize_tracks = not self.video_tracks and not self.audio_tracks and not _mapping(self.edit_sequence).get('empty_timeline',False)
        self.project_id = _clean_id(self.project_id, "project_id")
        self.media.validate()
        if not self.media_pool and (self.media.path or self.media.duration_ms):
            self.media_pool = [MediaAsset.from_legacy(self.media)]
        asset_ids: set[str] = set()
        for asset in self.media_pool:
            asset.validate()
            if asset.asset_id in asset_ids:
                raise ProjectValidationError(f"duplicate media asset id {asset.asset_id}")
            asset_ids.add(asset.asset_id)
        if not self.video_tracks and self.media_pool and not _mapping(self.edit_sequence).get('empty_timeline',False):
            asset = self.media_pool[0]
            clip_id = "clip-" + hashlib.sha1(asset.asset_id.encode("utf-8")).hexdigest()[:12]
            self.video_tracks = [VideoTrack(
                id="V1",
                name="V1",
                clips=[VideoClip(
                    id=clip_id,
                    asset_id=asset.asset_id,
                    source_in_ms=0,
                    source_out_ms=asset.duration_ms,
                    timeline_in_ms=0,
                    timeline_out_ms=asset.duration_ms,
                )],
                locked=bool(_mapping(self.edit_sequence).get("video_track_locked", True)),
                z_index=0,
            )]
        track_ids: set[str] = set()
        clip_ids: set[str] = set()
        for index, track in enumerate(self.video_tracks):
            track.validate()
            if track.id in track_ids:
                raise ProjectValidationError(f"duplicate video track id {track.id}")
            track_ids.add(track.id)
            track.z_index = index if track.z_index < 0 else track.z_index
            for clip in track.clips:
                if clip.id in clip_ids:
                    raise ProjectValidationError(f"duplicate video clip id {clip.id}")
                if clip.asset_id not in asset_ids:
                    raise ProjectValidationError(
                        f"video clip {clip.id} references missing asset {clip.asset_id}"
                    )
                clip_ids.add(clip.id)
        _repair_primary_media_contract(self)
        _ensure_linked_av_contract(self, materialize_unreferenced_audio=initialize_tracks)
        audio_track_ids: set[str] = set()
        audio_clip_ids: set[str] = set()
        for index, track in enumerate(self.audio_tracks):
            track.validate()
            if track.id in audio_track_ids:
                raise ProjectValidationError(f"duplicate audio track id {track.id}")
            audio_track_ids.add(track.id)
            track.z_index = index if track.z_index < 0 else track.z_index
            for clip in track.clips:
                if clip.id in audio_clip_ids:
                    raise ProjectValidationError(f"duplicate audio clip id {clip.id}")
                if clip.asset_id not in asset_ids:
                    raise ProjectValidationError(
                        f"audio clip {clip.id} references missing asset {clip.asset_id}"
                    )
                audio_clip_ids.add(clip.id)
        group_ids: set[str] = set()
        for group in self.av_track_groups:
            group.validate()
            if group.id in group_ids:
                raise ProjectValidationError(f"duplicate AV track group id {group.id}")
            if group.video_track_id and group.video_track_id not in track_ids:
                raise ProjectValidationError(
                    f"AV track group {group.id} references missing video track {group.video_track_id}"
                )
            if group.audio_track_id not in audio_track_ids:
                raise ProjectValidationError(
                    f"AV track group {group.id} references missing audio track {group.audio_track_id}"
                )
            group_ids.add(group.id)
        self.created_at = str(self.created_at or _utc_now())
        self.updated_at = str(self.updated_at or self.created_at)
        self.report_path = str(self.report_path or "")
        self.glossary_ids = _string_list(self.glossary_ids)
        self.effects = _mapping(self.effects)
        self.style_recipes = _mapping(self.style_recipes)
        self.generation_metadata = _mapping(self.generation_metadata)
        self.asr_evidence = _mapping(self.asr_evidence)
        self.render_settings = _mapping(self.render_settings)
        self.original_outputs = {
            str(key): str(value)
            for key, value in _mapping(self.original_outputs).items()
            if str(key).strip() and str(value).strip()
        }
        self.studio_state = _mapping(self.studio_state)
        # Validation normalizes the persisted schema but is not an external
        # replacement of canonical runtime state.
        object.__setattr__(self, "edit_sequence", _mapping(self.edit_sequence))
        self.edit_history = [
            _mapping(item) for item in self.edit_history if isinstance(item, Mapping)
        ]

        seen_cues: set[str] = set()
        for cue in self.cues:
            cue.validate()
            if cue.id in seen_cues:
                raise ProjectValidationError(f"duplicate cue id {cue.id}")
            seen_cues.add(cue.id)

        seen_speakers: set[str] = set()
        for speaker in self.speakers:
            speaker.validate()
            if speaker.id in seen_speakers:
                raise ProjectValidationError(f"duplicate speaker id {speaker.id}")
            seen_speakers.add(speaker.id)

        from .speaker_names import ensure_speaker_names
        ensure_speaker_names(self)

        seen_styles: set[str] = set()
        for style in self.styles:
            style.validate()
            if style.id in seen_styles:
                raise ProjectValidationError(f"duplicate style id {style.id}")
            seen_styles.add(style.id)
        if "default" not in seen_styles:
            self.styles.insert(0, default_style())

        # Recipes remain a renderer-neutral, JSON-only boundary. Validate on
        # every load/save so generated code can never enter the project core.
        if self.style_recipes:
            from .style_recipe import StyleRecipe, StyleRecipeValidationError

            normalized_recipes: dict[str, Any] = {}
            for recipe_id, payload in self.style_recipes.items():
                clean_id = _clean_id(recipe_id, "style_recipe.id")
                try:
                    normalized_recipes[clean_id] = StyleRecipe.from_dict(payload).to_dict()
                except StyleRecipeValidationError as exc:
                    raise ProjectValidationError(f"invalid style recipe {clean_id}: {exc}") from exc
            self.style_recipes = normalized_recipes

    def hidden_speaker_ids(self) -> frozenset[str]:
        """被使用者隐藏的说话人（成片/导出/高保真预览排除；编辑器保留）。"""
        return frozenset(
            speaker.id for speaker in self.speakers if speaker.hidden
        )

    def visible_cues(self) -> list["StudioCue"]:
        hidden = self.hidden_speaker_ids()
        if not hidden:
            return list(self.cues)
        return [cue for cue in self.cues if cue.speaker_id not in hidden]

    def to_dict(self) -> dict[str, Any]:
        from .studio_edit_sequence import persist_sequence

        # ``to_dict`` is an explicit persistence/snapshot boundary.  Getters
        # never perform this runtime -> schema synchronization.
        persist_sequence(self)
        self.validate()
        payload = asdict(self)
        # QC metrics are deterministic and can be rebuilt. P22 projects may
        # still contain this transient cache; do not keep growing project files.
        state = payload.get("studio_state", {})
        if isinstance(state, dict):
            state.pop("review_risks", None)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SubtitleProject":
        if not isinstance(payload, Mapping):
            raise ProjectValidationError("project root must be a JSON object")
        schema_version = int(payload.get("schema_version", 0) or 0)
        if schema_version != PROJECT_SCHEMA_VERSION:
            raise ProjectValidationError(
                f"unsupported project schema_version {schema_version}"
            )
        media_payload = payload.get("media")
        if not isinstance(media_payload, Mapping):
            raise ProjectValidationError("project media must be a JSON object")
        project = cls(
            media=StudioMedia(**dict(media_payload)),
            media_pool=[
                MediaAsset(**dict(item))
                for item in payload.get("media_pool", [])
                if isinstance(item, Mapping)
            ],
            video_tracks=[
                VideoTrack(
                    **{
                        **dict(item),
                        "clips": [
                            VideoClip(
                                **{
                                    **dict(clip),
                                    "transform": VideoTransform(
                                        **dict(clip.get("transform", {}))
                                    ),
                                }
                            )
                            for clip in item.get("clips", [])
                            if isinstance(clip, Mapping)
                        ],
                    }
                )
                for item in payload.get("video_tracks", [])
                if isinstance(item, Mapping)
            ],
            audio_tracks=[
                AudioTrack(
                    **{
                        **dict(item),
                        "clips": [
                            AudioClip(**dict(clip))
                            for clip in item.get("clips", [])
                            if isinstance(clip, Mapping)
                        ],
                    }
                )
                for item in payload.get("audio_tracks", [])
                if isinstance(item, Mapping)
            ],
            av_track_groups=[
                AVTrackGroup(**dict(item))
                for item in payload.get("av_track_groups", [])
                if isinstance(item, Mapping)
            ],
            cues=[StudioCue(**dict(item)) for item in payload.get("cues", [])],
            speakers=[StudioSpeaker(**dict(item)) for item in payload.get("speakers", [])],
            styles=[SubtitleStyle(**dict(item)) for item in payload.get("styles", [])],
            effects=_mapping(payload.get("effects")),
            style_recipes=_mapping(payload.get("style_recipes")),
            generation_metadata=_mapping(payload.get("generation_metadata")),
            asr_evidence=_mapping(payload.get("asr_evidence")),
            glossary_ids=_string_list(payload.get("glossary_ids")),
            edit_history=list(payload.get("edit_history", [])),
            render_settings=_mapping(payload.get("render_settings")),
            report_path=str(payload.get("report_path") or ""),
            original_outputs=_mapping(payload.get("original_outputs")),
            studio_state=_mapping(payload.get("studio_state")),
            edit_sequence=_mapping(payload.get("edit_sequence")),
            project_id=str(payload.get("project_id") or ""),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            schema_version=schema_version,
        )
        project.validate()
        from .studio_edit_sequence import ensure_edit_sequence

        ensure_edit_sequence(project)
        return project


def studio_data_root(base: str | os.PathLike[str] | None = None) -> Path:
    if base is not None:
        root = Path(base)
    else:
        from .runtime_paths import user_data_root
        return user_data_root() / STUDIO_DATA_DIRNAME
    return root / "2ByteASR" / STUDIO_DATA_DIRNAME


def studio_settings_path(base: str | os.PathLike[str] | None = None) -> Path:
    return studio_data_root(base) / "settings.json"


LIBRARY_INDEX_VERSION = 2
_LIBRARY_INDEX_SUMMARY_KEYS = (
    "project_id", "name", "name_origin", "name_custom", "cue_count", "duration_ms", "source_media",
    "created_at", "updated_at", "width", "height", "cover_path",
)


def library_index_path(base: str | os.PathLike[str] | None = None) -> Path:
    """Persistent Library summary index; keyed by resolved project path.

    Sits next to the Studio settings file so tests/settings redirection
    (studio_settings_path monkeypatching) isolates the index with them.
    """
    if base is not None:
        return Path(base) / "library-index.json"
    return studio_settings_path().parent / "library-index.json"


def load_library_index(base: str | os.PathLike[str] | None = None, *, diagnostics: list[str] | None = None) -> dict[str, dict[str, object]]:
    path = library_index_path(base)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError) as exc:
        if diagnostics is not None:
            diagnostics.append(f"工程索引读取失败：{path}（{exc}）；保留原索引，只读扫描工程。")
        return {}
    if not isinstance(payload, dict) or payload.get("version") != LIBRARY_INDEX_VERSION:
        if diagnostics is not None:
            diagnostics.append(f'工程索引版本或格式无效：{path}；保留原索引，只读扫描工程。')
        return {}
    entries = payload.get("projects")
    if not isinstance(entries, dict):
        if diagnostics is not None:
            diagnostics.append(f'工程索引条目格式无效：{path}；保留原索引，只读扫描工程。')
        return {}
    return {str(key): dict(value) for key, value in entries.items() if isinstance(value, dict)}


def save_library_index(
    index: Mapping[str, dict[str, object]],
    base: str | os.PathLike[str] | None = None,
) -> None:
    """Atomically persist the Library index; corruption-safe on failure."""
    payload = {
        "version": LIBRARY_INDEX_VERSION,
        "projects": dict(index),
    }
    try:
        _atomic_json_write(library_index_path(base), payload)
    except OSError:
        pass


def library_index_entry_stale(entry: Mapping[str, object] | None, stat: os.stat_result | None) -> bool:
    """True when the cached summary cannot represent the on-disk project."""
    if not isinstance(entry, dict) or stat is None:
        return True
    return (
        int(entry.get("mtime_ns", -1)) != int(stat.st_mtime_ns)
        or int(entry.get("size", -1)) != int(stat.st_size)
    )


def project_library_root(base: str | os.PathLike[str] | None = None) -> Path:
    """Writable app-owned project library; never defaults to the Desktop."""
    if base is not None:
        return Path(base) / PROJECT_LIBRARY_DIRNAME
    # Explicit preferences and the default share the same user-data boundary.
    try:
        configured = studio_settings_path()
        if configured.is_file():
            payload = json.loads(configured.read_text(encoding="utf-8"))
            custom_root = str(payload.get("project_root") or "").strip() if isinstance(payload, dict) else ""
            if custom_root:
                return Path(custom_root).expanduser()
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError) as exc:
        raise OSError(f"工程库设置读取失败：{configured}（{exc}）；未切换到空目录。") from exc
    from .runtime_paths import user_data_root
    return user_data_root() / PROJECT_LIBRARY_DIRNAME


def canonical_project_path(media_path: str | os.PathLike[str]) -> Path:
    """Return the single project-library path for a source media file."""
    media = Path(media_path)
    safe_name = "".join("_" if char in '<>:"/\\|?*' else char for char in media.stem).strip(" .") or "Subtitle Project"
    return project_library_root() / safe_name / f"{safe_name}{PROJECT_SUFFIX}"


def register_recent_project(
    path: str | os.PathLike[str],
    *,
    source_media: str = "",
    cue_count: int = 0,
) -> None:
    """Register a canonical project without moving or rewriting old projects."""
    target = Path(path).resolve()
    settings = studio_settings_path()
    try:
        payload = json.loads(settings.read_text(encoding="utf-8")) if settings.is_file() else {}
    except (OSError, ValueError, TypeError):
        payload = {}
    records = payload.get("recent_projects", []) if isinstance(payload, dict) else []
    records = [item for item in records if isinstance(item, dict) and str(item.get("path", "")) != str(target)]
    records.insert(0, {
        "path": str(target),
        "name": target.stem,
        "cue_count": int(cue_count),
        "source_media": str(source_media or ""),
    })
    payload["recent_projects"] = records[:18]
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def legacy_project_library_root() -> Path:
    return Path.home() / "Desktop" / PROJECT_ARCHIVE_DIRNAME


def project_archive_path(
    output_path: str | os.PathLike[str],
    media_path: str | os.PathLike[str] = "",
) -> Path:
    """Return the user-visible archive path for a recognition project."""
    output = Path(output_path)
    raw_name = Path(media_path).stem if media_path else output.stem
    safe_name = "".join("_" if char in '<>:"/\\|?*' else char for char in raw_name).strip(" .")
    safe_name = safe_name or "Subtitle Project"
    # Preserve explicit non-Desktop output paths for backwards compatibility;
    # Desktop-created projects move into the app-owned library instead.
    if output.parent.name.casefold() == "desktop":
        project_dir = project_library_root() / safe_name
    else:
        project_dir = output.parent / PROJECT_ARCHIVE_DIRNAME / safe_name
    for child in ("subtitles", "reports", "source", "autosave", "cache", "preview", "backup", "renders", "exports"):
        (project_dir / child).mkdir(parents=True, exist_ok=True)
    return project_dir / f"{safe_name}{PROJECT_SUFFIX}"


def waveform_cache_root(base: str | os.PathLike[str] | None = None) -> Path:
    return studio_data_root(base) / "waveform-cache"


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _atomic_json_blob_write(path: Path, content: str) -> dict[str, float]:
    """Atomically persist pre-serialized JSON and expose the durability phases."""

    import time

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    write_started = time.perf_counter()
    fsync_ms = 0.0
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            fsync_started = time.perf_counter()
            os.fsync(stream.fileno())
            fsync_ms = (time.perf_counter() - fsync_started) * 1000.0
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return {
        "persist_ms": (time.perf_counter() - write_started) * 1000.0,
        "fsync_ms": fsync_ms,
    }


def project_backup_path(path: str | os.PathLike[str]) -> Path:
    project_path = Path(path)
    archive_backup = project_path.parent / "backup"
    if archive_backup.is_dir():
        return archive_backup / f"{project_path.stem}.previous{project_path.suffix}"
    return project_path.with_suffix(project_path.suffix + ".bak")


def save_project(project: SubtitleProject, path: str | os.PathLike[str]) -> Path:
    runtime = getattr(project, "_studio_state_runtime", None)
    if runtime is not None and runtime._active is not None:
        raise RuntimeError("不能在媒体编辑事务提交前保存工程")
    target = Path(path)
    if target.suffix.lower() != PROJECT_SUFFIX:
        target = target.with_suffix(PROJECT_SUFFIX)
    project.updated_at = _utc_now()
    payload = project.to_dict()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        backup = project_backup_path(target)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{backup.name}.", suffix=".tmp", dir=str(target.parent)
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            shutil.copy2(target, temporary)
            os.replace(temporary, backup)
        finally:
            try:
                temporary.unlink()
            except OSError:
                pass
    _atomic_json_write(target, payload)
    return target


def load_project(path: str | os.PathLike[str]) -> SubtitleProject:
    project_path = Path(path)
    try:
        payload = json.loads(project_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ProjectValidationError(f"could not read project {project_path}: {exc}") from exc
    from .media_graph_integrity import validate_autosave_integrity, graph_counts
    try:
        expected = validate_autosave_integrity(payload)
        project = SubtitleProject.from_dict(payload)
        if expected is not None:
            actual = graph_counts({key: [asdict(x) for x in getattr(project, key)]
                                   for key in ("media_pool", "video_tracks", "audio_tracks", "av_track_groups")})
            if actual != expected["counts"]:
                raise ValueError("恢复时媒体轨道或片段数量发生变化，拒绝不完整恢复。")
        return project
    except (ValueError, KeyError, TypeError) as exc:
        raise ProjectValidationError(str(exc)) from exc


def _project_media_candidates(project: SubtitleProject) -> list[str]:
    candidates = [str(project.media.path or "")]
    sequence = project.edit_sequence if isinstance(project.edit_sequence, Mapping) else {}
    candidates.append(str(sequence.get("source_path") or ""))
    for segment in sequence.get("segments", ()) if isinstance(sequence, Mapping) else ():
        if isinstance(segment, Mapping):
            candidates.append(str(segment.get("source_path") or ""))
    state = project.studio_state if isinstance(project.studio_state, Mapping) else {}
    for key in ("media_path", "source_media", "timeline_source"):
        candidates.append(str(state.get(key) or ""))
    return list(dict.fromkeys(item.strip() for item in candidates if item.strip()))


def _project_autosave_snapshots(
    project_path: Path,
    *,
    newer_than_ns: int | None = None,
) -> list[tuple[Path, SubtitleProject]]:
    autosave_dir = project_path.resolve().parent / "autosave"
    try:
        paths = sorted(
            autosave_dir.glob(f"*{PROJECT_SUFFIX}"),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        )
    except OSError:
        return []
    snapshots: list[tuple[Path, SubtitleProject]] = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        # 2026-09-19：官方保存成功后其内容总是 autosave 的超集；恢复链
        # (recoverable_autosave) 也只考虑 mtime 更新的候选。旧于官方的
        # autosave 在 Library 富化里永远不提供增量，跳过免掉重复全量解析。
        if newer_than_ns is not None and stat.st_mtime_ns <= newer_than_ns:
            continue
        try:
            snapshots.append((path, load_project(path)))
        except (OSError, ValueError, TypeError):
            continue
    return snapshots


def _recover_preview_cues(
    project_path: Path,
    *,
    expected_count: int = 0,
    valid_style_ids: set[str] | None = None,
) -> tuple[list[StudioCue], str]:
    """Recover last-known visible cues from Studio-owned ASS artifacts.

    This is deliberately a last-resort migration path for early blank-project
    builds that rendered manual/imported cues but failed to persist them.  It
    never reads arbitrary sidecar subtitles and prefers the newest preview
    whose event count matches the last recorded Library count.
    """
    preview_dir = project_path.resolve().parent / "preview"
    try:
        paths = sorted(
            preview_dir.glob("*.ass"),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        )
    except OSError:
        return [], ""
    parsed: list[tuple[Path, list[StudioCue]]] = []
    known_styles = valid_style_ids or {"default"}
    for path in paths:
        cues: list[StudioCue] = []
        try:
            lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        except OSError:
            continue
        for index, line in enumerate(lines, 1):
            if not line.startswith("Dialogue:"):
                continue
            parsed_line = parse_ass_dialogue_line(line)
            if parsed_line is None:
                continue
            start_ms, end_ms, style_id, actor, text = parsed_line
            if end_ms <= start_ms:
                continue
            cues.append(StudioCue(
                id=f"recovered-{path.stem[-12:]}-{index}",
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
                speaker_id=actor or "S00",
                style_id=style_id if style_id in known_styles else "default",
                original_text=text,
            ))
        if cues:
            if expected_count > 0 and len(cues) == expected_count:
                return cues, str(path)
            parsed.append((path, cues))
    if not parsed:
        return [], ""
    # Without a matching recorded count, prefer the richest recent artifact;
    # generated empty/stale preview files cannot erase real manual cues.
    path, cues = max(parsed, key=lambda item: (len(item[1]), item[0].stat().st_mtime_ns))
    return cues, str(path)


def library_project_snapshot(
    path: str | os.PathLike[str],
    recent: Mapping[str, Any] | None = None,
) -> tuple[SubtitleProject, dict[str, object], bool]:
    """Build the canonical Library view from project, sequence and recovery data."""
    project_path = Path(path).expanduser().resolve()
    official = load_project(project_path)
    effective = copy.deepcopy(official)
    recent_data = dict(recent or {})
    try:
        official_mtime_ns = project_path.stat().st_mtime_ns
    except OSError:
        official_mtime_ns = None
    autosaves = _project_autosave_snapshots(project_path, newer_than_ns=official_mtime_ns)
    sources = [official, *(snapshot for _path, snapshot in autosaves)]

    media_candidates: list[str] = []
    for candidate_project in sources:
        media_candidates.extend(_project_media_candidates(candidate_project))
    media_candidates.append(str(recent_data.get("source_media") or ""))
    media_candidates = list(dict.fromkeys(item for item in media_candidates if item))
    existing_media = next((item for item in media_candidates if Path(item).expanduser().is_file()), "")
    chosen_media = existing_media or next(iter(media_candidates), "")
    if chosen_media:
        effective.media.path = str(Path(chosen_media).expanduser())
        effective.media.display_name = Path(chosen_media).name

    richest = max(
        sources,
        key=lambda item: (
            len(item.cues),
            int(item.media.duration_ms or 0),
            int(item.media.width or 0) * int(item.media.height or 0),
            len(_project_media_candidates(item)),
        ),
    )
    if not effective.cues and richest.cues:
        effective.cues = copy.deepcopy(richest.cues)
    if len(effective.styles) <= 1 and len(richest.styles) > 1:
        effective.styles = copy.deepcopy(richest.styles)
        effective.effects = copy.deepcopy(richest.effects)
        effective.style_recipes = copy.deepcopy(richest.style_recipes)
    if not effective.speakers and richest.speakers:
        effective.speakers = copy.deepcopy(richest.speakers)
    for field_name in ("generation_metadata", "asr_evidence", "render_settings", "studio_state"):
        current = getattr(effective, field_name)
        candidate = getattr(richest, field_name)
        if not current and candidate:
            setattr(effective, field_name, copy.deepcopy(candidate))

    durations = [
        int(item.media.duration_ms or 0)
        for item in sources
    ] + [
        int((item.edit_sequence or {}).get("source_duration_ms", 0) or 0)
        for item in sources
    ] + [int(recent_data.get("duration_ms", 0) or 0)]
    effective.media.duration_ms = max(durations, default=0)
    for dimension in ("width", "height"):
        setattr(
            effective.media,
            dimension,
            max((int(getattr(item.media, dimension, 0) or 0) for item in sources), default=0),
        )
    if not str((effective.edit_sequence or {}).get("source_path") or ""):
        best_sequence = max(
            (copy.deepcopy(item.edit_sequence) for item in sources),
            key=lambda value: (
                bool(str(value.get("source_path") or "")),
                len(value.get("segments", ())),
                int(value.get("source_duration_ms", 0) or 0),
            ),
        )
        effective.edit_sequence = best_sequence
    sequence = effective.edit_sequence if isinstance(effective.edit_sequence, dict) else {}
    if chosen_media:
        sequence["source_path"] = str(sequence.get("source_path") or chosen_media)
        sequence["source_duration_ms"] = int(sequence.get("source_duration_ms") or effective.media.duration_ms)
        segments = sequence.get("segments") if isinstance(sequence.get("segments"), list) else []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            segment["source_path"] = str(segment.get("source_path") or chosen_media)
            if int(segment.get("source_out_ms", 0) or 0) <= int(segment.get("source_in_ms", 0) or 0):
                segment["source_in_ms"] = 0
                segment["source_out_ms"] = effective.media.duration_ms
                segment["timeline_in_ms"] = 0
                segment["timeline_out_ms"] = effective.media.duration_ms
        effective.edit_sequence = sequence

    expected_count = int(recent_data.get("cue_count", 0) or 0)
    recovered_from = ""
    if not effective.cues and expected_count > 0:
        effective.cues, recovered_from = _recover_preview_cues(
            project_path,
            expected_count=expected_count,
            valid_style_ids={style.id for style in effective.styles},
        )
    effective.studio_state = dict(effective.studio_state or {})
    if recovered_from:
        effective.studio_state["library_recovered_cues_from"] = recovered_from
    from .studio_edit_sequence import ensure_edit_sequence

    ensure_edit_sequence(effective)
    effective.validate()
    cover = project_path.parent / "preview" / "project-cover.jpg"
    summary = {
        "project_id": effective.project_id,
        "name": str(effective.studio_state.get("project_name") or recent_data.get("name") or project_path.stem),
        "name_origin": dict(effective.studio_state.get("project_name_origin") or {}),
        "name_custom": bool(effective.studio_state.get("project_name") and not effective.studio_state.get("project_name_automatic")),
        "cue_count": max(len(effective.cues), expected_count if not effective.cues else 0),
        "duration_ms": int(effective.media.duration_ms or 0),
        "source_media": str(effective.media.path or ""),
        "created_at": effective.created_at,
        "updated_at": effective.updated_at,
        "width": int(effective.media.width or 0),
        "height": int(effective.media.height or 0),
        "cover_path": str(cover) if cover.is_file() else str(recent_data.get("cover_path") or ""),
    }
    changed = any((
        official.media.path != effective.media.path,
        int(official.media.duration_ms or 0) != int(effective.media.duration_ms or 0),
        int(official.media.width or 0) != int(effective.media.width or 0),
        int(official.media.height or 0) != int(effective.media.height or 0),
        len(official.cues) != len(effective.cues),
        official.edit_sequence != effective.edit_sequence,
    ))
    return effective, summary, changed


def repair_project_library_metadata(
    path: str | os.PathLike[str],
    recent: Mapping[str, Any] | None = None,
    *,
    media_metadata: Mapping[str, Any] | None = None,
) -> tuple[SubtitleProject, dict[str, object], bool]:
    """Persist one recovered Library project through the normal backup path."""
    project_path = Path(path).expanduser().resolve()
    project, summary, changed = library_project_snapshot(project_path, recent)
    metadata = dict(media_metadata or {})
    if metadata:
        for field_name in ("duration_ms", "width", "height", "fingerprint"):
            value = metadata.get(field_name)
            if value not in (None, "", 0):
                setattr(project.media, field_name, value)
        from .studio_edit_sequence import ensure_edit_sequence

        ensure_edit_sequence(project)
        summary.update({
            "duration_ms": int(project.media.duration_ms or 0),
            "width": int(project.media.width or 0),
            "height": int(project.media.height or 0),
        })
        changed = True
    if changed:
        project.studio_state = dict(project.studio_state or {})
        project.studio_state["library_metadata_repaired_at"] = _utc_now()
        save_project(project, project_path)
    return project, summary, changed


def _autosave_key(project: SubtitleProject, project_path: str | os.PathLike[str] | None) -> str:
    identity = str(Path(project_path).resolve()) if project_path else project.project_id
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def autosave_path(
    project: SubtitleProject,
    project_path: str | os.PathLike[str] | None = None,
    base: str | os.PathLike[str] | None = None,
) -> Path:
    if project_path:
        project_dir = Path(project_path).resolve().parent
        archive_autosave = project_dir / "autosave"
        if archive_autosave.is_dir():
            return archive_autosave / f"{_autosave_key(project, project_path)}{PROJECT_SUFFIX}"
    return studio_data_root(base) / "autosaves" / f"{_autosave_key(project, project_path)}{PROJECT_SUFFIX}"


def _autosave_path_for_identity(
    project_id: str,
    project_path: str | os.PathLike[str] | None = None,
    base: str | os.PathLike[str] | None = None,
) -> Path:
    identity = str(Path(project_path).resolve()) if project_path else str(project_id)
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    if project_path:
        project_dir = Path(project_path).resolve().parent
        archive_autosave = project_dir / "autosave"
        if archive_autosave.is_dir():
            return archive_autosave / f"{key}{PROJECT_SUFFIX}"
    return studio_data_root(base) / "autosaves" / f"{key}{PROJECT_SUFFIX}"


def save_autosave(
    project: SubtitleProject | object,
    project_path: str | os.PathLike[str] | None = None,
    base: str | os.PathLike[str] | None = None,
) -> Path:
    to_payload = getattr(project, "to_payload", None)
    if callable(to_payload):
        payload = to_payload()
        project_id = str(payload.get("project_id") or "")
        target = _autosave_path_for_identity(project_id, project_path, base)
    else:
        if not isinstance(project, SubtitleProject):
            raise TypeError("autosave source must be SubtitleProject or persistence revision")
        target = autosave_path(project, project_path, base)
        payload = project.to_dict()
    payload["autosave"] = {
        "saved_at": _utc_now(),
        "project_path": str(Path(project_path).resolve()) if project_path else "",
    }
    from .media_graph_integrity import graph_integrity
    payload["autosave"]["media_graph_integrity"] = graph_integrity(payload)
    _atomic_json_write(target, payload)
    _write_autosave_fingerprint_sidecar(target, payload)
    return target


def save_autosave_revision(
    revision: object,
    project_path: str | os.PathLike[str] | None = None,
    base: str | os.PathLike[str] | None = None,
    *, session_id: str = "",
) -> tuple[Path, dict[str, float]]:
    """Persist an immutable DTO without reconstructing a mutable project."""

    import time

    to_payload = getattr(revision, "to_payload", None)
    if not callable(to_payload):
        raise TypeError("revision must provide to_payload()")
    materialize_started = time.perf_counter()
    payload = to_payload()
    materialize_ms = (time.perf_counter() - materialize_started) * 1000.0
    payload["autosave"] = {
        "saved_at": _utc_now(),
        "project_path": str(Path(project_path).resolve()) if project_path else "",
        "session_id": session_id,
        "generation": int(getattr(revision, "generation", 0)),
    }
    from .media_graph_integrity import graph_integrity
    payload["autosave"]["media_graph_integrity"] = graph_integrity(payload)
    serialize_started = time.perf_counter()
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    serialize_ms = (time.perf_counter() - serialize_started) * 1000.0
    target = _autosave_path_for_identity(str(payload.get("project_id") or ""), project_path, base)
    if session_id:
        if not session_id.isalnum():
            raise ValueError("invalid autosave session id")
        target = target.with_name(f"{target.stem}.{session_id}{target.suffix}")
        # Writers from one page are serialized by its write lock. A shutdown
        # flush may win that lock before an already captured background write.
        if target.is_file():
            try:
                previous = json.loads(target.read_text(encoding="utf-8"))
                previous_meta = previous.get("autosave") or {}
                if int(previous_meta.get("generation", -1)) > int(getattr(revision, "generation", 0)):
                    return target, dict(materialize_ms=materialize_ms, serialize_ms=serialize_ms,
                                        persist_ms=0., fsync_ms=0.)
            except (OSError, ValueError, TypeError):
                pass
    phases = _atomic_json_blob_write(target, content)
    _write_autosave_fingerprint_sidecar(target, payload)
    phases.update({
        "materialize_ms": materialize_ms,
        "serialize_ms": serialize_ms,
    })
    return target, phases


def _content_fingerprint_payload(payload: dict) -> str:
    """Canonical content hash shared by loaded projects and autosave payloads."""
    payload = dict(payload)
    payload.pop("autosave", None)
    payload.pop("updated_at", None)
    payload.pop("created_at", None)
    state = payload.get("studio_state")
    if isinstance(state, dict):
        payload["studio_state"] = {
            key: value for key, value in state.items()
            if key not in {"last_opened", "review_risks", "review_confirmations", "cue_statuses"}
        }
    payload.pop("project_id", None)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def project_content_fingerprint(project: SubtitleProject) -> str:
    """Hash meaningful project content while ignoring runtime/recovery noise."""
    return _content_fingerprint_payload(project.to_dict())


def _write_autosave_fingerprint_sidecar(target: Path, payload: dict) -> None:
    """Tiny sidecar so recovery can compare content without parsing 9MB JSON.

    2026-09-18：重复进入实测每次打开都为"官方 vs autosave 指纹比对"完整
    解析一次候选（438-710ms）。边车持有 project_id + content_fingerprint；
    读取方必须校验 sidecar mtime ≥ 候选 mtime，陈旧即回退全量解析。
    """
    try:
        sidecar = {
            "project_id": str(payload.get("project_id") or ""),
            "content_fingerprint": _content_fingerprint_payload(payload),
        }
        _atomic_json_write(
            target.with_name(f"{target.stem}.fingerprint.json"),
            sidecar,
        )
    except OSError:
        pass


def autosave_fingerprint_sidecar(candidate: Path) -> dict:
    """Fresh fingerprint sidecar for an autosave candidate, or {}."""
    sidecar = candidate.with_name(f"{candidate.stem}.fingerprint.json")
    try:
        if not sidecar.is_file() or sidecar.stat().st_mtime_ns < candidate.stat().st_mtime_ns:
            return {}
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if isinstance(payload, dict) and str(payload.get("content_fingerprint") or ""):
        return payload
    return {}


def recoverable_autosave(
    project_path: str | os.PathLike[str],
    base: str | os.PathLike[str] | None = None,
    *,
    official: SubtitleProject | None = None,
) -> Path | None:
    target = Path(project_path)
    project = official if official is not None else load_project(target)
    canonical = autosave_path(project, target, base)
    candidates = [canonical, *canonical.parent.glob(f"{canonical.stem}.*{PROJECT_SUFFIX}")]
    candidates = sorted((x for x in candidates if x.is_file()), key=lambda x: x.stat().st_mtime_ns, reverse=True)
    for candidate in candidates:
        if candidate.stat().st_mtime_ns <= target.stat().st_mtime_ns:
            continue
        # 新鲜边车可直接校验身份，免去候选全量解析。
        sidecar = autosave_fingerprint_sidecar(candidate)
        if sidecar and str(sidecar.get("project_id") or "") == project.project_id:
            return candidate
        try:
            recovered = load_project(candidate)
            if recovered.project_id == project.project_id:
                return candidate
        except (OSError, ValueError, TypeError):
            continue
    return None


def project_from_runtime_cues(
    media_path: str | os.PathLike[str],
    cues: Iterable[Any],
    *,
    report_path: str = "",
    original_outputs: Mapping[str, str] | None = None,
    generation_metadata: Mapping[str, Any] | None = None,
    asr_evidence: Mapping[str, Any] | None = None,
    glossary_ids: Iterable[str] = (),
    media_identity: Mapping[str, Any] | None = None,
) -> SubtitleProject:
    studio_cues: list[StudioCue] = []
    speaker_ids: list[str] = []
    used_cue_ids: set[str] = set()
    for index, cue in enumerate(cues, 1):
        speaker_id = str(getattr(cue, "speaker", "S00") or "S00")
        if speaker_id not in speaker_ids:
            speaker_ids.append(speaker_id)
        cue_id = str(getattr(cue, "cue_id", index) or index)
        if cue_id in used_cue_ids:
            cue_id = f"{cue_id}-{index}"
        used_cue_ids.add(cue_id)
        text = str(getattr(cue, "text", "") or "")
        studio_cues.append(
            StudioCue(
                id=cue_id,
                start_ms=round(float(getattr(cue, "start", 0.0)) * 1000),
                end_ms=round(float(getattr(cue, "end", 0.0)) * 1000),
                text=text,
                speaker_id=speaker_id,
                original_text=text,
                evidence_refs=[],
            )
        )
    project = SubtitleProject(
        media=StudioMedia(path=str(Path(media_path).resolve())),
        cues=studio_cues,
        speakers=[StudioSpeaker(id=item) for item in speaker_ids],
        generation_metadata=_mapping(generation_metadata),
        asr_evidence=_mapping(asr_evidence),
        glossary_ids=_string_list(list(glossary_ids)),
        report_path=str(report_path or ""),
        original_outputs=_mapping(original_outputs),
    )
    from .speaker_names import initialize_speaker_names
    initialize_speaker_names(project)
    from .speaker_organization import apply_new_project_policy
    apply_new_project_policy(project)
    identity = dict(media_identity or {})
    if not identity and Path(media_path).is_file():
        from .studio_helpers import probe_media_identity

        try:
            identity = dict(probe_media_identity(media_path))
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            project.generation_metadata["media_contract_probe_error"] = str(exc)
    if identity:
        hydrate_media_contract(project, identity, source_path=media_path)
    project.validate()
    return project


def create_studio_outputs(
    media_path: str | os.PathLike[str],
    cues: Iterable[Any],
    *,
    txt_path: str,
    srt_path: str = "",
    report_path: str = "",
    segments: Iterable[Any] = (),
    generation_metadata: Mapping[str, Any] | None = None,
    glossary_ids: Iterable[str] = (),
    target_project_path: str | os.PathLike[str] = "",
    recognition_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Create an archived Studio project without mutating ASR outputs."""

    metadata = _mapping(generation_metadata)
    analysis_transcript = bool(metadata.get("analysis_transcript"))

    project_path = (
        Path(target_project_path).expanduser().resolve()
        if str(target_project_path or "").strip()
        else canonical_project_path(media_path)
    )
    project_path.parent.mkdir(parents=True, exist_ok=True)
    for child in ("subtitles", "reports", "source", "autosave", "cache", "preview", "backup", "renders", "exports"):
        (project_path.parent / child).mkdir(parents=True, exist_ok=True)
    evidence: dict[str, Any] = {}
    segment_rows = []
    for index, segment in enumerate(segments, 1):
        segment_id = str(getattr(segment, "segment_id", index) or index)
        reference = f"segment:{segment_id}"
        row = {
            "start_ms": round(float(getattr(segment, "start", 0.0)) * 1000),
            "end_ms": round(float(getattr(segment, "end", 0.0)) * 1000),
            "text": str(getattr(segment, "text", "") or ""),
            "speaker_id": str(getattr(segment, "speaker", "S00") or "S00"),
            "primary_source": str(getattr(segment, "primary_source", "") or ""),
            "caption_arbitration": copy.deepcopy(getattr(segment, "caption_arbitration", {}) or {}),
            "moss_text": str(getattr(segment, "moss_text", "") or ""),
            "moss_start": float(getattr(segment, "moss_start", getattr(segment, "start", 0.0)) or 0.0),
            "moss_end": float(getattr(segment, "moss_end", getattr(segment, "end", 0.0)) or 0.0),
            "firered_text": str(getattr(segment, "firered_text", "") or ""),
            "firered_start": float(getattr(segment, "firered_start", 0.0) or 0.0),
            "firered_end": float(getattr(segment, "firered_end", 0.0) or 0.0),
            "firered_alignment_confidence": float(getattr(segment, "firered_alignment_confidence", 0.0) or 0.0),
            "firered_llm_text": str(getattr(segment, "firered_llm_text", "") or ""),
            "qwen_asr_text": str(getattr(segment, "qwen_asr_text", "") or ""),
            "qwen_text": str(getattr(segment, "qwen_text", getattr(segment, "qwen_asr_text", "")) or ""),
            "qwen_confidence": float(getattr(segment, "qwen_confidence", 0.0) or 0.0),
            "final_text": str(getattr(segment, "final_text", getattr(segment, "text", "")) or ""),
            "final_start": float(getattr(segment, "final_start", getattr(segment, "start", 0.0)) or 0.0),
            "final_end": float(getattr(segment, "final_end", getattr(segment, "end", 0.0)) or 0.0),
            "final_text_owner": str(getattr(segment, "final_text_owner", "MOSS") or "MOSS"),
            "final_timing_owner": str(getattr(segment, "final_timing_owner", "MOSS") or "MOSS"),
            "alternate_text": str(getattr(segment, "alternate_text", "") or ""),
            "confidence": float(getattr(segment, "confidence", 0.0) or 0.0),
        }
        # 2026-09-18 VIII：持久化词级时间戳（AI 断句的停顿证据/词级拆分
        # 时间分配依赖它；此前只有读取端、没有写入端，拆分恒走占比估算）。
        # 单位约定：显式 start_ms/end_ms 键=毫秒；start/end=秒（WordUnit
        # 与 API 词级字段的既有约定）。additive 键，旧工程无该键自动回落。
        words_payload = []
        for word in getattr(segment, "words", None) or ():
            if isinstance(word, Mapping):
                word_text = str(word.get("text") or word.get("word") or "")
                if "start_ms" in word or "end_ms" in word:
                    word_start_ms = float(word.get("start_ms", 0) or 0)
                    word_end_ms = float(word.get("end_ms", word_start_ms) or word_start_ms)
                else:
                    word_start_ms = float(word.get("start", 0) or 0) * 1000.0
                    word_end_ms = float(word.get("end", word_start_ms / 1000.0) or 0) * 1000.0
            else:
                word_text = str(getattr(word, "text", "") or getattr(word, "word", "") or "")
                start_attr = getattr(word, "start_ms", None)
                if start_attr is None:
                    word_start_ms = float(getattr(word, "start", 0.0) or 0.0) * 1000.0
                    word_end_ms = float(getattr(word, "end", getattr(word, "start", 0.0) or 0.0) or 0.0) * 1000.0
                else:
                    word_start_ms = float(start_attr or 0)
                    word_end_ms = float(getattr(word, "end_ms", word_start_ms) or word_start_ms)
            if word_text.strip() and word_end_ms > word_start_ms:
                words_payload.append({
                    "text": word_text,
                    "start_ms": int(round(word_start_ms)),
                    "end_ms": int(round(word_end_ms)),
                })
        if words_payload:
            row["words"] = words_payload
        evidence[reference] = row
        segment_rows.append((reference, row))
    # Keep the original ASR files untouched for backwards compatibility, but
    # place canonical internal artifacts beside the project from this point on.
    subtitles_dir = project_path.parent / "subtitles"
    reports_dir = project_path.parent / "reports"
    if txt_path and Path(txt_path).is_file():
        shutil.copy2(
            txt_path,
            subtitles_dir / ("analysis_transcript.txt" if analysis_transcript else "transcript.txt"),
        )
    if srt_path and Path(srt_path).is_file():
        shutil.copy2(
            srt_path,
            subtitles_dir / ("analysis.srt" if analysis_transcript else "master.srt"),
        )
    if report_path and Path(report_path).is_file():
        shutil.copy2(report_path, reports_dir / Path(report_path).name)
    original_outputs = {"txt": txt_path}
    if srt_path:
        original_outputs["srt"] = srt_path
    project = project_from_runtime_cues(
        media_path,
        cues,
        report_path=report_path,
        original_outputs=original_outputs,
        generation_metadata=metadata,
        asr_evidence=evidence,
        glossary_ids=glossary_ids,
    )
    provisional_rows = [
        dict(item)
        for item in metadata.get("asr_provisional_cues", [])
        if isinstance(item, Mapping)
    ]
    if provisional_rows:
        states: dict[str, str] = {
            str(item.get("id") or ""): "invalidated"
            for item in provisional_rows
            if str(item.get("id") or "")
        }
        replacement: dict[str, list[str]] = {}
        for item in provisional_rows:
            provisional_id = str(item.get("id") or "")
            if not provisional_id:
                continue
            start_ms = int(item.get("start_ms") or 0)
            end_ms = max(start_ms + 1, int(item.get("end_ms") or start_ms + 1))
            replacement[provisional_id] = [
                cue.id
                for cue in project.cues
                if cue.end_ms > start_ms and cue.start_ms < end_ms
            ]
        states.update({cue.id: "final" for cue in project.cues})
        project.generation_metadata["asr_cue_states"] = states
        project.generation_metadata["asr_replacement_mapping"] = replacement
    for cue in project.cues:
        cue.evidence_refs = [
            reference
            for reference, row in segment_rows
            if int(row["end_ms"]) > cue.start_ms and int(row["start_ms"]) < cue.end_ms
        ]
    if project_path.is_file():
        existing = load_project(project_path)
        existing_media = os.path.normcase(os.path.abspath(existing.media.path))
        incoming_media = os.path.normcase(os.path.abspath(os.fspath(media_path)))
        if existing_media and existing_media != incoming_media:
            raise ProjectValidationError(
                "recognition target project belongs to a different media file"
            )
        if analysis_transcript:
            analysis_payload = {
                "updated_at": _utc_now(),
                "generation_metadata": metadata,
                "glossary_ids": _string_list(list(glossary_ids)),
                "cues": project.to_dict().get("cues", []),
                "speakers": project.to_dict().get("speakers", []),
                "asr_evidence": project.asr_evidence,
                "outputs": original_outputs,
            }
            existing.studio_state["analysis_transcript"] = analysis_payload
            # 三十一轮：快速分析的最终带时间轴 cue 直接留在工程里。流式
            # provisional cue 在识别过程中进了列表，完成后若被整批清空，
            # 用户看到的就是"二十分钟识别完字幕全消失"。仅当工程没有
            # 正式字幕（或现有字幕本身就是上次分析稿）时采纳；正式识别
            # （replace_cues）仍然整体替换。
            prior_states = _mapping(existing.generation_metadata).get("asr_cue_states") or {}
            prior_cues_all_from_asr = bool(existing.cues) and all(
                str(prior_states.get(cue.id)) in {"final", "invalidated", "provisional"}
                for cue in existing.cues
            )
            if not existing.cues or prior_cues_all_from_asr:
                existing.cues = project.cues
                existing.speakers = existing.speakers or project.speakers
                if project.generation_metadata.get("asr_cue_states"):
                    merged_meta = dict(existing.generation_metadata or {})
                    merged_meta["asr_cue_states"] = dict(
                        project.generation_metadata["asr_cue_states"]
                    )
                    merged_meta["asr_replacement_mapping"] = dict(
                        project.generation_metadata.get("asr_replacement_mapping", {})
                    )
                    existing.generation_metadata = merged_meta
            project = existing
        else:
            project.project_id = existing.project_id
            project.created_at = existing.created_at
            # Recognition and manual Studio import share one MediaAsset graph.
            # Keep established edits, then hydrate that same graph with the
            # fresh source probe created above.
            project.media = existing.media
            project.media_pool = existing.media_pool
            project.video_tracks = existing.video_tracks
            project.audio_tracks = existing.audio_tracks
            project.av_track_groups = existing.av_track_groups
            project.styles = existing.styles
            project.effects = existing.effects
            project.style_recipes = existing.style_recipes
            project.render_settings = existing.render_settings
            project.studio_state = existing.studio_state
            project.edit_sequence = existing.edit_sequence
            project.edit_history = existing.edit_history
            from .studio_helpers import probe_media_identity

            try:
                identity = probe_media_identity(media_path)
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                project.generation_metadata["media_contract_probe_error"] = str(exc)
            else:
                hydrate_media_contract(project, identity, source_path=media_path)
    if recognition_snapshot:
        from .recognition_input import attach_timeline_result
        project = attach_timeline_result(project, recognition_snapshot)
    save_project(project, project_path)
    register_recent_project(project_path, source_media=str(Path(media_path).resolve()), cue_count=len(project.cues))
    return {"project": str(project_path), "txt": str(txt_path)}


def analysis_transcript_cues(project: SubtitleProject) -> list[StudioCue]:
    """Return the non-destructive fast transcript stored for Clip Assistant."""
    payload = _mapping(project.studio_state.get("analysis_transcript"))
    cues: list[StudioCue] = []
    for raw in payload.get("cues", []) if isinstance(payload.get("cues"), list) else []:
        if not isinstance(raw, Mapping):
            continue
        try:
            cue = StudioCue(
                id=str(raw.get("id") or ""),
                start_ms=int(raw.get("start_ms") or 0),
                end_ms=int(raw.get("end_ms") or 0),
                text=str(raw.get("text") or ""),
                speaker_id=str(raw.get("speaker_id") or "S00"),
                original_text=str(raw.get("original_text") or raw.get("text") or ""),
                evidence_refs=_string_list(raw.get("evidence_refs")),
            )
            cue.validate()
        except (TypeError, ValueError, ProjectValidationError):
            continue
        cues.append(cue)
    return cues
