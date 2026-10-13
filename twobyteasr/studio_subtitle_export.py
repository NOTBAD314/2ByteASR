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

from .ass_compiler import compile_ass, compile_txt, escape_ass_text
from .studio_project import StudioCue, SubtitleProject


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

    @property
    def valid(self) -> bool:
        return all((
            self.timestamps_valid,
            self.speaker_mapping_valid,
            self.unicode_valid,
        ))


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
        text = str(cue.text or "").replace("\r\n", "\n").replace("\r", "\n")
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
    subset.validate()
    return subset


def _export_view_cues(project: SubtitleProject):
    """导出口径=当前活动序列的 timeline 域投影（2026-09-19 P0）。

    剪辑模式导出的是这段剪辑（序列时间从 00:00 起）；完整录播导出全集。
    project.cues 永远保持全集+源时间，不因导出被改写。
    """
    from .studio_edit_sequence import projected_cues

    return projected_cues(project, domain="timeline")


def _lookup_translation(view: dict, cue_id: str) -> dict | None:
    """A view cue's translation info (projected ids fall back to their source cue)."""
    from .studio_edit_sequence import source_cue_id_of

    return view.get(cue_id) or view.get(source_cue_id_of(cue_id))


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
    from .cue_forced_alignment import CUE_ALIGNMENT_PREFIX, is_cue_alignment_row
    from .cue_word_alignment import MEASURED_ALIGNMENTS
    from .studio_edit_sequence import source_cue_id_of

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
    from .studio_edit_sequence import projected_cues

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
    from .language_rules import project_language
    from .subtitle_translation import container_target, translation_view

    speakers = {speaker.id: speaker.name for speaker in project.speakers}
    target = container_target(project)
    translations = translation_view(project)
    untranslated = {"text": "", "status": "untranslated", "origin": "", "target": target}
    cues_by_id = {item.id: item for item in project.cues}
    rows = []
    for cue in sorted(_export_view_cues(project), key=lambda item: (item.start_ms, item.end_ms, item.id)):
        info = _lookup_translation(translations, cue.id) or untranslated
        speaker_name = speakers.get(cue.speaker_id, cue.speaker_id)
        rows.append({
            "id": cue.id,
            "start_ms": cue.start_ms,
            "end_ms": cue.end_ms,
            "text": cue.text,
            "speaker_id": cue.speaker_id,
            "speaker_name": speaker_name,
            "style_id": cue.style_id,
            # Bilingual additions (2026-10-12); the keys above are unchanged.
            "original_text": cue.text,
            "duration_ms": cue.end_ms - cue.start_ms,
            "speaker": {"id": cue.speaker_id, "name": speaker_name},
            "translation": {key: info.get(key, "") for key in ("text", "status", "origin", "target")},
            "word_timing": _safe_word_timing(project, cue, cues_by_id),
        })
    payload = {
        "schema_version": 1,
        "kind": "2byteasr-subtitle-export",
        "project_id": project.project_id,
        "original_language": project_language(project) or "",
        "translation_target": target,
        "cues": rows,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _compile_format(project: SubtitleProject, format_name: str) -> str:
    view = _export_view_cues(project)
    if format_name == "srt":
        return compile_srt(view)
    if format_name == "ass":
        return compile_ass(project, cues=view)
    if format_name == "txt":
        return compile_txt(project, cues=view)
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


def export_subtitle_artifacts(
    project: SubtitleProject,
    directory: str | os.PathLike[str],
    base_name: str,
    options: SubtitleExportOptions,
) -> tuple[SubtitleExportArtifact, ...]:
    project.validate()
    options.validate()
    target_dir = Path(directory)
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
                _atomic_text_write(candidate, _compile_format(scoped_project, format_name))
                expected = copy.copy(scoped_project)
                expected.cues = _export_view_cues(scoped_project)
                artifact = SubtitleExportArtifact(candidate, format_name, speaker_id, len(expected.cues))
                verification = verify_subtitle_artifact(artifact, expected)
                count_invalid = (
                    verification.cue_count < artifact.cue_count
                    if format_name == "ass"
                    else verification.cue_count != artifact.cue_count
                )
                if not verification.valid or count_invalid:
                    raise RuntimeError(f"subtitle artifact verification failed: {target}")
                pending.append((candidate, SubtitleExportArtifact(target, format_name, speaker_id, len(expected.cues))))
        for candidate, artifact in pending:
            try:
                os.replace(candidate, artifact.path)
            except OSError as exc:
                raise SubtitlePublicationError(artifact.path, artifacts, exc) from exc
            artifacts.append(artifact)
    return tuple(artifacts)


_SRT_BLOCK = re.compile(
    r"(?ms)^[ \t]*\d+[ \t]*\n"
    r"(\d{2}:\d{2}:\d{2},\d{3})[ \t]*-->[ \t]*(\d{2}:\d{2}:\d{2},\d{3})[ \t]*\n"
    r"(.*?)(?=\n{2,}\d+[ \t]*\n|\Z)"
)


def _parse_srt_time(value: str) -> int:
    hours, minutes, tail = value.split(":")
    seconds, millis = tail.split(",")
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis)


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
    if artifact.format == "srt":
        rows = list(_SRT_BLOCK.finditer(content))
        cue_count = len(rows)
        timestamps_valid = cue_count == len(expected) and all(
            _parse_srt_time(row.group(1)) == cue.start_ms
            and _parse_srt_time(row.group(2)) == cue.end_ms
            for row, cue in zip(rows, expected)
        )
        unicode_valid = all(cue.text.replace("\r\n", "\n").replace("\r", "\n") in row.group(3)
                            for row, cue in zip(rows, expected))
        speaker_mapping_valid = all(
            not artifact.speaker_id or cue.speaker_id == artifact.speaker_id for cue in expected
        )
    elif artifact.format == "ass":
        rows = [line for line in content.splitlines() if line.startswith("Dialogue:")]
        cue_count = len(rows)
        timestamps_valid = cue_count >= len(expected)
        speaker_mapping_valid = all(
            any(f",{cue.speaker_id}," in row for row in rows) for cue in expected
        )
        unicode_valid = all(escape_ass_text(cue.text) in content for cue in expected)
    elif artifact.format == "txt":
        # TXT stores one LF-delimited row per cue; U+2028/U+2029 are text.
        rows = content.removesuffix("\n").split("\n") if expected else []
        cue_count = len(rows)
        timestamps_valid = cue_count == len(expected)
        speaker_mapping_valid = all(
            not artifact.speaker_id or cue.speaker_id == artifact.speaker_id for cue in expected
        )
        unicode_valid = all(
            cue.text.replace("\r", " ").replace("\n", " ") == row for cue, row in zip(expected, rows)
        )
    elif artifact.format == "json":
        payload = json.loads(content)
        rows = payload.get("cues", []) if isinstance(payload, dict) else []
        cue_count = len(rows)
        timestamps_valid = cue_count == len(expected) and all(
            int(row.get("start_ms", -1)) == cue.start_ms and int(row.get("end_ms", -1)) == cue.end_ms
            for row, cue in zip(rows, expected)
        )
        speaker_mapping_valid = all(
            str(row.get("speaker_id") or "") == cue.speaker_id for row, cue in zip(rows, expected)
        )
        unicode_valid = all(str(row.get("text") or "") == cue.text for row, cue in zip(rows, expected))
    else:
        raise ValueError(f"unsupported subtitle format: {artifact.format}")
    return ArtifactVerification(
        artifact.path,
        artifact.format,
        cue_count,
        timestamps_valid,
        speaker_mapping_valid,
        unicode_valid,
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
    """One SRT cue body: unified newlines, no blank line (it would end the block)."""
    rows = [row.rstrip() for row in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(row for row in rows if row.strip())


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
            if not translated:
                missing.append(cue.id)
            elif info.get("status") == "needs_update":
                stale.append(cue.id)
        if layer == "original":
            text = original
        elif layer == "translation":
            if not translated:
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
    return "zh-Hant" if target == "zh-Hant" else "zh"


def _layer_filename(scope_stem: str, layer: str, original_suffix: str, translation_suffix: str,
                    counter: int) -> str:
    stem = scope_stem if counter <= 1 else f"{scope_stem} ({counter})"
    if layer == "json":
        return f"{stem}.json"
    suffix = {"original": original_suffix, "translation": translation_suffix, "bilingual": "bilingual"}[layer]
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

    Names: ``{stem}.ja.srt``, ``{stem}.zh.srt`` (``.zh-Hant.srt``),
    ``{stem}.bilingual.srt``, ``{stem}.json``. Existing files are never
    replaced: when any planned name exists the whole set moves to
    ``{stem} (2).ja.srt`` etc. Every candidate is parsed back before
    publication. Translations come from the project's translation records
    (old projects: the legacy ``translations`` dict).
    """
    from .export_preferences import output_basename
    from .language_rules import project_language
    from .subtitle_translation import container_target, normalize_target, translation_view

    project.validate()
    layers = tuple(dict.fromkeys(str(layer) for layer in layers))
    if not layers or not set(layers) <= SUPPORTED_LANGUAGE_LAYERS:
        raise ValueError("select at least one supported language layer")
    if speaker_mode not in SPEAKER_EXPORT_MODES:
        raise ValueError("unsupported speaker export mode")
    resolved_target = normalize_target(target) if target else container_target(project)
    translations = translation_view(project, target=resolved_target if target else None)
    original_suffix = original_suffix or project_language(project) or "ja"
    translation_suffix = _translation_suffix(resolved_target)
    base = output_basename(stem or "subtitles")
    target_dir = Path(directory)
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
                    _atomic_text_write(candidate, _compile_json(scoped_project))
                    expected.cues = view
                    format_name = "json"
                else:
                    expected.cues, missing, stale = layer_cues(
                        view, translations, layer, translation_first=translation_first)
                    _atomic_text_write(candidate, compile_srt(expected.cues))
                    format_name = "srt"
                check = SubtitleExportArtifact(candidate, format_name, speaker_id, len(expected.cues))
                verification = verify_subtitle_artifact(check, expected)
                if not verification.valid or verification.cue_count != len(expected.cues):
                    raise RuntimeError(f"subtitle artifact verification failed: {target_dir / name}")
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


__all__ = [
    "ArtifactVerification",
    "LANGUAGE_LAYERS",
    "LanguageLayerArtifact",
    "LanguageLayerExport",
    "SubtitleExportArtifact",
    "SubtitleExportOptions",
    "compile_srt",
    "export_language_layers",
    "export_subtitle_artifacts",
    "layer_cues",
    "verify_subtitle_artifact",
]
