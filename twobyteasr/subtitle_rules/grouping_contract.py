"""Stage-9-only contract. Never validate human edits against ASR.

Offsets count Unicode code points matched by text_rules.content_exact, not
UTF-16 units, graphemes or raw string length. All other source characters are
preserved by local reconstruction.
"""
from __future__ import annotations
from bisect import bisect_right
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any

from ..diagnostics.event_bridge import validation

CONTRACT_VERSION = "grouping-source-contract-v1"


class GroupingContractError(ValueError):
    def __init__(self, message, *, category="grouping_data_inconsistent"):
        super().__init__(message)
        self.category = category


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _field(row, key, default=None):
    return row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)


def _time(value):
    try:
        valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
    except (OverflowError, ValueError):
        valid = False
    if not valid:
        raise GroupingContractError("来源或字幕时间不是有限数字。", category="invalid_time")
    return float(value)


@dataclass(frozen=True)
class GroupingSourceRow:
    source_id: Any
    start: float
    end: float
    text: str
    speaker: str
    words: tuple[tuple[float, float, str], ...] = ()
    timing_locked: bool = False
    word_evidence_sha256: str = ""


@dataclass(frozen=True)
class GroupingSourceSnapshot:
    rows: tuple[GroupingSourceRow, ...]
    job_id: str = ""
    batch_id: str = ""
    version: str = CONTRACT_VERSION

    @property
    def fingerprint(self):
        return _hash([(row.source_id, row.start, row.end, row.text, row.speaker,
                       row.words, row.timing_locked, row.word_evidence_sha256) for row in self.rows])

    @property
    def source_text(self):
        return "".join(row.text for row in self.rows)

    def identity(self):
        return {"contract_version": self.version, "job_id": self.job_id,
                "batch_id": self.batch_id, "source_sha256": self.fingerprint,
                "source_ids": [row.source_id for row in self.rows],
                "index_unit": "content_exact_unicode_codepoints",
                "time_domain": "source_seconds"}

    def require_current(self, rows):
        if capture_grouping_source(rows).fingerprint != self.fingerprint:
            raise GroupingContractError("断句来源已变化；过期候选不能覆盖新的来源。",
                                        category="stale_source")


def runtime_task_binding(context):
    """A non-secret identity of the local destination, not an AI-returned ID."""
    return _hash([str(getattr(context, "job_id", "")),
                  str(getattr(context, "media_index", "")),
                  str(getattr(context, "media_path", "")),
                  str(getattr(context, "studio_project_path", ""))])


def capture_grouping_source(rows, *, job_id="", batch_id=""):
    captured, ids = [], set()
    for index, row in enumerate(rows):
        source_id = _field(row, "segment_id", _field(row, "id", index))
        if isinstance(source_id, bool) or not isinstance(source_id, (str, int)) or source_id in ids:
            raise GroupingContractError("断句来源 ID 缺失、重复或类型错误。", category="source_identity")
        ids.add(source_id)
        text = _field(row, "text")
        if not isinstance(text, str) or not text.strip():
            raise GroupingContractError("断句来源正文为空或类型错误。", category="source_text")
        start, end = _time(_field(row, "start")), _time(_field(row, "end"))
        if start < 0 or end <= start:
            raise GroupingContractError("断句来源句级时间无效。", category="invalid_time")
        speaker = _field(row, "speaker", "S00") or "S00"
        if not isinstance(speaker, str):
            raise GroupingContractError("断句来源说话人类型错误。", category="source_identity")
        words = []
        raw_words = tuple(_field(row, "words", ()) or ())
        word_identity = [(repr(_field(word, "start")), repr(_field(word, "end")),
                          repr(_field(word, "text")), repr(_field(word, "probability")))
                         for word in raw_words]
        for word in raw_words:
            a, b = _field(word, "start"), _field(word, "end")
            word_text = _field(word, "text", "")
            try:
                valid = _time(a) >= 0 and _time(b) > _time(a) and isinstance(word_text, str)
            except GroupingContractError:
                valid = False
            if valid:
                words.append((float(a), float(b), word_text))
        captured.append(GroupingSourceRow(source_id, start, end, text, speaker,
            tuple(words), bool(_field(row, "timing_locked", False)), _hash(word_identity)))
    return GroupingSourceSnapshot(tuple(captured), str(job_id or ""), str(batch_id or ""))


@validation("grouping.speaker_text_order_and_source_time")
def validate_grouping_result(source, cues, *, minimum_seconds=.35,
                             protected_after_source_ids=(), protect_all_source_boundaries=False):
    """Read-only conservation, ownership and source-seconds checks.

    Normal simultaneous speech is allowed. Readability may extend a short cue
    to its existing minimum duration; arbitrary other-source times fail.
    """
    from ..providers.asr_provider_snapshot import strip_boundary_space, _boundary_space
    snapshot = source if isinstance(source, GroupingSourceSnapshot) else capture_grouping_source(source)
    groups = {}
    positions = {row.source_id: index for index, row in enumerate(snapshot.rows)}
    protected = set(protected_after_source_ids)
    for row in snapshot.rows:
        groups.setdefault(row.speaker, []).append(row)
    output = {speaker: [] for speaker in groups}
    for cue in cues:
        speaker = _field(cue, "speaker", "S00") or "S00"
        if speaker not in output:
            raise GroupingContractError("断句候选引用了未知说话人。", category="source_identity")
        output[speaker].append(cue)
    for speaker, rows in groups.items():
        text = "".join(row.text for row in rows)
        ends, running = [], 0
        for row in rows:
            running += len(row.text)
            ends.append(running)
        cursor = 0
        for cue in output[speaker]:
            value = _field(cue, "text")
            if not isinstance(value, str):
                raise GroupingContractError("断句候选正文类型错误。", category="source_text")
            core = strip_boundary_space(value)
            if not core:
                raise GroupingContractError("断句候选包含空字幕。", category="source_text")
            while cursor < len(text) and _boundary_space(text[cursor]):
                cursor += 1
            left, right = cursor, cursor + len(core)
            if not text.startswith(core, cursor):
                raise GroupingContractError("断句未保持每个说话人的完整来源正文与顺序。",
                                            category="text_mutation_rejected")
            cursor = right
            owners = rows[bisect_right(ends, left):bisect_right(ends, right - 1) + 1]
            start, end = _time(_field(cue, "start")), _time(_field(cue, "end"))
            if not owners or start < 0 or end <= start:
                raise GroupingContractError("断句候选句级时间无效。", category="invalid_time")
            for left_owner, right_owner in zip(owners, owners[1:]):
                if (protect_all_source_boundaries or left_owner.source_id in protected
                        or positions[right_owner.source_id] != positions[left_owner.source_id] + 1
                        or right_owner.start - left_owner.end > 2.0):
                    raise GroupingContractError("断句跨过了受保护的来源或说话人交接边界。",
                                                category="protected_boundary")
            # Raw word evidence can itself be stale or in another time domain.
            # It participates in source identity but cannot widen the trusted
            # sentence envelope; reject and retain source sentences instead.
            earliest = min(row.start for row in owners)
            latest = max(row.end for row in owners)
            if start < earliest - .05 or start > latest + .05 or end > max(latest, start + minimum_seconds) + .05:
                raise GroupingContractError("断句候选时间超出其实际来源范围。", category="source_time_mismatch")
        while cursor < len(text) and _boundary_space(text[cursor]):
            cursor += 1
        if cursor != len(text):
            raise GroupingContractError("断句未覆盖完整来源正文。", category="text_mutation_rejected")
    return True


def grouped_result_is_valid(source, cues, **kwargs):
    try:
        return validate_grouping_result(source, cues, **kwargs)
    except (GroupingContractError, TypeError, AttributeError, KeyError):
        return False


def _unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise GroupingContractError("断句 JSON 包含重复字段。", category="format_mismatch")
        value[key] = item
    return value


@validation("grouping.boundary_schema_range")
def validate_boundary_offsets(boundaries, total):
    if (not isinstance(boundaries, list) or not boundaries or len(boundaries) > total
            or any(type(item) is not int for item in boundaries)):
        raise GroupingContractError("断句 boundaries 必须是非空整数数组。", category="boundary_schema")
    if boundaries != sorted(set(boundaries)) or boundaries[0] <= 0 or boundaries[-1] != total:
        raise GroupingContractError("断句 boundaries 必须递增、合法且覆盖全文终点。", category="boundary_range")
    return boundaries


@validation("grouping.json_and_source_equivalence")
def parse_grouping_response(content, source_text):
    """Accept complete JSON; a whole fenced object/numeric array is legacy.

    Never extract arbitrary objects from prose/error pages, or prefer one of
    two contradictory representations before local quality repairs.
    """
    from .text_rules import display_length, content_exact
    if not isinstance(content, str) or not content.strip():
        raise GroupingContractError("断句响应为空或类型错误。", category="empty_response")
    total = display_length(source_text)
    if total != len(content_exact(source_text)):
        raise GroupingContractError("来源字形归一化改变了索引长度；仅可使用原语音段边界。",
                                    category="index_unit_mismatch")
    if len(content.encode("utf-8")) > min(1024 * 1024, max(4096, len(source_text.encode("utf-8")) * 4 + total * 24)):
        raise GroupingContractError("断句响应超过本批合理大小。", category="response_too_large")
    raw = content.lstrip("\ufeff").strip()
    fence = chr(96) * 3
    if raw.startswith(fence) and raw.endswith(fence):
        lines = raw.splitlines()
        if lines[0].strip().lower() not in (fence, fence + "json") or lines[-1].strip() != fence:
            raise GroupingContractError("断句响应外层格式不完整。", category="parse_failure")
        raw = "\n".join(lines[1:-1]).strip()
    try:
        returned = json.loads(raw, object_pairs_hook=_unique_pairs,
                              parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, TypeError) as exc:
        if isinstance(exc, GroupingContractError):
            raise
        raise GroupingContractError("断句 JSON 必须是完整响应，不能混入解释、错误页或尾随内容。",
                                    category="parse_failure") from exc
    if isinstance(returned, list):
        returned = {"boundaries": returned}
    if not isinstance(returned, dict) or not returned or set(returned) - {"boundaries", "segmented_text"}:
        raise GroupingContractError("断句 JSON 字段不符合协议。", category="format_mismatch")
    boundaries = returned.get("boundaries")
    if "boundaries" in returned:
        validate_boundary_offsets(boundaries, total)
    if "segmented_text" in returned:
        segmented = returned["segmented_text"]
        if not isinstance(segmented, str) or not segmented:
            raise GroupingContractError("segmented_text 必须是完整非空正文。", category="format_mismatch")
        pieces = segmented.split("|")
        if any(not piece or display_length(piece) <= 0 for piece in pieces) or "".join(pieces) != source_text:
            raise GroupingContractError("segmented_text 改动、遗漏或混入了来源正文。",
                                        category="text_mutation_rejected")
        legacy, running = [], 0
        for piece in pieces:
            running += display_length(piece)
            legacy.append(running)
        validate_boundary_offsets(legacy, total)
        if boundaries is not None and boundaries != legacy:
            raise GroupingContractError("boundaries 与 segmented_text 相互矛盾。",
                                        category="conflicting_representations")
        boundaries = legacy
    validate_boundary_offsets(boundaries, total)
    return list(boundaries), returned

