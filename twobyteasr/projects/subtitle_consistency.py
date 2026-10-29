"""Read-only checks at Studio/load/export boundaries, never on each keystroke.

These checks describe an editable project, not a pure AI segmentation response.
Grouping must prove source coverage against its own trusted input snapshot before
commit. Human edits and translated/styled export text need not equal ASR text.
No alignment, projection, migration, serialization or cache mutation runs here.

cue_index is zero-based in the supplied scope. Issue reasons contain neither
subtitle text nor filesystem paths. Callers decide presentation and recovery;
this module never repairs or silently omits a cue.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    reason: str
    cue_id: str = ""
    cue_index: int | None = None
    source_ref: str = ""
    stage: str = "studio"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[ValidationIssue, ...] = ()
    warnings: tuple[ValidationIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "errors": [issue.to_dict() for issue in self.errors],
                "warnings": [issue.to_dict() for issue in self.warnings]}



class SubtitleConsistencyError(ValueError):
    """A boundary refused the candidate; its current text remains untouched."""
    def __init__(self, result: ValidationResult):
        self.result = result
        first = result.errors[0] if result.errors else None
        location = f"第 {first.cue_index + 1} 条字幕：" if first and first.cue_index is not None else ""
        super().__init__(location + (first.reason if first else "字幕数据未通过检查。"))


def _get(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)


def _mapping(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> bool:
    return isinstance(value, (list, tuple))


def _millisecond(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value) and value == int(value) and abs(value) < 2**53
    except (OverflowError, ValueError):
        return False


def _interval(start: Any, end: Any) -> bool:
    return _millisecond(start) and _millisecond(end) and 0 <= start < end


def _source_id(cue_id: str, canonical: Mapping) -> str:
    # Match an independent caption before interpreting legacy projection suffixes.
    if cue_id in canonical:
        return cue_id
    if cue_id.endswith("#tr") and cue_id[:-3] in canonical:
        return cue_id[:-3]
    return cue_id.split("#", 1)[0]


def word_receipt_problem(receipt: Mapping, text: str) -> tuple[str, str] | None:
    """Cheap local safety check; never realigns text or writes to the receipt."""
    if (receipt.get("word_alignment") == "downloaded_sentence_or_segment_start"
            and receipt.get("words") == [] and isinstance(text, str)):
        if receipt.get("segment_anchors") and receipt.get("anchor_base_text") != text:
            return ("stale_subtitle_anchors", "当前文字与原始片段起点不一致；保留句级时间，需要更细切分时重新对齐。")
        # A sentence-only import never had word indexes to invalidate.
        return None
    if not isinstance(text, str) or receipt.get("text", text) != text:
        return ("stale_word_alignment",
                "人工修改后的文字与旧字级记录不同；保留当前文字及句级时间。")
    words = receipt.get("words", ())
    if not _sequence(words):
        return ("word_structure_invalid", "旧字级记录结构无效；句级字幕仍可使用。")
    previous_char = previous_start = -1
    for word in words:
        if (not isinstance(word, Mapping) or not isinstance(word.get("text"), str)
                or not isinstance(word.get("evidence_ref"), str)):
            return ("word_structure_invalid", "旧字级记录结构无效；句级字幕仍可使用。")
        start, end = word.get("start_ms"), word.get("end_ms")
        lo, hi = word.get("char_start"), word.get("char_end")
        if not _interval(start, end) or start < previous_start:
            return ("word_time_invalid", "旧字级时间无效或顺序不一致；保留可信句级时间。")
        if (not _millisecond(lo) or not _millisecond(hi)
                or not 0 <= lo < hi <= len(text) or lo < previous_char):
            return ("word_index_invalid", "旧字级索引超出当前文字或顺序不一致；需更新字级对齐。")
        # Stored AlignedWord text uses the alignment module's documented
        # punctuation/space/case/script normalization. This is not an AI
        # source-coverage rule, and the exact receipt.text equality above stays.
        from ..recognition.cue_word_alignment import normalized_content
        if normalized_content(text[int(lo):int(hi)]) != normalized_content(word["text"]):
            return ("word_text_mismatch", "旧字级文字与对应位置不一致；需更新字级对齐。")
        previous_char, previous_start = hi, start
    return None


def _evidence_word_problem(row: Mapping) -> tuple[str, str] | None:
    # JSON consumes the acoustic stream first, even for an implicit cue-align
    # row absent from cue.evidence_refs. Validate that exact stream once/ref.
    arbitration = row.get("caption_arbitration") or {}
    if not isinstance(arbitration, Mapping):
        return ("source_word_structure_invalid", "来源中的旧字级记录结构无效；句级字幕仍可使用。")
    words = arbitration.get("acoustic_words") or row.get("words") or ()
    if not _sequence(words):
        return ("source_word_structure_invalid", "来源中的旧字级记录结构无效；句级字幕仍可使用。")
    previous_start = previous_char = -1
    source_text = row.get("text")
    for word in words:
        if not isinstance(word, Mapping) or not isinstance(word.get("text"), str):
            return ("source_word_structure_invalid", "来源中的旧字级记录结构无效；句级字幕仍可使用。")
        try:
            raw_start = word.get("start_ms", word.get("start"))
            raw_end = word.get("end_ms", word.get("end"))
            numeric = all(isinstance(value, (int, float)) and not isinstance(value, bool)
                          for value in (raw_start, raw_end))
            start = raw_start if "start_ms" in word else raw_start * 1000
            end = raw_end if "end_ms" in word else raw_end * 1000
            valid = (numeric and math.isfinite(start) and math.isfinite(end)
                     and 0 <= start < end < 2**53 and start >= previous_start)
        except (TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            return ("source_word_time_invalid", "来源中的旧字级时间无效；保留当前句级时间。")
        if "char_start" in word or "char_end" in word:
            lo, hi = word.get("char_start"), word.get("char_end")
            if (not isinstance(source_text, str) or not _millisecond(lo) or not _millisecond(hi)
                    or not 0 <= lo < hi <= len(source_text) or lo < previous_char):
                return ("source_word_index_invalid", "来源中的旧字级索引无效；需更新字级对齐。")
            from ..recognition.cue_word_alignment import normalized_content
            if normalized_content(source_text[int(lo):int(hi)]) != normalized_content(word["text"]):
                return ("source_word_text_mismatch", "来源中的旧字级文字与对应位置不一致；需更新字级对齐。")
            previous_char = hi
        previous_start = start
    return None


def _validate(project: Any, cues: Iterable[Any], *, stage: str, export_view: bool) -> ValidationResult:
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    if project is None:
        return ValidationResult((ValidationIssue(
            "project_missing", "没有可检查的字幕工程。", stage=stage),))
    canonical_rows = _get(project, "cues", ())
    if not _sequence(canonical_rows):
        return ValidationResult((ValidationIssue(
            "cues_structure_invalid", "字幕列表的结构无效；原工程未修改。", stage=stage),))
    canonical = {_get(cue, "id"): cue for cue in canonical_rows if isinstance(_get(cue, "id"), str)}
    speakers = _get(project, "speakers", ())
    speaker_ids = {_get(speaker, "id") for speaker in speakers
                   if isinstance(_get(speaker, "id"), str)} if _sequence(speakers) else set()
    evidence = _mapping(_get(project, "asr_evidence", {}))
    state = _mapping(_get(project, "studio_state", {}))
    timeline_value = state.get("caption_timeline")
    timeline = _mapping(timeline_value)
    receipts_value = timeline.get("instances", {})
    receipts = _mapping(receipts_value)
    archive = timeline.get("source_archive", ())
    archive_ids = {_get(row, "id") for row in archive
                   if isinstance(_get(row, "id"), str)} if _sequence(archive) else set()
    if not export_view and timeline_value is not None and (not isinstance(timeline_value, Mapping)
                                      or not isinstance(receipts_value, Mapping)
                                      or not _sequence(archive)):
        errors.append(ValidationIssue("caption_timeline_structure_invalid",
                                      "字幕来源收据的结构无效；原工程未修改。", stage=stage))
    evidence_problems = {}
    seen: set[str] = set()
    for index, cue in enumerate(cues):
        raw_id = _get(cue, "id", "")
        cue_id = raw_id if isinstance(raw_id, str) else ""
        def issue(code: str, reason: str, source_ref: str = "", *, warning: bool = False) -> None:
            (warnings if warning else errors).append(
                ValidationIssue(code, reason, cue_id, index, source_ref, stage))
        if not cue_id.strip():
            issue("cue_id_invalid", "字幕缺少有效编号。")
        elif cue_id in seen:
            issue("cue_id_duplicate", "同一范围内出现重复字幕编号。")
        seen.add(cue_id)
        if not _interval(_get(cue, "start_ms"), _get(cue, "end_ms")):
            issue("sentence_time_invalid", "句级时间必须是有限的整数毫秒，且结束晚于非负起点。")
        if not isinstance(_get(cue, "text"), str):
            issue("cue_text_invalid", "当前字幕文字不是字符串。")
        speaker_id = _get(cue, "speaker_id", "S00")
        if not isinstance(speaker_id, str) or not speaker_id.strip():
            issue("speaker_id_invalid", "字幕缺少有效的说话人编号。")
        elif speaker_ids and speaker_id not in speaker_ids:
            issue("speaker_reference_missing", "字幕引用的说话人不在工程名册中。", speaker_id)
        # Empty legacy rosters are legal; cue-local IDs still preserve tracks.
        source_id = _source_id(cue_id, canonical)
        if export_view and source_id not in canonical:
            issue("export_source_missing", "导出字幕无法对应当前工程中的字幕。", source_id)
        # The export layer may legitimately contain translated/styled text. Its
        # alignment belongs to the canonical current caption, not that display.
        owner = canonical.get(source_id, cue) if export_view else cue
        if export_view and _get(owner, "speaker_id", "S00") != speaker_id:
            issue("export_speaker_mismatch", "导出字幕的说话人与当前工程字幕不一致。", source_id)
        owner_id = str(_get(owner, "id", cue_id) or cue_id)
        checked_word_refs: set[str] = set()
        def check_source_words(ref: str, row: Mapping) -> None:
            if ref in checked_word_refs:
                return
            checked_word_refs.add(ref)
            if ref not in evidence_problems:
                evidence_problems[ref] = _evidence_word_problem(row)
            if evidence_problems[ref]:
                issue(*evidence_problems[ref], source_ref=ref, warning=True)

        refs = _get(owner, "evidence_refs", ())
        if not _sequence(refs):
            issue("source_references_invalid", "字幕的来源引用列表结构无效。")
        else:
            for ref in refs:
                if not isinstance(ref, str) or not ref:
                    issue("source_reference_invalid", "字幕包含无效的来源引用。")
                elif ref not in evidence:
                    issue("source_reference_missing", "字幕引用的来源证据不存在。", ref)
                elif not isinstance(evidence[ref], Mapping):
                    issue("source_evidence_invalid", "字幕引用的来源证据结构无效。", ref)
                else:
                    check_source_words(ref, evidence[ref])
        # Optional forced-alignment rows are also read by JSON without refs.
        # Only inspect this cue's candidates, never unrelated or hidden tracks.
        for key in dict.fromkeys((cue_id, owner_id, cue_id.split("#", 1)[0])):
            ref = "cue-align:" + key
            row = evidence.get(ref)
            if not isinstance(row, Mapping) or not isinstance(row.get("cue_alignment"), Mapping):
                continue
            check_source_words(ref, row)
            expected_text = _get(cue if key == cue_id and cue_id != owner_id else owner, "text", "")
            if row.get("text") != expected_text:
                issue("source_word_alignment_stale",
                      "当前文字与旧逐句对齐来源不同；保留人工文字及句级时间。",
                      ref, warning=True)
        if export_view and timeline_value is not None and (
                not isinstance(timeline_value, Mapping) or not isinstance(receipts_value, Mapping)):
            issue("caption_receipts_unavailable", "旧字级来源收据不可用；仅按当前文字和句级时间导出。",
                  warning=True)
        receipt = receipts.get(owner_id)
        if receipt is None:
            continue  # Manually created/imported captions need no ASR receipt.
        if not isinstance(receipt, Mapping):
            issue("caption_receipt_invalid", "这条字幕的来源收据结构无效。")
            continue
        parents = receipt.get("source_cue_ids")
        if parents is None:
            parents = [receipt["source_cue_id"]] if receipt.get("source_cue_id") else []
        if not _sequence(parents):
            issue("caption_source_invalid", "字幕的原始字幕引用结构无效。")
        elif archive_ids:
            for parent in parents:
                if not isinstance(parent, str) or parent not in archive_ids:
                    issue("caption_source_missing", "字幕引用的原始字幕不在保存的来源快照中。",
                          parent if isinstance(parent, str) else "")
        elif parents:
            issue("source_archive_unavailable", "旧工程未保存来源快照；无法核对原始字幕归属。",
                  warning=True)
        problem = word_receipt_problem(receipt, _get(owner, "text", ""))
        if problem:
            issue(*problem, warning=True)
        else:
            for word in receipt.get("words", ()):
                ref = word.get("evidence_ref", "")
                if ref and ref not in evidence and not ref.startswith("term:"):
                    issue("word_source_missing", "旧字级记录的来源不可用；句级字幕仍可使用。",
                          ref, warning=True)
                    break
    return ValidationResult(tuple(errors), tuple(warnings))


def validate_project(project: Any, *, stage: str = "studio") -> ValidationResult:
    """Inspect committed current captions; no ASR-text equality or repairs."""
    cues = _get(project, "cues", ())
    return _validate(project, cues if _sequence(cues) else (), stage=stage, export_view=False)


def validate_export_view(project: Any, cues: Iterable[Any], *, stage: str = "export") -> ValidationResult:
    """Inspect only the supplied current timeline/language/speaker export scope.

    This does not compute the scope or compare it to the original ASR cue set.
    Word warnings do not make ok false for sentence-level SRT.
    """
    return _validate(project, cues, stage=stage, export_view=True)

