"""Bounded current-cue re-recognition for Subtitle Studio."""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..timeline.studio_commands import cue_by_id
from ..projects.studio_project import SubtitleProject, studio_data_root
from ..system.processes import run_hidden_subprocess


@dataclass(frozen=True)
class LocalReASRResult:
    cue_id: str
    current_text: str
    primary_text: str
    review_text: str
    glossary_evidence: tuple[str, ...]
    recommendation: str
    backend: str
    task_id: str = ""
    audio_source: str = "original"
    preview_key: str = ""
    separation_backend: str = ""
    original_peaks: tuple[float, ...] = ()
    enhanced_peaks: tuple[float, ...] = ()


def protected_reasr_ids(project, cues, locked_speakers, *, keep_manual_text=True):
    """Identify user-owned captions without treating acoustic pauses as locks."""
    from ..timeline.studio_caption_timeline import KEY
    from ..timeline.studio_edit_sequence import source_cue_id_of

    state = project.studio_state
    speakers = set(locked_speakers) | set(state.get("locked_speakers") or ())
    locked = set(state.get("locked_cue_ids") or ())
    confirmed = state.get("review_confirmations") or {}
    manual = (state.get("manual_caption_text") or {}) if keep_manual_text else {}
    instances = (state.get(KEY) or {}).get("instances") or {}
    protected = set()
    for cue in cues:
        source = source_cue_id_of(cue.id)
        receipt = instances.get(cue.id) or instances.get(source) or {}
        if (cue.speaker_id in speakers or cue.id in locked or source in locked or getattr(cue, "locked", False)
                or confirmed.get(cue.id) or confirmed.get(source) or cue.id in manual or source in manual
                or getattr(cue, "timing_locked", False) or cue.transform.get("timing_locked")
                or receipt.get("manual_timing")):
            protected.add(cue.id)
    return protected


def clip_bounds(project: SubtitleProject, cue_id: str, padding_ms: int = 1200) -> tuple[int, int]:
    cue = cue_by_id(project, cue_id)
    start = max(0, cue.start_ms - max(0, int(padding_ms)))
    end = cue.end_ms + max(0, int(padding_ms))
    duration = project.media.duration_ms
    if project.render_settings.get('_cue_domain') == 'timeline':
        from ..timeline.studio_edit_sequence import timeline_duration_ms
        duration = timeline_duration_ms(project)
    if duration:
        end = min(end, duration)
    if end - start > 30_000:
        center = (cue.start_ms + cue.end_ms) // 2
        start = max(0, center - 15_000)
        end = start + 30_000
        if duration and end > duration:
            end = duration
            start = max(0, end - 30_000)
    return start, end


def build_clip_command(
    ffmpeg_path: str | os.PathLike[str],
    media_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    start_ms: int,
    end_ms: int,
    audio_stream: int | None = None,
    *,
    sample_rate: int = 16000,
    channels: int = 1,
) -> list[str]:
    # 2026-10-24: a caption recognized from a further audio track of a
    # multi-track file is heard again from that track (``0:a:N``).
    stream = [] if audio_stream is None else ["-map", f"0:a:{int(audio_stream)}"]
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
        *stream,
        "-vn",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
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


def _caption_stream(project, cue, media) -> int | None:
    """Relative audio stream of the track this caption was recognized from."""
    sources = (project.studio_state or {}).get("speaker_audio_sources") or {}
    source = sources.get(cue.speaker_id) if isinstance(sources, dict) else None
    if not source or os.path.normcase(str(source.get("source_path") or "")) != os.path.normcase(str(media.resolve())):
        return None
    return int(source.get("ordinal") or 0)


def run_local_reasr(
    project: SubtitleProject,
    cue_id: str,
    runtime_settings: dict,
    ffmpeg_path: str | os.PathLike[str],
    *,
    transcriber: Callable | None = None,
    on_progress: Callable[[str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    padding_ms: int = 1200,
    enhance_voice: bool = False,
) -> LocalReASRResult:
    def progress(stage):
        if cancel_check and cancel_check():
            from ..subtitle_rules.sentence_refine_contract import RefineError
            raise RefineError('重新识别已取消', 'cancelled')
        if on_progress:
            on_progress(stage)

    progress('读取素材与固定输入')
    cue = cue_by_id(project, cue_id)
    media = Path(project.media.path)
    if not media.is_file() and project.render_settings.get('_cue_domain') != 'timeline':
        raise FileNotFoundError(media)
    if cue.end_ms - cue.start_ms > 30_000:
        raise ValueError('当前字幕超过单句识别的 30 秒范围，请使用工程识别或先按实际内容拆分后重试')
    start_ms, end_ms = clip_bounds(project, cue_id, padding_ms=padding_ms)
    cache_dir = studio_data_root() / "reasr"
    cache_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix="cue-", suffix=".wav", dir=str(cache_dir))
    os.close(descriptor)
    clip_path = Path(temporary_name)
    enhanced_path = clip_path.with_name(clip_path.stem + "-enhanced.wav")
    models = dict(runtime_settings.get("models", {})) if isinstance(runtime_settings, dict) else {}
    review_backend = str(models.get("qwen_asr_backend") or "off")
    primary_backend = str(models.get("primary_asr_backend") or "moss")
    backend = review_backend if review_backend != "off" else primary_backend
    if backend == "moss":
        backend = "off"
    try:
        if backend == 'off':
            raise RuntimeError('当前没有可用于单句重新识别的后端，请选择本地复核模型后重试')
        if enhance_voice and backend not in {"local", "qwen_local"}:
            raise RuntimeError('人声增强后的重新识别需要本机 Qwen')
        progress('准备局部音频')
        sample_rate, channels = (44100, 2) if enhance_voice else (16000, 1)
        command = build_clip_command(ffmpeg_path, media, clip_path, start_ms, end_ms,
                                     audio_stream=_caption_stream(project, cue, media),
                                     sample_rate=sample_rate, channels=channels)
        if project.render_settings.get('_cue_domain') == 'timeline':
            from types import SimpleNamespace
            from ..exports.audio_export import capture_audio_mix, audio_mix_arguments
            duration = (end_ms - start_ms) / 1000
            job = SimpleNamespace(start_seconds=start_ms / 1000, duration_seconds=duration,
                                  video_graph={'duration_ms': end_ms})
            arguments = audio_mix_arguments(str(ffmpeg_path), job, capture_audio_mix(project))
            if arguments == ['-an']:
                raise RuntimeError('当前字幕范围没有启用的素材音频，请检查音轨、静音和素材位置')
            layout = 'stereo' if enhance_voice else 'mono'
            command = [str(ffmpeg_path), '-hide_banner', '-nostdin', '-loglevel', 'error', '-y',
                       '-f', 'lavfi', '-i', f'anullsrc=r={sample_rate}:cl={layout}:d={duration:.6f}',
                       *arguments, '-t', f'{duration:.6f}', '-ac', str(channels),
                       '-ar', str(sample_rate), str(clip_path)]
        completed = run_hidden_subprocess(
            command,
            purpose="ffmpeg re-asr extraction",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if completed.returncode != 0 or not clip_path.is_file() or clip_path.stat().st_size <= 44:
            raise RuntimeError(f"局部音频提取失败: {completed.stderr[-800:]}")
        speech_path = clip_path
        preview_key = ""
        separation_backend = ""
        original_peaks = enhanced_peaks = ()
        if enhance_voice:
            from ..media.vocal_enhancement import enhance_studio_clip, waveform_peaks
            from ..storage.project_stage_history import record_stage
            from ..recognition.service import CancelledError

            progress('分离所选范围的人声')
            try:
                enhanced = enhance_studio_clip(clip_path, enhanced_path, ffmpeg_path, cancel_check=cancel_check)
            except CancelledError:
                record_stage(project.project_id, 'enhancement', 'cancelled', clips=1)
                raise
            except Exception:
                record_stage(project.project_id, 'enhancement', 'failed', clips=1)
                raise
            record_stage(project.project_id, 'enhancement', 'completed',
                         source=f"htdemucs_{enhanced.backend}", clips=1,
                         cuda_clips=int(enhanced.backend == "cuda"))
            speech_path = enhanced.path
            preview_key = enhanced.cache_key
            separation_backend = enhanced.backend
            original_peaks, enhanced_peaks = waveform_peaks(clip_path), waveform_peaks(speech_path)
        if transcriber is None and backend == 'haas_ja':
            from ..recognition.asr import decode_audio_to_array
            from ..recognition.haas_backend import transcribe
            from ..recognition.run_context import get_runtime_context
            from ..subtitle_rules.language_rules import normalize_language
            from ..subtitle_rules.segmentation_profiles import project_language_tag
            from dataclasses import replace
            context = get_runtime_context()
            language = normalize_language(context.requested_language)
            if language == 'auto':
                language = normalize_language(project_language_tag(project))
            pcm = decode_audio_to_array(str(speech_path))
            context = replace(context, requested_language=language, asr_settings_snapshot=runtime_settings)
            transcriber = lambda _path, regions, _audio, **_options: transcribe(pcm, regions, context)
        if transcriber is None:
            from ..recognition.asr import transcribe_qwen_reference

            transcriber = transcribe_qwen_reference
        progress('识别中，等待模型返回（含按需加载）')
        duration = (end_ms - start_ms) / 1000
        rows = transcriber(
            str(speech_path),
            [{"start": 0.0, "end": duration}],
            None,
            backend_override="local" if backend == "qwen_local" else backend,
        )
        review_parts = []
        progress('校验识别结果')
        for row in rows or []:
            value = row.get('text') if isinstance(row, dict) else row
            if isinstance(value, str) and value.strip():
                review_parts.append(value.strip())
        # A 繁體 project reads the (简体) recognizers in 繁體 too (2026-10-19, ADR 0132).
        from ..subtitle_rules.chinese_script import for_project
        review_text = for_project("".join(review_parts), project)
        if not review_text.strip():
            raise RuntimeError('识别后端没有返回有效文字，原字幕已保留；请查看模型日志或更换后端重试')
        primary_text = for_project(_existing_primary_text(project, cue_id), project)
        recommendation = review_text or primary_text or cue.text
        return LocalReASRResult(
            cue_id=cue.id,
            current_text=cue.text,
            primary_text=primary_text,
            review_text=review_text,
            glossary_evidence=tuple(project.glossary_ids),
            recommendation=recommendation,
            backend=backend,
            audio_source="htdemucs" if enhance_voice else "original",
            preview_key=preview_key,
            separation_backend=separation_backend,
            original_peaks=original_peaks,
            enhanced_peaks=enhanced_peaks,
        )
    finally:
        for temporary in (clip_path, enhanced_path):
            try:
                temporary.unlink()
            except OSError:
                pass
