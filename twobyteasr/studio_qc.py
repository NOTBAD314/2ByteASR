"""Deterministic Subtitle Studio quality checks and conservative safe fixes.

The module deliberately contains no Qt code.  Rules produce small, user-facing
``QCIssue`` objects; Studio only renders those objects and invokes a prepared
``SafeFixPlan`` through the existing undo command path.
"""

from __future__ import annotations

import copy
import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from enum import Enum
from functools import lru_cache
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .studio_project import StudioCue, SubtitleProject


class QCSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class QCCategory(str, Enum):
    ASR = "asr"
    TEXT = "text"
    TERMINOLOGY = "terminology"
    TIMELINE = "timeline"
    READABILITY = "readability"
    SPEAKER = "speaker"


@dataclass(frozen=True)
class QCConfig:
    max_cps_warning: float = 15.0
    max_cps_critical: float = 20.0
    max_line_length: int = 28
    min_duration_ms: int = 400
    very_short_duration_ms: int = 240
    max_duration_ms: int = 7_000
    micro_overlap_ms: int = 50
    micro_gap_ms: int = 50
    short_gap_ms: int = 80
    duplicate_gap_ms: int = 250
    fragment_duration_ms: int = 350
    fragment_characters: int = 2
    fragment_merge_gap_ms: int = 60
    fragment_max_combined_characters: int = 18
    disagreement_similarity: float = 0.82
    low_confidence_warning: float = 0.75
    low_confidence_critical: float = 0.50
    speaker_continuity_gap_ms: int = 240


@dataclass(frozen=True)
class QCEvidence:
    label: str
    text: str = ""
    source: str = ""
    confidence: float | None = None
    context_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QCIssue:
    issue_type: str
    severity: QCSeverity
    category: QCCategory
    cue_id: str
    label: str
    description: str
    evidence: tuple[QCEvidence, ...] = ()
    fix_action: str = ""
    fix_metadata: Mapping[str, Any] = field(default_factory=dict)
    source: str = "qc"

    @property
    def safe_fixable(self) -> bool:
        return bool(self.fix_action)

    @property
    def id(self) -> str:
        seed = f"{self.cue_id}\0{self.issue_type}\0{self.source}"
        return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "issue_type": self.issue_type,
            "severity": self.severity.value,
            "category": self.category.value,
            "cue_id": self.cue_id,
            "label": self.label,
            "description": self.description,
            "evidence": [item.to_dict() for item in self.evidence],
            "safe_fixable": self.safe_fixable,
            "fix_action": self.fix_action,
            "fix_metadata": dict(self.fix_metadata),
            "source": self.source,
        }


@dataclass(frozen=True)
class QCResult:
    issues_by_cue: Mapping[str, tuple[QCIssue, ...]]

    @property
    def issues(self) -> tuple[QCIssue, ...]:
        return tuple(issue for rows in self.issues_by_cue.values() for issue in rows)

    def for_cue(self, cue_id: str) -> tuple[QCIssue, ...]:
        return self.issues_by_cue.get(str(cue_id), ())

    def cue_ids(self, severities: Iterable[QCSeverity] | None = None) -> set[str]:
        wanted = set(severities or ())
        return {
            cue_id
            for cue_id, issues in self.issues_by_cue.items()
            if issues and (not wanted or any(issue.severity in wanted for issue in issues))
        }

    def severity_counts(self) -> dict[str, int]:
        counts = Counter(issue.severity.value for issue in self.issues)
        return {level.value: counts[level.value] for level in QCSeverity}

    def safe_fix_counts(self) -> dict[str, int]:
        counts = Counter(issue.category.value for issue in self.issues if issue.safe_fixable)
        return dict(counts)


@dataclass(frozen=True)
class TerminologyEntry:
    canonical: str
    wrong_forms: tuple[str, ...] = ()
    source: str = "词库"


@dataclass(frozen=True)
class _QCContext:
    project: SubtitleProject
    ordered: tuple[StudioCue, ...]
    positions: Mapping[str, int]
    config: QCConfig
    terminology: tuple[TerminologyEntry, ...]
    evidence_by_cue: dict[str, tuple[QCEvidence, ...]] = field(
        default_factory=dict, compare=False
    )
    evidence_index: "_EvidenceTimeIndex | None" = None

    def neighbors(self, cue: StudioCue) -> tuple[StudioCue | None, StudioCue | None]:
        index = self.positions[cue.id]
        previous = self.ordered[index - 1] if index > 0 else None
        following = self.ordered[index + 1] if index + 1 < len(self.ordered) else None
        return previous, following


class _EvidenceTimeIndex:
    """Second-granularity buckets over ``asr_evidence`` rows.

    ``model_evidence`` used to walk the whole evidence mapping once per cue
    (O(cues x evidence)), which measured ~1.3s of GUI-thread time for a real
    976-cue project inside the post-edit deferred QC flush.  The bucket scan
    only visits rows whose start time can possibly overlap the queried cue.
    """

    __slots__ = ("_buckets", "_max_duration_ms")

    _BUCKET_MS = 1_000

    def __init__(self, evidence: Mapping[str, Any]):
        self._buckets: dict[int, list[tuple[int, str, Mapping[str, Any]]]] = defaultdict(list)
        self._max_duration_ms = 0
        for reference, row in evidence.items():
            if not isinstance(row, Mapping):
                continue
            start = int(row.get("start_ms", 0) or 0)
            end = int(row.get("end_ms", start) or start)
            if not (start or end):
                continue
            self._max_duration_ms = max(self._max_duration_ms, max(0, end - start))
            self._buckets[start // self._BUCKET_MS].append((start, reference, row))

    def overlapping(
        self, start_ms: int, end_ms: int, tolerance_ms: int
    ) -> tuple[tuple[int, str, Mapping[str, Any]], ...]:
        bucket = self._BUCKET_MS
        # A row can only satisfy ``row_end >= start_ms - tolerance`` when its
        # start is at most one max-duration away below the window.
        first = (start_ms - tolerance_ms - self._max_duration_ms) // bucket
        last = (end_ms + tolerance_ms) // bucket
        matched: list[tuple[int, str, Mapping[str, Any]]] = []
        for index in range(first, last + 1):
            entries = self._buckets.get(index)
            if not entries:
                continue
            for row_start, _reference, row in entries:
                row_end = int(row.get("end_ms", row_start) or row_start)
                if row_end >= start_ms - tolerance_ms and row_start <= end_ms + tolerance_ms:
                    matched.append((row_start, _reference, row))
        return tuple(matched)


class QCRule(Protocol):
    def evaluate(self, cue: StudioCue, context: _QCContext) -> Iterable[QCIssue]: ...


_CJK = r"\u3400-\u9fff"
_TERMINAL = "。！？!?…"
_PUNCTUATION = "，。！？；：、,.!?;:"


# 2026-09-18 VIII 曾只豁免语气字后的单个空格；2026-10-12 起中文字间的单个
# 半角空格一律视为有意的停顿排版（normalize_format_spaces），不再删除。


def _is_pure_interjection(text: str) -> bool:
    """整条 cue 都是独立语气词/应答（如 AI 断句拆出的「对」「嗯」）。"""
    stripped = str(text or "").strip()
    if not stripped:
        return False
    from .sentence_refine import INTERJECTION_CHARS
    return all(char in INTERJECTION_CHARS for char in stripped)

_EVIDENCE_LABELS = {
    "moss_text": "MOSS",
    "firered_text": "FireRed",
    "firered_llm_text": "FireRed 校对",
    "qwen_asr_text": "Qwen",
    "alternate_text": "备选模型",
}


def _visible_text(value: Any) -> str:
    return re.sub(r"\{[^}]*\}", "", str(value or "")).replace("\\N", "\n")


def _compact(value: Any) -> str:
    return normalize_candidate_text(value)


# 2026-09-18：进入路径 QC 全扫实测 672ms/3839 cue，其中 normalize_* 与
# segmentation_equivalent 对相同文本/文本对被重复求值（等价判定、votes、
# 冲突分类各算一遍）。三者均为 str→str 纯函数，有界缓存不改变任何结果。
@lru_cache(maxsize=16384)
def normalize_candidate_text(value: Any, *, normalize_punctuation: bool = True) -> str:
    """Normalize only for candidate comparison; never mutates cue text."""
    text = unicodedata.normalize("NFKC", _visible_text(value)).strip().casefold()
    text = re.sub(r"\s+", "", text)
    if normalize_punctuation:
        table = str.maketrans({"，": ",", "。": ".", "！": "!", "？": "?", "；": ";", "：": ":"})
        text = text.translate(table)
    return text


_DIGIT_NAMES = "零一二三四五六七八九"


def _spoken_integer(value: str) -> str:
    number = int(value)
    if number < 10:
        return _DIGIT_NAMES[number]
    if number < 100:
        tens, ones = divmod(number, 10)
        return ("十" if tens == 1 else _DIGIT_NAMES[tens] + "十") + (_DIGIT_NAMES[ones] if ones else "")
    if number < 1000:
        hundreds, rest = divmod(number, 100)
        suffix = "" if not rest else ("零" if rest < 10 else "") + _spoken_integer(str(rest))
        return _DIGIT_NAMES[hundreds] + "百" + suffix
    return "".join(_DIGIT_NAMES[int(char)] for char in value)


def normalize_spoken_text(value: Any) -> str:
    """Canonical speech content without erasing real lexical differences."""
    text = normalize_candidate_text(value, normalize_punctuation=False)
    text = re.sub(rf"[{re.escape(_PUNCTUATION)}…—~·'\"()（）【】\[\]]+", "", text)
    return re.sub(r"\d+", lambda match: _spoken_integer(match.group()), text)


@lru_cache(maxsize=8192)
def segmentation_equivalent(current: str, evidence: str) -> bool:
    """True when evidence differs only by punctuation or neighboring boundaries."""
    left = normalize_spoken_text(current)
    right = normalize_spoken_text(evidence)
    if not left or not right:
        return False
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    # Short names and terms carry too much information per character for an
    # insertion/deletion to be dismissed as a neighboring cue boundary.
    if len(shorter) < 6:
        return False
    if shorter in longer and len(shorter) / max(1, len(longer)) >= 0.68:
        return True
    # Compare a bounded set of windows aligned from the strongest matching
    # blocks. The former every-width x every-offset scan became seconds-long
    # for normal 100-250 character ASR evidence.
    pattern, source = shorter, longer
    target = len(pattern)
    lower = max(1, round(target * 0.8))
    upper = min(len(source), round(target * 1.2))
    matcher = SequenceMatcher(None, pattern, source, autojunk=False)
    blocks = sorted(
        matcher.get_matching_blocks(), key=lambda item: item.size, reverse=True
    )[:4]
    widths = {
        lower,
        target,
        upper,
    }
    windows: set[tuple[int, int]] = set()
    for width in widths:
        if width <= 0 or width > len(source):
            continue
        windows.add((0, width))
        windows.add((len(source) - width, width))
        for block in blocks:
            aligned = block.b - block.a
            tail_aligned = block.b + block.size - round(
                (block.a + block.size) * width / max(1, target)
            )
            for raw_start in (aligned, tail_aligned):
                start = min(len(source) - width, max(0, raw_start))
                windows.add((start, width))
    best = max(
        (
            SequenceMatcher(
                None, pattern, source[start:start + width], autojunk=False
            ).ratio()
            for start, width in windows
        ),
        default=matcher.ratio(),
    )
    if best >= 0.92:
        return True
    # A source segment that spans substantially beyond the final Cue often
    # contains one neighboring AI-split sentence. Judge its best aligned
    # window, while keeping same-length one-character conflicts strict.
    return len(longer) >= round(len(shorter) * 1.35) and best >= 0.72


@dataclass(frozen=True)
class QCCandidate:
    text: str
    sources: tuple[str, ...]
    context_only: bool = False


def _review_candidates_from_evidence(
    cue: StudioCue,
    evidence: Iterable[QCEvidence],
    *,
    equivalent_to_current: Mapping[QCEvidence, bool] | None = None,
) -> tuple[QCCandidate, ...]:
    evidence = tuple(evidence)
    grouped: dict[str, dict[str, Any]] = {}
    for item, label, text in (
        (None, "Current", cue.text),
        *((candidate, candidate.label, candidate.text) for candidate in evidence),
    ):
        normalized = normalize_candidate_text(text)
        equivalent = (
            bool(equivalent_to_current.get(item, False))
            if equivalent_to_current is not None and item is not None
            else label != "Current" and (
                normalize_spoken_text(cue.text) == normalize_spoken_text(text)
                or bool(item and item.context_only and segmentation_equivalent(cue.text, text)))
        )
        if label != "Current" and equivalent:
            normalized = normalize_candidate_text(cue.text)
        if not normalized:
            continue
        row = grouped.setdefault(normalized, {"text": str(text).strip(), "sources": [], "context_only": True})
        row['context_only'] = row['context_only'] and bool(item and item.context_only)
        if label not in row["sources"]:
            row["sources"].append(label)
    rows = list(grouped.values())
    indexed_rows = list(enumerate(rows))
    # Keep the current project text first, then prefer independent consensus.
    # The source order inside a candidate remains evidence order for readable UI.
    indexed_rows.sort(
        key=lambda item: (
            0 if "Current" in item[1]["sources"] else 1,
            -len(item[1]["sources"]),
            item[0],
        )
    )
    return tuple(QCCandidate(row["text"], tuple(row["sources"]), row['context_only']) for _index, row in indexed_rows)


def review_candidates(project: SubtitleProject, cue: StudioCue) -> tuple[QCCandidate, ...]:
    """Group Current and model evidence by unique normalized text."""
    return _review_candidates_from_evidence(cue, model_evidence(project, cue))


def _visible_characters(value: str) -> int:
    return len(re.sub(r"\s+", "", _visible_text(value)))


def _model_name(row: Mapping[str, Any], key: str) -> str:
    if key in _EVIDENCE_LABELS:
        return _EVIDENCE_LABELS[key]
    source = str(row.get("primary_source") or "").casefold()
    if key == "text":
        if "qwen" in source:
            return "Qwen"
        if "firered" in source:
            return "FireRed"
        if "moss" in source:
            return "MOSS"
        return "主识别"
    return key.removesuffix("_text").replace("_", " ").title()


def model_evidence(
    project: SubtitleProject,
    cue: StudioCue,
    *,
    index: _EvidenceTimeIndex | None = None,
) -> tuple[QCEvidence, ...]:
    """Join independent cue-local observations, keeping their model identity."""
    from .asr_source_evidence import MODEL_LABELS, cue_source_hypotheses
    grouped = defaultdict(list)
    for row in cue_source_hypotheses(project, cue, index=index):
        grouped[row['model']].append(row)
    result = []
    for model, rows in grouped.items():
        parts = [str(row['text']) for row in rows]
        confidence = [row['confidence'] for row in rows if row.get('confidence') is not None]
        result.append(QCEvidence(label=MODEL_LABELS.get(model, model), text=''.join(parts),
            source=model, confidence=min(confidence) if confidence else None,
            # A concatenation is cue-local only when every contributing row is.
            # Otherwise a neighboring segment could become an adoptable suffix.
            context_only=any(row.get('context_only', False) for row in rows)))
    return tuple(result)


def _confidence_values(project: SubtitleProject, cue: StudioCue) -> list[float]:
    result: list[float] = []
    for reference in cue.evidence_refs:
        row = project.asr_evidence.get(reference, {})
        if not isinstance(row, Mapping):
            continue
        for key, value in row.items():
            name = str(key).casefold()
            # Availability/version/other metadata are not model scores;
            # bool is numeric in Python and would otherwise become 0/1.
            if (name != 'confidence' and not name.endswith('_confidence')) or isinstance(value, bool):
                continue
            # A timing-alignment score is not a transcription confidence.
            if name.endswith('_alignment_confidence'):
                continue
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                continue
            # Old SpeechSegment/project serialization stores zero when Qwen
            # did not provide a score. Explicitly measured zero stays valid.
            if name == 'qwen_confidence' and parsed == 0 and row.get('qwen_confidence_available') is not True:
                continue
            # moss_firered_pipeline uses exactly 0.50 when no independent
            # FireRed candidate exists. That is missing comparison support,
            # not a per-cue acoustic probability.
            if (
                str(key).casefold() == "confidence"
                and abs(parsed - 0.5) < 1e-9
                and str(row.get("primary_source") or "").casefold().startswith("moss")
                and not any(
                    str(row.get(field) or "").strip()
                    for field in (
                        "alternate_text", "firered_text", "firered_llm_text", "qwen_asr_text",
                    )
                )
            ):
                continue
            if 0.0 <= parsed <= 1.0:
                result.append(parsed)
    return result


def _spanning_evidence_matches_current(
    project: SubtitleProject, cue: StudioCue, evidence: QCEvidence,
    *, index: _EvidenceTimeIndex | None = None,
) -> bool:
    """Recognize a model row that spans cue boundaries without false conflict."""
    current = normalize_spoken_text(cue.text)
    if not current:
        return False
    label = str(evidence.label or "").casefold()
    references = set(cue.evidence_refs)
    if references:
        candidate_rows: Iterable[tuple[str, Any]] = (
            (reference, project.asr_evidence.get(reference))
            for reference in cue.evidence_refs
        )
    elif index is not None:
        candidate_rows = (
            (_reference, row)
            for _start, _reference, row in index.overlapping(cue.start_ms, cue.end_ms, 0)
        )
    else:
        candidate_rows = project.asr_evidence.items()
    for reference, row in candidate_rows:
        if not isinstance(row, Mapping):
            continue
        start = int(row.get("start_ms", 0) or 0)
        end = int(row.get("end_ms", start) or start)
        overlap = max(0, min(cue.end_ms, end) - max(cue.start_ms, start))
        if overlap < 50:
            continue
        model_label = _model_name(row, "text").casefold()
        if label and model_label != label:
            continue
        spans_boundary = start < cue.start_ms or end > cue.end_ms
        if not spans_boundary:
            continue
        for key, value in row.items():
            if str(key).casefold() != "text" and not str(key).casefold().endswith("_text"):
                continue
            candidate = normalize_spoken_text(value)
            if candidate and (current in candidate or segmentation_equivalent(cue.text, value)):
                return True
    return False


class ASREvidenceRule:
    def evaluate(self, cue: StudioCue, context: _QCContext) -> Iterable[QCIssue]:
        evidence = context.evidence_by_cue.get(cue.id)
        if evidence is None:
            evidence = model_evidence(context.project, cue, index=context.evidence_index)
            context.evidence_by_cue[cue.id] = evidence
        from .asr_source_evidence import cue_source_hypotheses, coverage_summary
        coverage = coverage_summary(cue_source_hypotheses(context.project, cue, index=context.evidence_index))
        projection_difference = coverage.get('current_text_supported') is False and not coverage['conflict']
        if projection_difference:
            yield QCIssue(
                'current_projection_difference', QCSeverity.WARNING, QCCategory.ASR,
                cue.id, '当前全文缺少局部证据',
                '原始模型文字一致，但按当前时间范围投影后缺少部分字词。请检查字幕边界；已确认文字保留。',
                evidence, source='asr_projection',
            )
        distinct: dict[str, QCEvidence] = {_compact(cue.text): QCEvidence("Current", cue.text, "project")}
        segmentation_rows: list[QCEvidence] = []
        equivalent_to_current: dict[QCEvidence, bool] = {}
        for item in evidence:
            normalized = _compact(item.text)
            if normalized:
                equivalent = (
                    normalize_spoken_text(cue.text) == normalize_spoken_text(item.text)
                    or item.context_only and (segmentation_equivalent(cue.text, item.text)
                        or _spanning_evidence_matches_current(
                            context.project, cue, item, index=context.evidence_index))
                )
                equivalent_to_current[item] = equivalent
                if equivalent:
                    segmentation_rows.append(item)
                else:
                    distinct.setdefault(normalized, item)
        if segmentation_rows and len(distinct) == 1:
            yield QCIssue(
                "segmentation_difference",
                QCSeverity.INFO,
                QCCategory.ASR,
                cue.id,
                "分段方式不同",
                "模型语音内容一致，仅原始分段、标点或数字写法不同。",
                tuple(segmentation_rows),
                source="asr_segmentation",
            )
        if len(distinct) > 1 and not projection_difference:
            items = list(distinct.values())
            pairs = [
                (items[index], other)
                for index in range(len(items))
                for other in items[index + 1:]
            ]
            conflicting = [
                (left, right)
                for left, right in pairs
                if SequenceMatcher(None, _compact(left.text), _compact(right.text), autojunk=False).ratio()
                < context.config.disagreement_similarity
            ]
            if conflicting:
                # Ratio alone flags "AI sentence-split differences" as critical
                # conflicts. Only pairs whose raw texts are NOT segmentation-
                # equivalent carry real content risk; the rest become advisory.
                content_conflicts = tuple(
                    (left, right)
                    for left, right in conflicting
                    if normalize_spoken_text(left.text) != normalize_spoken_text(right.text)
                    and not ((left.context_only or right.context_only)
                             and segmentation_equivalent(left.text, right.text))
                )
                if content_conflicts:
                    yield QCIssue(
                        "model_disagreement",
                        QCSeverity.CRITICAL,
                        QCCategory.ASR,
                        cue.id,
                        "多模型冲突",
                        "不同识别模型对当前字幕给出了明显不同的文本，请试听后选择。",
                        tuple(distinct.values()),
                        source="asr_evidence",
                    )
                else:
                    yield QCIssue(
                        "segmentation_difference",
                        QCSeverity.INFO,
                        QCCategory.ASR,
                        cue.id,
                        "断句差异建议",
                        "模型内容一致，仅断句或分段方式不同；如需更顺滑可考虑合并相邻字幕。",
                        tuple(distinct.values()),
                        source="asr_segmentation",
                    )
        agreement_sources = max(
            (
                len([source for source in candidate.sources if source != 'Current'])
                for candidate in _review_candidates_from_evidence(
                    cue,
                    evidence,
                    equivalent_to_current=equivalent_to_current,
                )
            ),
            default=0,
        )
        confidence_values = _confidence_values(context.project, cue)
        if confidence_values:
            confidence = min(confidence_values)
            # Independent matching transcripts are stronger positive evidence
            # than one decoder's token confidence. Agreement stays out of the
            # priority queue unless another real QC rule finds a problem.
            if agreement_sources >= 3 and not projection_difference:
                severity = None
            elif confidence < context.config.low_confidence_warning:
                # Confidence alone is weak evidence. A real model conflict is
                # emitted separately as critical; otherwise this is advisory.
                severity = QCSeverity.WARNING
            else:
                severity = None
            if severity:
                yield QCIssue(
                    "low_confidence",
                    severity,
                    QCCategory.ASR,
                    cue.id,
                    "低置信度",
                    f"主识别置信度约 {confidence:.0%}，建议结合音频确认。",
                    (QCEvidence("识别置信度", confidence=confidence, source="asr_evidence"),),
                    source="asr_evidence",
                )
        votes = Counter(
            _compact(item.text)
            for item in evidence
            if _compact(item.text) and not equivalent_to_current.get(item, False)
        )
        if votes:
            majority, count = votes.most_common(1)[0]
            current = _compact(cue.text)
            if count >= 2 and majority != current:
                supporters = tuple(item for item in evidence if _compact(item.text) == majority)
                yield QCIssue(
                    "suspected_word",
                    QCSeverity.WARNING,
                    QCCategory.ASR,
                    cue.id,
                    "疑似错词",
                    "至少两个模型给出了相同的另一种写法。",
                    supporters,
                    source="model_consensus",
                )


class TextQualityRule:
    def evaluate(self, cue: StudioCue, context: _QCContext) -> Iterable[QCIssue]:
        text = _visible_text(cue.text)
        # 2026-10-12: a single half-width space between CJK characters is the
        # product's pause spacing (“有点担心 有点担心”), not an error.
        if normalize_format_spaces(text) != text:
            yield QCIssue(
                "extra_spaces", QCSeverity.INFO, QCCategory.TEXT, cue.id,
                "多余空格", "存在首尾空白、连续空格、全角标点旁的空格或不可见空白（不换行/零宽字符）；"
                "中文之间的单个停顿空格是有意排版，不算问题。",
                fix_action="normalize_text", source="text_rule",
            )
        if re.search(rf"([{re.escape(_PUNCTUATION)}])\1+", text):
            yield QCIssue(
                "duplicate_punctuation", QCSeverity.WARNING, QCCategory.TEXT, cue.id,
                "重复标点", "相同标点连续出现，可安全收敛为一个。",
                fix_action="normalize_text", source="text_rule",
            )
        if re.search(rf"^[，。；：、,.;:]|[{re.escape(_PUNCTUATION)}]{{3,}}", text):
            yield QCIssue(
                "abnormal_punctuation", QCSeverity.WARNING, QCCategory.TEXT, cue.id,
                "标点异常", "字幕以异常标点开头，或存在无法确定语义的标点组合。",
                source="text_rule",
            )
        if re.search(r"[\uff10-\uff19\uff21-\uff3a\uff41-\uff5a\u3000]", text):
            yield QCIssue(
                "width_mismatch", QCSeverity.INFO, QCCategory.TEXT, cue.id,
                "全半角混乱", "全角字母、数字或空格可统一为常用半角形式。",
                fix_action="normalize_text", source="text_rule",
            )
        if re.search(r"(?<![A-Za-z])i(?![A-Za-z])", text):
            yield QCIssue(
                "english_case", QCSeverity.INFO, QCCategory.TEXT, cue.id,
                "英文大小写异常", "独立英文代词 i 应写为 I。",
                fix_action="normalize_text", source="text_rule",
            )
        if re.search(r"[\uff10-\uff19]", text) or re.search(r"\d，\d", text):
            yield QCIssue(
                "number_format", QCSeverity.INFO, QCCategory.TEXT, cue.id,
                "数字格式异常", "数字中混入全角字符或中文分隔符。",
                fix_action="normalize_text", source="text_rule",
            )
        repeated = re.search(rf"([{_CJK}])\1{{3,}}", text)
        if repeated:
            yield QCIssue(
                "repeated_character", QCSeverity.WARNING, QCCategory.TEXT, cue.id,
                "连续重复字", f"“{repeated.group(0)}”可能是识别重复，也可能是语气表达，请人工确认。",
                source="text_rule",
            )


class TerminologyRule:
    def evaluate(self, cue: StudioCue, context: _QCContext) -> Iterable[QCIssue]:
        text = _visible_text(cue.text)
        evidence = context.evidence_by_cue.get(cue.id)
        if evidence is None:
            evidence = model_evidence(context.project, cue, index=context.evidence_index)
            context.evidence_by_cue[cue.id] = evidence
        for entry in context.terminology:
            canonical = entry.canonical.strip()
            if not canonical:
                continue
            wrong = next((form for form in entry.wrong_forms if form and form in text), "")
            model_support = tuple(
                item for item in evidence
                if canonical in item.text
                and not (
                    canonical not in text
                    and _spanning_evidence_matches_current(
                        context.project, cue, item, index=context.evidence_index
                    )
                )
            )
            if wrong:
                yield QCIssue(
                    "terminology_mismatch",
                    QCSeverity.CRITICAL if model_support else QCSeverity.WARNING,
                    QCCategory.TERMINOLOGY,
                    cue.id,
                    "术语疑似错误",
                    f"词库标准写法为“{canonical}”，当前字幕出现“{wrong}”。",
                    (*model_support, QCEvidence("词库", canonical, entry.source)),
                    source=entry.source,
                )
                return
            if canonical not in text and model_support:
                yield QCIssue(
                    "terminology_model_conflict",
                    QCSeverity.WARNING,
                    QCCategory.TERMINOLOGY,
                    cue.id,
                    "模型与词库冲突",
                    f"模型证据包含词库标准词“{canonical}”，当前字幕未采用。",
                    (*model_support, QCEvidence("词库", canonical, entry.source)),
                    source=entry.source,
                )
                return


class TimelineRule:
    def evaluate(self, cue: StudioCue, context: _QCContext) -> Iterable[QCIssue]:
        previous, following = context.neighbors(cue)
        duration = cue.end_ms - cue.start_ms
        if not cue.text.strip():
            yield QCIssue(
                "empty_cue", QCSeverity.CRITICAL, QCCategory.TIMELINE, cue.id,
                "空字幕", "字幕没有可见文字，可安全删除。",
                fix_action="delete_empty", source="timeline_rule",
            )
        if duration < context.config.min_duration_ms:
            severity = (
                QCSeverity.CRITICAL
                if duration < context.config.very_short_duration_ms
                else QCSeverity.WARNING
            )
            yield QCIssue(
                "short_duration", severity, QCCategory.TIMELINE, cue.id,
                "持续时间过短", f"当前字幕仅持续 {duration} ms。",
                source="timeline_rule",
            )
        elif duration > context.config.max_duration_ms:
            yield QCIssue(
                "long_duration", QCSeverity.WARNING, QCCategory.TIMELINE, cue.id,
                "持续时间异常长", f"当前字幕持续 {duration / 1000:.1f} 秒。",
                source="timeline_rule",
            )
        if previous:
            gap = cue.start_ms - previous.end_ms
            same_speaker = cue.speaker_id == previous.speaker_id
            combined = _visible_characters(previous.text) + _visible_characters(cue.text)
            if gap < 0:
                overlap = -gap
                micro = overlap <= context.config.micro_overlap_ms and same_speaker
                # Same-speaker overlaps on a continuous sentence are split
                # artifacts, not delivery errors: suggest a merge instead of
                # pushing the cue into the "needs confirmation" queue.
                continuous = (
                    same_speaker
                    and not previous.text.rstrip().endswith(tuple(_TERMINAL))
                    and _compact(previous.text) != _compact(cue.text)
                    and combined <= context.config.fragment_max_combined_characters
                )
                if continuous and overlap <= 1200:
                    yield QCIssue(
                        "merge_overlap_suggestion",
                        QCSeverity.INFO,
                        QCCategory.TIMELINE,
                        cue.id,
                        "建议合并叠字幕",
                        "与上一条同一说话人且语义连续，重叠处合并为一条会更顺畅。",
                        fix_action="merge_fragment",
                        fix_metadata={"previous_cue_id": previous.id},
                        source="timeline_rule",
                    )
                else:
                    yield QCIssue(
                        "micro_overlap" if micro else "overlap",
                        QCSeverity.WARNING if micro else QCSeverity.CRITICAL,
                        QCCategory.TIMELINE,
                        cue.id,
                        "极小重叠" if micro else "时间轴重叠",
                        f"与上一条重叠 {overlap} ms。",
                        fix_action="close_overlap" if micro else "",
                        fix_metadata={"previous_cue_id": previous.id, "milliseconds": overlap},
                        source="timeline_rule",
                    )
            elif 0 < gap < context.config.short_gap_ms:
                micro = gap <= context.config.micro_gap_ms and same_speaker
                yield QCIssue(
                    "micro_gap" if micro else "short_gap",
                    QCSeverity.INFO,
                    QCCategory.TIMELINE,
                    cue.id,
                    "极小间隔" if micro else "字幕间隔过小",
                    f"与上一条仅间隔 {gap} ms。",
                    fix_action="close_gap" if micro else "",
                    fix_metadata={"previous_cue_id": previous.id, "milliseconds": gap},
                    source="timeline_rule",
                )
            if (
                same_speaker
                and _compact(previous.text) == _compact(cue.text)
                and _compact(cue.text)
                and -context.config.micro_overlap_ms <= gap <= context.config.duplicate_gap_ms
            ):
                yield QCIssue(
                    "consecutive_duplicate", QCSeverity.WARNING, QCCategory.TIMELINE, cue.id,
                    "连续字幕完全相同", "与上一条文本及说话人相同，可合并为一条。",
                    fix_action="merge_duplicate",
                    fix_metadata={"previous_cue_id": previous.id},
                    source="timeline_rule",
                )
            combined = _visible_characters(previous.text) + _visible_characters(cue.text)
            fragment = min(duration, previous.end_ms - previous.start_ms) <= context.config.fragment_duration_ms
            fragment_chars = min(_visible_characters(previous.text), _visible_characters(cue.text)) <= context.config.fragment_characters
            same_presentation = previous.style_id == cue.style_id and previous.effect_id == cue.effect_id
            if (
                same_speaker
                and same_presentation
                and fragment
                and fragment_chars
                and -context.config.micro_overlap_ms <= gap <= context.config.fragment_merge_gap_ms
                and combined <= context.config.fragment_max_combined_characters
                and not previous.text.rstrip().endswith(tuple(_TERMINAL))
                and _compact(previous.text) != _compact(cue.text)
            ):
                yield QCIssue(
                    "merge_fragment", QCSeverity.INFO, QCCategory.TIMELINE, cue.id,
                    "疑似碎片字幕", "同一说话人的极短连续片段可保守合并。",
                    fix_action="merge_fragment",
                    fix_metadata={"previous_cue_id": previous.id},
                    source="timeline_rule",
                )


class ReadabilityRule:
    def evaluate(self, cue: StudioCue, context: _QCContext) -> Iterable[QCIssue]:
        duration = max(1, cue.end_ms - cue.start_ms)
        characters = _visible_characters(cue.text)
        cps = characters / (duration / 1000)
        if cps > context.config.max_cps_critical:
            severity = QCSeverity.CRITICAL
        elif cps > context.config.max_cps_warning:
            severity = QCSeverity.WARNING
        else:
            severity = None
        if severity:
            yield QCIssue(
                "high_cps", severity, QCCategory.READABILITY, cue.id,
                "读速过快", f"约 {cps:.1f} 字/秒，建议延长时间或精简文本。",
                (QCEvidence("CPS", f"{cps:.1f}"),), source="readability_rule",
            )
        lines = _visible_text(cue.text).splitlines() or [""]
        longest = max((len(line) for line in lines), default=0)
        if longest > context.config.max_line_length:
            yield QCIssue(
                "line_too_long", QCSeverity.WARNING, QCCategory.READABILITY, cue.id,
                "单行过长", f"最长一行 {longest} 字，建议重新断行。",
                source="readability_rule",
            )
        if len(lines) == 2:
            shorter, longer = sorted(map(len, lines))
            if longer >= 12 and shorter <= max(2, longer // 4):
                yield QCIssue(
                    "unbalanced_lines", QCSeverity.INFO, QCCategory.READABILITY, cue.id,
                    "双行严重不均", "两行长度差异较大，建议调整换行位置。",
                    source="readability_rule",
                )
        if duration < context.config.min_duration_ms and characters > 10:
            yield QCIssue(
                "dense_short_cue", QCSeverity.CRITICAL, QCCategory.READABILITY, cue.id,
                "短时间文字过多", "字幕很短但文字较多，几乎无法完整阅读。",
                source="readability_rule",
            )


class SpeakerContinuityRule:
    def evaluate(self, cue: StudioCue, context: _QCContext) -> Iterable[QCIssue]:
        index = context.positions[cue.id]
        if index <= 0 or index + 1 >= len(context.ordered):
            return
        previous = context.ordered[index - 1]
        following = context.ordered[index + 1]
        if (
            previous.speaker_id == following.speaker_id
            and cue.speaker_id != previous.speaker_id
            and cue.end_ms - cue.start_ms <= 900
            and cue.start_ms - previous.end_ms <= context.config.speaker_continuity_gap_ms
            and following.start_ms - cue.end_ms <= context.config.speaker_continuity_gap_ms
        ):
            yield QCIssue(
                "speaker_jump", QCSeverity.INFO, QCCategory.SPEAKER, cue.id,
                "Speaker 异常跳变", "相邻连续语句呈 A-B-A 切换，请确认中间字幕说话人。",
                source="speaker_rule",
            )
        if (
            previous.speaker_id != cue.speaker_id
            and cue.start_ms - previous.end_ms <= context.config.speaker_continuity_gap_ms
            and previous.text.rstrip()
            and not previous.text.rstrip().endswith(tuple(_TERMINAL))
        ):
            yield QCIssue(
                "speaker_sentence_switch", QCSeverity.INFO, QCCategory.SPEAKER, cue.id,
                "连续语句疑似切换 Speaker", "上一条没有结束语气且间隔很短，仅作保守提示。",
                source="speaker_rule",
            )


DEFAULT_RULES: tuple[QCRule, ...] = (
    ASREvidenceRule(),
    TextQualityRule(),
    TerminologyRule(),
    TimelineRule(),
    ReadabilityRule(),
    SpeakerContinuityRule(),
)


class SubtitleQCEngine:
    def __init__(self, config: QCConfig | None = None, rules: Sequence[QCRule] = DEFAULT_RULES):
        self.config = config or QCConfig()
        self.rules = tuple(rules)

    def _context(
        self,
        project: SubtitleProject,
        terminology: Iterable[TerminologyEntry] = (),
    ) -> _QCContext:
        ordered = tuple(sorted(project.cues, key=lambda item: (item.start_ms, item.end_ms, item.id)))
        evidence_index = (
            _EvidenceTimeIndex(project.asr_evidence)
            if getattr(project, "asr_evidence", None)
            else None
        )
        return _QCContext(
            project,
            ordered,
            {cue.id: index for index, cue in enumerate(ordered)},
            self.config,
            tuple(terminology),
            evidence_index=evidence_index,
        )

    def analyze(
        self,
        project: SubtitleProject,
        *,
        cue_ids: Iterable[str] | None = None,
        terminology: Iterable[TerminologyEntry] = (),
    ) -> QCResult:
        context = self._context(project, terminology)
        selected = None if cue_ids is None else {str(item) for item in cue_ids}
        cues = [
            cue for cue in context.ordered
            if selected is None or cue.id in selected
        ]
        return QCResult(self.evaluate_cues(context, cues))

    def build_context(
        self,
        project: SubtitleProject,
        *,
        terminology: Iterable[TerminologyEntry] = (),
    ) -> "_QCContext":
        """Reusable context for sliced scans（2026-09-18 进入路径分片 QC）。"""
        return self._context(project, terminology)

    def evaluate_cues(
        self,
        context: "_QCContext",
        cues: Sequence[StudioCue],
    ) -> dict[str, tuple[QCIssue, ...]]:
        """Evaluate an explicit cue slice against a prebuilt context."""
        severity_order = {QCSeverity.CRITICAL: 0, QCSeverity.WARNING: 1, QCSeverity.INFO: 2}
        issues: dict[str, tuple[QCIssue, ...]] = {}
        for cue in cues:
            rows = [issue for rule in self.rules for issue in rule.evaluate(cue, context)]
            rows.sort(key=lambda issue: (severity_order[issue.severity], issue.category.value, issue.label))
            issues[cue.id] = tuple(rows)
        return issues

    def analyze_incremental(
        self,
        project: SubtitleProject,
        cue_id: str,
        previous: QCResult,
        *,
        terminology: Iterable[TerminologyEntry] = (),
    ) -> QCResult:
        context = self._context(project, terminology)
        cue_id = str(cue_id)
        position = context.positions.get(cue_id)
        if position is None:
            return self.analyze(project, terminology=terminology)
        affected = {
            context.ordered[index].id
            for index in range(max(0, position - 2), min(len(context.ordered), position + 3))
        }
        partial = self.analyze(project, cue_ids=affected, terminology=terminology)
        merged = dict(previous.issues_by_cue)
        for affected_id in affected:
            merged.pop(affected_id, None)
        merged.update(partial.issues_by_cue)
        existing = {cue.id for cue in project.cues}
        return QCResult({key: value for key, value in merged.items() if key in existing})

    def analyze_incremental_many(
        self,
        project: SubtitleProject,
        cue_ids: Iterable[str],
        previous: QCResult,
        *,
        terminology: Iterable[TerminologyEntry] = (),
    ) -> QCResult:
        """Same result as folding analyze_incremental() over ``cue_ids``.

        The project does not change between those calls, so each fold step
        rebuilt the same whole-project context and re-evaluated overlapping
        windows. Build it once and evaluate the union of the +/-2 windows.
        """
        cue_ids = [str(item) for item in cue_ids]
        if not cue_ids:
            return previous
        terminology = tuple(terminology)
        context = self._context(project, terminology)
        positions = [context.positions.get(cue_id) for cue_id in cue_ids]
        if any(position is None for position in positions):
            return self.analyze(project, terminology=terminology)
        affected = {
            context.ordered[index].id
            for position in positions
            for index in range(max(0, position - 2), min(len(context.ordered), position + 3))
        }
        partial = self.analyze(project, cue_ids=affected, terminology=terminology)
        merged = dict(previous.issues_by_cue)
        for affected_id in affected:
            merged.pop(affected_id, None)
        merged.update(partial.issues_by_cue)
        existing = {cue.id for cue in project.cues}
        return QCResult({key: value for key, value in merged.items() if key in existing})


def _halfwidth_alphanumerics(text: str) -> str:
    result: list[str] = []
    for character in text:
        code = ord(character)
        if 0xFF10 <= code <= 0xFF19 or 0xFF21 <= code <= 0xFF3A or 0xFF41 <= code <= 0xFF5A:
            result.append(chr(code - 0xFEE0))
        elif character == "\u3000":
            result.append(" ")
        else:
            result.append(character)
    return "".join(result)


_FORMAT_INVISIBLE = frozenset("\u200b\u200c\u200d\u2060\ufeff")
_SPACE_BEFORE_FULLWIDTH = "，。！？；：、）」』】》〉"
_SPACE_AFTER_FULLWIDTH = "，。！？；：、（「『【《〈"


def _emoji_joiner(text: str, index: int) -> bool:
    if not 0 < index < len(text) - 1:
        return False
    return (unicodedata.category(text[index - 1]) in ("So", "Sk", "Mn")
            and unicodedata.category(text[index + 1]) == "So")


def normalize_format_spaces(text: str) -> str:
    """Format-only whitespace cleanup; the same rules as
    ``text_rules.normalize_format_whitespace`` (kept here so Studio QC does not
    import the recognition facade).

    Removes zero-width characters, edge whitespace of each line, spaces that
    touch full-width punctuation, and collapses other whitespace runs (incl.
    U+3000/NBSP) to one U+0020.  Keeps every single inner space: CJK pause
    spacing, English word spacing and user typesetting.  Idempotent.
    """
    text = str(text or "")
    if any(char in _FORMAT_INVISIBLE for char in text):
        text = "".join(char for index, char in enumerate(text)
                       if char not in _FORMAT_INVISIBLE
                       or (char == "\u200d" and _emoji_joiner(text, index)))
    lines: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"\A\s+|\s+\Z", "", line)
        line = re.sub(r"[^\S\n]+", " ", line)
        line = re.sub(rf" (?=[{_SPACE_BEFORE_FULLWIDTH}])", "", line)
        line = re.sub(rf"(?<=[{_SPACE_AFTER_FULLWIDTH}]) ", "", line)
        lines.append(line)
    return "\n".join(lines).strip("\n")


def normalize_safe_text(text: str) -> str:
    """Apply only formatting changes that do not choose alternative wording.

    2026-10-12: single spaces between CJK characters are intentional pause
    spacing and stay; only format junk (``normalize_format_spaces``) goes.
    """
    value = _halfwidth_alphanumerics(str(text or ""))
    lines: list[str] = []
    for line in value.splitlines() or [value]:
        line = normalize_format_spaces(line)
        line = re.sub(rf"([{re.escape(_PUNCTUATION)}])\1+", r"\1", line)
        line = re.sub(r"(?<![A-Za-z])i(?![A-Za-z])", "I", line)
        line = re.sub(r"(?<=\d)，(?=\d)", ",", line)
        lines.append(line)
    return "\n".join(lines).strip()


def _join_fragment_text(left: str, right: str) -> str:
    left, right = left.rstrip(), right.lstrip()
    separator = " " if left[-1:].isascii() and left[-1:].isalnum() and right[:1].isascii() and right[:1].isalnum() else ""
    return left + separator + right


@dataclass(frozen=True)
class SafeFixPlan:
    cues: tuple[StudioCue, ...]
    text_format_count: int = 0
    timing_count: int = 0
    duplicate_fragment_count: int = 0

    @property
    def total(self) -> int:
        return self.text_format_count + self.timing_count + self.duplicate_fragment_count

    @property
    def counts(self) -> dict[str, int]:
        return {
            "text_format": self.text_format_count,
            "timeline": self.timing_count,
            "duplicate_fragment": self.duplicate_fragment_count,
        }


def build_safe_fix_plan(project: SubtitleProject, config: QCConfig | None = None) -> SafeFixPlan:
    """Prepare a conservative project replacement without mutating ``project``."""
    config = config or QCConfig()
    working = copy.deepcopy(project.cues)
    text_count = 0
    for cue in working:
        normalized = normalize_safe_text(cue.text)
        if normalized != cue.text:
            cue.text = normalized
            text_count += 1

    empty_ids = {cue.id for cue in working if not cue.text.strip()}
    structure_count = len(empty_ids)
    if empty_ids:
        working = [cue for cue in working if cue.id not in empty_ids]

    def chronological() -> list[StudioCue]:
        return sorted(working, key=lambda item: (item.start_ms, item.end_ms, item.id))

    removed: set[str] = set()
    ordered = chronological()
    for left, right in zip(ordered, ordered[1:]):
        if left.id in removed or right.id in removed:
            continue
        gap = right.start_ms - left.end_ms
        if (
            left.speaker_id == right.speaker_id
            and _compact(left.text) == _compact(right.text)
            and _compact(left.text)
            and -config.micro_overlap_ms <= gap <= config.duplicate_gap_ms
            # AI 断句拆出的逐字应答（「对」「对」）是有意的节奏决策，
            # 不在安全修复里合回一条丢掉重复。
            and not (_is_pure_interjection(left.text) or _is_pure_interjection(right.text))
        ):
            left.end_ms = max(left.end_ms, right.end_ms)
            left.evidence_refs = list(dict.fromkeys([*left.evidence_refs, *right.evidence_refs]))
            removed.add(right.id)
            structure_count += 1
    if removed:
        working = [cue for cue in working if cue.id not in removed]

    removed = set()
    ordered = chronological()
    for left, right in zip(ordered, ordered[1:]):
        if left.id in removed or right.id in removed:
            continue
        gap = right.start_ms - left.end_ms
        durations = (left.end_ms - left.start_ms, right.end_ms - right.start_ms)
        character_counts = (_visible_characters(left.text), _visible_characters(right.text))
        combined = sum(character_counts)
        if not (
            left.speaker_id == right.speaker_id
            and left.style_id == right.style_id
            and left.effect_id == right.effect_id
            and min(durations) <= config.fragment_duration_ms
            and min(character_counts) <= config.fragment_characters
            and -config.micro_overlap_ms <= gap <= config.fragment_merge_gap_ms
            and combined <= config.fragment_max_combined_characters
            and not left.text.rstrip().endswith(tuple(_TERMINAL))
            # 独立语气词 cue（「嗯」「好」）不与邻句拼接（同上：有意节奏）。
            and not (_is_pure_interjection(left.text) or _is_pure_interjection(right.text))
        ):
            continue
        left.text = _join_fragment_text(left.text, right.text)
        left.original_text = _join_fragment_text(left.original_text, right.original_text)
        left.end_ms = max(left.end_ms, right.end_ms)
        left.evidence_refs = list(dict.fromkeys([*left.evidence_refs, *right.evidence_refs]))
        removed.add(right.id)
        structure_count += 1
    if removed:
        working = [cue for cue in working if cue.id not in removed]

    timing_count = 0
    ordered = chronological()
    for left, right in zip(ordered, ordered[1:]):
        if left.speaker_id != right.speaker_id:
            continue
        gap = right.start_ms - left.end_ms
        if -config.micro_overlap_ms <= gap < 0:
            candidate = left.end_ms
            if right.end_ms - candidate >= config.very_short_duration_ms:
                right.start_ms = candidate
                timing_count += 1
        elif 0 < gap <= config.micro_gap_ms:
            left.end_ms = right.start_ms
            timing_count += 1

    for cue in working:
        cue.validate()
    return SafeFixPlan(tuple(working), text_count, timing_count, structure_count)


def terminology_from_project(project: SubtitleProject) -> tuple[TerminologyEntry, ...]:
    """Read existing term-library data without mutating recognition runtime state."""
    if not project.glossary_ids:
        return ()
    try:
        import subtitle_core
    except Exception:
        return ()
    wanted = {str(item).strip() for item in project.glossary_ids if str(item).strip()}
    result: dict[str, TerminologyEntry] = {}
    try:
        profiles = subtitle_core.load_game_profiles()
    except Exception:
        profiles = {}
    for name, profile in profiles.items() if isinstance(profiles, Mapping) else ():
        identity = subtitle_core.runtime_game_identity(str(profile.get("identity", name)))
        if identity not in wanted and str(name) not in wanted:
            continue
        for item in profile.get("terms", []):
            if not isinstance(item, Mapping):
                continue
            canonical = str(item.get("canonical") or "").strip()
            aliases = tuple(str(alias).strip() for alias in item.get("aliases", []) if str(alias).strip())
            if canonical:
                result[canonical] = TerminologyEntry(canonical, aliases, str(name))
    for identity in wanted:
        try:
            mappings = subtitle_core.learned_mappings_for_game(identity)
        except Exception:
            mappings = ()
        for mapping in mappings:
            if not isinstance(mapping, Mapping):
                continue
            source = str(mapping.get("from") or "").strip()
            target = str(mapping.get("to") or "").strip()
            if not target:
                continue
            previous = result.get(target)
            wrong_forms = tuple(dict.fromkeys([*(previous.wrong_forms if previous else ()), *([source] if source and source != target else [])]))
            result[target] = TerminologyEntry(target, wrong_forms, identity)
    return tuple(result.values())
