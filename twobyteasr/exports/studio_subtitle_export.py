"""Speaker-aware subtitle artifact export with parser-backed verification."""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from ..rendering.ass_compiler import compile_ass, compile_txt, escape_ass_text
from ..projects.studio_project import StudioCue, SubtitleProject
from .srt_codec import _SRT_BLOCK, normalize_srt_text, parse_srt, parse_srt_time as _parse_srt_time
from .export_consistency import require_consistent_view, SubtitleDataError
from ..projects.subtitle_consistency import validate_export_view, ValidationResult


SUPPORTED_SUBTITLE_FORMATS = frozenset({"srt", "ass", "txt", "json"})
SPEAKER_EXPORT_MODES = frozenset({"combined", "per_speaker", "both"})


@dataclass(frozen=True)
class SubtitleExportOptions:
    formats: frozenset[str] = frozenset({"srt"})
    speaker_mode: str = "combined"

    def validate(self) -> None:
        if not self.formats or not self.formats <= SUPPORTED_SUBTITLE_FORMATS:
            raise ValueError("select at least one supported subtitle format")
        if self.speaker_mode not in SPEAKER_EXPORT_MODES:
            raise ValueError("unsupported speaker export mode")


@dataclass(frozen=True)
class SubtitleExportArtifact:
    path: Path
    format: str
    speaker_id: str
    cue_count: int


class SubtitlePublicationError(OSError):
    """A filesystem failure after validation, with an exact partial receipt."""
    def __init__(self, target, published, cause):
        self.published = tuple(published)
        self.failed_path = target
        names = "、".join(a.path.name for a in published) or "无"
        super().__init__(f"发布失败：{target.name}；已发布 {len(published)} 个文件（{names}）。未发布目标保留原文件。{cause}")


@dataclass(frozen=True)
class ArtifactVerification:
    path: Path
    format: str
    cue_count: int
    timestamps_valid: bool
    speaker_mapping_valid: bool
    unicode_valid: bool
    expected_cue_count: int = 0
    count_valid: bool = True
    structure_valid: bool = True
    first_mismatch: dict | None = None
    speaker_check: str = "source_scope"  # SRT/TXT carry no embedded speaker IDs.

    @property
    def valid(self) -> bool:
        return all((
            self.timestamps_valid,
            self.speaker_mapping_valid,
            self.unicode_valid,
            self.count_valid,
            self.structure_valid,
        ))


class SubtitleVerificationError(RuntimeError):
    """Actionable summary plus explicit, local-only source/read-back evidence."""

    def __init__(self, target: Path, speaker_id: str, verification: ArtifactVerification):
        self.failed_path = target
        self.verification = verification
        mismatch = verification.first_mismatch or {}
        scope = speaker_id or "合并字幕"
        number = mismatch.get("subtitle_number")
        location = f"{scope} 第 {number} 条字幕" if number else scope
        reason = mismatch.get("reason", "字幕条数核对不一致")
        super().__init__(f"{location}在导出后{reason}；未发布本批文件，原有文件保留。")

    def details(self) -> str:
        data = asdict(self.verification)
        data["path"] = str(self.failed_path)
        data["privacy"] = "此详情可能含字幕原文，仅保留在本机；请自行决定是否提供。"
        data["speaker_check_note"] = (
            "SRT/TXT 不含说话人字段；核对来源 cue 与目标分轨的归属。"
            if self.verification.speaker_check == "source_scope" else "核对文件内的说话人字段。")
        return json.dumps(data, ensure_ascii=False, indent=2)


def _srt_timestamp(milliseconds: int) -> str:
    value = max(0, int(milliseconds))
    hours, remainder = divmod(value, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def compile_srt(cues: Iterable[StudioCue]) -> str:
    ordered = sorted(cues, key=lambda item: (item.start_ms, item.end_ms, item.id))
    blocks = []
    for index, cue in enumerate(ordered, 1):
        text = normalize_srt_text(cue.text)
        blocks.append(
            f"{index}\n{_srt_timestamp(cue.start_ms)} --> {_srt_timestamp(cue.end_ms)}\n{text}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _speaker_filename(value: str) -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(value or "").strip())
    clean = re.sub(r"\s+", "_", clean).strip(" ._")[:80]
    if not clean or clean.casefold() in {
        "con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }:
        clean = "unknown"
    return clean


def _project_for_cues(project: SubtitleProject, cues: Iterable[StudioCue]) -> SubtitleProject:
    subset = copy.deepcopy(project)
    subset.cues = copy.deepcopy(list(cues))
    # Studio's legacy validate() coerces scalar fields and filters references.
    # Check the original snapshot first so it cannot hide invalid input. Only
    # intrinsic cue errors must be checked before projection (bad intervals
    # could otherwise disappear as "outside the edit"). Source receipts are
    # checked for the actual current sequence, not an unrelated source tail.
    raw = validate_export_view(subset, subset.cues, stage="export")
    intrinsic = {"cue_id_invalid", "cue_id_duplicate", "sentence_time_invalid",
                 "cue_text_invalid", "speaker_id_invalid", "speaker_reference_missing"}
    errors = tuple(issue for issue in raw.errors if issue.code in intrinsic)
    if errors:
        raise SubtitleDataError(ValidationResult(errors=errors))
    view = _export_view_cues(subset, styled=False)
    require_consistent_view(subset, view)
    subset.validate()
    return subset


def _export_view_cues(project: SubtitleProject, *, styled: bool = True):
    """导出口径=当前活动序列的 timeline 域投影（2026-09-19 P0）。

    剪辑模式导出的是这段剪辑（序列时间从 00:00 起）；完整录播导出全集。
    project.cues 永远保持全集+源时间，不因导出被改写。
    2026-10-13：文字按工程的标点选择（保留原文 / 添加标点 / 不加标点）输出；
    ``styled=False`` 给出原稿（JSON 的 original_text 与字级时间用它）。
    """
    from ..timeline.studio_edit_sequence import projected_cues

    view = projected_cues(project, domain="timeline")
    if not styled:
        return view
    from ..subtitle_rules.punctuation_style import style_cues
    return style_cues(project, view)


def _lookup_translation(view: dict, cue_id: str) -> dict | None:
    """A view cue's translation info (projected ids fall back to their source cue)."""
    from ..caption_style.bilingual_layout import translation_for_cue
    return translation_for_cue(view, cue_id)


def _word_piece(word: dict, enrich: dict | None, basis: str) -> dict:
    enrich = enrich or {}
    start_basis = enrich.get("start_basis") or ""
    end_basis = enrich.get("end_basis") or ""
    piece_basis = (start_basis if start_basis == end_basis else f"{start_basis}|{end_basis}") if (
        start_basis or end_basis) else basis
    piece = {
        "text": str(word.get("text") or ""),
        "start_ms": int(word["start_ms"]),
        "end_ms": int(word["end_ms"]),
        "granularity": str(enrich.get("granularity") or word.get("granularity") or "word"),
        "basis": str(piece_basis or ""),
    }
    for key in ("char_start", "char_end"):
        if word.get(key) is not None:
            piece[key] = int(word[key])
    if start_basis or end_basis:
        piece["start_basis"], piece["end_basis"] = start_basis, end_basis
    return piece


def _json_word_timing(project: SubtitleProject, cue: StudioCue, cues_by_id: dict | None = None) -> dict:
    """Measured Japanese word pieces of an export cue, in the export clock.

    Sources: an independent caption's receipt words (already project/export
    time) or the cue's own ``cue-align:`` forced-alignment row (audio clock,
    projected into the export clock like ``cue_words`` does). Only used when
    the evidence belongs to the cue's current text; nothing is estimated.
    """
    from ..recognition.cue_forced_alignment import CUE_ALIGNMENT_PREFIX, is_cue_alignment_row
    from ..recognition.cue_word_alignment import MEASURED_ALIGNMENTS
    from ..timeline.studio_edit_sequence import source_cue_id_of

    empty = {"source": "", "basis": "", "pieces": []}
    source_id = source_cue_id_of(cue.id)
    row = None
    for key in dict.fromkeys((cue.id, source_id)):
        candidate = project.asr_evidence.get(CUE_ALIGNMENT_PREFIX + key)
        if is_cue_alignment_row(candidate):
            row = candidate
            break
    row_pieces = []
    if row is not None and str(row.get("text") or "") == cue.text:
        arbitration = row.get("caption_arbitration") or {}
        row_pieces = [dict(item) for item in (arbitration.get("acoustic_words") or row.get("words") or ())
                      if isinstance(item, dict) and "start_ms" in item and "end_ms" in item]
    by_span = {
        (int(item["char_start"]), int(item["char_end"])): item
        for item in row_pieces if item.get("char_start") is not None and item.get("char_end") is not None
    }
    instances = (project.studio_state.get("caption_timeline") or {}).get("instances") or {}
    receipt = instances.get(cue.id) if isinstance(instances, dict) else None
    if (project.render_settings.get("_cue_domain") == "timeline" and isinstance(receipt, dict)
            and receipt.get("text") == cue.text and receipt.get("words")
            and receipt.get("word_alignment", "exact_token_text") in MEASURED_ALIGNMENTS):
        basis = str(receipt.get("word_alignment") or "exact_token_text")
        pieces = [
            _word_piece(word, by_span.get((word.get("char_start"), word.get("char_end"))), basis)
            for word in receipt["words"] if isinstance(word, dict) and "start_ms" in word and "end_ms" in word
        ]
        return {"source": "caption_receipt", "basis": basis, "pieces": pieces}
    if not row_pieces:
        return empty
    if cues_by_id is None:
        cues_by_id = {item.id: item for item in project.cues}
    canonical = cues_by_id.get(source_id)
    if canonical is None:
        return empty
    basis = "cue_forced_alignment"
    if cue.id == canonical.id and (cue.start_ms, cue.end_ms) == (canonical.start_ms, canonical.end_ms):
        return {"source": "cue_alignment", "basis": basis,
                "pieces": [_word_piece(item, item, basis) for item in row_pieces]}
    from ..timeline.studio_edit_sequence import projected_cues

    pieces = []
    for item in row_pieces:
        token = copy.deepcopy(canonical)
        token.start_ms, token.end_ms = int(item["start_ms"]), int(item["end_ms"])
        view = copy.copy(project)
        view.cues = [token]
        mapped = [entry for entry in projected_cues(view, min_visible_ms=1) if entry.id == cue.id]
        if len(mapped) == 1:
            pieces.append(_word_piece({**item, "start_ms": mapped[0].start_ms, "end_ms": mapped[0].end_ms},
                                      item, basis))
    return {"source": "cue_alignment", "basis": basis, "pieces": pieces}


def _safe_word_timing(project: SubtitleProject, cue: StudioCue, cues_by_id: dict | None = None) -> dict:
    try:
        return _json_word_timing(project, cue, cues_by_id)
    except Exception as exc:  # noqa: BLE001 - optional evidence never blocks export
        return {"source": "", "basis": f"unavailable:{type(exc).__name__}", "pieces": []}


def _compile_json(project: SubtitleProject) -> str:
    from ..caption_style.speaker_names import enabled as names_enabled, prefix as speaker_prefix
    from ..subtitle_rules.language_rules import project_language
    from ..subtitle_rules.punctuation_style import math_enabled, project_mode, protected_terms_of, style_text, style_translation
    from ..subtitle_rules.subtitle_translation import container_target, translation_view

    speakers = {speaker.id: speaker.name for speaker in project.speakers}
    target = container_target(project)
    translations = translation_view(project)
    untranslated = {"text": "", "status": "untranslated", "origin": "", "target": target}
    cues_by_id = {item.id: item for item in project.cues}
    mode = project_mode(project)
    math = math_enabled(project)
    language = project_language(project) or ""
    terms = protected_terms_of(project)
    rows = []
    raw_view = sorted(_export_view_cues(project, styled=False), key=lambda item: (item.start_ms, item.end_ms, item.id))
    consistency = require_consistent_view(project, raw_view)
    unavailable_words = {}
    for issue in consistency.warnings:
        if issue.code == "stale_word_alignment" or issue.code.startswith(("word_", "source_word_")):
            unavailable_words.setdefault(issue.cue_id, []).append(issue.code)
    for cue in raw_view:
        info = _lookup_translation(translations, cue.id) or untranslated
        speaker_name = speakers.get(cue.speaker_id, cue.speaker_id)
        styled = style_text(cue.text, mode, language=language, protected_terms=terms, math=math)
        word_timing = ({"source": "", "basis": "unavailable:" + ",".join(unavailable_words[cue.id]), "pieces": []}
                       if cue.id in unavailable_words else _safe_word_timing(project, cue, cues_by_id))
        if styled.changed:
            # Word pieces index the manuscript (original_text); give the
            # positions in the exported text too.
            for piece in word_timing.get("pieces") or ():
                start, end = piece.get("char_start"), piece.get("char_end")
                if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(styled.index_map):
                    mapped = [value for value in styled.index_map[start:end] if value is not None]
                    if mapped:
                        piece["text_char_start"], piece["text_char_end"] = mapped[0], mapped[-1] + 1
        translation = {key: info.get(key, "") for key in ("text", "status", "origin", "target")}
        translation["text"] = style_translation(translation["text"], mode, math=math)
        rows.append({
            "id": cue.id,
            "start_ms": cue.start_ms,
            "end_ms": cue.end_ms,
            "text": styled.text,
            "display_text": (speaker_prefix(cue.speaker_id, project.speakers)
                             if names_enabled(project.studio_state) and styled.text.strip() else '') + styled.text,
            "speaker_id": cue.speaker_id,
            "speaker_name": speaker_name,
            "style_id": cue.style_id,
            # Bilingual additions (2026-10-12); the keys above are unchanged.
            # original_text is the manuscript; text follows the punctuation choice.
            "original_text": cue.text,
            "duration_ms": cue.end_ms - cue.start_ms,
            "speaker": {"id": cue.speaker_id, "name": speaker_name},
            "translation": translation,
            "word_timing": word_timing,
        })
    payload = {
        "schema_version": 1,
        "kind": "2byteasr-subtitle-export",
        "project_id": project.project_id,
        "original_language": language,
        "translation_target": target,
        "punctuation": mode,
        "show_speaker_names": names_enabled(project.studio_state),
        "cues": rows,
    }
    if math:
        # 2026-10-16 (ADR 0124): text shows $…$ formulas as Unicode; original_text keeps the LaTeX.
        payload["math_formulas"] = True
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _display_text_cues(project: SubtitleProject):
    """Plain exports follow the visible language mode, retaining untranslated cues."""
    from ..caption_style.bilingual_layout import settings_from_state
    from ..subtitle_rules.subtitle_translation import translation_view
    from ..subtitle_rules.punctuation_style import math_enabled, project_mode, style_translation
    view = _export_view_cues(project)
    from ..caption_style.speaker_names import display_text_cues
    settings = settings_from_state(project.studio_state)
    if settings.mode == "original":
        return display_text_cues(project, view)
    translations = {key: dict(info, text=style_translation(info.get("text", ""),
                    project_mode(project), math=math_enabled(project)))
                    for key, info in translation_view(project).items()}
    result, missing, _ = layer_cues(view, translations, settings.mode,
                                   translation_first=settings.order == "translation_first")
    if settings.mode == "translation":
        missing_ids = set(missing)
        result.extend(c for c in view if c.id in missing_ids)
    return display_text_cues(project, sorted(result, key=lambda c: (c.start_ms, c.end_ms, c.id)))


def _compile_format(project: SubtitleProject, format_name: str) -> str:
    view = _export_view_cues(project)
    if format_name == "srt":
        return compile_srt(_display_text_cues(project))
    if format_name == "ass":
        return compile_ass(project, cues=view)
    if format_name == "txt":
        return compile_txt(project, cues=_display_text_cues(project))
    if format_name == "json":
        return _compile_json(project)
    raise ValueError(f"unsupported subtitle format: {format_name}")


def _atomic_text_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


from ..diagnostics.event_bridge import service_boundary


@service_boundary("subtitle.export")
def export_subtitle_artifacts(
    project: SubtitleProject,
    directory: str | os.PathLike[str],
    base_name: str,
    options: SubtitleExportOptions,
) -> tuple[SubtitleExportArtifact, ...]:
    project = copy.deepcopy(project)
    options.validate()
    target_dir = Path(directory).resolve()
    # The base is shared with video naming. Speaker-label normalization would
    # replace intentional spaces and truncate a long confirmed affix/base.
    from .export_preferences import output_basename
    stem = output_basename(base_name or 'subtitles')
    artifacts: list[SubtitleExportArtifact] = []
    # 三十八轮：被隐藏的说话人轨不进成片/导出（编辑器内仍可见可改）。
    visible_cues = project.visible_cues()
    scopes: list[tuple[str, SubtitleProject, str]] = []
    if options.speaker_mode in {"combined", "both"}:
        scopes.append(("", _project_for_cues(project, visible_cues), stem))
    if options.speaker_mode in {"per_speaker", "both"}:
        speaker_ids = list(dict.fromkeys(cue.speaker_id for cue in visible_cues))
        used_names: set[str] = set()
        for speaker_id in speaker_ids:
            mapping = {speaker.id: speaker.name for speaker in project.speakers}
            label = _speaker_filename(mapping.get(speaker_id, speaker_id))
            original_label, suffix = label, 2
            while label.casefold() in used_names:
                label = f"{original_label}_{suffix}"
                suffix += 1
            used_names.add(label.casefold())
            cues = [cue for cue in project.cues if cue.speaker_id == speaker_id]
            scopes.append((speaker_id, _project_for_cues(project, cues), f"{stem}_{label}"))
    target_dir.mkdir(parents=True, exist_ok=True)
    # All candidates use the destination filesystem and pass read-back before
    # any existing user file is replaced. Multi-file rename is not atomic:
    # a later locked target produces an explicit partial-publication receipt.
    with tempfile.TemporaryDirectory(prefix=".subtitle-export-", dir=target_dir, ignore_cleanup_errors=True) as stage:
        pending = []
        for speaker_id, scoped_project, scoped_stem in scopes:
            for format_name in sorted(options.formats):
                target = target_dir / f"{scoped_stem}.{format_name}"
                candidate = Path(stage) / target.name
                expected = copy.copy(scoped_project)
                expected.cues = _export_view_cues(scoped_project)
                if format_name in {"srt", "txt"}:
                    expected.cues = _display_text_cues(scoped_project)
                elif format_name == "ass":
                    from ..caption_style.bilingual_layout import project_display_cues
                    expected.cues = project_display_cues(scoped_project, expected.cues)
                require_consistent_view(scoped_project, expected.cues, speaker_id=speaker_id)
                _atomic_text_write(candidate, _compile_format(scoped_project, format_name))
                artifact = SubtitleExportArtifact(candidate, format_name, speaker_id, len(expected.cues))
                verification = verify_subtitle_artifact(artifact, expected)
                count_invalid = (
                    verification.cue_count < artifact.cue_count
                    if format_name == "ass"
                    else verification.cue_count != artifact.cue_count
                )
                if not verification.valid or count_invalid:
                    raise SubtitleVerificationError(target, speaker_id, verification)
                pending.append((candidate, SubtitleExportArtifact(target, format_name, speaker_id, len(expected.cues))))
        for candidate, artifact in pending:
            try:
                os.replace(candidate, artifact.path)
            except OSError as exc:
                raise SubtitlePublicationError(artifact.path, artifacts, exc) from exc
            artifacts.append(artifact)
    return tuple(artifacts)


def _ass_visible_text(text: str) -> str:
    """Decode visible ASS text once, without treating escaped literals as tags."""
    text = re.sub(r"\{[^}]*\}", "", text)
    escapes = {r"\\": "\\", r"\N": "\n", r"\n": "\n", r"\h": " "}
    return re.sub(r"\\\\|\\[Nnh]", lambda match: escapes[match.group()], text)


@service_boundary("subtitle.export_readback")
def verify_subtitle_artifact(
    artifact: SubtitleExportArtifact,
    expected_project: SubtitleProject,
) -> ArtifactVerification:
    content = artifact.path.read_text(encoding="utf-8")
    expected = sorted(expected_project.cues, key=lambda item: (item.start_ms, item.end_ms, item.id))
    timestamps_valid = True
    speaker_mapping_valid = True
    unicode_valid = True
    cue_count = 0
    structure_valid = True
    mismatches = []
    def mismatch(index, field, reason, actual=None):
        cue = expected[index - 1] if index <= len(expected) else None
        mismatches.append({"cue_id": cue.id if cue else None, "subtitle_number": index,
                           "field": field, "reason": reason,
                           "expected": asdict(cue) if cue else None, "actual": actual})
    if artifact.format == "srt":
        rows, errors = parse_srt(content)
        cue_count = len(rows)
        timestamps_valid = unicode_valid = cue_count == len(expected)
        structure_valid = not errors
        for index, (row, cue) in enumerate(zip(rows, expected), 1):
            if (row.start_ms, row.end_ms) != (cue.start_ms, cue.end_ms):
                timestamps_valid = False
                mismatch(index, "timestamps", "时间戳核对不一致", asdict(row))
            if row.text != normalize_srt_text(cue.text):
                unicode_valid = False
                mismatch(index, "text", "文字核对不一致", asdict(row))
        for index, cue in enumerate(expected, 1):
            if artifact.speaker_id and cue.speaker_id != artifact.speaker_id:
                speaker_mapping_valid = False
                mismatch(index, "speaker", "说话人归属核对不一致", {"speaker_id": artifact.speaker_id})
        for index, reason in errors:
            mismatch(index, "structure", reason, asdict(rows[index - 1]) if index <= len(rows) else None)
    elif artifact.format == "ass":
        rows = [line for line in content.splitlines() if line.startswith("Dialogue:")]
        cue_count = len(rows)
        timestamps_valid = cue_count >= len(expected)
        speaker_mapping_valid = all(
            any(f",{cue.speaker_id}," in row for row in rows) for cue in expected
        )
        # Automatic layout inserts ASS line breaks into long subtitles. Keep
        # every source character and explicit newline required, while allowing
        # additional visual breaks; text inside override tags is not evidence.
        from ..caption_style.caption_text_layout import normalized_caption_text
        visible = [_ass_visible_text(row.split(",", 9)[-1]) for row in rows]
        for index, cue in enumerate(expected, 1):
            source = normalized_caption_text(cue.text).replace("{", "｛").replace("}", "｝")
            # A hard space is still the source space. Added visual newlines
            # are allowed between characters, while source newlines remain
            # required. Never combine separate Dialogue rows into evidence.
            pattern = r"\n*".join(re.escape(char) for char in source)
            if not any(re.search(pattern, row) for row in visible):
                unicode_valid = False
                mismatch(index, "text", "ASS 可见文字核对不一致")
    elif artifact.format == "txt":
        # TXT stores one LF-delimited row per cue; U+2028/U+2029 are text.
        rows = content.removesuffix("\n").split("\n") if content else []
        cue_count = len(rows)
        timestamps_valid = cue_count == len(expected)
        speaker_mapping_valid = all(
            not artifact.speaker_id or cue.speaker_id == artifact.speaker_id for cue in expected
        )
        unicode_valid = cue_count == len(expected)
        for index, (cue, row) in enumerate(zip(expected, rows), 1):
            if cue.text.replace("\r", " ").replace("\n", " ") != row:
                unicode_valid = False
                mismatch(index, "text", "文字核对不一致", {"text": row})
            if artifact.speaker_id and cue.speaker_id != artifact.speaker_id:
                mismatch(index, "speaker", "说话人归属核对不一致", {"speaker_id": artifact.speaker_id})
    elif artifact.format == "json":
        try:
            payload = json.loads(content)
        except ValueError as exc:
            payload = None
            structure_valid = False
            mismatch(1, "structure", "JSON 文件无法完整解析", {"error": str(exc)})
        rows = payload.get("cues") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            if structure_valid:
                mismatch(1, "structure", "JSON 文件缺少有效字幕列表", {"type": type(rows).__name__})
            structure_valid = False
            rows = []
        cue_count = len(rows)
        timestamps_valid = speaker_mapping_valid = unicode_valid = cue_count == len(expected)
        for index, (row, cue) in enumerate(zip(rows, expected), 1):
            if not isinstance(row, dict):
                structure_valid = False
                mismatch(index, "structure", "字幕记录不是对象", row)
                continue
            if any(type(row.get(key)) is not int or row[key] != getattr(cue, key) for key in ("start_ms", "end_ms")):
                timestamps_valid = False
                mismatch(index, "timestamps", "时间戳核对不一致", row)
            if row.get("text") != cue.text:
                unicode_valid = False
                mismatch(index, "text", "文字核对不一致", row)
            if row.get("speaker_id") != cue.speaker_id or (artifact.speaker_id and cue.speaker_id != artifact.speaker_id):
                speaker_mapping_valid = False
                mismatch(index, "speaker", "说话人归属核对不一致", row)
            if row.get("id") != cue.id:
                structure_valid = False
                mismatch(index, "cue_id", "字幕来源 ID 核对不一致", row)
    else:
        raise ValueError(f"unsupported subtitle format: {artifact.format}")
    count_valid = cue_count >= len(expected) if artifact.format == "ass" else cue_count == len(expected)
    if not count_valid:
        mismatch(min(cue_count, len(expected)) + 1, "count",
                 f"字幕条数核对不一致（预期 {len(expected)}，实际 {cue_count}）")
    if not mismatches and not all((timestamps_valid, speaker_mapping_valid, unicode_valid)):
        mismatch(1, "content", "文件内容核对不一致")
    return ArtifactVerification(
        artifact.path,
        artifact.format,
        cue_count,
        timestamps_valid,
        speaker_mapping_valid,
        unicode_valid,
        len(expected), count_valid, structure_valid,
        min(mismatches, key=lambda item: item["subtitle_number"]) if mismatches else None,
        "embedded" if artifact.format in {"json", "ass"} else "source_scope",
    )


# ---------------------------------------------------------------------------
# Language layers (2026-10-12): original / translation / bilingual SRT + JSON,
# never overwriting an existing file.

LANGUAGE_LAYERS = ("original", "translation", "bilingual")
SUPPORTED_LANGUAGE_LAYERS = frozenset({*LANGUAGE_LAYERS, "json"})


@dataclass(frozen=True)
class LanguageLayerArtifact:
    path: Path
    layer: str
    format: str
    speaker_id: str
    cue_count: int
    missing_translation_ids: tuple[str, ...] = ()
    needs_update_ids: tuple[str, ...] = ()

    @property
    def missing_translation_count(self) -> int:
        return len(self.missing_translation_ids)

    @property
    def needs_update_count(self) -> int:
        return len(self.needs_update_ids)


@dataclass(frozen=True)
class LanguageLayerExport:
    artifacts: tuple[LanguageLayerArtifact, ...]
    target: str
    original_suffix: str
    translation_suffix: str
    missing_translation_ids: tuple[str, ...] = ()
    needs_update_ids: tuple[str, ...] = ()

    @property
    def missing_translation_count(self) -> int:
        return len(self.missing_translation_ids)

    @property
    def needs_update_count(self) -> int:
        return len(self.needs_update_ids)


def _srt_lines(text: str) -> str:
    """Language layers use the same lossless wire normalization as plain SRT."""
    return normalize_srt_text(text)


def layer_cues(
    cues: Iterable[StudioCue],
    translations: dict,
    layer: str,
    *,
    translation_first: bool = True,
) -> tuple[list[StudioCue], tuple[str, ...], tuple[str, ...]]:
    """Cue copies carrying one language layer's text.

    Returns ``(cues, missing_translation_ids, needs_update_ids)``. The
    translation layer omits cues without translation; the bilingual layer
    keeps them as original-only. Outdated (needs_update) translations are
    included and reported.
    """
    if layer not in LANGUAGE_LAYERS:
        raise ValueError(f"unsupported language layer: {layer}")
    result, missing, stale = [], [], []
    for cue in sorted(cues, key=lambda item: (item.start_ms, item.end_ms, item.id)):
        original = _srt_lines(cue.text)
        info = _lookup_translation(translations, cue.id) or {}
        translated = _srt_lines(info.get("text", ""))
        if layer != "original":
            if not translated.strip():
                missing.append(cue.id)
            elif info.get("status") == "needs_update":
                stale.append(cue.id)
        if layer == "original":
            text = original
        elif layer == "translation":
            if not translated.strip():
                continue
            text = translated
        else:
            parts = [translated, original] if translation_first else [original, translated]
            text = "\n".join(part for part in parts if part)
        copied = copy.copy(cue)
        copied.text = text
        result.append(copied)
    return result, tuple(missing), tuple(stale)


def _translation_suffix(target: str) -> str:
    from ..subtitle_rules.subtitle_translation import TARGET_SUFFIX
    return TARGET_SUFFIX.get(target, "zh")


def has_translations(project: SubtitleProject) -> bool:
    """Read the canonical records too, even if the legacy render view is absent."""
    from ..subtitle_rules.subtitle_translation import translation_view
    return any(str(info.get("text") or "").strip() for info in translation_view(project).values())


def _layer_filename(scope_stem: str, layer: str, original_suffix: str, translation_suffix: str,
                    counter: int) -> str:
    stem = scope_stem if counter <= 1 else f"{scope_stem} ({counter})"
    if layer == "json":
        return f"{stem}.json"
    suffix = {"original": original_suffix, "translation": translation_suffix, "bilingual": "bilingual"}[layer]
    if layer == "translation" and original_suffix.casefold() == translation_suffix.casefold():
        suffix = "translation." + suffix
    return f"{stem}.{suffix}.srt"


def _publish_new(candidate: Path, target: Path) -> None:
    """Move a verified candidate to ``target``; fail if it exists (no overwrite)."""
    if os.name == "nt":
        os.rename(candidate, target)  # Windows rename never replaces an existing file.
        return
    os.link(candidate, target)
    os.unlink(candidate)


def export_language_layers(
    project: SubtitleProject,
    directory: str | os.PathLike[str],
    stem: str,
    layers: Iterable[str] = LANGUAGE_LAYERS,
    *,
    translation_first: bool = True,
    speaker_mode: str = "combined",
    target: str | None = None,
    original_suffix: str | None = None,
) -> LanguageLayerExport:
    """Export original / translation / bilingual SRT (and optional JSON).

    Names: ``{stem}.<source>.srt`` (``.ja`` / ``.zh`` / ``.en``),
    ``{stem}.<target>.srt`` (``.zh`` / ``.zh-Hant`` / ``.en`` / ``.ja`` / ``.ko``),
    ``{stem}.bilingual.srt``, ``{stem}.json``. Existing files are never
    replaced: when any planned name exists the whole set moves to
    ``{stem} (2).ja.srt`` etc. Every candidate is parsed back before
    publication. Translations come from the project's translation records
    (old projects: the legacy ``translations`` dict).
    """
    from .export_preferences import output_basename
    from ..subtitle_rules.language_rules import project_language
    from ..subtitle_rules.subtitle_translation import container_target, normalize_target, translation_view

    project = copy.deepcopy(project)
    layers = tuple(dict.fromkeys(str(layer) for layer in layers))
    if not layers or not set(layers) <= SUPPORTED_LANGUAGE_LAYERS:
        raise ValueError("select at least one supported language layer")
    if speaker_mode not in SPEAKER_EXPORT_MODES:
        raise ValueError("unsupported speaker export mode")
    resolved_target = normalize_target(target) if target else container_target(project)
    translations = translation_view(project, target=resolved_target if target else None)
    # A previous language's text is not a translation into the selected target.
    translations = {key: info for key, info in translations.items()
                    if str(info.get("target") or "").split("-", 1)[0] == resolved_target.split("-", 1)[0]}
    from ..subtitle_rules.punctuation_style import MODE_NONE, math_enabled, project_mode, style_translation
    math = math_enabled(project)
    if (project_mode(project) == MODE_NONE or math) and translations:
        # 不加标点 and math formulas apply to every layer; translations are copied, never rewritten.
        mode = project_mode(project)
        translations = {key: (dict(value, text=style_translation(value.get("text", ""), mode, math=math))
                              if isinstance(value, dict) else value)
                        for key, value in translations.items()}
    original_suffix = original_suffix or project_language(project) or "ja"
    translation_suffix = _translation_suffix(resolved_target)
    base = output_basename(stem or "subtitles")
    target_dir = Path(directory).resolve()
    visible_cues = project.visible_cues()
    scopes: list[tuple[str, SubtitleProject, str]] = []
    if speaker_mode in {"combined", "both"}:
        scopes.append(("", _project_for_cues(project, visible_cues), base))
    if speaker_mode in {"per_speaker", "both"}:
        mapping = {speaker.id: speaker.name for speaker in project.speakers}
        used_names: set[str] = set()
        for speaker_id in dict.fromkeys(cue.speaker_id for cue in visible_cues):
            label = _speaker_filename(mapping.get(speaker_id, speaker_id))
            original_label, suffix = label, 2
            while label.casefold() in used_names:
                label = f"{original_label}_{suffix}"
                suffix += 1
            used_names.add(label.casefold())
            cues = [cue for cue in visible_cues if cue.speaker_id == speaker_id]
            scopes.append((speaker_id, _project_for_cues(project, cues), f"{base}_{label}"))
    counter = 1
    while any((target_dir / _layer_filename(scope_stem, layer, original_suffix, translation_suffix, counter)).exists()
              for _sid, _scoped, scope_stem in scopes for layer in layers):
        counter += 1
    target_dir.mkdir(parents=True, exist_ok=True)
    published: list[LanguageLayerArtifact] = []
    all_missing: dict[str, None] = {}
    all_stale: dict[str, None] = {}
    with tempfile.TemporaryDirectory(prefix=".subtitle-layers-", dir=target_dir, ignore_cleanup_errors=True) as stage:
        pending: list[tuple[Path, LanguageLayerArtifact]] = []
        for speaker_id, scoped_project, scope_stem in scopes:
            view = _export_view_cues(scoped_project)
            for layer in layers:
                name = _layer_filename(scope_stem, layer, original_suffix, translation_suffix, counter)
                candidate = Path(stage) / name
                expected = copy.copy(scoped_project)
                missing: tuple[str, ...] = ()
                stale: tuple[str, ...] = ()
                if layer == "json":
                    expected.cues = view
                    format_name = "json"
                else:
                    expected.cues, missing, stale = layer_cues(
                        view, translations, layer, translation_first=translation_first)
                    from ..caption_style.speaker_names import display_text_cues
                    expected.cues = display_text_cues(scoped_project, expected.cues)
                    format_name = "srt"
                    if layer == "translation" and not expected.cues:
                        scope = speaker_id or "当前范围"
                        raise ValueError(f"{scope}没有可导出的译文（目标语言 {resolved_target}，缺译 {len(missing)} 条）。"
                                         "请先补译，或选择原文／双语导出；未发布本批文件。")
                require_consistent_view(scoped_project, expected.cues, speaker_id=speaker_id)
                _atomic_text_write(candidate, _compile_json(scoped_project) if layer == "json" else compile_srt(expected.cues))
                check = SubtitleExportArtifact(candidate, format_name, speaker_id, len(expected.cues))
                verification = verify_subtitle_artifact(check, expected)
                if not verification.valid or verification.cue_count != len(expected.cues):
                    raise SubtitleVerificationError(target_dir / name, speaker_id, verification)
                all_missing.update(dict.fromkeys(missing))
                all_stale.update(dict.fromkeys(stale))
                pending.append((candidate, LanguageLayerArtifact(
                    target_dir / name, layer, format_name, speaker_id, len(expected.cues), missing, stale)))
        for candidate, artifact in pending:
            final = artifact
            for _attempt in range(100):
                try:
                    _publish_new(candidate, final.path)
                    break
                except FileExistsError:
                    # Appeared after planning: take the next free numbered name.
                    counter += 1
                    final = LanguageLayerArtifact(
                        target_dir / _layer_filename(
                            next(name for sid, _p, name in scopes if sid == artifact.speaker_id),
                            artifact.layer, original_suffix, translation_suffix, counter),
                        artifact.layer, artifact.format, artifact.speaker_id, artifact.cue_count,
                        artifact.missing_translation_ids, artifact.needs_update_ids)
                except OSError as exc:
                    raise SubtitlePublicationError(final.path, published, exc) from exc
            else:
                raise SubtitlePublicationError(final.path, published, FileExistsError(str(final.path)))
            published.append(final)
    return LanguageLayerExport(tuple(published), resolved_target, original_suffix, translation_suffix,
                               tuple(all_missing), tuple(all_stale))


@dataclass(frozen=True)
class PlannedSubtitleFile:
    name: str
    format: str
    speaker_id: str
    # "new"; "replace" (an existing file is replaced after read-back);
    # "renamed" (language layers never replace: the set moves to "(2)").
    status: str = "new"


def _planned_scope_stems(project: SubtitleProject, stem: str, speaker_mode: str) -> list[tuple[str, str]]:
    """Same scopes and per-speaker names as the two export functions."""
    visible_cues = project.visible_cues()
    scopes: list[tuple[str, str]] = []
    if speaker_mode in {"combined", "both"}:
        scopes.append(("", stem))
    if speaker_mode in {"per_speaker", "both"}:
        mapping = {speaker.id: speaker.name for speaker in project.speakers}
        used_names: set[str] = set()
        for speaker_id in dict.fromkeys(cue.speaker_id for cue in visible_cues):
            label = _speaker_filename(mapping.get(speaker_id, speaker_id))
            original_label, suffix = label, 2
            while label.casefold() in used_names:
                label = f"{original_label}_{suffix}"
                suffix += 1
            used_names.add(label.casefold())
            scopes.append((speaker_id, f"{stem}_{label}"))
    return scopes


def planned_subtitle_files(
    project: SubtitleProject,
    directory: str | os.PathLike[str] | None,
    base_name: str,
    options: SubtitleExportOptions,
    layers: Iterable[str] = (),
) -> tuple[PlannedSubtitleFile, ...]:
    """File names an export with these choices would write, without writing.

    With language ``layers`` the SRT (and JSON) files come from
    ``export_language_layers``; the other formats from
    ``export_subtitle_artifacts`` — the same split the export dialogs use.
    ``directory`` may be ``None`` when the folder is chosen later.
    """
    from .export_preferences import output_basename

    target_dir = Path(directory) if directory else None
    formats = set(options.formats) & SUPPORTED_SUBTITLE_FORMATS
    if options.speaker_mode not in SPEAKER_EXPORT_MODES:
        return ()
    scopes = _planned_scope_stems(project, output_basename(base_name or "subtitles"), options.speaker_mode)
    planned: list[PlannedSubtitleFile] = []
    layers = tuple(dict.fromkeys(layer for layer in layers if layer in LANGUAGE_LAYERS))
    if layers and "srt" in formats:
        from ..subtitle_rules.language_rules import project_language
        from ..subtitle_rules.subtitle_translation import container_target
        layer_list = layers + (("json",) if "json" in formats else ())
        original_suffix = project_language(project) or "ja"
        translation_suffix = _translation_suffix(container_target(project))
        counter = 1
        while target_dir is not None and any(
                (target_dir / _layer_filename(scope_stem, layer, original_suffix, translation_suffix, counter)).exists()
                for _sid, scope_stem in scopes for layer in layer_list):
            counter += 1
        for speaker_id, scope_stem in scopes:
            for layer in layer_list:
                planned.append(PlannedSubtitleFile(
                    _layer_filename(scope_stem, layer, original_suffix, translation_suffix, counter),
                    "json" if layer == "json" else "srt", speaker_id, "renamed" if counter > 1 else "new"))
        formats -= {"srt", "json"}
    for speaker_id, scope_stem in scopes:
        for format_name in sorted(formats):
            name = f"{scope_stem}.{format_name}"
            exists = target_dir is not None and (target_dir / name).exists()
            planned.append(PlannedSubtitleFile(name, format_name, speaker_id, "replace" if exists else "new"))
    return tuple(planned)


__all__ = [
    "ArtifactVerification",
    "LANGUAGE_LAYERS",
    "LanguageLayerArtifact",
    "LanguageLayerExport",
    "PlannedSubtitleFile",
    "SubtitleExportArtifact",
    "SubtitleExportOptions",
    "compile_srt",
    "export_language_layers",
    "export_subtitle_artifacts",
    "layer_cues",
    "planned_subtitle_files",
    "verify_subtitle_artifact",
]
