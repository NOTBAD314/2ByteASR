"""Low-cost, disk-cached Remotion still previews for Studio."""

from __future__ import annotations

import json
import os
import time
import hashlib
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence

from .advanced_renderer import (
    AdvancedRendererBackend, advanced_preview_cache_key, cue_visual_cache_key,
    normalized_visual_snapshot, scale_visual_for_composition, _normalized_recipe,
)
from .visual_snapshot import VisualCueSnapshot
from .renderer_service import GLOBAL_RENDERER_SERVICE, RendererJob, RendererService
from .style_recipe import MOTION_MODE_NONE, motion_mode


class AdvancedPreviewPhase(str, Enum):
    NONE = "NONE"
    FALLBACK_NATIVE = "FALLBACK_NATIVE"
    PREPARING = "PREPARING"
    ADVANCED_READY = "ADVANCED_READY"
    ADVANCED_VISIBLE = "ADVANCED_VISIBLE"
    STALE = "STALE"
    FAILED = "FAILED"


class AdvancedPreviewResidency(str, Enum):
    NOT_READY = "NOT_READY"
    LIVE = "LIVE"
    FIDELITY = "FIDELITY"
    CACHED_FIDELITY = "CACHED_FIDELITY"


@dataclass(frozen=True)
class AdvancedPreviewIdentity:
    cue_id: str
    snapshot_hash: str
    glyph_key: str
    motion_key: str
    request_key: str
    motion_time_ms: int
    resolution: tuple[int, int]
    fps: float
    graph_hash: str = ""
    appearance_generation: int = 0
    job_id: str = ""
    job_kind: str = "production"
    project_id: str = ""
    requested_at: float = 0.0

    @classmethod
    def from_snapshot(
        cls,
        snapshot: VisualCueSnapshot,
        *,
        width: int,
        height: int,
        motion_time_ms: int,
        job_kind: str = "production",
    ) -> "AdvancedPreviewIdentity":
        resolution = (max(1, int(width)), max(1, int(height)))
        fps = float(snapshot.fps)
        recipe = snapshot.style_recipe if isinstance(snapshot.style_recipe, Mapping) else {}
        graph = recipe.get("visualGraph") if isinstance(recipe, Mapping) else {}
        graph_hash = _hash_key("visual-graph-v1", graph) if isinstance(graph, Mapping) and graph else ""
        glyph_key = _hash_key(
            "pixel-v6",
            snapshot.pixel_hash(renderer_version="remotion-fidelity-v6", resolution=resolution),
        )
        motion_key = _hash_key("motion-v6", glyph_key, snapshot.motion_recipe, fps)
        # Quantize only the frame request. The motion cache bucket remains
        # stable across playhead movement and can hold multiple seek-safe frames.
        # v2: preview frames now rescale type to the composition width; v1
        # frames were rendered at play-resolution font sizes and must expire.
        frame_ms = round(max(0, int(motion_time_ms)) * fps / 1000.0) * 1000.0 / max(1.0, fps)
        request_key = (
            _hash_key("frame-v6-static", glyph_key, snapshot.project_id, job_kind)
            if motion_mode(snapshot.motion_recipe) == MOTION_MODE_NONE
            else _hash_key(
                "frame-v6-animated", motion_key, round(frame_ms, 3),
                snapshot.project_id, job_kind,
            )
        )
        return cls(
            cue_id=snapshot.cue_id,
            snapshot_hash=snapshot.stable_hash(),
            glyph_key=glyph_key,
            motion_key=motion_key,
            request_key=request_key,
            motion_time_ms=max(0, int(motion_time_ms)),
            resolution=resolution,
            fps=fps,
            graph_hash=graph_hash,
            appearance_generation=max(0, int(snapshot.appearance_generation)),
            job_id=uuid.uuid4().hex,
            job_kind=str(job_kind or "production"),
            project_id=str(snapshot.project_id or ""),
            requested_at=time.time(),
        )


def _hash_key(*parts: object) -> str:
    return hashlib.sha256(
        json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class AdvancedPreviewStateMachine:
    """Single-owner state for the selected Advanced cue."""

    def __init__(self):
        self.phase = AdvancedPreviewPhase.NONE
        self.residency = AdvancedPreviewResidency.NOT_READY
        self.identity: AdvancedPreviewIdentity | None = None
        self.generation = 0
        self.frame_path = ""
        self.error = ""
        self._ready_paths: dict[str, str] = {}

    def select(self, identity: AdvancedPreviewIdentity, *, cache_hit: bool, force: bool = False) -> int:
        same_request = (
            self.identity is not None
            and self.identity.request_key == identity.request_key
            and self.identity.cue_id == identity.cue_id
            and self.identity.appearance_generation == identity.appearance_generation
            and self.identity.snapshot_hash == identity.snapshot_hash
            and self.identity.graph_hash == identity.graph_hash
        )
        self.identity = identity
        self.error = ""
        ready_path = self._ready_paths.get(identity.request_key, "")
        if (cache_hit or ready_path) and not force:
            self.frame_path = ready_path
            self.phase = AdvancedPreviewPhase.ADVANCED_READY
            self.residency = AdvancedPreviewResidency.CACHED_FIDELITY
            return self.generation
        if force or not same_request or self.phase in {
            AdvancedPreviewPhase.NONE,
            AdvancedPreviewPhase.FALLBACK_NATIVE,
            AdvancedPreviewPhase.STALE,
            AdvancedPreviewPhase.FAILED,
        }:
            self.generation += 1
        self.frame_path = ""
        self.phase = AdvancedPreviewPhase.PREPARING
        self.residency = AdvancedPreviewResidency.NOT_READY
        return self.generation

    def invalidate_current(self) -> int:
        """Reject every result created before the newest user mutation."""

        self.generation += 1
        self.frame_path = ""
        self.error = ""
        if self.identity is not None:
            self.phase = AdvancedPreviewPhase.STALE
        self.residency = AdvancedPreviewResidency.NOT_READY
        return self.generation

    def mark_live(self, identity: AdvancedPreviewIdentity) -> bool:
        if not self._matches_current(identity):
            return False
        self.residency = AdvancedPreviewResidency.LIVE
        return True

    def publish_ready(
        self,
        identity: AdvancedPreviewIdentity,
        generation: int,
        frame_path: str,
        *,
        cache_hit: bool = False,
    ) -> bool:
        if generation != self.generation or not self._matches_current(identity):
            return False
        self.frame_path = str(frame_path)
        self._ready_paths[identity.request_key] = self.frame_path
        self.phase = AdvancedPreviewPhase.ADVANCED_READY
        self.residency = (
            AdvancedPreviewResidency.CACHED_FIDELITY
            if cache_hit else AdvancedPreviewResidency.FIDELITY
        )
        self.error = ""
        return True

    def mark_visible(self, identity: AdvancedPreviewIdentity) -> bool:
        if not self._matches_current(identity):
            return False
        if self.phase not in {AdvancedPreviewPhase.ADVANCED_READY, AdvancedPreviewPhase.ADVANCED_VISIBLE}:
            return False
        self.phase = AdvancedPreviewPhase.ADVANCED_VISIBLE
        return True

    def mark_stale(self, identity: AdvancedPreviewIdentity, generation: int) -> None:
        if self._matches_current(identity) and generation == self.generation:
            self.phase = AdvancedPreviewPhase.STALE

    def fail(self, identity: AdvancedPreviewIdentity, generation: int, message: str) -> bool:
        if not self._matches_current(identity) or generation != self.generation:
            return False
        self.phase = AdvancedPreviewPhase.FAILED
        if self.residency != AdvancedPreviewResidency.LIVE:
            self.residency = AdvancedPreviewResidency.NOT_READY
        self.frame_path = ""
        self.error = str(message)
        return True

    def fallback(self) -> None:
        self.phase = AdvancedPreviewPhase.FALLBACK_NATIVE
        self.residency = AdvancedPreviewResidency.NOT_READY

    @property
    def owns_visual(self) -> bool:
        return self.phase == AdvancedPreviewPhase.ADVANCED_VISIBLE

    def _matches_current(self, identity: AdvancedPreviewIdentity) -> bool:
        current = self.identity
        return bool(
            current is not None
            and identity.cue_id == current.cue_id
            and identity.appearance_generation == current.appearance_generation
            and identity.snapshot_hash == current.snapshot_hash
            and identity.graph_hash == current.graph_hash
            and identity.request_key == current.request_key
            and identity.job_id == current.job_id
            and identity.job_kind == current.job_kind
            and identity.project_id == current.project_id
        )


class AdvancedPreviewCache:
    DEFAULT_BUDGET_BYTES = 2 * 1024 * 1024 * 1024

    def __init__(
        self,
        root: str | os.PathLike[str] | None = None,
        *,
        budget_bytes: int = DEFAULT_BUDGET_BYTES,
        renderer_service: RendererService | None = None,
    ):
        default = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "2ByteASR" / "cache" / "advanced-preview"
        self.root = Path(root or default).resolve()
        self.budget_bytes = max(16 * 1024 * 1024, int(budget_bytes))
        self.renderer_service = renderer_service or GLOBAL_RENDERER_SERVICE

    def key(self, recipe: Mapping[str, object], text: str, *, width: int = 640, height: int = 360,
            fps: float = 30.0, duration_seconds: float = 1.2, font: str = "Microsoft YaHei UI") -> str:
        return advanced_preview_cache_key(
            recipe, text, width=width, height=height, fps=fps,
            duration_seconds=duration_seconds, font=font,
        )

    def path_for(self, key: str) -> Path:
        return self.root / f"{key}.png"

    def snapshot_key(self, snapshot: VisualCueSnapshot, *, relative_ms: int = 300,
                     width: int | None = None, height: int | None = None,
                     job_kind: str = "production") -> str:
        """Key one authoritative visual at one seek-safe preview instant."""
        width = int(width or snapshot.resolution[0])
        height = int(height or snapshot.resolution[1])
        return self.identity(
            snapshot, relative_ms=relative_ms, width=width, height=height,
            job_kind=job_kind,
        ).request_key

    def identity(self, snapshot: VisualCueSnapshot, *, relative_ms: int = 300,
                 width: int | None = None, height: int | None = None,
                 job_kind: str = "production") -> AdvancedPreviewIdentity:
        return AdvancedPreviewIdentity.from_snapshot(
            snapshot,
            width=int(width or snapshot.resolution[0]),
            height=int(height or snapshot.resolution[1]),
            motion_time_ms=relative_ms,
            job_kind=job_kind,
        )

    def discard_if_stale(self, generation: int, current_generation: int) -> bool:
        """Workers use this before publishing a completed frame."""
        return int(generation) != int(current_generation)

    def enforce_budget(self) -> None:
        if not self.root.is_dir():
            return
        files = [p for p in self.root.glob("*.png") if p.is_file()]
        total = sum(p.stat().st_size for p in files)
        if total <= self.budget_bytes:
            return
        for path in sorted(files, key=lambda p: p.stat().st_atime):
            if total <= self.budget_bytes:
                break
            try:
                size = path.stat().st_size
                path.unlink()
                total -= size
            except OSError:
                continue

    def render(self, recipe: Mapping[str, object], text: str, *, width: int = 640, height: int = 360,
               fps: float = 30.0, duration_seconds: float = 1.2, font: str = "Microsoft YaHei UI") -> tuple[str, Path, bool]:
        key = self.key(recipe, text, width=width, height=height, fps=fps, duration_seconds=duration_seconds, font=font)
        target = self.path_for(key)
        if target.is_file() and target.stat().st_size > 0:
            return key, target, True
        backend = AdvancedRendererBackend()
        backend.require_available()
        self.root.mkdir(parents=True, exist_ok=True)
        normalized = _normalized_recipe(recipe)
        normalized["typography"]["fontFamily"] = font
        props = {
            "schemaVersion": 1, "width": width, "height": height, "fps": fps,
            "durationInFrames": max(1, round(duration_seconds * fps)),
            "cues": [{"id": "preview", "text": text, "startMs": 0,
                      "endMs": round(duration_seconds * 1000), "styleId": "preview-style"}],
            "recipes": {"preview-style": normalized},
        }
        job = RendererJob(
            str(target), props, max(1, round(fps * 0.35)),
            job_id=uuid.uuid4().hex,
            job_kind="thumbnail",
            cue_id="preview",
            requested_at=time.time(),
        )
        result = self.renderer_service.render(
            [job],
            snapshot_identity=key,
            render_type="still",
            resolution=(width, height),
            batch_group=f"legacy-preview:{key}",
            timeout=120.0,
        )
        result.require_job(job)
        if not target.is_file() or target.stat().st_size <= 0:
            raise RuntimeError("Persistent renderer did not publish the preview frame")
        return key, target, False

    @staticmethod
    def _snapshot_props(
        snapshot: VisualCueSnapshot,
        *,
        width: int,
        height: int,
    ) -> tuple[dict[str, object], int]:
        visual = scale_visual_for_composition(
            normalized_visual_snapshot(snapshot), composition_width=width,
        )
        duration_seconds = max(0.12, (snapshot.end_ms - snapshot.start_ms) / 1000.0)
        props: dict[str, object] = {
            "schemaVersion": 1, "width": width, "height": height, "fps": snapshot.fps,
            "durationInFrames": max(1, round(duration_seconds * snapshot.fps)),
            "cues": [{"id": snapshot.cue_id, "text": snapshot.text,
                      "translation": getattr(snapshot, "translation", ""), "startMs": 0,
                      "endMs": round(duration_seconds * 1000), "styleId": "cue-style",
                      "visual": visual, "snapshotHash": snapshot.stable_hash()}],
            "recipes": {"cue-style": visual},
        }
        return props, int(props["durationInFrames"])

    def render_snapshot(
        self,
        snapshot: VisualCueSnapshot,
        *,
        force: bool = False,
        relative_ms: int = 300,
        width: int | None = None,
        height: int | None = None,
        generation: int | None = None,
        batch_group: str = "",
        job_kind: str = "production",
        identity: AdvancedPreviewIdentity | None = None,
    ) -> tuple[str, Path, bool]:
        """Render a real cue at its authoritative position/scale/style."""
        width = int(width or snapshot.resolution[0])
        height = int(height or snapshot.resolution[1])
        identity = identity or self.identity(
            snapshot, relative_ms=relative_ms, width=width, height=height,
            job_kind=job_kind,
        )
        key = identity.request_key
        target = self.path_for(key)
        if target.is_file() and target.stat().st_size > 0 and not force:
            try:
                os.utime(target, None)
            except OSError:
                pass
            return key, target, True
        backend = AdvancedRendererBackend()
        backend.require_available()
        self.root.mkdir(parents=True, exist_ok=True)
        props, duration_in_frames = self._snapshot_props(snapshot, width=width, height=height)
        preview_frame = min(
            duration_in_frames - 1,
            max(0, round(max(0, int(relative_ms)) * snapshot.fps / 1000.0)),
        )
        job = RendererJob(
            str(target), props, preview_frame,
            job_id=identity.job_id,
            job_kind=identity.job_kind,
            cue_id=identity.cue_id,
            project_id=identity.project_id,
            appearance_generation=identity.appearance_generation,
            snapshot_hash=identity.snapshot_hash,
            graph_hash=identity.graph_hash,
            requested_at=identity.requested_at,
        )
        result = self.renderer_service.render(
            [job],
            generation=generation,
            snapshot_identity=key,
            render_type="still",
            resolution=(width, height),
            batch_group=batch_group or f"cue-fidelity:{snapshot.cue_id}",
            timeout=120.0,
        )
        result.require_job(job)
        if not target.is_file() or target.stat().st_size <= 0:
            raise RuntimeError("Persistent renderer did not publish the cue frame")
        self.enforce_budget()
        return key, target, False

    def render_snapshot_batch(
        self,
        requests: Sequence[tuple[VisualCueSnapshot, int, int, int]],
        *,
        force: bool = False,
        generation: int | None = None,
        batch_group: str,
        render_type: str,
        job_kind: str = "card_preview",
    ) -> list[tuple[str, Path, bool]]:
        """Render all cache misses through one warm browser request."""
        if not requests:
            return []
        backend = AdvancedRendererBackend()
        backend.require_available()
        self.root.mkdir(parents=True, exist_ok=True)
        results: list[tuple[str, Path, bool] | None] = [None] * len(requests)
        jobs: list[RendererJob] = []
        job_indexes: list[int] = []
        keys: list[str] = []
        resolution = (0, 0)
        for index, (snapshot, relative_ms, width, height) in enumerate(requests):
            width, height = max(1, int(width)), max(1, int(height))
            resolution = (width, height)
            identity = self.identity(
                snapshot, relative_ms=relative_ms, width=width, height=height,
                job_kind=job_kind,
            )
            key = identity.request_key
            target = self.path_for(key)
            if target.is_file() and target.stat().st_size > 0 and not force:
                try:
                    os.utime(target, None)
                except OSError:
                    pass
                results[index] = (key, target, True)
                continue
            props, duration_in_frames = self._snapshot_props(snapshot, width=width, height=height)
            preview_frame = min(
                duration_in_frames - 1,
                max(0, round(max(0, int(relative_ms)) * snapshot.fps / 1000.0)),
            )
            jobs.append(RendererJob(
                str(target), props, preview_frame,
                job_id=identity.job_id,
                job_kind=identity.job_kind,
                cue_id=identity.cue_id,
                project_id=identity.project_id,
                appearance_generation=identity.appearance_generation,
                snapshot_hash=identity.snapshot_hash,
                graph_hash=identity.graph_hash,
                requested_at=identity.requested_at,
            ))
            job_indexes.append(index)
            keys.append(key)
        if jobs:
            renderer_result = self.renderer_service.render(
                jobs,
                generation=generation,
                snapshot_identity=_hash_key(*(keys or [batch_group])),
                render_type=render_type,
                resolution=resolution,
                batch_group=batch_group,
                timeout=120.0,
            )
            for job in jobs:
                renderer_result.require_job(job)
            for result_index, request_index in enumerate(job_indexes):
                key = keys[result_index]
                target = self.path_for(key)
                if not target.is_file() or target.stat().st_size <= 0:
                    raise RuntimeError(f"Persistent renderer did not publish batch item {result_index}")
                results[request_index] = (key, target, False)
        self.enforce_budget()
        return [item for item in results if item is not None]
