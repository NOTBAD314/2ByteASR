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


def _compile_json(project: SubtitleProject) -> str:
    speakers = {speaker.id: speaker.name for speaker in project.speakers}
    payload = {
        "schema_version": 1,
        "kind": "2byteasr-subtitle-export",
        "project_id": project.project_id,
        "cues": [
            {
                "id": cue.id,
                "start_ms": cue.start_ms,
                "end_ms": cue.end_ms,
                "text": cue.text,
                "speaker_id": cue.speaker_id,
                "speaker_name": speakers.get(cue.speaker_id, cue.speaker_id),
                "style_id": cue.style_id,
            }
            for cue in sorted(_export_view_cues(project), key=lambda item: (item.start_ms, item.end_ms, item.id))
        ],
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


__all__ = [
    "ArtifactVerification",
    "SubtitleExportArtifact",
    "SubtitleExportOptions",
    "compile_srt",
    "export_subtitle_artifacts",
    "verify_subtitle_artifact",
]
