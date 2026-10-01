"""Bounded current-cue re-recognition for Subtitle Studio."""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .studio_commands import cue_by_id
from .studio_project import SubtitleProject, studio_data_root
from .processes import run_hidden_subprocess


@dataclass(frozen=True)
class LocalReASRResult:
    cue_id: str
    current_text: str
    primary_text: str
    review_text: str
    glossary_evidence: tuple[str, ...]
    recommendation: str
    backend: str


def clip_bounds(project: SubtitleProject, cue_id: str, padding_ms: int = 1200) -> tuple[int, int]:
    cue = cue_by_id(project, cue_id)
    start = max(0, cue.start_ms - max(0, int(padding_ms)))
    end = cue.end_ms + max(0, int(padding_ms))
    if project.media.duration_ms:
        end = min(end, project.media.duration_ms)
    if end - start > 30_000:
        center = (cue.start_ms + cue.end_ms) // 2
        start = max(0, center - 15_000)
        end = start + 30_000
        if project.media.duration_ms and end > project.media.duration_ms:
            end = project.media.duration_ms
            start = max(0, end - 30_000)
    return start, end


def build_clip_command(
    ffmpeg_path: str | os.PathLike[str],
    media_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    start_ms: int,
    end_ms: int,
) -> list[str]:
    return [
        str(Path(ffmpeg_path).resolve()),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start_ms / 1000:.3f}",
        "-i",
        str(Path(media_path).resolve()),
        "-t",
        f"{max(0.05, (end_ms - start_ms) / 1000):.3f}",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(Path(output_path).resolve()),
    ]


def _existing_primary_text(project: SubtitleProject, cue_id: str) -> str:
    cue = cue_by_id(project, cue_id)
    candidates: list[str] = []
    for reference in cue.evidence_refs:
        row = project.asr_evidence.get(reference)
        if not isinstance(row, dict):
            continue
        for key in ("text", "moss_text", "firered_text", "qwen_asr_text", "alternate_text"):
            value = str(row.get(key) or "").strip()
            if value and value not in candidates:
                candidates.append(value)
    return " / ".join(candidates) or cue.original_text or cue.text


def run_local_reasr(
    project: SubtitleProject,
    cue_id: str,
    runtime_settings: dict,
    ffmpeg_path: str | os.PathLike[str],
    *,
    transcriber: Callable | None = None,
) -> LocalReASRResult:
    cue = cue_by_id(project, cue_id)
    media = Path(project.media.path)
    if not media.is_file():
        raise FileNotFoundError(media)
    start_ms, end_ms = clip_bounds(project, cue_id)
    cache_dir = studio_data_root() / "reasr"
    cache_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix="cue-", suffix=".wav", dir=str(cache_dir))
    os.close(descriptor)
    clip_path = Path(temporary_name)
    models = dict(runtime_settings.get("models", {})) if isinstance(runtime_settings, dict) else {}
    review_backend = str(models.get("qwen_asr_backend") or "off")
    primary_backend = str(models.get("primary_asr_backend") or "moss")
    backend = review_backend if review_backend != "off" else primary_backend
    if backend == "moss":
        backend = "off"
    try:
        completed = run_hidden_subprocess(
            build_clip_command(ffmpeg_path, media, clip_path, start_ms, end_ms),
            purpose="ffmpeg re-asr extraction",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if completed.returncode != 0 or not clip_path.is_file() or clip_path.stat().st_size <= 44:
            raise RuntimeError(f"局部音频提取失败: {completed.stderr[-800:]}")
        if backend == "off":
            rows = []
        else:
            if transcriber is None:
                from .asr import transcribe_qwen_reference

                transcriber = transcribe_qwen_reference
            duration = (end_ms - start_ms) / 1000
            rows = transcriber(
                str(clip_path),
                [{"start": 0.0, "end": duration}],
                None,
                backend_override="local" if backend == "qwen_local" else backend,
            )
        review_parts = []
        for row in rows or []:
            value = str(row.get("text") if isinstance(row, dict) else row).strip()
            if value and value not in review_parts:
                review_parts.append(value)
        review_text = "".join(review_parts)
        primary_text = _existing_primary_text(project, cue_id)
        recommendation = review_text or primary_text or cue.text
        return LocalReASRResult(
            cue_id=cue.id,
            current_text=cue.text,
            primary_text=primary_text,
            review_text=review_text,
            glossary_evidence=tuple(project.glossary_ids),
            recommendation=recommendation,
            backend=backend,
        )
    finally:
        try:
            clip_path.unlink()
        except OSError:
            pass
