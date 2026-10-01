"""Immutable render and persistence revisions for Subtitle Studio.

The GUI owns the mutable project graph.  Workers only receive the frozen DTOs
defined here, so a background compile or autosave can never observe a project
halfway through a transaction.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping

from .studio_edit_sequence import sequence_of
from .studio_project import (
    PROJECT_SCHEMA_VERSION,
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    SubtitleStyle,
)
from .studio_runtime_state import DirtyDomain, StateDelta


@dataclass(frozen=True, slots=True)
class FrozenMap:
    items: tuple[tuple[str, "FrozenJSON"], ...] = ()


FrozenJSON = None | bool | int | float | str | tuple["FrozenJSON", ...] | FrozenMap


def freeze_json(value: Any) -> FrozenJSON:
    if isinstance(value, Mapping):
        return FrozenMap(tuple(
            (str(key), freeze_json(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        ))
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"unsupported revision value: {type(value).__name__}")


def thaw_json(value: FrozenJSON) -> Any:
    if isinstance(value, FrozenMap):
        return {key: thaw_json(item) for key, item in value.items}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class RenderCueDTO:
    id: str
    start_ms: int
    end_ms: int
    text: str
    speaker_id: str
    style_id: str
    effect_id: str
    original_text: str
    evidence_refs: tuple[str, ...]
    raw_ass_override: str
    appearance_override: FrozenJSON
    transform: FrozenJSON
    base_preset_id: str = ""
    appearance_generation: int = 0

    @classmethod
    def capture(cls, cue: StudioCue) -> "RenderCueDTO":
        return cls(
            id=str(cue.id),
            start_ms=int(cue.start_ms),
            end_ms=int(cue.end_ms),
            text=str(cue.text),
            speaker_id=str(cue.speaker_id),
            style_id=str(cue.style_id),
            effect_id=str(cue.effect_id),
            original_text=str(cue.original_text),
            evidence_refs=tuple(str(item) for item in cue.evidence_refs),
            raw_ass_override=str(cue.raw_ass_override),
            appearance_override=freeze_json(cue.appearance_override),
            transform=freeze_json(cue.transform),
            base_preset_id=str(cue.base_preset_id),
            appearance_generation=int(cue.appearance_generation),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "text": self.text,
            "speaker_id": self.speaker_id,
            "style_id": self.style_id,
            "effect_id": self.effect_id,
            "original_text": self.original_text,
            "evidence_refs": list(self.evidence_refs),
            "raw_ass_override": self.raw_ass_override,
            "appearance_override": thaw_json(self.appearance_override),
            "transform": thaw_json(self.transform),
            "base_preset_id": self.base_preset_id,
            "appearance_generation": self.appearance_generation,
        }


@dataclass(frozen=True, slots=True)
class RenderStyleDTO:
    id: str
    name: str
    font_family: str
    font_size: float
    primary_color: str
    outline_color: str
    outline_width: float
    outline2_color: str
    outline2_width: float
    shadow: float
    bold: bool
    italic: bool
    underline: bool
    back_color: str
    border_style: int
    spacing: float
    alignment: int
    margin_l: int
    margin_r: int
    margin_v: int
    position_x: int | None
    position_y: int | None
    scale_x: float
    scale_y: float
    font_style_name: str = ""
    font_weight: int = 0
    font_file: str = ""
    font_face_index: int = 0

    @classmethod
    def capture(cls, style: SubtitleStyle) -> "RenderStyleDTO":
        return cls(**{
            field: getattr(style, field)
            for field in cls.__dataclass_fields__
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        }


@dataclass(frozen=True, slots=True)
class SpeakerDTO:
    id: str
    name: str
    style_id: str
    color: str

    @classmethod
    def capture(cls, speaker: StudioSpeaker) -> "SpeakerDTO":
        return cls(str(speaker.id), str(speaker.name), str(speaker.style_id), str(speaker.color))

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id, "name": self.name,
            "style_id": self.style_id, "color": self.color,
        }


@dataclass(frozen=True, slots=True)
class MediaDTO:
    path: str
    display_name: str
    duration_ms: int
    fingerprint: str
    width: int
    height: int

    @classmethod
    def capture(cls, media: StudioMedia) -> "MediaDTO":
        return cls(
            str(media.path), str(media.display_name), int(media.duration_ms),
            str(media.fingerprint), int(media.width), int(media.height),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path, "display_name": self.display_name,
            "duration_ms": self.duration_ms, "fingerprint": self.fingerprint,
            "width": self.width, "height": self.height,
        }


@dataclass(frozen=True, slots=True)
class SubtitleRenderRevision:
    project_id: str
    revision_id: int
    mapping_revision: int
    visual_revision: int
    play_res_x: int
    play_res_y: int
    cues: tuple[RenderCueDTO, ...]
    styles: tuple[RenderStyleDTO, ...]
    speakers: tuple[SpeakerDTO, ...]
    effects: FrozenJSON
    style_recipes: FrozenJSON
    preview_key: str = ""
    generation_metadata: FrozenJSON = ""
    studio_state: FrozenJSON = ""
    frame_rate: object = None
    # LIVE consumers select cues in project time; native ASS uses source time.
    timeline_cues: tuple[RenderCueDTO, ...] | None = None

    @property
    def compile_key(self) -> tuple[str, int, int, str]:
        # The bilingual flag rides inside preview_key so toggling the mode
        # produces a new key (and thus a fresh ASS compile) without changing
        # the tuple arity consumers compare.
        from .studio_revisions import thaw_json

        state = thaw_json(self.studio_state) if self.studio_state else {}
        flag = "bi" if isinstance(state, Mapping) and state.get("bilingual_mode") else "mono"
        return (
            self.project_id,
            self.mapping_revision,
            self.visual_revision,
            f"{self.preview_key}|{flag}",
        )


@dataclass(frozen=True, slots=True)
class PersistenceRevision:
    generation: int
    project_id: str
    schema_version: int
    created_at: str
    updated_at: str
    media: MediaDTO
    media_pool: FrozenJSON
    video_tracks: FrozenJSON
    audio_tracks: FrozenJSON
    av_track_groups: FrozenJSON
    cues: tuple[RenderCueDTO, ...]
    speakers: tuple[SpeakerDTO, ...]
    styles: tuple[RenderStyleDTO, ...]
    effects: FrozenJSON
    style_recipes: FrozenJSON
    generation_metadata: FrozenJSON
    asr_evidence: FrozenJSON
    glossary_ids: tuple[str, ...]
    edit_history: FrozenJSON
    render_settings: FrozenJSON
    report_path: str
    original_outputs: FrozenJSON
    studio_state: FrozenJSON
    edit_sequence: FrozenJSON

    def to_payload(self) -> dict[str, Any]:
        return {
            "media": self.media.to_dict(),
            "media_pool": thaw_json(self.media_pool),
            "video_tracks": thaw_json(self.video_tracks),
            "audio_tracks": thaw_json(self.audio_tracks),
            "av_track_groups": thaw_json(self.av_track_groups),
            "cues": [cue.to_dict() for cue in self.cues],
            "speakers": [speaker.to_dict() for speaker in self.speakers],
            "styles": [style.to_dict() for style in self.styles],
            "effects": thaw_json(self.effects),
            "style_recipes": thaw_json(self.style_recipes),
            "generation_metadata": thaw_json(self.generation_metadata),
            "asr_evidence": thaw_json(self.asr_evidence),
            "glossary_ids": list(self.glossary_ids),
            "edit_history": thaw_json(self.edit_history),
            "render_settings": thaw_json(self.render_settings),
            "report_path": self.report_path,
            "original_outputs": thaw_json(self.original_outputs),
            "studio_state": thaw_json(self.studio_state),
            "edit_sequence": thaw_json(self.edit_sequence),
            "project_id": self.project_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "schema_version": self.schema_version,
        }


_CUE_DIRTY = (
    DirtyDomain.CUE_MODEL | DirtyDomain.CUE_CONTENT
    | DirtyDomain.CUE_TIMING | DirtyDomain.CUE_STYLE
)
_STYLE_DIRTY = DirtyDomain.CUE_STYLE | DirtyDomain.ADVANCED_PREVIEW
_MAPPING_DIRTY = (
    DirtyDomain.CUE_MODEL | DirtyDomain.CUE_TIMING
    | DirtyDomain.SEQUENCE_STRUCTURE | DirtyDomain.PROJECT_METADATA
)
_VISUAL_DIRTY = (
    DirtyDomain.CUE_MODEL | DirtyDomain.CUE_CONTENT | DirtyDomain.CUE_TIMING
    | DirtyDomain.CUE_STYLE | DirtyDomain.ADVANCED_PREVIEW
    | DirtyDomain.PROJECT_METADATA
)


class StudioRevisionStore:
    """Project-lifetime structural-sharing boundary for worker inputs."""

    def __init__(self, project: SubtitleProject, *, revision: int = 0) -> None:
        self.project = project
        self.mapping_revision = 1
        self.visual_revision = 1
        self._cues = tuple(RenderCueDTO.capture(cue) for cue in project.cues)
        self._render_cues = self._capture_render_cues()
        self._timeline_cues = self._capture_timeline_cues()
        self._styles = tuple(RenderStyleDTO.capture(style) for style in project.styles)
        self._speakers = tuple(SpeakerDTO.capture(speaker) for speaker in project.speakers)
        self._effects = freeze_json(project.effects)
        self._recipes = freeze_json(project.style_recipes)
        self._persistence = self._capture_persistence(revision)
        self.render = self._capture_render(revision)

    def _capture_render_cues(self) -> tuple:
        """2026-09-19 P0：预览渲染（native ASS）用 source 域投影。

        mpv 在 mapped 序列下时钟恒在源域——此前 ASS 事件是 remap 出来的
        序列时间，剪辑模式视频字幕永不命中。identity 序列零开销直通
        （直接复用持久化捕获的同一批 DTO，不重复 capture）。
        持久化（autosave/保存）仍捕获 project.cues 全集，永不被片段视图
        污染。
        """
        from .studio_edit_sequence import projected_cues, sequence_of

        if sequence_of(self.project).is_identity():
            return tuple(self._cues)
        return tuple(
            RenderCueDTO.capture(cue)
            for cue in projected_cues(self.project, domain="source")
        )

    def _capture_timeline_cues(self) -> tuple:
        from .studio_edit_sequence import projected_cues, sequence_of
        if sequence_of(self.project).is_identity():
            return self._cues
        return tuple(RenderCueDTO.capture(c) for c in projected_cues(self.project, domain='timeline'))

    def _capture_render(self, revision: int) -> SubtitleRenderRevision:
        settings = self.project.render_settings
        from .caption_frame_time import project_frame_rate
        return SubtitleRenderRevision(
            project_id=str(self.project.project_id),
            revision_id=int(revision),
            mapping_revision=self.mapping_revision,
            visual_revision=self.visual_revision,
            play_res_x=max(1, int(settings.get("play_res_x", 1920))),
            play_res_y=max(1, int(settings.get("play_res_y", 1080))),
            cues=self._render_cues,
            styles=self._styles,
            speakers=self._speakers,
            effects=self._effects,
            style_recipes=self._recipes,
            generation_metadata=freeze_json(self.project.generation_metadata or {}),
            studio_state=freeze_json(self.project.studio_state or {}),
            frame_rate=project_frame_rate(self.project),
            timeline_cues=self._timeline_cues,
        )

    def _capture_persistence(self, generation: int) -> PersistenceRevision:
        project = self.project
        state = getattr(project, '_studio_state_runtime', None)
        if state is not None and state._active is not None:
            raise RuntimeError("不能在媒体编辑事务提交前捕获保存快照")
        from .studio_media_pool import validate_media_graph
        validate_media_graph(project)
        return PersistenceRevision(
            generation=int(generation),
            project_id=str(project.project_id),
            schema_version=int(project.schema_version or PROJECT_SCHEMA_VERSION),
            created_at=str(project.created_at), updated_at=str(project.updated_at),
            media=MediaDTO.capture(project.media),
            media_pool=freeze_json([asdict(asset) for asset in project.media_pool]),
            video_tracks=freeze_json([asdict(track) for track in project.video_tracks]),
            audio_tracks=freeze_json([asdict(track) for track in project.audio_tracks]),
            av_track_groups=freeze_json([asdict(group) for group in project.av_track_groups]),
            cues=self._cues, speakers=self._speakers, styles=self._styles,
            effects=self._effects, style_recipes=self._recipes,
            generation_metadata=freeze_json(project.generation_metadata),
            asr_evidence=freeze_json(project.asr_evidence),
            glossary_ids=tuple(str(item) for item in project.glossary_ids),
            edit_history=freeze_json(project.edit_history),
            render_settings=freeze_json(project.render_settings),
            report_path=str(project.report_path),
            original_outputs=freeze_json(project.original_outputs),
            studio_state=freeze_json(project.studio_state),
            edit_sequence=freeze_json(sequence_of(project).to_dict()),
        )

    @property
    def persistence(self) -> PersistenceRevision:
        return self._persistence

    def consume(self, delta: StateDelta) -> None:
        project = self.project
        dirty = delta.dirty
        if not dirty & (_VISUAL_DIRTY | _MAPPING_DIRTY | _STYLE_DIRTY | DirtyDomain.AUTOSAVE):
            # Selection/paint/QC is not a render revision. Re-freezing all ASR
            # metadata here made selection cost grow with the entire project.
            self.render = replace(self.render, revision_id=delta.revision)
            return
        if dirty & _CUE_DIRTY:
            current = {cue.id: cue for cue in project.cues}
            if dirty & DirtyDomain.CUE_MODEL or not delta.affected_cue_ids:
                self._cues = tuple(RenderCueDTO.capture(cue) for cue in project.cues)
            else:
                affected = delta.affected_cue_ids
                self._cues = tuple(
                    RenderCueDTO.capture(current[item.id])
                    if item.id in affected and item.id in current else item
                    for item in self._cues
                    if item.id in current
                )
            # 文本/时间编辑也要反映进 source 域投影（剪辑模式重派生；
            # identity 走快路径复用 _cues）。
            self._render_cues = self._capture_render_cues()
        if dirty & _STYLE_DIRTY:
            self._styles = tuple(RenderStyleDTO.capture(style) for style in project.styles)
            self._effects = freeze_json(project.effects)
            self._recipes = freeze_json(project.style_recipes)
        if dirty & DirtyDomain.PROJECT_METADATA:
            self._speakers = tuple(SpeakerDTO.capture(speaker) for speaker in project.speakers)
        if dirty & _MAPPING_DIRTY:
            self.mapping_revision += 1
            # 序列结构变化会改变 source 域投影（预览 ASS 的 cue 集合与
            # 裁边时间），必须重捕获渲染 cue。
            self._render_cues = self._capture_render_cues()
        if dirty & _VISUAL_DIRTY:
            self.visual_revision += 1
        if dirty & (_CUE_DIRTY | _MAPPING_DIRTY):
            self._timeline_cues = self._capture_timeline_cues()
        self.render = self._capture_render(delta.revision)
        if dirty & DirtyDomain.AUTOSAVE:
            self._persistence = self._capture_persistence(delta.revision)

    def refresh_persistence(self, generation: int) -> PersistenceRevision:
        # Studio viewport/layout fields are captured immediately before the
        # debounced autosave. Heavy cue/style tuples remain structurally shared.
        self._persistence = self._capture_persistence(generation)
        return self._persistence


def preview_render_revision(
    revision: SubtitleRenderRevision,
    *,
    text_overrides: Mapping[str, str] | None = None,
    transform_overrides: Mapping[str, Mapping[str, float | int]] | None = None,
    hidden_cue_ids: set[str] | frozenset[str] | None = None,
) -> SubtitleRenderRevision:
    """Derive a narrow live-preview revision without cloning the project."""

    texts = {str(key): str(value) for key, value in (text_overrides or {}).items()}
    transforms = {
        str(key): {str(name): item for name, item in value.items()}
        for key, value in (transform_overrides or {}).items()
    }
    hidden = set(hidden_cue_ids or ())
    styles = list(revision.styles)
    recipes = thaw_json(revision.style_recipes)
    if not isinstance(recipes, dict):
        recipes = {}
    derived_cues: list[RenderCueDTO] = []
    styles_by_id = {style.id: style for style in styles}
    for cue in revision.cues:
        # Route suppression outranks live text overrides. Advanced text edits
        # are rendered by LIVE; allowing an override to reinsert the cue into
        # ASS recreates the solid-frame flash and duplicate foreground.
        if cue.id in hidden:
            continue
        derived = replace(cue, text=texts[cue.id]) if cue.id in texts else cue
        transform = transforms.get(cue.id)
        if transform:
            source = styles_by_id.get(derived.style_id)
            if source is not None:
                # Shared source styles still need independent live transforms.
                live_id = f"{source.id}-live-transform-{derived.id}"
                live = replace(
                    source,
                    id=live_id,
                    position_x=(
                        int(transform["position_x"])
                        if "position_x" in transform else source.position_x
                    ),
                    position_y=(
                        int(transform["position_y"])
                        if "position_y" in transform else source.position_y
                    ),
                    font_size=float(transform.get("font_size", source.font_size)),
                )
                styles = [item for item in styles if item.id != live_id] + [live]
                payload = recipes.get(source.id)
                if isinstance(payload, dict):
                    live_recipe = thaw_json(freeze_json(payload))
                    layout = live_recipe.setdefault("layout", {})
                    typography = live_recipe.setdefault("typography", {})
                    if "position_x" in transform:
                        layout["positionX"] = int(transform["position_x"])
                    if "position_y" in transform:
                        layout["positionY"] = int(transform["position_y"])
                    if "font_size" in transform:
                        typography["fontSize"] = float(transform["font_size"])
                    recipes[live_id] = live_recipe
                derived = replace(derived, style_id=live_id)
        derived_cues.append(derived)
    preview_payload = {
        "texts": sorted(texts.items()),
        "transforms": [
            [cue_id, sorted(values.items())]
            for cue_id, values in sorted(transforms.items())
        ],
        "hidden": sorted(hidden),
    }
    preview_key = ""
    if texts or transforms or hidden:
        encoded = json.dumps(
            preview_payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        preview_key = hashlib.sha256(encoded).hexdigest()
    return replace(
        revision,
        cues=tuple(derived_cues), styles=tuple(styles),
        style_recipes=freeze_json(recipes),
        preview_key=preview_key,
    )
