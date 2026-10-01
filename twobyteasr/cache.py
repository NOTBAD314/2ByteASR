"""cache stage implementation extracted from subtitle_core."""

# 显式导入本模块使用的 stdlib，不依赖 ``from subtitle_core import *`` 泄漏。
# （subtitle_core 删除任何"看似无用"的导入都会让隐式依赖在运行期 NameError。）
import hashlib
import json
import io
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
import time
import uuid
from contextlib import contextmanager

# The core owns runtime configuration; these imports preserve the existing public contract.
from subtitle_core import *  # noqa: F401,F403
from twobyteasr import reporting as task_reporting
from twobyteasr.processes import popen_hidden_subprocess, run_hidden_subprocess
from twobyteasr.runtime import get_runtime_context

_EVENT_LOG_LOCK = threading.Lock()
_EVENT_OBSERVER_LOCK = threading.RLock()
_EVENT_OBSERVERS = []

__all__ = [
    'stable_digest',
    'file_digest',
    '_redact_runtime_secrets',
    'redact_runtime_secrets',
    'begin_run_event_log',
    'record_run_event',
    'add_run_event_observer',
    'remove_run_event_observer',
    'run_event_observer',
    'media_cache_context',
    'decode_audio_to_array',
    'load_shared_audio',
    'cache_stage_signature',
    'atomic_write_json',
    'run_cached_stage',
    'api_stage_force_refresh',
    'run_cached_api_batch',
    'cached_stage_is_valid',
    'store_cached_stage_value',
    'cleanup_old_cache',
]

def stable_digest(value):
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_digest(path):
    try:
        with open(path, "rb") as file:
            return hashlib.sha256(file.read()).hexdigest()
    except OSError:
        return ""


def redact_runtime_secrets(value):
    text = str(value)
    runtime_keys = []
    for resolver in (polish_llm_settings, group_llm_settings):
        try:
            runtime_keys.append(resolver().get("api_key", ""))
        except Exception:
            pass
    for secret in (DASHSCOPE_API_KEY, HF_TOKEN, *runtime_keys):
        if secret:
            text = text.replace(secret, "<redacted>")
    return text


# 兼容旧调用；跨模块代码必须使用上面的公开名称，避免 ``import *``
# 按 Python 规则过滤下划线名称后在异常回退路径触发 NameError。
_redact_runtime_secrets = redact_runtime_secrets


def _redact_runtime_payload(value):
    """Redact secrets without flattening lists and dictionaries used by reports."""
    if isinstance(value, dict):
        return {
            str(key): _redact_runtime_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_runtime_payload(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_runtime_secrets(value)


def begin_run_event_log():
    """为本次队列建立内部 JSONL 日志，不在素材目录生成辅助文件。"""
    global RUN_EVENT_LOG_PATH
    runtime_context = get_runtime_context()
    log_root = RUN_LOG_ROOT
    try:
        os.makedirs(log_root, exist_ok=True)
    except OSError:
        log_root = os.path.join(tempfile.gettempdir(), "2ByteASR", "logs")
        try:
            os.makedirs(log_root, exist_ok=True)
        except OSError:
            RUN_EVENT_LOG_PATH = ""
            runtime_context.event_log_path = ""
            return "日志目录不可写，已继续运行（不影响字幕输出）"
    _prune_run_event_logs(log_root)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    RUN_EVENT_LOG_PATH = os.path.join(
        log_root,
        f"auto_asr_{stamp}_{os.getpid()}_{uuid.uuid4().hex[:6]}.jsonl",
    )
    runtime_context.event_log_path = RUN_EVENT_LOG_PATH
    record_run_event(
        "run_started",
        pid=os.getpid(),
        pipeline_build=PIPELINE_BUILD_ID,
        core_path=os.path.realpath(__file__),
        startup_self_test=STARTUP_SELF_TEST_ID,
    )
    return RUN_EVENT_LOG_PATH


def _prune_run_event_logs(log_root, *, max_age_days=30, max_files=100):
    """Bound retention of redacted diagnostics that can still contain local paths."""
    try:
        root = os.path.realpath(log_root)
        entries = []
        for name in os.listdir(root):
            if not (name.startswith("auto_asr_") and name.endswith(".jsonl")):
                continue
            path = os.path.realpath(os.path.join(root, name))
            if os.path.commonpath((root, path)) != root or not os.path.isfile(path):
                continue
            entries.append((os.path.getmtime(path), path))
        entries.sort(reverse=True)
        cutoff = time.time() - max(1, int(max_age_days)) * 86400
        for index, (modified, path) in enumerate(entries):
            if modified < cutoff or index >= max(1, int(max_files)):
                try:
                    os.unlink(path)
                except OSError:
                    pass
    except (OSError, ValueError):
        pass


def add_run_event_observer(callback):
    """Subscribe to redacted structured runtime events."""
    if not callable(callback):
        raise TypeError("event observer must be callable")
    with _EVENT_OBSERVER_LOCK:
        if callback not in _EVENT_OBSERVERS:
            _EVENT_OBSERVERS.append(callback)
    return callback


def remove_run_event_observer(callback):
    with _EVENT_OBSERVER_LOCK:
        if callback in _EVENT_OBSERVERS:
            _EVENT_OBSERVERS.remove(callback)


@contextmanager
def run_event_observer(callback):
    add_run_event_observer(callback)
    try:
        yield callback
    finally:
        remove_run_event_observer(callback)


def record_run_event(event, **payload):
    safe_payload = {
        key: _redact_runtime_payload(value)
        for key, value in payload.items()
    }
    task_reporting.record_media_event(event, **safe_payload)
    with _EVENT_OBSERVER_LOCK:
        observers = tuple(_EVENT_OBSERVERS)
    for observer in observers:
        try:
            observer(str(event), dict(safe_payload))
        except Exception:
            # Observability must never break subtitle generation.
            pass
    event_log_path = get_runtime_context().event_log_path or RUN_EVENT_LOG_PATH
    if not event_log_path:
        return
    row = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "event": str(event),
        **safe_payload,
    }
    try:
        with _EVENT_LOG_LOCK:
            with open(event_log_path, "a", encoding="utf-8") as file:
                file.write(redact_runtime_secrets(json.dumps(row, ensure_ascii=False)) + "\n")
    except OSError:
        pass


def media_cache_context(media_path):
    stat = os.stat(media_path)
    identity = {
        "path": os.path.normcase(os.path.abspath(media_path)),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }
    cache_key = stable_digest(identity)[:24]
    cache_dir = os.path.join(CACHE_ROOT, cache_key)
    os.makedirs(cache_dir, exist_ok=True)
    return {"identity": identity, "cache_dir": cache_dir}


# ffmpeg 解码 watchdog（P1-6）：duration-aware absolute 上限。
# ffmpeg 以 -v error 运行，正常解码期间 stderr 无任何进度输出，无法用
# inactivity 检测；改用媒体时长推导上限（2x 实时余量 + 启动余量），
# 正常长素材（解码通常远快于 2x 实时）不会被误杀，异常卡死有界。
MIN_DECODE_TIMEOUT_SECONDS = 120.0
DECODE_TIMEOUT_REALTIME_FACTOR = 0.5
DECODE_TIMEOUT_STARTUP_MARGIN_SECONDS = 60.0
# 时长探测失败（ffprobe 不可用/解析失败）时的极宽松最终上限：仅防无限挂起。
FALLBACK_DECODE_TIMEOUT_SECONDS = 6 * 3600.0
DECODE_CANCEL_POLL_SECONDS = 0.1


def _probe_media_duration(media_path):
    """用 ffprobe 获取媒体时长（秒）；失败返回 None。"""
    probe = shutil.which("ffprobe")
    if not probe:
        return None
    try:
        completed = run_hidden_subprocess(
            [
                probe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                os.fspath(media_path),
            ],
            purpose="ffprobe shared audio duration",
            runner=subprocess.run,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
        )
        value = float(completed.stdout.strip())
        return value if value > 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _decode_stall_limit(duration_seconds):
    """duration-aware 解码上限；时长不可用时回退极宽松最终上限。"""
    if not duration_seconds or duration_seconds <= 0:
        return FALLBACK_DECODE_TIMEOUT_SECONDS
    return max(
        MIN_DECODE_TIMEOUT_SECONDS,
        duration_seconds * DECODE_TIMEOUT_REALTIME_FACTOR
        + DECODE_TIMEOUT_STARTUP_MARGIN_SECONDS,
    )


def decode_audio_to_array(media_path, cancellation_token=None, _stall_limit=None):
    """用 ffmpeg 解码为统一 16k 单声道 float32。

    - 用户取消：终止 ffmpeg 进程树后抛项目统一 ``CancelledError``；
    - 异常卡死（duration-aware stall limit）：终止进程树后抛明确
      ``RuntimeError``；
    - ``cancellation_token`` 为 None 表示调用者主动选择不可取消。
    """
    import numpy as np

    from twobyteasr.processes import stop_process_tree
    from twobyteasr.service import CancelledError

    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        os.fspath(media_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(AUDIO_SAMPLE_RATE),
        "-f",
        "f32le",
        "pipe:1",
    ]
    stall_limit = (
        _stall_limit
        if _stall_limit is not None
        else _decode_stall_limit(_probe_media_duration(media_path))
    )
    process = popen_hidden_subprocess(
        command,
        purpose="ffmpeg shared audio decode",
        process_factory=subprocess.Popen,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    started = time.monotonic()
    # communicate(timeout) 轮询循环：每次调用都会 drain 已到达的
    # stdout/stderr（PCM 可能数 GB），不会产生 PIPE deadlock；
    # TimeoutExpired 只是"尚未结束"，可再次调用继续读取。
    while True:
        try:
            stdout, stderr = process.communicate(timeout=DECODE_CANCEL_POLL_SECONDS)
            break
        except subprocess.TimeoutExpired as exc:
            if cancellation_token is not None and cancellation_token.is_cancelled:
                stop_process_tree(process)
                raise CancelledError("任务已取消。") from None
            if time.monotonic() - started > stall_limit:
                detail = (
                    (exc.stderr or b"").decode("utf-8", errors="replace")[-1200:]
                )
                stop_process_tree(process)
                raise RuntimeError(
                    f"音频解码长时间无响应（超过 {stall_limit:.0f} 秒），"
                    f"ffmpeg 已被终止：{os.path.basename(os.fspath(media_path))}。"
                    f"{detail}"
                ) from None
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace")[-1200:]
        raise RuntimeError(f"ffmpeg 音频解码失败：{detail}")
    audio = np.frombuffer(stdout, dtype="<f4").astype(np.float32, copy=True)
    if audio.ndim != 1 or audio.size == 0:
        raise RuntimeError("统一音频解码没有得到有效的单声道采样。")
    return audio


def load_shared_audio(media_path, cache_context):
    """读取隐藏的 float32 PCM 缓存；缓存损坏时自动重新解码。"""
    import numpy as np

    audio_path = os.path.join(cache_context["cache_dir"], "audio_16k.npy")
    meta_path = os.path.join(cache_context["cache_dir"], "audio_meta.json")
    signature = cache_stage_signature("audio")
    cache_reject_reason = "missing_artifact"
    try:
        with open(meta_path, "r", encoding="utf-8") as file:
            meta = json.load(file)
        if (
            meta.get("schema") == CACHE_SCHEMA_VERSION
            and meta.get("identity") == cache_context["identity"]
            and meta.get("signature") == signature
            and int(meta.get("sample_rate", 0)) == AUDIO_SAMPLE_RATE
            and os.path.isfile(audio_path)
        ):
            audio = np.load(audio_path, mmap_mode="r")
            if audio.ndim == 1 and audio.size == int(meta.get("samples", -1)):
                print(
                    f"   [缓存命中] 统一音频，{audio.size / AUDIO_SAMPLE_RATE:.2f} 秒。"
                )
                try:
                    os.utime(cache_context["cache_dir"], None)
                except OSError:
                    pass
                record_run_event("cache_hit", stage="audio", path=audio_path)
                record_run_event("CACHE_ACCEPTED", stage="audio", path=audio_path, reason="fingerprint_match,model_hash_match,upstream_hash_match,schema_match")
                return audio
    except (OSError, ValueError, TypeError):
        cache_reject_reason = "invalid_artifact"
    record_run_event("CACHE_REJECTED", stage="audio", path=audio_path, reason=cache_reject_reason)

    decoded = decode_audio_to_array(
        media_path,
        cancellation_token=get_runtime_context().cancellation_token,
    )
    temp_audio_path = audio_path + ".tmp"
    try:
        buffer = io.BytesIO()
        np.save(buffer, decoded, allow_pickle=False)
        Path(temp_audio_path).write_bytes(buffer.getvalue())
        os.replace(temp_audio_path, audio_path)
        atomic_write_json(
            meta_path,
            {
                "schema": CACHE_SCHEMA_VERSION,
                "created_at": time.time(),
                "identity": cache_context["identity"],
                "signature": signature,
                "sample_rate": AUDIO_SAMPLE_RATE,
                "samples": int(decoded.size),
                "dependency_hash": stable_digest(cache_context["identity"]),
            },
        )
    finally:
        if os.path.exists(temp_audio_path):
            try:
                os.remove(temp_audio_path)
            except OSError:
                pass
    duration = decoded.size / AUDIO_SAMPLE_RATE
    del decoded
    audio = np.load(audio_path, mmap_mode="r")
    record_run_event("cache_write", stage="audio", path=audio_path)
    print(f"   [缓存写入] 统一音频，{duration:.2f} 秒。")
    return audio


def cache_stage_signature(stage, extra=None, provider_snapshot=None):
    runtime_context = get_runtime_context()
    version = CACHE_STAGE_VERSIONS.get(stage)
    if version is None and str(stage).startswith("primary_"):
        version = CACHE_STAGE_VERSIONS["primary_backend"]
    if version is None:
        raise ValueError(f"未登记缓存阶段：{stage}")
    base = {
        "schema": CACHE_SCHEMA_VERSION,
        "stage": stage,
        "version": version,
    }
    if stage == "audio":
        base.update({"sample_rate": AUDIO_SAMPLE_RATE, "format": "float32-mono"})
    elif stage == "qwen":
        base.update(
            {
                "model": QWEN_ASR_MODEL,
                "chunk": QWEN_ASR_CHUNK_SECONDS,
                "pad": QWEN_ASR_AUDIO_PAD_SECONDS,
                "batch_size": QWEN_ASR_BATCH_SIZE,
                "domain": CONTENT_DOMAIN_HINT,
                # 开关必须进签名：否则关闭开关后旧缓存仍会被命中并复用 Qwen 证据。
                "enabled": bool(USE_QWEN_ASR_REFERENCE),
            }
        )
    elif stage == "firered":
        base.update(
            {
                "chunk": FIRERED_CHUNK_SECONDS,
                "step": FIRERED_CHUNK_STEP_SECONDS,
                "model_mtime": (
                    os.path.getmtime(os.path.join(FIRERED_MODEL_DIR, "model.pth.tar"))
                    if os.path.isfile(os.path.join(FIRERED_MODEL_DIR, "model.pth.tar"))
                    else 0
                ),
            }
        )
    elif stage == "polished":
        from .asr_provider_snapshot import task_provider_snapshot
        snapshot = provider_snapshot or task_provider_snapshot('polish')
        endpoint = snapshot.endpoint()
        base['provider_snapshot'] = snapshot.cache_identity()
        base.update(
            {
                "provider": endpoint["provider"],
                "model": endpoint["model"],
                "base_url": endpoint["base_url"],
                "domain": CONTENT_DOMAIN_HINT,
                "glossary": file_digest(GLOSSARY_PATH),
                "game_profiles": file_digest(GAME_PROFILES_PATH),
                "game_lexicons": (
                    enabled_game_lexicon_signature()
                    if runtime_context.enable_domain_terms
                    else {}
                ),
                "logic": POLISH_LOGIC_VERSION,
                "runtime_profile": runtime_content_profile_signature(),
                "verified_terms": (
                    file_digest(GAME_PROFILES_PATH)
                    if runtime_context.enable_domain_terms
                    else ""
                ),
                "learned_terms": (
                    file_digest(LEARNED_TERMS_PATH)
                    if runtime_context.enable_domain_terms
                    else ""
                ),
            }
        )
    elif stage == "grouped_local":
        base.update(max_chars=MAX_SUBTITLE_CHARS, preferred_chars=PREFERRED_MAX_SUBTITLE_CHARS,
                    max_seconds=MAX_SUBTITLE_SECONDS, logic=GROUP_LOGIC_VERSION,
                    runtime_profile=runtime_content_profile_signature())
    elif stage == "grouped":
        from .asr_provider_snapshot import task_provider_snapshot, GROUP_CACHE_VERSION
        snapshot = provider_snapshot or task_provider_snapshot("group")
        endpoint = snapshot.endpoint()
        base.update(
            {
                "provider_snapshot": snapshot.cache_identity(),
                "cache_version": GROUP_CACHE_VERSION,
                "provider": endpoint["provider"],
                "model": endpoint["model"],
                "base_url": endpoint["base_url"],
                "max_chars": MAX_SUBTITLE_CHARS,
                "preferred_chars": PREFERRED_MAX_SUBTITLE_CHARS,
                "max_seconds": MAX_SUBTITLE_SECONDS,
                "logic": GROUP_LOGIC_VERSION,
                "runtime_profile": runtime_content_profile_signature(),
            }
        )
    elif stage == "firered_primary":
        # 主播人数直接决定哪些 MOSS 标签进入成片。必须进入缓存签名，
        # 否则同一素材先按两人运行后再改成三人仍会命中旧的两人主稿。
        base.update({"runtime_profile": runtime_content_profile_signature()})
    elif stage == "final_timing":
        from .number_fidelity import RULE_VERSION, preference
        base.update({"logic": TIMING_LOGIC_VERSION, 'fidelity_rules': RULE_VERSION,
                     'prefer_arabic_numbers': preference(), 'cohesion_rules': 2})
    elif stage == "firered_llm":
        base.update({"logic": file_digest(__file__)})
    if extra is not None:
        base["dependency"] = stable_digest(extra)
    return stable_digest(base)


def atomic_write_json(path, payload):
    temp_path = path + ".tmp"
    try:
        Path(temp_path).write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _stage_cache_path(stage, cache_context, signature):
    # Legacy grouped.json is retained verbatim. New identities never replace it.
    name = f"grouped-snapshot-{signature}.json" if stage == "grouped" else f"{stage}.json"
    return os.path.join(cache_context["cache_dir"], name)


def _grouped_stage_text_valid(value, extra_signature):
    source = extra_signature.get("segments") if isinstance(extra_signature, dict) else None
    if source is None:
        return False
    expected, actual = {}, {}
    for row in source:
        expected.setdefault(row.get("speaker") or "S00", []).append(row["text"])
    for cue in value:
        actual.setdefault(cue.speaker or "S00", []).append(cue.text)
    return {k: "".join(v) for k,v in expected.items()} == {k: "".join(v) for k,v in actual.items()}


def run_cached_stage(
    stage,
    cache_context,
    runner,
    encoder=lambda value: value,
    decoder=lambda value: value,
    extra_signature=None,
    should_cache=lambda value: True,
):
    owner=get_runtime_context()
    def require_current():
        if get_runtime_context() is not owner or bool(getattr(owner.cancellation_token,'is_cancelled',False)):
            from .service import CancelledError
            raise CancelledError('阶段缓存任务已取消，拒绝迟到结果。')
    require_current()
    signature = cache_stage_signature(stage, extra_signature)
    cache_path = _stage_cache_path(stage, cache_context, signature)
    dependency_hash = stable_digest(extra_signature) if extra_signature is not None else ""
    rejected_reason = "missing_artifact"
    try:
        with open(cache_path, "r", encoding="utf-8") as file:
            payload = json.load(file)
        reasons = []
        if payload.get("schema") != CACHE_SCHEMA_VERSION:
            reasons.append("schema_mismatch")
        if payload.get("identity") != cache_context["identity"]:
            reasons.append("fingerprint_mismatch")
        if payload.get("signature") != signature:
            reasons.append("model_hash_or_settings_mismatch")
        if dependency_hash and payload.get("dependency_hash") != dependency_hash:
            reasons.append("upstream_hash_mismatch" if payload.get("dependency_hash") else "missing_dependency")
        if api_stage_force_refresh(stage):
            reasons.append("force_refresh")
        if stage == "grouped" and (payload.get("producer") != "ai" or payload.get("validation") != "exact_text_and_boundaries"):
            reasons.append("legacy_or_unvalidated_grouped")
        if stage == "grouped" and not reasons and not _grouped_stage_text_valid(decoder(payload.get("data")), extra_signature):
            reasons.append("text_mismatch")
        if not reasons:
            require_current()
            if stage=='polished':
                owner.terminology_status=dict(payload.get('terminology_status') or {})
                owner.polishing_summary=dict(payload.get('polishing_summary') or {})
                if owner.terminology_status:
                    owner.terminology_status['cached']=True
                    record_run_event('domain_term_verification_summary',**owner.terminology_status)
                if owner.polishing_summary:
                    owner.polishing_summary['cached']=True
                    record_run_event('polishing_summary',**owner.polishing_summary)
            extend_review_items(payload.get("review_items", []))
            try:
                os.utime(cache_context["cache_dir"], None)
            except OSError:
                pass
            print(f"   [缓存命中] {stage}，跳过重复计算。")
            record_run_event("CACHE_ACCEPTED", stage=stage, path=cache_path, reason="fingerprint_match,model_hash_match,upstream_hash_match,schema_match")
            record_run_event("cache_hit", stage=stage, path=cache_path)
            return decoder(payload.get("data"))
        rejected_reason = ",".join(reasons) or rejected_reason
        record_run_event("CACHE_REJECTED", stage=stage, path=cache_path, reason=rejected_reason)
    except (OSError, ValueError, TypeError):
        record_run_event("CACHE_REJECTED", stage=stage, path=cache_path, reason=rejected_reason)

    with capture_review_items() as stage_review_items:
        value = runner()
    require_current()
    extend_review_items(stage_review_items)
    used_fallback = any(
        item.get("category") in ("漏句回退", "校对回退", "断句回退")
        for item in stage_review_items
    )
    if stage=='polished' and (getattr(owner,'terminology_status',{}) or {}).get('status') in {'failed','partial'}:
        used_fallback=True
    verified_group = stage != "grouped" or (
        getattr(value, "origin", None) == "ai" and getattr(value, "validated", False)
        and _grouped_stage_text_valid(value, extra_signature))
    if should_cache(value) and not used_fallback and verified_group:
        atomic_write_json(
            cache_path,
            {
                "schema": CACHE_SCHEMA_VERSION,
                "created_at": time.time(),
                "identity": cache_context["identity"],
                "signature": signature,
                "dependency_hash": dependency_hash,
                **({"producer": "ai", "validation": "exact_text_and_boundaries"} if stage == "grouped" else {}),
                "model_identity": (extra_signature.get("model_identity") if isinstance(extra_signature, dict) else ""),
                "runtime_version": (extra_signature.get("runtime_version") if isinstance(extra_signature, dict) else "") or PIPELINE_BUILD_ID,
                "upstream_artifact_hashes": (extra_signature.get("upstream_artifact_hashes") if isinstance(extra_signature, dict) else {}),
                "review_items": stage_review_items,
                **({'terminology_status':getattr(owner,'terminology_status',{}),
                    'polishing_summary':getattr(owner,'polishing_summary',{})} if stage=='polished' else {}),
                "data": encoder(value),
            },
        )
        print(f"   [缓存写入] {stage}")
        record_run_event("cache_write", stage=stage, path=cache_path)
    elif used_fallback:
        print(f"   [缓存跳过] {stage} 使用了回退结果，下次仍会重试。")
        record_run_event("cache_skip_fallback", stage=stage)
    return value


def api_stage_force_refresh(stage):
    runtime_context = get_runtime_context()
    if stage == "polished":
        return bool(
            runtime_context.force_refresh_api_cache
            or runtime_context.force_refresh_polish_cache
        )
    if stage == "grouped":
        return bool(
            runtime_context.force_refresh_api_cache
            or runtime_context.force_refresh_group_cache
        )
    return False


def run_cached_api_batch(
    stage,
    cache_context,
    dependency,
    runner,
    encoder=lambda value: value,
    decoder=lambda value: value,
    fallback_categories=(),
    provider_snapshot=None,
    validator=None,
    diagnostics=None,
):
    """逐批保存成功的 DashScope 结果；单批失败不会拖累其余批次缓存。"""
    owner = get_runtime_context()
    def require_current():
        if get_runtime_context() is not owner or bool(getattr(owner.cancellation_token,'is_cancelled',False)):
            from .service import CancelledError
            raise CancelledError('已取消或被替换的任务不能读取/写入本次校对结果。')
    require_current()
    if stage not in ("polished", "grouped", "grouped_local"):
        raise ValueError(f"不支持的 API 逐批缓存阶段：{stage}")
    from .asr_provider_snapshot import GroupedBatchResult, GROUP_CACHE_VERSION, task_provider_snapshot
    strict_group = stage == "grouped"
    if strict_group and provider_snapshot is None:
        provider_snapshot = task_provider_snapshot("group")
    signature = cache_stage_signature(stage, provider_snapshot=provider_snapshot)
    batch_key = stable_digest(
        {
            "identity": cache_context["identity"],
            "stage_signature": signature,
            "dependency": dependency,
        }
    )
    batch_dir = os.path.join(cache_context["cache_dir"], "api_batches", stage)
    cache_path = os.path.join(batch_dir, f"{batch_key}.json")
    if diagnostics is not None:
        diagnostics.update(cache_key=batch_key, cache_version=GROUP_CACHE_VERSION, cache_hit=False)
    if not api_stage_force_refresh(stage):
        try:
            with open(cache_path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            if (
                payload.get("schema") == CACHE_SCHEMA_VERSION
                and payload.get("identity") == cache_context["identity"]
                and payload.get("signature") == signature
                and payload.get("dependency_hash") == stable_digest(dependency)
                and (not strict_group or (
                    payload.get("provider_fingerprint") == provider_snapshot.fingerprint
                    and payload.get("producer") == "ai"
                    and payload.get("validation") == "exact_text_and_boundaries"
                ))
            ):
                decoded = decoder(payload.get("data"))
                if strict_group and (validator is None or not validator(decoded)):
                    raise ValueError("Cached grouped text no longer matches immutable input")
                extend_review_items(payload.get("review_items", []))
                print(f"      [逐批缓存命中] {stage}")
                record_run_event("CACHE_ACCEPTED", stage=f"{stage}_batch", path=cache_path, reason="fingerprint_match,model_hash_match,upstream_hash_match,schema_match")
                record_run_event("cache_hit", stage=f"{stage}_batch", path=cache_path)
                if diagnostics is not None:
                    diagnostics["cache_hit"] = True
                return GroupedBatchResult(decoded, validated=True, cache_hit=True) if strict_group else decoded
            record_run_event("CACHE_REJECTED", stage=f"{stage}_batch", path=cache_path, reason="signature_or_dependency_mismatch")
        except (OSError, ValueError, TypeError):
            record_run_event("CACHE_REJECTED", stage=f"{stage}_batch", path=cache_path, reason="missing_artifact")

    with capture_review_items() as batch_review_items:
        value = runner()
    require_current()
    extend_review_items(batch_review_items)
    used_fallback = any(
        item.get("category") in set(fallback_categories)
        for item in batch_review_items
    )
    validated_ai = not strict_group or (
        getattr(value, "origin", None) == "ai" and getattr(value, "validated", False)
        and validator is not None and validator(value)
    )
    if not used_fallback and validated_ai:
        require_current()
        os.makedirs(batch_dir, exist_ok=True)
        atomic_write_json(
            cache_path,
            {
                "schema": CACHE_SCHEMA_VERSION,
                "created_at": time.time(),
                "identity": cache_context["identity"],
                "signature": signature,
                "dependency_hash": stable_digest(dependency),
                **({"provider_fingerprint": provider_snapshot.fingerprint,
                    "cache_version": GROUP_CACHE_VERSION, "producer": "ai",
                    "validation": "exact_text_and_boundaries"} if strict_group else {}),
                "review_items": batch_review_items,
                "data": encoder(value),
            },
        )
        print(f"      [逐批缓存写入] {stage}")
        record_run_event("cache_write", stage=f"{stage}_batch", path=cache_path)
    else:
        print(f"      [逐批缓存跳过] {stage} 当前批次使用回退。")
        record_run_event("cache_skip_fallback", stage=f"{stage}_batch", cache_key=batch_key,
                         result_origin=getattr(value, "origin", "unvalidated"))
    return value


def cached_stage_is_valid(stage, cache_context, extra_signature=None):
    """只检查缓存签名，供批量模型预热跳过已完成文件。"""
    signature = cache_stage_signature(stage, extra_signature)
    dependency_hash = stable_digest(extra_signature) if extra_signature is not None else ""
    cache_path = _stage_cache_path(stage, cache_context, signature)
    try:
        with open(cache_path, "r", encoding="utf-8") as file:
            payload = json.load(file)
        valid = (
            payload.get("schema") == CACHE_SCHEMA_VERSION
            and payload.get("identity") == cache_context["identity"]
            and payload.get("signature") == signature
            and (not dependency_hash or payload.get("dependency_hash") == dependency_hash)
        )
        record_run_event(
            "CACHE_ACCEPTED" if valid else "CACHE_REJECTED",
            stage=stage,
            path=cache_path,
            reason="fingerprint_match,model_hash_match,upstream_hash_match,schema_match" if valid else "signature_or_dependency_mismatch",
        )
        return valid
    except (OSError, ValueError, TypeError):
        record_run_event("CACHE_REJECTED", stage=stage, path=cache_path, reason="missing_artifact")
        return False


def store_cached_stage_value(
    stage,
    cache_context,
    value,
    encoder=lambda value: value,
    extra_signature=None,
):
    """写入已经由批量常驻模型算出的阶段结果。"""
    cache_path = os.path.join(cache_context["cache_dir"], f"{stage}.json")
    atomic_write_json(
        cache_path,
        {
            "schema": CACHE_SCHEMA_VERSION,
            "created_at": time.time(),
            "identity": cache_context["identity"],
            "signature": cache_stage_signature(stage, extra_signature),
            "dependency_hash": stable_digest(extra_signature) if extra_signature is not None else "",
            "model_identity": (extra_signature.get("model_identity") if isinstance(extra_signature, dict) else ""),
            "runtime_version": (extra_signature.get("runtime_version") if isinstance(extra_signature, dict) else "") or PIPELINE_BUILD_ID,
            "upstream_artifact_hashes": (extra_signature.get("upstream_artifact_hashes") if isinstance(extra_signature, dict) else {}),
            "review_items": [],
            "data": encoder(value),
        },
    )
    record_run_event("cache_write", stage=stage, path=cache_path, source="batch")


def cleanup_old_cache():
    if not os.path.isdir(CACHE_ROOT):
        return
    root = os.path.realpath(CACHE_ROOT)
    cutoff = time.time() - CACHE_MAX_AGE_DAYS * 86400
    removed = 0
    retired_files = 0
    retired_names = ("faster.json", "vad.json", "commentary.json", "forced_align.json")
    for name in os.listdir(root):
        candidate = os.path.realpath(os.path.join(root, name))
        try:
            if (
                os.path.commonpath((root, candidate)) != root
                or candidate == root
                or os.path.islink(candidate)
                or not os.path.isdir(candidate)
            ):
                continue
            for retired_name in retired_names:
                retired_path = os.path.realpath(os.path.join(candidate, retired_name))
                if (
                    os.path.commonpath((candidate, retired_path)) == candidate
                    and os.path.isfile(retired_path)
                    and not os.path.islink(retired_path)
                ):
                    os.remove(retired_path)
                    retired_files += 1
            if os.path.getmtime(candidate) >= cutoff:
                continue
            shutil.rmtree(candidate)
            removed += 1
        except OSError:
            continue
    if removed:
        print(f"   [缓存清理] 删除 {removed} 个超过 {CACHE_MAX_AGE_DAYS} 天的旧缓存。")
    if retired_files:
        print(f"   [缓存清理] 删除 {retired_files} 个已退役识别/对齐阶段缓存。")


import sys as _sys
import subtitle_core as _core
for _name in __all__:
    setattr(_core, _name, globals()[_name])
# ``twobyteasr.cache`` may be imported before the compatibility facade.  In that
# circular-import order the extracted stage modules have already executed their
# ``from subtitle_core import *`` while cache helpers were still unavailable.
# Backfill the public helpers so direct package imports behave exactly like the
# normal launcher import order.
for _module_name in (
    "twobyteasr.asr",
    "twobyteasr.correction",
    "twobyteasr.segmentation",
    "twobyteasr.timing",
    "twobyteasr.output",
):
    _module = _sys.modules.get(_module_name)
    if _module is not None:
        for _name in __all__:
            if not hasattr(_module, _name):
                setattr(_module, _name, globals()[_name])
del _core, _module, _module_name, _name, _sys
