"""One-Stop Auto-Pipeline engine (自动开关流水线, 2026-11-25).

Turns a Series / Saved Scheme into a lightweight 3-step post-recognition
pipeline for single videos OR multi-video batches:

    Video(s) -> 识别 (existing)
             -> Stage 1: 套常用词库 (glossary snapshot precheck + 3-episode graduated rules)
             -> Stage 2: 套常用人名 (saved cast / ECAPA voiceprint naming, never overwrites manual names)
             -> Stage 3: 套常用样式 (saved subtitle style preset, never overwrites manually styled cues)
             -> Handoff: additive receipt in ``project.studio_state['auto_pipeline_receipt']``
                         so each newly delivered project runs once and never repeats.

Strict safety guarantees:
  - Never modifies ``.2byteproj`` ``schema_version = 1`` top-level schema.
  - Only auto-rewrites text for rules explicitly graduated by the user (3 clean episodes).
  - Default glossary precheck is 100% local (terminology snapshot only, zero LLM quota).
  - Never overwrites speakers a person already renamed manually.
  - Never overwrites cues whose style was already edited manually.
  - A failure in any stage never crashes or corrupts the project.
"""
from __future__ import annotations

import copy
import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .series_store import DEFAULT_PIPELINE, SeriesRecord, SeriesStore, VoiceprintObservation

AUTO_PIPELINE_RECEIPT_KEY = "auto_pipeline_receipt"
_IGNORED_SPEAKERS = frozenset({"GAME_BACKGROUND", "SUBTITLES"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_anonymous_speaker(name: str, speaker_id: str = "") -> bool:
    clean = str(name or "").strip()
    if not clean:
        return True
    up = clean.upper()
    if up.startswith(("SPEAKER_", "R00", "API_", "LOCAL_")):
        return True
    if len(up) >= 2 and up[0] == "S" and up[1:].isdigit():
        return True
    if clean.startswith("说话人") and clean[3:].strip().isdigit():
        return True
    if speaker_id and clean == speaker_id and up.startswith("S") and up[1:].isdigit():
        return True
    return False


def _cue_has_manual_style(cue: Any) -> bool:
    """Return True when ``cue`` already carries a non-default or customized style."""
    style_id = str(getattr(cue, "style_id", "default") or "default").strip()
    if style_id != "default":
        return True
    base_preset = str(getattr(cue, "base_preset_id", "default") or "default").strip()
    if base_preset != "default":
        return True
    if getattr(cue, "appearance_override", None):
        return True
    if str(getattr(cue, "raw_ass_override", "") or "").strip():
        return True
    transform = getattr(cue, "transform", None)
    if isinstance(transform, dict):
        layers = transform.get("layers")
        if isinstance(layers, dict):
            for layer_cfg in layers.values():
                if isinstance(layer_cfg, dict) and (layer_cfg.get("style_id") or "font_size" in layer_cfg):
                    return True
    return False


@dataclass
class AutoPipelineConfig:
    enabled: bool = False
    run_glossary: bool = True
    auto_apply_graduated: bool = True
    run_speakers: bool = True
    run_style_preset: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AutoPipelineConfig":
        merged = {**DEFAULT_PIPELINE, **(data if isinstance(data, dict) else {})}
        return cls(
            enabled=bool(merged.get("enabled", False)),
            run_glossary=bool(merged.get("run_glossary", True)),
            auto_apply_graduated=bool(merged.get("auto_apply_graduated", True)),
            run_speakers=bool(merged.get("run_speakers", True)),
            run_style_preset=bool(merged.get("run_style_preset", True)),
        )

    def plain_flow_preview(self) -> str:
        """Compact one-line arrow preview containing only checked stages."""
        steps = ["识别"]
        if self.run_glossary:
            steps.append("套常用词库")
        if self.run_speakers:
            steps.append("套常用人名")
        if self.run_style_preset:
            steps.append("套常用样式")
        return " → ".join(steps)


@dataclass
class PipelineStageResult:
    stage: str           # glossary | speakers | style
    title: str
    status: str          # done | skipped | needs_review | failed
    summary: str
    count: int = 0
    review_count: int = 0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class AutoPipelineReceipt:
    series_id: str
    series_name: str
    project_name: str
    stages: list[PipelineStageResult] = field(default_factory=list)
    total_cues: int = 0
    auto_applied_count: int = 0
    remaining_review_count: int = 0
    elapsed_ms: int = 0
    ran_at: str = field(default_factory=_utc_now)

    def one_line_summary(self) -> str:
        done_parts = [s.summary for s in self.stages if s.status in ("done", "needs_review") and s.summary]
        body = "、".join(done_parts) if done_parts else "已按当前常用方案检查完毕"
        tail = f"；待确认 {self.remaining_review_count} 处" if self.remaining_review_count > 0 else "；无待确认项"
        return f"{body}{tail}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "series_id": self.series_id,
            "series_name": self.series_name,
            "project_name": self.project_name,
            "stages": [asdict(s) for s in self.stages],
            "total_cues": int(self.total_cues),
            "auto_applied_count": int(self.auto_applied_count),
            "remaining_review_count": int(self.remaining_review_count),
            "elapsed_ms": int(self.elapsed_ms),
            "ran_at": self.ran_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AutoPipelineReceipt | None":
        if not isinstance(data, dict) or not isinstance(data.get("stages"), list):
            return None
        stages = [
            PipelineStageResult(
                stage=str(s.get("stage") or ""),
                title=str(s.get("title") or ""),
                status=str(s.get("status") or "skipped"),
                summary=str(s.get("summary") or ""),
                count=int(s.get("count") or 0),
                review_count=int(s.get("review_count") or 0),
                details=copy.deepcopy(s.get("details") or {}),
            )
            for s in data["stages"]
            if isinstance(s, dict)
        ]
        return cls(
            series_id=str(data.get("series_id") or ""),
            series_name=str(data.get("series_name") or ""),
            project_name=str(data.get("project_name") or ""),
            stages=stages,
            total_cues=max(0, int(data.get("total_cues", 0) or 0)),
            auto_applied_count=max(0, int(data.get("auto_applied_count", 0) or 0)),
            remaining_review_count=max(0, int(data.get("remaining_review_count", 0) or 0)),
            elapsed_ms=max(0, int(data.get("elapsed_ms", 0) or 0)),
            ran_at=str(data.get("ran_at") or _utc_now()),
        )


@dataclass
class BatchPipelineSummary:
    series_id: str
    series_name: str
    receipts: list[AutoPipelineReceipt] = field(default_factory=list)
    cancelled: bool = False

    @property
    def total_videos(self) -> int:
        return len(self.receipts)

    @property
    def total_auto_applied(self) -> int:
        return sum(r.auto_applied_count for r in self.receipts)

    @property
    def total_remaining_review(self) -> int:
        return sum(r.remaining_review_count for r in self.receipts)

    def headline(self) -> str:
        prefix = "已取消，已完成前" if self.cancelled else "已处理"
        return (
            f"{prefix} {self.total_videos} 部视频：自动处理 {self.total_auto_applied} 项，"
            f"待确认 {self.total_remaining_review} 处。"
        )


def attach_receipt(project: Any, receipt: AutoPipelineReceipt) -> None:
    state = getattr(project, "studio_state", None)
    if not isinstance(state, dict):
        state = {}
        setattr(project, "studio_state", state)
    state[AUTO_PIPELINE_RECEIPT_KEY] = receipt.to_dict()


def load_receipt(project: Any) -> AutoPipelineReceipt | None:
    state = getattr(project, "studio_state", None)
    if not isinstance(state, dict):
        return None
    raw = state.get(AUTO_PIPELINE_RECEIPT_KEY)
    return AutoPipelineReceipt.from_dict(raw) if isinstance(raw, dict) else None


class _IsolatedGlossaryReader:
    """Read-only glossary view respecting ``2BYTEASR_USER_DATA_ROOT`` without leaking to real AppData."""

    def __init__(self, learned_path: Path, base_legacy: Any | None = None):
        self._learned_path = learned_path
        self._base = base_legacy

    def load_game_profiles(self) -> dict[str, Any]:
        if self._base is not None and hasattr(self._base, "load_game_profiles"):
            try:
                return self._base.load_game_profiles() or {}
            except Exception:  # noqa: BLE001
                return {}
        return {}

    def load_learned_term_payload(self, **_kwargs: Any) -> dict[str, Any]:
        if not self._learned_path.is_file():
            return {"schema_version": 2, "games": {}}
        try:
            data = json.loads(self._learned_path.read_text(encoding="utf-8-sig"))
            return data if isinstance(data, dict) else {"schema_version": 2, "games": {}}
        except (OSError, ValueError, TypeError):
            return {"schema_version": 2, "games": {}}

    def runtime_game_identity(self, value: Any) -> str:
        if self._base is not None and hasattr(self._base, "runtime_game_identity"):
            return str(self._base.runtime_game_identity(value))
        return str(value or "").strip().casefold()

    def resolve_glossary_identity(self, value: Any) -> str:
        if self._base is not None and hasattr(self._base, "resolve_glossary_identity"):
            return str(self._base.resolve_glossary_identity(value) or value)
        return str(value or "").strip()

    def _profile_lexicon_paths_for(self, profile: Any) -> list[str]:
        if self._base is not None and hasattr(self._base, "_profile_lexicon_paths_for"):
            try:
                return list(self._base._profile_lexicon_paths_for(profile) or ())
            except Exception:  # noqa: BLE001
                return []
        return []


def _default_glossary_legacy() -> Any:
    """Resolve local glossary reader while staying strictly inside isolated user_data_root when set."""
    from ..runtime_paths import USER_DATA_ENV, user_data_root

    base_legacy = None
    try:
        import subtitle_core as base_legacy  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        base_legacy = None

    isolated_env = os.environ.get(USER_DATA_ENV, "").strip()
    if isolated_env:
        data_root = user_data_root().resolve()
        learned_path = data_root / "learned_game_terms.json"
        base_path_raw = getattr(base_legacy, "LEARNED_TERMS_PATH", "") if base_legacy is not None else ""
        try:
            in_root = bool(base_path_raw) and Path(base_path_raw).resolve().is_relative_to(data_root)
        except OSError:
            in_root = False
        if not in_root:
            return _IsolatedGlossaryReader(learned_path, base_legacy)
    if base_legacy is not None:
        return base_legacy
    return _IsolatedGlossaryReader(user_data_root() / "learned_game_terms.json", None)


def default_glossary_matcher(
    project: Any,
    glossary_ids: Sequence[str],
    *,
    legacy: Any | None = None,
    snapshot: Any | None = None,
) -> dict[str, Any]:
    """Purely local terminology snapshot precheck: counts pending hits with zero LLM usage."""
    ids = [str(g).strip() for g in (glossary_ids or ()) if str(g).strip()]
    cues = list(getattr(project, "cues", ()))
    if not ids or not cues:
        return {"proposals": 0, "matched_cues": 0, "hits": [], "libraries": []}

    from ..glossary.terminology import TermResolver, snapshot_glossaries

    if snapshot is None:
        reader = legacy if legacy is not None else _default_glossary_legacy()
        snapshot = snapshot_glossaries(reader, ids)

    script = None
    try:
        from ..subtitle_rules.chinese_script import glossary_script
        script = glossary_script(project)
    except Exception:  # noqa: BLE001
        script = None

    resolver = TermResolver(snapshot, script=script)
    hits: list[dict[str, Any]] = []
    matched_cues = 0
    for cue in cues:
        text = str(getattr(cue, "text", "") or "")
        if not text:
            continue
        resolution = resolver.resolve(text)
        if resolution.hits:
            matched_cues += 1
            for hit in resolution.hits:
                hits.append({
                    "cue_id": str(getattr(cue, "id", "") or ""),
                    "source": hit.source,
                    "target": hit.canonical,
                    "reason": hit.reason,
                })

    return {
        "proposals": len(hits),
        "matched_cues": matched_cues,
        "hits": hits[:50],
        "libraries": [lib.id for lib in snapshot.libraries if lib.found],
    }


def default_style_applier(
    project: Any,
    visual: dict[str, Any],
    *,
    preset_store: Any | None = None,
) -> dict[str, Any]:
    """Apply a saved subtitle style preset to unstyled cues without overwriting manual style edits."""
    if not isinstance(visual, dict):
        return {"found": False, "applied": 0, "skipped_manual": 0, "preset_id": "", "preset_name": ""}

    preset_ref = str(
        visual.get("subtitle_style_preset")
        or visual.get("preset_id")
        or visual.get("preset")
        or ""
    ).strip()
    if not preset_ref:
        return {"found": False, "applied": 0, "skipped_manual": 0, "preset_id": "", "preset_name": ""}

    from ..caption_style.scoped_preset import preset_command
    from ..caption_style.style_presets import StylePresetStore

    pstore = preset_store if preset_store is not None else StylePresetStore()
    patch = pstore.load_patch(preset_ref)
    resolved_id = preset_ref
    if not patch:
        for sid, style_obj in pstore.all().items():
            if str(getattr(style_obj, "name", "") or "").strip() == preset_ref:
                patch = pstore.load_patch(sid)
                resolved_id = sid
                break

    if not patch:
        return {
            "found": False,
            "applied": 0,
            "skipped_manual": 0,
            "preset_id": preset_ref,
            "preset_name": preset_ref,
        }

    preset_name = str(patch.get("name") or resolved_id)
    cues = list(getattr(project, "cues", ()))
    eligible_ids = [str(c.id) for c in cues if not _cue_has_manual_style(c)]
    skipped_manual = len(cues) - len(eligible_ids)
    if not eligible_ids:
        return {
            "found": True,
            "applied": 0,
            "skipped_manual": skipped_manual,
            "preset_id": resolved_id,
            "preset_name": preset_name,
        }

    gen_meta = getattr(project, "generation_metadata", None)
    has_translations = isinstance(gen_meta, dict) and bool(gen_meta.get("translations"))
    layer = "group" if has_translations else "original"
    cmd = preset_command(
        project,
        eligible_ids,
        patch,
        layer=layer,
        apply_geometry=False,
    )
    if cmd is not None:
        cmd.redo()

    return {
        "found": True,
        "applied": len(eligible_ids),
        "skipped_manual": skipped_manual,
        "preset_id": resolved_id,
        "preset_name": preset_name,
    }


def _apply_graduated_rules(project: Any, series: SeriesRecord) -> tuple[int, list[str]]:
    """Only auto-rewrite rules explicitly graduated (clean >= 3 episodes + human opt-in)."""
    graduated_pairs: list[tuple[str, str]] = []
    for rk, rec in series.trust_ledger.items():
        if not rec.graduated or not rk.startswith("alias:"):
            continue
        body = rk[len("alias:"):]
        if "->" in body:
            src, dst = body.split("->", 1)
            src, dst = src.strip(), dst.strip()
            if src and dst and src != dst and len(src) >= 2:
                graduated_pairs.append((src, dst))

    if not graduated_pairs:
        return 0, []

    hits = 0
    applied_rules: list[str] = []
    for src, dst in graduated_pairs:
        rule_hits = 0
        for cue in getattr(project, "cues", ()):
            text = str(getattr(cue, "text", "") or "")
            if src in text:
                cue.text = text.replace(src, dst)
                rule_hits += text.count(src)
        if rule_hits > 0:
            hits += rule_hits
            applied_rules.append(f"{src}→{dst}({rule_hits}处)")
    return hits, applied_rules


def _project_label(project: Any) -> str:
    for val in (
        getattr(project, "name", ""),
        getattr(getattr(project, "media", None), "display_name", ""),
        getattr(getattr(project, "media", None), "path", ""),
    ):
        clean = str(val or "").strip()
        if clean:
            return Path(clean).stem if ("/" in clean or "\\" in clean) else clean
    return "未命名工程"


def run_auto_pipeline(
    project: Any,
    series: SeriesRecord,
    *,
    config: AutoPipelineConfig | None = None,
    store: SeriesStore | None = None,
    glossary_matcher: Callable[[Any, Sequence[str]], dict[str, Any]] | None = None,
    voiceprint_observations: Sequence[VoiceprintObservation] | None = None,
    style_applier: Callable[[Any, dict[str, Any]], dict[str, Any]] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_stage: Callable[[PipelineStageResult], None] | None = None,
) -> AutoPipelineReceipt:
    """Execute the configured 3-switch auto-pipeline on one ``SubtitleProject``."""
    t0 = time.perf_counter()
    cfg = config or AutoPipelineConfig.from_dict(series.pipeline)
    state = getattr(project, "studio_state", None)
    if not isinstance(state, dict):
        state = {}
        setattr(project, "studio_state", state)
    state["series_binding"] = {"series_id": series.id, "series_name": series.name}

    stages: list[PipelineStageResult] = []
    auto_applied = 0
    remaining_review = 0

    def _emit(res: PipelineStageResult) -> None:
        stages.append(res)
        if callable(on_stage):
            on_stage(res)

    def _cancelled() -> bool:
        return bool(callable(cancel_check) and cancel_check())

    # ---- Stage 1: 套常用词库 ----
    if not _cancelled():
        if not cfg.run_glossary:
            _emit(PipelineStageResult("glossary", "套常用词库", "skipped", ""))
        else:
            state["pipeline_glossary_ids"] = list(series.glossary_ids)
            proj_gids = getattr(project, "glossary_ids", None)
            if isinstance(proj_gids, list):
                for gid in series.glossary_ids:
                    if gid and gid not in proj_gids:
                        proj_gids.append(gid)
            grad_hits, grad_labels = _apply_graduated_rules(project, series) if cfg.auto_apply_graduated else (0, [])
            proposal_count = 0
            matcher = glossary_matcher if callable(glossary_matcher) else default_glossary_matcher
            match_info: dict[str, Any] | None = {}
            try:
                match_info = matcher(project, series.glossary_ids) or {}
                proposal_count = max(0, int(match_info.get("proposals", 0) or 0))
            except Exception as exc:  # noqa: BLE001
                _emit(PipelineStageResult("glossary", "套常用词库", "needs_review", f"词库检查未完成：{exc}", review_count=1))
                remaining_review += 1
                match_info = None

            if match_info is not None:
                auto_applied += grad_hits
                remaining_review += proposal_count
                parts = []
                if series.glossary_ids:
                    parts.append(f"挂 {len(series.glossary_ids)} 个词库")
                if grad_hits:
                    parts.append(f"自动改 {grad_hits} 处常用词")
                if proposal_count:
                    parts.append(f"标出 {proposal_count} 处待确认")
                summary = "，".join(parts) or "词库预检完成"
                status = "needs_review" if proposal_count else "done"
                _emit(PipelineStageResult(
                    "glossary", "套常用词库", status, summary,
                    count=grad_hits, review_count=proposal_count,
                    details={
                        "glossary_ids": list(series.glossary_ids),
                        "graduated_applied": grad_labels,
                        "matched_cues": int(match_info.get("matched_cues", 0) or 0),
                    },
                ))

    # ---- Stage 2: 套常用人名 ----
    if not _cancelled():
        if not cfg.run_speakers or not series.cast:
            _emit(PipelineStageResult("speakers", "套常用人名", "skipped", ""))
        else:
            named_count = 0
            review_speakers = 0
            cast_by_id = {m.cast_id: m for m in series.cast}
            speakers_list = [sp for sp in getattr(project, "speakers", ()) if sp.id not in _IGNORED_SPEAKERS]
            sp_by_id = {sp.id: sp for sp in speakers_list}

            if voiceprint_observations and store is not None and store.load_voiceprints(series.id):
                matches = store.match_episode_speakers(series.id, voiceprint_observations)
                pending_vp: list[dict[str, Any]] = []
                for m in matches:
                    sp = sp_by_id.get(m.label)
                    if sp is None or not _is_anonymous_speaker(sp.name, sp.id):
                        continue
                    if m.tier == "automatic" and m.cast_id in cast_by_id:
                        member = cast_by_id[m.cast_id]
                        sp.name = member.name
                        if member.color:
                            sp.color = member.color
                        named_count += 1
                    elif m.tier == "review":
                        review_speakers += 1
                        pending_vp.append({"label": m.label, "guess": m.cast_name, "reason": m.reason})
                if pending_vp:
                    state["pipeline_speaker_review"] = pending_vp
            else:
                cue_counts: dict[str, int] = {}
                for cue in getattr(project, "cues", ()):
                    cue_counts[cue.speaker_id] = cue_counts.get(cue.speaker_id, 0) + 1
                used = {
                    str(sp.name or "").strip().casefold()
                    for sp in speakers_list
                    if not _is_anonymous_speaker(sp.name, sp.id)
                }
                avail_cast = [m for m in series.cast if m.name.casefold() not in used]
                anon_targets = [sp for sp in speakers_list if _is_anonymous_speaker(sp.name, sp.id)]
                anon_targets.sort(key=lambda sp: cue_counts.get(sp.id, 0), reverse=True)
                for sp, member in zip(anon_targets, avail_cast):
                    sp.name = member.name
                    if member.color:
                        sp.color = member.color
                    named_count += 1

            auto_applied += named_count
            remaining_review += review_speakers
            parts = []
            if named_count:
                parts.append(f"套用 {named_count} 位说话人")
            if review_speakers:
                parts.append(f"{review_speakers} 位声音待确认")
            summary = "，".join(parts) or "已有命名全部保留"
            _emit(PipelineStageResult(
                "speakers", "套常用人名", "needs_review" if review_speakers else "done",
                summary, count=named_count, review_count=review_speakers,
            ))

    # ---- Stage 3: 套常用样式 ----
    if not _cancelled():
        if not cfg.run_style_preset or not series.visual:
            _emit(PipelineStageResult("style", "套常用样式", "skipped", ""))
        else:
            preset_name = str(
                series.visual.get("subtitle_style_preset")
                or series.visual.get("preset_id")
                or series.visual.get("preset")
                or "常用样式"
            )
            applier = style_applier if callable(style_applier) else default_style_applier
            try:
                style_res = applier(project, copy.deepcopy(series.visual)) or {}
                found = style_res.get("found", True)
                applied_cues = int(style_res.get("applied", 1 if found else 0) or 0)
                skipped_manual = int(style_res.get("skipped_manual", 0) or 0)
                display_name = str(style_res.get("preset_name") or preset_name)
                if found is False:
                    remaining_review += 1
                    _emit(PipelineStageResult(
                        "style", "套常用样式", "needs_review",
                        f"未找到样式预设「{display_name}」",
                        count=0, review_count=1,
                        details={"preset_id": str(style_res.get("preset_id") or preset_name)},
                    ))
                else:
                    state["pipeline_visual_applied"] = copy.deepcopy(series.visual)
                    if applied_cues > 0:
                        auto_applied += 1
                        summary = f"套用「{display_name}」样式"
                        if skipped_manual > 0:
                            summary += f"（保留 {skipped_manual} 句手动样式）"
                    else:
                        summary = "已有手动样式全部保留"
                    _emit(PipelineStageResult(
                        "style", "套常用样式", "done", summary,
                        count=applied_cues,
                        details={
                            "preset_id": str(style_res.get("preset_id") or preset_name),
                            "skipped_manual": skipped_manual,
                        },
                    ))
            except Exception as exc:  # noqa: BLE001
                remaining_review += 1
                _emit(PipelineStageResult("style", "套常用样式", "needs_review", f"样式未自动套用（{exc}）", review_count=1))

    elapsed_ms = int(round((time.perf_counter() - t0) * 1000))
    receipt = AutoPipelineReceipt(
        series_id=series.id,
        series_name=series.name,
        project_name=_project_label(project),
        stages=stages,
        total_cues=len(getattr(project, "cues", ())),
        auto_applied_count=auto_applied,
        remaining_review_count=remaining_review,
        elapsed_ms=elapsed_ms,
    )
    attach_receipt(project, receipt)
    return receipt


def maybe_run_auto_pipeline(
    project: Any,
    *,
    store: SeriesStore | None = None,
    is_new_delivery: bool = False,
    glossary_matcher: Callable[[Any, Sequence[str]], dict[str, Any]] | None = None,
    voiceprint_observations: Sequence[VoiceprintObservation] | None = None,
    style_applier: Callable[[Any, dict[str, Any]], dict[str, Any]] | None = None,
) -> AutoPipelineReceipt | None:
    """Run auto-pipeline once on an unexecuted newly delivered project when its scheme has it enabled."""
    if project is None:
        return None
    if load_receipt(project) is not None:
        return None
    if not getattr(project, "cues", ()):
        return None
    if getattr(project, "edit_history", None):
        return None

    active_store = store or SeriesStore()
    state = getattr(project, "studio_state", None)
    binding = state.get("series_binding") if isinstance(state, dict) else None
    bound_id = str(binding.get("series_id") or "").strip() if isinstance(binding, dict) else ""
    gen_meta = getattr(project, "generation_metadata", None) or {}
    recognized = bool(
        is_new_delivery
        or (isinstance(gen_meta, dict) and gen_meta.get("recognition_result"))
        or getattr(project, "asr_evidence", None)
        or getattr(project, "report_path", "")
    )

    rec = active_store.get(bound_id) if bound_id else None
    if rec is None and recognized:
        last_id = active_store.last_selected_id()
        rec = active_store.get(last_id) if last_id else None
    if rec is None:
        return None
    if not recognized and not bound_id:
        return None

    cfg = AutoPipelineConfig.from_dict(rec.pipeline)
    if not cfg.enabled:
        return None

    return run_auto_pipeline(
        project,
        rec,
        config=cfg,
        store=active_store,
        glossary_matcher=glossary_matcher,
        voiceprint_observations=voiceprint_observations,
        style_applier=style_applier,
    )


def run_batch_auto_pipeline(
    projects: Sequence[Any],
    series: SeriesRecord,
    *,
    config: AutoPipelineConfig | None = None,
    store: SeriesStore | None = None,
    glossary_matcher: Callable[[Any, Sequence[str]], dict[str, Any]] | None = None,
    style_applier: Callable[[Any, dict[str, Any]], dict[str, Any]] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_project_done: Callable[[int, int, AutoPipelineReceipt], None] | None = None,
) -> BatchPipelineSummary:
    """Run the 3-switch auto-pipeline over a batch of videos cleanly with cancel support."""
    summary = BatchPipelineSummary(series_id=series.id, series_name=series.name)
    total = len(projects)
    for idx, proj in enumerate(projects, 1):
        if callable(cancel_check) and cancel_check():
            summary.cancelled = True
            break
        receipt = run_auto_pipeline(
            proj,
            series,
            config=config,
            store=store,
            glossary_matcher=glossary_matcher,
            style_applier=style_applier,
            cancel_check=cancel_check,
        )
        summary.receipts.append(receipt)
        if callable(on_project_done):
            on_project_done(idx, total, receipt)
    return summary


__all__ = [
    "AUTO_PIPELINE_RECEIPT_KEY",
    "AutoPipelineConfig",
    "AutoPipelineReceipt",
    "BatchPipelineSummary",
    "PipelineStageResult",
    "attach_receipt",
    "default_glossary_matcher",
    "default_style_applier",
    "load_receipt",
    "maybe_run_auto_pipeline",
    "run_auto_pipeline",
    "run_batch_auto_pipeline",
]
