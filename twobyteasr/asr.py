"""asr stage implementation extracted from subtitle_core."""

import base64
import atexit
import ast
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# The core owns runtime configuration; these imports preserve the existing public contract.
from subtitle_core import *  # noqa: F401,F403
from twobyteasr.runtime import get_runtime_context
from twobyteasr.service import CancelledError
from twobyteasr.processes import (
    popen_hidden_subprocess,
    sanitized_child_environment,
    stop_process_tree,
)
from twobyteasr.asr_schema import (
    ASR_RESULT_SCHEMA_VERSION,
    canonical_result_from_segments,
    normalize_firered_worker_result,
    schema_shape,
)

__all__ = [
    'load_qwen_asr_model',
    'resolve_qwen_asr_local_source',
    'build_qwen_asr_context',
    'build_qwen_asr_chunks',
    'call_qwen_asr_api',
    'transcribe_qwen_reference',
    'transcribe_firered_llm_reference',
    'write_pcm16_wav',
    'transcribe_firered_reference',
    'resolve_qwen_aligner_local_source',
    'align_qwen_transcript_segments',
    'transcribe_qwen_aligner_reference',
    'resolve_whisper_local_source',
    'transcribe_whisper_reference',
    'reference_chunks_to_timeline_tokens',
    'resolve_funasr_local_source',
    'funasr_timestamp_tokens',
    'transcribe_funasr_reference',
    'transcribe_paraformer_timeline',
    'tokens_to_reference_chunks',
    'transcribe_primary_reference',
    'begin_local_asr_session',
    'end_local_asr_session',
    'local_asr_session_state',
    'probe_firered_environment',
    'probe_qwen_environment',
]


_SESSION_LOCK = threading.RLock()
_SESSION_ENABLED = False
_SESSION_PERSISTENT = False
_SESSION_QWEN_MODEL = None
_SESSION_FUNASR_MODELS = {}
_SESSION_STATS = {
    "cold_loads": {},
    "warm_reuses": {},
    "last_cold_load_seconds": {},
}
# 保护 torch.cuda.is_bf16_supported 的临时替换（FireRed 需要强制 FP16），
# 防止与 Qwen 的 dtype 决策并发读取时出现 patch/恢复次序颠倒的残留状态。
_TORCH_PATCH_LOCK = threading.RLock()


def _legacy_runtime_value(name, fallback=None):
    """Read mutable settings from the facade instead of the import-time star copy."""
    import subtitle_core

    return getattr(subtitle_core, name, fallback)


def _cuda_runtime_ready():
    """Require an executable CUDA kernel, not merely a visible driver.

    ``torch.cuda.is_available()`` is true for an RTX 50 GPU paired with some
    older wheels even though the first kernel fails. Hardware probing happens
    in a short-lived child process so this process also does not poison the
    CUDA context when a CPU-capable backend can continue safely.
    """
    from twobyteasr.hardware import detect_cuda_runtime

    return detect_cuda_runtime().ready


def _model_runtime_probe(*, model_id, runtime, model_path, source_path="", import_name=""):
    """Probe the interpreter that will execute a local model.

    This is deliberately a child-process check: importing Torch in the GUI can
    pin DLLs and, more importantly, would prove only the GUI environment rather
    than the interpreter selected for the model.
    """
    runtime = str(runtime or "")
    model_path = str(model_path or "")
    source_path = str(source_path or "")
    if runtime:
        runtime = os.path.abspath(runtime)
    if model_path:
        model_path = os.path.abspath(model_path)
    if source_path:
        source_path = os.path.abspath(source_path)
    details = {
        "model_id": str(model_id),
        "python_executable": runtime,
        "model_path": model_path,
        "entrypoint": source_path,
        "cuda_available": False,
        "gpu_name": "",
        "torch_version": "",
        "torch_cuda_version": "",
        "stdout": "",
        "stderr": "",
        "ready": False,
        "error": "",
    }
    parent_sys_path = [str(item) for item in sys.path]
    parent_sys_path_hash = hashlib.sha256(
        json.dumps(parent_sys_path, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    parent_cwd = os.getcwd()
    details.update({
        "parent_sys_path_hash_before": parent_sys_path_hash,
        "parent_cwd_before": parent_cwd,
    })
    if not runtime or not os.path.isfile(runtime):
        details["error"] = "python_executable_missing"
        return details
    if not model_path or not os.path.isdir(model_path):
        details["error"] = "model_path_missing"
        return details
    script = r'''
import json, sys
result = {"imports": [], "cuda_available": False, "gpu_name": "", "torch_version": "", "torch_cuda_version": "", "error": ""}
try:
    import torch
    result["imports"].append("torch")
    result["torch_version"] = str(getattr(torch, "__version__", ""))
    result["torch_cuda_version"] = str(getattr(torch.version, "cuda", "") or "")
    result["cuda_available"] = bool(torch.cuda.is_available())
    if result["cuda_available"]:
        result["gpu_name"] = str(torch.cuda.get_device_name(0))
except Exception as exc:
    result["error"] = f"torch:{type(exc).__name__}: {exc}"
try:
    __IMPORT_NAME__
    result["imports"].append("__IMPORT_LABEL__")
except Exception as exc:
    result["error"] = (result["error"] + "; " if result["error"] else "") + f"import:{type(exc).__name__}: {exc}"
print("__2BYTEASR_MODEL_PROBE__" + json.dumps(result, ensure_ascii=False))
'''.replace("import json, sys\n", "import json, sys\n" + (f"sys.path.insert(0, {source_path!r})\n" if source_path else "")).replace("__IMPORT_NAME__", f"import {import_name}" if import_name else "pass").replace("__IMPORT_LABEL__", import_name or "none")
    env = sanitized_child_environment()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    probe_cwd = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[1]
    )
    try:
        from twobyteasr.processes import python_utf8_command

        completed = subprocess.run(
            python_utf8_command([runtime, "-I", "-c", script]),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            cwd=str(probe_cwd),
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        details["probe_cwd"] = str(probe_cwd)
        details["parent_sys_path_hash_after"] = hashlib.sha256(
            json.dumps(
                [str(item) for item in sys.path],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        details["parent_cwd_after"] = os.getcwd()
        details["stdout"] = (completed.stdout or "")[-4000:]
        details["stderr"] = (completed.stderr or "")[-4000:]
        for line in reversed((completed.stdout or "").splitlines()):
            if line.startswith("__2BYTEASR_MODEL_PROBE__"):
                payload = json.loads(line.split("__2BYTEASR_MODEL_PROBE__", 1)[1])
                details.update({
                    "cuda_available": bool(payload.get("cuda_available")),
                    "gpu_name": str(payload.get("gpu_name") or ""),
                    "torch_version": str(payload.get("torch_version") or ""),
                    "torch_cuda_version": str(payload.get("torch_cuda_version") or ""),
                })
                details["error"] = str(payload.get("error") or "")
                break
        else:
            details["error"] = details["stderr"] or "model_probe_no_result"
        details["ready"] = bool(completed.returncode == 0 and not details["error"] and details["cuda_available"])
    except Exception as exc:
        details["error"] = f"{type(exc).__name__}: {exc}"
    return details


def _main_worker_python():
    from twobyteasr.runtime_registry import resolve_runtime_python
    runtime = resolve_runtime_python("main")
    if runtime:
        return runtime
    if getattr(sys, "frozen", False):
        raise RuntimeError("模型运行库未准备完成，请在模型工坊准备该模型。应用 EXE 不能充当 Python。")
    return sys.executable


def probe_firered_environment(runtime="", model_path="", source_path=""):
    """Return executable FireRed-AED runtime evidence for audited events."""
    if not runtime:
        from twobyteasr.runtime_registry import resolve_runtime_python
        runtime = _main_worker_python()
    if not model_path:
        from twobyteasr.runtime_paths import resolve_model_dir
        model_path = str(resolve_model_dir("FireRedASR2-AED"))
    source_path = source_path or FIRERED_SOURCE_DIR
    return _model_runtime_probe(
        model_id="firered", runtime=runtime, model_path=model_path,
        source_path=source_path, import_name="fireredasr2s.fireredasr2",
    )


def probe_qwen_environment(runtime="", model_path=""):
    """Return executable Qwen3-ASR runtime evidence for audited events."""
    if not runtime:
        from twobyteasr.runtime_registry import resolve_runtime_python
        runtime = _main_worker_python()
    if not model_path:
        model_path = resolve_qwen_asr_local_source()
    return _model_runtime_probe(
        model_id="qwen3-asr", runtime=runtime, model_path=model_path,
        import_name="qwen_asr",
    )


def _cuda_bf16_supported():
    """读取 torch 的 bf16 支持标志，与 FireRed 的临时替换互斥。"""
    import torch

    with _TORCH_PATCH_LOCK:
        return torch.cuda.is_bf16_supported()


def _raise_if_queue_cancelled():
    """让取消在长推理循环内尽快生效（GUI 取消令牌；无令牌时为空操作）。"""
    token = get_runtime_context().cancellation_token
    if token is not None and token.is_cancelled:
        raise CancelledError("任务已取消。")


def begin_local_asr_session(*, persistent=False):
    """Keep reusable local models alive for a queue or the Studio process.

    ``persistent`` is reserved for Studio recognition.  It prevents a second
    analysis/final pass from paying the model materialisation cost again; the
    process-exit hook remains the authoritative release boundary.
    """
    global _SESSION_ENABLED, _SESSION_PERSISTENT
    with _SESSION_LOCK:
        _SESSION_ENABLED = True
        _SESSION_PERSISTENT = bool(_SESSION_PERSISTENT or persistent)


def end_local_asr_session(*, force=False):
    """Release queue-owned models, unless Studio owns a persistent session."""
    global _SESSION_ENABLED, _SESSION_PERSISTENT, _SESSION_QWEN_MODEL
    with _SESSION_LOCK:
        if _SESSION_PERSISTENT and not force:
            return
        model = _SESSION_QWEN_MODEL
        funasr_models = list(_SESSION_FUNASR_MODELS.values())
        _SESSION_QWEN_MODEL = None
        _SESSION_FUNASR_MODELS.clear()
        _SESSION_ENABLED = False
        _SESSION_PERSISTENT = False
    if model is None and not funasr_models:
        return
    if model is not None:
        del model
    funasr_models.clear()
    import gc

    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    print("   [模型会话] 已释放 Studio/队列复用的本地 ASR 模型。")


def local_asr_session_state():
    """Return JSON-friendly evidence for cold-load and warm-reuse acceptance."""
    with _SESSION_LOCK:
        return {
            "enabled": bool(_SESSION_ENABLED),
            "persistent": bool(_SESSION_PERSISTENT),
            "models": [
                *(["qwen3-asr"] if _SESSION_QWEN_MODEL is not None else []),
                *sorted(_SESSION_FUNASR_MODELS),
            ],
            "cold_loads": dict(_SESSION_STATS["cold_loads"]),
            "warm_reuses": dict(_SESSION_STATS["warm_reuses"]),
            "last_cold_load_seconds": dict(_SESSION_STATS["last_cold_load_seconds"]),
        }


def _record_session_model_load(model_key, elapsed_seconds):
    with _SESSION_LOCK:
        bucket = _SESSION_STATS["cold_loads"]
        bucket[model_key] = int(bucket.get(model_key, 0)) + 1
        _SESSION_STATS["last_cold_load_seconds"][model_key] = round(
            float(elapsed_seconds), 3
        )


def _record_session_model_reuse(model_key):
    with _SESSION_LOCK:
        bucket = _SESSION_STATS["warm_reuses"]
        bucket[model_key] = int(bucket.get(model_key, 0)) + 1


def _reuse_or_remember_qwen_model(model):
    global _SESSION_QWEN_MODEL
    with _SESSION_LOCK:
        if _SESSION_ENABLED:
            _SESSION_QWEN_MODEL = model
    return model


def _session_qwen_model():
    with _SESSION_LOCK:
        if _SESSION_ENABLED and _SESSION_QWEN_MODEL is not None:
            _record_session_model_reuse("qwen3-asr")
            print("   [模型复用] 沿用本批已加载的 Qwen3-ASR。")
            return _SESSION_QWEN_MODEL
    return None


def _qwen_model_is_session_owned(model):
    with _SESSION_LOCK:
        return _SESSION_ENABLED and model is _SESSION_QWEN_MODEL


def _session_funasr_model(model_key):
    with _SESSION_LOCK:
        cached = _SESSION_FUNASR_MODELS.get(str(model_key)) if _SESSION_ENABLED else None
        if cached is not None:
            _record_session_model_reuse(str(model_key))
            print(f"   [模型复用] 沿用 Studio 已加载的 {model_key}。")
        return cached


def _reuse_or_remember_funasr_model(model_key, model_and_device):
    with _SESSION_LOCK:
        if _SESSION_ENABLED:
            _SESSION_FUNASR_MODELS[str(model_key)] = model_and_device
    return model_and_device


def _funasr_model_is_session_owned(model_key, model):
    with _SESSION_LOCK:
        cached = _SESSION_FUNASR_MODELS.get(str(model_key))
        return bool(_SESSION_ENABLED and cached is not None and cached[0] is model)

def load_qwen_asr_model():
    """只加载依赖锁指定且通过完整性校验的本地 Qwen3-ASR。"""
    import torch
    from qwen_asr import Qwen3ASRModel
    from twobyteasr.model_integrity import verify_model_files

    if not _cuda_runtime_ready():
        raise RuntimeError("Qwen3-ASR requires a usable CUDA runtime")
    reused = _session_qwen_model()
    if reused is not None:
        return reused

    dtype = torch.bfloat16 if _cuda_bf16_supported() else torch.float16
    model_kwargs = {
        "dtype": dtype,
        "device_map": "cuda:0",
        "max_inference_batch_size": QWEN_ASR_BATCH_SIZE,
        "max_new_tokens": QWEN_ASR_MAX_NEW_TOKENS,
    }
    errors = []
    local_source = resolve_qwen_asr_local_source()
    if local_source:
        print(f"   Qwen3-ASR 本地模型：{local_source}")
        try:
            verify_model_files("qwen_asr", local_source)
            load_started = time.perf_counter()
            model = Qwen3ASRModel.from_pretrained(
                local_source,
                local_files_only=True,
                **model_kwargs,
            )
            _record_session_model_load(
                "qwen3-asr", time.perf_counter() - load_started
            )
            return _reuse_or_remember_qwen_model(model)
        except Exception as exc:
            errors.append(f"本地目录: {exc}")
            print("   Qwen3-ASR 本地目录不可用或完整性校验失败。")

    if not local_source:
        errors.append("本地模型: 未找到完整的固定版本")
        print("   Qwen3-ASR 本地模型不完整；请重新运行 download_models.bat。")

    raise RuntimeError(
        "Qwen3-ASR model load failed: " + ("; ".join(errors) or "unknown error")
    )


def resolve_qwen_asr_local_source():
    """返回完整的项目内模型目录，不选取未固定版本的用户缓存。"""
    env_dir = os.environ.get("2BYTEASR_QWEN3_ASR_DIR", "").strip()
    candidates = []
    if env_dir:
        candidates.append(os.path.expanduser(env_dir))
    from twobyteasr.runtime_paths import iter_model_dir_candidates

    candidates.extend(str(path) for path in iter_model_dir_candidates("Qwen3-ASR-1.7B"))
    candidates.extend(
        [
            os.path.join(SCRIPT_DIR, "models", "Qwen3-ASR-1.7B"),
            os.path.join(SCRIPT_DIR, "models", "Qwen", "Qwen3-ASR-1.7B"),
        ]
    )
    seen = set()
    for candidate in candidates:
        normalized = os.path.normcase(os.path.abspath(candidate))
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.isfile(os.path.join(candidate, "config.json")):
            return candidate
    return ""


def resolve_qwen_aligner_local_source():
    """Return the pinned local Qwen forced-aligner directory only."""
    env_dir = os.environ.get("2BYTEASR_QWEN3_ALIGNER_DIR", "").strip()
    candidates = [os.path.expanduser(env_dir)] if env_dir else []
    from twobyteasr.runtime_paths import iter_model_dir_candidates

    candidates.extend(str(path) for path in iter_model_dir_candidates("Qwen3-ForcedAligner-0.6B"))
    candidates.extend(
        [
            os.path.join(SCRIPT_DIR, "models", "Qwen3-ForcedAligner-0.6B"),
            os.path.join(SCRIPT_DIR, "models", "Qwen", "Qwen3-ForcedAligner-0.6B"),
        ]
    )
    seen = set()
    for candidate in candidates:
        normalized = os.path.normcase(os.path.abspath(candidate))
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.isfile(os.path.join(candidate, "config.json")):
            return candidate
    return ""


def align_qwen_transcript_segments(aligner, audio, transcript_segments, *, sampling_rate=16000, batch_size=4):
    """Align MOSS text inside its rough spans and return pipeline-compatible word tokens."""
    jobs = []
    for row in transcript_segments or ():
        start = max(0.0, float(row.get("start", 0.0)))
        end = max(start, float(row.get("end", start)))
        text = clean_subtitle_text(row.get("text", ""))
        left = max(0, int(round(start * sampling_rate)))
        right = min(len(audio), int(round(end * sampling_rate)))
        if right - left < int(0.18 * sampling_rate) or not content_only(text):
            continue
        jobs.append((start, (audio[left:right], sampling_rate), text))

    tokens = []
    for offset in range(0, len(jobs), max(1, int(batch_size))):
        _raise_if_queue_cancelled()
        batch = jobs[offset : offset + max(1, int(batch_size))]
        results = aligner.align(
            audio=[item[1] for item in batch],
            text=[item[2] for item in batch],
            language=["Chinese"] * len(batch),
        )
        for (base_start, _piece, _text), result in zip(batch, results):
            for item in result:
                token_text = clean_subtitle_text(item.text)
                start = base_start + max(0.0, float(item.start_time))
                end = base_start + max(float(item.start_time), float(item.end_time))
                if content_only(token_text) and end > start:
                    tokens.append(
                        {
                            "text": token_text,
                            "start": round(start, 3),
                            "end": round(end, 3),
                            "confidence": 0.90,
                            "source": "qwen-forced-aligner",
                        }
                    )
    return sorted(tokens, key=lambda item: (item["start"], item["end"]))


def transcribe_qwen_aligner_reference(audio_source, transcript_segments):
    """Use the pinned Qwen3 forced aligner as an alternative word-timeline backend."""
    backend = str(_legacy_runtime_value("FIRERED_ASR_BACKEND", FIRERED_ASR_BACKEND))
    if backend != "qwen_aligner":
        return []
    import gc
    import torch
    from twobyteasr.model_integrity import verify_model_files

    if not _cuda_runtime_ready():
        print("   [警告] Qwen3 ForcedAligner 需要 CUDA，本次保留 MOSS 粗时间轴。")
        return []
    source = resolve_qwen_aligner_local_source()
    if not source:
        print("   [警告] Qwen3 ForcedAligner 未完整安装；请在模型工坊下载后重试。")
        return []
    owns_audio = isinstance(audio_source, (str, bytes, os.PathLike))
    audio = decode_audio_to_array(audio_source) if owns_audio else audio_source
    aligner = None
    try:
        from qwen_asr import Qwen3ForcedAligner

        verify_model_files("qwen_aligner", source)
        dtype = torch.bfloat16 if _cuda_bf16_supported() else torch.float16
        print("   加载 Qwen3 ForcedAligner 0.6B，生成字/词级时间戳...")
        aligner = Qwen3ForcedAligner.from_pretrained(
            source,
            local_files_only=True,
            device_map="cuda:0",
            dtype=dtype,
        )
        tokens = align_qwen_transcript_segments(
            aligner,
            audio,
            transcript_segments,
            sampling_rate=AUDIO_SAMPLE_RATE,
        )
        print(f"   [完成] Qwen3 ForcedAligner：生成 {len(tokens)} 个时间单元。")
        return tokens
    except CancelledError:
        raise
    except Exception as exc:
        print(f"   [警告] Qwen3 ForcedAligner 失败，保留 MOSS 粗时间轴：{exc}")
        add_review_item(0.0, "时间轴模型失败", str(exc)[:160], priority=2)
        return []
    finally:
        if aligner is not None:
            del aligner
        if owns_audio and audio is not None:
            del audio
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def resolve_whisper_local_source():
    """Return the pinned local Whisper large-v3-turbo directory."""
    env_dir = os.environ.get("2BYTEASR_WHISPER_DIR", "").strip()
    candidates = [os.path.expanduser(env_dir)] if env_dir else []
    from twobyteasr.runtime_paths import iter_model_dir_candidates

    candidates.extend(str(path) for path in iter_model_dir_candidates("Whisper-large-v3-turbo"))
    candidates.extend(
        [
            os.path.join(SCRIPT_DIR, "models", "Whisper-large-v3-turbo"),
            os.path.join(SCRIPT_DIR, "models", "whisper-large-v3-turbo"),
        ]
    )
    seen = set()
    for candidate in candidates:
        normalized = os.path.normcase(os.path.abspath(candidate))
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.isfile(os.path.join(candidate, "config.json")):
            return candidate
    return ""


def transcribe_whisper_reference(audio_path, speech_regions, shared_audio=None):
    """Produce review chunks with the pinned local Whisper large-v3-turbo model."""
    import gc
    import torch
    from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor
    from twobyteasr.model_integrity import verify_model_files

    source = resolve_whisper_local_source()
    if not source:
        raise RuntimeError("Whisper large-v3-turbo 未完整安装，请先在模型工坊下载。")
    verify_model_files("whisper_turbo", source)
    owns_audio = shared_audio is None
    audio = decode_audio_to_array(audio_path) if owns_audio else shared_audio
    chunks = build_qwen_asr_chunks(audio, speech_regions, AUDIO_SAMPLE_RATE)
    if not chunks:
        return []
    device = torch.device("cuda:0" if _cuda_runtime_ready() else "cpu")
    dtype = torch.float16 if device.type == "cuda" else torch.float32
    model = None
    processor = None
    try:
        print(
            "   加载 Whisper large-v3-turbo，生成多语种文字复核证据"
            f"（{device.type.upper()}）..."
        )
        processor = AutoProcessor.from_pretrained(source, local_files_only=True)
        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            source,
            local_files_only=True,
            torch_dtype=dtype,
            low_cpu_mem_usage=True,
        ).to(device)
        model.eval()
        batch_size = 4 if device.type == "cuda" else 1
        references = []
        for offset in range(0, len(chunks), batch_size):
            _raise_if_queue_cancelled()
            batch = chunks[offset : offset + batch_size]
            inputs = processor(
                [item["audio"][0] for item in batch],
                sampling_rate=AUDIO_SAMPLE_RATE,
                return_tensors="pt",
                padding=True,
                return_attention_mask=True,
            )
            generation_inputs = {
                "input_features": inputs.input_features.to(device=device, dtype=dtype),
                "language": "zh",
                "task": "transcribe",
            }
            attention_mask = getattr(inputs, "attention_mask", None)
            if attention_mask is not None:
                generation_inputs["attention_mask"] = attention_mask.to(device)
            with torch.inference_mode():
                generated_ids = model.generate(**generation_inputs)
            texts = processor.batch_decode(generated_ids, skip_special_tokens=True)
            for chunk, text in zip(batch, texts):
                cleaned = clean_subtitle_text(text)
                if content_only(cleaned):
                    references.append(
                        {
                            "start": chunk["start"],
                            "end": chunk["end"],
                            "text": cleaned,
                            "source": "whisper-large-v3-turbo",
                        }
                    )
            completed = min(offset + len(batch), len(chunks))
            print(
                f"      [Whisper 进度] {completed}/{len(chunks)} 个短块已处理"
                f"（{device.type.upper()}）",
                flush=True,
            )
        if not references:
            raise RuntimeError("Whisper 没有生成有效文字。")
        print(f"   [完成] Whisper：{len(references)}/{len(chunks)} 个复核短块。")
        return references
    finally:
        if model is not None:
            del model
        if processor is not None:
            del processor
        if owns_audio and audio is not None:
            del audio
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def reference_chunks_to_timeline_tokens(chunks, *, source="reference-timeline"):
    """Turn timestamped ASR chunks into conservative subtitle-timeline tokens.

    Whisper exposes reliable chunk boundaries in this integration, not true
    forced-alignment word boundaries.  We therefore distribute visible text
    inside each chunk and label the source explicitly instead of pretending it
    is word-level alignment.
    """
    tokens = []
    for chunk in chunks or ():
        text = clean_subtitle_text(chunk.get("text", ""))
        pieces = re.findall(r"[\u3400-\u9fff]|[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*|[^\s]", text)
        if not pieces:
            continue
        start = max(0.0, float(chunk.get("start", 0.0)))
        end = max(start + 0.02, float(chunk.get("end", start + 0.02)))
        step = (end - start) / len(pieces)
        for index, piece in enumerate(pieces):
            token_start = start + index * step
            token_end = end if index == len(pieces) - 1 else start + (index + 1) * step
            tokens.append(
                {
                    "text": piece,
                    "start": token_start,
                    "end": max(token_start + 0.01, token_end),
                    "confidence": 0.70,
                    "source": source,
                }
            )
    return tokens


_FUNASR_MODEL_DIRS = {
    "sensevoice": "SenseVoiceSmall",
    "paraformer": "Paraformer-zh",
    "funasr_nano": "Fun-ASR-Nano-2512",
}


def resolve_funasr_local_source(model_key):
    directory = _FUNASR_MODEL_DIRS.get(str(model_key), "")
    if not directory:
        return ""
    env_name = f"2BYTEASR_{str(model_key).upper()}_DIR"
    env_dir = os.environ.get(env_name, "").strip()
    from twobyteasr.runtime_paths import iter_model_dir_candidates

    candidates = [os.path.expanduser(env_dir)] if env_dir else []
    candidates.extend(str(path) for path in iter_model_dir_candidates(directory))
    candidates.append(os.path.join(SCRIPT_DIR, "models", directory))
    for candidate in candidates:
        if os.path.isfile(os.path.join(candidate, "configuration.json")):
            return candidate
    return ""


def _clean_funasr_text(value):
    text = re.sub(r"<\|[^|>]+\|>", "", str(value or ""))
    return clean_subtitle_text(text)


def _split_text_for_timestamps(text, count):
    units = re.findall(r"[\u3400-\u9fff]|[A-Za-z0-9]+|[^\s]", content_only(text))
    if count <= 0 or not units:
        return []
    if len(units) == count:
        return units
    if count == 1:
        return ["".join(units)]
    result = []
    for index in range(count):
        left = round(index * len(units) / count)
        right = round((index + 1) * len(units) / count)
        result.append("".join(units[left:right]))
    return result


def funasr_timestamp_tokens(result, *, base_start=0.0, source="paraformer"):
    """Normalize FunASR millisecond timestamps to the pipeline token contract."""
    if not isinstance(result, dict):
        return []
    timestamps = result.get("timestamp") or result.get("timestamps") or []
    # Some FunASR/ModelScope combinations serialize timestamps before returning
    # them.  Treat that as the same public result shape instead of silently
    # turning a successful transcription into zero timeline units.
    if isinstance(timestamps, str):
        try:
            timestamps = ast.literal_eval(timestamps)
        except (SyntaxError, ValueError):
            timestamps = []
    valid = [item for item in timestamps if isinstance(item, (list, tuple)) and len(item) >= 2]
    if not valid:
        return []
    supplied = result.get("tokens") or result.get("token")
    if isinstance(supplied, str):
        units = supplied.split()
    elif isinstance(supplied, (list, tuple)):
        units = [str(item) for item in supplied]
    else:
        units = []
    if len(units) != len(valid):
        units = _split_text_for_timestamps(_clean_funasr_text(result.get("text", "")), len(valid))
    tokens = []
    for unit, stamp in zip(units, valid):
        text = _clean_funasr_text(unit)
        start = base_start + max(0.0, float(stamp[0]) / 1000.0)
        end = base_start + max(float(stamp[0]), float(stamp[1])) / 1000.0
        if content_only(text) and end > start:
            tokens.append(
                {
                    "text": text,
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "confidence": 0.82,
                    "source": source,
                }
            )
    return tokens


def _funasr_generate(model, wav_path, model_key):
    options = {"input": wav_path, "cache": {}, "batch_size_s": 60}
    if model_key == "sensevoice":
        options.update(language="auto", use_itn=True)
    elif model_key == "paraformer":
        # FunASR defaults pred_timestamp to False.  Without this flag inference
        # still succeeds and returns text, but no character timeline, which used
        # to be misreported as "主力转写没有生成可用片段".
        options.update(pred_timestamp=True)
    try:
        return model.generate(**options)
    except TypeError:
        return model.generate(input=wav_path)


def _load_funasr_model(model_key):
    cached = _session_funasr_model(model_key)
    if cached is not None:
        return cached
    import torch
    from funasr import AutoModel
    from twobyteasr.model_integrity import verify_model_files

    source = resolve_funasr_local_source(model_key)
    if not source:
        raise RuntimeError(f"{model_key} 未完整安装，请先在模型工坊下载。")
    verify_model_files(model_key, source)
    device = "cuda:0" if _cuda_runtime_ready() else "cpu"
    load_started = time.perf_counter()
    model_and_device = (
        AutoModel(model=source, device=device, disable_update=True),
        device,
    )
    _record_session_model_load(model_key, time.perf_counter() - load_started)
    return _reuse_or_remember_funasr_model(model_key, model_and_device)


def transcribe_funasr_reference(model_key, audio_path, speech_regions, shared_audio=None):
    """Run SenseVoice or Fun-ASR Nano over the same review chunks as Qwen."""
    import gc

    if model_key not in {"sensevoice", "funasr_nano"}:
        raise ValueError(f"Unsupported FunASR review model: {model_key}")
    owns_audio = shared_audio is None
    audio = decode_audio_to_array(audio_path) if owns_audio else shared_audio
    chunks = build_qwen_asr_chunks(audio, speech_regions, AUDIO_SAMPLE_RATE)
    if not chunks:
        return []
    if getattr(sys, "frozen", False):
        # 三十一轮：frozen 宿主不带 torch/funasr，进程内加载必炸且异常
        # 曾被上游吞成空结果（"识别失败，请检查模型与运行日志"）。走
        # main venv 子进程（与 Qwen3-ASR 同构），一次进程跑完所有块。
        return _transcribe_funasr_worker(model_key, chunks)
    model = None
    temporary_paths = []
    try:
        model, device = _load_funasr_model(model_key)
        print(f"   加载 {model_key}，生成本地文字复核证据（{device}）...")
        references = []
        for index, chunk in enumerate(chunks, 1):
            _raise_if_queue_cancelled()
            handle = tempfile.NamedTemporaryFile(prefix="2byteasr_funasr_", suffix=".wav", delete=False)
            wav_path = handle.name
            handle.close()
            temporary_paths.append(wav_path)
            write_pcm16_wav(wav_path, chunk["audio"][0])
            rows = _funasr_generate(model, wav_path, model_key) or []
            row = rows[0] if isinstance(rows, list) and rows else rows
            text = _clean_funasr_text(row.get("text", "") if isinstance(row, dict) else "")
            if content_only(text):
                references.append(
                    {
                        "start": chunk["start"],
                        "end": chunk["end"],
                        "text": text,
                        "source": model_key,
                    }
                )
            print(f"      {model_key} 短块 {index}/{len(chunks)}", flush=True)
        if not references:
            raise RuntimeError(f"{model_key} 没有生成有效文字。")
        return references
    finally:
        if model is not None and not _funasr_model_is_session_owned(model_key, model):
            del model
        for path in temporary_paths:
            try:
                os.unlink(path)
            except OSError:
                pass
        if owns_audio and audio is not None:
            del audio
        gc.collect()


def transcribe_paraformer_timeline(audio_source, *, force=False):
    """Generate Chinese token timestamps with the pinned local Paraformer model."""
    import gc

    backend = str(_legacy_runtime_value("FIRERED_ASR_BACKEND", FIRERED_ASR_BACKEND))
    if backend != "paraformer" and not force:
        return []
    owns_audio = isinstance(audio_source, (str, bytes, os.PathLike))
    audio = decode_audio_to_array(audio_source) if owns_audio else audio_source
    model = None
    wav_path = ""
    try:
        model, device = _load_funasr_model("paraformer")
        handle = tempfile.NamedTemporaryFile(prefix="2byteasr_paraformer_", suffix=".wav", delete=False)
        wav_path = handle.name
        handle.close()
        write_pcm16_wav(wav_path, audio)
        print(f"   加载 Paraformer，生成中文时间戳（{device}）...")
        rows = _funasr_generate(model, wav_path, "paraformer") or []
        row = rows[0] if isinstance(rows, list) and rows else rows
        tokens = funasr_timestamp_tokens(row, source="paraformer")
        if not tokens and isinstance(row, dict):
            # Keep Paraformer usable across hub/model revisions which omit CIF
            # timestamps despite the request.  This is explicitly a conservative
            # whole-audio distribution, not claimed as word-level alignment.
            text = _clean_funasr_text(row.get("text", ""))
            pieces = re.findall(
                r"[\u3400-\u9fff]|[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*|[^\s]",
                content_only(text),
            )
            duration = max(0.02, len(audio) / float(AUDIO_SAMPLE_RATE))
            if pieces:
                step = duration / len(pieces)
                tokens = [
                    {
                        "text": piece,
                        "start": round(index * step, 3),
                        "end": round((index + 1) * step, 3),
                        "confidence": 0.66,
                        "source": "paraformer-distributed",
                    }
                    for index, piece in enumerate(pieces)
                ]
                print(
                    "   [提示] Paraformer 未返回 CIF 时间戳，已按完整音频时长保守分配文字时间。"
                )
        print(f"   [完成] Paraformer：生成 {len(tokens)} 个时间单元。")
        return tokens
    except CancelledError:
        raise
    except Exception as exc:
        print(f"   [警告] Paraformer 时间轴失败，保留 MOSS 粗时间轴：{exc}")
        add_review_item(0.0, "时间轴模型失败", str(exc)[:160], priority=2)
        return []
    finally:
        if model is not None and not _funasr_model_is_session_owned("paraformer", model):
            del model
        if wav_path:
            try:
                os.unlink(wav_path)
            except OSError:
                pass
        if owns_audio and audio is not None:
            del audio
        gc.collect()


atexit.register(end_local_asr_session, force=True)


def build_qwen_asr_context(media_path):
    """只给 Qwen3-ASR 内容类型与文件名，不把 glossary 当强制热词。"""
    media_title = os.path.splitext(os.path.basename(media_path))[0]
    return (
        f"这是中文二次元游戏实况，文件名为《{media_title}》。"
        "请忠实转写实际语音，注意角色、技能和机制专名，"
        "不要凭文件名补写未说内容。"
    )


def build_qwen_asr_chunks(
    audio,
    speech_regions,
    sampling_rate=16000,
    *,
    chunk_seconds=None,
    max_merge_gap_seconds=None,
):
    """把 VAD 人声区间合并成短块，避免 Qwen 自回归解码整段长音频。

    三十六轮：块长可参（API 主力传 10s——MAI 等 API 的 segment 粒度是
    "大停顿"级，连续语流会整段共享一个时间戳，块越短匀速兜底的误差上界
    越小，且短上下文明显改善数字串烧等文本质量）。同一区间的切分缝
    不互相 pad：0.4s 双侧 pad 重叠曾让边界词被两块各识别一遍（"150"
    实录重复），pad 只留在区间外侧。max_merge_gap_seconds（API 主力
    传 1.0）：间隔超过该值的相邻区间不得合并——合并会把中间静音一起
    发给 API 并摊进字幕时间（0.2-1.6 与 5.0-6.4 合成 0-6.6 一行的实录）。
    """
    limit_seconds = float(
        chunk_seconds if chunk_seconds is not None else QWEN_ASR_CHUNK_SECONDS
    )
    audio_seconds = len(audio) / sampling_rate
    regions = [
        {
            "start": max(0.0, float(item["start"])),
            "end": min(audio_seconds, float(item["end"])),
        }
        for item in speech_regions
        if float(item["end"]) > float(item["start"])
    ]
    if not regions:
        regions = []
        offset = 0.0
        while offset < audio_seconds:
            regions.append(
                {
                    "start": offset,
                    "end": min(audio_seconds, offset + limit_seconds),
                }
            )
            offset += limit_seconds

    def _merge_exceeded(start, end, current_start, current_end):
        if end - current_start > limit_seconds:
            return True
        if max_merge_gap_seconds is None:
            return False
        return start - current_end > float(max_merge_gap_seconds)

    merged_ranges = []
    current_start = None
    current_end = None
    for region in regions:
        start = region["start"]
        end = region["end"]
        if current_start is None:
            current_start, current_end = start, end
            continue
        if _merge_exceeded(start, end, current_start, current_end):
            merged_ranges.append((current_start, current_end))
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    if current_start is not None:
        merged_ranges.append((current_start, current_end))

    # 三十一轮：单条超过上限的区间（增量层给 45s 合成区间）也要切开——
    # 原判断只在合并下一段时生效，超长单区间会整体透传成一条巨型 cue
    # （用户实录：一条 40s/48 字大段，chunk 内没有任何时间戳）。
    # 三十六轮：同一区间的切分缝不互相 pad（否则缝两侧各带 0.2s pad，
    # 边界词会被两块各识别一遍，"150" 用户实录重复），pad 只留区间外侧。
    pieces = []  # (start, end, pad_left, pad_right)
    for start, end in merged_ranges:
        piece_start = start
        while end - piece_start > limit_seconds:
            pieces.append((piece_start, piece_start + limit_seconds, piece_start == start, False))
            piece_start += limit_seconds
        if end > piece_start:
            pieces.append((piece_start, end, piece_start == start, True))

    chunks = []
    for start, end, pad_left, pad_right in pieces:
        padded_start = max(0.0, start - QWEN_ASR_AUDIO_PAD_SECONDS) if pad_left else start
        padded_end = (
            min(audio_seconds, end + QWEN_ASR_AUDIO_PAD_SECONDS)
            if pad_right
            else end
        )
        left = int(round(padded_start * sampling_rate))
        right = int(round(padded_end * sampling_rate))
        if right <= left:
            continue
        chunks.append(
            {
                "start": padded_start,
                "end": padded_end,
                "audio": (audio[left:right], sampling_rate),
            }
        )
    return chunks


def _pcm16_wav_bytes(audio, sampling_rate=AUDIO_SAMPLE_RATE):
    import numpy as np

    pcm = np.clip(np.asarray(audio), -1.0, 1.0)
    pcm = np.rint(pcm * 32767.0).astype("<i2", copy=False)
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(int(sampling_rate))
        wav_file.writeframes(pcm.tobytes())
    return stream.getvalue()


def _qwen_api_text(payload):
    choices = payload.get("output", {}).get("choices", [])
    if not choices:
        return ""
    content = choices[0].get("message", {}).get("content", [])
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict)
        ).strip()
    return ""


def _logprob_confidence(value, default=0.78):
    """Map whisper-style avg_logprob (<=0) into a 0..1 confidence; absent→default."""
    try:
        logprob = float(value)
    except (TypeError, ValueError):
        return float(default)
    if logprob > 0.0:
        return float(default)
    return max(0.0, min(1.0, 1.0 + logprob))


def _normalize_speaker_id(value):
    """把 diarization 返回的 speaker（int/str）归一成 S 命名（S00/S01…）。

    与 MOSS 说话人命名一致，便于复用下游说话人机制；注意是 file-local ID，
    不承诺跨文件身份稳定（三十八轮 SpeakerIdentityResolver 预留映射层）。
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return text
    try:
        return f"S{int(digits):02d}"
    except (TypeError, ValueError):
        return text


def _extract_transcription_segments(payload):
    """Normalize verbose_json segments to {start, end, text, confidence} rows."""
    rows = []
    for item in payload.get("segments") or []:
        if not isinstance(item, dict):
            continue
        try:
            start = max(0.0, float(item.get("start")))
            end = float(item.get("end"))
        except (TypeError, ValueError):
            continue
        text = clean_subtitle_text(str(item.get("text", "") or ""))
        if not text or end <= start:
            continue
        rows.append(
            {
                "start": start,
                "end": end,
                "text": text,
                "confidence": _logprob_confidence(item.get("avg_logprob")),
                "speaker": _normalize_speaker_id(item.get("speaker")),
            }
        )
    return rows


def _extract_transcription_words(payload):
    """Normalize verbose_json word timestamps (top-level or per-segment)."""
    raw = payload.get("words")
    if not isinstance(raw, list):
        raw = []
        for segment in payload.get("segments") or []:
            if isinstance(segment, dict) and isinstance(segment.get("words"), list):
                raw.extend(segment["words"])
    words = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            start = max(0.0, float(item.get("start")))
            end = float(item.get("end"))
        except (TypeError, ValueError):
            continue
        text = clean_subtitle_text(
            str(item.get("word", item.get("text", "")) or "")
        )
        if not text or end <= start:
            continue
        words.append(
            {
                "start": start,
                "end": end,
                "text": text,
                "confidence": _logprob_confidence(item.get("avg_logprob")),
                "speaker": _normalize_speaker_id(item.get("speaker")),
            }
        )
    return words


def _inherit_word_speakers_from_segments(words, segments):
    """words[].speaker 缺失时按时间所处 segment/phrase 继承 diarization。

    官方口径：Azure 只给 phrase 级 speaker，OpenRouter 把它贴到 segment 与
    word——但 word 级可能缺失。缺失不得等于丢弃 diarization（三十八轮用户
    指令），按 word 时间中点落入的 segment 继承。
    """
    for word in words:
        if word.get("speaker") is not None:
            continue
        midpoint = (float(word["start"]) + float(word["end"])) / 2.0
        candidates = {segment.get("speaker") for segment in segments
                      if float(segment["start"]) <= midpoint <= float(segment["end"])
                      and segment.get("speaker") is not None}
        if len(candidates) == 1:
            word["speaker"] = next(iter(candidates))
    return words


def _api_transcription_rows(result, chunk):
    """Expand one verbose_json chunk result into reference rows with real timing.

    相对时间戳以 chunk 音频切片起点（含 pad）为绝对偏移。三十八轮起
    **speaker change 是最高优先级的强制行边界**：一行绝不混合不同说话人的
    字，每行携带自己的 speaker（S 命名，file-local）；words 缺 speaker 时
    按时间所处 segment 继承 diarization。无 segments 时回退整块单行。
    """
    base = max(0.0, float(chunk["start"]))
    limit = max(base + 0.02, float(chunk["end"]))
    segments = list(result.get("segments") or [])
    words = _inherit_word_speakers_from_segments(
        [dict(word) for word in result.get("words") or []], segments
    )

    def _word_text(word):
        return str(word.get("text") or word.get("word") or "")

    def _clamped(rel_start, rel_end, lo):
        start = max(lo, min(limit, base + float(rel_start)))
        end = max(start + 0.02, min(limit, base + float(rel_end)))
        return start, end

    # 组 = [rel_start, rel_end, speaker, words, fallback_text, confidence]
    groups: list[list] = []
    owners = {}
    for index, word in enumerate(words):
        candidates = [s for s in segments if float(s['start'])-.05 <= float(word['start']) < float(s['end'])+.05]
        matching = [s for s in candidates if word.get('speaker') and _normalize_speaker_id(s.get('speaker')) == _normalize_speaker_id(word.get('speaker'))]
        if matching or candidates:
            owners[index] = max(matching or candidates, key=lambda s: min(float(s['end']),float(word['end']))-max(float(s['start']),float(word['start'])))
    for segment in segments:
        seg_start = float(segment["start"])
        seg_end = float(segment["end"])
        seg_speaker = _normalize_speaker_id(segment.get("speaker"))
        seg_words = [
            word
            for index, word in enumerate(words)
            if owners.get(index) is segment
        ]
        if not seg_words:
            groups.append(
                [seg_start, seg_end, seg_speaker, [], segment.get("text", ""),
                 float(segment.get("confidence", 0.78))]
            )
            continue
        current = None
        for word in seg_words:
            speaker = _normalize_speaker_id(word.get("speaker")) or seg_speaker
            if current is None or speaker != current[2]:
                current = [
                    float(word["start"]), float(word["end"]), speaker, [word],
                    "", float(segment.get("confidence", 0.78)),
                ]
                groups.append(current)
            else:
                current[1] = max(current[1], float(word["end"]))
                current[3].append(word)
    if not groups:
        current = None
        for word in words:
            speaker = _normalize_speaker_id(word.get("speaker"))
            if current is None or speaker != current[2]:
                current = [
                    float(word["start"]), float(word["end"]), speaker, [word],
                    "", float(word.get("confidence", 0.78)),
                ]
                groups.append(current)
            else:
                current[1] = max(current[1], float(word["end"]))
                current[3].append(word)
        if current is None:
            text = clean_subtitle_text(str(result.get("text", "") or ""))
            if content_only(text):
                return [{"start": base, "end": limit, "text": text}]
            return []

    rows = []
    floor = base
    for rel_start, rel_end, speaker, group_words, fallback_text, confidence in groups:
        # 整组落在块外（如提供方越界 segment）：丢弃，不得造 0.02s 垃圾行
        if base + float(rel_start) >= limit - 0.02:
            continue
        start, end = _clamped(rel_start, rel_end, base)
        if end <= start:
            continue
        if group_words:
            text = clean_subtitle_text("".join(_word_text(w) for w in group_words))
            tokens = []
            for word in group_words:
                token_start, token_end = _clamped(
                    float(word["start"]), float(word["end"]), start
                )
                tokens.append(
                    {
                        "start": token_start,
                        "end": token_end,
                        "text": _word_text(word),
                        "confidence": float(word.get("confidence", confidence)),
                    }
                )
        else:
            text = clean_subtitle_text(str(fallback_text or ""))
            tokens = []
        if not content_only(text):
            continue
        row = {
            "start": start,
            "end": end,
            "text": text,
            "confidence": float(confidence),
        }
        if speaker:
            row["speaker"] = str(speaker)
        if tokens:
            row["tokens"] = tokens
        rows.append(row)
    return rows


class _AsrApiThrottle:
    """进程级自适应节流（四十四轮 429 根治）。

    OpenRouter 等网关按时间窗限流：4 路并发 × 亚秒级重试只会火上浇油。
    所有 ASR API 请求共用此节流器：
    - acquire()：请求前排队，保证全局最小请求间隔；
    - report_429()：指数抬高最小间隔（尊重 Retry-After），并给一段公共冷却；
    - report_success()：连续成功 20 次后间隔减半（限流窗口过去后自动提速）。
    """

    _MAX_INTERVAL = 6.0
    _COOLDOWN_BASE = 0.6

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._min_interval = 0.0
        self._next_allowed = 0.0
        self._success_streak = 0

    def acquire(self) -> None:
        while True:
            with self._lock:
                wait = self._next_allowed - time.monotonic()
                if wait <= 0:
                    self._next_allowed = time.monotonic() + self._min_interval
                    return
            time.sleep(min(wait, 0.5))

    def report_429(self, retry_after: float = 0.0) -> None:
        with self._lock:
            self._min_interval = min(
                self._MAX_INTERVAL,
                max(self._min_interval * 2.0, self._COOLDOWN_BASE, float(retry_after or 0.0)),
            )
            self._success_streak = 0
            self._next_allowed = max(
                self._next_allowed,
                time.monotonic() + max(0.5, float(retry_after or 0.0)),
            )

    def report_success(self) -> None:
        with self._lock:
            self._success_streak += 1
            if self._min_interval > 0 and self._success_streak >= 20:
                self._min_interval /= 2.0
                self._success_streak = 0

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return {
                "min_interval": round(self._min_interval, 3),
                "success_streak": self._success_streak,
            }


_ASR_API_THROTTLE = _AsrApiThrottle()


def _retry_after_seconds(response) -> float:
    """解析 Retry-After 头（秒数或 HTTP 日期）；失败返回 0。"""
    try:
        raw = response.headers.get("Retry-After") or response.headers.get("retry-after")
    except Exception:
        return 0.0
    if not raw:
        return 0.0
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        pass
    try:
        from email.utils import parsedate_to_datetime

        target = parsedate_to_datetime(str(raw)).timestamp()
        return max(0.0, target - time.time())
    except Exception:
        return 0.0


def call_qwen_asr_api(audio, context, *, endpoint=None, requests_module=None):
    """Call DashScope or OpenAI-compatible ASR for one short 16 kHz mono chunk."""
    import requests as requests_package
    from twobyteasr.llm_config import (
        qwen_asr_endpoint_from_settings,
        validate_qwen_asr_endpoint,
    )

    runtime_settings = _legacy_runtime_value("RUNTIME_SETTINGS", RUNTIME_SETTINGS)
    endpoint = dict(endpoint or qwen_asr_endpoint_from_settings(runtime_settings))
    validate_qwen_asr_endpoint(endpoint)
    requests_module = requests_module or requests_package
    wav_data = _pcm16_wav_bytes(audio)
    request_token = get_runtime_context().cancellation_token
    def check_request_cancelled():
        if request_token is not None:request_token.raise_if_cancelled()
        else:_raise_if_queue_cancelled()
    protocol = endpoint.get("protocol", "dashscope_multimodal")
    from .speaker_evidence import save_speaker_evidence, public_request
    evidence_root = endpoint.get("audit_root", "")
    request_id = str(endpoint.get("audit_request", "request"))
    if protocol == "dashscope_multimodal":
        data_uri = "data:audio/wav;base64," + base64.b64encode(wav_data).decode("ascii")
        # 三十九轮：按 Qwen-ASR API 参考修正 asr_options——官方字段仅
        # language/enable_itn；enable_lid 是文档外参数（DashScope 会忽略，
        # 同步协议响应本就无时间戳/说话人，见 plan 三十九轮 Findings）。
        body = {
            "model": endpoint["model"],
            "input": {
                "messages": [
                    {"role": "system", "content": [{"text": context}]},
                    {"role": "user", "content": [{"audio": data_uri}]},
                ]
            },
            "parameters": {
                "asr_options": {
                    "enable_itn": True,
                    "language": "zh",
                }
            },
        }
        if str(endpoint.get("model", "")).startswith("qwen-audio-3.0-asr-flash"):
            body["input"]["messages"] = [{"role":"user","content":[
                {"type":"input_audio","input_audio":{"data":data_uri}}]}]
            body["parameters"] = {"format":"wav","sample_rate":16000}
    last_error = None
    is_multipart = protocol in {"openai_transcription", "azure_transcription"}
    # 三十七轮：OpenRouter JSON input_audio 通道（用户主动选择）——
    # verbose_json + segment/word 粒度 + Azure diarization，MAI-Transcribe-2
    # 返回字级时间戳（word: {word, start, end}），官方 STT 文档口径。
    is_openrouter_json = protocol == "openrouter_verbose_json"
    is_transcription = is_multipart or is_openrouter_json
    # 三十五轮：verbose_json 换取 segment/word 级时间戳（MAI-Transcribe-2 等），
    # 服务商拒收时同轮降级 json；降级记忆跨重试保留。
    verbose_ok = is_transcription
    granularities_ok = is_openrouter_json
    provider_ok = is_openrouter_json

    def _openrouter_body(
        with_granularities: bool, with_verbose: bool, with_provider: bool = True
    ) -> dict:
        payload = {
            "model": endpoint["model"],
            "input_audio": {
                "data": base64.b64encode(wav_data).decode("ascii"),
                "format": "wav",
            },
            "response_format": "verbose_json" if with_verbose else "json",
        }
        if with_granularities:
            payload["timestamp_granularities"] = ["segment", "word"]
        if with_provider:
            # Azure Fast Transcription 官方参数（provider.options.azure 原样转发）：
            # transcribeStyle clean|verbatim，官方默认 verbatim——我们要 clean 必须
            # 显式传（三十九轮）。diarization 见三十七轮。
            payload["provider"] = {
                "options": {
                    "azure": {
                        "diarization": {"enabled": True},
                        "modelOptions": {
                            "transcribeStyle": str(endpoint.get("style") or "clean"),
                        },
                    }
                }
            }
        return payload

    def _post_openrouter(
        with_granularities: bool, with_verbose: bool, with_provider: bool = True
    ):
        body = _openrouter_body(with_granularities, with_verbose, with_provider)
        save_speaker_evidence(evidence_root, f"{request_id}-sent-{time.time_ns()}",
            public_request(endpoint, **{k:v for k,v in body.items() if k != "input_audio"}))
        return requests_module.post(
            endpoint["url"],
            headers={
                "Authorization": f"Bearer {endpoint['api_key']}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=(10, 180),
        )

    # 四十四轮：429/5xx 重试从 3 次亚秒退避改为 6 次指数退避（1.5→20s 封顶，
    # 尊重 Retry-After），且全部请求过进程级自适应节流器——并发下也不会
    # 在限流窗口内连环撞墙（用户实录 590 块大面积 429 根因）。
    for attempt in range(6):
        check_request_cancelled()
        _ASR_API_THROTTLE.acquire()
        save_speaker_evidence(evidence_root, f"{request_id}-attempt{attempt}-request",
            public_request(endpoint, audio_seconds=len(audio)/AUDIO_SAMPLE_RATE,
                response_format="verbose_json" if verbose_ok else "json",
                timestamp_granularities=["segment","word"] if is_openrouter_json and granularities_ok else [],
                diarization_requested=bool(is_openrouter_json and provider_ok)))
        try:
            if is_openrouter_json:
                response = _post_openrouter(granularities_ok, verbose_ok, provider_ok)
                # 400 降级链：撤时间戳粒度 → 撤 verbose_json → 撤 provider 路由项
                # （diarization/transcribeStyle 被拒时的最终兜底）。
                if response.status_code == 400 and granularities_ok:
                    granularities_ok = False
                    response = _post_openrouter(False, verbose_ok, provider_ok)
                if response.status_code == 400 and verbose_ok:
                    verbose_ok = False
                    response = _post_openrouter(False, False, provider_ok)
                if response.status_code == 400 and provider_ok:
                    provider_ok = False
                    response = _post_openrouter(False, False, False)
            elif is_multipart:
                response_format = "verbose_json" if verbose_ok else "json"
                data = {"prompt": context[:900], "response_format": response_format}
                headers = (
                    {"api-key": endpoint["api_key"]}
                    if protocol == "azure_transcription"
                    # Azure OpenAI 部署式转写：模型由 URL 里的部署名决定，
                    # 鉴权用 api-key 头（三十二轮：MAI-Transcribe-2 的 Azure 通道）。
                    else {"Authorization": f"Bearer {endpoint['api_key']}"}
                )
                if protocol == "openai_transcription":
                    data["model"] = endpoint["model"]
                response = requests_module.post(
                    endpoint["url"],
                    headers=headers,
                    files={"file": ("chunk.wav", wav_data, "audio/wav")},
                    data=data,
                    timeout=(10, 180),
                )
                if response.status_code == 400 and verbose_ok:
                    verbose_ok = False
                    response = requests_module.post(
                        endpoint["url"],
                        headers=headers,
                        files={"file": ("chunk.wav", wav_data, "audio/wav")},
                        data={**data, "response_format": "json"},
                        timeout=(10, 180),
                    )
            else:
                response = requests_module.post(
                    endpoint["url"],
                    headers={
                        "Authorization": f"Bearer {endpoint['api_key']}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                    timeout=(10, 180),
                )
            check_request_cancelled()
            payload = response.json()
            save_speaker_evidence(evidence_root, f"{request_id}-attempt{attempt}-raw", payload)
            if response.status_code == 200:
                _ASR_API_THROTTLE.report_success()
                if not is_transcription:
                    sentence = (payload.get("output") or {}).get("sentence")
                    if isinstance(sentence, dict):
                        # Ordinary Flash's channel_id is a physical channel,
                        # never a person. Filetrans alone supplies speaker_id.
                        normalized = _filetrans_task_rows({"transcripts":[{"sentences":[
                            {k:v for k,v in sentence.items() if k not in {"channel_id", "speaker_id"}}
                        ]}]}, len(audio)/AUDIO_SAMPLE_RATE)
                        return normalized
                    text = _qwen_api_text(payload)
                    if text:
                        return clean_subtitle_text(text)
                    raise RuntimeError("ASR API 返回成功，但没有识别文本。")
                save_speaker_evidence(evidence_root, f"{request_id}-attempt{attempt}-raw", payload)
                segments = _extract_transcription_segments(payload)
                words = _extract_transcription_words(payload)
                text = clean_subtitle_text(str(payload.get("text", "") or ""))
                if text or segments:
                    return {"text": text, "segments": segments, "words": words}
                if words:
                    return {"text": "", "segments": [], "words": words}
                # 无人声块（BGM/静音段是游戏素材常态）：空结果合法，不当失败重试。
                return {"text": "", "segments": [], "words": []}
            code = str(payload.get("code", "") or "")
            message = str(payload.get("message", "") or response.reason or "未知错误")
            last_error = RuntimeError(
                f"ASR API 请求失败（HTTP {response.status_code} / {code or 'no-code'}）：{message}"
            )
            if response.status_code == 429:
                _ASR_API_THROTTLE.report_429(_retry_after_seconds(response))
            if response.status_code not in {429, 500, 502, 503, 504}:
                break
        except CancelledError:
            raise
        except Exception as exc:
            last_error = exc
        if attempt < 5:
            until=time.monotonic()+min(20.0,1.5*(2**attempt))
            while time.monotonic()<until:
                check_request_cancelled();time.sleep(min(.1,max(0.,until-time.monotonic())))
    raise RuntimeError(str(last_error or "ASR API 请求失败。"))


def _transcribe_api_owned(audio_path, chunks, *, publish_primary=False):
    from .asr_api_process import transcribe
    return transcribe(audio_path,chunks,publish_primary=publish_primary)


def _transcribe_qwen_api(audio_path, chunks, *, publish_primary=False, _endpoint=None, _context=None):
    from twobyteasr.llm_config import asr_api_display, qwen_asr_endpoint_from_settings

    runtime_settings = _legacy_runtime_value("RUNTIME_SETTINGS", RUNTIME_SETTINGS)
    endpoint = dict(_endpoint or qwen_asr_endpoint_from_settings(runtime_settings))
    from .speaker_evidence import save_speaker_evidence, scope_request_speakers
    if not endpoint.get("audit_root") and os.path.isfile(audio_path):
        endpoint["audit_root"] = str(Path(media_cache_context(audio_path)["cache_dir"]) / "speaker-evidence")
    endpoint.setdefault("audit_root", "")
    save_speaker_evidence(endpoint["audit_root"], "request-ranges",
        [{"request":i,"start":c["start"],"end":c["end"],"samples":len(c["audio"][0])} for i,c in enumerate(chunks)])
    def normalize(result, index):
        rows = _api_transcription_rows(result, chunks[index])
        save_speaker_evidence(endpoint["audit_root"], f"chunk{index}-normalized", rows)
        return scope_request_speakers(rows,index,len(chunks))
    display = asr_api_display(endpoint)
    context = _context if _context is not None else build_qwen_asr_context(audio_path)
    workers = max(1, min(6, int(CLOUD_BATCH_WORKERS), len(chunks)))
    started = time.perf_counter()
    results = [None] * len(chunks)
    print(f"   使用 {display}，{workers} 路并发转写短块...")
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="qwen-asr-api")
    from .asr_progress import PrimaryProgress
    progress = PrimaryProgress(audio_path,len(chunks),publish_primary=publish_primary)
    rate_limited = False
    failed_indices: set[int] = set()
    try:
        iterator = iter(enumerate(chunks))
        futures = {}
        def submit_next():
            item = next(iterator, None)
            if item is None:return
            index, chunk = item
            future = pool.submit(call_qwen_asr_api, chunk["audio"][0], context,
                                 endpoint={**endpoint,"audit_request":f"chunk{index}"})
            futures[future] = index
            return future
        for _ in range(workers):submit_next()
        # 轮询完成（与 run_parallel_stages 同款）：as_completed 的迭代本身
        # 会阻塞等待下一个 future，取消检查永远执行不到；这里在每轮等待
        # 前先检查取消，用户取消后 50ms 内即退出。
        pending = set(futures)
        while pending:
            _raise_if_queue_cancelled()
            done = {future for future in pending if future.done()}
            if not done:
                time.sleep(0.05)
                continue
            for future in done:
                pending.discard(future)
                index = futures.pop(future)
                next_future = submit_next()
                if next_future is not None:pending.add(next_future)
                try:
                    result = future.result()
                except CancelledError:
                    raise
                except Exception as exc:
                    if "HTTP 429" in str(exc):
                        rate_limited = True
                    failed_indices.add(index)
                    print(f"      [警告] {display} 短块 {index + 1}/{len(chunks)} 失败：{exc}")
                    continue
                failed_indices.discard(index)
                if isinstance(result, dict):
                    # verbose_json：真实段级（或字级）时间戳展开成多行 reference
                    rows = normalize(result, index)
                    if rows:
                        results[index] = rows
                    progress.complete(index, results[index] or [])
                    continue
                if content_only(result):
                    results[index] = [
                        {
                            "start": chunks[index]["start"],
                            "end": chunks[index]["end"],
                            "text": result,
                        }
                    ]
                progress.complete(index,results[index] or [])
    except CancelledError:
        # P1-5：取消路径不等待在途 HTTP 请求（不再因 with 语义的
        # shutdown(wait=True) 阻塞最长 180 秒）。worker task
        # （call_qwen_asr_api）是纯 HTTP+返回值、无副作用——已发出的
        # 请求继续执行（同步 requests 不可硬取消，可能仍产生 API 费用），
        # 其迟到结果不会进入结果表（coordinator 已退出收集循环）；
        # 未开始执行的 future 被 cancel_futures 取消，不再发起新请求。
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        pool.shutdown(wait=True)
    # 四十四轮：失败块补扫轮——主扫失败的块不再直接丢弃（字幕出空洞），
    # 串行重试至多 4 轮。此时节流器已被 429 抬高间隔，串行+节流=温和重放。
    for sweep in range(4):
        if not failed_indices:
            break
        _raise_if_queue_cancelled()
        pending_retry = sorted(failed_indices)
        print(
            f"   [补扫 {sweep + 1}/4] {display}：重试 {len(pending_retry)} 个失败短块"
            "（限流退避后串行重放）…"
        )
        for index in pending_retry:
            _raise_if_queue_cancelled()
            try:
                result = call_qwen_asr_api(chunks[index]["audio"][0], context,
                    endpoint={**endpoint,"audit_request":f"chunk{index}-retry{sweep}"})
            except CancelledError:
                raise
            except Exception as exc:
                print(f"      [警告] {display} 短块 {index + 1}/{len(chunks)} 重试失败：{exc}")
                continue
            failed_indices.discard(index)
            if isinstance(result, dict):
                rows = normalize(result, index)
                if rows:
                    results[index] = rows
            elif content_only(result):
                results[index] = [
                    {
                        "start": chunks[index]["start"],
                        "end": chunks[index]["end"],
                        "text": result,
                    }
                ]
    if failed_indices:
        missing_ms = sum(
            int(chunks[index]["end"]) - int(chunks[index]["start"])
            for index in failed_indices
        )
        print(
            f"   [警告] {display}：{len(failed_indices)} 个短块最终失败"
            f"（约 {missing_ms / 1000:.0f} 秒素材无字幕，可重跑识别补齐）"
        )
    for index, rows in enumerate(results):
        if rows and index not in progress.completed:progress.complete(index,rows,force=index==len(results)-1)
    progress.complete(max(progress.completed,default=0),[],force=True)
    references = [row for item in results if item for row in item]
    save_speaker_evidence(endpoint["audit_root"], "merged", references)
    if not references:
        hint = "（检测到限流 HTTP 429：请稍后重试或降低并发）" if rate_limited else ""
        raise RuntimeError(
            f"{display} 没有成功返回任何短块。请检查 API Key、余额和网络。{hint}"
        )
    print(
        f"   [完成] {display}：{len(references)} 条文字（{len(chunks)} 个短块），"
        f"耗时 {time.perf_counter() - started:.1f} 秒。"
    )
    return references


def _filetrans_task_url(endpoint, task_id: str) -> str:
    """轮询 URL：与提交端点同根（自定义网关/新域名也能用）。"""
    base = str(endpoint.get("url") or "")
    marker = "/api/v1/"
    idx = base.find(marker)
    root = base[:idx] if idx >= 0 else "https://dashscope.aliyuncs.com"
    return f"{root}/api/v1/tasks/{task_id}"


def _filetrans_cancel_task(requests_module, endpoint, task_id: str) -> None:
    """用户取消后尽力取消云端任务（PENDING 可取消；失败不影响本地取消路径）。"""
    try:
        requests_module.post(
            _filetrans_task_url(endpoint, task_id) + "/cancel",
            headers={"Authorization": f"Bearer {endpoint['api_key']}"},
            timeout=(5, 15),
        )
    except Exception:
        pass


class _FiletransTaskError(RuntimeError):
    """filetrans 任务在服务端执行失败（携带服务端 code，如 InvalidParameter.ParseError）。"""

    def __init__(self, status: str, code: str, message: str):
        self.task_status = status
        self.code = code
        super().__init__(f"filetrans 任务失败（{status} / {code or 'no-code'}）：{message}")


def _filetrans_submit(requests_module, endpoint, file_url: str, context: str, parameters: dict) -> str:
    """提交异步转写任务，返回 task_id。

    四十一轮修正（用户实录 InvalidParameter.ParseError）：
    - `enable_words` 不是本路线合法参数（词级 words 结果自动返回）→ 删除；
    - `input.context` 是数组 [{role, content:[{type,text}]}]，不是 {user:[...]}；
    - 新域名（工作台 maas 域）要求 parameters 必传（空也要 {}）。
    提交 400 时先撤 context 再撤 parameters 之外的修饰。
    """
    headers = {
        "Authorization": f"Bearer {endpoint['api_key']}",
        "Content-Type": "application/json",
        # 官方要求：漏掉 X-DashScope-Async 会退化为同步调用而失败。
        "X-DashScope-Async": "enable",
    }
    input_block = {"file_urls": [file_url]}
    if str(context or "").strip():
        input_block["context"] = [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": str(context)[:2000]}],
            }
        ]
    attempts = [
        {"model": endpoint["model"], "input": input_block, "parameters": dict(parameters)},
        {"model": endpoint["model"], "input": {"file_urls": [file_url]}, "parameters": dict(parameters)},
        {"model": endpoint["model"], "input": {"file_urls": [file_url]}, "parameters": {}},
    ]
    last_detail = ""
    for body in attempts:
        from .speaker_evidence import save_speaker_evidence, public_request
        save_speaker_evidence(endpoint.get("audit_root"),f"filetrans-submit-{time.time_ns()}",
            public_request(endpoint, parameters=body["parameters"], audio_files=len(body["input"]["file_urls"]),
                           has_context="context" in body["input"]))
        response = requests_module.post(endpoint["url"], headers=headers, json=body, timeout=(10, 60))
        try:
            payload = response.json() if callable(getattr(response, "json", None)) else {}
        except Exception:
            payload = {}
        if response.status_code == 200:
            task_id = str((payload.get("output") or {}).get("task_id") or "")
            if task_id:
                return task_id
            raise RuntimeError(
                "提交 filetrans 任务成功但没有 task_id："
                f"{payload.get('code', '')} {payload.get('message', '')}"
            )
        last_detail = (
            f"HTTP {response.status_code} / {payload.get('code', 'no-code')}："
            f"{payload.get('message', '') or response.reason}"
        )
    raise RuntimeError(f"提交 filetrans 任务失败（{last_detail}）")


def _filetrans_poll(
    requests_module,
    endpoint,
    task_id: str,
    *,
    poll_interval: float = 2.0,
    max_wait_seconds: float | None = None,
):
    """轮询到终态。SUCCEEDED 返回 transcription_url；FAILED/CANCELED 抛错。

    异步任务语义（用户规格）：submit 返回 ≠ 识别完成。每轮 poll 前检查取消，
    用户取消在 50ms~poll_interval 内退出。
    """
    deadline = time.monotonic() + (
        max_wait_seconds if max_wait_seconds is not None else 7200.0
    )
    reported = set()
    while True:
        _raise_if_queue_cancelled()
        response = requests_module.get(
            _filetrans_task_url(endpoint, task_id),
            headers={"Authorization": f"Bearer {endpoint['api_key']}"},
            timeout=(10, 60),
        )
        try:
            payload = response.json() if callable(getattr(response, "json", None)) else {}
        except Exception:
            payload = {}
        output = payload.get("output") or {}
        status = str(output.get("task_status") or "")
        if status and status not in reported:
            reported.add(status)
            print(f"   [OSS 文件转写] 任务状态：{status}")
        if status == "SUCCEEDED":
            # 只要任一子任务成功整体即 SUCCEEDED：必须找 subtask SUCCEEDED 的结果。
            for item in output.get("results") or []:
                if (
                    str(item.get("subtask_status") or "") == "SUCCEEDED"
                    and item.get("transcription_url")
                ):
                    return str(item["transcription_url"])
            details = "; ".join(
                f"{item.get('code')}:{item.get('message')}" for item in output.get("results") or []
            )
            raise _FiletransTaskError(status, "", f"任务完成但没有可用结果：{details or '无 results'}")
        if status in {"FAILED", "CANCELED", "EXPIRED", "CANCEL"}:
            message = str(output.get("message") or "")
            code = str(output.get("code") or "")
            if not message or not code:
                for item in output.get("results") or []:
                    if str(item.get("subtask_status") or "") != "SUCCEEDED":
                        code = code or str(item.get("code") or "")
                        message = message or str(item.get("message") or "")
            raise _FiletransTaskError(status, code, message or "未知原因")
        if time.monotonic() > deadline:
            raise TimeoutError(f"filetrans 任务超过安全时限（{task_id}）。")
        time.sleep(poll_interval)


def _filetrans_download(requests_module, transcription_url: str) -> dict:
    response = requests_module.get(transcription_url, timeout=(10, 180))
    if response.status_code != 200:
        raise RuntimeError(f"下载识别结果失败（HTTP {response.status_code}）。")
    return response.json()


def _filetrans_task_rows(result_payload, audio_seconds: float) -> dict:
    """filetrans 结果（ms）→ verbose_json 同构 {text, segments, words}。

    复用 `_api_transcription_rows` 的展开/说话人继承/边界钳制：句 speaker_id
    进 segment.speaker，词缺 speaker 时按时间所处 segment 继承（三十八轮语义）。
    """
    transcripts = list(result_payload.get("transcripts") or [])
    segments = []
    words = []
    for transcript in transcripts:
        for sentence in transcript.get("sentences") or []:
            begin = max(0.0, float(sentence.get("begin_time") or 0) / 1000.0)
            end = max(begin, float(sentence.get("end_time") or 0) / 1000.0)
            segment = {
                "start": begin,
                "end": end,
                "text": str(sentence.get("text") or ""),
                "confidence": 0.78,
            }
            speaker = sentence.get("speaker_id")
            if speaker is not None:
                segment["speaker"] = speaker
            segments.append(segment)
            for word in sentence.get("words") or []:
                entry = {
                    "start": max(0.0, float(word.get("begin_time") or 0) / 1000.0),
                    "end": max(0.0, float(word.get("end_time") or 0) / 1000.0),
                    # 官方结果字段名是 text（非 word）。
                    "text": str(word.get("text") or word.get("word") or "") + str(word.get("punctuation") or ""),
                    "confidence": 0.78,
                }
                word_speaker=word.get('speaker_id',speaker)
                if word_speaker is not None:
                    entry["speaker"] = word_speaker
                words.append(entry)
    text = str((transcripts[0] if transcripts else {}).get("text") or "")
    return {"text": text, "segments": segments, "words": words}


def _transcribe_qwen_filetrans(
    audio_path,
    audio,
    *,
    endpoint=None,
    requests_module=None,
    storage=None,
):
    """Qwen 录音文件识别（异步 filetrans）整段转写，返回 reference 行。

    生命周期：PREPARING_AUDIO → UPLOADING → SUBMITTING → (PENDING/RUNNING) →
    DOWNLOADING_RESULT → PARSING → CLEANING_UP → COMPLETED/FAILED。
    上传进度与识别进度分开汇报；try/finally 保证成功/失败/取消都删临时对象。
    OSS AccessKey 只用于签名，绝不进入 Qwen 请求体或日志。
    """
    import requests as requests_package

    from twobyteasr.llm_config import asr_api_display, qwen_asr_endpoint_from_settings
    from twobyteasr.temp_audio_storage import oss_storage_from_settings, redact_signed_url

    runtime_settings = _legacy_runtime_value("RUNTIME_SETTINGS", RUNTIME_SETTINGS)
    endpoint = dict(endpoint or qwen_asr_endpoint_from_settings(runtime_settings))
    requests_module = requests_module or requests_package
    display = asr_api_display(endpoint)
    models = runtime_settings.get("models", {}) or {}
    auto_delete = bool(models.get("oss_auto_delete", True))
    if storage is None:
        storage = oss_storage_from_settings(runtime_settings)
        if storage is None:
            raise RuntimeError(
                "未配置 OSS 临时存储：Qwen 录音文件识别需要先把音频上传到你的"
                "阿里云 OSS（设置 → 云端 ASR 中转存储，AccessKey 用 DPAPI 加密保存）。"
            )
    audio_seconds = float(len(audio) or 0) / float(AUDIO_SAMPLE_RATE)
    from .speaker_evidence import save_speaker_evidence, scope_request_speakers
    endpoint.setdefault("audit_root",str(Path(media_cache_context(audio_path)["cache_dir"])/"speaker-evidence"))
    context = build_qwen_asr_context(audio_path)
    started = time.perf_counter()
    stored = None
    task_id = None
    print(
        f"   [OSS 文件转写] PREPARING_AUDIO：整段音频 {audio_seconds / 60:.1f} 分钟"
        f"（{display}，服务端 VAD，不做本地切块）"
    )
    wav_data = _pcm16_wav_bytes(audio)
    try:
        _raise_if_queue_cancelled()
        print(
            f"   [OSS 文件转写] UPLOADING：{len(wav_data) / 1048576:.1f} MB → {storage.describe()}"
        )
        stored = storage.upload_audio(wav_data, "wav")
        url = storage.create_download_url(stored.key)
        # 日志红线：预签名 URL 的 query 含签名凭据派生值，必须脱敏。
        print(f"   [OSS 文件转写] 预签名 URL（TTL 内有效）：{redact_signed_url(url)}")
        storage.verify_download_url(url)
        print("   [OSS 文件转写] SUBMITTING：提交异步识别任务…")
        # 任务级参数降级链：提交接口只做惰性校验（400 拦不住执行期
        # InvalidParameter.ParseError——用户实录四十一轮），所以任务在服务端
        # 因参数被拒时换更保守的参数重提。词级 words 结果自动返回无需参数；
        # diarization_enabled 给说话人分离；新域名要求 parameters 必传。
        variants = (
            ("context+diarization", {"diarization_enabled": True}, True),
            ("diarization", {"diarization_enabled": True}, False),
        )
        for label, parameters, use_context in variants:
            task_id = _filetrans_submit(
                requests_module,
                endpoint,
                url,
                context if use_context else "",
                parameters,
            )
            print(
                f"   [OSS 文件转写] 任务已受理（task_id={task_id}，参数={label}），"
                "进入 PENDING/RUNNING 轮询…"
            )
            try:
                result_url = _filetrans_poll(requests_module, endpoint, task_id)
                print("   [OSS 文件转写] DOWNLOADING_RESULT：下载识别结果…")
                result_payload = _filetrans_download(requests_module, result_url)
                save_speaker_evidence(endpoint["audit_root"],"filetrans-original",result_payload)
                print("   [OSS 文件转写] PARSING：解析句/词级时间戳（ms→s）…")
                rows = _api_transcription_rows(
                    _filetrans_task_rows(result_payload, audio_seconds),
                    {"start": 0.0, "end": audio_seconds},
                )
                save_speaker_evidence(endpoint["audit_root"],"filetrans-normalized",rows)
                rows = scope_request_speakers(rows,0,1)
                break
            except _FiletransTaskError as exc:
                retryable = (
                    "InvalidParameter" in f"{exc.code} {exc}"
                    and (label, parameters, use_context) != variants[-1]
                )
                if not retryable:
                    raise
                print(
                    f"   [OSS 文件转写][警告] 服务端拒绝参数（{exc.code or exc.task_status}），"
                    f"降级为更保守参数重提（{label} → 下一级）…"
                )
                continue
    except CancelledError:
        if task_id:
            _filetrans_cancel_task(requests_module, endpoint, task_id)
        raise
    finally:
        if stored is not None:
            if auto_delete:
                print(f"   [OSS 文件转写] CLEANING_UP：删除临时对象 {stored.key}")
                storage.delete_object(stored.key)
            else:
                print(
                    f"   [OSS 文件转写] 已按设置保留临时对象 {stored.key}"
                    "（自动删除关闭；48 小时后由启动清理兜底）"
                )
    if not rows:
        raise RuntimeError(f"{display} 识别完成但没有可用的字幕行（可能整段无人声）。")
    speakers = {row.get("speaker") for row in rows if row.get("speaker")}
    print(
        f"   [完成] {display}：{len(rows)} 行字幕、{len(speakers)} 位说话人，"
        f"耗时 {time.perf_counter() - started:.1f} 秒。"
    )
    return rows


def _run_firered_llm_worker(chunks):
    """Transcribe bounded ASR chunks in the isolated FireRed LLM environment."""
    import subtitle_core

    root = os.path.abspath(subtitle_core.SCRIPT_DIR)
    from twobyteasr.runtime_registry import resolve_runtime_python

    python_executable = resolve_runtime_python("firered_llm")
    worker = os.path.join(root, "firered_llm_worker.py")
    from twobyteasr.runtime_paths import resolve_model_dir

    model_dir = str(resolve_model_dir("FireRedASR2-LLM"))
    for path, label in (
        (python_executable, "FireRed LLM 独立 Python"),
        (worker, "FireRed LLM worker"),
        (model_dir, "FireRedASR2-LLM 模型"),
    ):
        if not os.path.exists(path):
            raise RuntimeError(f"缺少 {label}：{path}")

    with tempfile.TemporaryDirectory(prefix="firered_llm_asr_") as temp_dir:
        jobs = []
        for index, chunk in enumerate(chunks, 1):
            wav_path = os.path.join(temp_dir, f"chunk_{index:04d}.wav")
            write_pcm16_wav(wav_path, chunk["audio"][0])
            jobs.append({"segment_id": index, "path": wav_path})
        manifest_path = os.path.join(temp_dir, "manifest.json")
        output_path = os.path.join(temp_dir, "results.json")
        Path(manifest_path).write_text(
            json.dumps({"jobs": jobs}, ensure_ascii=False), encoding="utf-8"
        )

        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        process = popen_hidden_subprocess(
            [
                python_executable,
                worker,
                "--manifest",
                manifest_path,
                "--output",
                output_path,
                "--model-dir",
                model_dir,
            ],
            purpose="FireRed LLM worker",
            process_factory=subprocess.Popen,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )
        output_lines = []

        def read_output():
            for line in process.stdout or ():
                value = line.rstrip()
                output_lines.append(value)
                if value.startswith("[2BYTEASR_FIRERED_LLM]"):
                    print(f"      {value}", flush=True)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        deadline = time.monotonic() + max(1800.0, len(jobs) * 180.0)
        try:
            while process.poll() is None:
                _raise_if_queue_cancelled()
                if time.monotonic() > deadline:
                    raise TimeoutError("FireRedASR2-LLM 子进程超过安全时限。")
                time.sleep(0.2)
            reader.join(timeout=5)
        except BaseException:
            stop_process_tree(process)
            raise
        if process.returncode != 0:
            raise RuntimeError(
                "FireRedASR2-LLM 子进程失败：" + "\n".join(output_lines[-20:])
            )
        with open(output_path, "r", encoding="utf-8") as stream:
            values = {
                int(item["segment_id"]): str(item.get("text") or "")
                for item in json.load(stream).get("results", [])
            }
        references = []
        for index, chunk in enumerate(chunks, 1):
            text = clean_subtitle_text(values.get(index, ""))
            if content_only(text):
                references.append(
                    {"start": chunk["start"], "end": chunk["end"], "text": text}
                )
        if not references:
            raise RuntimeError("FireRedASR2-LLM 没有生成可用文字。")
        return references


def transcribe_firered_llm_reference(audio_path, speech_regions, shared_audio=None):
    audio = shared_audio if shared_audio is not None else decode_audio_to_array(audio_path)
    chunks = build_qwen_asr_chunks(audio, speech_regions, AUDIO_SAMPLE_RATE)
    if not chunks:
        return []
    print(f"   加载 FireRedASR2-LLM，转写 {len(chunks)} 个人声短块...")
    references = _run_firered_llm_worker(chunks)
    print(f"   [完成] FireRedASR2-LLM：{len(references)}/{len(chunks)} 个短块。")
    return references


def _recognized_confidence(result, default=0.0):
    """Read a recognizer-provided confidence without substituting consensus."""
    candidates = []
    if isinstance(result, dict):
        candidates.extend(result.get(key) for key in ("confidence", "probability", "score"))
    else:
        candidates.extend(getattr(result, key, None) for key in ("confidence", "probability", "score"))
    for value in candidates:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if 0.0 <= numeric <= 1.0:
            return numeric
    return float(default)


def transcribe_qwen_reference(
    audio_path,
    speech_regions,
    shared_audio=None,
    *,
    backend_override=None,
):
    """Qwen3-ASR 1.7B 提供第三份中文文字证据，不生成或修改时间戳。"""
    use_qwen = bool(_legacy_runtime_value("USE_QWEN_ASR_REFERENCE", USE_QWEN_ASR_REFERENCE))
    backend = str(
        backend_override
        if backend_override is not None
        else _legacy_runtime_value("QWEN_ASR_BACKEND", QWEN_ASR_BACKEND)
    )
    if backend_override is not None:
        use_qwen = True
    if not use_qwen or backend == "off":
        return []
    if backend == "whisper_turbo":
        try:
            return transcribe_whisper_reference(audio_path, speech_regions, shared_audio)
        except CancelledError:
            raise
        except Exception as exc:
            print(f"   [警告] Whisper 复核失败，自动沿用 FireRed/MOSS：{exc}")
            add_review_item(0.0, "Whisper失败", str(exc)[:160], priority=2)
            return []
    if backend in {"sensevoice", "funasr_nano"}:
        try:
            return transcribe_funasr_reference(
                backend, audio_path, speech_regions, shared_audio
            )
        except CancelledError:
            raise
        except Exception as exc:
            if backend_override is not None:
                # 主力路径（backend_override）失败必须如实上报：吞成空结果
                # 会让整轮识别以 empty_result 失败且日志找不到原因
                # （三十一轮 SenseVoice 用户实录）。
                raise
            print(f"   [警告] {backend} 复核失败，自动沿用 FireRed/MOSS：{exc}")
            add_review_item(0.0, f"{backend}失败", str(exc)[:160], priority=2)
            return []

    if backend == "firered_llm":
        try:
            return transcribe_firered_llm_reference(
                audio_path, speech_regions, shared_audio
            )
        except CancelledError:
            raise
        except Exception as exc:
            print(f"   [警告] FireRedASR2-LLM 复核失败：{exc}")
            add_review_item(0.0, "FireRed LLM失败", str(exc)[:160], priority=2)
            return []

    model = None
    audio = shared_audio
    owns_audio = shared_audio is None
    try:
        sampling_rate = AUDIO_SAMPLE_RATE
        if audio is None:
            audio = decode_audio_to_array(audio_path)
        # 三十六轮：API 主力（backend_override 来自 transcribe_primary_reference）
        # 用 10s 短块——MAI segment 粒度粗 + 25s 块让多句共享一个时间戳，
        # 匀速兜底误差到秒级（异环自行车实录）。API 复核保持 25s（只要文字）。
        # gap>1s 的相邻 VAD 区间不合并：合并会把中间静音摊进字幕时间。
        # 四十轮：filetrans 协议例外——整段上传 OSS 交给服务端 VAD，本地不切块。
        api_primary = backend == "api" and backend_override is not None
        if backend == "api":
            from twobyteasr.llm_config import qwen_asr_endpoint_from_settings

            from .runtime import get_runtime_context
            api_endpoint = dict(get_runtime_context().asr_endpoint_snapshot or
                qwen_asr_endpoint_from_settings(
                    _legacy_runtime_value("RUNTIME_SETTINGS", RUNTIME_SETTINGS)
                )
            )
            from .cloud_asr_jobs import FLASH, FILETRANS, SPARK
            if api_endpoint.get('model') in {FLASH,FILETRANS,SPARK}:
                # Native workers receive the complete frozen analysis waveform;
                # their own bounded chunks retain silence and exact offsets.
                return _transcribe_api_owned(audio_path,[dict(start=0,end=len(audio)/sampling_rate,
                    audio=(audio,sampling_rate))],publish_primary=api_primary)
            if str(api_endpoint.get("protocol") or "") == "dashscope_filetrans":
                return _transcribe_qwen_filetrans(audio_path, audio, endpoint=api_endpoint)
            if api_primary and str(api_endpoint.get("protocol")) == "openrouter_verbose_json":
                # One request gives provider diarization a global scope on the
                # common three-minute edit. Long tasks retain explicit request
                # scopes; no number-based speaker merging across requests.
                limit = round(180 * sampling_rate)
                chunks = [{"start":offset/sampling_rate,
                           "end":min(len(audio),offset+limit)/sampling_rate,
                           "audio":(audio[offset:offset+limit],sampling_rate)}
                          for offset in range(0,len(audio),limit)]
                return _transcribe_api_owned(audio_path,chunks,publish_primary=True)
        chunks = build_qwen_asr_chunks(
            audio,
            speech_regions,
            sampling_rate,
            chunk_seconds=(
                QWEN_ASR_API_CHUNK_SECONDS if api_primary else None
            ),
            max_merge_gap_seconds=(1.0 if api_primary else None),
        )
        if not chunks:
            label = "Qwen3-ASR"
            if backend == "api":
                from twobyteasr.llm_config import asr_api_display, qwen_asr_endpoint_from_settings

                label = asr_api_display(
                    qwen_asr_endpoint_from_settings(
                        _legacy_runtime_value("RUNTIME_SETTINGS", RUNTIME_SETTINGS)
                    )
                )
            print(f"   [警告] {label} 没有可转写的人声短块，本次跳过。")
            return []

        if backend == "api":
            return _transcribe_api_owned(audio_path, chunks, publish_primary=api_primary)
        if backend != "local":
            return []

        if getattr(sys, "frozen", False):
            model_path = resolve_qwen_asr_local_source()
            if not model_path:
                raise RuntimeError("Qwen3-ASR local model directory is missing")
            return _transcribe_qwen_worker(audio, chunks, model_path)

        import gc
        import torch

        print(f"   加载 Qwen3-ASR 1.7B，按 VAD 短块生成第三份文字参考...")

        model_load_started = time.perf_counter()
        model = load_qwen_asr_model()
        model_load_ms = (time.perf_counter() - model_load_started) * 1000.0
        if model is None:
            raise RuntimeError("Qwen3-ASR model loader returned no model")

        context = build_qwen_asr_context(audio_path)
        started = time.perf_counter()
        references = []
        batch_count = (len(chunks) + QWEN_ASR_BATCH_SIZE - 1) // QWEN_ASR_BATCH_SIZE
        for batch_index, offset in enumerate(
            range(0, len(chunks), QWEN_ASR_BATCH_SIZE), 1
        ):
            _raise_if_queue_cancelled()
            batch = chunks[offset : offset + QWEN_ASR_BATCH_SIZE]
            batch_started = time.perf_counter()
            results = model.transcribe(
                audio=[item["audio"] for item in batch],
                context=[context] * len(batch),
                language=["Chinese"] * len(batch),
                return_time_stamps=False,
            )
            for chunk, result in zip(batch, results):
                text = clean_subtitle_text(result.text)
                if content_only(text):
                    confidence = _recognized_confidence(result)
                    references.append(
                        {
                            "start": chunk["start"],
                            "end": chunk["end"],
                            "text": text,
                            "confidence": confidence,
                        }
                    )
            print(
                f"      Qwen3-ASR 批次 {batch_index}/{batch_count}："
                f"{time.perf_counter() - batch_started:.1f} 秒",
                flush=True,
            )
        elapsed = time.perf_counter() - started
        from twobyteasr.cache import record_run_event
        record_run_event(
            "QWEN_RUNTIME",
            QWEN_PYTHON_EXECUTABLE=sys.executable,
            QWEN_WORKER_ENTRYPOINT="qwen_asr.Qwen3ASRModel.transcribe",
            QWEN_MODEL_PATH=str(resolve_qwen_asr_local_source()),
            QWEN_DEVICE="cuda:0",
            QWEN_CUDA_AVAILABLE=True,
            QWEN_GPU_NAME="",
            QWEN_INPUT_CHUNK_COUNT=len(chunks),
            QWEN_PROCESS_PID=os.getpid(),
            QWEN_MODEL_LOAD_MS=round(float(locals().get("model_load_ms", 0.0)), 3),
            QWEN_INFERENCE_MS=round(elapsed * 1000.0, 3),
            QWEN_RAW_RESULT_COUNT=len(references),
            QWEN_PARSED_RESULT_COUNT=len(references),
            QWEN_STDERR="",
        )
        print(
            f"   [完成] Qwen3-ASR：{len(references)}/{len(chunks)} 个短块，"
            f"纯转写 {elapsed:.1f} 秒。"
        )
        return references
    except CancelledError:
        raise
    except Exception as exc:
        if backend_override is not None:
            # 主力路径失败必须如实上报（三十一轮 SenseVoice 教训），
            # 吞成空结果会让整轮识别以 misleading 的 empty_result 失败。
            raise
        label = "Qwen3-ASR"
        category = "Qwen3失败"
        if backend == "api":
            try:
                from twobyteasr.llm_config import (
                    asr_api_display,
                    qwen_asr_endpoint_from_settings,
                )

                label = asr_api_display(
                    qwen_asr_endpoint_from_settings(
                        _legacy_runtime_value("RUNTIME_SETTINGS", RUNTIME_SETTINGS)
                    )
                )
            except Exception:
                label = "ASR API"
            category = "API复核失败"
        print(f"   [警告] {label} 复核失败：{exc}")
        add_review_item(
            0.0,
            category,
            str(exc)[:160],
            priority=2,
        )
        if backend == "local":
            raise RuntimeError(f"Qwen3-ASR inference failed: {type(exc).__name__}: {exc}") from exc
        return []
    finally:
        session_owned = model is not None and _qwen_model_is_session_owned(model)
        if model is not None and not session_owned:
            del model
        if owns_audio and audio is not None:
            del audio
        import gc

        gc.collect()
        if backend == "local" and not getattr(sys, "frozen", False):
            # frozen GUI has no in-process torch; the worker subprocess owns
            # its GPU memory and releases it on exit. Importing torch here
            # would raise in the finally block and discard the worker result.
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()


def write_pcm16_wav(path, audio):
    """从统一 float32 采样直接写 WAV，避免 ffmpeg 分段 seek 的时间取整。"""
    import numpy as np

    pcm = np.clip(np.asarray(audio), -1.0, 1.0)
    pcm = np.rint(pcm * 32767.0).astype("<i2", copy=False)
    with wave.open(path, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(AUDIO_SAMPLE_RATE)
        wav_file.writeframes(pcm.tobytes())


def _run_isolated_asr_worker(command, output_path, *, model_id, audio_input, model_path, entrypoint,
                             input_text=None, event_handler=None, cancel_handler=None, timeout_seconds=None):
    """Run a model worker and return parsed JSON plus process telemetry."""
    from twobyteasr.processes import popen_hidden_subprocess, stop_process_tree

    started_wall = time.time()
    started_perf = time.perf_counter()
    from twobyteasr.processes import external_python_environment
    from twobyteasr.python_runtime_identity import file_identity, environment_difference, save_identity
    environment = external_python_environment()
    if entrypoint == "sensevoice_worker.py":
        from twobyteasr.runtime_registry import load_registry
        save_identity("production-launch", dict(command=list(map(str, command)), cwd=os.getcwd(),
            selected=file_identity(command[0]), registration=load_registry().get("main"),
            environment_difference=environment_difference(os.environ, environment)))
    process = popen_hidden_subprocess(
        command, purpose=f"{model_id} ASR worker", process_factory=subprocess.Popen,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", env=environment,
        stdin=subprocess.PIPE if input_text is not None else None,
    )
    # Drain both pipes continuously, publish completed work, and own cancellation.
    import queue
    from collections import deque
    from .cache import record_run_event
    lines=queue.Queue(maxsize=256)
    worker_identity = dict(model_id=model_id, backend=model_id.lower(), pid=process.pid,
                           worker=str(entrypoint), runtime=str(command[0]),
                           role='primary_transcription' if model_id == 'PRIMARY_API' else 'asr_worker',
                           execution='worker_process_started', loaded=None)
    record_run_event('asr_worker_started', **worker_identity)
    record_run_event('MODEL_STARTED', **worker_identity)
    stop_readers=threading.Event()
    captured={'stdout':deque(maxlen=200),'stderr':deque(maxlen=200)}
    def read_pipe(pipe,kind):
        try:
            for line in iter(pipe.readline,''):
                while not stop_readers.is_set():
                    try:lines.put((kind,line),timeout=.1);break
                    except queue.Full:pass
                if stop_readers.is_set():break
        finally:pipe.close()
    readers=[threading.Thread(target=read_pipe,args=(pipe,kind),daemon=True)
             for pipe,kind in ((process.stdout,'stdout'),(process.stderr,'stderr'))]
    for reader in readers:reader.start()
    deadline=started_perf+max(60.,float(os.environ.get('TWOBYTEASR_ASR_WORKER_TIMEOUT',str(timeout_seconds or 3600))))
    try:
        if input_text is not None:
            process.stdin.write(input_text)
            process.stdin.close()
        while process.poll() is None or any(t.is_alive() for t in readers) or not lines.empty():
            _raise_if_queue_cancelled()
            if time.perf_counter()>deadline:raise RuntimeError(f'{model_id} worker timeout')
            try:kind,line=lines.get(timeout=.1)
            except queue.Empty:continue
            captured[kind].append(line)
            if line.startswith('[2BYTEASR_SPEAKER] '):
                event=json.loads(line[len('[2BYTEASR_SPEAKER] '):])
                record_run_event('speaker_progress',worker_pid=process.pid,**event)
                if event_handler is not None:event_handler(event)
                continue
            if event_handler is not None and line.startswith('[2BYTEASR_API] '):
                event_handler(json.loads(line[len('[2BYTEASR_API] '):]))
                continue
            marker='[2BYTEASR_FIRERED_AED] '
            if line.startswith(marker):
                try:event=json.loads(line[len(marker):])
                except (ValueError,TypeError):continue
                if event.get('event')=='batch_completed':
                    record_run_event('asr_evidence_delta',backend='firered',state='provisional_evidence',
                        worker_pid=process.pid,**{key:value for key,value in event.items() if key!='event'})
                elif event.get('event') in {'loading','loaded','model_dtype','concurrency_reduced'}:
                    record_run_event('asr_worker_progress',backend='firered',worker_pid=process.pid,
                        worker_state=event['event'],**{key:value for key,value in event.items() if key!='event'})
        _raise_if_queue_cancelled()
    except BaseException:
        if cancel_handler is not None and process.poll() is None:
            try:
                cancel_handler()
                process.wait(timeout=3)
            except Exception:
                pass
        # Windows venv launchers are parents of the actual Python worker.
        # taskkill completion may precede descendant handle release.
        import psutil
        try:children=psutil.Process(process.pid).children(recursive=True)
        except psutil.Error:children=[]
        stop_process_tree(process)
        _,pending_children=psutil.wait_procs(children,timeout=3)
        for child in pending_children:
            try:child.kill()
            except psutil.NoSuchProcess:pass
        if pending_children:psutil.wait_procs(pending_children,timeout=3)
        raise
    finally:
        stop_readers.set()
        for reader in readers:reader.join(timeout=5)
        record_run_event('asr_worker_exited',backend=model_id.lower(),pid=process.pid,
            returncode=process.poll(),readers_stopped=not any(t.is_alive() for t in readers))
    stdout,stderr=''.join(captured['stdout']),''.join(captured['stderr'])
    elapsed_ms = (time.perf_counter() - started_perf) * 1000.0
    if process.returncode != 0:
        raise RuntimeError(f"{model_id} worker failed (exit {process.returncode}):\nstdout:\n{stdout[-4500:]}\nstderr:\n{stderr[-1500:]}")
    try:
        payload = json.loads(Path(output_path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"{model_id} worker produced no valid output: {exc}") from exc
    from twobyteasr.cache import record_run_event
    count = len(payload.get("results", [])) if isinstance(payload, dict) else 0
    alignment_samples = _parse_firered_alignment_telemetry(stdout) if model_id == "FIRERED" else []
    forced_align_error = bool(
        model_id == "FIRERED"
        and "forced_align" in (stderr or "")
        and "RuntimeError" in (stderr or "")
    )
    if model_id == "FIRERED":
        record_run_event('firered_performance',load_ms=payload.get('load_ms'),
            inference_ms=payload.get('inference_ms'),worker_elapsed_ms=elapsed_ms,
            **dict(payload.get('telemetry') or {}))
        record_run_event(
            "FIRERED_RAW_SCHEMA",
            producer="firered_aed_worker",
            consumer="firered_adapter",
            shape=schema_shape(payload),
            raw_result_count=count,
        )
    record_run_event(
        f"{model_id.upper()}_PROCESS",
        **({
            "FIRERED_PYTHON_EXECUTABLE": command[0],
            "FIRERED_ENTRYPOINT": entrypoint,
            "FIRERED_MODEL_PATH": model_path,
            "FIRERED_DEVICE": "cuda:0",
            "FIRERED_CUDA_AVAILABLE": True,
            "FIRERED_GPU_NAME": "",
            "FIRERED_AUDIO_INPUT": audio_input,
            "FIRERED_AUDIO_DURATION": 0.0,
            "FIRERED_PROCESS_PID": process.pid,
            "FIRERED_PROCESS_START": started_wall,
            "FIRERED_STDOUT": (stdout or "")[-4000:],
            "FIRERED_STDERR": (stderr or "")[-4000:],
            "FIRERED_RAW_RESULT_COUNT": count,
            "FIRERED_PARSED_SEGMENT_COUNT": count,
            "FIRERED_ALIGNMENT_DTYPE_SAMPLES": alignment_samples,
            "FIRERED_FORCED_ALIGN_ERROR": forced_align_error,
        } if model_id == "FIRERED" else {
            'pid':process.pid,'device':'network','elapsed_ms':elapsed_ms,'result_rows':count,
            'owned_process_exited':process.poll() is not None,
        } if model_id == 'PRIMARY_API' else {
            "QWEN_PYTHON_EXECUTABLE": command[0],
            "QWEN_WORKER_ENTRYPOINT": entrypoint,
            "QWEN_MODEL_PATH": model_path,
            "QWEN_DEVICE": "cuda:0",
            "QWEN_CUDA_AVAILABLE": True,
            "QWEN_GPU_NAME": "",
            "QWEN_INPUT_CHUNK_COUNT": count,
            "QWEN_PROCESS_PID": process.pid,
            "QWEN_MODEL_LOAD_MS": float(payload.get("load_ms", 0.0) or 0.0),
            "QWEN_INFERENCE_MS": float(payload.get("inference_ms", elapsed_ms) or elapsed_ms),
            "QWEN_RAW_RESULT_COUNT": count,
            "QWEN_PARSED_RESULT_COUNT": count,
            "QWEN_STDERR": (stderr or "")[-4000:],
        }),
    )
    if forced_align_error:
        record_run_event(
            "FIRERED_FORCED_ALIGN_FAILURE",
            producer="fireredasr_aed",
            consumer="firered_adapter",
            alignment_samples=alignment_samples,
            stderr_tail=(stderr or "")[-4000:],
        )
        raise RuntimeError(
            "FireRed forced alignment failed; refusing text-only output: "
            + (stderr or "")[-1000:]
        )
    return payload


def _parse_firered_alignment_telemetry(stdout):
    """Extract bounded dtype evidence emitted at FireRed's alignment boundary."""
    markers = ("[2BYTEASR_FIRERED_ALIGN_DTYPE] ", "[2BYTEASR_FIRERED_AED] ")
    samples = []
    for line in (stdout or "").splitlines():
        marker = next((item for item in markers if line.startswith(item)), None)
        if marker is None:
            continue
        try:
            value = json.loads(line[len(marker):])
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict) and (value.get("event") == "align_dtype" or "log_probs_dtype" in value):
            samples.append(value)
    return samples[-8:]


def _transcribe_firered_worker(audio, audio_seconds, firered_dir):
    from twobyteasr.runtime_registry import resolve_runtime_python

    runtime = _main_worker_python()
    worker = os.path.join(os.path.abspath(SCRIPT_DIR), "firered_aed_worker.py")
    if not os.path.isfile(runtime) or not os.path.isfile(worker):
        raise RuntimeError(f"FireRed worker runtime missing: python={runtime}, worker={worker}")
    with tempfile.TemporaryDirectory(prefix="firered_aed_worker_") as temp_dir:
        segmentation_started=time.perf_counter()
        jobs = []
        offset = 0.0
        chunk_index = 0
        while offset < audio_seconds - 0.01:
            chunk_index += 1
            end = min(audio_seconds, offset + FIRERED_CHUNK_SECONDS)
            path = os.path.join(temp_dir, f"chunk_{chunk_index:04d}.wav")
            write_pcm16_wav(path, audio[int(round(offset * AUDIO_SAMPLE_RATE)):int(round(end * AUDIO_SAMPLE_RATE))])
            jobs.append({"segment_id": chunk_index, "path": path, "offset": offset, "duration": end - offset})
            if end >= audio_seconds - 0.01:
                break
            offset += FIRERED_CHUNK_STEP_SECONDS
        manifest = os.path.join(temp_dir, "manifest.json")
        output = os.path.join(temp_dir, "results.json")
        Path(manifest).write_text(
            json.dumps({"jobs": jobs}, ensure_ascii=False), encoding="utf-8"
        )
        from .cache import record_run_event
        record_run_event('firered_audio_prepared',elapsed_ms=round((time.perf_counter()-segmentation_started)*1000,3),
            chunk_count=len(jobs),audio_seconds=audio_seconds,coverage='full_audio',batch_size=1)
        payload = _run_isolated_asr_worker(
            [runtime, '-I', worker, "--manifest", manifest, "--output", output, "--model-dir", firered_dir],
            output, model_id="FIRERED", audio_input="shared_audio", model_path=firered_dir,
            entrypoint="firered_aed_worker.py",
        )
        normalized = normalize_firered_worker_result(
            payload,
            jobs,
            producer="firered_aed_worker",
            consumer="firered_adapter",
        )
        from twobyteasr.cache import record_run_event
        record_run_event(
            "FIRERED_NORMALIZED_SCHEMA",
            producer="firered_adapter",
            consumer="firered_timeline",
            shape=schema_shape(normalized),
            normalized_segment_count=len(normalized["segments"]),
        )
        if not normalized["segments"]:
            raise RuntimeError("FireRed worker returned no parsed tokens")
        return normalized


def _transcribe_qwen_worker(audio, chunks, model_path):
    from twobyteasr.runtime_registry import resolve_runtime_python

    runtime = _main_worker_python()
    worker = os.path.join(os.path.abspath(SCRIPT_DIR), "qwen_asr_worker.py")
    if not os.path.isfile(runtime) or not os.path.isfile(worker):
        raise RuntimeError(f"Qwen worker runtime missing: python={runtime}, worker={worker}")
    with tempfile.TemporaryDirectory(prefix="qwen_asr_worker_") as temp_dir:
        jobs = []
        for index, chunk in enumerate(chunks, 1):
            path = os.path.join(temp_dir, f"chunk_{index:04d}.wav")
            write_pcm16_wav(path, chunk["audio"][0])
            jobs.append({"segment_id": index, "path": path, "start": chunk["start"], "end": chunk["end"]})
        manifest = os.path.join(temp_dir, "manifest.json")
        output = os.path.join(temp_dir, "results.json")
        Path(manifest).write_text(
            json.dumps({"jobs": jobs}, ensure_ascii=False), encoding="utf-8"
        )
        payload = _run_isolated_asr_worker(
            [runtime, '-I', worker, "--manifest", manifest, "--output", output, "--model-dir", model_path],
            output, model_id="QWEN3-ASR", audio_input="shared_audio", model_path=model_path,
            entrypoint="qwen_asr_worker.py",
        )
        values = payload.get("results", []) if isinstance(payload, dict) else []
        references = []
        for chunk, value in zip(chunks, values):
            text = clean_subtitle_text(value.get("text", ""))
            if content_only(text):
                references.append({"start": chunk["start"], "end": chunk["end"], "text": text, "confidence": float(value.get("confidence", 0.0) or 0.0)})
        if not references:
            raise RuntimeError("Qwen worker returned no parsed text")
        return references


def _transcribe_funasr_worker(model_key, chunks):
    """Frozen-mode FunASR route: one main-venv subprocess for all chunks."""
    from twobyteasr.runtime_registry import resolve_runtime_python

    source = resolve_funasr_local_source(model_key)
    if not source:
        raise RuntimeError(f"{model_key} 未完整安装，请先在模型工坊下载。")
    runtime = _main_worker_python()
    worker = os.path.join(os.path.abspath(SCRIPT_DIR), "sensevoice_worker.py")
    if not os.path.isfile(runtime) or not os.path.isfile(worker):
        raise RuntimeError(f"{model_key} worker runtime missing: python={runtime}, worker={worker}")
    with tempfile.TemporaryDirectory(prefix="funasr_worker_") as temp_dir:
        jobs = []
        for index, chunk in enumerate(chunks, 1):
            path = os.path.join(temp_dir, f"chunk_{index:04d}.wav")
            write_pcm16_wav(path, chunk["audio"][0])
            jobs.append(
                {
                    "segment_id": index,
                    "path": path,
                    "start": chunk["start"],
                    "end": chunk["end"],
                }
            )
        manifest = os.path.join(temp_dir, "manifest.json")
        output = os.path.join(temp_dir, "results.json")
        Path(manifest).write_text(
            json.dumps({"model_key": model_key, "jobs": jobs}, ensure_ascii=False),
            encoding="utf-8",
        )
        payload = _run_isolated_asr_worker(
            [
                runtime, "-I", "-X", "utf8", worker,
                "--manifest", manifest, "--output", output,
                "--model-key", model_key, "--model-dir", source,
            ],
            output, model_id="SENSEVOICE", audio_input="shared_audio", model_path=source,
            entrypoint="sensevoice_worker.py",
        )
        values = payload.get("results", []) if isinstance(payload, dict) else []
        references = []
        for chunk, value in zip(chunks, values):
            text = _clean_funasr_text(str(value.get("text", "")))
            if content_only(text):
                references.append(
                    {
                        "start": chunk["start"],
                        "end": chunk["end"],
                        "text": text,
                        "source": model_key,
                    }
                )
        if not references:
            raise RuntimeError(f"{model_key} worker returned no parsed text")
        return references


def transcribe_firered_reference(audio_source, audio_seconds, *, beam_size=3, force=False):
    """FireRed 提供第二份文字证据和可信边界，不直接覆盖主转写。"""
    use_firered = bool(
        _legacy_runtime_value(
            "USE_FIRERED_BOUNDARY_REFINEMENT", USE_FIRERED_BOUNDARY_REFINEMENT
        )
    )
    backend = str(_legacy_runtime_value("FIRERED_ASR_BACKEND", FIRERED_ASR_BACKEND))
    if (not use_firered or backend != "local") and not force:
        return []
    from twobyteasr.runtime_paths import resolve_model_dir

    firered_dir = str(resolve_model_dir("FireRedASR2-AED"))
    if not os.path.isdir(FIRERED_SOURCE_DIR) or not os.path.isdir(firered_dir):
        raise RuntimeError(
            f"FireRed-AED runtime missing: source={FIRERED_SOURCE_DIR!r}, model={firered_dir!r}"
        )
    if getattr(sys, "frozen", False) or str(_legacy_runtime_value('PRIMARY_ASR_BACKEND','')) == 'api':
        audio = audio_source if not isinstance(audio_source, (str, bytes, os.PathLike)) else decode_audio_to_array(audio_source)
        try:
            return _transcribe_firered_worker(audio, min(float(audio_seconds), len(audio) / AUDIO_SAMPLE_RATE), firered_dir)
        finally:
            if isinstance(audio_source, (str, bytes, os.PathLike)):
                del audio
    print("   加载 FireRedASR2-AED，辅助校准字级首尾边界...")
    import gc
    import torch

    if not _cuda_runtime_ready():
        raise RuntimeError("FireRed-AED requires a usable CUDA runtime")

    if FIRERED_SOURCE_DIR not in sys.path:
        sys.path.insert(0, FIRERED_SOURCE_DIR)

    with _TORCH_PATCH_LOCK:
        # FireRedASR2-AED 在 bf16 下不稳定，强制 FP16；
        # 捕获与替换都在锁内，避免并发线程把已替换的 lambda 当成"原值"。
        original_bf16_check = torch.cuda.is_bf16_supported
        torch.cuda.is_bf16_supported = lambda: False
    model = None
    audio = None
    runtime_started_wall = time.time()
    owns_audio = isinstance(audio_source, (str, bytes, os.PathLike))
    try:
        from twobyteasr.model_integrity import verify_model_files

        verify_model_files("firered_aed", firered_dir)
        from fireredasr2s.fireredasr2 import FireRedAsr2, FireRedAsr2Config

        audio = (
            decode_audio_to_array(audio_source)
            if owns_audio
            else audio_source
        )
        decoded_seconds = len(audio) / AUDIO_SAMPLE_RATE
        audio_seconds = min(float(audio_seconds), decoded_seconds)

        config = FireRedAsr2Config(
            use_gpu=True,
            use_half=True,
            beam_size=max(1, min(8, int(beam_size))),
            nbest=1,
            decode_max_len=0,
            softmax_smoothing=1.25,
            aed_length_penalty=0.6,
            eos_penalty=1.0,
            return_timestamp=True,
        )
        model = FireRedAsr2.from_pretrained("aed", firered_dir, config)
        tokens = []
        with tempfile.TemporaryDirectory(prefix="asr_firered_") as temp_dir:
            offset = 0.0
            chunk_index = 0
            while offset < audio_seconds - 0.01:
                _raise_if_queue_cancelled()
                chunk_index += 1
                chunk_end = min(audio_seconds, offset + FIRERED_CHUNK_SECONDS)
                is_first = chunk_index == 1
                is_last = chunk_end >= audio_seconds - 0.01
                owned_start = 0.0 if is_first else offset + 1.0
                owned_end = float("inf") if is_last else offset + FIRERED_CHUNK_SECONDS - 1.0
                chunk_path = os.path.join(temp_dir, f"chunk_{chunk_index:04d}.wav")
                start_sample = int(round(offset * AUDIO_SAMPLE_RATE))
                end_sample = int(round(chunk_end * AUDIO_SAMPLE_RATE))
                write_pcm16_wav(chunk_path, audio[start_sample:end_sample])
                result = model.transcribe(
                    [f"chunk_{chunk_index:04d}"], [chunk_path]
                )[0]
                for token, start, end in result.get("timestamp") or []:
                    global_start = offset + float(start)
                    global_end = offset + float(end)
                    midpoint = (global_start + global_end) / 2.0
                    if owned_start <= midpoint < owned_end:
                        tokens.append(
                            {
                                "text": str(token),
                                "start": global_start,
                                "end": global_end,
                                "confidence": float(result.get("confidence", 0.75)),
                            }
                        )
                if is_last:
                    break
                offset += FIRERED_CHUNK_STEP_SECONDS

        from twobyteasr.cache import record_run_event
        record_run_event(
            "FIRERED_RAW_SCHEMA",
            producer="fireredasr2s.FireRedAsr2.transcribe",
            consumer="firered_adapter",
            shape=schema_shape(tokens),
            raw_result_count=len(tokens),
        )
        normalized_result = canonical_result_from_segments(
            tokens,
            producer="fireredasr2s.FireRedAsr2.transcribe",
            consumer="firered_adapter",
            backend="firered",
            provenance={"normalization": "in_process_timestamp_tokens_to_asr_result"},
        )
        record_run_event(
            "FIRERED_NORMALIZED_SCHEMA",
            producer="firered_adapter",
            consumer="firered_timeline",
            shape=schema_shape(normalized_result),
            normalized_segment_count=len(tokens),
        )
        record_run_event(
            "FIRERED_RUNTIME",
            FIRERED_PYTHON_EXECUTABLE=sys.executable,
            FIRERED_ENTRYPOINT="fireredasr2s.fireredasr2.FireRedAsr2.transcribe",
            FIRERED_MODEL_PATH=firered_dir,
            FIRERED_DEVICE="cuda:0",
            FIRERED_CUDA_AVAILABLE=True,
            FIRERED_GPU_NAME="",
            FIRERED_AUDIO_INPUT=str(audio_source) if owns_audio else "shared_audio",
            FIRERED_AUDIO_DURATION=round(float(audio_seconds), 3),
            FIRERED_PROCESS_PID=os.getpid(),
            FIRERED_PROCESS_START=runtime_started_wall,
            FIRERED_STDOUT="",
            FIRERED_STDERR="",
            FIRERED_RAW_RESULT_COUNT=len(tokens),
            FIRERED_PARSED_SEGMENT_COUNT=len(tokens),
        )
        print(f"   [完成] FireRed：{len(tokens)} 个候选字词边界。")
        return normalized_result
    except CancelledError:
        raise
    except Exception as exc:
        print(f"   [警告] FireRed-AED 识别失败：{exc}")
        try:
            from twobyteasr.cache import record_run_event
            record_run_event(
                "FIRERED_RUNTIME",
                FIRERED_PYTHON_EXECUTABLE=sys.executable,
                FIRERED_ENTRYPOINT="fireredasr2s.fireredasr2.FireRedAsr2.transcribe",
                FIRERED_MODEL_PATH=firered_dir,
                FIRERED_DEVICE="cuda:0",
                FIRERED_CUDA_AVAILABLE=False,
                FIRERED_GPU_NAME="",
                FIRERED_AUDIO_INPUT=str(audio_source) if owns_audio else "shared_audio",
                FIRERED_AUDIO_DURATION=round(float(audio_seconds), 3),
                FIRERED_PROCESS_PID=os.getpid(),
                FIRERED_PROCESS_START=runtime_started_wall,
                FIRERED_STDOUT="",
                FIRERED_STDERR=f"{type(exc).__name__}: {exc}",
                FIRERED_RAW_RESULT_COUNT=0,
                FIRERED_PARSED_SEGMENT_COUNT=0,
            )
        except Exception:
            pass
        raise RuntimeError(f"FireRed-AED inference failed: {type(exc).__name__}: {exc}") from exc
    finally:
        with _TORCH_PATCH_LOCK:
            torch.cuda.is_bf16_supported = original_bf16_check
        if model is not None:
            del model
        if owns_audio and audio is not None:
            del audio
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def tokens_to_reference_chunks(tokens, speech_regions, *, source):
    """Group word/token timestamps into the common ASR chunk contract."""
    cleaned_tokens = sorted(
        (
            {
                **item,
                "start": float(item.get("start", 0.0)),
                "end": float(item.get("end", 0.0)),
                "text": str(item.get("text", "")),
            }
            for item in (tokens or [])
            if content_only(str(item.get("text", "")))
            and float(item.get("end", 0.0)) > float(item.get("start", 0.0))
        ),
        key=lambda item: (item["start"], item["end"]),
    )
    if not cleaned_tokens:
        return []
    regions = [
        (float(item.get("start", 0.0)), float(item.get("end", 0.0)))
        for item in (speech_regions or [])
        if float(item.get("end", 0.0)) > float(item.get("start", 0.0))
    ]
    if not regions:
        regions = [(cleaned_tokens[0]["start"], cleaned_tokens[-1]["end"])]
    chunks = []
    used = set()
    for region_start, region_end in regions:
        matches = []
        for index, token in enumerate(cleaned_tokens):
            midpoint = (token["start"] + token["end"]) / 2.0
            if region_start <= midpoint <= region_end:
                matches.append(token)
                used.add(index)
        if matches:
            chunks.append(
                {
                    "start": min(item["start"] for item in matches),
                    "end": max(item["end"] for item in matches),
                    "text": clean_subtitle_text("".join(item["text"] for item in matches)),
                    "source": source,
                    "tokens": matches,
                }
            )
    for index, token in enumerate(cleaned_tokens):
        if index not in used:
            chunks.append(
                {
                    "start": token["start"],
                    "end": token["end"],
                    "text": clean_subtitle_text(token["text"]),
                    "source": source,
                    "tokens": [token],
                }
            )
    return sorted(chunks, key=lambda item: (item["start"], item["end"]))


def transcribe_primary_reference(
    backend,
    audio_path,
    speech_regions,
    shared_audio,
    audio_seconds,
):
    """Run a non-MOSS primary backend and return normalized timed text chunks."""
    backend = str(backend or "moss")
    if backend == 'glm_asr_nano':
        return transcribe_glm_reference(shared_audio,speech_regions)
    if backend == 'canary_qwen':
        return _transcribe_dedicated_reference('canary','Canary','canary-qwen-2.5b','canary_asr_worker.py',shared_audio,speech_regions)
    if backend == "firered":
        result = transcribe_firered_reference(
            shared_audio, audio_seconds, force=True
        )
        from .asr_schema import flatten_segment_tokens
        tokens = flatten_segment_tokens(result,producer='firered_adapter',consumer='firered_primary_reference')
        return tokens_to_reference_chunks(tokens, speech_regions, source="firered-primary")
    if backend == "firered_llm":
        return transcribe_firered_llm_reference(
            audio_path, speech_regions, shared_audio
        )
    if backend == "paraformer":
        tokens = transcribe_paraformer_timeline(shared_audio, force=True)
        return tokens_to_reference_chunks(tokens, speech_regions, source="paraformer-primary")
    mapped = "local" if backend == "qwen_local" else backend
    if mapped in {"api", "local", "whisper_turbo", "sensevoice", "funasr_nano"}:
        rows = transcribe_qwen_reference(
            audio_path,
            speech_regions,
            shared_audio,
            backend_override=mapped,
        )
        for row in rows:
            row.setdefault("source", f"{backend}-primary")
        return rows
    raise RuntimeError(f"不支持的主力转写后端：{backend}")


def transcribe_glm_reference(audio, speech_regions):
    return _transcribe_dedicated_reference('glm_asr','GLM','GLM-ASR-Nano-2512','glm_asr_worker.py',audio,speech_regions)


def _transcribe_dedicated_reference(role, label, model_dir, worker_name, audio, speech_regions):
    from .runtime_registry import resolve_runtime_python
    from .runtime_paths import resolve_model_dir
    runtime=resolve_runtime_python(role)
    if not runtime or not os.path.isfile(runtime):
        raise RuntimeError(label+' 独立运行库未准备，请在模型工坊点击校验并修复。')
    source=str(resolve_model_dir(model_dir))
    worker=os.path.join(os.path.abspath(SCRIPT_DIR),worker_name)
    with tempfile.TemporaryDirectory(prefix=role+'_worker_') as directory:
        jobs=[]
        for region in speech_regions:
            cursor=float(region['start']);end=min(float(region['end']),len(audio)/AUDIO_SAMPLE_RATE)
            while cursor<end:
                stop=min(end,cursor+30)
                path=os.path.join(directory,f'chunk_{len(jobs):04d}.wav')
                write_pcm16_wav(path,audio[round(cursor*AUDIO_SAMPLE_RATE):round(stop*AUDIO_SAMPLE_RATE)])
                jobs.append(dict(path=path,start=cursor,end=stop));cursor=stop
        if not jobs:return []
        manifest=os.path.join(directory,'manifest.json');output=os.path.join(directory,'results.json')
        Path(manifest).write_text(json.dumps(dict(jobs=jobs)),'utf8')
        payload=_run_isolated_asr_worker([runtime,'-I',worker,'--manifest',manifest,'--output',output,'--model-dir',source],
            output,model_id=role.upper(),audio_input='shared_audio',model_path=source,entrypoint=worker_name)
        rows=payload.get('results',[])
        if not any(str(row.get('text','')).strip() for row in rows):
            raise RuntimeError(label+' 正式 worker 未返回文字，请展开原始日志查看详情。')
        return rows


# subtitle_core 通过 `from twobyteasr.asr import *` 使用本模块实现；
# 反向注册保证 legacy 端访问到的也是这里的版本，避免循环导入下的两份实现分叉。
import subtitle_core as _core
for _name in __all__:
    setattr(_core, _name, globals()[_name])
del _core, _name
