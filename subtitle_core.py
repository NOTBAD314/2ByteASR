"""Compatibility facade and shared runtime configuration for 2ByteASR.

Stage implementations live in ``twobyteasr`` modules.  This file keeps the historical
public API used by the launcher, tests, and pipeline while configuration remains in
one place during the incremental migration.
"""

import copy
import hashlib
import ipaddress
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import uuid
import warnings
import wave
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from difflib import SequenceMatcher
from statistics import median


from twobyteasr import reporting as task_reporting
from twobyteasr.llm_config import (
    endpoint_from_settings,
    read_secret_value,
    save_api_keys,
    secrets_path,
    validate_endpoint,
)
from twobyteasr.models import SpeechSegment, SubtitleCue, WordUnit
from twobyteasr.processes import run_hidden_subprocess
from twobyteasr.runtime import get_runtime_context
from twobyteasr.settings import load_runtime_settings, save_runtime_settings


warnings.filterwarnings(
    "ignore",
    message=r"urllib3 .*doesn.*match a supported version!",
)
warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API.*",
    category=UserWarning,
)


# ==========================================
# 配置区
# ==========================================
PIPELINE_BUILD_ID = "2026.08.10-v7.18-asr-result-schema-v2"
STARTUP_SELF_TEST_ID = "startup-self-test-v6.9"
RUNTIME_SETTINGS, RUNTIME_SETTINGS_PATH, RUNTIME_SETTINGS_WARNINGS = load_runtime_settings()






PRIMARY_ASR_BACKEND = RUNTIME_SETTINGS["models"].get("primary_asr_backend", "moss")
QWEN_ASR_BACKEND = RUNTIME_SETTINGS["models"]["qwen_asr_backend"]
QWEN_ASR_MODEL = RUNTIME_SETTINGS["models"]["qwen_asr_model"]
QWEN_ASR_API_MODEL = RUNTIME_SETTINGS["models"]["qwen_asr_api_model"]
QWEN_ASR_API_URL = RUNTIME_SETTINGS["models"]["qwen_asr_api_url"]
FIRERED_ASR_BACKEND = RUNTIME_SETTINGS["models"]["firered_asr_backend"]


LLM_MODEL = RUNTIME_SETTINGS["models"]["polish_model"]
POLISH_LLM_BASE_URL_DEFAULT = RUNTIME_SETTINGS["models"]["polish_base_url"]

# 断句/断句校验可使用独立云端模型；校对仍用上面的 LLM_MODEL。
GROUP_LLM_MODEL = RUNTIME_SETTINGS["models"]["group_model"]
GROUP_LLM_BASE_URL_DEFAULT = RUNTIME_SETTINGS["models"]["group_base_url"]


AUDIO_SAMPLE_RATE = 16000


SHOW_SPEAKER_LABELS_IN_SRT = RUNTIME_SETTINGS["switches"]["show_speaker_labels_in_srt"]


from twobyteasr.runtime_paths import pipeline_script_root

SCRIPT_DIR = str(pipeline_script_root(__file__))


def _load_secret_value(*names):
    """Read a secret from process env first, then Windows DPAPI storage."""
    value, _ = read_secret_value(*names)
    return value


def require_runtime_secrets(require_dashscope=True, require_hf=False):
    missing = []
    if require_dashscope and not get_dashscope_api_key():
        missing.append("DASHSCOPE_API_KEY")
    if require_hf and not HF_TOKEN:
        missing.append("HF_TOKEN")
    if missing:
        local_secrets_path = secrets_path()
        raise RuntimeError(
            "缺少密钥："
            + ", ".join(missing)
            + "\n请任选一种方式配置后重开终端再运行：\n"
            + "1) 用户/系统环境变量 DASHSCOPE_API_KEY、HF_TOKEN\n"
            + f"2) 在程序的 AI 模型与密钥页面保存（加密文件：{local_secrets_path}）\n"
            + "PowerShell 当前会话示例：\n"
            + "  $env:DASHSCOPE_API_KEY = \"<your-dashscope-key>\"\n"
            + "  $env:HF_TOKEN = \"<your-hf-token>\""
        )


DASHSCOPE_API_KEY = _load_secret_value("DASHSCOPE_API_KEY", "2BYTEASR_DASHSCOPE_API_KEY")
HF_TOKEN = _load_secret_value("HF_TOKEN", "HUGGINGFACE_HUB_TOKEN", "2BYTEASR_HF_TOKEN")


GLOSSARY_PATH = os.path.join(SCRIPT_DIR, "glossary.txt")


GAME_PROFILES_PATH = os.path.join(SCRIPT_DIR, "game_profiles.json")


from twobyteasr.term_constants import GAME_LEXICON_MAX_PROMPT_TERMS


PROFILE_HISTORY_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", SCRIPT_DIR),
    "2ByteASR",
    "content_profiles.json",
)


LEARNED_TERMS_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", SCRIPT_DIR),
    "2ByteASR",
    "learned_game_terms.json",
)

HOST_VOICEPRINT_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", SCRIPT_DIR),
    "2ByteASR",
    "host_voiceprints",
)

HOST_VOICEPRINT_REGISTRY_PATH = os.path.join(HOST_VOICEPRINT_DIR, "registry.json")


RUN_LOG_ROOT = os.path.join(
    os.environ.get("LOCALAPPDATA", SCRIPT_DIR),
    "2ByteASR",
    "logs",
)


FIRERED_SOURCE_DIR = os.path.join(SCRIPT_DIR, "third_party", "FireRedASR2S")


def _resolve_firered_model_dir() -> str:
    try:
        from twobyteasr.runtime_paths import resolve_model_dir

        return str(resolve_model_dir("FireRedASR2-AED"))
    except Exception:
        return os.path.join(SCRIPT_DIR, "models", "FireRedASR2-AED")


FIRERED_MODEL_DIR = _resolve_firered_model_dir()


# 每次启动都默认通用模式，防止上一个游戏的词表污染下一期素材。
# 只有用户在运行时窗口里明确填写游戏并勾选术语增强，才会联网找词或套用游戏规则。
_DEFAULT_RUNTIME_CONTEXT = get_runtime_context()
_DEFAULT_RUNTIME_CONTEXT.output_review_track = bool(
    RUNTIME_SETTINGS["switches"]["output_review_track"]
)
_DEFAULT_RUNTIME_CONTEXT.force_refresh_polish_cache = bool(
    RUNTIME_SETTINGS["cache"]["force_refresh_polish"]
)
_DEFAULT_RUNTIME_CONTEXT.force_refresh_group_cache = bool(
    RUNTIME_SETTINGS["cache"]["force_refresh_group"]
)
_DEFAULT_RUNTIME_CONTEXT.dialogue_coverage_mode = str(
    RUNTIME_SETTINGS["switches"].get("dialogue_coverage_mode", "all_dialogue")
)

RUNTIME_GAME_NAME = _DEFAULT_RUNTIME_CONTEXT.game_name


RUNTIME_ENABLE_DOMAIN_TERMS = _DEFAULT_RUNTIME_CONTEXT.enable_domain_terms


RUNTIME_DISCOVERED_TERMS = _DEFAULT_RUNTIME_CONTEXT.discovered_terms


RUNTIME_OUTPUT_REVIEW_TRACK = _DEFAULT_RUNTIME_CONTEXT.output_review_track


RUNTIME_FORCE_REFRESH_API_CACHE = _DEFAULT_RUNTIME_CONTEXT.force_refresh_api_cache


# 校对和断句分别刷新，避免只想重跑其中一步时把两轮 DashScope 都作废。
RUNTIME_FORCE_REFRESH_POLISH_CACHE = _DEFAULT_RUNTIME_CONTEXT.force_refresh_polish_cache


RUNTIME_FORCE_REFRESH_GROUP_CACHE = _DEFAULT_RUNTIME_CONTEXT.force_refresh_group_cache


def _supplement_tool_path():
    """winget 等安装的 FFmpeg/ffprobe 可能不在当前进程 PATH（新装环境常见），
    把常见安装位置补充进 PATH，避免“缺少 ffmpeg/ffprobe”误报。
    便携包内置工具（tools/）也在此补齐：setup 只改安装进程的 PATH，
    从桌面启动的应用不会继承，运行前必须自愈。"""
    project_root = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "FFmpeg", "bin"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages"),
        os.path.join(os.environ.get("ProgramFiles", ""), "FFmpeg", "bin"),
        r"C:\ffmpeg\bin",
        # 便携包内置工具
        os.path.join(project_root, "tools", "ffmpeg", "bin"),
        os.path.join(project_root, "tools"),
        os.path.join(project_root, "tools", "git", "cmd"),
        os.path.join(project_root, "tools", "git", "bin"),
    ]
    extra = [c for c in candidates if c and os.path.isdir(c)]
    for base in candidates:
        if not base or not os.path.isdir(base):
            continue
        if os.path.basename(base) == "Packages":
            # winget portable 包实际解压在 WinGet\Packages\<包名>\...，递归定位 ffmpeg.exe。
            # 限制扫描深度：未安装 ffmpeg 的机器上不应遍历整棵 WinGet 目录树。
            for root, dirs, files in os.walk(base):
                if "ffmpeg.exe" in files:
                    extra.append(root)
                    dirs[:] = []
                    continue
                depth = root[len(base):].count(os.sep)
                if depth >= 3:
                    dirs[:] = []
    if extra:
        os.environ["PATH"] = os.pathsep.join(
            [*dict.fromkeys(extra), os.environ.get("PATH", "")]
        )


_supplement_tool_path()


PARALLEL_CLOUD_BATCHES = RUNTIME_SETTINGS["performance"]["parallel_cloud_batches"]


CLOUD_BATCH_WORKERS = max(1, min(8, int(RUNTIME_SETTINGS["performance"]["cloud_batch_workers"])))


PARALLEL_CPU_VAD = RUNTIME_SETTINGS["performance"]["parallel_cpu_vad"]


MOSS_PARALLEL_WORKERS = max(
    1, min(2, int(RUNTIME_SETTINGS["performance"]["moss_parallel_workers"]))
)


MOSS_PARALLEL_MIN_VRAM_GB = float(
    RUNTIME_SETTINGS["performance"]["moss_parallel_min_vram_gb"]
)


PARALLEL_GPU_ASR = RUNTIME_SETTINGS["performance"]["parallel_gpu_asr"]


PARALLEL_GPU_ASR_MIN_VRAM_GB = float(
    RUNTIME_SETTINGS["performance"]["parallel_gpu_asr_min_vram_gb"]
)


RUNTIME_EXPECTED_SPEAKERS = _DEFAULT_RUNTIME_CONTEXT.expected_speakers
RUNTIME_DIALOGUE_COVERAGE_MODE = _DEFAULT_RUNTIME_CONTEXT.dialogue_coverage_mode


RUNTIME_CANCELLATION_TOKEN = _DEFAULT_RUNTIME_CONTEXT.cancellation_token


RUN_EVENT_LOG_PATH = _DEFAULT_RUNTIME_CONTEXT.event_log_path


BUILTIN_GAME_PROFILES = ("洛克王国：世界", "绝区零")


# 纯音频无法得知剪辑时间轴帧率，用 60 fps 作为兜底；直接选视频时自动探测。
TIMELINE_FPS = 60.0


USE_FIRERED_BOUNDARY_REFINEMENT = (
    RUNTIME_SETTINGS["switches"]["enable_firered_boundary_refinement"]
    and FIRERED_ASR_BACKEND != "off"
)


FIRERED_CHUNK_SECONDS = 38.0


FIRERED_CHUNK_STEP_SECONDS = 36.0


FIRERED_NORMAL_TOKEN_SECONDS = 0.80


FIRERED_LONG_TOKEN_TAIL_SECONDS = 0.24


FIRERED_TEXT_ALIGNMENT_PAD_SECONDS = 0.35


# FireRed 的病态长 token 只可作为邻近文字证据；有效字头已经落到 MOSS
# 段外时不能再把该 token 的尾点夹回段尾，否则会制造 0.4-2 秒假尾巴。
FIRERED_EFFECTIVE_TOKEN_OUTSIDE_TOLERANCE_SECONDS = 0.08


# Qwen3-ASR 只提供复核文字证据；主时间骨架由 FireRed-AED/FireRedVAD 负责。
USE_QWEN_ASR_REFERENCE = (
    RUNTIME_SETTINGS["switches"]["enable_qwen_asr_reference"]
    and QWEN_ASR_BACKEND != "off"
)


QWEN_ASR_CHUNK_SECONDS = 25.0


# 三十六轮：API 主力转写的切块上限。MAI-Transcribe-2 等转写 API 的
# segment 粒度是"大停顿"级（连续语流整段共享一个时间戳），块越短，
# 无字级时间戳时匀速兜底的误差上界越小；短上下文也显著改善数字串烧
# 等文本质量（"120130140" 用户实录）。本地模型保持 25s 不变。
QWEN_ASR_API_CHUNK_SECONDS = 10.0


QWEN_ASR_AUDIO_PAD_SECONDS = 0.20


QWEN_ASR_BATCH_SIZE = max(
    1, min(12, int(RUNTIME_SETTINGS["performance"]["qwen_asr_batch_size"]))
)


QWEN_ASR_MAX_NEW_TOKENS = 160


QWEN_ASR_TEXT_ALIGNMENT_PAD_SECONDS = 0.50


QWEN_ASR_ALTERNATE_MIN_SIMILARITY = 0.38


# 这是内容类型提示，不是热词表，也不会触发本地强制替换。
CONTENT_DOMAIN_HINT = (
    "中文二次元游戏/二游实况与展会视频，可能出现游戏名、角色名、技能、机制、"
    "地图、厂商、展台以及玩家口头梗。陌生词可能是专名，不要擅自普通词化。"
)


# 成片固定规则：前者必须从最终字幕删除；后者统一为剪辑者确认过的真实写法。
SUBTITLE_SUPPRESSED_PHRASES = (
    "我操", "卧槽", "我艹", "卧艹", "我草", "卧草", "窝草", "沃草", "握草",
)





def get_dashscope_api_key():
    """Always resolve the latest key (environment wins over DPAPI storage)."""
    return _load_secret_value(
        "DASHSCOPE_API_KEY",
        "2BYTEASR_DASHSCOPE_API_KEY",
        "GROUP_LLM_API_KEY",
    )


def polish_llm_settings():
    """Return the current OpenAI-compatible endpoint used by subtitle correction."""
    snapshot = get_runtime_context().provider_snapshot
    if snapshot is not None:
        return snapshot.endpoint()
    return endpoint_from_settings(RUNTIME_SETTINGS, "polish")


def describe_secret_source(value_name="DASHSCOPE_API_KEY"):
    """Return a safe debug string describing which source provided the API key.

    只返回来源描述，绝不返回密钥本身；需要明文请直接读环境变量或
    ``read_secret_value``（调用方负责掩码）。
    """
    for name in ("DASHSCOPE_API_KEY", "2BYTEASR_DASHSCOPE_API_KEY", "GROUP_LLM_API_KEY"):
        raw = str(os.environ.get(name, "") or "").strip()
        if raw:
            return f"env:{name}"
    names = ("DASHSCOPE_API_KEY", "2BYTEASR_DASHSCOPE_API_KEY", "GROUP_LLM_API_KEY")
    raw, source = read_secret_value(*names)
    if raw:
        name = source.rsplit("/", 1)[-1].strip()
        return f"dpapi:{name}"
    return "missing"


def mask_api_key(key):
    key = str(key or "")
    if not key:
        return "<empty>"
    if len(key) <= 12:
        return key[:3] + "..."
    return f"{key[:8]}...{key[-4:]} (len={len(key)})"


def group_llm_settings():
    """Return the current OpenAI-compatible endpoint used by full-text grouping."""
    snapshot = get_runtime_context().provider_snapshot
    if snapshot is not None:
        return snapshot.endpoint()
    return endpoint_from_settings(RUNTIME_SETTINGS, "group")


def adopt_profile_runtime_settings(settings, warnings=()):
    """Publish an already persisted complete profile to legacy task globals."""
    global RUNTIME_SETTINGS, RUNTIME_SETTINGS_WARNINGS
    RUNTIME_SETTINGS = settings
    RUNTIME_SETTINGS_WARNINGS = list(warnings)
    names = {
        'PRIMARY_ASR_BACKEND': 'primary_asr_backend', 'QWEN_ASR_BACKEND': 'qwen_asr_backend',
        'QWEN_ASR_MODEL': 'qwen_asr_model', 'QWEN_ASR_API_MODEL': 'qwen_asr_api_model',
        'QWEN_ASR_API_URL': 'qwen_asr_api_url', 'FIRERED_ASR_BACKEND': 'firered_asr_backend',
        'LLM_MODEL': 'polish_model', 'POLISH_LLM_BASE_URL_DEFAULT': 'polish_base_url',
        'GROUP_LLM_MODEL': 'group_model', 'GROUP_LLM_BASE_URL_DEFAULT': 'group_base_url',
    }
    for name, key in names.items():
        globals()[name] = settings['models'][key]
    globals()['USE_QWEN_ASR_REFERENCE'] = settings['models']['qwen_asr_backend'] != 'off'
    globals()['USE_FIRERED_BOUNDARY_REFINEMENT'] = settings['models']['firered_asr_backend'] != 'off'


def configure_runtime_llms(
    models,
    *,
    polish_key="",
    group_key="",
    share_key=False,
    unified_glm_processing=None,
    use_ai_grouping=None,
    enable_ai_polish=None,
    prefer_arabic_numbers=None,
):
    """Apply UI-selected model settings and persist only explicitly entered keys."""
    global RUNTIME_SETTINGS, RUNTIME_SETTINGS_WARNINGS, LLM_MODEL, POLISH_LLM_BASE_URL_DEFAULT
    global GROUP_LLM_MODEL, GROUP_LLM_BASE_URL_DEFAULT, DASHSCOPE_API_KEY

    updated = json.loads(json.dumps(RUNTIME_SETTINGS, ensure_ascii=False))
    for key in (
        "polish_transport",
        "polish_protocol",
        "polish_provider",
        "polish_model",
        "polish_base_url",
        "group_transport",
        "group_protocol",
        "group_provider",
        "group_model",
        "group_base_url",
        "ai_service",
    ):
        value = str(models.get(key, "") or "").strip()
        if value:
            updated["models"][key] = value
    profiles = models.get("provider_profiles")
    if isinstance(profiles, dict) and profiles:
        updated["models"]["provider_profiles"] = json.loads(
            json.dumps(profiles, ensure_ascii=False)
        )
    if unified_glm_processing is not None:
        updated["switches"]["unified_glm_processing"] = bool(
            unified_glm_processing
        )
    if use_ai_grouping is not None:
        updated["switches"]["use_ai_grouping"] = bool(use_ai_grouping)
    if enable_ai_polish is not None:
        updated["switches"]["enable_ai_polish"] = bool(enable_ai_polish)
    if prefer_arabic_numbers is not None:
        updated['switches']['prefer_arabic_numbers'] = bool(prefer_arabic_numbers)
    # 显式 project_root 只用于源码树；打包模式下让 settings 层自己解析稳定
    # 配置根（%LOCALAPPDATA%\2ByteASR），避免每次构建重置用户 Provider 配置。
    RUNTIME_SETTINGS, _, warnings = save_runtime_settings(updated)
    RUNTIME_SETTINGS_WARNINGS = list(warnings)
    if polish_key or group_key:
        save_api_keys(
            polish_key=polish_key,
            group_key=group_key,
            share_key=bool(share_key),
        )
    LLM_MODEL = RUNTIME_SETTINGS["models"]["polish_model"]
    POLISH_LLM_BASE_URL_DEFAULT = RUNTIME_SETTINGS["models"]["polish_base_url"]
    GROUP_LLM_MODEL = RUNTIME_SETTINGS["models"]["group_model"]
    GROUP_LLM_BASE_URL_DEFAULT = RUNTIME_SETTINGS["models"]["group_base_url"]
    DASHSCOPE_API_KEY = get_dashscope_api_key()
    return warnings


def configure_runtime_asr(
    models,
    *,
    qwen_asr_key="",
):
    """Persist ASR backend choices and an optional DPAPI-protected Qwen key."""
    global RUNTIME_SETTINGS, RUNTIME_SETTINGS_WARNINGS
    global PRIMARY_ASR_BACKEND, QWEN_ASR_BACKEND, QWEN_ASR_MODEL, QWEN_ASR_API_MODEL, QWEN_ASR_API_URL
    global FIRERED_ASR_BACKEND, USE_QWEN_ASR_REFERENCE, USE_FIRERED_BOUNDARY_REFINEMENT

    updated = json.loads(json.dumps(RUNTIME_SETTINGS, ensure_ascii=False))
    for key in (
        "primary_asr_backend",
        "qwen_asr_backend",
        "qwen_asr_model",
        "qwen_asr_api_provider",
        "qwen_asr_api_protocol",
        "qwen_asr_api_model",
        "qwen_asr_api_url",
        "firered_asr_backend",
        "api_transcribe_style",
        "speaker_source",
    ):
        value = str(models.get(key, "") or "").strip()
        if value:
            updated["models"][key] = value
    # 四十轮：OSS 临时中转（非密钥字段；类型口径与 settings._merge_known_settings 一致）。
    for key in ("oss_region", "oss_endpoint", "oss_bucket", "oss_prefix"):
        value = str(models.get(key, "") or "").strip()
        if value:
            updated["models"][key] = value
    if "oss_signed_url_ttl" in models:
        try:
            updated["models"]["oss_signed_url_ttl"] = min(
                604800, max(300, int(models["oss_signed_url_ttl"]))
            )
        except (TypeError, ValueError):
            pass
    if isinstance(models.get("oss_auto_delete"), bool):
        updated["models"]["oss_auto_delete"] = models["oss_auto_delete"]
    updated["switches"]["enable_qwen_asr_reference"] = (
        updated["models"]["qwen_asr_backend"] != "off"
    )
    updated["switches"]["enable_firered_boundary_refinement"] = (
        updated["models"]["firered_asr_backend"] != "off"
    )
    RUNTIME_SETTINGS, _, warnings = save_runtime_settings(updated)
    RUNTIME_SETTINGS_WARNINGS = list(warnings)
    # Legacy bucket write for qwen_asr_key is intentionally skipped.
    # Modern ASR saves use provider+base scoped DPAPI keys via save_api_key_for.
    # This enforces "key belongs to Provider/Endpoint, not a global ASR key".
    # Old installs that only have the legacy name are still read via fallback in read_api_key.
    # if qwen_asr_key:
    #     save_api_keys(qwen_asr_key=qwen_asr_key)

    PRIMARY_ASR_BACKEND = RUNTIME_SETTINGS["models"].get("primary_asr_backend", "moss")
    QWEN_ASR_BACKEND = RUNTIME_SETTINGS["models"]["qwen_asr_backend"]
    QWEN_ASR_MODEL = RUNTIME_SETTINGS["models"]["qwen_asr_model"]
    QWEN_ASR_API_MODEL = RUNTIME_SETTINGS["models"]["qwen_asr_api_model"]
    QWEN_ASR_API_URL = RUNTIME_SETTINGS["models"]["qwen_asr_api_url"]
    FIRERED_ASR_BACKEND = RUNTIME_SETTINGS["models"]["firered_asr_backend"]
    USE_QWEN_ASR_REFERENCE = QWEN_ASR_BACKEND != "off"
    USE_FIRERED_BOUNDARY_REFINEMENT = FIRERED_ASR_BACKEND != "off"
    return warnings



from twobyteasr.llm_adapter import (
    LLMRequestError,
    classify_structured_output_failure,
    extract_chat_message_text,
    get_last_llm_response_diagnostics,
    llm_provider_capabilities,
    llm_response_preview,
    post_chat_completion,
    record_structured_output_failure,
    run_llm_json_self_test,
)
def boundaries_to_segmented_text(source_text, boundary_offsets):
    text = clean_subtitle_text(source_text)
    total = display_length(text)
    ordered = sorted({int(x) for x in boundary_offsets if int(x) > 0})
    if not ordered or ordered[-1] != total:
        # repair last
        ordered = [offset for offset in ordered if 0 < offset < total] + [total]
    start = 0
    parts = []
    for offset in ordered:
        parts.append(text[start:offset])
        start = offset
    if any(part == "" for part in parts):
        raise ValueError("空分段")
    return "|".join(parts)



def validate_grouping_boundaries_with_llm(
    segment_batch,
    boundary_offsets,
    firered_tokens=(),
    provider_snapshot=None,
    batch_diagnostics=None,
):
    """第二轮云端校验：只允许移动竖线，禁止增删改任何原字。"""
    source_text = "".join(clean_subtitle_text(segment.text) for segment in segment_batch)
    total_length = display_length(source_text)
    if total_length <= 1 or len(boundary_offsets) <= 1:
        return list(boundary_offsets)

    try:
        segmented_text = boundaries_to_segmented_text(source_text, boundary_offsets)
    except Exception:
        return list(boundary_offsets)

    from twobyteasr.asr_provider_snapshot import task_provider_snapshot, request_record, classify_request_error
    snapshot = provider_snapshot or task_provider_snapshot("group")
    settings = snapshot.endpoint()
    diag = request_record(snapshot, stage="grouped_validate",
        batch_id=(batch_diagnostics or {}).get("batch_id"), speaker=segment_batch[0].speaker,
        attempt=1, cache_key=(batch_diagnostics or {}).get("cache_key", ""), input_characters=len(source_text))
    started = time.perf_counter()
    prompt = f"""你是中文口语视频字幕的断句校验器，不是润色器、不是校对器。

绝对约束：
1. 只能移动竖线“|”的位置；不能修改、增删、替换、重排 source_text 的任何字符。
2. 返回的 segmented_text 去掉全部“|”后，必须与 source_text 逐字完全一致。
3. 若竖线切开了完整词/短语（例如“估|计”“眼|皮”“接|受”“能|力”“为什|么”“商|城”“其实我的|…”“我的眼|皮”），必须把竖线挪到该结构之前或之后，使左右都是可独立听懂的口语成分。
4. pause 气口很重要；但若 pause 落在完整词或未完成成分内部，不能保留错误切开。
5. 目标中位数约 {PREFERRED_MAX_SUBTITLE_CHARS} 字，常规不超过 {MAX_SUBTITLE_CHARS} 字；完整短语可到 {COMPLETE_PHRASE_SOFT_MAX_CHARS} 字。不要为了变短而过切，也不要留下短残尾。
6. 只修明显坏切：词中切开、上条停在“的/一个/这个”且下条是短中心语（如“300万的｜启动资金啊”“进入一个｜珊瑚场啊”）、1-3 字残句。合格则原样返回；单字条并入邻句或消竖线。
7. 已合格则原样返回。
8. 只返回 JSON：{{"segmented_text":"第一条|第二条","boundaries":[8,17,{total_length}]}}。boundaries 严格递增且最后一项等于 {total_length}。"""

    request_body = {
        "source_text": source_text,
        "total_length": total_length,
        "segmented_text": segmented_text,
        "boundaries": list(boundary_offsets),
    }
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(request_body, ensure_ascii=False)},
    ]
    try:
        from twobyteasr.ai_providers import provider_for_stage
        content = provider_for_stage(snapshot.execution_settings(), "group", sender=post_chat_completion).complete(
            messages, stage="grouped_validate", operation_kind='group', max_tokens=min(4096, max(512, total_length * 2)),
            temperature=0.0, timeout=snapshot.timeout_policy.total, _timeout_policy=snapshot.timeout_policy,
            request_diagnostics=diag, enable_thinking=False, response_format={"type": "json_object"},
            cancel_check=lambda: bool(getattr(get_runtime_context().cancellation_token, "is_cancelled", False)),
        )
        diag["raw_response_length"] = len(content)
        returned = parse_qwen_object(content)
        new_segmented = returned.get("segmented_text")
        if isinstance(new_segmented, str) and new_segmented.strip():
            parts = [clean_subtitle_text(part) for part in new_segmented.split("|")]
            if (
                parts
                and all(parts)
                and content_exact("".join(parts)) == content_exact(source_text)
            ):
                rebuilt = []
                running = 0
                for part in parts:
                    running += display_length(part)
                    rebuilt.append(running)
                if rebuilt and rebuilt[-1] == total_length:
                    if rebuilt != list(boundary_offsets):
                        print(
                            f"   [断句校验/{settings['model']}] 仅移动竖线，"
                            f"边界 {len(boundary_offsets)} -> {len(rebuilt)}。"
                        )
                    return rebuilt
        new_boundaries = returned.get("boundaries")
        if isinstance(new_boundaries, list) and new_boundaries:
            normalized = [int(value) for value in new_boundaries]
            if normalized[-1] == total_length:
                # verify via local slice conservation
                try:
                    texts_from_boundary_offsets(
                        segment_batch, normalized, firered_tokens
                    )
                    return normalized
                except Exception:
                    pass
    except Exception as exc:
        print(f"   [警告] 断句校验未采纳，沿用首轮边界：{exc}")
        diag["fallback_reason"] = classify_request_error(exc)
        record_run_event("grouping_validate_skip", error=classify_request_error(exc),
                         provider_snapshot_fingerprint=snapshot.fingerprint)
        if classify_request_error(exc) == "cancelled":
            from twobyteasr.service import CancelledError
            raise CancelledError("断句任务已取消。") from exc
    finally:
        diag["total_duration_ms"] = round((time.perf_counter()-started)*1000, 3)
        diag["validator_result"] = "accepted_boundary_check" if diag["fallback_reason"] is None else "kept_first_pass"
        record_run_event("asr_provider_request", **diag)
    return list(boundary_offsets)



def runtime_game_identity(game_name):
    """忽略中英文冒号和常见分隔符，识别同一个游戏名称。"""
    cleaned = clean_subtitle_text(game_name)
    return re.sub(r"[\s:：·._/\\-]+", "", cleaned).lower()


def canonicalize_runtime_game_name(game_name):
    cleaned = clean_subtitle_text(game_name)
    identity = runtime_game_identity(cleaned)
    if identity == "洛克王国世界":
        return "洛克王国：世界"
    if identity == "绝区零":
        return "绝区零"
    return cleaned


_GAME_PROFILES_CACHE = {"mtime_ns": 0, "profiles": {}}


def load_game_profiles():
    """读取并缓存 35KB 的游戏配置；文件变化时自动失效（进程内缓存）。"""
    try:
        stat = os.stat(GAME_PROFILES_PATH)
        mtime_ns = stat.st_mtime_ns
    except OSError:
        return {}
    if _GAME_PROFILES_CACHE["mtime_ns"] == mtime_ns:
        return _GAME_PROFILES_CACHE["profiles"]
    try:
        with open(GAME_PROFILES_PATH, "r", encoding="utf-8-sig") as file:
            payload = json.load(file)
        profiles = payload.get("profiles", {})
        profiles = profiles if isinstance(profiles, dict) else {}
    except (OSError, ValueError, TypeError):
        profiles = {}
    _GAME_PROFILES_CACHE["mtime_ns"] = mtime_ns
    _GAME_PROFILES_CACHE["profiles"] = profiles
    return profiles


def active_game_profile():
    identity = runtime_game_identity(RUNTIME_GAME_NAME)
    for name, profile in load_game_profiles().items():
        if runtime_game_identity(profile.get("identity", name)) == identity:
            return profile
    return {}


def active_profile_term_items():
    items = active_game_profile().get("terms", [])
    return [item for item in items if isinstance(item, dict) and item.get("canonical")]


def active_profile_terms():
    return list(
        dict.fromkeys(
            clean_subtitle_text(item["canonical"])
            for item in active_profile_term_items()
            if clean_subtitle_text(item["canonical"])
        )
    )


def active_profile_alias_rules():
    """把专名别名分成安全全文替换和需要独立 ASR 支持的短词。"""
    rules = []
    for item in active_profile_term_items():
        target = clean_subtitle_text(item.get("canonical", ""))
        explicit_mode = str(item.get("replacement_mode", "")).strip().lower()
        for source in item.get("aliases", []):
            source = clean_subtitle_text(source)
            if not source or not target or source == target:
                continue
            if explicit_mode in ("global", "contextual"):
                mode = explicit_mode
            else:
                # 三字以上错词通常足够独特；二字日常词（落地、封印、码头等）
                # 必须得到另一套 ASR 的正确专名支持，防止 PVP 词表污染普通对话。
                mode = "global" if display_length(source) >= 3 else "contextual"
            rules.append(
                {
                    "source": source,
                    "target": target,
                    "mode": mode,
                    "category": str(item.get("category", "game_term")),
                }
            )
    return rules


def active_blocked_mapping_pairs():
    result = set()
    for item in active_game_profile().get("blocked_mappings", []):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        source = content_only(item[0])
        target = content_only(item[1])
        if source and target:
            result.add((source, target))
    return result


def _profile_lexicon_paths_for(profile):
    """只加载配置明确列出的脚本目录内词库，拒绝越界路径。"""
    paths = []
    script_root = os.path.abspath(SCRIPT_DIR)
    for relative in profile.get("lexicons", []):
        if not isinstance(relative, str) or not relative.strip():
            continue
        candidate = os.path.abspath(os.path.join(SCRIPT_DIR, relative))
        try:
            if os.path.commonpath((script_root, candidate)) != script_root:
                continue
        except ValueError:
            continue
        if os.path.isfile(candidate):
            paths.append(candidate)
    return list(dict.fromkeys(paths))


def active_profile_lexicon_paths():
    """当前内容 profile 的词库路径（浏览/单库语义）。"""
    return _profile_lexicon_paths_for(active_game_profile())


def _iter_enabled_profiles():
    """按本批启用词库顺序产出 (profile) ；找不到匹配的 id 跳过。"""
    profiles = load_game_profiles()
    for identity in runtime_enabled_glossary_ids():
        for name, profile in profiles.items():
            if runtime_game_identity(str(profile.get("identity", name))) == identity:
                yield profile
                break


def enabled_profile_lexicon_paths():
    """本批启用词库的全部词库路径（pipeline 多词库语义）。"""
    paths = []
    for profile in _iter_enabled_profiles():
        paths.extend(_profile_lexicon_paths_for(profile))
    return list(dict.fromkeys(paths))


def load_enabled_game_lexicon_names():
    """读取本批启用词库的全部本地图鉴（弱候选，不直接触发替换）。"""
    names = []
    loaded = []
    for path in enabled_profile_lexicon_paths():
        try:
            with open(path, "r", encoding="utf-8-sig") as file:
                payload = json.load(file)
            entries = payload.get("entries", [])
            current = [
                clean_subtitle_text(item.get("name", ""))
                for item in entries
                if isinstance(item, dict) and clean_subtitle_text(item.get("name", ""))
            ]
            names.extend(current)
            loaded.append(
                (
                    payload.get("category", os.path.basename(path)),
                    len(entries),
                    len(set(current)),
                )
            )
        except (OSError, ValueError, TypeError):
            continue
    return list(dict.fromkeys(names)), loaded


def load_active_game_lexicon_names(include_hidden: bool = False):
    """读取当前内容 profile 的完整本地图鉴（浏览/单库语义）。

    用户明确隐藏的参考词默认不返回（弱候选/统计都不再包含），
    术语库管理界面用 include_hidden=True 列出"已隐藏"行以便恢复。
    """
    expected_identity = runtime_game_identity(RUNTIME_GAME_NAME)
    hidden = set() if include_hidden else hidden_reference_terms_for_game(RUNTIME_GAME_NAME)
    names = []
    loaded = []
    for path in active_profile_lexicon_paths():
        try:
            with open(path, "r", encoding="utf-8-sig") as file:
                payload = json.load(file)
            if runtime_game_identity(payload.get("game", "")) != expected_identity:
                continue
            entries = payload.get("entries", [])
            current = [
                clean_subtitle_text(item.get("name", ""))
                for item in entries
                if isinstance(item, dict) and clean_subtitle_text(item.get("name", ""))
                and clean_subtitle_text(item.get("name", "")) not in hidden
            ]
            names.extend(current)
            loaded.append(
                (
                    payload.get("category", os.path.basename(path)),
                    len(entries),
                    len(set(current)),
                )
            )
        except (OSError, ValueError, TypeError):
            continue
    return list(dict.fromkeys(names)), loaded


def active_game_lexicon_signature():
    return {
        os.path.relpath(path, SCRIPT_DIR).replace("\\", "/"): file_digest(path)
        for path in active_profile_lexicon_paths()
    }


def enabled_game_lexicon_signature():
    return {
        os.path.relpath(path, SCRIPT_DIR).replace("\\", "/"): file_digest(path)
        for path in enabled_profile_lexicon_paths()
    }


def load_learned_term_payload(*, strict=False):
    try:
        with open(LEARNED_TERMS_PATH, "r", encoding="utf-8-sig") as file:
            payload = json.load(file)
        if strict and not isinstance(payload, dict):
            raise ValueError("词库文件格式无效，未写入")
        return payload if isinstance(payload, dict) else {"schema": 1, "games": {}}
    except FileNotFoundError:
        return {"schema": 1, "games": {}}
    except (OSError, ValueError, TypeError):
        if strict:
            raise
        return {"schema": 1, "games": {}}


TERM_PROVENANCE_BUILTIN = "builtin"
TERM_PROVENANCE_OFFICIAL = "official"
TERM_PROVENANCE_USER_CONFIRMED = "user_confirmed"
TERM_PROVENANCE_LEARNED = "learned"
TERM_PROVENANCE_CANDIDATE = "candidate"
_TERM_PROVENANCES = {
    TERM_PROVENANCE_BUILTIN,
    TERM_PROVENANCE_OFFICIAL,
    TERM_PROVENANCE_USER_CONFIRMED,
    TERM_PROVENANCE_LEARNED,
    TERM_PROVENANCE_CANDIDATE,
}


def learned_mapping_provenance(mapping):
    explicit = str(mapping.get("provenance") or "").strip().lower()
    if explicit in _TERM_PROVENANCES:
        return explicit
    verification = str(mapping.get("verification") or "").strip().lower()
    sources = {str(item).strip().lower() for item in mapping.get("sources", [])}
    origin = str(mapping.get("origin") or "").strip().lower()
    if (
        verification == "user_manual"
        or "user_manual" in sources
        or origin in {"手动", "批量导入", "用户确认", "ai 学习"}
    ):
        return TERM_PROVENANCE_USER_CONFIRMED
    if bool(mapping.get("confirmed")) and verification.startswith("user_"):
        return TERM_PROVENANCE_USER_CONFIRMED
    return TERM_PROVENANCE_LEARNED if bool(mapping.get("confirmed")) else TERM_PROVENANCE_CANDIDATE


def _normalized_learned_mapping(mapping):
    result = dict(mapping)
    result["provenance"] = learned_mapping_provenance(result)
    return result


def _profile_term_is_user_confirmed(item):
    source = str(item.get("source") or "").strip().lower()
    return "user_verified" in source or "user_manual" in source or "manual_srt" in source


def builtin_reference_terms_for_game(game_name, include_hidden: bool = False):
    identity = runtime_game_identity(canonicalize_runtime_game_name(game_name))
    hidden = set() if include_hidden else hidden_reference_terms_for_game(game_name)
    result = []
    for name, profile in load_game_profiles().items():
        if runtime_game_identity(str(profile.get("identity", name))) != identity:
            continue
        for item in profile.get("terms", []):
            if not isinstance(item, dict) or _profile_term_is_user_confirmed(item):
                continue
            canonical = clean_subtitle_text(item.get("canonical", ""))
            if canonical and canonical not in hidden:
                result.append(canonical)
        break
    return list(dict.fromkeys(result))


def _learned_payload_save(payload):
    try:
        os.makedirs(os.path.dirname(LEARNED_TERMS_PATH), exist_ok=True)
        atomic_write_json(LEARNED_TERMS_PATH, payload)
        return True
    except OSError:
        return False


def hidden_reference_terms_for_game(game_name):
    """User-hidden builtin reference words for one game (persistent exclusion).

    Later AI updates / builtin refreshes must never resurrect these.
    """
    identity = runtime_game_identity(canonicalize_runtime_game_name(game_name))
    if not identity:
        return set()
    entry = load_learned_term_payload().get("games", {}).get(identity, {})
    if not isinstance(entry, dict):
        return set()
    return {
        clean_subtitle_text(item)
        for item in entry.get("hidden_reference_terms", [])
        if clean_subtitle_text(item)
    }


def set_reference_terms_hidden(game_name, names, hidden: bool) -> int:
    """Hide (or restore) builtin reference words for one game."""
    identity = runtime_game_identity(canonicalize_runtime_game_name(game_name))
    if not identity:
        return 0
    targets = {clean_subtitle_text(item) for item in names if clean_subtitle_text(item)}
    if not targets:
        return 0
    payload = load_learned_term_payload()
    entry = payload.setdefault("games", {}).setdefault(
        identity, {"game": canonicalize_runtime_game_name(game_name), "mappings": []}
    )
    current = {
        clean_subtitle_text(item)
        for item in entry.get("hidden_reference_terms", [])
        if clean_subtitle_text(item)
    }
    changed = current.copy()
    if hidden:
        changed |= targets
    else:
        changed -= targets
    if changed == current:
        return 0
    entry["hidden_reference_terms"] = sorted(changed)
    return len(targets) if _learned_payload_save(payload) else 0


def hidden_runtime_game_profile_ids():
    payload = load_learned_term_payload()
    return {
        str(item)
        for item in payload.get("hidden_profile_ids", [])
        if str(item).strip()
    }


def is_runtime_game_profile_hidden(game_name):
    return runtime_game_identity(canonicalize_runtime_game_name(game_name)) in hidden_runtime_game_profile_ids()


def hide_runtime_game_profile(game_name):
    identity = runtime_game_identity(canonicalize_runtime_game_name(game_name))
    if not identity:
        return False
    payload = load_learned_term_payload()
    hidden = [str(item) for item in payload.get("hidden_profile_ids", []) if str(item).strip()]
    if identity not in hidden:
        hidden.append(identity)
    payload["hidden_profile_ids"] = hidden
    try:
        os.makedirs(os.path.dirname(LEARNED_TERMS_PATH), exist_ok=True)
        atomic_write_json(LEARNED_TERMS_PATH, payload)
    except OSError:
        return False
    return True


def migrate_user_verified_profile_terms():
    """Migrate only profile rows whose source explicitly proves user ownership."""
    payload = load_learned_term_payload()
    payload["schema"] = max(2, int(payload.get("schema", 1) or 1))
    games = payload.setdefault("games", {})
    added = 0
    changed = False
    for game_name, profile in load_game_profiles().items():
        identity = runtime_game_identity(str(profile.get("identity", game_name)))
        user_terms = [
            item for item in profile.get("terms", [])
            if isinstance(item, dict) and _profile_term_is_user_confirmed(item)
        ]
        if not identity or not user_terms:
            continue
        entry = games.setdefault(identity, {"game": game_name, "mappings": []})
        entry.setdefault("game", game_name)
        existing = {
            (content_only(item.get("from", "")), content_only(item.get("to", "")))
            for item in entry.get("mappings", []) if isinstance(item, dict)
        }
        for term in user_terms:
            target = content_only(term.get("canonical", ""))
            if not target:
                continue
            source_label = clean_subtitle_text(term.get("source", "user_verified"))
            for source in (target, *term.get("aliases", [])):
                source = content_only(source)
                key = (source, target)
                if not source or key in existing:
                    continue
                entry.setdefault("mappings", []).append({
                    "from": source,
                    "to": target,
                    "reason": "从旧版用户核验 profile 迁移",
                    "sources": [source_label],
                    "verification": "user_profile_migration",
                    "confirmed": True,
                    "provenance": TERM_PROVENANCE_USER_CONFIRMED,
                    "category": clean_subtitle_text(term.get("category", "其他")) or "其他",
                    "origin": "用户整理",
                    "updated": time.strftime("%Y-%m-%d"),
                })
                existing.add(key)
                added += 1
                changed = True
    if changed:
        for entry in games.values():
            if isinstance(entry, dict):
                entry["mappings"] = sorted(
                    entry.get("mappings", []),
                    key=lambda item: (str(item.get("to", "")), str(item.get("from", ""))),
                )
        try:
            os.makedirs(os.path.dirname(LEARNED_TERMS_PATH), exist_ok=True)
            atomic_write_json(LEARNED_TERMS_PATH, payload)
        except OSError as exc:
            print(f"   [警告] 旧版用户术语迁移未能保存：{exc}")
            return 0
    return added


def runtime_enabled_glossary_ids():
    """本批启用的词库 identity 列表（多词库）。

    空时回退到当前内容（旧单库行为）。从 active RuntimeContext 读取，
    不在 stage 模块（polishing 等）里直接写 RUNTIME_GAME_NAME。
    """
    from twobyteasr.runtime import get_runtime_context

    context = get_runtime_context()
    if not bool(getattr(context, "enable_domain_terms", False)):
        return []
    ids = [
        str(item)
        for item in getattr(context, "enabled_glossary_ids", ()) or ()
        if str(item).strip()
    ]
    if not ids:
        name = str(getattr(context, "game_name", "") or "") or RUNTIME_GAME_NAME
        if name:
            ids = [runtime_game_identity(name)]
    return list(dict.fromkeys(ids))


def learned_mappings_for_game(game_name=None):
    """已确认/学习映射。game_name 显式传参时只看该库（浏览语义）；
    不传时按本批启用的词库集合合并（pipeline 语义）。"""
    if game_name:
        game_name = canonicalize_runtime_game_name(game_name)
        ids = [runtime_game_identity(game_name)]
    else:
        ids = runtime_enabled_glossary_ids()
    payload = load_learned_term_payload().get("games", {})
    merged = []
    seen = set()
    for identity in ids:
        entry = payload.get(identity, {})
        mappings = entry.get("mappings", []) if isinstance(entry, dict) else []
        for item in mappings:
            if not (isinstance(item, dict) and item.get("from") and item.get("to")):
                continue
            key = (str(item["from"]), str(item["to"]))
            if key in seen:
                continue
            seen.add(key)
            merged.append(_normalized_learned_mapping(item))
    return merged


def user_confirmed_mappings_for_game(game_name=None):
    return [
        item for item in learned_mappings_for_game(game_name)
        if learned_mapping_provenance(item) == TERM_PROVENANCE_USER_CONFIRMED
        and bool(item.get("confirmed", True))
    ]


def learned_content_type(game_name=None):
    game_name = canonicalize_runtime_game_name(game_name or RUNTIME_GAME_NAME)
    entry = load_learned_term_payload().get("games", {}).get(
        runtime_game_identity(game_name), {}
    )
    return str(entry.get("content_type", "game")) if isinstance(entry, dict) else "game"


def ensure_learned_content(game_name, content_type="game"):
    """Create/update a content entry even before it has any learned mappings."""
    game_name = canonicalize_runtime_game_name(game_name)
    identity = runtime_game_identity(game_name)
    if not game_name or not identity:
        return False
    allowed = {"game", "event", "series", "creator", "other"}
    content_type = str(content_type) if str(content_type) in allowed else "other"
    payload = load_learned_term_payload()
    payload["schema"] = max(2, int(payload.get("schema", 1) or 1))
    payload["hidden_profile_ids"] = [
        str(item)
        for item in payload.get("hidden_profile_ids", [])
        if str(item).strip() and str(item) != identity
    ]
    entry = payload.setdefault("games", {}).setdefault(
        identity, {"game": game_name, "mappings": []}
    )
    entry["game"] = game_name
    entry["content_type"] = content_type
    try:
        os.makedirs(os.path.dirname(LEARNED_TERMS_PATH), exist_ok=True)
        atomic_write_json(LEARNED_TERMS_PATH, payload)
    except OSError:
        return False
    return True


def learned_canonical_terms(game_name=None):
    """Return saved canonical spellings as safe, evidence-gated glossary hints."""
    result = []
    seen = set()
    for item in learned_mappings_for_game(game_name):
        target = content_only(item.get("to", ""))
        if 2 <= len(target) <= 18 and target not in seen:
            result.append(target)
            seen.add(target)
    return result


def enabled_glossary_adjudication_evidence():
    """Structured, read-only evidence for cloud disagreement adjudication."""
    enabled_ids = runtime_enabled_glossary_ids()
    enabled_set = set(enabled_ids)
    games = []
    canonical_terms = []
    aliases = []
    corrections = []
    for name, profile in load_game_profiles().items():
        identity = runtime_game_identity(str(profile.get("identity", name)))
        if identity not in enabled_set:
            continue
        games.append(str(name))
        for item in profile.get("terms", []):
            if not isinstance(item, dict):
                continue
            canonical = clean_subtitle_text(item.get("canonical", ""))
            if not canonical:
                continue
            canonical_terms.append(canonical)
            for alias in item.get("aliases", []):
                alias = clean_subtitle_text(alias)
                if alias and alias != canonical:
                    aliases.append({"alias": alias, "canonical": canonical})
    payload_games = load_learned_term_payload().get("games", {})
    for identity in enabled_ids:
        entry = payload_games.get(identity, {}) if isinstance(payload_games, dict) else {}
        if not isinstance(entry, dict):
            continue
        game_name = clean_subtitle_text(entry.get("game", ""))
        if game_name:
            games.append(game_name)
        for item in entry.get("mappings", []):
            if not isinstance(item, dict):
                continue
            source = content_only(item.get("from", ""))
            target = content_only(item.get("to", ""))
            if not source or not target:
                continue
            canonical_terms.append(target)
            if source != target:
                corrections.append({
                    "wrong": source,
                    "correct": target,
                    "category": clean_subtitle_text(item.get("category", "")),
                    "origin": clean_subtitle_text(item.get("origin", "")),
                })
    return {
        "enabled_glossary_ids": enabled_ids,
        "game_or_content_names": list(dict.fromkeys(games)),
        "canonical_terms": list(dict.fromkeys(canonical_terms)),
        "aliases": list({(item["alias"], item["canonical"]): item for item in aliases}.values()),
        "wrong_to_correct_mappings": list({
            (item["wrong"], item["correct"]): item for item in corrections
        }.values()),
    }


def add_learned_mapping(game_name, source, target, *, category="其他", origin="手动", evidence_metadata=None):
    """手动新增一条已学习映射；from==to 表示确认专名正确写法。返回是否新增。"""
    game_name = canonicalize_runtime_game_name(game_name)
    identity = runtime_game_identity(game_name)
    source = content_only(source)
    target = content_only(target)
    if not source or not target:
        return False
    payload = load_learned_term_payload(strict=True)
    payload["schema"] = max(2, int(payload.get("schema", 1) or 1))
    payload["hidden_profile_ids"] = [
        str(item)
        for item in payload.get("hidden_profile_ids", [])
        if str(item).strip() and str(item) != identity
    ]
    entry = payload.setdefault("games", {}).setdefault(
        identity, {"game": game_name, "mappings": []}
    )
    mappings = entry.setdefault("mappings", [])
    for item in mappings:
        if item.get("from") == source and item.get("to") == target:
            return False
    record = {
            "from": source,
            "to": target,
            "reason": "手动添加",
            "sources": ["user_manual"],
            "verification": "user_manual",
            "confirmed": True,
            "provenance": TERM_PROVENANCE_USER_CONFIRMED,
            "category": clean_subtitle_text(category) or "其他",
            "origin": clean_subtitle_text(origin) or "手动",
            "updated": time.strftime("%Y-%m-%d"),
        }
    if evidence_metadata is not None:
        # Batch acceptance confirms use, not independent manual verification.
        for key in ('reason','sources','verification','category_key','task_id','priority','frequency_note'):
            if key in evidence_metadata:
                record[key]=copy.deepcopy(evidence_metadata[key])
    mappings.append(record)
    os.makedirs(os.path.dirname(LEARNED_TERMS_PATH), exist_ok=True)
    atomic_write_json(LEARNED_TERMS_PATH, payload)
    return True


def persist_learned_mappings(game_name, mappings):
    if not game_name or not mappings:
        return
    payload = load_learned_term_payload()
    payload["schema"] = max(2, int(payload.get("schema", 1) or 1))
    games = payload.setdefault("games", {})
    identity = runtime_game_identity(game_name)
    entry = games.setdefault(identity, {"game": game_name, "mappings": []})
    existing = {
        (content_only(item.get("from", "")), content_only(item.get("to", ""))): item
        for item in entry.get("mappings", [])
        if isinstance(item, dict)
    }
    blocked = (
        active_blocked_mapping_pairs()
        if runtime_game_identity(game_name) == runtime_game_identity(RUNTIME_GAME_NAME)
        else set()
    )
    for mapping in mappings:
        key = (content_only(mapping.get("from", "")), content_only(mapping.get("to", "")))
        if not all(key) or key in blocked:
            continue
        existing[key] = {
            "from": clean_subtitle_text(mapping["from"]),
            "to": clean_subtitle_text(mapping["to"]),
            "reason": clean_subtitle_text(mapping.get("reason", "联网术语核验"))[:160],
            "sources": list(mapping.get("sources", ()))[:5],
            "verification": mapping.get("verification", "web_source"),
            "confirmed": bool(mapping.get("confirmed", False)),
            "provenance": (
                str(mapping.get("provenance"))
                if str(mapping.get("provenance", "")).lower() in _TERM_PROVENANCES
                else (
                    TERM_PROVENANCE_USER_CONFIRMED
                    if learned_mapping_provenance(mapping) == TERM_PROVENANCE_USER_CONFIRMED
                    else TERM_PROVENANCE_CANDIDATE
                )
            ),
            "category": clean_subtitle_text(mapping.get("category", "其他")) or "其他",
            "origin": clean_subtitle_text(
                mapping.get("origin")
                or (
                    "AI 学习"
                    if str(mapping.get("verification", "")).startswith("ai_")
                    else ("官方" if mapping.get("verification") == "web_official" else "用户确认")
                )
            ),
            "updated": time.strftime("%Y-%m-%d"),
        }
    entry["mappings"] = sorted(existing.values(), key=lambda item: (item["to"], item["from"]))
    try:
        os.makedirs(os.path.dirname(LEARNED_TERMS_PATH), exist_ok=True)
        atomic_write_json(LEARNED_TERMS_PATH, payload)
    except OSError as exc:
        # 本批已核验映射仍可使用；只是不带到下一批，不能因此重跑联网 API。
        print(f"   [警告] 已学习术语未能持久保存：{exc}")


def delete_learned_mappings(game_name, mapping_keys):
    """删除用户在管理窗口中明确选中的学习映射。"""
    identity = runtime_game_identity(canonicalize_runtime_game_name(game_name))
    payload = load_learned_term_payload()
    games = payload.get("games", {})
    entry = games.get(identity)
    if not isinstance(entry, dict):
        return 0
    keys = {
        (content_only(source), content_only(target))
        for source, target in mapping_keys
    }
    before = list(entry.get("mappings", []))
    entry["mappings"] = [
        item
        for item in before
        if (
            content_only(item.get("from", "")),
            content_only(item.get("to", "")),
        )
        not in keys
    ]
    removed = len(before) - len(entry["mappings"])
    if removed:
        os.makedirs(os.path.dirname(LEARNED_TERMS_PATH), exist_ok=True)
        atomic_write_json(LEARNED_TERMS_PATH, payload)
    return removed


def delete_learned_game(game_name):
    """Remove one user-created content entry and all of its learned mappings."""
    identity = runtime_game_identity(canonicalize_runtime_game_name(game_name))
    if not identity:
        return False
    payload = load_learned_term_payload()
    games = payload.get("games", {})
    if not isinstance(games, dict) or identity not in games:
        return False
    del games[identity]
    try:
        os.makedirs(os.path.dirname(LEARNED_TERMS_PATH), exist_ok=True)
        atomic_write_json(LEARNED_TERMS_PATH, payload)
    except OSError:
        return False
    return True


def prepared_learned_mappings(segments, game_name=None):
    """把已核验学习词转换成本次稿件可安全应用的映射。"""
    result = []
    blocked = active_blocked_mapping_pairs()
    for item in learned_mappings_for_game(game_name):
        source = content_only(item.get("from", ""))
        target = content_only(item.get("to", ""))
        if not source or not target or source == target or (source, target) in blocked:
            continue
        occurrence_ids = [
            segment.segment_id
            for segment in segments
            if source in content_only(segment.text)
        ]
        if not occurrence_ids:
            continue
        confirmed = bool(item.get("confirmed", False))
        result.append(
            {
                "from": source,
                "to": target,
                "source_ids": occurrence_ids,
                # 用户确认词或本批重复出现时全文统一；单次联网学习词只改命中段。
                "apply_all": confirmed or len(occurrence_ids) >= 2,
                "reason": item.get("reason", "已学习术语"),
                "sources": list(item.get("sources", ())),
                "verification": item.get("verification", "learned"),
                "confirmed": confirmed,
            }
        )
        RUNTIME_DISCOVERED_TERMS.add(target)
    return result


def active_canonical_replacements():
    if not RUNTIME_ENABLE_DOMAIN_TERMS:
        return ()
    pairs = [
        (item["source"], item["target"])
        for item in active_profile_alias_rules()
        if item["mode"] == "global"
    ]
    return tuple(dict.fromkeys(pairs))


def active_contextual_alias_map():
    return {
        item["source"]: item["target"]
        for item in active_profile_alias_rules()
        if item["mode"] == "contextual"
    }


def apply_active_canonical_replacements(text):
    for source, target in active_canonical_replacements():
        if source == "爆米花":
            text = re.sub(r"爆米花(?!爆破)", target, text)
        else:
            text = text.replace(source, target)
    if active_canonical_replacements():
        # PVP 口语中的“挂寄生”常被写成“刮寄生”；只在明确技能搭配里修正，
        # 不把普通动词“刮”一概替换。
        text = re.sub(r"刮(?=(?:个|一层|两层|三层|几层)?寄生)", "挂", text)
    return text


def runtime_content_profile_signature():
    return {
        "game": clean_subtitle_text(RUNTIME_GAME_NAME),
        "domain_terms": bool(RUNTIME_ENABLE_DOMAIN_TERMS),
        "enabled_glossary_ids": sorted(runtime_enabled_glossary_ids()),
        "expected_speakers": int(RUNTIME_EXPECTED_SPEAKERS),
        "dialogue_coverage_mode": str(RUNTIME_DIALOGUE_COVERAGE_MODE),
    }


def runtime_settings_snapshot():
    """Non-secret effective settings, suitable for a per-media task report."""
    from twobyteasr.recognition_plan import text_ai_plan
    context = get_runtime_context()
    plan = text_ai_plan(context.asr_settings_snapshot or RUNTIME_SETTINGS, purpose=context.recognition_purpose)
    disabled = dict(provider="disabled", model="", base_url="")
    polish_settings = polish_llm_settings() if plan.polish else disabled
    group_settings = group_llm_settings() if plan.group else disabled
    return {
        "config_file": RUNTIME_SETTINGS_PATH,
        "config_warnings": list(RUNTIME_SETTINGS_WARNINGS),
        "models": {
            "primary_asr_backend": PRIMARY_ASR_BACKEND,
            "qwen_asr_backend": QWEN_ASR_BACKEND,
            "qwen_asr_model": QWEN_ASR_MODEL,
            "qwen_asr_api_provider": RUNTIME_SETTINGS["models"].get(
                "qwen_asr_api_provider", "dashscope"
            ),
            "qwen_asr_api_protocol": RUNTIME_SETTINGS["models"].get(
                "qwen_asr_api_protocol", "dashscope_multimodal"
            ),
            "qwen_asr_api_model": QWEN_ASR_API_MODEL,
            "qwen_asr_api_url": QWEN_ASR_API_URL,
            "firered_asr_backend": FIRERED_ASR_BACKEND,
            "polish_provider": polish_settings["provider"],
            "polish_model": polish_settings["model"],
            "polish_base_url": polish_settings["base_url"],
            "group_provider": group_settings["provider"],
            "group_model": group_settings["model"],
            "group_base_url": group_settings["base_url"],
        },
        "switches": {
            "enable_ai_polish": plan.polish,
            "enable_qwen_asr_reference": bool(USE_QWEN_ASR_REFERENCE),
            "enable_firered_boundary_refinement": bool(USE_FIRERED_BOUNDARY_REFINEMENT),
            "use_ai_grouping": bool(RUNTIME_SETTINGS["switches"].get("use_ai_grouping", True)),
            "unified_glm_processing": bool(
                RUNTIME_SETTINGS["switches"].get("unified_glm_processing", True)
            ),
            "show_speaker_labels_in_srt": bool(SHOW_SPEAKER_LABELS_IN_SRT),
            "output_review_track": bool(RUNTIME_OUTPUT_REVIEW_TRACK),
            "dialogue_coverage_mode": str(RUNTIME_DIALOGUE_COVERAGE_MODE),
        },
        "cache": {
            "force_refresh_polish": bool(RUNTIME_FORCE_REFRESH_POLISH_CACHE),
            "force_refresh_group": bool(RUNTIME_FORCE_REFRESH_GROUP_CACHE),
        },
        "performance": {
            "parallel_cloud_batches": bool(PARALLEL_CLOUD_BATCHES),
            "cloud_batch_workers": int(CLOUD_BATCH_WORKERS),
            "parallel_cpu_vad": bool(PARALLEL_CPU_VAD),
            "moss_parallel_workers": int(MOSS_PARALLEL_WORKERS),
            "moss_parallel_min_vram_gb": float(MOSS_PARALLEL_MIN_VRAM_GB),
            "qwen_asr_batch_size": int(QWEN_ASR_BATCH_SIZE),
            "parallel_gpu_asr": bool(PARALLEL_GPU_ASR),
            "parallel_gpu_asr_min_vram_gb": float(PARALLEL_GPU_ASR_MIN_VRAM_GB),
        },
        "content_profile": runtime_content_profile_signature(),
    }


def begin_media_report(media_path, cache_context):
    task_reporting.begin_media_report(
        media_path,
        cache_context,
        runtime_settings_snapshot(),
    )


def finish_media_report(status, **result):
    return task_reporting.finish_media_report(status, **result)


# 字幕风格来自人工校正样本：以约 8 字的完整语义块为目标。
HARD_GAP_SECONDS = 1.2


INTERNAL_HARD_GAP_SECONDS = 3.0


# 约 0.8 秒已经是剪辑上清晰可感知的停顿。只要边界不落在词中、也不是
# 明显未完成成分，就保留 MOSS 的原始段界，避免把停顿后的两字回应重新吞回前句。
PROTECTED_SOURCE_GAP_SECONDS = 0.75


TWO_CHARACTER_MERGE_MAX_GAP_SECONDS = 0.75


PROTECTED_SOURCE_SHORT_CHARS = 3


# 单字语气词只在近乎连读时并入相邻字幕；更远的语气词由成片规则省略，
# 不能为了消灭单字轨而让上一句横跨整段空白。
SINGLE_CHARACTER_MERGE_MAX_GAP_SECONDS = 0.35


MAX_SUBTITLE_SECONDS = 5.0


# 人工样本的自然中位数约 10 字。长度只用于舒适度排序，不能为了凑 8 字
# 把“终末地的单肩包”“捶背的毛绒锤”或完整主谓宾机械腰斩。
PREFERRED_MAX_SUBTITLE_CHARS = 10


MAX_SUBTITLE_CHARS = 16


# 人工修订样本最长 14-15 字；最终成片不再为“完整短语”放宽到 17-20 字。
# 达到 16 字附近且包含两个语义动作时，应优先在自然气口拆分。
COMPLETE_PHRASE_SOFT_MAX_CHARS = 16


MAX_RAW_SEGMENT_CHARS = 24


REAL_PAUSE_HINT_SECONDS = 0.18


# 只修正“字幕句首明确落在 VAD 静音区”的保守场景。小于 180ms 可能只是
# 起音检测误差，大于 650ms 更可能是漏句或说话人归属问题，只提示复核。
VAD_ONSET_SNAP_MIN_LEAD_SECONDS = 0.18


VAD_ONSET_SNAP_MAX_LEAD_SECONDS = 0.65


VAD_ONSET_CONTAINMENT_PAD_SECONDS = 0.03


MIN_SUBTITLE_SECONDS = 0.35


PHONETIC_MAX_DISTANCE = 0.70


# 人声起音只用来修正相邻字幕交界，不参与文字识别。
BOUNDARY_VAD_THRESHOLD = 0.50


BOUNDARY_VAD_MIN_SPEECH_MS = 80


BOUNDARY_VAD_MIN_SILENCE_MS = 160


BOUNDARY_VAD_MIN_GAP_SECONDS = 0.15


BOUNDARY_VAD_LOOKBACK_SECONDS = 0.30


BOUNDARY_VAD_SHORT_GAP_ONSET_LEAD_SECONDS = 0.07


MAX_CUE_HOLD_GAP_SECONDS = 0.20


MAX_HELD_SUBTITLE_SECONDS = 4.00


# 与下一条之间有足够空白的独立字幕，在识别尾音后多保留 200ms，避免突兀消失。
ISOLATED_CUE_TAIL_SECONDS = 0.20


# 默认尾帧仍只增加 200ms；如果所有轨道在相邻字幕间仍剩不足 500ms 的空白，
# 再让当前可见字幕保持到下一条开始，避免剪映画面出现短促闪轴。
SHORT_DISPLAY_GAP_BRIDGE_SECONDS = 0.50


EDITORIAL_OMITTABLE_SINGLE_CHARACTERS = frozenset(
    (
        "嗯", "啊", "哦", "呃", "哎", "诶", "唉", "呀", "哈",
        "喔", "恩", "噢", "唔", "欸", "吶", "呵", "嘿", "嘻", "哼", "欸",
    )
)


INTERNAL_BOUNDARY_MAX_SHIFT_SECONDS = 0.45


INTERNAL_BOUNDARY_MIN_VAD_SILENCE_RATIO = 0.45


# FireRed is allowed to correct the position of characters inside a MOSS segment,
# but must not pull an entire segment far outside MOSS's speaker boundary.
FIRERED_TIMELINE_MAX_START_SHIFT_SECONDS = 0.45


FIRERED_TIMELINE_MAX_END_SHIFT_SECONDS = 0.65


# 中间结果写入 LocalAppData，不在素材目录额外生成文件。
CACHE_ROOT = os.path.join(
    os.environ.get("LOCALAPPDATA", SCRIPT_DIR),
    "2ByteASR",
    "cache",
)


CACHE_SCHEMA_VERSION = 3


CACHE_MAX_AGE_DAYS = 14


CACHE_STAGE_VERSIONS = {
    "audio": 1,
    "qwen": 4,
    "firered": 6,
    "polished": 28,
    "grouped": 55,
    "grouped_local": 1,
    "moss": 6,
    "firered_vad": 1,
    "lightweight_vad": 1,
    # Every non-MOSS primary backend shares this cache schema.  The concrete
    # backend and its speech regions are already included in extra_signature.
    "primary_backend": 1,
    # 11: 主稿入口新增同说话人部分覆盖去重（2026-09-03 重复段/0.35s 阶梯串修复）。
    "firered_primary": 11,
    "firered_llm": 2,
    "final_timing": 11,
}


# API 阶段只依赖各自逻辑版本，不再散列整个 6800 行模块。以后修改时间轴、
# 输出或日志不会无故让全文校对和全文断句缓存失效。
POLISH_LOGIC_VERSION = "polish-v32-explicit-coverage-and-partial-cache"
GROUP_LOGIC_VERSION = "group-v59-word-safe-comfort-length"
TIMING_LOGIC_VERSION = "timing-v10-reading-rate-guard"


# 复核清单只打印在运行窗口，不增加第三个输出文件。
REVIEW_MAX_ITEMS = 24


REVIEW_LOW_CONFIDENCE = 0.45


REVIEW_FAST_CHARS_PER_SECOND = 9.0


REVIEW_TIMING_DIFFERENCE_SECONDS = 0.30


TARGET_RAW_SEGMENT_CHARS = 8


MIN_BALANCED_SEGMENT_CHARS = 4


API_BATCH_MAX_CHARS = 5000


API_BATCH_MAX_CUES = 20


# 字幕校对比全文断句包含更多文字修改与安全审计，单个大批次容易成为
# 云端长尾。32 条左右的短素材拆成 3 个批次，可让现有 3 路并发真正生效；
# 断句仍保留 20 条上限，避免无意义地增加云端请求数。
POLISH_BATCH_MAX_CUES = 16


# One initial request plus one targeted retry for malformed/empty structured output.
API_RETRIES = 2


# 全文断句只提供边界建议，失败时已有逐字守恒的本地分段兜底。云端模型在
# temperature=0 下重复提交同一批次通常仍会撞上相同安全护栏，过去最多
# 白等 90 秒；一次未通过即本地回退，不影响已完成的校对正文。
GROUPING_API_RETRIES = 2


# CLI 账号会话传输（grok_cli 等）的单批延迟与 polish 同级：2026-09-03 实测
# 同传输的 polish 批次最长 136s 仍成功，而断句 45s 上限把正常长尾判成超时，
# 3 次即连锁熔断（当单 9/13 批次回退）。与 API_TIMEOUT_SECONDS 对齐。
GROUPING_API_TIMEOUT_SECONDS = 120


# 断句批次独立上限：indexed_content 会把每个字编号后随请求发送，5000 字
# 批次的 CLI 载荷与响应时长都是超时主因。1800 字/10 条让单批回到 20~40s
# 区间，配合云端并发总墙钟时间不升反降。
GROUP_API_BATCH_MAX_CHARS = 1800


GROUP_API_BATCH_MAX_CUES = 10


# 词中切点“挪字修复”（不合并两条）允许跨过的最大间隙：换气级。跨长静音
# 或说话人重叠锁定段不挪，防止破坏时间冻结契约。
MID_WORD_MOVE_MAX_GAP_SECONDS = 2.0


# 本地回退（云端断句不可用/关闭）时保留 MOSS 原句的舒适长度上限：
# 13-16 字的段走词感知 DP 重切到 ~8-12 字，避免单行放不下被播放器折行。
# 云端模型自己返回的 13-16 字完整成分不受此限制（语义优先）。
FALLBACK_COMFORT_MAX_CHARS = 12


# normalize 推挤同说话人碰撞时，单条字幕的最短可读时长按字数放宽：
# 8 字条不再被压到 0.35s（0.35s 阶梯串 = 23~43 字/秒闪现的根因兜底）。
NORMALIZE_MAX_CHARS_PER_SECOND = 12.0


# 首轮云端模型已收到全文、气口和强制边界，随后还有完整的本地词法/语义护栏。
# 再请求一次云端校验会把每个断句批次的延迟近乎翻倍，且仍需本地裁决；
# 默认关闭，保留函数供诊断或未来配置化使用。
SECOND_PASS_GROUP_VALIDATION = False


API_TIMEOUT_SECONDS = 120


RUN_REVIEW_ITEMS = _DEFAULT_RUNTIME_CONTEXT.review_items


_REVIEW_ITEM_LOCAL = threading.local()


def _active_review_items():
    return getattr(_REVIEW_ITEM_LOCAL, "items", get_runtime_context().review_items)


def extend_review_items(items):
    _active_review_items().extend(items or [])


@contextmanager
def capture_review_items():
    """Isolate review messages produced by one concurrent stage or API batch."""
    previous = getattr(_REVIEW_ITEM_LOCAL, "items", None)
    captured = []
    _REVIEW_ITEM_LOCAL.items = captured
    try:
        yield captured
    finally:
        if previous is None:
            try:
                del _REVIEW_ITEM_LOCAL.items
            except AttributeError:
                pass
        else:
            _REVIEW_ITEM_LOCAL.items = previous


def reset_review_items():
    runtime_items = get_runtime_context().review_items
    runtime_items.clear()
    if RUN_REVIEW_ITEMS is not runtime_items:
        RUN_REVIEW_ITEMS.clear()
    local_items = getattr(_REVIEW_ITEM_LOCAL, "items", None)
    if local_items is not None:
        local_items.clear()


def resolve_review_items(*, categories, segment_ids):
    """Remove pre-polish review notes only for segments successfully adjudicated."""
    category_set = {str(item) for item in categories}
    id_set = {int(item) for item in segment_ids}
    if not category_set or not id_set:
        return 0
    runtime_items = get_runtime_context().review_items
    before = len(runtime_items)
    runtime_items[:] = [
        item
        for item in runtime_items
        if not (
            str(item.get("category") or "") in category_set
            and int(item.get("segment_id") or -1) in id_set
        )
    ]
    return before - len(runtime_items)


_REVIEW_SEVERITIES = {"error", "warning", "review", "info", "debug"}
_REVIEW_CATEGORY_SEVERITY = {
    "校对回退": "warning",
    "断句回退": "warning",
    "主力转写提前结束": "warning",
    "时间轴模型失败": "warning",
    "Whisper失败": "warning",
    "漏句回退": "warning",
    "多模型文本冲突": "review",
    "多模型争议": "review",
    "低置信度": "review",
    "ASR分歧": "review",
    "说话人重叠": "review",
    "疑似重复": "review",
    "显示过短": "review",
    "阅读较快": "review",
    "边界待看": "review",
    "孤立实义单字": "review",
    "Qwen骨架缺口": "info",
    "时间锚覆盖低": "info",
    "句首VAD校准": "debug",
    "MOSS重叠副本去重": "debug",
    "临时说话人找回": "info",
    "FireRed-LLM跳过": "info",
    "成片省略语气词": "info",
    "单字护栏回滚": "info",
}


def review_item_severity(item_or_category, priority=1):
    if isinstance(item_or_category, dict):
        explicit = str(item_or_category.get("severity") or "").lower()
        if explicit in _REVIEW_SEVERITIES:
            return explicit
        category = str(item_or_category.get("category") or "")
        priority = int(item_or_category.get("priority", priority) or priority)
    else:
        category = str(item_or_category or "")
    if category in _REVIEW_CATEGORY_SEVERITY:
        return _REVIEW_CATEGORY_SEVERITY[category]
    return "review" if int(priority) >= 2 else "info"


def add_review_item(
    timestamp,
    category,
    detail,
    text="",
    priority=1,
    severity=None,
    **diagnostics,
):
    resolved_severity = str(severity or "").lower()
    if resolved_severity not in _REVIEW_SEVERITIES:
        resolved_severity = review_item_severity(category, priority)
    item = {
        "timestamp": max(0.0, float(timestamp)),
        "category": str(category),
        "detail": str(detail),
        "text": clean_subtitle_text(text) if text else "",
        "priority": int(priority),
        "severity": resolved_severity,
    }
    for key, value in diagnostics.items():
        if key not in item:
            item[str(key)] = value
    _active_review_items().append(
        item
    )


def serialize_segments(segments):
    return [asdict(segment) for segment in segments]


def deserialize_segments(items):
    result = []
    for item in items or []:
        words = [WordUnit(**word) for word in item.get("words", [])]
        result.append(
            SpeechSegment(
                segment_id=int(item["segment_id"]),
                start=float(item["start"]),
                end=float(item["end"]),
                text=str(item["text"]),
                confidence=float(item.get("confidence", 0.0)),
                words=words,
                speaker=str(item.get("speaker", "S00")),
                moss_text=str(item.get("moss_text", "")),
                moss_context=str(item.get("moss_context", "")),
                firered_llm_text=str(item.get("firered_llm_text", "")),
                firered_llm_context=str(item.get("firered_llm_context", "")),
                alternate_text=str(item.get("alternate_text", "")),
                alternate_context=str(item.get("alternate_context", "")),
                qwen_asr_text=str(item.get("qwen_asr_text", "")),
                qwen_asr_context=str(item.get("qwen_asr_context", "")),
                overlapping_speaker_conflict=bool(
                    item.get("overlapping_speaker_conflict", False)
                ),
                timing_locked=bool(item.get("timing_locked", False)),
                firered_text=str(item.get("firered_text", "")),
                moss_start=float(item.get("moss_start", item.get("start", 0.0)) or 0.0),
                moss_end=float(item.get("moss_end", item.get("end", 0.0)) or 0.0),
                firered_start=float(item.get("firered_start", 0.0) or 0.0),
                firered_end=float(item.get("firered_end", 0.0) or 0.0),
                firered_alignment_confidence=float(item.get("firered_alignment_confidence", 0.0) or 0.0),
                qwen_text=str(item.get("qwen_text", item.get("qwen_asr_text", "")) or ""),
                qwen_confidence=float(item.get("qwen_confidence", 0.0) or 0.0),
                final_text=str(item.get("final_text", item.get("text", "")) or ""),
                final_start=float(item.get("final_start", item.get("start", 0.0)) or 0.0),
                final_end=float(item.get("final_end", item.get("end", 0.0)) or 0.0),
                final_text_owner=str(item.get("final_text_owner", "MOSS") or "MOSS"),
                final_timing_owner=str(item.get("final_timing_owner", "MOSS") or "MOSS"),
                primary_source=str(item.get("primary_source", "moss-host")),
                reference_consensus=float(item.get("reference_consensus", 0.0)),
            )
        )
    return result


def serialize_cues(cues):
    return [asdict(cue) for cue in cues]


def deserialize_cues(items):
    return [
        SubtitleCue(
            cue_id=int(item["cue_id"]),
            start=float(item["start"]),
            end=float(item["end"]),
            text=str(item["text"]),
            timing_locked=bool(item.get("timing_locked", False)),
            speaker=str(item.get("speaker", "S00")),
        )
        for item in (items or [])
    ]


from twobyteasr.cache import *  # noqa: F401,F403

def pause_exit(code=0):
    raise SystemExit(code)


def load_runtime_game_history():
    try:
        with open(PROFILE_HISTORY_PATH, "r", encoding="utf-8") as file:
            payload = json.load(file)
        values = payload.get("recent_games", [])
        if not isinstance(values, list):
            return []
        result = []
        seen = set()
        for value in values:
            canonical = canonicalize_runtime_game_name(value)
            identity = runtime_game_identity(canonical)
            if canonical and identity and identity not in seen:
                result.append(canonical)
                seen.add(identity)
        return result[:12]
    except (OSError, ValueError, TypeError):
        return []


def save_runtime_game_history(game_name):
    game_name = canonicalize_runtime_game_name(game_name)
    if not game_name:
        return
    recent = [game_name]
    current_identity = runtime_game_identity(game_name)
    recent.extend(
        value
        for value in load_runtime_game_history()
        if runtime_game_identity(value) != current_identity
    )
    try:
        os.makedirs(os.path.dirname(PROFILE_HISTORY_PATH), exist_ok=True)
        atomic_write_json(PROFILE_HISTORY_PATH, {"recent_games": recent[:12]})
    except OSError as exc:
        print(f"   [警告] 内容历史未保存，不影响本批识别：{exc}")


def delete_runtime_game_history(game_name):
    """Remove one content name from the user-maintained recent-content list."""
    identity = runtime_game_identity(canonicalize_runtime_game_name(game_name))
    if not identity:
        return False
    before = load_runtime_game_history()
    recent = [value for value in before if runtime_game_identity(value) != identity]
    if len(recent) == len(before):
        return False
    try:
        os.makedirs(os.path.dirname(PROFILE_HISTORY_PATH), exist_ok=True)
        atomic_write_json(PROFILE_HISTORY_PATH, {"recent_games": recent[:12]})
    except OSError:
        return False
    return True


def detect_timeline_fps(media_path):
    """直接选视频时读取真实帧率；纯音频沿用 60 fps 兜底。"""
    ffprobe_path = shutil.which("ffprobe")
    if not ffprobe_path:
        return TIMELINE_FPS
    command = [
        ffprobe_path,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=avg_frame_rate",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        media_path,
    ]
    try:
        result = run_hidden_subprocess(
            command,
            purpose="ffprobe timeline fps",
            runner=subprocess.run,
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        value = result.stdout.strip().splitlines()[0]
        numerator, denominator = value.split("/", 1)
        fps = float(numerator) / float(denominator)
        if 10.0 <= fps <= 240.0:
            print(f"   检测到视频时间轴：{fps:.6g} fps。")
            return fps
    except Exception:
        pass
    print(f"   未检测到视频帧率，按 {TIMELINE_FPS:.6g} fps 对齐。")
    return TIMELINE_FPS


def output_paths_for_media(media_path):
    file_dir = os.path.dirname(media_path)
    base_name = os.path.splitext(os.path.basename(media_path))[0]
    return (
        os.path.join(file_dir, f"{base_name}_剪映文稿.txt"),
        os.path.join(file_dir, f"{base_name}_剪映文稿.srt"),
    )


def format_elapsed(seconds):
    seconds = max(0, int(round(float(seconds))))
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}小时{minutes:02d}分{secs:02d}秒"
    if minutes:
        return f"{minutes}分{secs:02d}秒"
    return f"{secs}秒"


def run_timed_stage(index, total, label, resource, runner):
    cancellation_token = (
        get_runtime_context().cancellation_token or RUNTIME_CANCELLATION_TOKEN
    )
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    print(f"\n[阶段 {index}/{total}] {label}（{resource}）", flush=True)
    started = time.perf_counter()
    record_run_event(
        "stage_started",
        index=index,
        total=total,
        label=label,
        resource=resource,
    )
    try:
        value = runner()
    except BaseException as exc:
        elapsed = time.perf_counter() - started
        cancelled = isinstance(exc, KeyboardInterrupt) or exc.__class__.__name__ == "CancelledError"
        record_run_event(
            "stage_cancelled" if cancelled else "stage_failed",
            index=index,
            label=label,
            elapsed_seconds=round(elapsed, 3),
            error=redact_runtime_secrets(exc),
            traceback=redact_runtime_secrets(traceback.format_exc()),
        )
        raise
    elapsed = time.perf_counter() - started
    record_run_event(
        "stage_completed",
        index=index,
        label=label,
        elapsed_seconds=round(elapsed, 3),
    )
    print(f"[阶段完成] {label}：{format_elapsed(elapsed)}", flush=True)
    return value


def check_runtime():
    from importlib.metadata import PackageNotFoundError, version as package_version
    missing = []
    packages = ["pypinyin", "requests", "jieba", "PySide6", "QtAwesome"]
    if QWEN_ASR_BACKEND == "local" or PRIMARY_ASR_BACKEND == "qwen_local":
        packages.append("qwen-asr")
    if QWEN_ASR_BACKEND == "whisper_turbo" or PRIMARY_ASR_BACKEND == "whisper_turbo":
        packages.append("transformers")
    if (
        QWEN_ASR_BACKEND in {"sensevoice", "funasr_nano"}
        or FIRERED_ASR_BACKEND == "paraformer"
        or PRIMARY_ASR_BACKEND in {"sensevoice", "funasr_nano", "paraformer"}
    ):
        packages.append("funasr")
    if FIRERED_ASR_BACKEND == "qwen_aligner" and "qwen-asr" not in packages:
        packages.append("qwen-asr")
    # 打包（frozen）运行里 PyInstaller 不带 dist-info，importlib.metadata 必然
    # PackageNotFoundError——按真实可导入性校验；且 qwen-asr/transformers/funasr
    # 等运行时包执行于外部 venv（bundle 刻意排除），不在进程内检查范围。
    frozen = bool(getattr(sys, "frozen", False))
    frozen_external_runtimes = {"qwen-asr", "transformers", "funasr"}
    module_aliases = {
        "PySide6": "PySide6",
        "QtAwesome": "qtawesome",
    }
    for package_name in packages:
        if frozen:
            if package_name in frozen_external_runtimes:
                continue
            try:
                __import__(module_aliases.get(package_name, package_name))
            except ImportError:
                missing.append(package_name)
            continue
        try:
            package_version(package_name)
        except PackageNotFoundError:
            missing.append(package_name)
    if missing:
        raise RuntimeError(
            "缺少运行依赖："
            + ", ".join(missing)
            + "\n请执行：\n"
            'python -m pip install -r requirements-main.txt'
        )
    for executable in ("ffmpeg", "ffprobe"):
        resolved = shutil.which(executable)
        if resolved is None:
            raise RuntimeError(f"缺少 {executable}，请先加入 PATH。")
        # 可执行性验证：部分环境（winget 安装中断/缺运行库）下 exe 会
        # 0xc0000005 崩溃，运行中才暴露。提前探测并给出明确提示。
        try:
            completed = run_hidden_subprocess(
                [resolved, "-version"],
                purpose=f"{executable} runtime check",
                runner=subprocess.run,
                capture_output=True,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            completed = None
        if completed is None or completed.returncode not in (0, 1):
            raise RuntimeError(
                f"{executable} 无法正常运行（可能已损坏或缺少运行库）。\n"
                "请重新安装 FFmpeg：\n"
                "  winget uninstall Gyan.FFmpeg\n"
                "  winget install Gyan.FFmpeg\n"
                "或从 https://www.gyan.dev/ffmpeg/builds/ 下载完整版解压到 C:\\ffmpeg\\bin"
            )


# 兼容门面：subtitle_core 与 twobyteasr 互为循环导入，本处导入必须位于配置区之后，
# 请勿上移或把函数定义插到这些 import 语句中间。
from twobyteasr.text_rules import *  # noqa: F401,F403
from twobyteasr.asr import *  # noqa: F401,F403


def best_alternate_window(primary, raw_alternate):
    """裁掉时间窗中串入的邻句字，只保留最像当前语音段的一小段。"""
    primary_content = content_only(primary)
    alternate_content = content_only(raw_alternate)
    if not primary_content or not alternate_content:
        return "", 0.0

    target_length = len(primary_content)
    minimum_length = max(1, target_length - 2)
    maximum_length = min(len(alternate_content), target_length + 2)
    best_text = ""
    best_score = 0.0
    for window_length in range(minimum_length, maximum_length + 1):
        for start in range(0, len(alternate_content) - window_length + 1):
            window = alternate_content[start : start + window_length]
            text_similarity = SequenceMatcher(
                None, primary_content, window, autojunk=False
            ).ratio()
            phonetic_similarity = SequenceMatcher(
                None,
                phonetic_text(primary_content),
                phonetic_text(window),
                autojunk=False,
            ).ratio()
            # 除非明显更像，否则优先保留与主识别接近的完整句长。
            length_penalty = abs(window_length - target_length) * 0.060
            score = (
                max(text_similarity, phonetic_similarity) * 0.75
                + min(text_similarity, phonetic_similarity) * 0.25
                - length_penalty
            )
            if score > best_score:
                best_score = score
                best_text = window
    return best_text, best_score


LEGITIMATE_REPEATED_VOCALS = set("哈啊嗯哦嘿呵呜啦哎呀")


def load_glossary():
    if not os.path.exists(GLOSSARY_PATH):
        print("   未找到 glossary.txt，本次不使用专名参考。")
        return []

    # glossary.txt 是用户可编辑文件，Windows 记事本可能以 GBK/GB18030 保存；
    # 严格 UTF-8 解码失败会中断整个校对阶段，这里按常见编码逐级回退。
    raw = open(GLOSSARY_PATH, "rb").read()
    text = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        print("   [警告] glossary.txt 无法按 UTF-8/GBK 解码，使用替换字符继续。")
        text = raw.decode("utf-8", errors="replace")
    terms = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    if len(terms) > 200:
        print("   [警告] glossary.txt 超过 200 行，本次只读取前 200 行。")
        terms = terms[:200]
    print(f"   已读取 {len(terms)} 个弱参考专名。")
    return terms


def load_content_context(media_title=""):
    """按本次弹窗选择生成背景；不再要求剪辑者逐期修改文本文件。"""
    if not RUNTIME_GAME_NAME:
        context = (
            "普通中文直播、对话或游戏视频。不要沿用任何旧游戏的角色、技能或机制词；"
            "只根据本期声音证据校对普通同音字，无法确认时保留 MOSS 主稿。"
            f"素材标题：{media_title}。"
        )
    elif RUNTIME_ENABLE_DOMAIN_TERMS:
        context = (
            f"当前素材与《{RUNTIME_GAME_NAME}》有关。可联网核对该游戏的官方角色、生物、"
            "技能、机制、队伍和战斗术语；只在读音、上下文和多处证据共同支持时修正，"
            f"无法确认时保留 MOSS 主稿。素材标题：{media_title}。"
        )
    else:
        context = (
            f"当前素材与《{RUNTIME_GAME_NAME}》有关，但游戏名只作为弱背景；"
            "本次未启用联网术语增强，不要主动套用角色、技能或机制词，"
            f"无法确认时保留 MOSS 主稿。素材标题：{media_title}。"
        )
    print(f"   [项目背景] {context}")
    return context


def load_verified_game_terms():
    """从所选游戏的结构化配置读取核验词，不要求剪辑者修改 TXT。"""
    if not RUNTIME_ENABLE_DOMAIN_TERMS:
        print("   [游戏词表] 本次未启用，不读取游戏专名配置。")
        return []
    terms = active_profile_terms()
    if not terms:
        print(
            f"   [游戏词表] 《{RUNTIME_GAME_NAME}》没有本地核验表；"
            "仅使用联网高置信候选与本地安全门。"
        )
        return []
    print(f"   已读取 {len(terms)} 个《{RUNTIME_GAME_NAME}》核验游戏词。")
    return terms


def repair_with_contextual_profile_aliases(segments):
    """短日常词只有在独立 ASR 明确写出目标专名时才替换。"""
    alias_map = active_contextual_alias_map()
    if not alias_map:
        return segments
    changes = []
    for segment in segments:
        references = [
            content_only(value)
            for value in (
                segment.firered_text,
                segment.qwen_asr_text,
                segment.firered_llm_text,
                segment.alternate_text,
            )
            if content_only(value)
        ]
        for source, target in alias_map.items():
            if source not in content_only(segment.text):
                continue
            exact_support = sum(target in value for value in references)
            if exact_support < 1:
                continue
            before = segment.text
            segment.text = clean_subtitle_text(segment.text.replace(source, target))
            if segment.text != before:
                changes.append((source, target))
    if changes:
        sample = "、".join(f"{source}→{target}" for source, target in changes[:12])
        print(f"   [语境术语修正] 独立 ASR 支持 {len(changes)} 处；示例：{sample}。")
    return segments


def repair_with_verified_game_terms(segments, verified_terms):
    """用核验词+读音+独立 ASR 支持修专名；无证据时绝不猜。"""
    changes = []
    contextual_aliases = active_contextual_alias_map()
    terms = sorted(
        {content_only(term) for term in verified_terms if content_only(term)},
        key=len,
        reverse=True,
    )
    for segment in segments:
        for _ in range(3):
            text = content_only(segment.text)
            references = [
                content_only(value)
                for value in (
                    segment.firered_text,
                    segment.qwen_asr_text,
                    segment.firered_llm_text,
                )
                if content_only(value)
            ]
            best = None
            for target in terms:
                target_sound = phonetic_text(target)
                exact_reference_support = (
                    target not in text and any(target in value for value in references)
                )
                for length in range(max(2, len(target) - 1), len(target) + 2):
                    for start in range(0, len(text) - length + 1):
                        source = text[start : start + length]
                        if (
                            source in terms
                            or source == target
                            or source in target
                            or target in source
                        ):
                            continue
                        source_sound = phonetic_text(source)
                        similarity = SequenceMatcher(
                            None,
                            source_sound,
                            target_sound,
                            autojunk=False,
                        ).ratio()
                        independent_support = exact_reference_support and similarity >= 0.76
                        contextual_target = contextual_aliases.get(source) == target
                        near_exact_official = (
                            len(source) == len(target)
                            and similarity >= 0.96
                            and target[-1:] in GLOBAL_DOMAIN_TERM_SUFFIXES
                            and not contextual_target
                        )
                        if not (independent_support or near_exact_official):
                            continue
                        candidate = (
                            int(independent_support),
                            similarity,
                            len(target),
                            -start,
                            start,
                            source,
                            target,
                            "独立ASR+核验词" if independent_support else "严格近音+核验词",
                        )
                        if best is None or candidate[:4] > best[:4]:
                            best = candidate
            if best is None:
                break
            _, similarity, _, _, start, source, target, basis = best
            before = segment.text
            # segment.text 已被 normalize 成紧凑正文，content_only 的位置在这里一致。
            segment.text = clean_subtitle_text(
                text[:start] + target + text[start + len(source) :]
            )
            changes.append(
                (segment.segment_id, source, target, similarity, basis, before, segment.text)
            )
    if changes:
        sample = "、".join(
            f"{source}→{target}"
            for _, source, target, _, _, _, _ in changes[:12]
        )
        print(f"   [核验词修正] 共 {len(changes)} 处；示例：{sample}。")
    return segments


# 兼容门面：同上，保持在配置区之后导入，请勿上移或改顺序。
from twobyteasr.correction import *  # noqa: F401,F403
from twobyteasr.segmentation import *  # noqa: F401,F403
from twobyteasr.timing import *  # noqa: F401,F403
from twobyteasr.output import *  # noqa: F401,F403
from twobyteasr.speakers import (
    host_voiceprint_status_summary,
    load_host_voiceprint_registry,
)

def run_startup_self_test():
    """Run the startup guards against this facade's current settings/state."""
    from twobyteasr.startup_selftest import run_startup_self_test as run_checks
    return run_checks(sys.modules[__name__])
