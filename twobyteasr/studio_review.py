"""Compatibility facade for the P24 Subtitle QC engine.

Older Studio code and project files speak in terms of review risk. Keep that
small API readable while the source of truth is now the rule-based QC result.
Computed caches live on the project object and are not serialized.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from difflib import SequenceMatcher
from collections import defaultdict
from collections import Counter
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .studio_project import SubtitleProject
from .studio_qc import (
    QCCategory,
    QCResult,
    QCSeverity,
    SubtitleQCEngine,
    normalize_spoken_text,
    terminology_from_project,
)
from .studio_project import studio_data_root
from .design.components import format_model_evidence_coverage


class ReviewReasonCode(str, Enum):
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    MODEL_DISAGREEMENT = "MODEL_DISAGREEMENT"
    TERM_CONFLICT = "TERM_CONFLICT"
    SPEAKER_UNCERTAIN = "SPEAKER_UNCERTAIN"
    TIMING_OVERLAP = "TIMING_OVERLAP"
    TOO_LONG = "TOO_LONG"
    SEGMENTATION_ANOMALY = "SEGMENTATION_ANOMALY"
    PUNCTUATION_ANOMALY = "PUNCTUATION_ANOMALY"
    LOW_COVERAGE = "LOW_COVERAGE"
    MANUAL_RULE = "MANUAL_RULE"


class ReviewSeverity(str, Enum):
    MUST_REVIEW = "MUST_REVIEW"
    SUGGEST_REVIEW = "SUGGEST_REVIEW"
    INFO = "INFO"


@dataclass(frozen=True)
class ReviewItem:
    reason_code: ReviewReasonCode
    severity: ReviewSeverity
    label: str
    description: str
    evidence: tuple[dict[str, Any], ...] = ()
    models: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason_code": self.reason_code.value,
            "severity": self.severity.value,
            "label": self.label,
            "description": self.description,
            "evidence": [dict(item) for item in self.evidence],
            "models": list(self.models),
        }


@dataclass(frozen=True)
class CueReviewRisk:
    cue_id: str
    score: int
    level: str
    reasons: tuple[str, ...]
    severity: ReviewSeverity = ReviewSeverity.INFO
    items: tuple[ReviewItem, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        # Same keys and order as asdict(); asdict first deep-copied every
        # item's evidence only to replace "items" below (0.3 s GUI stall
        # finishing the QC scan of a 156-cue project).
        return {
            "cue_id": self.cue_id,
            "score": self.score,
            "level": self.level,
            "reasons": list(self.reasons),
            "severity": self.severity.value,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True)
class ReviewScopeSnapshot:
    filter_mode: str
    search_query: str
    speaker_filter: str
    review_severity: str
    visible_cue_ids: tuple[str, ...]


@dataclass
class ReviewSession:
    scope: ReviewScopeSnapshot
    resolved_ids: set[str] = field(default_factory=set)

    @property
    def total(self) -> int:
        return len(self.scope.visible_cue_ids)

    @property
    def completed(self) -> int:
        return len(self.resolved_ids.intersection(self.scope.visible_cue_ids))

    def resolve(self, cue_id: str) -> None:
        if str(cue_id) in self.scope.visible_cue_ids:
            self.resolved_ids.add(str(cue_id))

    def next_id(self, current_id: str, *, include_resolved: bool = False) -> str:
        ids = self.scope.visible_cue_ids
        if not ids:
            return ""
        try:
            start = ids.index(str(current_id)) + 1
        except ValueError:
            start = 0
        ordered = ids[start:] + ids[:start]
        if include_resolved:
            return ordered[0] if ordered else ""
        return next((cue_id for cue_id in ordered if cue_id not in self.resolved_ids), "")


class ReviewRiskType(str, Enum):
    """Dimensions of disagreement shown by the Review queue."""

    LEXICAL = "LEXICAL"
    BOUNDARY = "BOUNDARY"
    SPEAKER = "SPEAKER"
    TIMING = "TIMING"


@dataclass(frozen=True)
class ReviewEvidenceAggregate:
    """Content-level evidence for one cue, independent of Qt presentation."""

    candidate_id: str
    cue_id: str
    normalized_text: str
    risk_types: tuple[str, ...] = ()
    lexical_confidence: float = 1.0
    boundary_confidence: float = 1.0
    speaker_confidence: float = 1.0
    timing_confidence: float = 1.0
    models_agree_text: bool = True
    models_agree_boundary: bool = True
    models_agree_speaker: bool = True
    edit_distance: float = 0.0
    phonetic_similarity: float = 1.0
    model_majority: float = 1.0
    acoustic_confidence: float | None = None
    context_consistency: float = 1.0
    timing_delta_ms: int = 0
    boundary_only: bool = False
    speaker_only: bool = False
    timing_only: bool = False
    requires_review: bool = False
    risk_score: int = 0
    reasons: tuple[str, ...] = ()
    hypotheses: tuple[dict[str, Any], ...] = ()
    source_coverage: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["risk_types"] = list(self.risk_types)
        payload["reasons"] = list(self.reasons)
        payload["hypotheses"] = [dict(item) for item in self.hypotheses]
        return payload


def _hypothesis_text(row: Mapping[str, Any]) -> str:
    return str(
        row.get("text")
        or row.get("candidate_text")
        or row.get("transcript")
        or row.get("value")
        or ""
    ).strip()


def _hypothesis_model(row: Mapping[str, Any], fallback: str) -> str:
    from .model_execution import canonical_model_id
    return canonical_model_id(row.get("model") or row.get("source") or row.get("label") or fallback) or fallback


def _as_hypotheses(value: Any) -> list[dict[str, Any]]:
    """Flatten common evidence shapes into compact, comparable hypotheses."""
    if isinstance(value, Mapping):
        nested = value.get("hypotheses")
        if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
            result: list[dict[str, Any]] = []
            for item in nested:
                if isinstance(item, Mapping):
                    result.extend(_as_hypotheses(item))
            return result
        result = []
        for key, item in value.items():
            if not str(key).casefold().endswith("_text") or not str(item or "").strip():
                continue
            row = dict(value)
            row["text"] = str(item).strip()
            row["model"] = str(value.get("model") or key.removesuffix("_text"))
            confidence = value.get(f"{key.removesuffix('_text')}_confidence")
            if confidence is not None:
                row["confidence"] = confidence
            speaker = value.get(f"{key.removesuffix('_text')}_speaker")
            if speaker is not None:
                row["speaker_id"] = speaker
            result.append(row)
        if result:
            return result
        direct_text = _hypothesis_text(value)
        if direct_text:
            return [dict(value)]
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        result: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, Mapping):
                result.extend(_as_hypotheses(item))
        return result
    return []


def review_hypotheses_from_project(project: SubtitleProject, cue) -> tuple[dict[str, Any], ...]:
    """Project independent evidence onto this cue without source unions."""
    from .asr_source_evidence import cue_source_hypotheses
    return cue_source_hypotheses(project, cue)


def _stream_stats(hypotheses: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in hypotheses:
        text = _hypothesis_text(row)
        if text:
            grouped[_hypothesis_model(row, "model")].append(row)
    result: dict[str, dict[str, Any]] = {}
    for model, rows in grouped.items():
        # A repeated receipt or alias spelling is the same observation.
        unique = {}
        for row in rows:
            key = (_hypothesis_text(row), row.get("start_ms"), row.get("end_ms"), row.get("reference"))
            unique.setdefault(key, row)
        rows = list(unique.values())
        ordered = sorted(rows, key=lambda item: (int(item.get("start_ms", 0) or 0), int(item.get("end_ms", 0) or 0)))
        stream = "".join(_hypothesis_text(item) for item in ordered)
        normalized = normalize_spoken_text(stream)
        boundaries = tuple(
            (int(item.get("start_ms", 0) or 0), int(item.get("end_ms", 0) or 0))
            for item in ordered
        )
        speakers = tuple(str(item.get("speaker_id") or item.get("speaker") or "").strip() for item in ordered)
        confidences = []
        for item in ordered:
            try:
                parsed = float(item.get("confidence"))
                if 0 <= parsed <= 1:
                    confidences.append(parsed)
            except (TypeError, ValueError):
                pass
        result[model] = {
            "rows": ordered,
            "text": stream,
            "normalized": normalized,
            "boundaries": boundaries,
            "speakers": speakers,
            "confidence": min(confidences) if confidences else None,
        }
    return result


class ReviewEvidenceAggregator:
    """Deterministic, content-level Review risk engine.

    Boundary differences are retained as evidence but do not become a human
    review item unless they are materially ambiguous. Timing deltas at or below
    ``timing_tolerance_ms`` are merged automatically.
    """

    def __init__(self, *, timing_tolerance_ms: int = 150, material_timing_ms: int = 200):
        self.timing_tolerance_ms = max(0, int(timing_tolerance_ms))
        self.material_timing_ms = max(self.timing_tolerance_ms + 1, int(material_timing_ms))

    def aggregate(self, cue_or_project, hypotheses_or_cue=None) -> ReviewEvidenceAggregate:
        if isinstance(cue_or_project, SubtitleProject):
            project, cue = cue_or_project, hypotheses_or_cue
            hypotheses = review_hypotheses_from_project(project, cue)
        else:
            cue, hypotheses = cue_or_project, _as_hypotheses(hypotheses_or_cue)
        if cue is None:
            raise ValueError("cue is required")
        rows = [dict(item) for item in hypotheses if _hypothesis_text(item)]
        current = {"text": str(getattr(cue, "text", "")), "model": "Current", "speaker_id": getattr(cue, "speaker_id", "")}
        rows_with_current = rows + [current]
        streams = _stream_stats(rows_with_current)
        current_norm = normalize_spoken_text(current["text"])
        # A single ASR segment may span multiple subtitle cues. When its text
        # contains the current cue and its timed extent crosses the cue
        # boundary, treat it as segmentation evidence instead of a lexical
        # disagreement. Genuine alternate text remains a lexical risk.
        contextual_boundary_models: set[str] = set()
        for name, item in streams.items():
            if name == "Current" or not current_norm:
                continue
            normalized = str(item.get("normalized") or "")
            rows_for_model = item.get("rows") or ()
            spans_boundary = any(
                int(row.get("original_start_ms" if row.get('context_only') else "start_ms", 0) or 0) < int(getattr(cue, "start_ms", 0))
                or int(row.get("original_end_ms" if row.get('context_only') else "end_ms", 0) or 0) > int(getattr(cue, "end_ms", 0))
                for row in rows_for_model
                if isinstance(row, Mapping)
            )
            if normalized != current_norm and current_norm in normalized and spans_boundary:
                contextual_boundary_models.add(name)
        from .asr_source_evidence import coverage_summary
        source_coverage = coverage_summary(rows)
        for name, item in streams.items():
            partial_rows = item.get('rows') or ()
            if name == 'Current' or not partial_rows:
                continue
            if source_coverage.get('current_text_supported') is True and all(
                   row.get('cue_text_start') is not None and row.get('comparison_text') and normalize_spoken_text(row['text']) ==
                   normalize_spoken_text(row['comparison_text']) for row in partial_rows):
                contextual_boundary_models.add(name)
        model_norms = [
            current_norm if name in contextual_boundary_models else item["normalized"]
            for name, item in streams.items()
            if name != "Current"
        ]
        # Compare model evidence with the text currently in the project as
        # well. A single model disagreeing with the current cue is still a
        # lexical risk; comparing only model-to-model would incorrectly mark
        # that common case as "agreed".
        comparison_norms = [current_norm, *model_norms] if model_norms else [current_norm]
        unique_norms = set(comparison_norms)
        models_agree_text = len(unique_norms) <= 1
        majority_count = max(
            (model_norms.count(item) for item in set(model_norms)),
            default=1,
        )
        # Current is the text being checked, never an independent ASR vote.
        model_majority = majority_count / max(1, len(model_norms))
        pair_ratios = [
            SequenceMatcher(None, left, right, autojunk=False).ratio()
            for index, left in enumerate(comparison_norms)
            for right in comparison_norms[index + 1 :]
        ]
        lexical_similarity = min(pair_ratios, default=1.0)
        edit_distance = round(1.0 - lexical_similarity, 4)
        speakers = {
            speaker for item in streams.values() for speaker in item["speakers"] if speaker
        }
        models_agree_speaker = len(speakers) <= 1
        all_boundaries = {item["boundaries"] for name, item in streams.items() if name != "Current"}
        models_agree_boundary = len(all_boundaries) <= 1
        timing_ranges = [
            (
                min((point[0] for point in item["boundaries"]), default=0),
                max((point[1] for point in item["boundaries"]), default=0),
            )
            for name, item in streams.items() if name != "Current" and item["boundaries"]
        ]
        timing_delta = 0
        if timing_ranges:
            starts = [point[0] for point in timing_ranges]
            ends = [point[1] for point in timing_ranges]
            timing_delta = max(max(starts) - min(starts), max(ends) - min(ends))
        risk_types: list[str] = []
        reasons: list[str] = []
        boundary_only = bool(not models_agree_boundary and models_agree_text)
        speaker_only = bool(not models_agree_speaker and models_agree_text)
        timing_only = bool(timing_delta > self.timing_tolerance_ms and models_agree_text)
        if not models_agree_text:
            risk_types.append(ReviewRiskType.LEXICAL.value)
            reasons.append('当前全文与局部投影不一致／缺少完整字词范围证据'
                if source_coverage.get('current_text_supported') is False and not source_coverage['conflict']
                else "文本冲突")
        if boundary_only:
            risk_types.append(ReviewRiskType.BOUNDARY.value)
            reasons.append("断句不确定")
        if speaker_only:
            risk_types.append(ReviewRiskType.SPEAKER.value)
            reasons.append("说话人不确定")
        if timing_only:
            risk_types.append(ReviewRiskType.TIMING.value)
            reasons.append("时间边界不确定")
        boundary_flags = {
            str(row.get(flag)).casefold()
            for item in streams.values() if item["rows"]
            for row in item["rows"]
            for flag in ("boundary_risk", "word_internal", "semantic_break", "pause_conflict")
            if row.get(flag) is not None
        }
        short_or_long_segment = any(
            int(row.get("end_ms", 0) or 0) - int(row.get("start_ms", 0) or 0) in range(1, 241)
            or int(row.get("end_ms", 0) or 0) - int(row.get("start_ms", 0) or 0) > 7000
            for item in streams.values() if item["rows"]
            for row in item["rows"]
        )
        material_boundary = boundary_only and (
            timing_delta > self.material_timing_ms
            or bool(boundary_flags.intersection({"1", "true", "yes", "high"}))
            or short_or_long_segment and len({len(item["boundaries"]) for name, item in streams.items() if name != "Current"}) > 1
        )
        lexical_risk = not models_agree_text
        speaker_risk = speaker_only and len(speakers) > 1
        timing_risk = timing_only and timing_delta > self.material_timing_ms
        requires_review = bool(lexical_risk or speaker_risk or material_boundary or timing_risk)
        if source_coverage['missing'] or source_coverage['partial'] or source_coverage['coverage_unknown']:
            requires_review = True
            reasons.append('来源信息缺失／待恢复' if source_coverage['missing'] else
                '原始来源已保留，字级覆盖待核验' if source_coverage['coverage_unknown'] else '部分范围缺少独立来源覆盖')
        score = 0
        if lexical_risk:
            score += 65
        if speaker_risk:
            score += 25
        if material_boundary:
            score += 18
        if timing_risk:
            score += 18
        confidence_values = [item["confidence"] for item in streams.values() if item["confidence"] is not None]
        acoustic = min(confidence_values) if confidence_values else None
        lexical_confidence = 1.0 if models_agree_text else round(max(0.0, min(1.0, lexical_similarity * model_majority)), 3)
        timing_confidence = 1.0 if timing_delta <= self.timing_tolerance_ms else round(max(0.0, 1.0 - timing_delta / max(1, self.material_timing_ms * 2)), 3)
        speaker_confidence = 1.0 if models_agree_speaker else round(1.0 / max(2, len(speakers)), 3)
        boundary_confidence = 1.0 if models_agree_boundary else (0.55 if not material_boundary else 0.3)
        return ReviewEvidenceAggregate(
            candidate_id=f"{getattr(cue, 'id', 'cue')}:review",
            cue_id=str(getattr(cue, "id", "")),
            normalized_text=current_norm,
            risk_types=tuple(dict.fromkeys(risk_types)),
            lexical_confidence=lexical_confidence,
            boundary_confidence=boundary_confidence,
            speaker_confidence=speaker_confidence,
            timing_confidence=timing_confidence,
            models_agree_text=models_agree_text,
            models_agree_boundary=models_agree_boundary,
            models_agree_speaker=models_agree_speaker,
            edit_distance=edit_distance,
            phonetic_similarity=lexical_similarity,
            model_majority=round(model_majority, 3),
            acoustic_confidence=acoustic,
            timing_delta_ms=int(timing_delta),
            boundary_only=boundary_only,
            speaker_only=speaker_only,
            timing_only=timing_only,
            requires_review=requires_review,
            risk_score=min(100, score),
            reasons=tuple(dict.fromkeys(reasons)),
            hypotheses=tuple(rows),
            source_coverage=source_coverage,
        )


def aggregate_review_evidence(cue_or_project, hypotheses_or_cue=None) -> ReviewEvidenceAggregate:
    return ReviewEvidenceAggregator().aggregate(cue_or_project, hypotheses_or_cue)


class ReviewTriageDecision(str, Enum):
    KEEP_AUTO = "KEEP_AUTO"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    LIKELY_BOUNDARY_ONLY = "LIKELY_BOUNDARY_ONLY"
    LIKELY_SPEAKER_ONLY = "LIKELY_SPEAKER_ONLY"


@dataclass(frozen=True)
class ReviewTriageResult:
    candidate_id: str
    decision: str
    confidence: float
    reason: str
    provider_succeeded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _deterministic_triage(candidate: ReviewEvidenceAggregate) -> ReviewTriageResult:
    if candidate.models_agree_text and candidate.boundary_only and not candidate.requires_review:
        return ReviewTriageResult(candidate.candidate_id, ReviewTriageDecision.LIKELY_BOUNDARY_ONLY.value, candidate.boundary_confidence, "文本一致，仅断句差异")
    if candidate.models_agree_text and candidate.speaker_only:
        return ReviewTriageResult(candidate.candidate_id, ReviewTriageDecision.LIKELY_SPEAKER_ONLY.value, candidate.speaker_confidence, "文本一致，仅说话人候选不同")
    if candidate.requires_review:
        return ReviewTriageResult(candidate.candidate_id, ReviewTriageDecision.NEEDS_HUMAN.value, max(0.0, 1.0 - candidate.risk_score / 120), " / ".join(candidate.reasons) or "证据置信度不足")
    return ReviewTriageResult(candidate.candidate_id, ReviewTriageDecision.KEEP_AUTO.value, max(candidate.lexical_confidence, 0.75), "确定性证据一致")


class ReviewTriageAI:
    """Optional batched cloud triage; deterministic evidence always wins."""

    SCHEMA = {
        "type": "object",
        "properties": {"results": {"type": "array", "items": {"type": "object"}}},
        "required": ["results"],
    }

    def __init__(self, provider=None, *, settings: Mapping[str, Any] | None = None):
        self.provider = provider
        self.settings = dict(settings or {})
        self.provider_succeeded = False
        self.last_error = ""

    def triage(self, candidates: Iterable[ReviewEvidenceAggregate | Mapping[str, Any]], *, context: Mapping[str, Any] | None = None) -> tuple[ReviewTriageResult, ...]:
        normalized: list[ReviewEvidenceAggregate] = []
        for item in candidates:
            if isinstance(item, ReviewEvidenceAggregate):
                normalized.append(item)
                continue
            payload = dict(item) if isinstance(item, Mapping) else {}
            known = {key: payload[key] for key in ReviewEvidenceAggregate.__dataclass_fields__ if key in payload}
            known.setdefault("candidate_id", str(payload.get("id") or "candidate"))
            known.setdefault("cue_id", str(payload.get("cue_id") or ""))
            known.setdefault("normalized_text", str(payload.get("normalized_text") or payload.get("text") or ""))
            for key in ("risk_types", "reasons", "hypotheses"):
                if key in known and isinstance(known[key], list):
                    known[key] = tuple(known[key])
            normalized.append(ReviewEvidenceAggregate(**known))
        deterministic = {item.candidate_id: _deterministic_triage(item) for item in normalized}
        if not normalized:
            return ()
        provider = self.provider
        if provider is None:
            try:
                from .ai_providers import provider_for_stage
                provider = provider_for_stage(self.settings, "polish")
            except Exception as exc:
                self.last_error = str(exc)
        if provider is None:
            return tuple(deterministic.values())
        request = {
            "candidates": [item.to_dict() for item in normalized],
            "context": dict(context or {}),
            "decisions": [item.value for item in ReviewTriageDecision],
            "instruction": "只判断是否值得人工查看，不改写字幕文本。",
        }
        try:
            payload = provider.structured_complete(
                [{"role": "system", "content": "You are a subtitle review triage assistant."}, {"role": "user", "content": __import__("json").dumps(request, ensure_ascii=False)}],
                self.SCHEMA,
                max_tokens=3000,
                temperature=0.0,
                stage="studio_review_triage",
            )
            rows = payload.get("results", []) if isinstance(payload, Mapping) else []
            by_id = {str(row.get("candidate_id")): row for row in rows if isinstance(row, Mapping)}
            output: list[ReviewTriageResult] = []
            for item in normalized:
                base = deterministic[item.candidate_id]
                row = by_id.get(item.candidate_id)
                if not row:
                    output.append(base)
                    continue
                decision = str(row.get("decision") or base.decision)
                # A deterministic lexical disagreement can never be hidden by
                # a model's optimistic triage response.
                if ReviewRiskType.LEXICAL.value in item.risk_types:
                    decision = ReviewTriageDecision.NEEDS_HUMAN.value
                elif item.boundary_only and not item.requires_review:
                    decision = ReviewTriageDecision.LIKELY_BOUNDARY_ONLY.value
                elif item.speaker_only:
                    decision = ReviewTriageDecision.LIKELY_SPEAKER_ONLY.value
                try:
                    confidence = max(0.0, min(1.0, float(row.get("confidence", base.confidence))))
                except (TypeError, ValueError):
                    confidence = base.confidence
                output.append(ReviewTriageResult(item.candidate_id, decision, confidence, str(row.get("reason") or base.reason), True))
            self.provider_succeeded = True
            return tuple(output)
        except Exception as exc:
            self.last_error = str(exc)
            return tuple(
                ReviewTriageResult(item.candidate_id, base.decision, base.confidence, "AI预审未运行；" + base.reason, False)
                for item, base in ((item, deterministic[item.candidate_id]) for item in normalized)
            )

    def triage_batch(self, candidates, *, context=None):
        return self.triage(candidates, context=context)


def triage_review_candidates(candidates, *, provider=None, settings=None, context=None):
    return ReviewTriageAI(provider, settings=settings).triage(candidates, context=context)


_LEGACY_LABELS = {
    "model_disagreement": "多模型文本不一致",
    "low_confidence": "低置信度",
    "overlap": "时间轴重叠",
    "micro_overlap": "极小重叠",
    "short_duration": "时长过短",
    "long_duration": "时长过长",
    "high_cps": "阅读速度过快",
    "line_too_long": "单行过长",
    "short_gap": "字幕间隔过短",
    "micro_gap": "字幕间隔过短",
    "empty_cue": "空字幕",
}


def _legacy_reason(issue) -> str:
    label = _LEGACY_LABELS.get(issue.issue_type, issue.label)
    if issue.issue_type == "low_confidence" and issue.evidence:
        confidence = issue.evidence[0].confidence
        if confidence is not None:
            return f"{label} {confidence:.0%}"
    if issue.issue_type == "high_cps" and issue.evidence:
        return f"{label} {issue.evidence[0].text} 字/秒"
    return label


_REASON_BY_ISSUE = {
    "low_confidence": ReviewReasonCode.LOW_CONFIDENCE,
    "model_disagreement": ReviewReasonCode.MODEL_DISAGREEMENT,
    "suspected_word": ReviewReasonCode.MODEL_DISAGREEMENT,
    "terminology_mismatch": ReviewReasonCode.TERM_CONFLICT,
    "terminology_model_conflict": ReviewReasonCode.TERM_CONFLICT,
    "speaker_switch": ReviewReasonCode.SPEAKER_UNCERTAIN,
    "speaker_continuity": ReviewReasonCode.SPEAKER_UNCERTAIN,
    "overlap": ReviewReasonCode.TIMING_OVERLAP,
    "micro_overlap": ReviewReasonCode.TIMING_OVERLAP,
    "long_duration": ReviewReasonCode.TOO_LONG,
    "high_cps": ReviewReasonCode.TOO_LONG,
    "line_too_long": ReviewReasonCode.TOO_LONG,
    "unbalanced_lines": ReviewReasonCode.TOO_LONG,
    "short_duration": ReviewReasonCode.SEGMENTATION_ANOMALY,
    "segmentation_difference": ReviewReasonCode.SEGMENTATION_ANOMALY,
    "merge_overlap_suggestion": ReviewReasonCode.SEGMENTATION_ANOMALY,
    "merge_fragment": ReviewReasonCode.SEGMENTATION_ANOMALY,
    "consecutive_duplicate": ReviewReasonCode.SEGMENTATION_ANOMALY,
    "duplicate_punctuation": ReviewReasonCode.PUNCTUATION_ANOMALY,
    "abnormal_punctuation": ReviewReasonCode.PUNCTUATION_ANOMALY,
}


def _reason_code(issue) -> ReviewReasonCode:
    mapped = _REASON_BY_ISSUE.get(issue.issue_type)
    if mapped is not None:
        return mapped
    if issue.category == QCCategory.SPEAKER:
        return ReviewReasonCode.SPEAKER_UNCERTAIN
    if issue.category == QCCategory.TERMINOLOGY:
        return ReviewReasonCode.TERM_CONFLICT
    if issue.category == QCCategory.TIMELINE:
        return ReviewReasonCode.SEGMENTATION_ANOMALY
    if issue.category == QCCategory.READABILITY:
        return ReviewReasonCode.TOO_LONG
    if issue.category == QCCategory.TEXT:
        return ReviewReasonCode.PUNCTUATION_ANOMALY
    return ReviewReasonCode.MANUAL_RULE


def _review_severity(value: QCSeverity) -> ReviewSeverity:
    return {
        QCSeverity.CRITICAL: ReviewSeverity.MUST_REVIEW,
        QCSeverity.WARNING: ReviewSeverity.SUGGEST_REVIEW,
        QCSeverity.INFO: ReviewSeverity.INFO,
    }[value]


def _review_items(issues) -> tuple[ReviewItem, ...]:
    """Coalesce duplicate product reasons while retaining their real evidence."""
    ranks = {
        ReviewSeverity.MUST_REVIEW: 3,
        ReviewSeverity.SUGGEST_REVIEW: 2,
        ReviewSeverity.INFO: 1,
    }
    grouped: dict[ReviewReasonCode, dict[str, Any]] = {}
    for issue in issues:
        code = _reason_code(issue)
        severity = _review_severity(issue.severity)
        row = grouped.setdefault(code, {
            "severity": severity,
            "labels": [],
            "descriptions": [],
            "evidence": [],
            "models": [],
        })
        if ranks[severity] > ranks[row["severity"]]:
            row["severity"] = severity
        if issue.label not in row["labels"]:
            row["labels"].append(issue.label)
        if issue.description not in row["descriptions"]:
            row["descriptions"].append(issue.description)
        for evidence in issue.evidence:
            payload = evidence.to_dict()
            if payload not in row["evidence"]:
                row["evidence"].append(payload)
            label = str(evidence.label or "").strip()
            if label and label not in {"Current", "CPS", "识别置信度", "词库"} and label not in row["models"]:
                row["models"].append(label)
    ordered = sorted(grouped.items(), key=lambda item: (-ranks[item[1]["severity"]], item[0].value))
    return tuple(
        ReviewItem(
            reason_code=code,
            severity=row["severity"],
            label=" / ".join(row["labels"]),
            description=" ".join(row["descriptions"]),
            evidence=tuple(row["evidence"]),
            models=tuple(row["models"]),
        )
        for code, row in ordered
    )


def review_risks_from_qc(result: QCResult) -> dict[str, CueReviewRisk]:
    weights = {QCSeverity.CRITICAL: 60, QCSeverity.WARNING: 25, QCSeverity.INFO: 8}
    risks: dict[str, CueReviewRisk] = {}
    for cue_id, issues in result.issues_by_cue.items():
        items = _review_items(issues)
        actionable = tuple(
            issue for issue in issues
            if issue.severity != QCSeverity.INFO and not issue.safe_fixable
        )
        score = sum(weights[issue.severity] for issue in actionable)
        level = "high" if any(issue.severity == QCSeverity.CRITICAL for issue in actionable) else (
            "suggested" if actionable else "confident"
        )
        severity = next(
            (item.severity for item in items if item.severity is not ReviewSeverity.INFO),
            ReviewSeverity.INFO,
        )
        risks[cue_id] = CueReviewRisk(
            cue_id,
            score,
            level,
            tuple(dict.fromkeys(_legacy_reason(issue) for issue in actionable)),
            severity,
            items,
        )
    return risks


def analyze_review_risks(project: SubtitleProject) -> dict[str, CueReviewRisk]:
    result = SubtitleQCEngine().analyze(project, terminology=terminology_from_project(project))
    return review_risks_from_qc(result)


def store_review_risks(project: SubtitleProject) -> dict[str, CueReviewRisk]:
    result = SubtitleQCEngine().analyze(project, terminology=terminology_from_project(project))
    risks = review_risks_from_qc(result)
    setattr(project, "_qc_result", result)
    setattr(project, "_review_risks_cache", {cue_id: risk.to_dict() for cue_id, risk in risks.items()})
    return risks


def cached_review_risks(project: SubtitleProject | None) -> dict[str, Any]:
    if project is None:
        return {}
    cache = getattr(project, "_review_risks_cache", None)
    # Historical serialized QC metrics predate the current coverage contract.
    # Keep their stored dictionary intact, but only use freshly computed
    # runtime statistics (normal Studio startup runs its chunked QC scan).
    result = dict(cache) if isinstance(cache, dict) else {}
    from .studio_edit_sequence import source_cue_id_of
    receipts = project.studio_state.get('caption_timeline', {}).get('instances', {})
    current = {c.id for c in project.cues}
    for cue_id, receipt in receipts.items():
        if cue_id in current and receipt.get('needs_review'):
            key = source_cue_id_of(cue_id)
            row = dict(result.get(key, {}))
            row.update(level='high', score=max(100, int(row.get('score', 0))))
            row['reasons'] = list(dict.fromkeys([*row.get('reasons', ()), '波纹边界缺少完整字词映射，请检查保留文字']))
            result[key] = row
    return result


def cached_qc_result(project: SubtitleProject | None) -> QCResult:
    result = getattr(project, "_qc_result", None) if project is not None else None
    return result if isinstance(result, QCResult) else QCResult({})


def _audit_bucket(aggregate: ReviewEvidenceAggregate | None, risk: CueReviewRisk | None) -> str:
    """Map evidence to the three user-facing review levels."""
    # The existing Studio Review queue already applies the calibrated QC
    # thresholds (notably low-confidence and timing rules). Preserve those
    # levels when exporting a production audit; evidence aggregates explain
    # the reason but must not silently turn 296 suggested cues into 233 hard
    # lexical failures.
    if risk is not None:
        if risk.level == "high":
            return "NEEDS_REVIEW"
        if risk.level == "suggested":
            return "SUGGEST_CONFIRM"
        if risk.level == "confident" and aggregate is None:
            return "AUTO_ACCEPT"
    if aggregate is not None:
        if aggregate.models_agree_text and aggregate.timing_delta_ms <= 150 and (
            not aggregate.speaker_only or aggregate.speaker_confidence >= 0.5
        ) and not aggregate.requires_review:
            return "AUTO_ACCEPT"
        if aggregate.requires_review and (
            ReviewRiskType.LEXICAL.value in aggregate.risk_types
            or aggregate.risk_score >= 60
        ):
            return "NEEDS_REVIEW"
        return "SUGGEST_CONFIRM"
    if risk is None or risk.level == "confident":
        return "AUTO_ACCEPT"
    return "NEEDS_REVIEW" if risk.level == "high" or risk.score >= 60 else "SUGGEST_CONFIRM"


def review_evidence_coverage(project: SubtitleProject) -> dict[str, Any]:
    """Count guaranteed whole-cue overlap separately from partial receipts."""
    totals = {
        "TOTAL": len(project.cues),
        "MOSS_COUNT": 0,
        "FIRERED_COUNT": 0,
        "QWEN_COUNT": 0,
        "3_SOURCE_OVERLAP": 0,
        "2_SOURCE_OVERLAP": 0,
        "1_SOURCE_ONLY": 0,
        "0_SOURCE": 0,
        "PARTIAL_SOURCE_COVERAGE": 0,
        "UNKNOWN_SOURCE_COVERAGE": 0,
    }
    aggregator = ReviewEvidenceAggregator()
    for cue in project.cues:
        coverage = format_model_evidence_coverage(aggregator.aggregate(project, cue).hypotheses)
        moss = coverage["moss"] == "✓"
        firered = coverage["firered"] == "✓"
        qwen = coverage["qwen"] == "✓"
        totals["MOSS_COUNT"] += int(moss)
        totals["FIRERED_COUNT"] += int(firered)
        totals["QWEN_COUNT"] += int(qwen)
        totals["PARTIAL_SOURCE_COVERAGE"] += int(coverage["partial"])
        totals["UNKNOWN_SOURCE_COVERAGE"] += int(coverage["coverage_unknown"])
        if coverage["coverage_unknown"]:
            continue
        known = coverage["minimum_count"]
        if known >= 3:
            totals["3_SOURCE_OVERLAP"] += 1
        elif known == 2:
            totals["2_SOURCE_OVERLAP"] += 1
        elif known == 1:
            totals["1_SOURCE_ONLY"] += 1
        else:
            totals["0_SOURCE"] += 1
    return totals


def export_review_risk_audit(
    project: SubtitleProject,
    output_path: str | Path | None = None,
    *,
    provider=None,
    hypotheses_by_cue: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
    batch_size: int = 40,
) -> dict[str, Any]:
    """Export explainable per-cue Review evidence for calibration.

    Cloud triage is only sent the middle-risk band in bounded batches.  The
    deterministic lexical gate remains authoritative for high-risk cues.
    """
    project.validate()
    qc_result = cached_qc_result(project)
    if not qc_result.issues_by_cue:
        qc_result = SubtitleQCEngine().analyze(project, terminology=terminology_from_project(project))
    risks = review_risks_from_qc(qc_result)
    aggregates: dict[str, ReviewEvidenceAggregate] = {}
    for cue in project.cues:
        evidence = None
        if hypotheses_by_cue is not None:
            evidence = hypotheses_by_cue.get(cue.id)
        if evidence is None:
            evidence = review_hypotheses_from_project(project, cue)
        if evidence:
            aggregates[cue.id] = ReviewEvidenceAggregator().aggregate(cue, evidence)

    middle = [item for item in aggregates.values() if 1 <= item.risk_score < 60]
    triage_results: dict[str, ReviewTriageResult] = {}
    triage_errors: list[str] = []
    if middle and provider is not None:
        triage_engine = ReviewTriageAI(provider)
        for start in range(0, len(middle), max(1, int(batch_size))):
            batch = middle[start:start + max(1, int(batch_size))]
            triage = triage_engine.triage(batch, context=context)
            triage_results.update({item.candidate_id: item for item in triage})
            if triage_engine.last_error:
                # Keep diagnostics useful without allowing a provider exception
                # (which may contain request details) to bloat the audit file.
                message = " ".join(str(triage_engine.last_error).split())[:240]
                if message and message not in triage_errors:
                    triage_errors.append(message)
    distribution = Counter()
    category_counts = Counter()
    reason_counts = Counter()
    duplicate_text_cards = 0
    score_histograms: dict[str, Counter] = defaultdict(Counter)
    bucket_counts = Counter()
    records: list[dict[str, Any]] = []
    for cue in project.cues:
        aggregate = aggregates.get(cue.id)
        risk = risks.get(cue.id)
        if aggregate is not None:
            risk_types = list(aggregate.risk_types)
            scores = {
                "LEXICAL": round((1.0 - aggregate.lexical_confidence) * 100),
                "BOUNDARY": round((1.0 - aggregate.boundary_confidence) * 100),
                "SPEAKER": round((1.0 - aggregate.speaker_confidence) * 100),
                "TIMING": round((1.0 - aggregate.timing_confidence) * 100),
            }
            evidence_rows = [dict(item) for item in aggregate.hypotheses]
            reason = " / ".join(aggregate.reasons) or "证据一致"
            triage = triage_results.get(aggregate.candidate_id)
        else:
            risk_types = []
            scores = {"LEXICAL": 0, "BOUNDARY": 0, "SPEAKER": 0, "TIMING": 0}
            evidence_rows = []
            reason = " / ".join(risk.reasons) if risk else "无风险证据"
            triage = None
        risk_type_by_code = {
            "MODEL_DISAGREEMENT": ReviewRiskType.LEXICAL.value,
            "SEGMENTATION_ANOMALY": ReviewRiskType.BOUNDARY.value,
            "SPEAKER_UNCERTAIN": ReviewRiskType.SPEAKER.value,
            "TIMING_OVERLAP": ReviewRiskType.TIMING.value,
            "TOO_LONG": ReviewRiskType.TIMING.value,
        }
        if risk is not None:
            for item in risk.items:
                if item.severity is ReviewSeverity.INFO:
                    continue
                code = getattr(item.reason_code, "value", str(item.reason_code))
                mapped = risk_type_by_code.get(code)
                if mapped and mapped not in risk_types:
                    risk_types.append(mapped)
                    scores[mapped] = max(
                        int(scores.get(mapped, 0)),
                        100 if item.severity is ReviewSeverity.MUST_REVIEW else 50,
                    )
        reason_values = []
        if risk is not None:
            reason_values.extend(risk.reasons)
        if aggregate is not None:
            reason_values.extend(aggregate.reasons)
        reason = " / ".join(dict.fromkeys(str(item) for item in reason_values if str(item))) or "证据一致"
        bucket = _audit_bucket(aggregate, risk)
        if triage is not None and bucket != "NEEDS_REVIEW":
            if triage.decision == ReviewTriageDecision.NEEDS_HUMAN.value:
                bucket = "NEEDS_REVIEW"
            elif triage.decision == ReviewTriageDecision.KEEP_AUTO.value:
                bucket = "AUTO_ACCEPT"
            else:
                bucket = "SUGGEST_CONFIRM"
        bucket_counts[bucket] += 1
        category_set = set(risk_types)
        if risk is not None:
            for item in risk.items:
                if item.severity is ReviewSeverity.INFO:
                    continue
                code = getattr(item.reason_code, "value", str(item.reason_code))
                category_set.add(risk_type_by_code.get(code, "MIXED"))
        dimensions = category_set.intersection({"LEXICAL", "BOUNDARY", "SPEAKER", "TIMING"})
        if "MIXED" in category_set or len(dimensions) > 1:
            category_counts["MIXED"] += 1
        for category in dimensions:
            category_counts[category] += 1
        try:
            from .studio_qc import review_candidates
            candidates = review_candidates(project, cue)
            normalized = [normalize_spoken_text(item.text) for item in candidates]
            duplicate_text_cards += max(0, len(normalized) - len(set(normalized)))
        except Exception:
            pass
        reason_values = []
        if aggregate is not None:
            reason_values.extend(aggregate.reasons)
        if risk is not None:
            reason_values.extend(risk.reasons)
        for reason_item in dict.fromkeys(str(item) for item in reason_values if str(item)):
            reason_counts[str(reason_item)] += 1
        for risk_type in risk_types:
            distribution[risk_type] += 1
            score_histograms[risk_type][str(min(100, max(0, int(scores.get(risk_type, 0))) // 10 * 10))] += 1
        records.append({
            "cue_id": cue.id,
            "risk_types": risk_types,
            "risk_scores": scores,
            "model_evidence": evidence_rows,
            "ai_triage": triage.to_dict() if triage is not None else None,
            "final_bucket": bucket,
            "reason": reason,
        })
    payload = {
        "schema_version": 1,
        "total": len(project.cues),
        "distribution": {key: int(distribution.get(key, 0)) for key in (
            "LEXICAL", "BOUNDARY", "SPEAKER", "TIMING",
        )},
        "risk_category_counts": {key: int(category_counts.get(key, 0)) for key in (
            "LEXICAL", "BOUNDARY", "SPEAKER", "TIMING", "MIXED",
        )},
        "duplicate_text_review_cards": int(duplicate_text_cards),
        "score_histograms": {key: dict(value) for key, value in score_histograms.items()},
        "final_buckets": {key: int(bucket_counts.get(key, 0)) for key in (
            "AUTO_ACCEPT", "SUGGEST_CONFIRM", "NEEDS_REVIEW",
        )},
        "triage_batch_size": max(1, int(batch_size)),
        "triage_candidate_count": len(middle),
        "triage_errors": triage_errors,
        "reason_counts": {
            str(reason): {
                "count": int(count),
                "percentage": round(float(count) * 100.0 / max(1, len(project.cues)), 2),
            }
            for reason, count in reason_counts.most_common()
        },
        "top_reasons": [
            {"reason": str(reason), "count": int(count),
             "percentage": round(float(count) * 100.0 / max(1, len(project.cues)), 2)}
            for reason, count in reason_counts.most_common(5)
        ],
        "cues": records,
    }
    target = Path(output_path) if output_path is not None else Path(studio_data_root()) / "review_risk_audit.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def generate_review_risk_audit(*args, **kwargs) -> dict[str, Any]:
    """Compatibility alias used by verification scripts."""
    return export_review_risk_audit(*args, **kwargs)


def audit_current_project_review(
    project: SubtitleProject | None = None,
    *,
    project_path: str | Path | None = None,
    provider=None,
    context: Mapping[str, Any] | None = None,
    batch_size: int = 40,
) -> dict[str, Any]:
    """Audit the current Studio project and persist the production artifact.

    The explicit project argument is the open Studio session boundary. A path
    is accepted for the developer/runtime action so the same code can audit a
    saved project without inventing a second review implementation.
    """
    if project is None:
        if project_path is None:
            raise ValueError("current project or project_path is required")
        from .studio_project import load_project
        project = load_project(project_path)
    output_path = studio_data_root().parent / "logs" / "review_risk_audit.json"
    payload = export_review_risk_audit(
        project,
        output_path,
        provider=provider,
        context={**dict(context or {}), "project_path": str(project_path or "")},
        batch_size=batch_size,
    )
    payload["project_path"] = str(project_path or "")
    payload["project_id"] = str(project.project_id)
    # Keep the convenience fields in sync with the on-disk production file.
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
