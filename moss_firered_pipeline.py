import copy
import gc
import json
import math
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median

import numpy as np
import hashlib

from twobyteasr.asr_schema import (
    ASR_RESULT_SCHEMA_VERSION,
    SchemaContractError,
    canonical_result_from_segments,
    flatten_segment_tokens,
    normalize_moss_result,
    schema_shape,
    validate_canonical_result,
    validate_flat_segments,
)

from twobyteasr.processes import (
    hidden_subprocess_kwargs,
    python_utf8_command,
    sanitized_child_environment,
    stop_process_tree,
    utf8_worker_environment,
)
from twobyteasr.runtime import get_runtime_context
from twobyteasr.service import CancelledError
from twobyteasr.pipeline_runtime import (
    complete_media_run,
    finalize_cues,
    run_parallel_stages,
)


PIPELINE_BUILD_ID = "2026.08.10-v7.18-asr-result-schema-v2"


_CANCELLATION_TOKEN = None


MOSS_MODEL = "OpenMOSS-Team/MOSS-Transcribe-Diarize"
MOSS_TIMEOUT_SECONDS = 7200
MOSS_NO_PROGRESS_TIMEOUT_SECONDS = 900
MOSS_CHUNK_SECONDS = 180.0
MOSS_CHUNK_OVERLAP_SECONDS = 20.0
MOSS_SINGLE_PASS_MAX_SECONDS = 210.0
MOSS_SPEAKER_PAD_SECONDS = 0.30
# Keep pathological FireRed token tails from becoming false sentence timing.
FIRERED_EFFECTIVE_TOKEN_OUTSIDE_TOLERANCE_SECONDS = 0.08
MOSS_OVERLAP_CONFLICT_SECONDS = 0.15
# 自动模式最多保留四位持续出现的主播；手动模式允许到六位。
# 二者分开，避免为了三主播直播而把大量一次性节目/角色声全部写入成片。
MOSS_AUTO_MAX_HOST_SPEAKERS = 4
MOSS_MAX_EXPECTED_SPEAKERS = 6
MOSS_HOST_MIN_SPAN_RATIO = 0.60  # Candidate timeline persistence; never voiceprint similarity.
MOSS_HOST_MIN_ACTIVE_BIN_RATIO = 0.75
FIRERED_LLM_MIN_GPU_GB = 15.5
# 走增量识别的主力后端。三十六轮起不含 "api"：增量层把整块 45s 当
# "语音区间"传入，25s 硬切块边界落在连续语流中间（时间戳劣化实录）；
# API 主力改走全量路径（先 VAD 再按真实区间 + 10s 切块）。
INCREMENTAL_PRIMARY_BACKENDS = {"qwen_local", "whisper_turbo", "sensevoice", "funasr_nano"}
SPEAKER_EMBEDDING_MIN_SIMILARITY = 0.42
SPEAKER_EMBEDDING_MAX_AUDIO_SECONDS = 14.0
REGISTERED_HOST_MIN_SIMILARITY = 0.55
REGISTERED_HOST_MIN_MARGIN = 0.05
REGISTERED_HOST_MIN_SEGMENTS = 2
TRANSIENT_HOST_MAX_LABEL_SEGMENTS = 3
TRANSIENT_HOST_MAX_DURATION_SECONDS = 2.20
TRANSIENT_HOST_MAX_CHARS = 8
TRANSIENT_HOST_MIN_CROSS_SPEAKER_OVERLAP = 0.12
TRANSIENT_HOST_NEARBY_PAD_SECONDS = 0.12
TRANSIENT_HOST_MIN_SIMILARITY = 0.12
TRANSIENT_HOST_MIN_MARGIN = 0.055


def set_cancellation_token(token):
    global _CANCELLATION_TOKEN
    _CANCELLATION_TOKEN = token


def verify_pipeline_contract(legacy, launcher_path, launcher_build_id):
    """确保入口与两个核心模块来自同一目录、同一构建版本。"""
    frozen = bool(getattr(sys, "frozen", False))
    expected_root = os.path.normcase(
        os.path.realpath(os.path.dirname(os.path.abspath(launcher_path)))
    )
    entries = (
        ("auto_asr", launcher_path, launcher_build_id),
        ("subtitle_core", getattr(legacy, "__file__", ""), getattr(legacy, "PIPELINE_BUILD_ID", "")),
        ("moss_firered_pipeline", __file__, PIPELINE_BUILD_ID),
    )
    normalized = []
    problems = []
    for name, path, build_id in entries:
        resolved = os.path.realpath(os.path.abspath(path)) if path else ""
        root = os.path.normcase(os.path.dirname(resolved)) if resolved else ""
        normalized.append((name, resolved, str(build_id or "")))
        if not resolved:
            problems.append(f"{name} 路径无效：{resolved or '<missing>'}")
        elif not frozen and not os.path.isfile(resolved):
            problems.append(f"{name} 路径无效：{resolved}")
        elif not frozen and root != expected_root:
            problems.append(f"{name} 不在入口目录：{resolved}")

    build_ids = {build_id for _, _, build_id in normalized if build_id}
    if len(build_ids) != 1 or any(not build_id for _, _, build_id in normalized):
        detail = "；".join(f"{name}={build_id or '<missing>'}" for name, _, build_id in normalized)
        problems.append(f"构建版本不一致：{detail}")
    if problems:
        raise RuntimeError("流水线文件自检失败：\n- " + "\n- ".join(problems))

    print(f"[流水线版本] {normalized[0][2]}")
    for name, path, _ in normalized:
        print(f"   {name}: {path}")
    return {
        "build_id": normalized[0][2],
        "paths": {name: path for name, path, _ in normalized},
    }


def _script_paths(legacy):
    script_dir = legacy.SCRIPT_DIR

    def _models_root():
        # P8C-R3.1: models live under the registered MODEL_ROOT (persisted,
        # independent of the install directory). dist-relative models/ stays
        # as fallback for installs that really ship their own model tree.
        try:
            from twobyteasr.runtime_paths import get_runtime_paths

            root = str(get_runtime_paths().model_root)
            if root and os.path.isdir(root):
                return root
        except Exception:
            pass
        return os.path.join(script_dir, "models")

    def role_python(role):
        # RuntimeEnvironmentRegistry: registered/legacy venvs, never a venv
        # expected inside the packaged install directory. When nothing is
        # found the stable root is reported so repair targets one location.
        try:
            from twobyteasr.runtime_registry import (
                intended_runtime_root,
                resolve_runtime_python,
            )

            resolved = resolve_runtime_python(role)
            if resolved:
                return resolved
            return os.path.join(intended_runtime_root(role), "Scripts", "python.exe")
        except Exception:
            venv = ".venv-" + role.replace("_", "-")
            return os.path.join(script_dir, venv, "Scripts", "python.exe")

    models = _models_root()
    frozen = bool(getattr(sys, "frozen", False))
    # Packaged runs use the workers/ copy of moss_worker.py: it sits in a
    # pyd-free subdirectory so the isolated (-I) 3.12 venv never resolves
    # the GUI bundle's cp310 extensions from the install root.
    moss_worker_path = os.path.join(script_dir, "moss_worker.py")
    if frozen:
        workers_copy = os.path.join(script_dir, "workers", "moss_worker.py")
        if os.path.isfile(workers_copy):
            moss_worker_path = workers_copy
    return {
        "main_python": role_python("main"),
        "moss_python": role_python("moss"),
        "moss_worker": moss_worker_path,
        "firered_llm_worker": os.path.join(script_dir, "firered_llm_worker.py"),
        "firered_llm_python": role_python("firered_llm"),
        "firered_vad": os.path.join(models, "FireRedVAD", "VAD"),
        "firered_source": os.path.join(script_dir, "third_party", "FireRedASR2S"),
        "firered_worker": os.path.join(script_dir, "firered_aed_worker.py"),
        "qwen_worker": os.path.join(script_dir, "qwen_asr_worker.py"),
        "firered_llm": os.path.join(models, "FireRedASR2-LLM"),  # 可选本地复核；不在 dependencies.lock.json，需手动放置模型
        "speaker_embedding": os.path.join(models, "spkrec-ecapa-voxceleb"),
    }


def _path_signature(path):
    if not os.path.exists(path):
        return {"path": os.path.normcase(os.path.abspath(path)), "missing": True}
    if os.path.isfile(path):
        stat = os.stat(path)
        return {"path": os.path.normcase(os.path.abspath(path)), "size": stat.st_size, "mtime": stat.st_mtime_ns}
    newest = 0
    count = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                stat = os.stat(os.path.join(root, name))
            except OSError:
                continue
            count += 1
            newest = max(newest, stat.st_mtime_ns)
    return {"path": os.path.normcase(os.path.abspath(path)), "files": count, "mtime": newest}


def _model_result_count(value):
    """Count concrete model output without treating an empty fallback as success."""
    if isinstance(value, dict) and value.get("result_type") == "ASRResult":
        rows = value.get("segments")
        return len(rows) if isinstance(rows, list) else 0
    if isinstance(value, dict):
        for key in ("segments", "tokens", "chunks", "references"):
            rows = value.get(key)
            if isinstance(rows, (list, tuple)):
                return sum(1 for row in rows if _model_row_is_valid(row))
        return 0
    if isinstance(value, (list, tuple)):
        return sum(1 for row in value if _model_row_is_valid(row))
    return 0


def _model_row_is_valid(row):
    if isinstance(row, dict):
        text = str(row.get("text") or row.get("content") or "").strip()
        if text:
            return True
        timestamps = row.get("timestamp") or row.get("tokens")
        return isinstance(timestamps, (list, tuple)) and bool(timestamps)
    return bool(str(row or "").strip())


def _model_stage_summary(legacy):
    """Collapse auditable model transitions into a persisted per-model view."""
    report_api = getattr(getattr(legacy, "task_reporting", None), "active_media_report", None)
    report = report_api() if callable(report_api) else None
    events = list(report.get("events", [])) if isinstance(report, dict) else []
    from twobyteasr.model_execution import summarize_model_events
    return summarize_model_events(events)


def _record_fused_review_classification(
    legacy, segments, *, firered_selected, firered_failed, qwen_selected, qwen_failed
):
    """Classify fused evidence after all selected stages have settled."""
    from twobyteasr.asr_source_evidence import _confidence
    counts = {
        "MULTI_SOURCE_AGREEMENT": 0,
        "MULTI_SOURCE_CONFLICT": 0,
        "SINGLE_SOURCE_DEGRADED": 0,
        "TIMING_LOW_CONFIDENCE": 0,
        "TEXT_LOW_CONFIDENCE": 0,
        "TEXT_CONFIDENCE_UNKNOWN": 0,
    }
    for segment in segments:
        has_firered = bool(segment.firered_text)
        has_qwen = bool(segment.qwen_text)
        if has_firered and has_qwen:
            similarity = legacy.asr_consensus_similarity(
                segment.firered_text, segment.qwen_text
            )
            counts[
                "MULTI_SOURCE_AGREEMENT"
                if similarity >= legacy.ASR_CONSENSUS_MIN_SIMILARITY
                else "MULTI_SOURCE_CONFLICT"
            ] += 1
        elif (firered_selected and firered_failed) or (qwen_selected and qwen_failed):
            counts["SINGLE_SOURCE_DEGRADED"] += 1
        aligned = float((getattr(segment, "caption_arbitration", None) or {})
                        .get("forced_alignment_window", {}).get("token_count", 0) or 0) > 0
        if firered_selected and not aligned and (
            firered_failed
            or not has_firered
            or float(segment.firered_alignment_confidence or 0.0) < 0.60
        ):
            counts["TIMING_LOW_CONFIDENCE"] += 1
        qwen_score = _confidence({"qwen_confidence": segment.qwen_confidence,
            "qwen_confidence_available": getattr(segment, "qwen_confidence_available", False)}, "qwen3-asr")
        if qwen_selected and not qwen_failed and has_qwen and qwen_score is None:
            counts["TEXT_CONFIDENCE_UNKNOWN"] += 1
        if qwen_selected and (qwen_failed or not has_qwen or
                (qwen_score is not None and qwen_score < 0.60)):
            counts["TEXT_LOW_CONFIDENCE"] += 1
    legacy.record_run_event(
        "review_classification",
        phase="post_model_fusion",
        counts=counts,
        segment_count=len(segments),
    )
    return counts


def _real_three_source_cue_evidence(segments, *, limit=5):
    """Persist bounded rows proving that all three real ASR sources were joined.

    The row keeps each recognizer's own text and timing contract.  It is only
    emitted when MOSS text, a FireRed token window, and Qwen text are all
    present; disagreement is retained for review rather than hidden by the
    final text owner.
    """
    rows = []
    for segment in segments:
        if not (
            segment.moss_text
            and segment.firered_text
            and segment.firered_end > segment.firered_start
            and segment.qwen_text
        ):
            continue
        rows.append(
            {
                "cue_id": int(segment.segment_id),
                "moss": {
                    "text": str(segment.moss_text),
                    "start": round(float(segment.moss_start), 3),
                    "end": round(float(segment.moss_end), 3),
                },
                "firered": {
                    "text": str(segment.firered_text),
                    "start": round(float(segment.firered_start), 3),
                    "end": round(float(segment.firered_end), 3),
                    "confidence": round(float(segment.firered_alignment_confidence or 0.0), 3),
                },
                "qwen": {
                    "text": str(segment.qwen_text),
                    "confidence": round(float(segment.qwen_confidence or 0.0), 3),
                },
                "final": {
                    "text": str(segment.final_text or segment.text),
                    "start": round(float(segment.final_start or segment.start), 3),
                    "end": round(float(segment.final_end or segment.end), 3),
                    "text_owner": str(segment.final_text_owner or "MOSS"),
                    "timing_owner": str(segment.final_timing_owner or "MOSS"),
                },
                "text_similarity": round(
                    float(segment.reference_consensus or 0.0), 3
                ),
            }
        )
        if len(rows) >= max(1, int(limit)):
            break
    return rows


def _model_event(
    legacy,
    event,
    *,
    model_id,
    role,
    backend,
    media_path,
    worker,
    runtime,
    started_at=None,
    ended_at=None,
    segment_count=0,
    failure_reason="",
    ready=None,
    missing_paths=(),
    execution="runtime",
    telemetry=None,
):
    """Emit an auditable model state transition with no secret-bearing fields."""
    now = time.time()
    start = float(started_at if started_at is not None else now)
    end = float(ended_at if ended_at is not None else now)
    payload = dict(
        model_id=str(model_id),
        role=str(role),
        backend=str(backend),
        worker=str(worker or ""),
        runtime=str(runtime or ""),
        input=str(media_path or ""),
        started_at_ms=round(start * 1000.0, 3),
        ended_at_ms=round(end * 1000.0, 3),
        elapsed_seconds=round(max(0.0, end - start), 3),
        segment_count=int(segment_count or 0),
        failure_reason=str(failure_reason or ""),
        environment_ready=ready,
        missing_paths=[str(path) for path in missing_paths],
        execution=str(execution or "runtime"),
        thread=threading.current_thread().name,
    )
    if isinstance(telemetry, dict):
        payload.update({str(key): value for key, value in telemetry.items()})
    legacy.record_run_event(
        event,
        **payload,
    )


def _run_audited_model_stage(
    legacy,
    *,
    model_id,
    role,
    backend,
    media_path,
    worker,
    runtime,
    runner,
    selected=True,
    allow_failure=False,
    skip_reason="",
    environment_probe=None,
):
    """Run one selected ASR stage and make empty/failure states explicit."""
    if not selected:
        _model_event(
            legacy,
            "MODEL_SKIPPED",
            model_id=model_id,
            role=role,
            backend=backend,
            media_path=media_path,
            worker=worker,
            runtime=runtime,
            failure_reason=skip_reason or "not_selected",
            execution="skipped",
        )
        return []

    _model_event(
        legacy,
        "MODEL_SELECTED",
        model_id=model_id,
        role=role,
        backend=backend,
        media_path=media_path,
        worker=worker,
        runtime=runtime,
        ready=None,
    )

    missing = [
        path for path in (worker, runtime)
        if path and not os.path.exists(path)
    ]
    if not callable(environment_probe):
        _model_event(
            legacy,
            "MODEL_ENVIRONMENT_READY",
            model_id=model_id,
            role=role,
            backend=backend,
            media_path=media_path,
            worker=worker,
            runtime=runtime,
            ready=not missing,
            missing_paths=missing,
        )
    if missing:
        reason = "environment_missing:" + ",".join(str(path) for path in missing)
        if callable(environment_probe):
            _model_event(
                legacy,
                "MODEL_ENVIRONMENT_READY",
                model_id=model_id,
                role=role,
                backend=backend,
                media_path=media_path,
                worker=worker,
                runtime=runtime,
                ready=False,
                missing_paths=missing,
                failure_reason=reason,
            )
        _model_event(
            legacy,
            "MODEL_FAILED",
            model_id=model_id,
            role=role,
            backend=backend,
            media_path=media_path,
            worker=worker,
            runtime=runtime,
            segment_count=0,
            failure_reason=reason,
        )
        if allow_failure:
            return []
        raise RuntimeError(f"{model_id} environment is not ready: {reason}")
    telemetry = {}
    if callable(environment_probe):
        try:
            telemetry = dict(environment_probe() or {})
        except BaseException as exc:
            telemetry = {"probe_error": f"{type(exc).__name__}: {exc}"}
        ready = bool(telemetry.get("ready"))
        _model_event(
            legacy,
            "MODEL_ENVIRONMENT_READY",
            model_id=model_id,
            role=role,
            backend=backend,
            media_path=media_path,
            worker=worker,
            runtime=runtime,
            ready=ready,
            failure_reason=str(telemetry.get("error") or "") if not ready else "",
            telemetry=telemetry,
        )
        if not ready:
            reason = "environment_not_ready:" + str(telemetry.get("error") or "probe_failed")
            _model_event(
                legacy,
                "MODEL_FAILED",
                model_id=model_id,
                role=role,
                backend=backend,
                media_path=media_path,
                worker=worker,
                runtime=runtime,
                segment_count=0,
                failure_reason=reason,
                telemetry=telemetry,
            )
            if allow_failure:
                return []
            raise RuntimeError(f"{model_id} environment is not ready: {reason}")
    started = time.time()
    _model_event(
        legacy,
        "MODEL_STAGE_ENTERED",
        model_id=model_id,
        role=role,
        backend=backend,
        media_path=media_path,
        worker=worker,
        runtime=runtime,
        started_at=started,
        execution="stage_entered_not_worker_start",
    )
    try:
        value = runner()
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit, CancelledError)):
            raise
        ended = time.time()
        _model_event(
            legacy,
            "MODEL_FAILED",
            model_id=model_id,
            role=role,
            backend=backend,
            media_path=media_path,
            worker=worker,
            runtime=runtime,
            started_at=started,
            ended_at=ended,
            failure_reason=f"{type(exc).__name__}: {exc}",
            telemetry=telemetry,
        )
        if allow_failure:
            return []
        raise
    legacy.record_run_event(
        "MODEL_RESULT_SCHEMA",
        model_id=model_id,
        producer=f"{model_id}_runner",
        consumer="model_audit",
        shape=schema_shape(value),
    )
    count = _model_result_count(value)
    ended = time.time()
    if count <= 0:
        reason = "empty_result"
        _model_event(
            legacy,
            "MODEL_FAILED",
            model_id=model_id,
            role=role,
            backend=backend,
            media_path=media_path,
            worker=worker,
            runtime=runtime,
            started_at=started,
            ended_at=ended,
            segment_count=0,
            failure_reason=reason,
            telemetry=telemetry,
        )
        if allow_failure:
            return []
        raise RuntimeError(f"{model_id} returned no usable segments")
    _model_event(
        legacy,
        "MODEL_COMPLETED",
        model_id=model_id,
        role=role,
        backend=backend,
        media_path=media_path,
        worker=worker,
        runtime=runtime,
        started_at=started,
        ended_at=ended,
        segment_count=count,
        telemetry=telemetry,
    )
    return value


def check_runtime(legacy):
    legacy.check_runtime()
    from twobyteasr.hardware import (
        combination_requires_cuda,
        require_cuda_runtime,
        require_local_torch_runtime,
    )
    from twobyteasr.model_integrity import verify_model_files
    from importlib.metadata import PackageNotFoundError, version as package_version

    require_local_torch_runtime(legacy.RUNTIME_SETTINGS)
    if combination_requires_cuda(legacy.RUNTIME_SETTINGS):
        require_cuda_runtime()
    primary_key = str(getattr(legacy, "PRIMARY_ASR_BACKEND", "moss"))
    if primary_key in {'vibevoice_1_5b', 'vibevoice_7b'}:
        raise RuntimeError('VibeVoice-ASR-Streaming 已移除，请在模型工坊选择现有主力模型。')
    if primary_key == "none":
        raise RuntimeError("尚未选择主力转写模型。请先在模型工坊选择一个主力模型。")
    if primary_key == "moss" and not getattr(sys, "frozen", False):
        # 源码模式才做 speechbrain 元数据检查。打包运行不带 dist-info，且
        # speechbrain 实际运行在 .venv-moss 的 MOSS worker 内部——由 worker
        # 自己的导入给出明确错误。
        try:
            package_version("speechbrain")
        except PackageNotFoundError as exc:
            raise RuntimeError(
                "缺少说话人分块拼接依赖 speechbrain。请运行：python -m pip install speechbrain==1.0.3"
            ) from exc
    paths = _script_paths(legacy)
    required = []
    if primary_key == "moss":
        required.extend(
            [
                (paths["firered_vad"], "FireRedVAD 模型"),
                (paths["moss_python"], "MOSS 独立 Python 环境"),
                (paths["moss_worker"], "MOSS 子进程桥接脚本"),
                (paths["speaker_embedding"], "ECAPA 说话人嵌入模型"),
            ]
        )
    elif primary_key == "firered":
        required.extend(
            [(legacy.FIRERED_SOURCE_DIR, "FireRedASR2S 源码"), (legacy.FIRERED_MODEL_DIR, "FireRedASR2-AED 模型")]
        )
    elif primary_key == "qwen_local":
        required.append((legacy.resolve_qwen_asr_local_source(), "Qwen3-ASR 主力模型"))
    elif primary_key == "firered_llm":
        required.extend(
            [
                (paths["firered_llm"], "FireRedASR2-LLM 模型"),
                (paths["firered_llm_python"], "FireRed LLM 独立 Python 环境"),
                (paths["firered_llm_worker"], "FireRed LLM 子进程 Adapter"),
            ]
        )
    elif primary_key == "whisper_turbo":
        required.append((legacy.resolve_whisper_local_source(), "Whisper Turbo 主力模型"))
    elif primary_key in {"sensevoice", "funasr_nano", "paraformer"}:
        required.append((legacy.resolve_funasr_local_source(primary_key), f"{primary_key} 主力模型"))
    if legacy.FIRERED_ASR_BACKEND == "local":
        required.extend(
            [
                (legacy.FIRERED_SOURCE_DIR, "FireRedASR2S 源码"),
                (legacy.FIRERED_MODEL_DIR, "FireRedASR2-AED 模型"),
            ]
        )
    elif legacy.FIRERED_ASR_BACKEND == "qwen_aligner":
        required.append((legacy.resolve_qwen_aligner_local_source(), "Qwen3 ForcedAligner 模型"))
    elif legacy.FIRERED_ASR_BACKEND == "whisper_turbo":
        required.append((legacy.resolve_whisper_local_source(), "Whisper 字幕时间轴模型"))
    elif legacy.FIRERED_ASR_BACKEND == "paraformer":
        required.append((legacy.resolve_funasr_local_source("paraformer"), "Paraformer 模型"))

    review_key = str(legacy.QWEN_ASR_BACKEND)
    if review_key == "local":
        required.append((legacy.resolve_qwen_asr_local_source(), "Qwen3-ASR 复核模型"))
    elif review_key == "firered_llm":
        required.extend(
            [
                (paths["firered_llm"], "FireRedASR2-LLM 复核模型"),
                (paths["firered_llm_python"], "FireRed LLM 独立 Python 环境"),
                (paths["firered_llm_worker"], "FireRed LLM 子进程 Adapter"),
            ]
        )
    elif review_key == "whisper_turbo":
        required.append((legacy.resolve_whisper_local_source(), "Whisper Turbo 复核模型"))
    elif review_key in {"sensevoice", "funasr_nano"}:
        required.append((legacy.resolve_funasr_local_source(review_key), f"{review_key} 复核模型"))
    missing = []
    for path, label in required:
        if not os.path.exists(path):
            missing.append(f"{label}（{os.path.normcase(os.path.abspath(path))}）")
    if missing:
        raise RuntimeError(
            "缺少新流水线组件：" + "、".join(missing)
            + "。\n请运行 setup_2byteasr.bat 重新配置，或直接运行 download_models.bat 下载模型。"
        )
    if primary_key == "moss":
        from twobyteasr.runtime_paths import resolve_model_dir

        verify_model_files("moss", resolve_model_dir("MOSS-Transcribe-Diarize"))
        verify_model_files("speaker_embedding", paths["speaker_embedding"])
    elif primary_key == "firered":
        verify_model_files("firered_aed", legacy.FIRERED_MODEL_DIR)
    elif primary_key == "qwen_local":
        verify_model_files("qwen_asr", legacy.resolve_qwen_asr_local_source())
    elif primary_key == "firered_llm":
        verify_model_files("firered_llm", paths["firered_llm"])
    elif primary_key == "whisper_turbo":
        verify_model_files("whisper_turbo", legacy.resolve_whisper_local_source())
    elif primary_key in {"sensevoice", "funasr_nano", "paraformer"}:
        verify_model_files(primary_key, legacy.resolve_funasr_local_source(primary_key))
    if primary_key == "moss":
        from twobyteasr.runtime_paths import resolve_model_dir

        verify_model_files("firered_vad", resolve_model_dir("FireRedVAD"))
    if legacy.FIRERED_ASR_BACKEND == "local":
        verify_model_files("firered_aed", legacy.FIRERED_MODEL_DIR)
    elif legacy.FIRERED_ASR_BACKEND == "qwen_aligner":
        verify_model_files("qwen_aligner", legacy.resolve_qwen_aligner_local_source())
    elif legacy.FIRERED_ASR_BACKEND == "whisper_turbo":
        verify_model_files("whisper_turbo", legacy.resolve_whisper_local_source())
    elif legacy.FIRERED_ASR_BACKEND == "paraformer":
        verify_model_files("paraformer", legacy.resolve_funasr_local_source("paraformer"))
    if review_key == "local":
        verify_model_files("qwen_asr", legacy.resolve_qwen_asr_local_source())
    elif review_key == "firered_llm":
        verify_model_files("firered_llm", paths["firered_llm"])
    elif review_key == "whisper_turbo":
        verify_model_files("whisper_turbo", legacy.resolve_whisper_local_source())
    elif review_key in {"sensevoice", "funasr_nano"}:
        verify_model_files(review_key, legacy.resolve_funasr_local_source(review_key))
    status = getattr(legacy, "host_voiceprint_status_summary", None)
    if callable(status):
        print(f"   [主播声纹] {status()}")
    _preflight_cloud_stages(legacy)


def _preflight_cloud_stages(legacy):
    """开跑前（t=0）校验云端校对/断句配置，杜绝 30 分钟后才失败。

    2026-09-03 run eca757：grok_account（Grok 登陆）用户在阶段 8 才发现
    校对无 API 密钥，30 分钟 GPU 转写整轮作废。HTTP 端点缺模型/地址/密钥、
    CLI 传输未安装/未登录都必须在这里立即抛错，错误信息给出可行动指引。
    """
    context = get_runtime_context()
    if context.recognition_purpose == 'analysis':
        legacy.record_run_event('cloud_preflight_skipped', reason='analysis_has_no_cloud_text_stages')
        return
    from twobyteasr.ai_providers import provider_for_stage
    from twobyteasr.llm_config import validate_endpoint
    from twobyteasr.asr_provider_snapshot import task_provider_snapshot
    task_settings = context.asr_settings_snapshot or legacy.RUNTIME_SETTINGS
    from twobyteasr.recognition_plan import text_ai_plan
    plan = text_ai_plan(task_settings, purpose=context.recognition_purpose)
    stages = [(stage, {"polish": "字幕校对模型", "group": "全文断句模型"}[stage]) for stage in plan.roles]
    for stage in ('polish', 'group'):
        if stage not in plan.roles:
            legacy.record_run_event('text_ai_stage_disabled', stage=stage, reason='user_disabled')
    for stage, label in stages:
        snapshot = task_provider_snapshot(stage)
        endpoint = snapshot.endpoint()
        transport = snapshot.transport
        legacy.record_run_event("asr_provider_snapshot", job_id=context.job_id,
                                stage=f"preflight_{stage}", **snapshot.public_identity())
        if snapshot.kind == "cli":
            # CLI 传输的模型名来自 provider profile（可为空=CLI 默认模型），
            # 没有 API 密钥概念；只校验会话可用性。
            provider = provider_for_stage(snapshot.execution_settings(), stage)
            probe = provider.validate(use_cache=True)
            if not probe.available or not probe.authenticated:
                raise RuntimeError(
                    f"{label}使用账号登陆传输（{getattr(transport, 'value', transport)}），"
                    f"当前不可用：{probe.message}。"
                    "请在 AI 模型与密钥中完成登录，或改选 DeepSeek 等 OpenAI 兼容厂商并填写 API 密钥。"
                )
            model_hint = str(endpoint.get("model", "")).strip() or "CLI 默认模型"
            print(f"   [云端预检] {label}：账号会话可用（{model_hint}）。")
        else:
            validate_endpoint(endpoint, label)
            print(
                f"   [云端预检] {label}：{endpoint.get('provider', 'custom')} "
                f"端点配置有效。"
            )


def _cancel_requested():
    if _CANCELLATION_TOKEN is not None and _CANCELLATION_TOKEN.is_cancelled:
        return True
    if os.name != "nt" or not sys.stdin or not sys.stdin.isatty():
        return False
    try:
        import msvcrt

        if msvcrt.kbhit():
            return msvcrt.getwch().lower() == "q"
    except (ImportError, OSError):
        pass
    return False


def _parallel_cancel_poll():
    """并行编排层在安全点抛出取消：队列令牌或控制台 Q 键。"""
    if _cancel_requested():
        raise CancelledError("任务已取消。")


def _run_streaming_worker(
    command,
    timeout_seconds,
    no_progress_seconds=MOSS_NO_PROGRESS_TIMEOUT_SECONDS,
    *,
    abort_event=None,
    line_prefix="",
):
    # 所有走本函数的 worker 都以 `-I`（隔离模式）启动：隔离模式隐含 -E、
    # 无视 PYTHON* 环境变量，ACP=936 的机器上子进程会把中文进度按 GBK 写进
    # 管道（2026-09-20 运行日志乱码实录）。-X utf8 是显式解释器选项，在
    # -I 下依然生效，因此在这里统一钉住子进程 stdio 编码。
    command = python_utf8_command(command)
    worker_owner = get_runtime_context()
    worker_job_id = str(getattr(worker_owner, 'job_id', '') or '')
    # Python 3.12 子进程的 stdout 接到 PIPE 后会回落到 Windows 本地代码页；
    # 主进程按 UTF-8 解码时就会把中文进度替换成问号/�。注意 -I 会忽略全部
    # PYTHON* 环境变量（隐含 -E），因此必须用 -X utf8 这个显式解释器选项
    # 固定子进程 stdio 编码，环境变量只对无 -I 的子进程有意义。
    # P8C-R3.1: 剥离冻结宿主遗留的 PYTHONHOME/PYTHONPATH/_MEIPASS2，
    # 否则外部 venv python 无法启动（No module named 'encodings'）。
    worker_env = utf8_worker_environment()
    # P8C-R3.1: 子进程 CWD 绝不能是打包安装根——dist 根带有 GUI 的 cp310
    # .pyd，外部 venv python 的 sys.path[0]=''（CWD 搜索）会加载到它们并报
    # "Module use of python310.dll conflicts"。用解释器自己的 Scripts 目录。
    worker_cwd = os.path.dirname(str(command[0] if not isinstance(command[0], Path) else Path(command[0]))) or None
    if getattr(sys, "frozen", False):
        # 打包宿主的 PATH 含 bundle 目录（python3.dll/python310.dll 所在），
        # 外部 venv python 的 CWD/PATH 搜索会加载它们并报
        # "Module use of python310.dll conflicts"。worker 需要 venv 自身、
        # Windows 系统目录和 tools/ffmpeg（media_duration 用 ffprobe）。
        venv_scripts = os.path.dirname(str(command[0]))
        system_root = worker_env.get("SystemRoot") or r"C:\Windows"
        try:
            from twobyteasr.runtime_paths import detect_install_root

            install_root = detect_install_root()
        except Exception:
            install_root = os.path.dirname(venv_scripts)
        ffmpeg_bin = os.path.join(install_root, "tools", "ffmpeg", "bin")
        worker_env["PATH"] = os.pathsep.join(
            [
                venv_scripts,
                ffmpeg_bin,
                os.path.join(system_root, "System32"),
                system_root,
                os.path.join(system_root, "System32", "Wbem"),
                os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0"),
            ]
        )
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=worker_env,
        cwd=worker_cwd,
        **hidden_subprocess_kwargs(),
    )
    from twobyteasr.cache import record_run_event
    worker_identity = dict(model_id='moss', backend='moss', pid=process.pid,
        job_id=worker_job_id,
        worker=next((str(arg) for arg in command if str(arg).endswith('moss_worker.py')), ''), runtime=str(command[0]),
        role='primary_transcription', execution='worker_process_started', loaded=None)
    record_run_event('asr_worker_started', **worker_identity)
    record_run_event('MODEL_STARTED', **worker_identity)
    if sys.stdin and sys.stdin.isatty():
        print("      MOSS 运行中可按 Q 安全取消本次任务。", flush=True)
    output_queue = queue.Queue()

    def read_output():
        try:
            for line in process.stdout:
                output_queue.put(line.rstrip())
        finally:
            output_queue.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    lines = []
    finished_output = False
    started = time.monotonic()
    last_output = started
    try:
        while process.poll() is None or not finished_output:
            if get_runtime_context() is not worker_owner:
                raise CancelledError('MOSS旧任务已被替换，停止worker并拒绝迟到结果。')
            now = time.monotonic()
            if now - started > timeout_seconds:
                raise TimeoutError(f"MOSS 子进程超过 {timeout_seconds / 60:.0f} 分钟未完成。")
            if process.poll() is None and now - last_output > no_progress_seconds:
                raise TimeoutError(
                    f"MOSS 连续 {no_progress_seconds / 60:.0f} 分钟没有任何进度输出，"
                    "已停止疑似卡死进程；整段任务未完成，诊断已保留。"
                )
            if _cancel_requested():
                raise KeyboardInterrupt("用户按 Q 取消 MOSS。")
            if abort_event is not None and abort_event.is_set():
                raise RuntimeError("同组 MOSS 工作进程失败，已停止当前进程。")
            try:
                line = output_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if line is None:
                finished_output = True
                continue
            progress = None
            if line.startswith("MOSS_EVENT "):
                try:
                    progress = json.loads(line[len("MOSS_EVENT "):])
                    record_run_event("asr_worker_progress", backend="moss", job_id=worker_job_id, **progress)
                except (ValueError, TypeError):
                    pass
            if not progress or not progress.get("heartbeat"):
                last_output = time.monotonic()
            if line:
                lines.append(line)
                print(f"      MOSS{line_prefix}: {line}", flush=True)
        reader.join(timeout=2.0)
        return process.returncode, lines
    except BaseException as exc:
        exc.output_lines = list(lines)
        stop_process_tree(process)
        reader.join(timeout=2.0)
        raise
    finally:
        if process.poll() is None:
            stop_process_tree(process)
        record_run_event('asr_worker_exited', model_id='moss', backend='moss',
            job_id=worker_job_id, pid=process.pid, returncode=process.poll(), readers_stopped=not reader.is_alive())


def _chunk_moss_audio(shared_audio, temp_dir, legacy):
    """Compatibility name: transport ONE complete task PCM, never slice it."""
    path = os.path.join(temp_dir, "moss_full_audio.npy")
    np.save(path, np.asarray(shared_audio, dtype="<f4"), allow_pickle=False)
    return [{"chunk_id": 1, "audio": path, "offset": 0.0,
             "duration": len(shared_audio) / legacy.AUDIO_SAMPLE_RATE,
             "sample_count": len(shared_audio)}]


def _moss_parallel_worker_count(jobs, legacy, total_vram_gb=None, free_vram_gb=None):
    # Persisted legacy settings cannot reactivate independent MOSS contexts.
    return 1


def _read_moss_worker_payload(output_path, returncode, output_lines, label, recorder=None):
    if returncode != 0 or not os.path.isfile(output_path):
        detail = "\n".join(output_lines[-30:])[-3000:]
        raise RuntimeError(f"{label}失败（退出码 {returncode}）：{detail}")
    with open(output_path, "r", encoding="utf-8") as file:
        payload = json.load(file)
    _validate_moss_worker_payload(
        payload,
        producer="moss_worker",
        consumer="moss_chunk_merger",
    )
    if callable(recorder):
        recorder(
            "MOSS_RAW_SCHEMA",
            producer="moss_worker",
            consumer="moss_chunk_merger",
            shape=schema_shape(payload),
        )
    return payload


def _validate_moss_worker_payload(payload, *, producer, consumer):
    """Reject malformed worker/cache chunks before merge code dereferences them."""
    if not isinstance(payload, dict):
        raise SchemaContractError(
            producer=producer,
            consumer=consumer,
            received=payload,
            expected_schema="MOSS worker dict with non-empty flat chunks",
        )
    chunks = payload.get("chunks")
    if not isinstance(chunks, (list, tuple)) or not chunks:
        raise SchemaContractError(
            producer=producer,
            consumer=consumer,
            received=payload,
            expected_schema="MOSS worker dict with non-empty chunks: list[dict]",
        )
    flat_segments = 0
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise SchemaContractError(
                producer=producer,
                consumer=consumer,
                received=chunk,
                expected_schema="MOSS chunk dict with flat segments: list[dict]",
            )
        rows = chunk.get("segments")
        if not isinstance(rows, (list, tuple)):
            raise SchemaContractError(
                producer=producer,
                consumer=consumer,
                received=chunk,
                expected_schema="MOSS chunk dict with flat segments: list[dict]",
            )
        for row in rows:
            if not isinstance(row, dict):
                raise SchemaContractError(
                    producer=producer,
                    consumer=consumer,
                    received=row,
                    expected_schema="MOSS ASRSegment dict with start/end/text",
                )
            flat_segments += 1


def _run_moss_manifest_jobs(jobs, temp_dir, paths, legacy, title, *, force_workers=None):
    """Reject historical block requests; one task owns one full-context worker."""
    if len(jobs) != 1 or float(jobs[0].get("offset", 0)) != 0:
        raise ValueError("MOSS full_context 禁止多个独立块或非零任务起点。")
    output_path = os.path.join(temp_dir, "moss.json")
    command = [paths["moss_python"], "-I", paths["moss_worker"],
               "--audio", jobs[0]["audio"], "--output", output_path,
               "--model", MOSS_MODEL, "--title", title]
    code, lines = _run_streaming_worker(command, MOSS_TIMEOUT_SECONDS)
    return _read_moss_worker_payload(output_path, code, lines, "MOSS 整段worker",
                                   recorder=getattr(legacy, "record_run_event", None))


def _speaker_match_score(current_segments, previous_segments, local_speaker, global_speaker, legacy):
    score = 0.0
    for current in current_segments:
        if current["speaker"] != local_speaker:
            continue
        for previous in previous_segments:
            if previous["speaker"] != global_speaker:
                continue
            time_score = _time_overlap(
                float(current["start"]),
                float(current["end"]),
                float(previous["start"]),
                float(previous["end"]),
            )
            center_gap = abs(
                (float(current["start"]) + float(current["end"])) / 2.0
                - (float(previous["start"]) + float(previous["end"])) / 2.0
            )
            if time_score <= 0.0 and center_gap > 1.0:
                continue
            similarity = legacy.asr_consensus_similarity(current["text"], previous["text"])
            score += similarity * (0.20 + time_score) * max(0.20, 1.0 - center_gap / 2.0)
    return score


def _map_chunk_speakers(
    chunk_segments,
    previous_segments,
    known_speakers,
    next_speaker_id,
    legacy,
    local_embeddings=None,
    global_embeddings=None,
):
    local_speakers = sorted({item["speaker"] for item in chunk_segments})
    if not previous_segments:
        mapping = {}
        for local in local_speakers:
            mapping[local] = f"S{next_speaker_id:02d}"
            next_speaker_id += 1
        return mapping, next_speaker_id

    mapping = {}
    used_global = set()
    local_embeddings = local_embeddings or {}
    global_embeddings = global_embeddings or {}

    # MOSS 每块会重新编号；声纹相似度先负责身份延续，文字重叠只作后备。
    voice_candidates = []
    for local in local_speakers:
        local_embedding = local_embeddings.get(local)
        if local_embedding is None:
            continue
        for global_speaker, global_embedding in global_embeddings.items():
            similarity = float(np.dot(local_embedding, global_embedding))
            if similarity >= SPEAKER_EMBEDDING_MIN_SIMILARITY:
                voice_candidates.append((similarity, local, global_speaker))
    for _, local, global_speaker in sorted(voice_candidates, reverse=True):
        if local in mapping or global_speaker in used_global:
            continue
        mapping[local] = global_speaker
        used_global.add(global_speaker)

    candidates = []
    previous_speakers = sorted({item["speaker"] for item in previous_segments})
    for local in local_speakers:
        if local in mapping:
            continue
        for global_speaker in previous_speakers:
            if global_speaker in used_global:
                continue
            score = _speaker_match_score(
                chunk_segments, previous_segments, local, global_speaker, legacy
            )
            if score >= 0.18:
                candidates.append((score, local, global_speaker))
    for _, local, global_speaker in sorted(candidates, reverse=True):
        if local in mapping or global_speaker in used_global:
            continue
        mapping[local] = global_speaker
        used_global.add(global_speaker)

    # 重叠区恰好静音时没有文字可比；同名标签作为保守后备，避免主播被切成多个全局标签。
    for local in local_speakers:
        if local not in mapping and local in known_speakers and local not in used_global:
            mapping[local] = local
            used_global.add(local)
    for local in local_speakers:
        if local in mapping:
            continue
        while f"S{next_speaker_id:02d}" in known_speakers or f"S{next_speaker_id:02d}" in used_global:
            next_speaker_id += 1
        mapping[local] = f"S{next_speaker_id:02d}"
        used_global.add(mapping[local])
        next_speaker_id += 1
    return mapping, next_speaker_id


def _speaker_group_signal(chunk, local_speaker, chunk_index, chunk_count, audio_seconds, shared_audio, legacy):
    offset = float(chunk.get("offset", 0.0))
    duration = float(chunk.get("duration", 0.0))
    owned_start = offset if chunk_index == 0 else offset + MOSS_CHUNK_OVERLAP_SECONDS / 2.0
    chunk_end = min(audio_seconds, offset + duration)
    owned_end = chunk_end if chunk_index == chunk_count - 1 else chunk_end - MOSS_CHUNK_OVERLAP_SECONDS / 2.0
    rows = []
    for raw in chunk.get("segments", []):
        if str(raw.get("speaker") or "S00").strip("[] ") != local_speaker:
            continue
        start = max(0.0, offset + float(raw["start"]))
        end = min(audio_seconds, max(start + 0.01, offset + float(raw["end"])))
        center = (start + end) / 2.0
        if owned_start <= center < owned_end or (chunk_index == chunk_count - 1 and center <= owned_end):
            rows.append((start, end))
    rows.sort(key=lambda item: min(4.0, item[1] - item[0]), reverse=True)
    pieces = []
    remaining = int(SPEAKER_EMBEDDING_MAX_AUDIO_SECONDS * legacy.AUDIO_SAMPLE_RATE)
    for start, end in rows:
        left = max(0, int((start + 0.08) * legacy.AUDIO_SAMPLE_RATE))
        right = min(len(shared_audio), int((end - 0.08) * legacy.AUDIO_SAMPLE_RATE))
        if right - left < int(0.35 * legacy.AUDIO_SAMPLE_RATE):
            continue
        piece = np.asarray(shared_audio[left:right], dtype=np.float32)[:remaining]
        pieces.append(piece)
        remaining -= len(piece)
        if remaining <= 0:
            break
    if not pieces:
        return None
    signal = np.concatenate(pieces)
    peak = float(np.max(np.abs(signal)))
    return signal / max(peak, 1e-4)


def _compute_chunk_speaker_embeddings(chunks, shared_audio, audio_seconds, legacy):
    if len(chunks) <= 1 or shared_audio is None:
        return {}
    paths = _script_paths(legacy)
    model_dir = paths["speaker_embedding"]
    if not os.path.isfile(os.path.join(model_dir, "embedding_model.ckpt")):
        raise RuntimeError("缺少 ECAPA 声纹模型，已停止分块说话人拼接。")
    if getattr(sys, "frozen", False):
        audio_npy = str(getattr(shared_audio, "filename", "") or "")
        return _compute_chunk_speaker_embeddings_subprocess(
            chunks, audio_seconds, model_dir, legacy, audio_npy
        )
    try:
        import warnings

        import torch
        import torchaudio

        # SpeechBrain 1.0.3 仍查询已被新版 torchaudio 移除的旧接口；
        # 本流程直接传入张量，不调用其音频加载器，因此声明 soundfile 后端即可兼容。
        if not hasattr(torchaudio, "list_audio_backends"):
            torchaudio.list_audio_backends = lambda: ["soundfile"]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from speechbrain.inference.speaker import EncoderClassifier
            from speechbrain.utils.fetching import LocalStrategy

            encoder = EncoderClassifier.from_hparams(
                source=model_dir,
                savedir=model_dir,
                overrides={"pretrained_path": model_dir},
                local_strategy=LocalStrategy.NO_LINK,
                run_opts={"device": "cpu"},
            )
        keys = []
        signals = []
        for chunk_index, chunk in enumerate(chunks):
            local_speakers = sorted(
                {str(item.get("speaker") or "S00").strip("[] ") for item in chunk.get("segments", [])}
            )
            for local_speaker in local_speakers:
                signal = _speaker_group_signal(
                    chunk,
                    local_speaker,
                    chunk_index,
                    len(chunks),
                    audio_seconds,
                    shared_audio,
                    legacy,
                )
                if signal is None:
                    continue
                keys.append((chunk_index, local_speaker))
                signals.append(torch.from_numpy(signal))
        if not signals:
            return {}
        lengths = torch.tensor([len(item) for item in signals], dtype=torch.float32)
        padded = torch.nn.utils.rnn.pad_sequence(signals, batch_first=True)
        relative_lengths = lengths / padded.shape[1]
        with torch.inference_mode():
            matrix = encoder.encode_batch(padded, relative_lengths).squeeze(1)
            matrix = torch.nn.functional.normalize(matrix, dim=-1).cpu().numpy()
        print(f"   [完成] ECAPA 声纹：{len(keys)} 个分块说话人嵌入。")
        return {key: vector for key, vector in zip(keys, matrix)}
    except Exception as exc:
        raise RuntimeError(f"ECAPA 声纹失败，已停止以避免说话人串号：{exc}") from exc
    finally:
        gc.collect()


def _compute_chunk_speaker_embeddings_subprocess(chunks, audio_seconds, model_dir, legacy, audio_npy):
    """P8C-R3.1: ECAPA in the main runtime venv via subprocess (frozen mode)."""
    from twobyteasr.processes import main_python_executable, run_speaker_embed_worker

    main_python = main_python_executable()
    if not main_python or not os.path.isfile(main_python):
        raise RuntimeError("ECAPA 声纹失败：主运行环境 Python 未找到（无法计算说话人嵌入）。")
    pipeline_dir = os.path.dirname(os.path.abspath(__file__))
    worker_path = os.path.join(pipeline_dir, "workers", "speaker_embed_worker.py")
    if not os.path.isfile(worker_path):
        worker_path = os.path.join(pipeline_dir, "speaker_embed_worker.py")
    manifest = {
        "audio_npy": audio_npy,
        "sample_rate": int(legacy.AUDIO_SAMPLE_RATE),
        "model_dir": model_dir,
        "max_audio_seconds": SPEAKER_EMBEDDING_MAX_AUDIO_SECONDS,
        "chunk_overlap_seconds": MOSS_CHUNK_OVERLAP_SECONDS,
        "audio_seconds": float(audio_seconds),
        "chunks": [
            {
                "offset": float(chunk.get("offset", 0.0)),
                "duration": float(chunk.get("duration", 0.0)),
                "segments": list(chunk.get("segments", [])),
            }
            for chunk in chunks
        ],
    }
    raw = run_speaker_embed_worker(
        worker_path=worker_path,
        main_python=main_python,
        manifest=manifest,
    )
    embeddings = {}
    for key, vector in raw.items():
        chunk_text, local = str(key).split("|", 1)
        embeddings[(int(chunk_text), local)] = np.asarray(vector, dtype=np.float32)
    print(f"   [完成] ECAPA 声纹（子进程）：{len(embeddings)} 个分块说话人嵌入。")
    return embeddings


def _transient_host_candidates(moss_segments, host_speakers, legacy):
    """只挑出极短、极少出现且压在另一说话人上的临时 MOSS 标签。"""
    label_counts = {}
    for row in moss_segments:
        speaker = str(row.get("speaker") or "S00")
        label_counts[speaker] = label_counts.get(speaker, 0) + 1
    candidates = []
    for row in moss_segments:
        speaker = str(row.get("speaker") or "S00")
        if speaker in host_speakers or label_counts.get(speaker, 0) > TRANSIENT_HOST_MAX_LABEL_SEGMENTS:
            continue
        start = float(row["start"])
        end = float(row["end"])
        if end - start < 0.45 or end - start > TRANSIENT_HOST_MAX_DURATION_SECONDS:
            continue
        text = legacy.content_only(row.get("text", ""))
        if not text or len(text) > TRANSIENT_HOST_MAX_CHARS:
            continue
        if not any(
            other is not row
            and str(other.get("speaker") or "S00") != speaker
            and (
                _time_overlap(start, end, float(other["start"]), float(other["end"]))
                >= TRANSIENT_HOST_MIN_CROSS_SPEAKER_OVERLAP
                or (
                    float(other["end"]) >= start - TRANSIENT_HOST_NEARBY_PAD_SECONDS
                    and float(other["start"]) <= end + TRANSIENT_HOST_NEARBY_PAD_SECONDS
                )
            )
            for other in moss_segments
        ):
            continue
        candidates.append(row)
    return candidates


def _speaker_signal_from_rows(rows, shared_audio, legacy, max_seconds, trim_seconds=0.08):
    pieces = []
    remaining = int(max_seconds * legacy.AUDIO_SAMPLE_RATE)
    for row in rows:
        start = float(row["start"])
        end = float(row["end"])
        left = max(0, int((start + trim_seconds) * legacy.AUDIO_SAMPLE_RATE))
        right = min(len(shared_audio), int((end - trim_seconds) * legacy.AUDIO_SAMPLE_RATE))
        if right - left < int(0.35 * legacy.AUDIO_SAMPLE_RATE):
            left = max(0, int(start * legacy.AUDIO_SAMPLE_RATE))
            right = min(len(shared_audio), int(end * legacy.AUDIO_SAMPLE_RATE))
        if right - left < int(0.30 * legacy.AUDIO_SAMPLE_RATE):
            continue
        piece = np.asarray(shared_audio[left:right], dtype=np.float32)[:remaining]
        if not len(piece):
            # 防御：长度门槛变化后切片可能为空；continue 而非 break，
            # 避免错误截断后续更短但仍可用的片段。
            continue
        pieces.append(piece)
        remaining -= len(piece)
        if remaining <= 0:
            break
    if not pieces:
        return None
    signal = np.concatenate(pieces)
    peak = float(np.max(np.abs(signal)))
    return signal / max(peak, 1e-4)


def _clean_host_prototype_signal(moss_segments, host_speaker, shared_audio, legacy):
    rows = []
    for row in moss_segments:
        if str(row.get("speaker") or "S00") != host_speaker:
            continue
        start = float(row["start"])
        end = float(row["end"])
        if end - start < 0.75:
            continue
        if any(
            other is not row
            and str(other.get("speaker") or "S00") != host_speaker
            and _time_overlap(start, end, float(other["start"]), float(other["end"]))
            >= TRANSIENT_HOST_MIN_CROSS_SPEAKER_OVERLAP
            for other in moss_segments
        ):
            continue
        rows.append(row)
    rows.sort(key=lambda row: float(row["end"]) - float(row["start"]), reverse=True)
    return _speaker_signal_from_rows(
        rows,
        shared_audio,
        legacy,
        SPEAKER_EMBEDDING_MAX_AUDIO_SECONDS,
    )


def _encode_speaker_signals(encoder, signals):
    import torch

    tensors = [torch.from_numpy(np.asarray(signal, dtype=np.float32)) for signal in signals]
    lengths = torch.tensor([len(item) for item in tensors], dtype=torch.float32)
    padded = torch.nn.utils.rnn.pad_sequence(tensors, batch_first=True)
    with torch.inference_mode():
        matrix = encoder.encode_batch(padded, lengths / padded.shape[1]).squeeze(1)
        matrix = torch.nn.functional.normalize(matrix, dim=-1).cpu().numpy()
    return matrix


def _rescue_transient_host_segments(moss_segments, host_speakers, shared_audio, legacy):
    """以双重保守门槛找回重叠时被 MOSS 临时拆出的主播短句。"""
    if shared_audio is None or len(host_speakers) < 2:
        return 0
    candidates = _transient_host_candidates(moss_segments, host_speakers, legacy)
    if not candidates:
        return 0
    prototype_signals = []
    usable_hosts = []
    for host_speaker in host_speakers:
        signal = _clean_host_prototype_signal(
            moss_segments, host_speaker, shared_audio, legacy
        )
        if signal is None:
            continue
        usable_hosts.append(host_speaker)
        prototype_signals.append(signal)
    if len(usable_hosts) < 2:
        print("   [声纹保守补漏] 主播干净声纹不足，跳过临时标签认领。")
        return 0
    candidate_rows = []
    candidate_signals = []
    for row in candidates:
        signal = _speaker_signal_from_rows(
            [row],
            shared_audio,
            legacy,
            TRANSIENT_HOST_MAX_DURATION_SECONDS,
        )
        if signal is None:
            continue
        candidate_rows.append(row)
        candidate_signals.append(signal)
    if not candidate_signals:
        return 0
    paths = _script_paths(legacy)
    model_dir = paths["speaker_embedding"]
    try:
        import warnings
        import torchaudio

        if not hasattr(torchaudio, "list_audio_backends"):
            torchaudio.list_audio_backends = lambda: ["soundfile"]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from speechbrain.inference.speaker import EncoderClassifier
            from speechbrain.utils.fetching import LocalStrategy

            encoder = EncoderClassifier.from_hparams(
                source=model_dir,
                savedir=model_dir,
                overrides={"pretrained_path": model_dir},
                local_strategy=LocalStrategy.NO_LINK,
                run_opts={"device": "cpu"},
            )
        matrix = _encode_speaker_signals(
            encoder,
            prototype_signals + candidate_signals,
        )
    except Exception as exc:
        print(f"   [声纹保守补漏] ECAPA 不可用，本次跳过临时标签认领：{exc}")
        return 0
    finally:
        gc.collect()
    prototypes = matrix[: len(prototype_signals)]
    rescued = 0
    rejected = 0
    for row, vector in zip(candidate_rows, matrix[len(prototype_signals) :]):
        scores = np.asarray(vector @ prototypes.T, dtype=np.float32)
        ranking = np.argsort(scores)[::-1]
        best_index = int(ranking[0])
        second_score = float(scores[int(ranking[1])])
        best_score = float(scores[best_index])
        margin = best_score - second_score
        if best_score < TRANSIENT_HOST_MIN_SIMILARITY or margin < TRANSIENT_HOST_MIN_MARGIN:
            rejected += 1
            continue
        original_speaker = str(row.get("speaker") or "S00")
        row["speaker"] = usable_hosts[best_index]
        row["speaker_rescued_from"] = original_speaker
        row["speaker_rescue_score"] = round(best_score, 3)
        row["speaker_rescue_margin"] = round(margin, 3)
        rescued += 1
    if rescued or rejected:
        print(
            f"   [声纹保守补漏] 找回 {rescued} 个主播短句；"
            f"拒绝 {rejected} 个不够确定的临时标签。"
        )
    return rescued


def _drop_redundant_cover_segments(segments, legacy):
    """去掉“一个长段又覆盖同说话人多个短段”的分块边界重复。"""
    ordered = sorted(segments, key=lambda item: (float(item["start"]), float(item["end"])))
    dropped = set()
    for cover_index, cover in enumerate(ordered):
        cover_text = legacy.content_only(cover.get("text", ""))
        cover_start = float(cover["start"])
        cover_end = float(cover["end"])
        cover_duration = max(0.01, cover_end - cover_start)
        if len(cover_text) < 4:
            continue
        pieces = []
        for piece_index, piece in enumerate(ordered):
            if piece_index == cover_index or piece_index in dropped:
                continue
            if str(piece.get("speaker") or "S00") != str(cover.get("speaker") or "S00"):
                continue
            piece_start = float(piece["start"])
            piece_end = float(piece["end"])
            piece_duration = max(0.01, piece_end - piece_start)
            if piece_start < cover_start - 0.12 or piece_end > cover_end + 0.12:
                continue
            if piece_duration >= cover_duration * 0.90:
                continue
            if _time_overlap(cover_start, cover_end, piece_start, piece_end) / piece_duration < 0.85:
                continue
            piece_text = legacy.content_only(piece.get("text", ""))
            if piece_text:
                pieces.append((piece_start, piece_end, piece_text))
        if len(pieces) < 2:
            continue
        pieces.sort(key=lambda item: (item[0], item[1]))
        piece_text = "".join(item[2] for item in pieces)
        if not (0.62 <= len(piece_text) / max(1, len(cover_text)) <= 1.45):
            continue
        covered = 0.0
        interval_start = None
        interval_end = None
        for start, end, _ in pieces:
            if interval_start is None:
                interval_start, interval_end = start, end
            elif start <= interval_end:
                interval_end = max(interval_end, end)
            else:
                covered += interval_end - interval_start
                interval_start, interval_end = start, end
        if interval_start is not None:
            covered += interval_end - interval_start
        similarity = legacy.asr_consensus_similarity(cover_text, piece_text)
        if covered / cover_duration < 0.52 or similarity < 0.76:
            continue
        dropped.add(cover_index)
        print(
            f"   [分块去重] {cover_start:.2f}-{cover_end:.2f}s {cover.get('speaker', 'S00')} "
            f"长段与 {len(pieces)} 个短段重复，保留短段精细边界。"
        )
    kept = [item for index, item in enumerate(ordered) if index not in dropped]
    return _strip_partial_duplicate_covers(kept, legacy)


def _content_positions(text, legacy):
    """把 text 中每个可计数字符的位置映射成 content_only 序列的下标。"""
    positions = []
    content = legacy.content_only(text)
    cursor = 0
    for index, char in enumerate(text):
        if cursor < len(content) and legacy.content_only(char) == content[cursor]:
            positions.append(index)
            cursor += 1
    return positions if cursor == len(content) else []


def _strip_partial_duplicate_covers(segments, legacy):
    """剥掉同说话人“长段文本部分包含相邻短段文本”的残留重复。

    现有全有全无去重只处理“多个时间完全包含的短段拼出长段大部分文字”。
    真实数据里还有三种漏网形态（见 2026-09-03 s4前瞻 取证）：
    短段在时间上越过长段边界、只有一个短段、或只覆盖长段开头/结尾的一部分。
    这里按“同说话人 + 时间重叠 + 短段文本是长段文本的连续子串（≥6 字）”
    逐对剥离长段中被覆盖的字符区间；≥85% 被覆盖时长段整段删除。
    不剥离会让下游同说话人 cue 相互碰撞，被 normalize 推成 0.35s 阶梯串。
    """
    ordered = sorted(segments, key=lambda item: (float(item["start"]), float(item["end"])))
    if len(ordered) < 2:
        return segments
    survivors = [dict(item) for item in ordered]
    # 时长优先：完全相同的重复对先扫描长的那条并整段删除，短的那条保留。
    scan_order = sorted(
        range(len(survivors)),
        key=lambda index: (
            -(float(survivors[index]["end"]) - float(survivors[index]["start"])),
            index,
        ),
    )
    alive = [True] * len(survivors)
    stripped_logs = []
    for cover_index in scan_order:
        cover = survivors[cover_index]
        if not alive[cover_index]:
            continue
        cover_text = str(cover.get("text", ""))
        cover_content = legacy.content_only(cover_text)
        if len(cover_content) < 6:
            continue
        cover_start = float(cover["start"])
        cover_end = float(cover["end"])
        cover_duration = max(0.01, cover_end - cover_start)
        covered = [False] * len(cover_content)
        matched_pieces = []  # (content_pos, content_len, piece_start, piece_end)
        for piece_index, piece in enumerate(survivors):
            if piece_index == cover_index or not alive[piece_index]:
                continue
            if str(piece.get("speaker") or "S00") != str(cover.get("speaker") or "S00"):
                continue
            piece_content = legacy.content_only(piece.get("text", ""))
            if len(piece_content) < 6:
                continue
            piece_start = float(piece["start"])
            piece_end = float(piece["end"])
            # 允许短段在时间上越过长段边界（S03 案例重叠比仅 0.46）：
            # 定位由下方“映射时间与短段相邻”校验和 ≥6 连续字重合保证。
            if _time_overlap(cover_start, cover_end, piece_start, piece_end) < 0.25:
                continue
            # 短段文本可能与长段只部分重合（短段=长段子串+额外内容，或反之），
            # 用最长公共连续子串对齐；≥6 个连续汉字/字母的精确重合已足够强。
            match = SequenceMatcher(
                None, cover_content, piece_content, autojunk=False
            ).find_longest_match(0, len(cover_content), 0, len(piece_content))
            if match.size < 6:
                continue
            pos = match.a
            # 公共子串可能落在长段里同一句话的另一处；要求映射时间与短段相邻。
            mapped_start = cover_start + cover_duration * pos / len(cover_content)
            if abs(mapped_start - piece_start) > 10.0:
                continue
            for offset in range(pos, pos + match.size):
                covered[offset] = True
            matched_pieces.append((pos, match.size, piece_start, piece_end))
        covered_count = sum(covered)
        if covered_count == 0:
            continue
        if covered_count / len(cover_content) >= 0.85:
            alive[cover_index] = False
            stripped_logs.append(
                f"{cover_start:.2f}-{cover_end:.2f}s {cover.get('speaker', 'S00')} "
                f"整段与短段重复（{covered_count}/{len(cover_content)} 字），删除长段"
            )
            continue
        positions = _content_positions(cover_text, legacy)
        if len(positions) != len(cover_content):
            continue
        kept_chars = []
        content_cursor = 0
        keep_last_content = True
        for index, char in enumerate(cover_text):
            if content_cursor < len(positions) and index == positions[content_cursor]:
                keep_last_content = not covered[content_cursor]
                if keep_last_content:
                    kept_chars.append(char)
                content_cursor += 1
            elif keep_last_content:
                # 标点跟随它前面的正文字符一起保留或删除。
                kept_chars.append(char)
        kept_content_count = len(cover_content) - covered_count
        if kept_content_count < 2 or len(legacy.content_only("".join(kept_chars))) < 2:
            alive[cover_index] = False
            stripped_logs.append(
                f"{cover_start:.2f}-{cover_end:.2f}s {cover.get('speaker', 'S00')} "
                "剥掉重复文字后已无正文，删除长段"
            )
            continue
        new_start, new_end = cover_start, cover_end
        prefix_stripped = covered[0]
        suffix_stripped = covered[-1]
        minimum = float(getattr(legacy, "MIN_SUBTITLE_SECONDS", 0.35))
        if suffix_stripped:
            block_start = len(covered)
            while block_start > 0 and covered[block_start - 1]:
                block_start -= 1
            block_pieces = [
                (pos, piece_start)
                for pos, _length, piece_start, _piece_end in matched_pieces
                if pos >= block_start
            ]
            earliest = min((piece_start for _pos, piece_start in block_pieces), default=cover_end)
            new_end = min(cover_end, max(cover_start + minimum, earliest))
        if prefix_stripped:
            block_end = 0
            while block_end < len(covered) and covered[block_end]:
                block_end += 1
            block_pieces = [
                (pos, piece_end)
                for pos, length, _piece_start, piece_end in matched_pieces
                if pos + length <= block_end
            ]
            latest = max((piece_end for _pos, piece_end in block_pieces), default=cover_start)
            new_start = max(cover_start, min(cover_end - minimum, latest))
        if new_end - new_start < 0.05:
            alive[cover_index] = False
            stripped_logs.append(
                f"{cover_start:.2f}-{cover_end:.2f}s {cover.get('speaker', 'S00')} "
                "剥掉重复文字后时间跨度不足，删除长段"
            )
            continue
        cover["text"] = "".join(kept_chars)
        cover["start"] = round(float(new_start), 3)
        cover["end"] = round(float(new_end), 3)
        stripped_logs.append(
            f"{cover_start:.2f}-{cover_end:.2f}s {cover.get('speaker', 'S00')} "
            f"长段剥掉 {covered_count} 个重复字，保留 {kept_content_count} 字"
            f"（{cover['start']:.2f}-{cover['end']:.2f}s）"
        )
    if stripped_logs:
        print(f"   [部分去重] 剥掉 {len(stripped_logs)} 个同说话人重复覆盖：")
        for line in stripped_logs:
            print(f"     - {line}")
    return [item for index, item in enumerate(survivors) if alive[index]]


def _merge_moss_chunks(payload, audio_seconds, legacy, shared_audio=None):
    _validate_moss_worker_payload(
        payload,
        producer="moss_worker",
        consumer="moss_chunk_merger",
    )
    chunks = list(payload["chunks"])
    raw_segment_count = sum(len(chunk.get("segments", [])) for chunk in chunks)
    nested_lists = sum(
        1
        for chunk in chunks
        for row in chunk.get("segments", [])
        if isinstance(row, (list, tuple))
    )
    if nested_lists:
        raise SchemaContractError(
            producer="moss_worker",
            consumer="moss_chunk_merger",
            received=payload,
            expected_schema="MOSS chunks with flat ASRSegment dict rows",
            sample_shape={"raw_chunks": len(chunks), "flat_segments": raw_segment_count, "nested_lists": nested_lists},
        )
    chunk_embeddings = _compute_chunk_speaker_embeddings(
        chunks, shared_audio, audio_seconds, legacy
    )
    merged = []
    previous_full = []
    known_speakers = set()
    next_speaker_id = 1
    global_embeddings = {}
    chunk_summaries = []
    for chunk_index, chunk in enumerate(chunks):
        offset = float(chunk.get("offset", 0.0))
        duration = float(chunk.get("duration", 0.0))
        current_full = []
        for raw in chunk.get("segments", []):
            text = legacy.clean_subtitle_text(raw.get("text", ""))
            if not legacy.content_only(text):
                continue
            start = max(0.0, offset + float(raw["start"]))
            end = min(audio_seconds, max(start + 0.01, offset + float(raw["end"])))
            current_full.append(
                {
                    "start": start,
                    "end": end,
                    "speaker": str(raw.get("speaker") or "S00").strip("[] ") or "S00",
                    "text": text,
                }
            )
        local_embeddings = {
            local: vector
            for (embedding_chunk_index, local), vector in chunk_embeddings.items()
            if embedding_chunk_index == chunk_index
        }
        mapping, next_speaker_id = _map_chunk_speakers(
            current_full,
            previous_full,
            known_speakers,
            next_speaker_id,
            legacy,
            local_embeddings=local_embeddings,
            global_embeddings=global_embeddings,
        )
        voice_scores = {}
        for local, global_speaker in mapping.items():
            vector = local_embeddings.get(local)
            if vector is None:
                continue
            previous_embedding = global_embeddings.get(global_speaker)
            if previous_embedding is not None:
                voice_scores[local] = round(float(np.dot(vector, previous_embedding)), 3)
                blended = previous_embedding * 0.35 + vector * 0.65
                global_embeddings[global_speaker] = blended / max(1e-8, np.linalg.norm(blended))
            else:
                voice_scores[local] = 1.0
                global_embeddings[global_speaker] = vector
        for item in current_full:
            item["speaker"] = mapping[item["speaker"]]
        known_speakers.update(mapping.values())

        owned_start = offset if chunk_index == 0 else offset + MOSS_CHUNK_OVERLAP_SECONDS / 2.0
        chunk_end = min(audio_seconds, offset + duration)
        owned_end = (
            chunk_end
            if chunk_index == len(chunks) - 1
            else chunk_end - MOSS_CHUNK_OVERLAP_SECONDS / 2.0
        )
        for item in current_full:
            center = (item["start"] + item["end"]) / 2.0
            if owned_start <= center < owned_end or (
                chunk_index == len(chunks) - 1 and center <= owned_end
            ):
                merged.append(item)
        previous_full = current_full
        chunk_summaries.append(
            {
                "chunk_id": chunk.get("chunk_id", chunk_index + 1),
                "offset": offset,
                "duration": duration,
                "generated_tokens": int(chunk.get("generated_tokens", 0)),
                "speaker_map": mapping,
                "speaker_voice_scores": voice_scores,
            }
        )

    merged.sort(key=lambda item: (item["start"], item["end"]))
    deduplicated = []
    for item in merged:
        if deduplicated:
            previous = deduplicated[-1]
            overlap = _time_overlap(item["start"], item["end"], previous["start"], previous["end"])
            smaller = max(0.01, min(item["end"] - item["start"], previous["end"] - previous["start"]))
            if (
                item["speaker"] == previous["speaker"]
                and overlap / smaller >= 0.65
                and legacy.asr_consensus_similarity(item["text"], previous["text"]) >= 0.78
            ):
                if len(legacy.content_only(item["text"])) > len(legacy.content_only(previous["text"])):
                    deduplicated[-1] = item
                continue
        deduplicated.append(item)
    payload["segments"] = _drop_redundant_cover_segments(deduplicated, legacy)
    payload["chunk_summaries"] = chunk_summaries
    payload.pop("chunks", None)
    canonical = normalize_moss_result(payload, producer="moss_chunk_merger", consumer="moss_pipeline")
    legacy.record_run_event(
        "MOSS_NORMALIZED_SCHEMA",
        producer="moss_chunk_merger",
        consumer="moss_pipeline",
        shape=schema_shape(canonical),
        raw_chunks=len(chunks),
        flat_segments=len(canonical["segments"]),
        nested_lists=0,
    )
    legacy.record_run_event(
        "MOSS_SCHEMA_COUNTS",
        producer="moss_chunk_merger",
        consumer="moss_pipeline",
        raw_chunks=len(chunks),
        flat_segments=len(canonical["segments"]),
        nested_lists=0,
    )
    from twobyteasr.speaker_evidence import label_summary
    canonical.setdefault('metadata', {})['speaker_stages'] = {
        'parsed_chunks': [label_summary(chunk.get('segments', [])) for chunk in chunks],
        'global_identities': label_summary(canonical['segments']),
    }
    return canonical


def _flatten_firered_stage5_result(value):
    """Convert the audited FireRed ASRResult exactly once at the Stage 5 boundary."""
    if value in (None, [], ()):
        return []
    if not isinstance(value, dict) or value.get("result_type") != "ASRResult":
        raise SchemaContractError(
            producer="firered_adapter",
            consumer="stage5_firered_token_boundary",
            received=value,
            expected_schema="ASRResult dict with flat segments",
        )
    return flatten_segment_tokens(
        value,
        producer="firered_adapter",
        consumer="stage5_firered_token_boundary",
    )


def transcribe_moss_global(media_path, shared_audio, legacy, cache_context):
    _parallel_cancel_poll()
    task_owner = get_runtime_context()
    # MOSS 转写必须在主进程预检 CUDA：子进程内报错只会显示为“MOSS 子进程失败”，
    # 无法给出明确原因。打包（frozen）运行没有进程内 torch——改用主运行环境
    # 的子进程探测（hardware._probe_torch_runtime），结果等价。
    if not getattr(sys, "frozen", False):
        try:
            import torch

            if not torch.cuda.is_available():
                raise RuntimeError(
                    "本机未检测到 NVIDIA CUDA GPU，无法运行 MOSS 转写——"
                    "生成字幕需要 CUDA 显卡（MOSS/FireRed/Qwen 均为 GPU 模型）。"
                )
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"MOSS CUDA 预检失败：{exc}") from exc
    else:
        from twobyteasr.hardware import ready_torch_probe

        probe = ready_torch_probe()
        if not probe.get("imported") or not probe.get("usable"):
            raise RuntimeError(
                "MOSS CUDA 预检失败：主运行环境 torch/CUDA 不可用"
                f"（imported={probe.get('imported')}, "
                f"error={probe.get('error') or probe.get('torch_error') or 'n/a'}）。"
                "MOSS/FireRed/Qwen 均为 GPU 模型，需要可用的 NVIDIA CUDA 显卡。"
            )
    from moss_worker import audio_fingerprint, INFERENCE_MODE, CACHE_VERSION
    paths = _script_paths(legacy)
    fingerprint = audio_fingerprint(shared_audio, legacy.AUDIO_SAMPLE_RATE)
    evidence = Path(cache_context["cache_dir"]) / "speaker-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    legacy.record_run_event("moss_full_context_preparing", inference_mode=INFERENCE_MODE,
        task_audio_duration=len(shared_audio) / legacy.AUDIO_SAMPLE_RATE,
        sample_rate=legacy.AUDIO_SAMPLE_RATE, sample_count=len(shared_audio),
        task_audio_fingerprint=fingerprint, cache_version=CACHE_VERSION)
    with tempfile.TemporaryDirectory(prefix="moss_bridge_") as temp_dir:
        job = _chunk_moss_audio(shared_audio, temp_dir, legacy)[0]
        output_path = os.path.join(temp_dir, "moss.json")
        command = [paths["moss_python"], "-I", paths["moss_worker"],
                   "--audio", job["audio"], "--output", output_path, "--model", MOSS_MODEL,
                   "--title", Path(media_path).stem, "--task-audio-fingerprint", fingerprint]
        print(f"[MOSS LAUNCH full_context] worker={paths['moss_worker']} runtime={paths['moss_python']} samples={len(shared_audio)} @ {legacy.AUDIO_SAMPLE_RATE}Hz", flush=True)
        lines = []
        try:
            code, lines = _run_streaming_worker(command, MOSS_TIMEOUT_SECONDS)
            _parallel_cancel_poll()
            payload = _read_moss_worker_payload(output_path, code, lines, "MOSS 整段worker",
                                               recorder=legacy.record_run_event)
        except BaseException as exc:
            lines = getattr(exc, 'output_lines', lines)
            raise
        finally:
            # Diagnostics survive failure and temp-dir cleanup; never write subtitles here.
            if Path(output_path).is_file():
                raw = Path(output_path).read_text("utf8")
                (evidence / "moss-full-context-raw.json").write_text(raw, "utf8")
                try:
                    legacy.record_run_event("moss_full_context_execution", job_id=task_owner.job_id,
                                            **json.loads(raw).get("execution", {}))
                except (ValueError, TypeError):
                    pass
            (evidence / "moss-full-context-worker.log").write_text("\n".join(lines), "utf8")
    if get_runtime_context() is not task_owner:
        raise CancelledError('MOSS旧任务结果拒绝写入新任务。')
    payload = _normalize_moss_full_context(payload, shared_audio, legacy)
    _parallel_cancel_poll()
    from twobyteasr.speaker_evidence import save_speaker_evidence
    save_speaker_evidence(evidence, "moss-full-context-parsed", payload)
    return payload


def _normalize_moss_full_context(payload, shared_audio, legacy):
    from moss_worker import audio_fingerprint, INFERENCE_MODE, CACHE_VERSION
    _validate_moss_worker_payload(payload, producer="moss_worker", consumer="moss_full_context")
    chunks = payload["chunks"]
    execution = payload.get("execution", {})
    expected = audio_fingerprint(shared_audio, legacy.AUDIO_SAMPLE_RATE)
    if (payload.get("inference_mode") != INFERENCE_MODE or payload.get("cache_version") != CACHE_VERSION
        or len(chunks) != 1 or float(chunks[0].get("offset", -1)) != 0
        or execution.get("sample_count") != len(shared_audio)
        or execution.get("sample_rate") != legacy.AUDIO_SAMPLE_RATE
        or execution.get("task_audio_fingerprint") != expected):
        raise RuntimeError("MOSS完整输入/模式/时钟校验失败；拒绝分块或不完整运输结果。")
    rows = copy.deepcopy(chunks[0]["segments"])
    duration = len(shared_audio) / legacy.AUDIO_SAMPLE_RATE
    for row in rows:
        if not str(row.get("speaker", "")).strip():
            raise RuntimeError("MOSS原生标签缺失，拒绝伪造身份。")
        if float(row["start"]) < 0 or float(row["end"]) > duration + 1:
            execution["complete"] = False
            execution.setdefault("truncation_reasons", []).append("invalid_timestamp")
        row["start"] = max(0, float(row["start"]))
        row["end"] = min(duration, float(row["end"]))
    payload["segments"] = rows
    # No local relabeling, overlap ownership windows, cross-context ECAPA or dedup.
    canonical = normalize_moss_result(payload, producer="moss_full_context", consumer="moss_pipeline")
    canonical["provenance"]["normalization"] = "single_native_context_to_flat_segments"
    from twobyteasr.speaker_evidence import label_summary
    canonical["metadata"].update(inference_mode=INFERENCE_MODE, cache_version=CACHE_VERSION,
        raw_speaker_to_internal_speaker_id={row["speaker"]: row["speaker"] for row in rows},
        speaker_stages={"parsed_chunks": [label_summary(rows)], "global_identities": label_summary(rows)})
    if not execution.get("complete"):
        legacy.add_review_item(0, "主力转写不完整", "MOSS整段生成需要复核：" + ",".join(execution.get("truncation_reasons", [])), priority=3)
    legacy.record_run_event("moss_full_context_normalized", **execution,
                           speaker_distribution=label_summary(rows))
    return canonical


def _moss_cache_reuse_receipt(source_execution):
    """Separate cached artifact measurements from this task's actual calls."""
    receipt = copy.deepcopy(source_execution)
    receipt.update(cache_hit=True, worker_pids=[], worker_count=0,
        generation_attempts=0, application_chunk_count=0, retries=[],
        input_tokens=None, generated_tokens=None, attention_backend=None, dtype=None,
        elapsed_seconds=0.0, model_load_seconds=0.0,
        peak_allocated_gb=None, peak_reserved_gb=None,
        phase='cache_reuse', measurement_origin='source_execution',
        source_execution=copy.deepcopy(source_execution))
    return receipt


def _decode_moss_full_context_cache(payload, shared_audio, legacy):
    if not isinstance(payload, dict) or not payload.get('execution', {}).get('complete'):
        raise ValueError('MOSS缓存缺少完整整段结束回执。')
    try:
        return _normalize_moss_full_context(payload, shared_audio, legacy)
    except (RuntimeError, SchemaContractError) as exc:
        raise ValueError('MOSS缓存完整输入校验失败。') from exc


def _moss_stage_signature(paths):
    from moss_worker import INFERENCE_MODE, CACHE_VERSION, PROMPT_VERSION, GENERATION_POLICY
    worker = Path(paths["moss_worker"])
    root = worker.parent.parent if worker.parent.name == "workers" else worker.parent
    implementation = root / "third_party" / "MOSS-Transcribe-Diarize" / "moss_transcribe_diarize"
    from twobyteasr.runtime_paths import resolve_model_dir
    model_root = Path(resolve_model_dir("MOSS-Transcribe-Diarize"))
    def identity(path):
        return {**_path_signature(str(path)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None}
    return {"asr_result_schema_version": ASR_RESULT_SCHEMA_VERSION, "model": MOSS_MODEL,
            "worker": identity(worker), "inference_mode": INFERENCE_MODE, "cache_version": CACHE_VERSION,
            "prompt_version": PROMPT_VERSION, "generation_policy": GENERATION_POLICY,
            "implementation": {name: identity(implementation / name) for name in (
                "inference_utils.py", "processing_moss_transcribe_diarize.py", "modeling_moss_transcribe_diarize.py", "transcript_parser.py")},
            "model_config": {name: identity(model_root / name) for name in ("config.json", "generation_config.json", "processor_config.json")},
            "model_files": _path_signature(str(model_root)), "runtime": _path_signature(paths.get("moss_python", ""))}


def precompute_moss_batch_cache(media_paths, legacy):
    """Each media task now owns its full-context worker/cache and cancellation fence.

    Do not preload a multi-task block manifest before task audio/snapshots exist.
    Model features remain internally batched within each single generation.
    """
    return


def detect_firered_vad(audio, legacy):
    paths = _script_paths(legacy)
    if not os.path.isdir(paths["firered_vad"]):
        raise RuntimeError("FireRedVAD 模型目录不存在。")
    from twobyteasr.model_integrity import verify_model_files

    verify_model_files("firered_vad", os.path.dirname(paths["firered_vad"]))
    # Frozen GUI 不带 torch 栈（spec excluded_modules），VAD 与 FireRedASR-AED
    # 同架构：在注册的 main runtime venv 子进程里跑，GUI 进程永不加载 VAD 模型。
    from twobyteasr.runtime_registry import resolve_runtime_python
    from twobyteasr.runtime_paths import detect_install_root

    python = resolve_runtime_python("main") or ('' if getattr(sys, 'frozen', False) else sys.executable)
    worker = detect_install_root() / "firered_vad_worker.py"
    if not os.path.isfile(python) or not worker.is_file():
        raise RuntimeError(f"FireRedVAD worker 运行环境缺失: python={python}, worker={worker}")
    from twobyteasr.processes import run_hidden_subprocess

    with tempfile.TemporaryDirectory(prefix="firered_vad_") as temp_dir:
        wav_path = os.path.join(temp_dir, "audio.wav")
        legacy.write_pcm16_wav(wav_path, audio)
        output_path = os.path.join(temp_dir, "regions.json")
        completed = run_hidden_subprocess(
            [
                python, '-I', "-u", str(worker),
                "--wav", wav_path,
                "--model-dir", paths["firered_vad"],
                "--output", output_path,
            ],
            purpose="FireRedVAD worker",
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=1800,
            env=utf8_worker_environment(),
        )
        if completed.returncode != 0:
            stderr_tail = (completed.stderr or completed.stdout or "")[-1200:].strip()
            raise RuntimeError(
                f"FireRedVAD worker failed (exit {completed.returncode}): {stderr_tail}"
            )
        regions = json.loads(Path(output_path).read_text(encoding="utf-8"))["regions"]
    if not regions:
        raise RuntimeError("FireRedVAD 没有检测到语音。")
    print(f"   [完成] FireRedVAD：{len(regions)} 个人声区间。")
    return regions


def detect_lightweight_vad(audio, legacy):
    """Dependency-free energy VAD for non-MOSS and online/CPU combinations.

    It is intentionally conservative: its job is only to avoid sending long
    silence to a selected ASR engine. MOSS keeps using FireRedVAD because its
    speaker/tail safety checks need the stronger independent boundary signal.
    """
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    sample_rate = int(legacy.AUDIO_SAMPLE_RATE)
    if samples.size < max(1, sample_rate // 10):
        raise RuntimeError("音频过短，无法检测有效语音。")
    frame = max(1, int(round(sample_rate * 0.030)))
    hop = max(1, int(round(sample_rate * 0.010)))
    if samples.size < frame:
        frames = samples.reshape(1, -1)
    else:
        count = 1 + (samples.size - frame) // hop
        shape = (count, frame)
        strides = (samples.strides[0] * hop, samples.strides[0])
        frames = np.lib.stride_tricks.as_strided(samples, shape=shape, strides=strides)
    rms = np.sqrt(np.mean(np.square(frames, dtype=np.float32), axis=1) + 1e-10)
    peak = float(np.max(rms))
    floor = float(np.percentile(rms, 30))
    threshold = max(1e-4, floor * 2.2, peak * 0.025)
    active = rms >= threshold
    if not np.any(active):
        raise RuntimeError("轻量静音检测没有发现有效语音。")

    pad_frames = max(1, int(round(0.18 / (hop / sample_rate))))
    active_indices = np.flatnonzero(active)
    padded = np.zeros_like(active, dtype=bool)
    for index in active_indices:
        padded[max(0, index - pad_frames): min(len(padded), index + pad_frames + 1)] = True

    regions = []
    start = None
    for index, is_active in enumerate(np.append(padded, False)):
        if is_active and start is None:
            start = index
        elif not is_active and start is not None:
            begin = start * hop / sample_rate
            end = min(samples.size / sample_rate, (index * hop + frame) / sample_rate)
            if end - begin >= 0.18:
                if regions and begin - regions[-1]["end"] <= 0.30:
                    regions[-1]["end"] = end
                else:
                    regions.append({"start": begin, "end": end})
            start = None
    if not regions:
        raise RuntimeError("轻量静音检测没有形成可用语音区间。")
    print(f"   [完成] 轻量静音检测：{len(regions)} 个人声区间（无需 FireRedVAD）。")
    return regions


def _time_overlap(left_start, left_end, right_start, right_end):
    return max(0.0, min(left_end, right_end) - max(left_start, right_start))


def _distributed_words(text, start, end, confidence, legacy):
    chars = list(legacy.content_only(text))
    if not chars:
        return []
    duration = max(0.01, end - start)
    return [
        legacy.WordUnit(
            start + duration * index / len(chars),
            start + duration * (index + 1) / len(chars),
            char,
            confidence,
        )
        for index, char in enumerate(chars)
    ]



def _load_host_encoder(legacy):
    paths = _script_paths(legacy)
    model_dir = paths["speaker_embedding"]
    if not os.path.isfile(os.path.join(model_dir, "embedding_model.ckpt")):
        raise RuntimeError("缺少 ECAPA 声纹模型")
    import warnings

    import torchaudio

    if not hasattr(torchaudio, "list_audio_backends"):
        torchaudio.list_audio_backends = lambda: ["soundfile"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from speechbrain.inference.speaker import EncoderClassifier
        from speechbrain.utils.fetching import LocalStrategy

        encoder = EncoderClassifier.from_hparams(
            source=model_dir,
            savedir=model_dir,
            overrides={"pretrained_path": model_dir},
            local_strategy=LocalStrategy.NO_LINK,
            run_opts={"device": "cpu"},
        )
    return encoder


def apply_registered_host_voiceprints(
    moss_segments,
    host_speakers,
    shared_audio,
    legacy,
    candidate_speakers=None,
    runtime_context=None,
):
    """Map every credible MOSS label onto enrolled hosts before final filtering."""
    fallback_hosts = list(host_speakers)
    candidate_speakers = list(candidate_speakers or host_speakers)
    if shared_audio is None or not host_speakers:
        return host_speakers, moss_segments
    load_registry = getattr(legacy, "load_host_voiceprint_registry", None)
    if load_registry is None:
        return host_speakers, moss_segments
    registry = load_registry()
    enrolled = list(registry.get("hosts") or [])
    if len(enrolled) < 1:
        print("   [主播声纹] 未找到已注册原型，继续用 MOSS 自动标签。")
        return host_speakers, moss_segments

    import numpy as np

    # 不做整轨 asarray：shared_audio 可能是 mmap 或非 float32 数组，
    # 整轨转换会在长素材上物化全量副本；按说话人切片后再转换，峰值受
    # SPEAKER_EMBEDDING_MAX_AUDIO_SECONDS 约束。
    sample_rate = int(getattr(legacy, "AUDIO_SAMPLE_RATE", 16000))
    max_seconds = float(SPEAKER_EMBEDDING_MAX_AUDIO_SECONDS)

    def speaker_signal(speaker):
        rows = [
            item
            for item in moss_segments
            if str(item.get("speaker") or "S00") == speaker
        ]
        if not rows:
            return None
        rows.sort(key=lambda item: float(item["end"]) - float(item["start"]), reverse=True)
        chunks = []
        total = 0.0
        for row in rows:
            start = max(0.0, float(row["start"]))
            end = max(start + 0.05, float(row["end"]))
            a = int(start * sample_rate)
            b = min(len(shared_audio), int(end * sample_rate))
            if b - a < int(0.35 * sample_rate):
                continue
            piece = np.asarray(shared_audio[a:b], dtype=np.float32)
            chunks.append(piece)
            total += (b - a) / sample_rate
            if total >= max_seconds:
                break
        if not chunks:
            return None
        signal = np.concatenate(chunks)
        if len(signal) > int(max_seconds * sample_rate):
            signal = signal[: int(max_seconds * sample_rate)]
        return signal

    signals = []
    live_hosts = []
    for speaker in candidate_speakers:
        segment_count = sum(
            str(item.get("speaker") or "S00") == speaker
            for item in moss_segments
        )
        if segment_count < REGISTERED_HOST_MIN_SEGMENTS:
            continue
        signal = speaker_signal(speaker)
        if signal is None:
            continue
        signals.append(signal)
        live_hosts.append(speaker)
    if not signals:
        print("   [主播声纹] 当前素材无法提取稳定主播片段，跳过注册匹配。")
        return host_speakers, moss_segments

    try:
        encoder = _load_host_encoder(legacy)
        live_matrix = _encode_speaker_signals(encoder, signals)
    except Exception as exc:
        print(f"   [主播声纹] ECAPA 不可用，跳过注册匹配：{exc}")
        return host_speakers, moss_segments
    finally:
        gc.collect()

    proto = np.asarray([item["embedding"] for item in enrolled], dtype=np.float32)
    norms = np.linalg.norm(proto, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-8)
    proto = proto / norms

    assignment = {}
    rejected = {}
    for live_index, speaker in enumerate(live_hosts):
        scores = np.asarray(live_matrix[live_index] @ proto.T, dtype=np.float32)
        ranking = np.argsort(scores)[::-1]
        proto_index = int(ranking[0])
        score = float(scores[proto_index])
        second_score = float(scores[int(ranking[1])]) if len(ranking) > 1 else -1.0
        margin = score - second_score if len(ranking) > 1 else 1.0
        if score < REGISTERED_HOST_MIN_SIMILARITY or margin < REGISTERED_HOST_MIN_MARGIN:
            rejected[speaker] = {
                "score": round(score, 3),
                "margin": round(margin, 3),
            }
            continue
        host = enrolled[proto_index]
        label = str(host.get("label") or "").strip() or f"S{len(assignment)+1:02d}"
        assignment[speaker] = {
            "label": label,
            "name": str(host.get("name") or host.get("id") or label),
            "score": round(score, 3),
            "margin": round(margin, 3),
        }
    if not assignment:
        print("   [主播声纹] 注册原型未命中足够相似度，保留 MOSS 标签。")
        return host_speakers, moss_segments

    # A confident enrolled match can rename a raw MOSS label onto a label that is
    # already used by another, lower-confidence speaker (for example raw S02 is
    # confidently 主播A/S01 while raw S01 is the second, stable host).  Keeping
    # the rejected raw label unchanged would then merge both people into S01 and
    # silently remove the second speaker track.  Preserve every speaker already
    # selected by the host filter, but leave low-confidence fallbacks anonymous.
    label_order = []
    for host in enrolled:
        label = str(host.get("label") or "").strip()
        if label and label not in label_order:
            label_order.append(label)
    used_labels = {info["label"] for info in assignment.values()}
    requested = int(
        (
            runtime_context.expected_speakers
            if runtime_context is not None
            else getattr(legacy, "RUNTIME_EXPECTED_SPEAKERS", 0)
        )
        or 0
    )
    # 自动模式必须保留主播筛选阶段已经确认的未注册主播。过去这里按
    # “已注册声纹数”截断，注册两人后第三位未注册主播会再次被静默丢掉。
    target_count = requested or min(
        MOSS_AUTO_MAX_HOST_SPEAKERS,
        len(fallback_hosts),
    )
    fallback_assignment = {}
    for speaker in fallback_hosts:
        if speaker in assignment or len(used_labels) >= target_count:
            continue
        available = next((label for label in label_order if label not in used_labels), "")
        if not available:
            available = speaker if speaker not in used_labels else ""
        if not available:
            continue
        fallback_assignment[speaker] = {
            "label": available,
            "score": rejected.get(speaker, {}).get("score"),
            "margin": rejected.get(speaker, {}).get("margin"),
        }
        used_labels.add(available)

    for item in moss_segments:
        speaker = str(item.get("speaker") or "S00")
        mapped = assignment.get(speaker) or fallback_assignment.get(speaker)
        if not mapped:
            continue
        item["speaker_raw"] = speaker
        item["speaker"] = mapped["label"]
        if mapped.get("name"):
            item["speaker_host_name"] = mapped["name"]
            item["speaker_host_score"] = mapped["score"]
        else:
            item["speaker_voiceprint_fallback"] = True

    new_hosts = []
    seen = set()
    for label in label_order:
        if any(
            v["label"] == label
            for v in (*assignment.values(), *fallback_assignment.values())
        ) and label not in seen:
            new_hosts.append(label)
            seen.add(label)
    if len(new_hosts) < target_count:
        for speaker in fallback_hosts:
            label = (
                assignment.get(speaker, {}).get("label")
                or fallback_assignment.get(speaker, {}).get("label")
                or speaker
            )
            if label not in seen:
                new_hosts.append(label)
                seen.add(label)
            if len(new_hosts) >= target_count:
                break
    detail = "，".join(
        f"{info['label']}={info['name']}({info['score']:.3f},余量{info['margin']:.3f}<-{src})"
        for src, info in assignment.items()
    )
    print(f"   [主播声纹] 注册匹配：{detail}")
    if fallback_assignment:
        fallback_detail = "，".join(
            f"{source}->{info['label']}"
            for source, info in fallback_assignment.items()
        )
        print(
            "   [主播声纹] 低置信稳定主播仅保留分轨、不实名："
            f"{fallback_detail}"
        )
    recorder = getattr(legacy, "record_run_event", None)
    if callable(recorder):
        recorder(
            "host_voiceprint_mapping",
            assignments=assignment,
            rejected=rejected,
            fallback_assignments=fallback_assignment,
            host_labels=new_hosts,
        )
    return new_hosts or host_speakers, moss_segments


def select_host_speakers(
    moss_segments,
    audio_seconds,
    legacy,
    runtime_context=None,
    label_source="MOSS",
):
    speakers = sorted({str(item.get("speaker") or "S00") for item in moss_segments})
    requested = int(
        (
            runtime_context.expected_speakers
            if runtime_context is not None
            else getattr(legacy, "RUNTIME_EXPECTED_SPEAKERS", 0)
        )
        or 0
    )
    max_hosts = requested or MOSS_AUTO_MAX_HOST_SPEAKERS
    if not requested and len(speakers) <= 2:
        # 1/2 人素材保留原来的快速路径。达到三位时即使是短素材也按
        # 发言量排序并受自动人数上限约束，避免短片中的一次性角色声
        # 绕过筛选，同时让稳定的第三主播正常进入分轨。
        return speakers

    bin_seconds = 60.0
    stats = {}
    for speaker in speakers:
        rows = [item for item in moss_segments if str(item.get("speaker") or "S00") == speaker]
        first = min(float(item["start"]) for item in rows)
        last = max(float(item["end"]) for item in rows)
        active_bins = {
            int(float(item["start"]) // bin_seconds)
            for item in rows
        }
        stats[speaker] = {
            "count": len(rows),
            "span_ratio": max(0.0, last - first) / max(1.0, audio_seconds),
            "bins": len(active_bins),
            "chars": sum(len(legacy.content_only(item.get("text", ""))) for item in rows),
        }
    max_bins = max(item["bins"] for item in stats.values())
    for speaker, item in stats.items():
        print(f"   [说话人候选] raw_label={speaker} label_source={label_source} timeline_span_ratio={item['span_ratio']:.4f} "
              f"candidate_min_span_ratio={MOSS_HOST_MIN_SPAN_RATIO:.2f} identity_confirmed=false")
    max_count = max(item["count"] for item in stats.values())
    eligible = [
        speaker
        for speaker, item in stats.items()
        if item["span_ratio"] >= MOSS_HOST_MIN_SPAN_RATIO
        and item["bins"] >= max(2, math.ceil(max_bins * MOSS_HOST_MIN_ACTIVE_BIN_RATIO))
        and item["count"] >= max(3, math.ceil(max_count * 0.45))
    ]
    ranked = sorted(
        # 用户明确指定人数时，从全部 MOSS 标签中选足人数；自动模式才
        # 使用持续度门槛过滤节目/角色声。
        speakers if requested else (eligible or speakers),
        key=lambda speaker: (
            stats[speaker]["bins"],
            stats[speaker]["span_ratio"],
            stats[speaker]["count"],
            stats[speaker]["chars"],
        ),
        reverse=True,
    )
    selected = ranked[:max_hosts]
    from twobyteasr.speaker_recovery import candidate_snapshot
    inventory = candidate_snapshot(moss_segments, selected, requested)
    if inventory["needs_confirmation"]:
        legacy.add_review_item(
            0.0, "说话人需要确认",
            f"检测到多个持续说话人，需要确认。请在说话人管理中试听全部 {label_source} 标签并选择主要说话人；自动筛选不代表真人身份。",
            priority=3,
        )
    detail = "，".join(
        f"{speaker}(跨{stats[speaker]['bins']}分钟窗/{stats[speaker]['span_ratio']:.0%})"
        for speaker in selected
    )
    source = "用户指定人数" if requested else "自动筛选"
    print(f"   [主播筛选] {source}，暂用 {detail}；未选标签保存在工程候选中，不自动认定为节目/角色声。")
    if requested and len(selected) < requested:
        legacy.add_review_item(
            0.0,
            "主播人数不足",
            f"预计 {requested} 位主播，但 {label_source} 只形成 {len(selected)} 个可用匿名标签",
            priority=3,
        )
        print(
            f"   [警告] 预计 {requested} 位主播，但只找到 {len(selected)} 位；"
            "不会复制或伪造第二条轨道。"
        )
    return selected


_NON_SPEECH_ONLY_RE = re.compile(
    r"^\s*(?:[\[【（(].{0,16}(?:音乐|音效|掌声|笑声|环境音|噪声|music|sfx).{0,16}[\]】）)]|"
    r"(?:音乐|音效|掌声|笑声|环境音|噪声|music|sfx))\s*$",
    re.IGNORECASE,
)


def _dialogue_coverage_mode(runtime_context, legacy):
    mode = str(
        getattr(runtime_context, "dialogue_coverage_mode", "")
        if runtime_context is not None
        else getattr(legacy, "RUNTIME_DIALOGUE_COVERAGE_MODE", "all_dialogue")
    ).strip()
    return mode if mode in {"all_dialogue", "host_priority", "host_only"} else "all_dialogue"


def _trustworthy_dialogue_text(item, text, speech_overlap, duration, legacy):
    """Reject non-speech labels and low-confidence/VAD-empty MOSS rows."""
    content = legacy.content_only(text)
    if not content or _NON_SPEECH_ONLY_RE.fullmatch(str(text or "")):
        return False
    confidence = item.get("confidence")
    if confidence is not None:
        try:
            if float(confidence) < 0.25:
                return False
        except (TypeError, ValueError):
            return False
    return speech_overlap >= min(0.12, max(0.01, duration) * 0.25)


def _firered_token_window(tokens, start, end):
    """Return a neighbourhood search window, not a matched acoustic interval.

    Neighbouring tokens can belong to another speaker. Their pooled confidence
    does not verify either clipped endpoint or simultaneous speech.
    """
    nearby = [
        token for token in (tokens or [])
        if float(token.get("end", 0.0)) >= float(start) - MOSS_SPEAKER_PAD_SECONDS
        and float(token.get("start", 0.0)) <= float(end) + MOSS_SPEAKER_PAD_SECONDS
        and float(token.get("end", 0.0)) > float(token.get("start", 0.0))
    ]
    if not nearby:
        return None
    tolerance = float(FIRERED_EFFECTIVE_TOKEN_OUTSIDE_TOLERANCE_SECONDS)
    window_start = max(float(start) - tolerance, min(float(item["start"]) for item in nearby))
    window_end = min(float(end) + tolerance, max(float(item["end"]) for item in nearby))
    confidences = []
    for item in nearby:
        try:
            value = float(item.get("confidence"))
        except (TypeError, ValueError):
            continue
        if 0.0 <= value <= 1.0:
            confidences.append(value)
    return {
        "start": max(0.0, window_start),
        "end": max(max(0.0, window_start) + 0.01, window_end),
        "confidence": sum(confidences) / len(confidences) if confidences else 0.0,
        "token_count": len(nearby),
        "kind": "bounded_search_window",
        "independent_acoustic": False,
        "neighbourhood_seconds": float(MOSS_SPEAKER_PAD_SECONDS),
        "clipping_seconds": tolerance,
    }


def build_moss_host_primary_segments(
    moss_payload,
    firered_tokens,
    speech_regions,
    audio_seconds,
    legacy,
    shared_audio=None,
    runtime_context=None,
):
    """MOSS 主播文本和时间作为骨架；FireRed 只提供独立文字证据，不再接管时间。"""
    try:
        legacy.record_run_event(
            "STAGE5_INPUT_SCHEMA",
            producer="moss_pipeline+firered_adapter",
            consumer="build_moss_host_primary_segments",
            moss_shape=schema_shape(moss_payload),
            firered_shape=schema_shape(firered_tokens),
            expected_schema="MOSS ASRResult + Sequence[ASRSegment]",
        )
    except Exception:
        pass
    moss_payload = validate_canonical_result(
        moss_payload,
        producer="moss_pipeline",
        consumer="build_moss_host_primary_segments",
        allow_empty=False,
    )
    firered_tokens = validate_flat_segments(
        firered_tokens,
        producer="stage5_firered_token_boundary",
        consumer="build_moss_host_primary_segments",
    )
    # 旧缓存也可能来自尚未做覆盖式去重的分块版本，因此主稿入口再做一次幂等清理。
    moss_segments = _drop_redundant_cover_segments(
        list(moss_payload.get("segments", [])), legacy
    )
    moss_payload["segments"] = moss_segments
    from twobyteasr.speaker_evidence import label_summary
    speaker_stages = moss_payload.setdefault("metadata", {}).setdefault("speaker_stages", {})
    speaker_stages["before_host_filter"] = label_summary(moss_segments)
    host_speakers = select_host_speakers(
        moss_segments,
        audio_seconds,
        legacy,
        runtime_context=runtime_context,
    )
    all_speakers = sorted(
        {str(item.get("speaker") or "S00") for item in moss_segments}
    )
    host_speakers, moss_segments = apply_registered_host_voiceprints(
        moss_segments,
        host_speakers,
        shared_audio,
        legacy,
        candidate_speakers=all_speakers,
        runtime_context=runtime_context,
    )
    moss_payload["segments"] = moss_segments
    moss_payload["host_speakers"] = host_speakers
    speaker_stages["after_registered_identity"] = label_summary(moss_segments)
    speaker_stages["selected_hosts"] = {"labels": list(host_speakers)}
    identities = {}
    for row in moss_segments:
        raw_label = str(row.get('speaker_raw') or row['speaker'])
        identities[raw_label] = str(row['speaker'])
    moss_payload['metadata']['raw_speaker_to_internal_speaker_id'] = identities
    legacy.record_run_event('moss_identity_mapping', raw_speaker_to_internal_speaker_id=identities)
    all_speakers = sorted(
        {str(item.get("speaker") or "S00") for item in moss_segments}
    )
    coverage_mode = _dialogue_coverage_mode(runtime_context, legacy)
    included_speakers = (
        set(host_speakers)
        if coverage_mode == "host_only"
        else set(all_speakers)
    )
    _rescue_transient_host_segments(
        moss_segments,
        host_speakers,
        shared_audio,
        legacy,
    )
    filtered_labels = {}
    for item in moss_segments:
        speaker = str(item.get("speaker") or "S00")
        if speaker in host_speakers:
            continue
        summary = filtered_labels.setdefault(speaker, {"segments": 0, "seconds": 0.0})
        summary["segments"] += 1
        summary["seconds"] += max(0.0, float(item["end"]) - float(item["start"]))
    for summary in filtered_labels.values():
        summary["seconds"] = round(summary["seconds"], 3)
    legacy.record_run_event(
        "host_filter_summary",
        dialogue_coverage_mode=coverage_mode,
        host_labels=list(host_speakers),
        filtered_labels=filtered_labels,
    )
    tokens = []
    for token in firered_tokens:
        text = legacy.clean_subtitle_text(token.get("text", ""))
        if not legacy.content_only(text):
            continue
        tokens.append(
            {
                "text": text,
                "start": float(token["start"]),
                "end": float(token["end"]),
                "confidence": float(token.get("confidence", 0.75)),
                "source": str(token.get("source") or ""),
                "alignment_key": str(token.get("alignment_key") or ""),
            }
        )
    # Forced-aligner tokens are this transcript's own words placed in time:
    # timing evidence only, never an independent second opinion on the text.
    aligner_mode = bool(tokens) and all(token["source"] == "qwen-forced-aligner" for token in tokens)
    from twobyteasr.language_rules import JA as _JA, japanese_display_source
    from twobyteasr.forced_alignment import segment_alignment_key
    japanese = getattr(runtime_context, "task_language", "") == _JA
    result = []
    dropped_no_speech = 0
    for index, moss in enumerate(moss_segments):
        speaker = str(moss.get("speaker") or "S00")
        if speaker not in included_speakers:
            continue
        start = max(0.0, float(moss["start"]))
        end = max(start + 0.01, float(moss["end"]))
        raw_moss_text = str(moss.get("text", "") or "")
        moss_text = legacy.clean_subtitle_text(japanese_display_source(raw_moss_text) if japanese else raw_moss_text)
        if not legacy.content_only(moss_text):
            continue
        speech_overlap = sum(
            _time_overlap(start, end, float(region["start"]), float(region["end"]))
            for region in speech_regions
        )
        if not _trustworthy_dialogue_text(
            moss, moss_text, speech_overlap, end - start, legacy
        ):
            dropped_no_speech += 1
            continue

        nearby_tokens = [
            token
            for token in tokens
            if token["end"] >= start - MOSS_SPEAKER_PAD_SECONDS
            and token["start"] <= end + MOSS_SPEAKER_PAD_SECONDS
        ]
        aligned_window = None
        if aligner_mode:
            key = segment_alignment_key(moss.get("speaker"), moss["start"], moss["end"])
            own = [token for token in tokens if token["alignment_key"] == key]
            nearby_tokens = own
            raw_firered, firered_candidate, firered_similarity, firered_window = "", "", 0.0, None
            if own:
                aligned_window = {"start": min(t["start"] for t in own), "end": max(t["end"] for t in own),
                                  "job": key, "token_count": len(own), "kind": "forced_alignment_span"}
        else:
            raw_firered = legacy.clean_subtitle_text(
                "".join(token["text"] for token in nearby_tokens)
            )
            firered_candidate, firered_similarity = legacy.best_alternate_window(
                moss_text, raw_firered
            )
            if firered_similarity < 0.42:
                firered_candidate = ""
            firered_window = (
                _firered_token_window(nearby_tokens, start, end)
                if firered_candidate
                else None
            )
        if (
            coverage_mode == "host_priority"
            and speaker not in host_speakers
            and firered_similarity < 0.64
        ):
            continue
        confidence = 0.78 if firered_similarity >= 0.78 else (0.64 if firered_similarity >= 0.55 else 0.50)
        if aligner_mode:
            # No second recognizer text here (the aligner reuses this text):
            # a neutral baseline; the Qwen review decides real disputes.
            confidence = 0.64
        overlap_conflict = any(
            other_index != index
            and str(other.get("speaker") or "S00") != speaker
            and _time_overlap(start, end, float(other["start"]), float(other["end"]))
            >= MOSS_OVERLAP_CONFLICT_SECONDS
            for other_index, other in enumerate(moss_segments)
        )
        rescued_from = str(moss.get("speaker_rescued_from") or "")
        segment = legacy.SpeechSegment(
            segment_id=0,
            start=start,
            end=max(end, start + legacy.MIN_SUBTITLE_SECONDS),
            text=moss_text,
            confidence=confidence,
            words=_distributed_words(moss_text, start, end, confidence, legacy),
            speaker=speaker,
            moss_text=moss_text,
            moss_context=moss_text,
            alternate_text=firered_candidate,
            alternate_context=raw_firered,
            overlapping_speaker_conflict=overlap_conflict,
            timing_locked=overlap_conflict,
            firered_text=firered_candidate,
            firered_start=(firered_window["start"] if firered_window else 0.0),
            firered_end=(firered_window["end"] if firered_window else 0.0),
            firered_alignment_confidence=(
                firered_window["confidence"] if firered_window else 0.0
            ),
            primary_source=(
                "moss-host-rescued" if rescued_from
                else "moss-host" if speaker in host_speakers
                else "moss-dialogue"
            ),
            reference_consensus=firered_similarity,
        )
        if firered_window:
            segment.caption_arbitration = dict(segment.caption_arbitration or {}, timing_evidence=dict(firered_window))
        if aligned_window:
            segment.caption_arbitration = dict(segment.caption_arbitration or {},
                                               forced_alignment_window=dict(aligned_window))
        segment.caption_arbitration['word_timing'] = {'basis': 'uniform_display_estimate', 'source': 'moss_sentence_bounds'}
        if overlap_conflict:
            legacy.add_review_item(
                start,
                "说话人重叠",
                "主播与节目/角色声重叠，保留 MOSS 主播稿并冻结跨说话人替换",
                moss_text,
                priority=3,
            )
        if rescued_from:
            legacy.add_review_item(
                start,
                "临时说话人找回",
                f"MOSS {rescued_from} 仅短暂出现；ECAPA 以 "
                f"{float(moss.get('speaker_rescue_score', 0.0)):.3f} 分、"
                f"{float(moss.get('speaker_rescue_margin', 0.0)):.3f} 差值认领为 {speaker}",
                moss_text,
                priority=2,
            )
        result.append(segment)

    result.sort(key=lambda segment: (segment.start, segment.end))
    for segment_id, segment in enumerate(result, 1):
        segment.segment_id = segment_id
    if not result:
        raise RuntimeError("MOSS 没有筛出可用的主播字幕。")
    print(
        f"   [完成] MOSS 对白主稿：{len(result)} 段；覆盖模式 {coverage_mode}；"
        f"未再补入 {sum(1 for token in tokens if not any(segment.start - 0.2 <= (token['start'] + token['end']) / 2.0 <= segment.end + 0.2 for segment in result))} "
        + ("个段外对齐时间片（属于未选说话人）。" if aligner_mode else "个段外 FireRed 字词。")
    )
    if dropped_no_speech:
        print(f"   [VAD拒绝] {dropped_no_speech} 个 MOSS 段缺少实际人声覆盖。")
    return result


def attach_qwen_review_evidence(segments, qwen_chunks, legacy):
    """保留 Qwen 原始时间窗，并允许它与 MOSS 形成独立共识。"""
    if not legacy.USE_QWEN_ASR_REFERENCE:
        # 纵深防御：即使上游漏了短路，关闭开关时也绝不附着 Qwen 证据。
        return segments
    accepted = 0
    for segment in segments:
        contexts = []
        matched_chunks = []
        for chunk in qwen_chunks or []:
            if (
                float(chunk["end"]) < segment.start - legacy.QWEN_ASR_TEXT_ALIGNMENT_PAD_SECONDS
                or float(chunk["start"]) > segment.end + legacy.QWEN_ASR_TEXT_ALIGNMENT_PAD_SECONDS
            ):
                continue
            text = legacy.clean_subtitle_text(chunk.get("text", ""))
            if legacy.content_only(text):
                contexts.append(text)
                matched_chunks.append(chunk)
        raw_context = legacy.clean_subtitle_text(" ".join(contexts))
        segment.qwen_asr_context = raw_context
        if not raw_context:
            continue

        from twobyteasr.model_execution import review_model_id
        model = review_model_id(getattr(legacy, "QWEN_ASR_BACKEND", "local"))
        if model == 'api':
            model = 'asr-api:' + str(getattr(legacy, 'QWEN_ASR_API_MODEL', '') or 'unrecorded')
        decision = dict(segment.caption_arbitration or {})
        coverage = dict(decision.get("source_coverage") or {})
        coverage[model] = [dict(start_ms=round(float(chunk['start']) * 1000),
            end_ms=round(float(chunk['end']) * 1000), text=str(chunk.get('text') or ''),
            confidence=chunk.get('confidence'), coverage_basis='observed_model_window')
            for chunk in matched_chunks]
        decision['source_coverage'] = coverage
        segment.caption_arbitration = decision

        primary_candidate, primary_score = legacy.best_alternate_window(
            segment.text, raw_context
        )
        moss_candidate, moss_score = legacy.best_alternate_window(
            segment.moss_text, raw_context
        )
        moss_supported = (
            moss_candidate
            and moss_score >= 0.72
            and legacy.asr_consensus_similarity(segment.moss_text, moss_candidate) >= 0.72
        )
        # 若 Qwen 的原始窗完整支持 MOSS（尤其补回 FireRed 漏掉的句首/句尾），
        # 优先保留这份独立候选；不能总裁成最像 FireRed 的等长文本。
        chunk_confidences = []
        for chunk in matched_chunks:
            try:
                confidence = float(chunk.get("confidence"))
            except (TypeError, ValueError):
                continue
            if 0.0 <= confidence <= 1.0:
                chunk_confidences.append(confidence)
        qwen_confidence = (
            sum(chunk_confidences) / len(chunk_confidences)
            if chunk_confidences
            else 0.0
        )
        if moss_supported and (
            moss_score >= primary_score + 0.02
            or len(legacy.content_only(moss_candidate))
            > len(legacy.content_only(primary_candidate))
        ):
            segment.qwen_asr_text = moss_candidate
            segment.qwen_confidence = qwen_confidence
            accepted += 1
        elif primary_candidate and primary_score >= legacy.QWEN_ASR_ALTERNATE_MIN_SIMILARITY:
            segment.qwen_asr_text = primary_candidate
            segment.qwen_confidence = qwen_confidence
            accepted += 1
        elif moss_supported:
            segment.qwen_asr_text = moss_candidate
            segment.qwen_confidence = qwen_confidence
            accepted += 1
    review_label = "Qwen3-ASR"
    if str(getattr(legacy, "QWEN_ASR_BACKEND", "")) == "api":
        try:
            from twobyteasr.llm_config import (
                asr_api_display,
                qwen_asr_endpoint_from_settings,
            )

            review_label = asr_api_display(
                qwen_asr_endpoint_from_settings(
                    getattr(legacy, "RUNTIME_SETTINGS", {}) or {}
                )
            )
        except Exception:
            review_label = "ASR API"
    print(f"   [完成] {review_label} 复核：{accepted}/{len(segments)} 段获得独立文字证据。")
    return segments


def build_alternate_primary_segments(references, timeline_tokens, legacy, backend):
    """Convert any non-MOSS recognizer into the pipeline's primary segment contract."""
    # 三十八轮：API diarization 的 file-local speaker（S00/S01…）经
    # SpeakerIdentityResolver 缝隙透传（未来接 embedding/voice profile 时
    # 在此映射为稳定身份，不动管线契约）。
    from twobyteasr.speaker_identity import speaker_identity_resolver

    resolver = speaker_identity_resolver()
    segments = []
    for row in sorted(references or [], key=lambda item: (float(item["start"]), float(item["end"]))):
        start = max(0.0, float(row.get("start", 0.0)))
        end = max(start + 0.04, float(row.get("end", start)))
        text = legacy.clean_subtitle_text(row.get("text", ""))
        if not legacy.content_only(text):
            continue
        local_speaker = str(row.get("speaker") or "S00")
        speaker = resolver.resolve("", local_speaker)
        row_tokens = list(row.get("tokens") or [])
        streaming=backend in {'vibevoice_1_5b','vibevoice_7b'}
        if streaming:
            from twobyteasr.optional_timing import exact_tokens
            row_tokens=row_tokens or exact_tokens(row,timeline_tokens)
        if not row_tokens and not streaming:
            row_tokens = [
                item
                for item in (timeline_tokens or [])
                if start <= (float(item.get("start", 0.0)) + float(item.get("end", 0.0))) / 2.0 <= end
            ]
        words = []
        for token in row_tokens:
            token_text = legacy.clean_subtitle_text(token.get("text", ""))
            if not legacy.content_only(token_text):
                continue
            words.append(
                legacy.WordUnit(
                    max(start, float(token.get("start", start))),
                    min(end, max(float(token.get("end", end)), float(token.get("start", start)) + 0.02)),
                    token_text,
                    float(token.get("confidence", 0.78)),
                )
            )
        if not words and not streaming:
            words = _distributed_words(text, start, end, 0.76, legacy)
        segments.append(
            legacy.SpeechSegment(
                segment_id=len(segments) + 1,
                start=start,
                end=end,
                text=text,
                confidence=float(row.get("confidence") if row.get("confidence") is not None else (min((w.probability for w in words),default=0.0) if streaming else 0.78)),
                words=words,
                speaker=speaker,
                moss_text="",
                moss_context="",
                primary_source=str(row.get("source") or f"{backend}-primary"),
            )
        )
        segment = segments[-1]
        if row.get('speaker_evidence'):
            segment.caption_arbitration['speaker_evidence']=copy.deepcopy(row['speaker_evidence'])
        if streaming:
            segment.caption_arbitration.update(native_model_probability=None,
                confidence_kind='acoustic_alignment_support' if words else 'unknown',
                timing_precision='word-span' if words else 'chunk',
                streaming_chunk_index=row.get('chunk_index'),native_timestamp_source='streaming_chunk_bounds')
            segment.final_timing_owner='FireRed acoustic word alignment' if words else 'VibeVoice chunk bounds (word alignment unavailable)'
            segment.timing_locked=not bool(words)
            if not words:
                legacy.add_review_item(start,'VibeVoice 字级对齐未完成','保留主转写文字、原生身份和块级范围；未知模型概率不作为零概率。',priority=2)
            continue
        # Independent text is evidence, never a replacement word sequence for
        # an unrelated API transcript. Project matching anchors onto this text.
        nearby = [token for token in (timeline_tokens or [])
                  if float(token.get('end',0)) >= start and float(token.get('start',0)) <= end]
        raw_firered = legacy.clean_subtitle_text(''.join(str(token.get('text','')) for token in nearby))
        candidate, similarity = legacy.best_alternate_window(text, raw_firered)
        coverage = legacy.firered_anchor_coverage(segment, nearby)
        if candidate and similarity >= .42 and coverage['coverage'] >= .55:
            window = _firered_token_window(nearby, start, end)
            if window:
                segment.firered_text = candidate
                segment.alternate_text = candidate
                segment.alternate_context = raw_firered
                segment.firered_start = window['start']
                segment.firered_end = window['end']
                segment.firered_alignment_confidence = min(window['confidence'], coverage['coverage'])
                segment.reference_consensus = similarity
                segment.caption_arbitration = dict(segment.caption_arbitration or {}, timing_evidence=dict(window))
        primary_words_match = bool(row.get('tokens')) and legacy.content_only(''.join(word.text for word in segment.words)) == legacy.content_only(text)
        if legacy.content_only(''.join(word.text for word in segment.words)) != legacy.content_only(text):
            segment.words = _distributed_words(text, start, end, float(row.get('confidence',.76)), legacy)
        native_sentence = bool(row.get('timestamp_source')) and row.get('timestamp_source') != 'request_bounds_coarse'
        segment.words = legacy.segment_content_timeline(segment, () if primary_words_match or native_sentence else nearby)
        if primary_words_match:
            segment.final_timing_owner=f'{backend.upper()} word timestamps'
        elif native_sentence:
            segment.final_timing_owner=f'{backend.upper()} native sentence timestamps'
    if not segments:
        raise RuntimeError(f"{backend} 主力转写没有生成有效文字。")
    legacy.record_run_event(
        "alternate_primary_asr",
        backend=backend,
        segments=len(segments),
        diarization=False,
    )
    return segments


def alternate_dialogue_coverage_signature(backend, speaker_mode, runtime_context, legacy):
    if backend == "moss" and speaker_mode == "moss":
        return {}
    return {"alternate_coverage_policy": "anonymous-primary-preserving-trustworthy-firered-v1",
            "alternate_coverage_mode": _dialogue_coverage_mode(runtime_context, legacy),
            "alternate_speaker_backend": speaker_mode,
            "alternate_expected_speakers": int(getattr(runtime_context, "expected_speakers", 0) or 0)}


def apply_alternate_dialogue_coverage(
    segments, references, timeline_tokens, speech_regions, audio_seconds,
    legacy, backend, runtime_context=None,
):
    """Filter existing alternate objects; anonymous candidates are not true identities."""
    mode = _dialogue_coverage_mode(runtime_context, legacy)
    rows = [row for row in sorted(references or [], key=lambda row: (float(row["start"]), float(row["end"])))
            if legacy.content_only(legacy.clean_subtitle_text(row.get("text", "")))]
    if len(rows) != len(segments):
        raise RuntimeError("独立主稿覆盖筛选的原始证据数量不一致；未猜测说话人或复制字幕。")
    pairs = []
    for segment, source_row in zip(segments, rows):
        expected_start = max(0.0, float(source_row.get("start", 0.0)))
        expected_end = max(expected_start + 0.04, float(source_row.get("end", expected_start)))
        if (segment.text != legacy.clean_subtitle_text(source_row.get("text", ""))
                or abs(segment.start - expected_start) > 1e-8
                or abs(segment.end - expected_end) > 1e-8):
            raise RuntimeError("独立主稿覆盖筛选的原始文字或时间证据不一致；未猜测归属。")
        row = dict(source_row, speaker=segment.speaker)
        if backend.startswith("vibevoice_"):
            # Chunk generation has no model probability. Alignment confidence
            # must not be interpreted as native zero-confidence evidence.
            row["confidence"] = None
        pairs.append((segment, row))
    speaker_backend = str(getattr(runtime_context, "speaker_source", "") or
                          ("native" if backend.startswith("vibevoice_") else backend))
    label_source = (
        backend if speaker_backend == "native" else speaker_backend)
    candidates = sorted({str(segment.speaker) for segment in segments})
    selected = select_host_speakers(
        [row for _segment, row in pairs], audio_seconds, legacy,
        runtime_context=runtime_context, label_source=label_source,
    ) if mode != "all_dialogue" else []
    kept, decisions = [], []
    for segment, row in pairs:
        reason, similarity = "all_dialogue", None
        retain = True
        if mode != "all_dialogue":
            overlap = sum(_time_overlap(segment.start, segment.end,
                          float(region["start"]), float(region["end"])) for region in speech_regions)
            retain = _trustworthy_dialogue_text(row, segment.text, overlap,
                                                segment.end - segment.start, legacy)
            reason = "trustworthy_dialogue" if retain else "no_reliable_speech"
            if retain and segment.speaker not in selected:
                if mode == "host_only":
                    retain, reason = False, "outside_selected_candidates"
                else:
                    nearby = [token for token in timeline_tokens or []
                              if float(token.get("end", 0)) >= segment.start - MOSS_SPEAKER_PAD_SECONDS
                              and float(token.get("start", 0)) <= segment.end + MOSS_SPEAKER_PAD_SECONDS]
                    context = legacy.clean_subtitle_text("".join(str(token.get("text", "")) for token in nearby))
                    _candidate, similarity = legacy.best_alternate_window(segment.text, context)
                    retain = similarity >= 0.64
                    reason = "independent_firered_support" if retain else "noncandidate_without_firered_support"
        if retain:
            kept.append(segment)
        decisions.append(dict(segment_id=segment.segment_id, speaker=segment.speaker,
                              start=segment.start, end=segment.end, retained=retain,
                              reason=reason, firered_similarity=similarity))
    summary = dict(dialogue_coverage_mode=mode, backend=backend,
                   primary_backend=backend, speaker_backend=speaker_backend,
                   host_labels=list(selected), candidate_labels=candidates,
                   before_segments=len(segments), after_segments=len(kept),
                   filtered_labels={speaker: dict(segments=sum(not row["retained"] and row["speaker"] == speaker for row in decisions))
                                    for speaker in candidates},
                   executed=True, identity_confirmed=False,
                   selection_source="anonymous_timeline_persistence_and_text_amount",
                   needs_confirmation=mode != "all_dialogue", decisions=decisions)
    # Execute outside the cached conversion so every job records its own policy.
    legacy.record_run_event("host_filter_summary", **summary)
    if runtime_context is not None:
        recovery = getattr(runtime_context, "speaker_recovery", None)
        if isinstance(recovery, dict):
            recovery["coverage_filter"] = copy.deepcopy(summary)
            if mode != "all_dialogue":
                recovery["needs_confirmation"] = True
    if mode != "all_dialogue":
        legacy.add_review_item(0.0, "主要说话人候选需要确认",
            "已按匿名标签的持续度和发言量执行覆盖筛选；没有声纹或真人身份确认。原始全部候选及筛选区间保存在工程证据中。",
            priority=3)
    if not kept:
        raise RuntimeError("覆盖筛选未保留可靠对白；请使用全部对白并在说话人管理中确认匿名候选。")
    if mode != "all_dialogue":
        for index, segment in enumerate(kept, 1):
            segment.segment_id = index
    return kept


def add_qwen_skeleton_gap_review_items(segments, qwen_chunks, moss_payload, legacy):
    """Flag text supported by Qwen but excluded from the host-only MOSS skeleton."""
    if not legacy.USE_QWEN_ASR_REFERENCE:
        return 0
    host_speakers = set(moss_payload.get("host_speakers") or [])
    if not host_speakers or not qwen_chunks:
        return 0
    candidates = []
    for item in moss_payload.get("segments") or []:
        speaker = str(item.get("speaker") or "S00")
        if speaker in host_speakers:
            continue
        start = max(0.0, float(item.get("start", 0.0)))
        end = max(start, float(item.get("end", start)))
        duration = end - start
        text = legacy.clean_subtitle_text(item.get("text", ""))
        if duration < 0.45 or len(legacy.content_only(text)) < 3:
            continue
        host_overlap = sum(
            _time_overlap(start, end, segment.start, segment.end)
            for segment in segments
        )
        if host_overlap / max(0.01, duration) >= 0.20:
            continue
        qwen_context = legacy.clean_subtitle_text(
            " ".join(
                legacy.clean_subtitle_text(chunk.get("text", ""))
                for chunk in qwen_chunks
                if float(chunk.get("end", 0.0)) >= start - 0.30
                and float(chunk.get("start", 0.0)) <= end + 0.30
            )
        )
        if not legacy.content_only(qwen_context):
            continue
        qwen_candidate, similarity = legacy.best_alternate_window(text, qwen_context)
        if not qwen_candidate or similarity < 0.64:
            continue
        candidates.append((similarity, start, end, speaker, text))

    # Keep the review track useful on noisy program audio: retain at most the
    # strongest twelve gaps, then restore timeline order for editors.
    candidates.sort(key=lambda row: (-row[0], row[1]))
    selected = sorted(candidates[:12], key=lambda row: row[1])
    for similarity, start, _end, speaker, text in selected:
        legacy.add_review_item(
            start,
            "Qwen骨架缺口",
            f"MOSS 将该段归为节目/角色声 {speaker}，Qwen 文字支持 {similarity:.0%}；不自动写入主播轨",
            text,
            priority=2,
            severity="info",
        )
    legacy.record_run_event(
        "qwen_skeleton_gap_review",
        candidate_count=len(candidates),
        emitted_count=len(selected),
    )
    if selected:
        print(f"   [Qwen骨架缺口] {len(selected)} 段写入独立复核轨，不混入主播字幕。")
    return len(selected)


def restore_qwen_supported_dialogue_segments(
    segments,
    qwen_chunks,
    moss_payload,
    firered_tokens,
    speech_regions,
    legacy,
    runtime_context=None,
):
    """Restore non-host MOSS speech when Qwen independently supports its text."""
    if _dialogue_coverage_mode(runtime_context, legacy) != "host_priority":
        return segments, 0
    host_speakers = set(moss_payload.get("host_speakers") or [])
    if not host_speakers or not qwen_chunks:
        return segments, 0
    restored = []
    for index, item in enumerate(moss_payload.get("segments") or []):
        speaker = str(item.get("speaker") or "S00")
        if speaker in host_speakers:
            continue
        start = max(0.0, float(item.get("start", 0.0)))
        end = max(start + 0.01, float(item.get("end", start)))
        duration = end - start
        raw_text = str(item.get("text", "") or "")
        if getattr(runtime_context, "task_language", "") == "ja":
            from twobyteasr.language_rules import japanese_display_source
            raw_text = japanese_display_source(raw_text)
        text = legacy.clean_subtitle_text(raw_text)
        speech_overlap = sum(
            _time_overlap(start, end, float(region["start"]), float(region["end"]))
            for region in speech_regions
        )
        if not _trustworthy_dialogue_text(
            item, text, speech_overlap, duration, legacy
        ):
            continue
        if any(
            segment.speaker == speaker
            and _time_overlap(start, end, segment.start, segment.end) / max(0.01, duration) >= 0.5
            for segment in segments
        ):
            continue
        matched_qwen_chunks = [
            chunk for chunk in qwen_chunks
            if float(chunk.get("end", 0.0)) >= start - 0.30
            and float(chunk.get("start", 0.0)) <= end + 0.30
        ]
        qwen_context = legacy.clean_subtitle_text(" ".join(
            legacy.clean_subtitle_text(chunk.get("text", ""))
            for chunk in matched_qwen_chunks
        ))
        qwen_candidate, qwen_similarity = legacy.best_alternate_window(
            text, qwen_context
        )
        if not qwen_candidate or qwen_similarity < 0.64:
            continue
        nearby_tokens = [
            token for token in (firered_tokens or [])
            if float(token.get("end", 0.0)) >= start - MOSS_SPEAKER_PAD_SECONDS
            and float(token.get("start", 0.0)) <= end + MOSS_SPEAKER_PAD_SECONDS
        ]
        aligned_window = None
        if nearby_tokens and all(token.get("source") == "qwen-forced-aligner" for token in nearby_tokens):
            # Aligner tokens repeat this transcript: timing of this speaker's
            # own segment only, never a second text source.
            from twobyteasr.forced_alignment import segment_alignment_key
            key = segment_alignment_key(item.get("speaker"), item.get("start", 0.0), item.get("end", 0.0))
            own = [token for token in nearby_tokens if str(token.get("alignment_key")) == key]
            firered_context, firered_candidate, firered_similarity, firered_window = "", "", 0.0, None
            if own:
                aligned_window = {"start": min(float(t["start"]) for t in own), "end": max(float(t["end"]) for t in own),
                                  "job": key, "token_count": len(own), "kind": "forced_alignment_span"}
        else:
            firered_context = legacy.clean_subtitle_text(
                "".join(token.get("text", "") for token in nearby_tokens)
            )
            firered_candidate, firered_similarity = legacy.best_alternate_window(
                text, firered_context
            )
            firered_window = (
                _firered_token_window(nearby_tokens, start, end)
                if firered_candidate and firered_similarity >= 0.42
                else None
            )
        qwen_confidences = []
        for chunk in matched_qwen_chunks:
            try:
                confidence = float(chunk.get("confidence"))
            except (TypeError, ValueError):
                continue
            if 0.0 <= confidence <= 1.0:
                qwen_confidences.append(confidence)
        qwen_confidence = (
            sum(qwen_confidences) / len(qwen_confidences)
            if qwen_confidences
            else 0.0
        )
        overlap_conflict = any(
            other_index != index
            and str(other.get("speaker") or "S00") != speaker
            and _time_overlap(start, end, float(other["start"]), float(other["end"]))
            >= MOSS_OVERLAP_CONFLICT_SECONDS
            for other_index, other in enumerate(moss_payload.get("segments") or [])
        )
        restored.append(legacy.SpeechSegment(
            segment_id=0,
            start=start,
            end=max(end, start + legacy.MIN_SUBTITLE_SECONDS),
            text=text,
            confidence=0.70,
            words=_distributed_words(text, start, end, 0.70, legacy),
            speaker=speaker,
            moss_text=text,
            moss_context=text,
            alternate_text=firered_candidate if firered_similarity >= 0.42 else "",
            alternate_context=firered_context,
            qwen_asr_text=qwen_candidate,
            qwen_asr_context=qwen_context,
            firered_start=(firered_window["start"] if firered_window else 0.0),
            firered_end=(firered_window["end"] if firered_window else 0.0),
            firered_alignment_confidence=(
                firered_window["confidence"] if firered_window else 0.0
            ),
            qwen_confidence=qwen_confidence,
            overlapping_speaker_conflict=overlap_conflict,
            timing_locked=overlap_conflict,
            firered_text=firered_candidate if firered_similarity >= 0.42 else "",
            primary_source="moss-dialogue-qwen-restored",
            reference_consensus=max(qwen_similarity, firered_similarity),
            caption_arbitration=({"timing_evidence": dict(firered_window)} if firered_window
                                 else {"forced_alignment_window": aligned_window} if aligned_window else {}),
        ))
    if not restored:
        return segments, 0
    combined = list(segments) + restored
    combined.sort(key=lambda segment: (segment.start, segment.end, segment.speaker))
    for segment_id, segment in enumerate(combined, 1):
        segment.segment_id = segment_id
    legacy.record_run_event(
        "dialogue_segments_restored",
        dialogue_coverage_mode="host_priority",
        restored_count=len(restored),
        restored_by_speaker={
            speaker: sum(item.speaker == speaker for item in restored)
            for speaker in sorted({item.speaker for item in restored})
        },
        evidence="moss+qwen",
    )
    return combined, len(restored)


def reconcile_firered_moss_qwen(segments, legacy):
    # Two independent local ASR models often agree on a one- or two-character
    # correction inside an otherwise nearly identical sentence.  Apply those
    # shared spans before the broader arbitration scores are calculated.
    segments = legacy.apply_reference_consensus_corrections(segments)
    promoted = 0
    from twobyteasr.language_rules import is_japanese
    # Japanese kanji are not traditional Chinese: compare and adopt as written.
    simplify = (lambda text: text) if is_japanese() else legacy.simplify_chinese
    for segment in segments:
        primary = legacy.clean_subtitle_text(simplify(segment.text))
        moss = legacy.clean_subtitle_text(
            simplify(segment.moss_text or segment.alternate_text)
        )
        firered = legacy.clean_subtitle_text(
            simplify(segment.firered_text or segment.alternate_text)
        )
        qwen = legacy.clean_subtitle_text(simplify(segment.qwen_asr_text))
        if not primary:
            continue
        first_reference = firered if segment.primary_source.startswith("moss-host") else moss
        if first_reference and qwen:
            consensus = legacy.asr_consensus_similarity(first_reference, qwen)
            segment.reference_consensus = consensus
            first_support = legacy.asr_consensus_similarity(primary, first_reference)
            qwen_support = legacy.asr_consensus_similarity(primary, qwen)
            primary_support = max(
                first_support,
                qwen_support,
            )
            if (
                len(legacy.content_only(primary)) >= 4
                and consensus >= 0.76
                and primary_support < 0.62
            ):
                legacy.add_review_item(
                    segment.start,
                    "多模型文本冲突",
                    "FireRed/Qwen3 互相支持，但与 MOSS 主播稿明显不同；保留主播稿并等待受限校对",
                    segment.text,
                    priority=3,
                    segment_id=segment.segment_id,
                )
            if (
                not segment.overlapping_speaker_conflict
                and consensus >= legacy.ASR_CONSENSUS_MIN_SIMILARITY
                and (segment.confidence < 0.60 or primary_support < 0.60)
            ):
                candidate = qwen
                if legacy.consensus_candidate_is_safe(primary, candidate, segment.confidence):
                    segment.text = candidate
                    segment.primary_source = (
                        "moss-host+refs"
                        if segment.primary_source.startswith("moss-host")
                        else "moss+qwen3-consensus"
                    )
                    promoted += 1
        supports = [value for value in (first_reference, qwen) if value]
        if supports:
            best_support = max(legacy.asr_consensus_similarity(primary, value) for value in supports)
            if segment.confidence < 0.62 or best_support < 0.58:
                legacy.add_review_item(
                    segment.start,
                    "多模型争议",
                    f"主稿证据分 {segment.confidence:.2f}，最佳外部支持 {best_support:.0%}",
                    segment.text,
                    priority=2,
                    segment_id=segment.segment_id,
                )
    print(f"   [完成] 本地仲裁：{promoted}/{len(segments)} 段由两套独立参考安全接管。")
    return segments


def _disputed_segments(segments, legacy):
    disputed = []
    for segment in segments:
        moss = segment.moss_text or segment.alternate_text
        firered = segment.firered_text or segment.alternate_text
        qwen = segment.qwen_asr_text
        primary = segment.text
        first_reference = firered if segment.primary_source.startswith("moss-host") else moss
        external_consensus = (
            legacy.asr_consensus_similarity(first_reference, qwen)
            if first_reference and qwen
            else 0.0
        )
        primary_support = max(
            [legacy.asr_consensus_similarity(primary, value) for value in (first_reference, qwen) if value]
            or [0.0]
        )
        if (
            not segment.overlapping_speaker_conflict
            and (
                segment.confidence < 0.55
                or (external_consensus >= 0.80 and primary_support < 0.68)
            )
        ):
            severity = (
                max(0.0, 0.62 - float(segment.confidence)) * 2.0
                + max(0.0, external_consensus - primary_support)
            )
            disputed.append((severity, segment))
    if len(disputed) <= 24:
        return [segment for _, segment in sorted(disputed, reverse=True, key=lambda item: item[0])]

    # 不再只复核视频开头的前24条：按全片六个时间窗抽高风险项，再用全局高风险补齐。
    end_time = max(segment.end for _, segment in disputed)
    selected = []
    selected_ids = set()
    for bucket in range(6):
        left = end_time * bucket / 6.0
        right = end_time * (bucket + 1) / 6.0
        rows = sorted(
            (item for item in disputed if left <= item[1].start < right),
            reverse=True,
            key=lambda item: item[0],
        )[:4]
        for _, segment in rows:
            selected.append(segment)
            selected_ids.add(segment.segment_id)
    for _, segment in sorted(disputed, reverse=True, key=lambda item: item[0]):
        if len(selected) >= 24:
            break
        if segment.segment_id not in selected_ids:
            selected.append(segment)
            selected_ids.add(segment.segment_id)
    return selected[:24]


def safe_review_disputes_with_firered_llm(segments, shared_audio, legacy):
    """FireRed-LLM 是争议复核增强；失败不应让整批主识别报废。"""
    try:
        return review_disputes_with_firered_llm(segments, shared_audio, legacy)
    except CancelledError:
        raise
    except Exception as exc:
        legacy.add_review_item(
            0.0,
            "FireRed-LLM跳过",
            f"可选复核失败，已保留 MOSS/FireRed/Qwen 主链结果：{exc}",
            priority=2,
        )
        print(f"   [警告] FireRedASR2-LLM 可选复核失败，继续主流程：{exc}")
        return segments


def review_disputes_with_firered_llm(segments, shared_audio, legacy):
    disputes = _disputed_segments(segments, legacy)
    if not disputes:
        print("   FireRedASR2-LLM：没有满足门槛的争议片段，跳过。")
        return segments
    endpoint = os.environ.get("FIRERED_LLM_ENDPOINT", "").strip().rstrip("/")
    if not endpoint:
        # Local FireRed LLM is now a first-class Primary/Review backend. Running
        # this legacy optional pass as well would load the 8B model twice.
        return segments
    if endpoint:
        from twobyteasr.llm_config import validate_transport_url

        validate_transport_url(endpoint, "FireRed-LLM 服务")
    paths = _script_paths(legacy)
    local_ready = all(
        os.path.exists(path)
        for path in (
            os.path.join(paths["firered_llm"], "model.pth.tar"),
            os.path.join(paths["firered_llm"], "asr_encoder.pth.tar"),
            os.path.join(paths["firered_llm"], "Qwen2-7B-Instruct", "config.json"),
            paths["firered_llm_worker"],
        )
    )
    if local_ready:
        try:
            import torch

            local_ready = torch.cuda.is_available() and torch.cuda.get_device_properties(0).total_memory / (1024 ** 3) >= FIRERED_LLM_MIN_GPU_GB
        except Exception:
            local_ready = False
    if not endpoint and not local_ready:
        print(
            f"   FireRedASR2-LLM：发现 {len(disputes)} 个争议片段，但本机显存/模型条件不足，"
            "保留给云端模型受限校对并列入复核清单。"
        )
        return segments

    with tempfile.TemporaryDirectory(prefix="firered_llm_") as temp_dir:
        jobs = []
        for index, segment in enumerate(disputes, 1):
            start = max(0.0, segment.start - 0.40)
            end = min(len(shared_audio) / legacy.AUDIO_SAMPLE_RATE, segment.end + 0.40)
            left = int(round(start * legacy.AUDIO_SAMPLE_RATE))
            right = int(round(end * legacy.AUDIO_SAMPLE_RATE))
            wav_path = os.path.join(temp_dir, f"dispute_{index:03d}.wav")
            legacy.write_pcm16_wav(wav_path, shared_audio[left:right])
            jobs.append({"segment_id": segment.segment_id, "path": wav_path, "start": start, "end": end})

        results = {}
        if endpoint:
            import requests

            for job in jobs:
                _parallel_cancel_poll()
                with open(job["path"], "rb") as audio_file:
                    response = requests.post(
                        endpoint,
                        data={"model": os.environ.get("FIRERED_LLM_MODEL", "FireRedASR2-LLM"), "response_format": "json"},
                        files={"file": (os.path.basename(job["path"]), audio_file, "audio/wav")},
                        timeout=600,
                    )
                response.raise_for_status()
                payload = response.json()
                results[job["segment_id"]] = payload.get("text", "")
        else:
            manifest_path = os.path.join(temp_dir, "manifest.json")
            output_path = os.path.join(temp_dir, "results.json")
            Path(manifest_path).write_text(
                json.dumps({"jobs": jobs}, ensure_ascii=False), encoding="utf-8"
            )
            process = subprocess.Popen(
                python_utf8_command([paths["firered_llm_python"], "-I", paths["firered_llm_worker"], "--manifest", manifest_path, "--output", output_path, "--model-dir", paths["firered_llm"]]),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=utf8_worker_environment(),
                cwd=os.path.dirname(paths["firered_llm_python"]) or None,
                **hidden_subprocess_kwargs(),
            )
            output_queue = queue.Queue()

            def read_llm_output():
                try:
                    output_queue.put(process.communicate())
                except Exception as exc:
                    output_queue.put(exc)

            reader = threading.Thread(target=read_llm_output, daemon=True)
            reader.start()
            try:
                deadline = time.monotonic() + 3600
                while process.poll() is None:
                    if time.monotonic() > deadline:
                        raise TimeoutError("FireRedASR2-LLM 子进程超过 60 分钟未完成。")
                    if _cancel_requested():
                        raise KeyboardInterrupt("用户取消 FireRedASR2-LLM 复核。")
                    time.sleep(0.5)
                received = output_queue.get(timeout=5)
                if isinstance(received, Exception):
                    raise received
                stdout_data, stderr_data = received
            except BaseException:
                stop_process_tree(process)
                raise
            if process.returncode != 0:
                raise RuntimeError("FireRedASR2-LLM 子进程失败：" + (stderr_data or "")[-1600:])
            with open(output_path, "r", encoding="utf-8") as file:
                for item in json.load(file).get("results", []):
                    # 坏条目逐项跳过：单个非法 id 不应让整个争议复核阶段作废。
                    try:
                        segment_id = int(item["segment_id"])
                    except (KeyError, TypeError, ValueError):
                        print(
                            "      [警告] FireRed-LLM 结果含非法 segment_id，"
                            f"已跳过该条：{item.get('segment_id')!r}"
                        )
                        continue
                    results[segment_id] = item.get("text", "")

    attached = 0
    by_id = {segment.segment_id: segment for segment in segments}
    for segment_id, text in results.items():
        segment = by_id.get(int(segment_id))
        if segment is None:
            continue
        cleaned = legacy.clean_subtitle_text(text)
        if not legacy.content_only(cleaned):
            continue
        segment.firered_llm_text = cleaned
        segment.firered_llm_context = cleaned
        attached += 1
    print(f"   [完成] FireRedASR2-LLM：{attached}/{len(disputes)} 个争议片段获得额外证据。")
    return segments


def _cuda_total_memory_gb():
    try:
        from twobyteasr.hardware import collect_gpu_telemetry
        value = collect_gpu_telemetry().get("total_vram_gb")
        return float(value) if value is not None else 0.0
    except Exception:
        return 0.0


def _cuda_free_memory_gb():
    """返回 device 0 当前空闲显存（GB）；多卡时取所有设备的最小空闲值。"""
    try:
        from twobyteasr.hardware import collect_gpu_telemetry
        value = collect_gpu_telemetry().get("free_vram_gb")
        return float(value) if value is not None else 0.0
    except Exception:
        return 0.0


def _gpu_runtime_snapshot():
    try:
        from twobyteasr.hardware import collect_gpu_telemetry
        return dict(collect_gpu_telemetry())
    except Exception as exc:
        return {"status": "UNKNOWN", "probe_error": f"{type(exc).__name__}: {exc}", "total_vram_gb": None, "free_vram_gb": None}


def process_media(
    media_path,
    file_index,
    file_total,
    legacy,
    runtime_context=None,
):
    runtime_context = runtime_context or get_runtime_context()
    from twobyteasr.recognition_plan import text_ai_plan
    task_settings = runtime_context.asr_settings_snapshot or legacy.RUNTIME_SETTINGS
    text_plan = text_ai_plan(task_settings, purpose=runtime_context.recognition_purpose)
    runtime_context.reset_for_media()
    runtime_context.media_path = str(media_path)
    runtime_context.media_index = file_index
    from twobyteasr.recognition_result import media_identity_for_task
    runtime_context.media_identity = media_identity_for_task(media_path, runtime_context)
    if runtime_context.recognition_snapshot:
        runtime_context.media_identity["fingerprint"] = runtime_context.recognition_snapshot["fingerprint"]
    legacy.reset_review_items()
    started = time.perf_counter()
    base_name = os.path.splitext(os.path.basename(media_path))[0]
    txt_path, srt_path = legacy.output_paths_for_media(media_path)
    timeline_fps = legacy.detect_timeline_fps(media_path)
    if getattr(runtime_context, "recognition_snapshot", None):
        media_assets = runtime_context.recognition_snapshot["project"].get("media_pool", [])
        timeline_fps = next((float(a.get("video_metadata", {}).get("fps") or 0)
                             for a in media_assets if a.get("video_metadata", {}).get("fps")), timeline_fps)
    cache_context = legacy.media_cache_context(media_path)
    legacy.begin_media_report(media_path, cache_context)
    paths = _script_paths(legacy)
    primary_backend = str(getattr(legacy, "PRIMARY_ASR_BACKEND", "moss"))
    analysis_transcript = str(
        getattr(runtime_context, "recognition_purpose", "final") or "final"
    ) == "analysis"
    stage_total = 8 if analysis_transcript else 11 - int(not text_plan.polish)
    stage_index = 0
    incremental_primary_rows = []

    print("\n" + "=" * 72)
    print(f"[文件 {file_index}/{file_total}] {os.path.basename(media_path)}")
    print(f"   缓存目录：{cache_context['cache_dir']}")
    if analysis_transcript:
        print("   [分析稿] 仅运行主力 ASR、必要时间轴与本地断句；跳过复核和云端校对。")
        legacy.record_run_event(
            "analysis_transcript_pipeline",
            primary_backend=primary_backend,
            skips=["review_asr", "firered_llm", "cloud_polish", "ai_grouping"],
        )

    # 三十六轮：API 主力不再走增量——增量把整块 45s 当"语音区间"传下去，
    # 25s 硬切块边界落在连续语流中间，多句共享一个时间戳（异环自行车
    # 实录：0→25.2 一整行 21 句话）。全量路径先跑 FireRedVAD/轻量 VAD，
    # 按真实人声区间 + 10s 上限切块。代价：API 主力失去流式 provisional。
    if primary_backend in INCREMENTAL_PRIMARY_BACKENDS:
        try:
            from twobyteasr.incremental_asr import IncrementalASRPipeline
            from twobyteasr.media_service import GLOBAL_MEDIA_SERVICE

            metadata = GLOBAL_MEDIA_SERVICE.metadata(media_path)
            token = getattr(runtime_context, "cancellation_token", None)
            cancelled = lambda: bool(token is not None and token.is_cancelled)
            model_settings = dict(getattr(legacy, "RUNTIME_SETTINGS", {}).get("models", {}) or {})
            model_revision = str(model_settings.get(primary_backend) or "configured")
            from twobyteasr.platform_media import executable_name
            ffmpeg_path = Path(__file__).resolve().parent / "tools" / "ffmpeg" / "bin" / executable_name("ffmpeg")

            def recognize_incremental(chunk_path, spec):
                duration = max(0.02, (spec.end_ms - spec.start_ms) / 1000.0)
                try:
                    return legacy.transcribe_primary_reference(
                        primary_backend,
                        str(chunk_path),
                        [{"start": 0.0, "end": duration}],
                        None,
                        duration,
                    )
                except RuntimeError as exc:
                    if (
                        primary_backend in {"sensevoice", "funasr_nano"}
                        and "没有生成有效文字" in str(exc)
                    ):
                        return []
                    raise

            incremental_started = time.perf_counter()
            incremental_pipeline = IncrementalASRPipeline(
                media_path,
                duration_ms=metadata.duration_ms,
                backend=primary_backend,
                model_revision=model_revision,
                settings={"sample_rate": legacy.AUDIO_SAMPLE_RATE},
                ffmpeg_path=ffmpeg_path,
                cache_root=Path(cache_context["cache_dir"]) / "incremental-asr",
                recognize_chunk=recognize_incremental,
                event_sink=lambda delta: legacy.record_run_event("cue_delta", **delta.to_payload()),
                cancelled=cancelled,
            )
            incremental_primary_rows = list(incremental_pipeline.run())
            runtime_context.asr_provisional_cues = [dict(item) for item in incremental_primary_rows]
            runtime_context.asr_manifest_key = incremental_pipeline.identity.key
            legacy.record_run_event(
                "incremental_asr_completed",
                backend=primary_backend,
                cue_count=len(incremental_primary_rows),
                manifest_key=incremental_pipeline.identity.key,
                elapsed_seconds=round(time.perf_counter() - incremental_started, 3),
            )
        except InterruptedError:
            if getattr(getattr(runtime_context, "cancellation_token", None), "is_cancelled", False):
                raise CancelledError("增量识别已取消。")
            raise
        except Exception as exc:
            incremental_primary_rows = []
            legacy.record_run_event(
                "incremental_asr_fallback",
                backend=primary_backend,
                error=str(exc),
            )
            print(f"   [提示] 增量识别准备失败，回退现有完整流程：{exc}")

    stage_index += 1
    shared_audio = legacy.run_timed_stage(
        stage_index, stage_total, "统一 16k 音频采样时钟", "CPU+磁盘缓存", lambda: legacy.load_shared_audio(media_path, cache_context)
    )
    audio_seconds = len(shared_audio) / legacy.AUDIO_SAMPLE_RATE
    from twobyteasr.speaker_evidence import save_speaker_evidence, fuse_moss_speakers
    speaker_audit_root = Path(cache_context["cache_dir"]) / "speaker-evidence"
    save_speaker_evidence(speaker_audit_root, "task-input", {
        "path": media_path, "seconds": audio_seconds, "samples": len(shared_audio),
        "sample_rate": legacy.AUDIO_SAMPLE_RATE, "time_domain": "timeline" if runtime_context.recognition_snapshot else "source",
        "snapshot": runtime_context.recognition_snapshot.get("fingerprint", ""),
        "audio_sha256": hashlib.sha256(np.asarray(shared_audio,dtype='<f4').tobytes()).hexdigest(),
        "job_id": runtime_context.job_id,
        "project_id": runtime_context.recognition_snapshot.get("project_id", ""),
        "shared_by": ["primary", "vad", "firered", "alignment", "voiceprint", "review"],
    })

    from moss_worker import audio_fingerprint
    moss_signature = {**_moss_stage_signature(paths),
                      "task_audio_fingerprint": audio_fingerprint(shared_audio, legacy.AUDIO_SAMPLE_RATE)}

    def audit_branch(name):
        legacy.record_run_event("recognition_branch_input", branch=name, input_path=media_path,
            sample_rate=legacy.AUDIO_SAMPLE_RATE, samples=len(shared_audio), start_seconds=0,
            end_seconds=audio_seconds, fingerprint=runtime_context.media_identity.get("fingerprint", ""),
            job_id=runtime_context.job_id, media_sha256=runtime_context.media_identity.get("sha256", ""))

    def run_moss_stage():
        audit_branch(primary_backend)
        if primary_backend != "moss":
            legacy.record_run_event('MODEL_PLANNED', model_id=primary_backend,
                role='primary_transcription', backend=primary_backend,
                execution='planned_may_reuse_cache', loaded=None)
            api_primary_label = "在线 ASR API 主力转写"
            if primary_backend == "api":
                try:
                    from twobyteasr.llm_config import (
                        asr_api_display,
                        qwen_asr_endpoint_from_settings,
                    )

                    api_primary_label = (
                        f"在线 ASR API 主力转写（"
                        f"{asr_api_display(qwen_asr_endpoint_from_settings(getattr(legacy, 'RUNTIME_SETTINGS', {}) or {}))}）"
                    )
                except Exception:
                    pass
            labels = {
                "firered": "FireRedASR2-AED 主力转写",
                "qwen_local": "Qwen3-ASR 本地主力转写",
                "whisper_turbo": "Whisper 主力转写",
                "sensevoice": "SenseVoice 主力转写",
                "paraformer": "Paraformer 主力转写",
                "funasr_nano": "Fun-ASR Nano 主力转写",
                "api": api_primary_label,
            }
            resources = {
                "api": "网络 API",
                "whisper_turbo": "GPU/CPU",
                "sensevoice": "GPU/CPU",
                "paraformer": "GPU/CPU",
                "funasr_nano": "GPU/CPU",
            }
            if incremental_primary_rows:
                references = [
                    {
                        "start": float(item["start_ms"]) / 1000.0,
                        "end": float(item["end_ms"]) / 1000.0,
                        "text": str(item["text"]),
                        "source": str(item.get("source") or primary_backend),
                    }
                    for item in incremental_primary_rows
                ]
                legacy.record_run_event(
                    "cache_hit",
                    stage=f"primary_{primary_backend}",
                    source="incremental_manifest",
                    chunks=len(references),
                )
            else:
                references = legacy.run_timed_stage(
                    2,
                    stage_total,
                    labels.get(primary_backend, f"{primary_backend} 主力转写"),
                    resources.get(primary_backend, "GPU"),
                    lambda: legacy.run_cached_stage(
                        f"primary_{primary_backend}",
                        cache_context,
                        lambda: legacy.transcribe_primary_reference(
                            primary_backend,
                            media_path,
                            speech_regions,
                            shared_audio,
                            audio_seconds,
                        ),
                        should_cache=bool,
                        extra_signature={
                            "backend": primary_backend,
                            "vad": speech_regions,
                            **(
                                # 三十六轮 bump v2：VAD 区间 + 10s 短块 + 切分缝
                                # 不互 pad（v1=verbose_json 25s 块），旧缓存不复活。
                                # 四十轮 bump v3：协议入签名——filetrans 整段
                                # 上传（服务端 VAD）与 v2 短块语义不同，不互访缓存。
                                {
                                    "api_identity": {key:runtime_context.asr_endpoint_snapshot.get(key,'') for key in ('provider','model','url')},
                                    "speaker_strategy":getattr(runtime_context,'speaker_source','single'),
                                    "api_timing": "request_scoped_180s_v4",
                                    "api_protocol": str(
                                        runtime_context.asr_endpoint_snapshot.get(
                                            "protocol",
                                            "dashscope_multimodal",
                                        )
                                    ),
                                }
                                if primary_backend == "api"
                                else {}
                            ),
                        },
                    ),
                )
            payload = {
                "segments": [
                    {
                        **copy.deepcopy(item),
                        "start": float(item["start"]),
                        "end": float(item["end"]),
                        "text": str(item["text"]),
                        "speaker": str(item.get("speaker") or "S00"),
                    }
                    for item in references
                ],
                "references": references,
                "primary_backend": primary_backend,
            }
            # The real backend already ran (or returned cached rows). This is
            # a result receipt, never evidence that a MOSS worker was started.
            legacy.record_run_event('MODEL_RESULT_AVAILABLE', model_id=primary_backend,
                role='primary_transcription', backend=primary_backend,
                segment_count=len(payload['segments']), loaded=None,
                execution='result_available', worker_start_event='asr_worker_started')
            return payload
        value = _run_audited_model_stage(
            legacy,
            model_id="moss",
            role="primary_transcription",
            backend="moss",
            media_path=media_path,
            worker=paths.get("moss_worker", ""),
            runtime=paths.get("moss_python", ""),
            runner=lambda: legacy.run_timed_stage(
                2,
                stage_total,
                "MOSS 全局说话人与粗时间转写",
                "独立 Python 3.12 + GPU",
                lambda: legacy.run_cached_stage(
                    "moss",
                    cache_context,
                    lambda: transcribe_moss_global(media_path, shared_audio, legacy, cache_context),
                    should_cache=lambda value: bool(value.get("segments")) and value.get("execution", {}).get("complete", False),
                    decoder=lambda value: _decode_moss_full_context_cache(value, shared_audio, legacy),
                    extra_signature=moss_signature,
                ),
            ),
            selected=True,
        )
        # A reused artifact's original receipt is provenance, not new calls.
        execution = dict(value.get("execution", {}))
        from twobyteasr import reporting
        report = reporting.active_media_report() or {}
        cache_hit = "moss" in report.get("cache", {}).get("hits", [])
        if cache_hit:
            execution = _moss_cache_reuse_receipt(value.get("execution", {}))
        legacy.record_run_event("moss_full_context_result", **execution)
        return value

    def run_vad_stage():
        audit_branch("vad")
        use_firered_vad = primary_backend == "moss" or os.path.isdir(paths["firered_vad"])

        def detect_selected_vad():
            if use_firered_vad:
                try:
                    return detect_firered_vad(shared_audio, legacy)
                except Exception as exc:
                    # 打包（frozen）运行没有进程内 torch/soundfile，FireRedVAD
                    # 无法在主进程执行——降级到轻量静音检测并明示（行为差异
                    # 如实记录，待 VAD 子进程路由落地后消除）。
                    if primary_backend == "moss" and not getattr(sys, "frozen", False):
                        raise
                    print(
                        f"   [提示] FireRedVAD 不可用，自动改用轻量静音检测：{exc}"
                    )
            return detect_lightweight_vad(shared_audio, legacy)

        return legacy.run_timed_stage(
            3,
            stage_total,
            "FireRedVAD 人声安全检查" if use_firered_vad else "轻量静音与人声区间检测",
            "CPU",
            lambda: legacy.run_cached_stage(
                "firered_vad" if use_firered_vad else "lightweight_vad",
                cache_context,
                detect_selected_vad,
                should_cache=bool,
                extra_signature=(
                    _path_signature(paths["firered_vad"])
                    if use_firered_vad
                    else {"engine": "energy-v1", "sample_rate": legacy.AUDIO_SAMPLE_RATE}
                ),
            ),
        )

    def run_firered_stage():
        audit_branch("firered")
        timeline_backend = str(getattr(legacy, "FIRERED_ASR_BACKEND", "local"))
        from twobyteasr.language_rules import JA as _JA, supports as _supports
        japanese = getattr(runtime_context, "task_language", "") == _JA
        if japanese and timeline_backend != "off":
            # FireRed/Paraformer/Whisper-as-timeline are Chinese timing tools
            # here; Japanese audio is aligned to its own transcript instead.
            if timeline_backend != "qwen_aligner":
                legacy.record_run_event("timeline_backend_rerouted", requested=timeline_backend,
                                        selected="qwen_aligner", reason="japanese_audio",
                                        requested_supports_japanese=_supports(
                                            {"local": "firered_aed"}.get(timeline_backend, timeline_backend), "align", _JA))
                print(f"   [语言] 日语音频不送 {timeline_backend}，改用 Qwen3-ForcedAligner 对齐日文转写。")
            timeline_backend = "qwen_aligner"
            return _run_audited_model_stage(
                legacy, model_id="qwen_aligner", role="timeline_alignment", backend=timeline_backend,
                media_path=media_path, worker="qwen_aligner_worker.py", runtime=paths["main_python"],
                runner=lambda: legacy.run_timed_stage(
                    4, stage_total, "Qwen3 ForcedAligner 日语字词时间轴", "GPU",
                    lambda: canonical_result_from_segments(
                        legacy.transcribe_qwen_aligner_reference(
                            shared_audio, moss_payload.get("segments", []), language="Japanese"),
                        producer="qwen_aligner_worker", consumer="firered_stage", backend="qwen_aligner",
                        language="ja", allow_empty=True)),
                selected=True, allow_failure=True)
        if timeline_backend == "off":
            print("   [分析稿] 未选择独立时间轴模型，沿用主力 ASR 粗时间。")
            return _run_audited_model_stage(
                legacy,
                model_id="firered",
                role="timeline_alignment",
                backend=timeline_backend,
                media_path=media_path,
                worker="",
                runtime="",
                runner=lambda: [],
                selected=False,
                skip_reason="timeline_backend_off",
            )
        primary_references = moss_payload.get("references", [])
        if timeline_backend == "local" and primary_backend == "firered":
            return _run_audited_model_stage(
                legacy,
                model_id="firered",
                role="timeline_alignment",
                backend=timeline_backend,
                media_path=media_path,
                worker=str(getattr(legacy, "FIRERED_SOURCE_DIR", "") or ""),
                runtime=str(getattr(legacy, "FIRERED_MODEL_DIR", "") or ""),
                runner=lambda: canonical_result_from_segments(
                    [token for item in primary_references for token in item.get("tokens", [])],
                    producer="primary_firered_reference",
                    consumer="firered_stage",
                    backend="firered",
                ),
                selected=True,
                allow_failure=True,
            )
        if timeline_backend == "paraformer" and primary_backend == "paraformer":
            return _run_audited_model_stage(
                legacy,
                model_id="paraformer",
                role="timeline_alignment",
                backend=timeline_backend,
                media_path=media_path,
                worker="",
                runtime=str(legacy.resolve_funasr_local_source("paraformer")),
                runner=lambda: canonical_result_from_segments(
                    [token for item in primary_references for token in item.get("tokens", [])],
                    producer="primary_paraformer_reference",
                    consumer="firered_stage",
                    backend="paraformer",
                ),
                selected=True,
                allow_failure=True,
            )
        if timeline_backend == "whisper_turbo" and primary_backend == "whisper_turbo":
            return _run_audited_model_stage(
                legacy,
                model_id="whisper-turbo",
                role="timeline_alignment",
                backend=timeline_backend,
                media_path=media_path,
                worker="",
                runtime=str(legacy.resolve_whisper_local_source()),
                runner=lambda: canonical_result_from_segments(
                    legacy.reference_chunks_to_timeline_tokens(
                        primary_references, source="whisper-timeline"
                    ),
                    producer="primary_whisper_reference",
                    consumer="firered_stage",
                    backend="whisper-turbo",
                ),
                selected=True,
                allow_failure=True,
            )
        stage_label = (
            "Qwen3 ForcedAligner 字词时间轴"
            if timeline_backend == "qwen_aligner"
            else (
                "Whisper 多语种字幕时间轴"
                if timeline_backend == "whisper_turbo"
                else "Paraformer 中文字幕时间轴"
                if timeline_backend == "paraformer"
                else "FireRedASR2-AED 独立文字证据"
            )
        )
        if timeline_backend == "local":
            legacy.record_run_event("CACHE_REJECTED", stage="firered", reason="real_execution_required")
        return _run_audited_model_stage(
            legacy,
            model_id="firered" if timeline_backend == "local" else timeline_backend,
            role="timeline_alignment",
            backend=timeline_backend,
            media_path=media_path,
            worker=(paths["firered_worker"] if timeline_backend == "local" else str(getattr(legacy, "FIRERED_SOURCE_DIR", "") or "")),
            runtime=(paths["main_python"] if timeline_backend == "local" else str(getattr(legacy, "FIRERED_MODEL_DIR", "") or "")),
            runner=lambda: legacy.run_timed_stage(
                4,
                stage_total,
                stage_label,
                "GPU",
                lambda: (
                    canonical_result_from_segments(
                        legacy.transcribe_qwen_aligner_reference(shared_audio, moss_payload.get("segments", [])),
                        producer="qwen_aligner_worker", consumer="firered_stage", backend="qwen_aligner",
                        allow_empty=True)
                    if timeline_backend == "qwen_aligner"
                    else (
                        legacy.reference_chunks_to_timeline_tokens(
                            legacy.transcribe_whisper_reference(
                                media_path, speech_regions, shared_audio
                            ),
                            source="whisper-timeline",
                        )
                        if timeline_backend == "whisper_turbo"
                        else (
                            legacy.transcribe_paraformer_timeline(shared_audio)
                            if timeline_backend == "paraformer"
                            else legacy.transcribe_firered_reference(shared_audio, audio_seconds)
                        )
                    )
                ),
            ),
            selected=True,
            allow_failure=True,
            environment_probe=(
                lambda: legacy.probe_firered_environment(
                    paths["main_python"], str(getattr(legacy, "FIRERED_MODEL_DIR", "") or ""), paths["firered_source"]
                )
                if timeline_backend == "local" else None
            ),
        )

    firered_early = None
    api_overlap = False
    if (primary_backend == "api" and legacy.PARALLEL_GPU_ASR
            and legacy.USE_FIRERED_BOUNDARY_REFINEMENT and legacy.FIRERED_ASR_BACKEND == "local"):
        from twobyteasr.asr_progress import api_local_admission
        admission = api_local_admission(_gpu_runtime_snapshot(), audio_bytes=getattr(shared_audio, "nbytes", 0))
        legacy.record_run_event("api_local_admission", **admission)
        api_overlap = admission["admitted"]
    if api_overlap:
        speech_regions = run_vad_stage()
        moss_payload = {}
        legacy.record_run_event("local_stages_parallel", stages=["primary_api", "firered"], max_workers=2)
        parallel_results = run_parallel_stages(legacy, {"primary":run_moss_stage, "firered":run_firered_stage},
            thread_name_prefix="api-firered", cancel_poll=_parallel_cancel_poll)
        moss_payload, firered_early = parallel_results["primary"], parallel_results["firered"]
    elif legacy.PARALLEL_CPU_VAD and primary_backend == "moss":
        print("   [并行加速] FireRedVAD 与 MOSS 同时运行。")
        legacy.record_run_event("local_stages_parallel", stages=["moss", "firered_vad"])
        parallel_results = run_parallel_stages(
            legacy,
            {"moss": run_moss_stage, "vad": run_vad_stage},
            thread_name_prefix="moss-vad",
            cancel_poll=_parallel_cancel_poll,
        )
        moss_payload = parallel_results["moss"]
        speech_regions = parallel_results["vad"]
    else:
        if primary_backend == "moss":
            moss_payload = run_moss_stage()
            speech_regions = run_vad_stage()
        else:
            speech_regions = run_vad_stage()
            moss_payload = run_moss_stage()
    stage_index = 3

    # The language this task runs with: a manual choice, otherwise the kana
    # share of the primary transcript (kanji alone never mean Chinese).
    from twobyteasr.language_rules import resolve_task_language, JA as _JA
    task_language, language_evidence = resolve_task_language(
        getattr(runtime_context, "requested_language", "auto"),
        [str(row.get("text") or "") for row in moss_payload.get("segments", [])],
        asr_detected=(moss_payload.get("metadata") or {}).get("detected_language") or moss_payload.get("language"),
    )
    runtime_context.task_language = task_language
    runtime_context.language_evidence = language_evidence
    legacy.TASK_LANGUAGE = task_language
    legacy.record_run_event("TASK_LANGUAGE", language=task_language, **language_evidence)
    print(f"   [语言] 本任务按{'日语' if task_language == _JA else '中文'}处理"
          f"（{language_evidence.get('decided_by')}，假名占比 {language_evidence.get('kana_share', 0):.0%}）。")
    if task_language == _JA and firered_early is not None:
        # The overlapped FireRed run started before the language was known.
        legacy.record_run_event("timeline_result_discarded", backend="firered", reason="japanese_audio")
        firered_early = None

    from twobyteasr.speaker_evidence import needs_moss_speakers
    from twobyteasr.speaker_strategy import resolve
    speaker_mode = resolve(runtime_context.asr_settings_snapshot or legacy.RUNTIME_SETTINGS)
    runtime_context.speaker_source = speaker_mode
    if speaker_mode!='moss':
        moss_payload['host_speakers']=[]
        if not moss_payload.get('references'):moss_payload['references']=copy.deepcopy(moss_payload.get('segments',[]))
    speaker_processing = {"mode":speaker_mode, "status":"single" if speaker_mode=='single' else 'provider',
                          'moss_called':primary_backend=='moss'}
    from twobyteasr.speaker_evidence import label_summary
    speaker_processing.update(enabled=speaker_mode != 'single', selected_backend=speaker_mode,
        primary_backend=primary_backend, job_id=runtime_context.job_id,
        stages={'primary': label_summary(moss_payload.get('segments', []))})
    if speaker_mode == 'moss' and primary_backend == 'moss':
        speaker_processing.update(status='completed', backend='moss')
        speaker_processing['stages'].update(moss_payload.get('metadata', {}).get('speaker_stages', {}))
    # Native output is reused exactly once. A recognizer without speaker
    # capability simply yields one lane; no extra model runs or native-label
    # requirement is inferred from retired recognition-stage switches.
    if primary_backend != 'moss':
        speaker_processing.update(status='native', moss_called=False,
            text_transcription_repeated=False)
        legacy.record_run_event('speaker_source', text_source=primary_backend,
            processing=speaker_processing)

    # Capture before host filtering, duplicate cleanup or voiceprint relabeling.
    # This is project evidence, independent of Stage 9 cache identities.
    from twobyteasr.speaker_recovery import candidate_snapshot
    runtime_context.speaker_recovery = candidate_snapshot(
        moss_payload.get("segments", []), (), runtime_context.expected_speakers, source=speaker_mode,
    ) if moss_payload.get("segments") else {}
    runtime_context.speaker_recovery['processing'] = speaker_processing
    if speaker_processing.get('status') == 'failed':
        runtime_context.speaker_recovery['needs_confirmation'] = True
    if not moss_payload.get("segments"):
        raise RuntimeError(f"{primary_backend} 主力转写没有生成可用片段。")

    moss_last_end = max(float(item["end"]) for item in moss_payload["segments"])
    vad_last_end = max(float(item["end"]) for item in speech_regions)
    if vad_last_end - moss_last_end > 0.50:
        legacy.add_review_item(
            moss_last_end,
            "主力转写提前结束",
            f"{primary_backend} 到 {moss_last_end:.2f}s，FireRedVAD 人声到 {vad_last_end:.2f}s；尾段不自动臆造文字",
            priority=3,
        )
        if primary_backend == 'moss':
            legacy.record_run_event("moss_full_context_coverage", complete=False,
                reason="vad_tail_uncovered", vad_last_end=vad_last_end, transcript_last_end=moss_last_end,
                overlap_recognition_verified=False)

    def run_qwen_stage():
        audit_branch("qwen_review")
        if analysis_transcript:
            return _run_audited_model_stage(
                legacy,
                model_id="qwen3-asr",
                role="text_verification",
                backend="off",
                media_path=media_path,
                worker="",
                runtime="",
                runner=lambda: [],
                selected=False,
                skip_reason="analysis_transcript",
            )
        review_backend = str(legacy.QWEN_ASR_BACKEND)
        equivalent_primary = "local" if primary_backend == "qwen_local" else primary_backend
        if review_backend == equivalent_primary:
            print("   [复用] 文字复核模型与主力模型相同，不重复加载。")
            return _run_audited_model_stage(
                legacy,
                model_id="qwen3-asr",
                role="text_verification",
                backend=review_backend,
                media_path=media_path,
                worker="",
                runtime="",
                runner=lambda: [],
                selected=False,
                skip_reason="same_as_primary",
            )
        resource = (
            "网络 API"
            if review_backend == "api"
            else (
                "GPU/CPU"
                if review_backend in {"whisper_turbo", "sensevoice", "funasr_nano"}
                else "GPU"
            )
        )
        if review_backend == "api":
            # 三十五轮：api 复核不再顶着 "Qwen3-ASR 局部复核" 的名字——
            # 用户看到 Qwen 字样会以为没切换服务商（用户实录）。
            try:
                from twobyteasr.llm_config import (
                    asr_api_display,
                    qwen_asr_endpoint_from_settings,
                )

                api_label = asr_api_display(
                    qwen_asr_endpoint_from_settings(
                        getattr(legacy, "RUNTIME_SETTINGS", {}) or {}
                    )
                )
            except Exception:
                api_label = "ASR API"
            stage_label = f"在线 ASR API 文字复核（{api_label}）"
        else:
            stage_label = (
                "Whisper large-v3-turbo 文字复核"
                if review_backend == "whisper_turbo"
                else (
                    f"{review_backend} 本地文字复核"
                    if review_backend in {"sensevoice", "funasr_nano", "firered_llm"}
                    else "Qwen3-ASR VAD短块复核"
                )
            )
        return _run_audited_model_stage(
            legacy,
            model_id="qwen3-asr",
            role="text_verification",
            backend=review_backend,
            media_path=media_path,
            worker=(
                paths["qwen_worker"] if review_backend == "local" else ""
            ),
            runtime=(
                paths["main_python"] if review_backend == "local" else ""
            ),
            runner=lambda: legacy.run_timed_stage(
                6,
                stage_total,
                stage_label,
                resource,
                lambda: legacy.transcribe_qwen_reference(media_path, speech_regions, shared_audio),
            ),
            selected=True,
            allow_failure=True,
            environment_probe=(
                lambda: legacy.probe_qwen_environment(
                    paths["main_python"], str(legacy.resolve_qwen_asr_local_source())
                )
                if review_backend == "local" else None
            ),
        )
        if review_backend == "local":
            # A selected local model is an acceptance source, never a silent
            # cache substitute.  Keep old artifacts for forensic comparison but
            # force a real load/inference for this stage.
            legacy.record_run_event("CACHE_REJECTED", stage="qwen", reason="real_execution_required")

    gpu_snapshot = _gpu_runtime_snapshot()
    gpu_status = str(gpu_snapshot.get("status") or "UNKNOWN")
    total_vram_gb = gpu_snapshot.get("total_vram_gb")
    free_vram_gb = gpu_snapshot.get("free_vram_gb")
    legacy.record_run_event("GPU_STATUS", **gpu_snapshot)
    min_vram_gb = legacy.PARALLEL_GPU_ASR_MIN_VRAM_GB
    parallel_gpu_asr = bool(
        not analysis_transcript
        and legacy.PARALLEL_GPU_ASR
        and primary_backend == "moss"
        and legacy.USE_FIRERED_BOUNDARY_REFINEMENT
        and legacy.FIRERED_ASR_BACKEND == "local"
        and legacy.USE_QWEN_ASR_REFERENCE
        and legacy.QWEN_ASR_BACKEND == "local"
        and gpu_status == "READY"
        and total_vram_gb is not None
        and free_vram_gb is not None
        and total_vram_gb >= min_vram_gb
        and free_vram_gb >= min_vram_gb
    )
    # Stability-first policy for dual heavy local GPU ASR:
    # FireRedASR2-AED + Qwen3-ASR-1.7B both do full model materialization + CUDA init.
    # Concurrent from_pretrained (or equivalent) + device_map / internal meta paths
    # have produced "Cannot copy out of meta tensor" and 15s wasted fallback on RTX 50-series.
    # We keep the parallel orchestration code, but for the known-risky local+local combo we run serially.
    # Inference overlap can be re-enabled later once loader is proven safe under concurrent load.
    if parallel_gpu_asr:
        both_local_gpu = (legacy.FIRERED_ASR_BACKEND == "local") and (legacy.QWEN_ASR_BACKEND == "local")
        if both_local_gpu:
            print("   [稳定优先] FireRed 与 Qwen3 同为本地 GPU 重模型，串行加载以避免 meta/并发初始化失败。")
            legacy.record_run_event("gpu_asr_parallel_skipped_local_dual", reason="both_local_gpu")
            parallel_gpu_asr = False
    if parallel_gpu_asr:
        print(
            f"   [并行加速] FireRed-AED 与 Qwen3-ASR 同时运行"
            f"（总显存 {total_vram_gb:.1f} GB / 空闲 {free_vram_gb:.1f} GB）。"
        )
        legacy.record_run_event(
            "gpu_asr_parallel",
            total_vram_gb=round(float(total_vram_gb), 2),
            free_vram_gb=round(float(free_vram_gb), 2),
            min_vram_gb=round(min_vram_gb, 2),
        )
        parallel_results = run_parallel_stages(
            legacy,
            {"firered": run_firered_stage, "qwen": run_qwen_stage},
            thread_name_prefix="gpu-asr",
            cancel_poll=_parallel_cancel_poll,
        )
        firered_result = parallel_results["firered"]
        qwen_chunks = parallel_results["qwen"]
        # Both recognizers deliberately return [] on CUDA/OOM failure. Retry only
        # the failed side after its sibling has released VRAM, preserving correctness.
        if not firered_result:
            print("   [显存回退] FireRed 并行结果为空，释放另一模型后串行重试。")
            legacy.record_run_event("gpu_asr_parallel_fallback", stage="firered")
            firered_result = run_firered_stage()
        if not qwen_chunks:
            print("   [显存回退] Qwen3 并行结果为空，释放另一模型后串行重试。")
            legacy.record_run_event("gpu_asr_parallel_fallback", stage="qwen")
            qwen_chunks = run_qwen_stage()
    else:
        if legacy.PARALLEL_GPU_ASR:
            legacy.record_run_event(
                "gpu_asr_parallel_skipped",
                total_vram_gb=(round(float(total_vram_gb), 2) if total_vram_gb is not None else None),
                free_vram_gb=(round(float(free_vram_gb), 2) if free_vram_gb is not None else None),
                gpu_status=gpu_status,
                min_vram_gb=round(min_vram_gb, 2),
            )
        firered_result = firered_early if firered_early else run_firered_stage()
        qwen_chunks = None

    # Stage 4 remains canonical for audit/count/cache provenance.  Stage 5
    # receives a single explicitly flattened token sequence at this boundary.
    firered_tokens = _flatten_firered_stage5_result(firered_result)
    legacy.record_run_event(
        "FIRERED_STAGE5_SCHEMA",
        producer="firered_adapter",
        consumer="build_moss_host_primary_segments",
        canonical_shape=schema_shape(firered_result),
        flat_shape=schema_shape(firered_tokens),
        canonical_segment_count=(len(firered_result.get("segments", [])) if isinstance(firered_result, dict) else 0),
        flat_segment_count=len(firered_tokens),
    )

    firered_selected = str(getattr(legacy, "FIRERED_ASR_BACKEND", "local")) != "off"
    firered_failed = bool(firered_selected and not firered_tokens)
    if firered_failed:
        legacy.add_review_item(
            0.0,
            "时间轴模型 FireRed 未完成",
            "时间轴模型 FireRed 未完成，当前时间轴退化为 MOSS",
            priority=3,
            severity="warning",
            model_id="firered",
        )
        legacy.record_run_event(
            "model_degraded",
            model_id="firered",
            role="timeline_alignment",
            fallback_owner="moss",
            reason="no_firered_timeline_output",
        )
    qwen_selected = bool(not analysis_transcript and legacy.USE_QWEN_ASR_REFERENCE)
    # qwen_chunks is populated after the optional serial stage below.  The
    # selected/failed state is finalized there once every execution path has
    # had a chance to run.

    alternate_coverage_signature = alternate_dialogue_coverage_signature(
        primary_backend, speaker_mode, runtime_context, legacy,
    )
    primary_dependency = {
        'speaker_strategy':speaker_mode,
        'speaker_policy': 'primary-native-identities-v4',
        "asr_result_schema_version": ASR_RESULT_SCHEMA_VERSION,
        "stage5_input_schema": "ASRResult+moss-flat-firered-flat-v2",
        "backend": primary_backend,
        "primary": moss_payload["segments"],
        "vad": speech_regions,
        "timeline": firered_tokens,
        "firered_execution": _model_stage_summary(legacy).get("firered", {}),
        "upstream_artifact_hashes": {
            "moss": legacy.stable_digest(moss_payload),
            "firered": legacy.stable_digest(firered_tokens),
        },
        "model_identity": _path_signature(paths.get("firered_worker", "")),
        "runtime_version": str(paths.get("main_python", "")),
    }
    primary_dependency.update(alternate_coverage_signature)
    stage_index = 5
    audit_branch("alignment")
    if primary_backend == "moss":
        audit_branch("voiceprint")
    else:
        legacy.record_run_event("recognition_branch_skipped", branch="voiceprint",
            reason="API primary path keeps acoustic candidates for explicit identity confirmation")
    segments = legacy.run_timed_stage(
        stage_index,
        stage_total,
        "筛选 MOSS 主播并建立主稿" if primary_backend == "moss" else "建立统一主稿",
        "CPU",
        lambda: legacy.run_cached_stage(
            "firered_primary",
            cache_context,
            lambda: (
                build_moss_host_primary_segments(
                    moss_payload,
                    firered_tokens,
                    speech_regions,
                    audio_seconds,
                    legacy,
                    shared_audio=shared_audio,
                    runtime_context=runtime_context,
                )
                if primary_backend == "moss" and speaker_mode=='moss'
                else build_alternate_primary_segments(
                    moss_payload.get("references", []),
                    firered_tokens,
                    legacy,
                    primary_backend,
                )
            ),
            encoder=legacy.serialize_segments,
            decoder=legacy.deserialize_segments,
            should_cache=lambda value: bool(value) and not firered_failed,
            extra_signature=primary_dependency,
        ),
    )

    if not (primary_backend == "moss" and speaker_mode == "moss"):
        segments = apply_alternate_dialogue_coverage(
            segments, moss_payload.get("references", []), firered_tokens,
            speech_regions, audio_seconds, legacy, primary_backend,
            runtime_context=runtime_context,
        )

    speaker_processing['stages']['primary_segments'] = label_summary(segments)
    if primary_backend == 'moss':
        speaker_processing['stages'].update(moss_payload.get('metadata', {}).get('speaker_stages', {}))
    if analysis_transcript:
        qwen_chunks = []
        legacy.record_run_event('stage_skipped', index=6, total=stage_total,
            label='独立文字复核', resource='未启用', reason='analysis_transcript')
    elif qwen_chunks is None and legacy.USE_QWEN_ASR_REFERENCE:
        qwen_chunks = run_qwen_stage()
    elif qwen_chunks is None:
        # 开关关闭时不执行 Qwen 阶段（含旧缓存命中），避免复用旧复核证据。
        qwen_chunks = []
        legacy.record_run_event('stage_skipped', index=6, total=stage_total,
            label='独立文字复核', resource='未启用', reason='review_backend_off')
    stage_index = 6
    segments = attach_qwen_review_evidence(segments, qwen_chunks, legacy)
    if getattr(runtime_context, "task_language", "") == "ja" and not moss_payload.get("host_speakers"):
        # build_moss_host_primary_segments records the hosts on a validated
        # copy, so this payload never carried them and the Qwen-supported
        # restoration below silently did nothing. Japanese tasks (no FireRed
        # evidence at all) restore other characters from the Qwen review.
        selected = (((moss_payload.get("metadata") or {}).get("speaker_stages") or {})
                    .get("selected_hosts") or {}).get("labels")
        moss_payload["host_speakers"] = list(selected or sorted({segment.speaker for segment in segments}))
        legacy.record_run_event("host_speakers_propagated", hosts=moss_payload["host_speakers"],
                                reason="validated_copy_kept_host_speakers", language="ja")
    segments, _restored_dialogue_count = restore_qwen_supported_dialogue_segments(
        segments,
        qwen_chunks,
        moss_payload,
        firered_tokens,
        speech_regions,
        legacy,
        runtime_context=runtime_context,
    )
    add_qwen_skeleton_gap_review_items(
        segments,
        qwen_chunks,
        moss_payload,
        legacy,
    )
    segments = reconcile_firered_moss_qwen(segments, legacy)
    duplicate_reference = (primary_backend == "api" and str(getattr(legacy,"QWEN_ASR_BACKEND","")) == "api")
    qwen_failed = bool(qwen_selected and not qwen_chunks and not duplicate_reference)
    if qwen_failed:
        legacy.add_review_item(
            0.0,
            "文字复核模型 Qwen3 未完成",
            f"独立文字复核未完成，当前保留 {primary_backend.upper()} 主稿及已获得的时间轴证据",
            priority=3,
            severity="warning",
            model_id="qwen3-asr",
        )
        legacy.record_run_event(
            "model_degraded",
            model_id="qwen3-asr",
            role="text_verification",
            fallback_owner="moss",
            reason="no_qwen_text_output",
        )
    for segment in segments:
        # Preserve each model's own evidence.  ``reference_consensus`` is a
        # lexical similarity score and must never overwrite FireRed timing or
        # Qwen confidence.
        segment.caption_arbitration = dict(segment.caption_arbitration or {})
        segment.caption_arbitration['acoustic_words'] = [
            {'text': str(token.get('text') or ''), 'start_ms': round(float(token['start'])*1000),
             'end_ms': round(float(token['end'])*1000),
             'model': 'qwen3_forced_aligner' if token.get('source') == 'qwen-forced-aligner' else 'firered',
             **({'granularity': token.get('granularity'), 'start_basis': token.get('start_basis'),
                 'end_basis': token.get('end_basis')} if token.get('source') == 'qwen-forced-aligner' else {})}
            for token in (firered_tokens or []) if token.get('text') and float(token['end']) > segment.start
            and float(token['start']) < segment.end
            # An aligner token belongs to the speaker segment it was aligned in.
            and (token.get('source') != 'qwen-forced-aligner'
                 or str(token.get('alignment_key')) == str(
                     (segment.caption_arbitration.get('forced_alignment_window') or {}).get('job')))]
        segment.moss_start = float(segment.moss_start or segment.start)
        segment.moss_end = float(segment.moss_end or segment.end)
        if segment.firered_text and segment.firered_end > segment.firered_start:
            segment.firered_start = float(segment.firered_start)
            segment.firered_end = float(segment.firered_end)
        else:
            segment.firered_start = 0.0
            segment.firered_end = 0.0
            segment.firered_alignment_confidence = 0.0
        segment.qwen_text = str(segment.qwen_asr_text or "")
        if not segment.qwen_text:
            segment.qwen_confidence = 0.0
        segment.final_text = str(segment.text or "")
        if primary_backend.startswith('vibevoice_'):
            segment.final_start=float(segment.start)
            segment.final_end=float(segment.end)
            segment.final_timing_owner='FireRed acoustic word alignment' if segment.words else 'VibeVoice chunk bounds (word alignment unavailable)'
        elif str(segment.final_timing_owner).endswith('timestamps'):
            segment.final_start=float(segment.start)
            segment.final_end=float(segment.end)
        elif segment.firered_text and segment.firered_end > segment.firered_start:
            segment.final_start = float(segment.firered_start)
            segment.final_end = max(
                segment.final_start + 0.01, float(segment.firered_end)
            )
            segment.final_timing_owner = "FireRed"
        elif (segment.caption_arbitration.get('forced_alignment_window') or {}).get('end', 0) > (
                segment.caption_arbitration.get('forced_alignment_window') or {}).get('start', 0):
            window = segment.caption_arbitration['forced_alignment_window']
            segment.final_start = float(window['start'])
            segment.final_end = max(segment.final_start + 0.01, float(window['end']))
            segment.final_timing_owner = "Qwen3-ForcedAligner"
        else:
            segment.final_start = float(segment.start)
            segment.final_end = float(segment.end)
            segment.final_timing_owner = (
                f"{primary_backend.upper()} (degraded: FireRed unavailable)"
                if firered_failed
                else primary_backend.upper()
            )
        segment.final_text_owner = (
            primary_backend.upper()+"+FireRed+Qwen3" if segment.firered_text and segment.qwen_text
            else primary_backend.upper()+"+FireRed" if segment.firered_text
            else primary_backend.upper()+"+Qwen3" if segment.qwen_text
            else primary_backend.upper()
        )
    fused_review_counts = _record_fused_review_classification(
        legacy,
        segments,
        firered_selected=firered_selected,
        firered_failed=firered_failed,
        qwen_selected=qwen_selected,
        qwen_failed=qwen_failed,
    )
    real_three_source_cues = _real_three_source_cue_evidence(segments, limit=5)
    legacy.record_run_event(
        "real_three_source_cues",
        cue_count=len(real_three_source_cues),
        cues=real_three_source_cues,
        evidence="MOSS+FireRed+Qwen real outputs",
    )
    if analysis_transcript:
        # Stage 6 is the first post-ASR local grouping stage in analysis mode;
        # expensive review stages are absent rather than shown as fake work.
        stage_index = 5

    save_speaker_evidence(speaker_audit_root, "aligned", legacy.serialize_segments(segments))
    japanese_task = getattr(runtime_context, "task_language", "") == _JA
    if japanese_task and not analysis_transcript:
        # FireRedASR2-LLM is a Chinese recognizer: never a vote on Japanese text.
        stage_index += 1
        legacy.record_run_event('stage_skipped', index=stage_index, total=stage_total,
            label='FireRedASR2-LLM 争议片段复核', resource='未启用', reason='japanese_audio')
    if not analysis_transcript and not japanese_task:
        stage_index += 1
        segments = legacy.run_timed_stage(
            stage_index,
            stage_total,
            "FireRedASR2-LLM 争议片段复核",
            "可选远程/高显存 GPU",
            lambda: legacy.run_cached_stage(
                "firered_llm",
                cache_context,
                lambda: safe_review_disputes_with_firered_llm(segments, shared_audio, legacy),
                encoder=legacy.serialize_segments,
                decoder=legacy.deserialize_segments,
                should_cache=lambda rows: any(segment.firered_llm_text for segment in rows),
                extra_signature={
                    "segments": legacy.serialize_segments(segments),
                    "endpoint": os.environ.get("FIRERED_LLM_ENDPOINT", ""),
                    "model": _path_signature(paths["firered_llm"]),
                    "worker": _path_signature(paths["firered_llm_worker"]),
                    "min_gpu_gb": FIRERED_LLM_MIN_GPU_GB,
                },
            ),
        )

    from twobyteasr.terminology import apply_to_segments, runtime_snapshot
    term_snapshot = runtime_snapshot(legacy)
    if japanese_task:
        # Glossaries hold Chinese alias -> canonical spellings; applying them
        # would rewrite Japanese words that merely share kanji.
        legacy.record_run_event("terminology_skipped", reason="japanese_audio",
                                libraries=[library.id for library in term_snapshot.libraries])
    else:
        segments = apply_to_segments(segments, term_snapshot, legacy)

    if text_plan.polish:
        stage_index += 1
        from twobyteasr.asr_provider_snapshot import task_provider_snapshot
        polish_snapshot = task_provider_snapshot('polish')
        legacy.record_run_event("asr_provider_snapshot", job_id=runtime_context.job_id,
                                stage="polished", **polish_snapshot.public_identity())
        segments = legacy.run_timed_stage(
            stage_index,
            stage_total,
            "云端模型受限校对",
            f"{polish_snapshot.provider}/{polish_snapshot.model} · {polish_snapshot.transport}+本地安全裁决",
            lambda: legacy.run_cached_stage(
                "polished",
                cache_context,
                lambda: legacy.polish_subtitles(segments, base_name, cache_context),
                encoder=legacy.serialize_segments,
                decoder=legacy.deserialize_segments,
                extra_signature=legacy.serialize_segments(segments),
            ),
        )
    # Search owns an independent scope/cache and runs even after a text hit.
    from twobyteasr.domain_terms import run_optional_term_verification
    segments = run_optional_term_verification(segments, base_name, cache_context)
    # 即使命中旧缓存，仍在本地执行术语与成片规则；后续全文断句会依据
    # 规整后的文字和说话人插话边界重新计算缓存签名。
    save_speaker_evidence(speaker_audit_root, 'corrected-before-editorial', legacy.serialize_segments(segments))
    segments = legacy.apply_editorial_segment_rules(segments)
    # Cloud/cached polishing and editorial formatting may alter casing. The
    # authoritative local pass runs before grouping and its word alignment.
    segments = apply_to_segments(segments, term_snapshot, legacy)
    save_speaker_evidence(speaker_audit_root, "polished", legacy.serialize_segments(segments))
    if getattr(runtime_context, "task_language", "") == "ja":
        # Japanese line breaks follow bunsetsu boundaries of these exact texts
        # (nagisa in the main runtime, no model). Without it the script-class
        # heuristic protects words but cannot split long hiragana stretches.
        from twobyteasr import japanese_morphology
        texts = [segment.text for segment in segments]
        try:
            tagged = japanese_morphology.tag_texts(texts)
        except Exception as error:
            tagged = None
            legacy.record_run_event("japanese_morphology_unavailable", error=str(error)[:300])
            print(f"   [日语断句] 分词不可用，改用文字类别近似规则：{str(error)[:120]}")
        document = japanese_morphology.build_document(texts, tagged)
        japanese_morphology.install(document)
        legacy.record_run_event("japanese_morphology", **document.receipt(),
                                elapsed_ms=(tagged or {}).get("elapsed_ms"))
        if tagged:
            print(f"   [日语断句] nagisa 文节：{document.measured_segments}/{len(texts)} 段，"
                  f"{len(document.allowed)} 个可断点，其中 {len(document.strong)} 个强断点。")

    grouping_uses_ai = text_plan.group
    stage_index += 1
    if grouping_uses_ai:
        from twobyteasr.asr_provider_snapshot import task_provider_snapshot
        runtime_context.provider_snapshot = task_provider_snapshot('group')
        legacy.record_run_event("asr_provider_snapshot", job_id=runtime_context.job_id,
                                stage="grouped", **runtime_context.provider_snapshot.public_identity())
    cues = legacy.run_timed_stage(
        stage_index,
        stage_total,
        "云端模型全文智能断句" if grouping_uses_ai else "本地规则全文断句",
        (
            f"{runtime_context.provider_snapshot.provider}/{runtime_context.provider_snapshot.model} · {runtime_context.provider_snapshot.transport}+说话人插话保护"
            if grouping_uses_ai
            else ("VibeVoice 原生块+真实词级对齐+块级待审" if primary_backend.startswith('vibevoice_')
                  else "MOSS 自然语句+日语文节+对齐停顿" if getattr(runtime_context, "task_language", "") == "ja"
                  else "MOSS 自然语句+FireRed 停顿+本地护栏")
        ),
        lambda: legacy.run_cached_stage(
            "grouped" if grouping_uses_ai else "grouped_local",
            cache_context,
            lambda: (__import__('twobyteasr.optional_timing',fromlist=['grouping']).grouping(
                    segments,firered_tokens,legacy,speech_regions=speech_regions,
                    protect_all_source_boundaries=False,cache_context=cache_context,use_ai=grouping_uses_ai,
                    provider_snapshot=runtime_context.provider_snapshot)
                if primary_backend.startswith('vibevoice_') else legacy.group_subtitles(
                    segments,
                    firered_tokens=firered_tokens,
                    speech_regions=speech_regions,
                    protect_all_source_boundaries=False,
                    cache_context=cache_context,
                    use_ai=grouping_uses_ai,
                    provider_snapshot=runtime_context.provider_snapshot,
            )),
            encoder=legacy.serialize_cues,
            decoder=legacy.deserialize_cues,
            extra_signature={
                **alternate_coverage_signature,
                "segments": legacy.serialize_segments(segments),
                "firered_tokens": firered_tokens,
                "speech_regions": speech_regions,
                "use_ai": grouping_uses_ai,
            },
        ),
    )

    save_speaker_evidence(speaker_audit_root, 'grouped-before-final-timing', legacy.serialize_cues(cues))
    stage_index += 1
    cues = legacy.run_timed_stage(
        stage_index,
        stage_total,
        "锁定最终字幕时间轴",
        "CPU+帧量化",
        lambda: legacy.run_cached_stage(
            "final_timing",
            cache_context,
            lambda: finalize_cues(
                cues,
                segments,
                firered_tokens,
                speech_regions,
                audio_seconds,
                timeline_fps,
                legacy,
            ),
            encoder=legacy.serialize_cues,
            decoder=legacy.deserialize_cues,
            extra_signature={
                **alternate_coverage_signature,
                "cues": legacy.serialize_cues(cues),
                "mode": "vibevoice-native-chunk-measured-words-v1" if primary_backend.startswith('vibevoice_') else "moss-outer-strict-vad-onset-firered-inner-tail200-gap500-turn-protection-v6",
                "firered_execution": _model_stage_summary(legacy).get("firered", {}),
                "firered_result_hash": legacy.stable_digest(firered_tokens),
                "final_timing_owner": "VibeVoice chunks / FireRed measured words" if primary_backend.startswith('vibevoice_') else "FireRed" if not firered_failed else "MOSS_DEGRADED",
                "upstream_artifact_hashes": {
                    "firered": legacy.stable_digest(firered_tokens),
                    "firered_primary": legacy.stable_digest(legacy.serialize_segments(segments)),
                },
                "model_identity": _path_signature(paths.get("firered_worker", "")),
                "runtime_version": str(paths.get("main_python", "")),
            },
        ),
    )

    # Run outside the cache callback too: old final_timing artifacts may carry
    # editorial tails across a different speaker's source onset.
    from twobyteasr.display_timing import protect_runtime_display_tails
    overlap_audit = protect_runtime_display_tails(cues, segments)
    if japanese_task and not analysis_transcript and str(getattr(legacy, "FIRERED_ASR_BACKEND", "local")) != "off":
        # Word timing must belong to the text the user will edit: align each
        # final caption's current text (adjacent same-speaker captions together).
        from twobyteasr.cue_forced_alignment import align_final_cues
        print("   [日语字级时间] 按最终字幕文字对齐（同说话人相邻字幕成段对齐）…")
        aligned_cues = align_final_cues(cues, shared_audio, legacy, speech_regions=speech_regions)
        measured = sum(1 for cue in cues if any(
            piece.get("start_basis") == "model" and piece.get("end_basis") == "model"
            for piece in (getattr(cue, "forced_alignment", None) or {}).get("segments") or ()))
        print(f"   [日语字级时间] {measured}/{len(cues)} 条字幕有模型实测的字词片段"
              + (f"；{len(cues) - measured} 条只有估算（边界不可靠或整段被压缩），工作台会标出。"
                 if measured < len(cues) else "。"))
        legacy.record_run_event("japanese_word_timing_summary", cues=len(cues), attached=aligned_cues,
                                measured=measured)
        # Cuts inside one speaker's utterance that the aligner did not measure
        # were estimated by line breaking; move them to the pause in the audio
        # when (and only when) there is a clear one.
        from twobyteasr.cue_boundary_refine import apply_to_runtime_cues
        snapped = apply_to_runtime_cues(cues, shared_audio, legacy)
        if snapped:
            print(f"   [日语切点] {len(snapped)} 个未实测的切点移到了前面的停顿处（中位 "
                  f"{sorted(c['old_ms'] - c['new_ms'] for c in snapped)[len(snapped) // 2]} ms）。")
        # Line starts placed by the optional CTC aligner when they agree within
        # 80 ms with an independent reference (aligner-measured start, else the
        # current start). Ends are never taken from it.
        from twobyteasr.ctc_alignment import apply_to_runtime_cues as refine_starts
        refined = refine_starts(cues, shared_audio, legacy)
        if refined:
            print(f"   [日语句首] {len(refined)} 条字幕的开头按 CTC 对齐模型校正（与参考相差 80 ms 内）。")
    save_speaker_evidence(speaker_audit_root, "final", legacy.serialize_cues(cues))
    speaker_processing['stages']['final_cues'] = label_summary(cues)
    legacy.record_run_event('speaker_identity_stages', **speaker_processing)
    legacy.record_run_event("display_overlap_classification", pairs=overlap_audit)
    stage_index += 1
    model_statuses = _model_stage_summary(legacy)
    legacy.record_run_event("model_summary", models=model_statuses)
    coverage_filter = copy.deepcopy(runtime_context.speaker_recovery.get("coverage_filter"))
    raw_candidates = runtime_context.speaker_recovery.get("raw_segments", [])
    if raw_candidates:
        runtime_context.speaker_recovery = candidate_snapshot(
            raw_candidates, {segment.speaker for segment in segments}, runtime_context.expected_speakers,source=speaker_mode,
        )
        # Refresh candidate roles without discarding the actual diarization
        # execution/failure receipt captured before downstream timing stages.
        runtime_context.speaker_recovery['processing'] = speaker_processing
        runtime_context.speaker_recovery['allow_raw_recovery'] = primary_backend == 'moss'
        if coverage_filter is not None:
            runtime_context.speaker_recovery['coverage_filter'] = coverage_filter
            if coverage_filter.get('needs_confirmation'):
                runtime_context.speaker_recovery['needs_confirmation'] = True
        if speaker_processing.get('backend') == 'ecapa':
            runtime_context.speaker_recovery['needs_confirmation'] = True
            if 'S00' in runtime_context.speaker_recovery['roles']:
                runtime_context.speaker_recovery['roles']['S00'] = 'game'
                runtime_context.speaker_recovery['reasons']['S00'] = '真实语音身份不确定；完整 API 文字保留，可恢复或手动归属'
        if speaker_processing.get('status') == 'failed':
            runtime_context.speaker_recovery['needs_confirmation'] = True
        if runtime_context.speaker_recovery["needs_confirmation"]:
            legacy.add_review_item(
                0.0, "说话人需要确认", "检测到多个持续说话人，需要确认；请打开说话人管理恢复候选。", priority=3,
            )
    return complete_media_run(
        cues=cues,
        segments=segments,
        file_index=file_index,
        file_total=file_total,
        started=started,
        audio_seconds=audio_seconds,
        txt_path=txt_path,
        srt_path=srt_path,
        stage_index=stage_index,
        stage_total=stage_total,
        legacy=legacy,
        runtime_context=runtime_context,
        include_srt=str(getattr(legacy, "FIRERED_ASR_BACKEND", "local")) != "off",
        model_statuses=model_statuses,
        review_classification=fused_review_counts,
        real_three_source_cues=real_three_source_cues,
        cache_owners={
            "firered_primary": primary_backend.upper() if primary_backend.startswith('vibevoice_') else "FireRed" if not firered_failed else "MOSS_DEGRADED",
            "final_timing": "VibeVoice chunks / FireRed measured words" if primary_backend.startswith('vibevoice_') else "FireRed" if not firered_failed else "MOSS_DEGRADED",
        },
    )


def main(legacy):
    print("MOSS + FireRedVAD + FireRedASR2-AED + Qwen3 字幕生成器")
    print(f"[运行配置] {legacy.RUNTIME_SETTINGS_PATH}")
    print(
        "[模型] "
        f"Qwen3-ASR={legacy.QWEN_ASR_MODEL} | "
        f"校对={legacy.LLM_MODEL} | 断句={legacy.GROUP_LLM_MODEL}"
    )
    for warning in legacy.RUNTIME_SETTINGS_WARNINGS:
        print(f"[配置警告] {warning}")
    try:
        startup_self_test = legacy.run_startup_self_test()
    except Exception as exc:
        print(f"\n[启动自测失败] {exc}")
        legacy.pause_exit(1)
    print(
        f"[启动自测通过] {startup_self_test['id']}："
        f"{startup_self_test['checks']} 项关键护栏正常"
    )
    try:
        from twobyteasr.ui import run_desktop_app
    except ImportError as exc:
        print(f"\n[界面依赖缺失] {exc}")
        print("请运行 setup_environment.bat 安装 PySide6 与 Qt 图标库。")
        legacy.pause_exit(1)
    exit_code = run_desktop_app(legacy, sys.modules[__name__], startup_self_test)
    legacy.pause_exit(exit_code)
