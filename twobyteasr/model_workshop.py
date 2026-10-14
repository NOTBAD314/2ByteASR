"""Warm, model-aware workshop used by the PySide6 desktop shell.

The workshop intentionally owns presentation and orchestration only. Runtime
backend validation remains in ``twobyteasr.ui.persist_asr_configuration`` and
downloads remain in ``scripts/download_models.ps1``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import QObject, QPoint, QProcess, QProcessEnvironment, QRectF, QSettings, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPalette, QTextCursor
from PySide6.QtWidgets import QFrame  # for dim backdrop on technical dialog
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from twobyteasr.download_sources import (
    classify_error_text,
    user_facing_error,
    user_facing_source_choices,
    DownloadSourceError,
)

from twobyteasr.i18n import apply_ui_language, current_language, translate, ui_literal
from twobyteasr.llm_config import resolve_api_key
from twobyteasr.model_storage import ModelStorageDialog
from twobyteasr.processes import popen_hidden_subprocess, run_hidden_subprocess
from twobyteasr.ui_navigation import (NAVIGATION_QSS, WorkspaceNavigation, style_workspace_page_title,
                                      style_workspace_sidebar_heading)
from twobyteasr.ui_theme import WORKSHOP_TOKENS
from twobyteasr.themed_icons import install_themed_icon
from twobyteasr.ui_widgets import CategoryChip, PillLabel, StatusBadge
from twobyteasr.model_task_metadata import (
    ModelCopy, MODEL_COPY, COMPARISON_NOTE, SPEED_NOTE, SIZE_NOTE, task_for,
)

from .i18n import bind_text

from .i18n import tr


GUI_PROFILE_ENABLED = os.environ.get("TWOBYTEASR_GUI_PROFILE") == "1"


def _play_download_result_sound(ok: bool) -> None:
    """Play one semantic system sound for a final model-download result."""
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_OK if ok else winsound.MB_ICONHAND)
    except Exception:
        from PySide6.QtWidgets import QApplication

        QApplication.beep()


class _HiddenProcessBridge(QObject):
    """QProcess-compatible child bridge; Mac preparation owns a process group."""

    readyReadStandardOutput = Signal()
    finished = Signal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cwd = ""
        self._environment = QProcessEnvironment.systemEnvironment()
        self._process = None
        self._state = QProcess.ProcessState.NotRunning
        self._output = bytearray()
        self._output_lock = threading.Lock()
        self._started = threading.Event()

    def setProcessChannelMode(self, _mode) -> None:
        return

    def setWorkingDirectory(self, path: str) -> None:
        self._cwd = str(path or "")

    def setProcessEnvironment(self, environment: QProcessEnvironment) -> None:
        self._environment = environment

    def processEnvironment(self) -> QProcessEnvironment:
        return self._environment

    def state(self):
        return self._state

    def processId(self) -> int:
        return int(getattr(self._process, "pid", 0) or 0)

    def start(self, program: str, arguments) -> None:
        if self._state != QProcess.ProcessState.NotRunning:
            return
        self._state = QProcess.ProcessState.Starting
        self._started.clear()
        environment = {
            key: self._environment.value(key)
            for key in self._environment.keys()
        }
        try:
            self._process = popen_hidden_subprocess(
                [str(program), *(str(value) for value in arguments)],
                purpose="model workshop download",
                cwd=self._cwd or None,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                **({'start_new_session': True} if sys.platform == 'darwin' else {}),
            )
        except OSError:
            self._process = None
            self._state = QProcess.ProcessState.NotRunning
            self._started.set()
            return
        self._state = QProcess.ProcessState.Running
        self._started.set()
        threading.Thread(
            target=self._drain_output,
            name="model-download-output",
            daemon=True,
        ).start()

    def waitForStarted(self, timeout_ms: int) -> bool:
        self._started.wait(max(0, timeout_ms) / 1000.0)
        return self._state == QProcess.ProcessState.Running

    def readAllStandardOutput(self):
        with self._output_lock:
            value = bytes(self._output)
            self._output.clear()
        return value

    def terminate(self) -> None:
        if self._process is not None and self._process.poll() is None:
            if sys.platform == 'darwin':
                import signal
                try:
                    os.killpg(self._process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            else:
                self._process.terminate()

    def kill(self) -> None:
        if self._process is not None and self._process.poll() is None:
            if sys.platform == 'darwin':
                import signal
                try:
                    os.killpg(self._process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                self._process.kill()

    def waitForFinished(self, timeout_ms: int) -> bool:
        process = self._process
        if process is None:
            return True
        try:
            process.wait(timeout=max(0, timeout_ms) / 1000.0)
        except subprocess.TimeoutExpired:
            return False
        return True

    def _drain_output(self) -> None:
        process = self._process
        if process is None:
            return
        stream = process.stdout
        try:
            while True:
                chunk = stream.read(4096) if stream is not None else b""
                if not chunk:
                    break
                with self._output_lock:
                    self._output.extend(chunk)
                self.readyReadStandardOutput.emit()
            exit_code = int(process.wait())
        except Exception:
            exit_code = int(process.poll() or 1)
        self._state = QProcess.ProcessState.NotRunning
        status = (
            QProcess.ExitStatus.NormalExit
            if exit_code >= 0
            else QProcess.ExitStatus.CrashExit
        )
        self.finished.emit(exit_code, status)

# Prefer external traceable metadata; fall back to embedded profiles for resilience.
try:
    from twobyteasr.model_evaluation_metadata import get_profile as _get_eval_profile  # type: ignore
except Exception:
    _get_eval_profile = None  # type: ignore

# Verified same-protocol benchmark groups → relative scores (1-100).
# Pure data + pure functions; snapshot ships with the app (offline-safe).
from twobyteasr.model_benchmarks import (
    API_MODEL_ALIASES as _BENCHMARK_API_ALIASES,
    DEFAULT_SCENE as _DEFAULT_BENCHMARK_SCENE,
    SCENES as _BENCHMARK_SCENES,
    assert_primary_groups_unique as _assert_primary_groups_unique,
    best_score as _benchmark_best_score,
    groups_for_model as _benchmark_groups_for_model,
    reference_api_model as _benchmark_reference_api_model,
    reference_entry as _benchmark_reference_entry,
    reference_gap as _benchmark_reference_gap,
    scene_label as _benchmark_scene_label,
    secondary_record as _benchmark_secondary_record,
    source_type_label as _benchmark_source_type_label,
)

try:
    _assert_primary_groups_unique()
except Exception:  # pragma: no cover - data invariant guard
    raise


def _auto_stage_enabled(model, runtime_settings) -> bool:
    """Installed helpers run unless the user turned them off (2026-10-14)."""
    if model.key == "ja_ctc_aligner":
        from .ctc_alignment import enabled
        return enabled(runtime_settings if isinstance(runtime_settings, dict) else None)
    return True


def _set_auto_stage_enabled(model, value: bool, runtime_settings) -> None:
    if model.key == "ja_ctc_aligner":
        from .ctc_alignment import set_enabled
        set_enabled(value, runtime_settings)


@dataclass(frozen=True)
class WorkshopModel:
    key: str
    role: str
    name: str
    monogram: str
    summary: str
    mode: str
    size: str
    proof: str
    description: str
    capabilities: tuple[tuple[str, int], ...]
    extra_roles: tuple[str, ...] = ()
    install_keys: tuple[str, ...] = ()
    download_key: str | None = None
    available: bool = True
    runtime_available: bool = True
    runtime_roles: tuple[str, ...] = ()
    api_preset: str | None = None
    logo_asset: str | None = None
    icon_name: str = "fa5s.wave-square"
    icon_color: str = "#577d4d"
    icon_background: str = "#e4ebdd"
    variants: tuple[str, ...] = ()
    # P1-10: explicit supported languages for badges (concise, user-facing)
    languages: tuple[str, ...] = ()  # e.g. ("中文",) or ("多语言", "中文", "English")
    # P1-11: soft "recommended for role" marker (subtle green border + small tag)
    recommended: bool = False
    # Model capability describes what trustworthy evidence the checkpoint can
    # produce. Adapter bindings separately describe what this build has
    # actually verified and wired into each pipeline role.
    asr_capabilities: tuple[str, ...] = ()
    adapter_bindings: tuple[tuple[str, str], ...] = ()
    # Optional override for future pure diarization / review / translation models.
    # Existing models derive their task from actual checkpoint capabilities.
    model_type: str = ""
    # Models a pipeline step uses automatically once installed (no role to
    # select): the installed state shows this text instead of "接入中".
    auto_stage: str = ""
    # Host platforms the model can run on ("darwin-arm64"); empty = the
    # existing per-platform rules apply.
    platforms: tuple[str, ...] = ()


MODELS = (
    WorkshopModel('spark_asr_v2','api','Spark-ASR-2.0','S2',
        '讯飞原生 WSS · 中英听写 V2','在线 · AppID + APIKey + APISecret','不占本地空间',
        '协议接入；真实服务验证待完成',
        '单会话不超过 60 秒，长音频连续切块，动态修订替换。没有原生说话人能力；时间证据不足时由所选对齐模型补充。可保留已有字幕的说话人标签。',(),
        api_preset='spark_asr_v2',asr_capabilities=('ASR_TEXT',),adapter_bindings=(('primary','api'),('review','api'))),
    # 2026-10-13: Qwen Cloud, the official international Qwen API (no workspace
    # host). 2026-10-14 (ADR 0112): regular use needs the user's own OSS; the
    # provider's temporary upload is a labelled trial only.
    WorkshopModel('qwen_cloud_filetrans','api','Qwen Cloud｜录音文件识别','QC',
        '长文件异步 · Qwen-Audio-3.1 或 Qwen3-ASR','在线 · Qwen Cloud API Key + 自己的 OSS','不占本地空间',
        '不需要显卡与本地模型；正式使用需要自己的 OSS 私有存储',
        'Qwen 官方国际站（home.qwencloud.com）的录音文件识别：Qwen-Audio-3.1 返回字/词级时间与说话人，Qwen3-ASR 返回字/词级时间（无说话人）。音频先传到你自己的 OSS 私有存储，用限时签名链接交给服务商，结果保存后删除；服务商临时上传只供试用（48 小时失效，官方说明勿用于生产）。单文件不超过 12 小时。Key 与阿里云百炼（中国站）的不能互换。超时不会自动重新付费提交。',(),
        api_preset='qwen_cloud_filetrans',asr_capabilities=('ASR_TEXT','TIMESTAMP','DIARIZATION'),adapter_bindings=(('primary','api'),('review','api'))),
    WorkshopModel('qwen31_filetrans','api','阿里云百炼｜录音文件识别','QF',
        '长文件异步 · Qwen3-ASR 或 Qwen-Audio-3.1','在线 · 百炼 Key + API Host','不占本地空间',
        '不需要显卡；正式使用需要自己的 OSS 私有存储',
        '同一个百炼 Key 下两个模型：Qwen3-ASR-Flash（字/词级时间，无说话人，不支持热词）与 Qwen-Audio-3.1（字/词级时间与说话人，支持热词）。单文件不超过 12 小时；说话人区分官方建议 2 小时内。音频先传到你自己的 OSS 私有存储，用限时签名链接交给百炼，结果成功保存后删除；百炼临时上传只供试用（48 小时失效，官方说明勿用于生产）。超时不会自动重新付费提交。',(),
        api_preset='qwen31_filetrans',asr_capabilities=('ASR_TEXT','TIMESTAMP','DIARIZATION'),adapter_bindings=(('primary','api'),('review','api'))),
    # 2026-10-13: cloud MOSS on the MOSI platform; independent of the local
    # "moss" card (no shared settings, key or job state).
    WorkshopModel('mosi_moss_pro','api','MOSS-Transcribe-Diarize Pro 云端','MP',
        '云端多人转写 · 本地文件直传','在线 · 只需 MOSI API Key','不占本地空间',
        '不需要显卡与本地模型；句段级时间',
        'MOSI 平台的 moss-transcribe-diarize-pro：上传本次音频，返回文字、句段起止时间与说话人。单次最长 60 分钟，更长自动分段且各段说话人不合并。只有句段时间；需要按字剪辑时可再配本地对齐模型。按音频时长计费（官方价格页 ¥2.00/小时，2026-10-13 核对）。',(),
        api_preset='mosi_moss_pro',asr_capabilities=('ASR_TEXT','TIMESTAMP','DIARIZATION'),adapter_bindings=(('primary','api'),)),
    WorkshopModel(
        "moss",
        "primary",
        "MOSS-Transcribe-Diarize",
        "MO",
        "中文长音频 · 说话人区分",
        "本地 · NVIDIA CUDA",
        "约 1.7 GB",
        "相对参考（官方未提供统一跨模型基准）：准确度优先",
        "适合中文长视频与多人内容，作为第一遍骨架保留完整语义，并提供稳定的说话人区分。",
        (("中文长音频", 88), ("多人区分", 82), ("运行速度", 61)),
        (),
        ("moss", "firered_vad", "speaker_embedding"),
        "moss",
        logo_asset="openmoss.png",
        icon_name="fa5s.wave-square",
        icon_color="#ffffff",
        icon_background="#6f8f63",
        languages=("中文",),
        recommended=True,  # 主力转写推荐
        asr_capabilities=("ASR_TEXT", "DIARIZATION"),
        adapter_bindings=(("primary", "moss"),),
    ),
    WorkshopModel(
        "firered",
        "timeline",
        "FireRedASR2-AED",
        "Fi",
        "中文与方言 · 可独立生成字幕",
        "本地 · NVIDIA CUDA",
        "约 4.4 GB",
        "相对参考（官方未提供统一跨模型基准）：时间轴优秀",
        "负责字级首尾边界，也可以单独生成中文与方言字幕。与 MOSS 组合时能明显改善时间轴。",
        (("字级时间轴", 93), ("中文方言", 85), ("运行速度", 69)),
        (),
        ("firered_aed",),
        "firered_aed",
        logo_asset="firered.png",
        icon_name="fa5s.fire",
        icon_color="#ffffff",
        icon_background="#e86659",
        languages=("中文", "方言"),
        recommended=True,  # 时间轴推荐
        asr_capabilities=("ASR_TEXT", "TIMESTAMP"),
        adapter_bindings=(("primary", "firered"), ("timeline", "local")),
    ),
    # remaining models get languages too (see below)
    WorkshopModel(
        "qwen_local",
        "review",
        "Qwen3-ASR 1.7B",
        "Qw",
        "多语言 · 词汇与文字复核参考",
        "本地 · NVIDIA CUDA",
        "约 4.7 GB",
        "相对参考（官方未提供统一跨模型基准）：文字精度高",
        "多语言语音转写模型，可独立识别字幕；在组合流程中重新听音频，为每个片段提供独立文字与词汇证据。",
        (("文字精度", 92), ("多语言", 82), ("运行速度", 58)),
        (),
        ("qwen_asr",),
        "qwen_asr",
        logo_asset="qwen.png",
        icon_name="fa5s.magic",
        icon_color="#ffffff",
        icon_background="#7967d8",
        languages=("多语言",),
        recommended=True,  # 文字复核推荐（本地）
        asr_capabilities=("ASR_TEXT", "LANGUAGE_ID"),
        adapter_bindings=(("primary", "qwen_local"), ("review", "local")),
    ),
    WorkshopModel(
        "firered_llm",
        "primary",
        "FireRedASR2-LLM",
        "FL",
        "中文普通话 / 方言 / English · 高精度 LLM ASR",
        "本地 · 独立 FireRed LLM Runtime",
        "预计下载 17.57 GiB",
        "官方中文与方言精度突出 · 单段最多 40 秒",
        "8B+ Encoder-Adapter-LLM 模型。独立 Runtime 已通过 Windows CUDA 双 fixture 验证，可作为主力或文字复核。",
        (("准确度", 100), ("方言", 94), ("运行速度", 70)),
        (),
        ("firered_llm",),
        "firered_llm",
        runtime_available=True,
        runtime_roles=("primary", "review"),
        logo_asset="firered.png",
        icon_name="fa5s.fire",
        icon_color="#ffffff",
        icon_background="#b75f55",
        languages=("中文", "方言", "English"),
        asr_capabilities=("ASR_TEXT",),
        adapter_bindings=(("primary", "firered_llm"), ("review", "firered_llm")),
    ),
    WorkshopModel(
        "glm_asr_nano",
        "primary",
        "GLM-ASR-Nano-2512",
        "GL",
        "中文 / English / 粤语与方言 · 低音量鲁棒",
        "本地 · 独立 GLM Runtime",
        "预计下载 4.21 GiB",
        "1.5B 官方架构 · OpenASR 评测另列",
        "GLM 的轻量语音识别模型。使用独立 Python 3.12 与 Transformers 5 运行库，支持本地中文、粤语与英文转写。",
        (("准确度", 95), ("多语言", 88), ("运行速度", 90)),
        (),
        ("glm_asr_nano",),
        "glm_asr_nano",
        runtime_available=True,
        runtime_roles=('primary',),
        adapter_bindings=(('primary','glm_asr_nano'),),
        logo_asset="zai.png",
        icon_name="fa5s.wave-square",
        icon_color="#ffffff",
        icon_background="#477f72",
        languages=("中文", "粤语", "English", "17种语言"),
        asr_capabilities=("ASR_TEXT", "LANGUAGE_ID"),
    ),
    WorkshopModel(
        "canary_qwen",
        "primary",
        "Canary-Qwen-2.5B",
        "NQ",
        "English ASR · 标点与大小写",
        "本地 · 独立 NVIDIA NeMo Runtime",
        "预计下载 4.77 GiB",
        "英语 OpenASR 榜单同表最佳（Mean WER 5.63% / RTFx 418）",
        "FastConformer + Qwen 的英文语音模型。自动准备独立 NeMo 运行库、模型和 tokenizer，并通过真实样本任务验证；不支持中文。",
        (("英文准确度", 97), ("英文速度", 100), ("多语言", 12)),
        (),
        ("canary_qwen", "canary_qwen_tokenizer"),
        "canary_qwen",
        runtime_available=True,
        runtime_roles=('primary',),
        adapter_bindings=(('primary','canary_qwen'),),
        logo_asset="nvidia.png",
        icon_name="fa5s.microchip",
        icon_color="#ffffff",
        icon_background="#6b8e3f",
        languages=("English",),
        asr_capabilities=("ASR_TEXT",),
    ),
    WorkshopModel(
        "omni_asr_llm_7b",
        "primary",
        "Omnilingual ASR LLM 7B",
        "Om",
        "1600+ 语言 · 高显存",
        "仅权重 · 原生 Windows 推理不支持",
        "预计下载 29.06 GiB",
        "超广语言覆盖 · 约 17 GiB BF16 显存",
        "Meta 的 7.8B 多语言 ASR。权重可校验下载，但上游 fairseq2 不支持原生 Windows，因此当前 Windows 版不能加载或推理。下载完成不会加入识别方案。",
        (("语言覆盖", 100), ("参考准确度", 92), ("运行速度", 25)),
        (),
        ("omni_asr_llm_7b",),
        "omni_asr_llm_7b",
        runtime_available=False,
        runtime_roles=(),
        logo_asset="meta.png",
        icon_name="fa5s.globe",
        icon_color="#ffffff",
        icon_background="#596f7c",
        languages=("1600+ 语言",),
        asr_capabilities=("ASR_TEXT", "LANGUAGE_ID"),
    ),
    WorkshopModel(
        "groq_api",
        "api",
        "Groq Whisper API",
        "Gq",
        "Whisper 云端加速 · OpenAI 转写协议",
        "在线 · 需 Groq API Key",
        "不占本地空间",
        "速度优先 · 支持短块复核",
        "使用 Groq 的 Whisper large-v3-turbo 转写接口，适合境外网络或已有 Groq 额度的用户。",
        (("运行速度", 96), ("多语言", 89), ("国内可达", 42)),
        api_preset="groq",
        logo_asset="groq.png",
        icon_name="fa5s.bolt",
        icon_color="#ffffff",
        icon_background="#d0774e",
        asr_capabilities=("ASR_TEXT", "LANGUAGE_ID"),
        adapter_bindings=(("primary", "api"), ("review", "api")),
    ),
    WorkshopModel(
        "openai_api",
        "api",
        "OpenAI Transcribe API",
        "OA",
        "通用多语言 · 支持上下文提示",
        "在线 · 需 OpenAI API Key",
        "不占本地空间",
        "通用能力强 · 境外服务",
        "使用 OpenAI 音频转写接口作为独立文字复核来源，适合已有 OpenAI API 的用户。",
        (("多语言", 93), ("文字精度", 89), ("国内可达", 35)),
        api_preset="openai",
        logo_asset="openai.png",
        icon_name="fa5s.microphone",
        icon_color="#ffffff",
        icon_background="#3f6f65",
        asr_capabilities=("ASR_TEXT", "LANGUAGE_ID"),
        adapter_bindings=(("primary", "api"), ("review", "api")),
    ),
    WorkshopModel(
        # 三十七轮：OpenRouter JSON input_audio + timestamp_granularities(word)
        # 字级时间戳通道（三十八轮起是 OpenRouter 唯一通道，旧 multipart 已删）。
        "mai_latest",
        "api",
        "MAI 2.1｜待服务商验证",
        "MA",
        "OpenRouter · 新版映射需验证",
        "在线 · 需 OpenRouter Key",
        "不占本地空间",
        "模型与原生能力待当前服务商验证",
        "MAI 2.1 的当前 OpenRouter 模型 ID 尚未获得服务商确认。旧 microsoft/mai-transcribe-2 不会冒充新版；请在配置中填写服务商确认的新版 ID。实际通道是否提供词时间戳、说话人和原样转写须逐项验证。",
        (),
        api_preset="openrouter_word",
        logo_asset=None,
        icon_name="fa5b.microsoft",
        icon_color="#ffffff",
        icon_background="#0078d4",
        languages=("多语言",),
        asr_capabilities=("ASR_TEXT", "LANGUAGE_ID"),
        adapter_bindings=(("primary", "api"), ("review", "api")),
    ),
    WorkshopModel(
        "custom_asr_api",
        "api",
        "OpenAI 兼容 ASR",
        "API",
        "自定义模型、地址与密钥",
        "在线或自托管 · OpenAI 音频协议",
        "取决于服务商",
        "兼容入口 · 用户自定义",
        "可连接实现 /v1/audio/transcriptions 的第三方或自托管服务；模型名、URL 与 Key 均可配置。",
        (("灵活性", 96), ("兼容性", 82), ("易用性", 68)),
        api_preset="custom",
        logo_asset="openai.png",
        icon_name="fa5s.code",
        icon_color="#ffffff",
        icon_background="#7b756d",
        languages=("多语言",),
        asr_capabilities=("ASR_TEXT", "LANGUAGE_ID"),
        adapter_bindings=(("primary", "api"), ("review", "api")),
    ),
    WorkshopModel(
        "sensevoice",
        "primary",
        "SenseVoice Small",
        "SV",
        "中文/粤语/英语/日语/韩语 · CPU 也可运行",
        "本地 · ModelScope / FunASR",
        "约 0.9 GB",
        "文字复核已接入 · 主力骨架待接入",
        "非自回归多语言模型，支持情感与音频事件识别；现在可作为本地文字复核证据。作为独立主力时暂不提供 MOSS 的多人区分。",
        (("运行速度", 96), ("中文粤语", 88), ("硬件友好", 91)),
        ("review",),
        ("sensevoice",),
        "sensevoice",
        runtime_available=True,
        runtime_roles=("review",),
        logo_asset="modelscope.png",
        icon_name="fa5s.volume-up",
        icon_color="#ffffff",
        icon_background="#7566ce",
        languages=("中文", "粤语", "English", "日本語", "한국어"),
        asr_capabilities=("ASR_TEXT", "LANGUAGE_ID"),
        adapter_bindings=(("primary", "sensevoice"), ("review", "sensevoice")),
    ),
    WorkshopModel(
        "paraformer",
        "primary",
        "Paraformer Large",
        "Pa",
        "中文长音频 · 支持热词",
        "本地 · ModelScope / Hugging Face",
        "约 1.0 GB",
        "中文时间轴已接入 · 主力骨架待接入",
        "FunASR 中文非自回归模型，可组合 VAD、标点和热词；现在可替换 FireRed 提供中文时间戳。独立主力转写仍在适配。",
        (("中文识别", 88), ("运行速度", 91), ("热词支持", 94)),
        ("timeline",),
        ("paraformer",),
        "paraformer",
        runtime_available=True,
        runtime_roles=("timeline",),
        logo_asset="modelscope.png",
        icon_name="fa5s.align-left",
        icon_color="#ffffff",
        icon_background="#438c9c",
        languages=("中文",),
        asr_capabilities=("ASR_TEXT", "TIMESTAMP"),
        adapter_bindings=(("primary", "paraformer"), ("timeline", "paraformer")),
    ),
    WorkshopModel(
        "whisper",
        "primary",
        "Whisper large-v3-turbo",
        "Wh",
        "多语言 · 通用内容",
        "本地",
        "约 1.6 GB",
        "多语种复核已接入 · 主力骨架待接入",
        "通用多语言模型，现在可替换 Qwen 提供独立文字复核证据；作为主力转写时暂不提供 MOSS 的多人说话人骨架。",
        (("多语言", 91), ("兼容性", 88), ("运行速度", 73)),
        ("timeline", "review"),
        ("whisper_turbo",),
        "whisper_turbo",
        runtime_available=True,
        runtime_roles=("timeline", "review"),
        logo_asset="openai.png",
        icon_name="fa5s.microphone",
        icon_color="#ffffff",
        icon_background="#3d4549",
        languages=("多语言",),
        asr_capabilities=("ASR_TEXT", "TIMESTAMP", "LANGUAGE_ID"),
        adapter_bindings=(
            ("primary", "whisper_turbo"),
            ("timeline", "whisper_turbo"),
            ("review", "whisper_turbo"),
        ),
    ),
    WorkshopModel(
        "qwen_aligner",
        "timeline",
        "Qwen3-ForcedAligner 0.6B",
        "Qa",
        "11 种语言 · 字/词级强制对齐",
        "本地 · NVIDIA CUDA 或 CPU（较慢）",
        "约 1.8 GB",
        "官方字词时间戳 · 已接入",
        "Qwen 官方强制对齐模型，可根据已有文字（MOSS、本地或云端识别）生成字级或词级时间戳；可直接替换 FireRed 作为多语种时间轴后端。没有 NVIDIA 显卡时用 CPU 运行，结果相同但更慢。",
        (("字词对齐", 94), ("多语言", 76), ("运行速度", 72)),
        (),
        ("qwen_aligner",),
        "qwen_aligner",
        runtime_available=True,
        logo_asset="qwen.png",
        icon_name="fa5s.magic",
        icon_color="#ffffff",
        icon_background="#8a78df",
        languages=("多语言", "11种"),
        asr_capabilities=("ALIGNMENT",),
        adapter_bindings=(("timeline", "qwen_aligner"),),
    ),
    WorkshopModel(
        "ja_ctc_aligner",
        "timeline",
        "日语 CTC 对齐模型",
        "Ja",
        "日语 · 句首时间校正",
        "本地 · ModelScope / Hugging Face",
        "约 1.3 GB",
        "日语识别自动使用 · 已接入",
        "wav2vec2 日语字符 CTC 模型，用于强制对齐日语字幕的句首：只在它与 Qwen 对齐器的实测起点相差 80 毫秒内时采用，句尾不改。安装后识别日语时自动执行，也可在字幕工作台时间轴右键对整个工程校正。",
        (("句首对齐", 80), ("日语", 85), ("运行速度", 80)),
        (),
        ("ja_ctc_aligner",),
        "ja_ctc_aligner",
        runtime_available=True,
        icon_name="fa5s.ruler-horizontal",
        icon_color="#ffffff",
        icon_background="#5f7fbf",
        languages=("日本語",),
        asr_capabilities=("ALIGNMENT",),
        auto_stage="已安装 · 日语识别时自动使用",
    ),
    WorkshopModel(
        "mlx_qwen3_asr_0_6b",
        "primary",
        "Qwen3-ASR 0.6B（Apple Silicon）",
        "Qm",
        "M 系列芯片 Mac 本地识别 · 不需要 NVIDIA",
        "本地 · Apple Silicon（MLX）",
        "约 1.0 GB",
        "社区 MLX 移植 · 兔白尚未在真 Mac 上验收",
        "Qwen3-ASR 0.6B 的 MLX 8-bit 版本（mlx-community），在 M 系列芯片的 Mac 上本地识别，不上传音频。它按语音段给出文字，不给字词时间，也不区分说话人；需要字词时间时，请同时安装“Qwen3 对齐模型（Apple Silicon）”。",
        (("运行速度", 86), ("文字精度", 74), ("硬件友好", 92)),
        (),
        ("mlx_qwen3_asr_0_6b",),
        "mlx_qwen3_asr_0_6b",
        runtime_available=True,
        logo_asset="qwen.png",
        icon_name="fa5s.microchip",
        icon_color="#ffffff",
        icon_background="#6f63c9",
        languages=("多语言", "中文", "日本語"),
        asr_capabilities=("ASR_TEXT", "LANGUAGE_ID"),
        adapter_bindings=(("primary", "mlx_qwen3_asr"),),
        platforms=("darwin-arm64",),
    ),
    WorkshopModel(
        "mlx_qwen3_asr_1_7b",
        "primary",
        "Qwen3-ASR 1.7B（Apple Silicon）",
        "QM",
        "M 系列芯片 Mac 本地识别 · 更准、更慢",
        "本地 · Apple Silicon（MLX）",
        "约 2.5 GB",
        "社区 MLX 移植 · 兔白尚未在真 Mac 上验收",
        "Qwen3-ASR 1.7B 的 MLX 8-bit 版本（mlx-community），比 0.6B 更准但更慢、占用更多内存。只按语音段给文字，不给字词时间，不区分说话人。",
        (("运行速度", 70), ("文字精度", 84), ("硬件友好", 80)),
        (),
        ("mlx_qwen3_asr_1_7b",),
        "mlx_qwen3_asr_1_7b",
        runtime_available=True,
        logo_asset="qwen.png",
        icon_name="fa5s.microchip",
        icon_color="#ffffff",
        icon_background="#5a4fb8",
        languages=("多语言", "中文", "日本語"),
        asr_capabilities=("ASR_TEXT", "LANGUAGE_ID"),
        adapter_bindings=(("primary", "mlx_qwen3_asr_1_7b"),),
        platforms=("darwin-arm64",),
    ),
    WorkshopModel(
        "mlx_qwen_aligner",
        "timeline",
        "Qwen3 对齐模型（Apple Silicon）",
        "Qa",
        "字/词级强制对齐 · 不是语音识别模型",
        "本地 · Apple Silicon（MLX）",
        "约 1.3 GB",
        "回执与 CUDA/CPU 版相同 · 尚未在真 Mac 上验收",
        "Qwen3-ForcedAligner 0.6B 的 MLX 8-bit 版本：只给已有文字（本地或云端识别的结果）配上字/词时间，它本身不会把语音转成文字。对齐在本机进行，不上传音频。",
        (("字词对齐", 92), ("多语言", 76), ("硬件友好", 90)),
        (),
        ("mlx_qwen_aligner",),
        "mlx_qwen_aligner",
        runtime_available=True,
        logo_asset="qwen.png",
        icon_name="fa5s.magic",
        icon_color="#ffffff",
        icon_background="#8a78df",
        languages=("多语言", "11种"),
        asr_capabilities=("ALIGNMENT",),
        adapter_bindings=(("timeline", "mlx_qwen_aligner"),),
        platforms=("darwin-arm64",),
    ),
    WorkshopModel(
        "funasr_nano",
        "primary",
        "Fun-ASR Nano 2512",
        "Fu",
        "多语言与中文方言 · LLM 驱动",
        "本地 · ModelScope / Hugging Face",
        "约 2.4 GB",
        "中文方言复核已接入 · 主力骨架待接入",
        "FunAudioLLM 的多语言识别模型，覆盖中文方言与多语种；现在可作为独立文字复核证据，主力多人骨架仍在适配。",
        (("中文方言", 92), ("多语言", 86), ("运行速度", 68)),
        ("review",),
        ("funasr_nano",),
        "funasr_nano",
        runtime_available=True,
        runtime_roles=("review",),
        logo_asset="modelscope.png",
        icon_name="fa5s.wave-square",
        icon_color="#ffffff",
        icon_background="#4c9a8c",
        languages=("多语言", "中文方言"),
        asr_capabilities=("ASR_TEXT", "LANGUAGE_ID"),
        adapter_bindings=(("primary", "funasr_nano"), ("review", "funasr_nano")),
    ),
)


ROLE_CAPABILITY_REQUIREMENTS = {
    'speaker': (('DIARIZATION',),),
    "primary": (("ASR_TEXT",),),
    "review": (("ASR_TEXT",),),
    "timeline": (("TIMESTAMP",), ("ALIGNMENT",)),
}


def _capability_supports_role(capabilities: tuple[str, ...], role: str) -> bool:
    available = set(capabilities)
    alternatives = ROLE_CAPABILITY_REQUIREMENTS.get(role, ())
    return any(set(requirement) <= available for requirement in alternatives)


def _adapter_backend(model: WorkshopModel, role: str) -> str | None:
    return dict(model.adapter_bindings).get(role)


MLX_DOWNLOAD_KEYS = frozenset({"mlx_qwen3_asr_0_6b", "mlx_qwen3_asr_1_7b", "mlx_qwen_aligner"})
# MOSS / FireRed on the Apple GPU (2026-10-14): prepared by
# macos_model_prepare.prepare_local; an Intel Mac has no Apple GPU.
MAC_GPU_DOWNLOAD_KEYS = frozenset({"moss", "firered_aed"})
MAC_GPU_INSTALL_KEYS = frozenset({"moss", "firered_vad", "speaker_embedding", "firered_aed"})
MAC_GPU_MODE = "本地 · Apple 芯片 GPU（MPS）· 建议 16 GB 以上内存"


def model_mode_text(model: WorkshopModel) -> str:
    """How the model runs on this computer (the Windows text stays as written)."""
    if sys.platform == 'darwin' and model.download_key in MAC_GPU_DOWNLOAD_KEYS:
        return MAC_GPU_MODE
    return model.mode


def _host_platform_tag() -> str:
    import platform
    machine = platform.machine().lower()
    return f"{sys.platform}-{ {'aarch64': 'arm64', 'amd64': 'x86_64'}.get(machine, machine) }"


def _model_roles(model: WorkshopModel) -> tuple[str, ...]:
    return tuple(
        role
        for role in ("primary", "timeline", "review")
        if _capability_supports_role(model.asr_capabilities, role)
    )


def _browser_groups(model: WorkshopModel) -> tuple[str, ...]:
    """Browse-tab membership: online API cards live only in 「在线 API」.

    _model_roles keeps capability semantics (the role picker still offers
    API models for primary/review). The browser tabs are a deployment-mode
    grouping: API cards used to leak into 主力转写/文字复核 via capability
    derivation while the 在线 API tab stayed empty because nothing ever
    produced the "api" role (三十二轮用户实录）。
    """

    if model.api_preset:
        return ("api",)
    return _model_roles(model)


def _api_combo_label(models: dict) -> tuple[str, bool]:
    """当前 API 组合标签：服务商 · 模型（三十三轮：在线 API 要能看出当前用的谁）。"""

    from .ui import ASR_API_PRESETS
    from .llm_config import read_asr_api_key

    provider = str(models.get("qwen_asr_api_provider", "qwen31_filetrans") or "qwen31_filetrans")
    model_id = str(models.get("qwen_asr_api_model", "") or "")
    preset = ASR_API_PRESETS.get(provider, {})
    # 组合卡窄列：短服务商名 + 模型 id 最后一段（microsoft/mai-transcribe-2 →
    # OpenRouter · mai-transcribe-2），完整形态在 api tab 副标题显示。
    label = translate(str(preset.get("short") or preset.get("label") or provider), current_language())
    ready = bool(read_asr_api_key(provider, str(models.get("qwen_asr_api_url", "") or ""))[0])
    short_model = model_id.rsplit("/", 1)[-1]
    text = f"{label} · {short_model}" if short_model else label
    return (text[:30] + "…") if len(text) > 32 else text, ready


def _runtime_role_available(model: WorkshopModel, role: str) -> bool:
    return bool(
        model.runtime_available
        and _capability_supports_role(model.asr_capabilities, role)
        and _adapter_backend(model, role)
    )


def _stars(score: int) -> str:
    """Kept for compatibility tests. Visible cards use RatingBar, not black dots."""
    clamped = max(1, min(int(score), 5))
    return "●" * clamped + "○" * (5 - clamped)


CANONICAL_MODEL_ORDER = (
    'qwen_cloud_filetrans','spark_asr_v2','qwen31_filetrans','mosi_moss_pro',
    "moss",
    "firered",
    "qwen_local",
    "firered_llm",
    "glm_asr_nano",
    "canary_qwen",
    "omni_asr_llm_7b",
    "sensevoice",
    "paraformer",
    "whisper",
    "funasr_nano",
    "qwen_aligner",
    "ja_ctc_aligner",
    "mlx_qwen3_asr_0_6b",
    "mlx_qwen3_asr_1_7b",
    "mlx_qwen_aligner",
    "groq_api",
    "openai_api",
    "mai_latest",
    "custom_asr_api",
)

_SCENE_COPY = {key: copy.summary for key, copy in MODEL_COPY.items()}

_RATING_WORDS = {1: "低", 2: "偏低", 3: "中", 4: "高", 5: "很高"}
_RATING_WORDS_EN = {1: "low", 2: "below average", 3: "medium", 4: "high", 5: "very high"}


# Structured technical notes are intentionally concise and conservative.  The
# model card stays newcomer-friendly; this data powers the opt-in detail panel
# with operating constraints and the role each model actually plays here.
_TECHNICAL_PROFILES = {
    "moss": {
        "purpose": "中文长音频的第一遍转写与说话人区分。",
        "strengths": "先保留完整语义，再向后续时间轴与文字复核提供稳定骨架。",
        "limits": "需要 NVIDIA CUDA；说话人标签是区分依据，不等同于自动识别真实姓名。",
        "io": "输入本地音频；输出初稿文本、分段和说话人证据。",
        "source": "2ByteASR 内置 MOSS 转写与说话人工作进程。",
        "url": "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize",
        "official": {
            "developer": "OpenMOSS",
            "series": "MOSS-Transcribe-Diarize",
            "params": "0.9B（端到端长音频多说话人模型）",
            "languages": ["中文"],
            "repo": "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize",
        },
        "capabilities": ["长音频", "说话人区分", "时间戳", "事件感知"],
        "benchmarks": [
            # Traceable from MOSS-Audio Technical Report (arXiv) Table 5 dataset-level CER.
            # We record as "reported CER on internal long-form multi-speaker sets" with conditions.
            {"metric": "CER", "value": "按 MOSS-Audio 技术报告 Table 5 在特定长音频/多说话人集合上报告", "dataset": "内部长音频多说话人集合", "condition": "端到端联合建模（转写+说话人+事件）", "hardware": "官方测试环境", "source": "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize"},
        ],
        "resources": "官方未提供统一硬件需求（2ByteASR 要求 NVIDIA CUDA）",
        "twobyte": {
            "position": "主力转写",
            "reason": "中文长音频 + 说话人区分，适合作为第一遍主力转写保留完整语义骨架。",
        },
    },
    "firered": {
        "purpose": "中文/方言语音识别与细粒度时间轴。",
        "strengths": "擅长补足字词首尾边界，适合作为 MOSS 初稿之后的时间轴阶段。",
        "limits": "本机运行需要 CUDA；时间戳质量仍会受原始音频、多人重叠说话影响。",
        "io": "输入音频；输出识别文字与可用于字幕切分的时间边界。",
        "source": "FireRedASR 官方项目。",
        "url": "https://github.com/FireRedTeam/FireRedASR",
        "hf": "https://huggingface.co/FireRedTeam/FireRedASR2-AED",
        "official": {
            "developer": "FireRedTeam",
            "series": "FireRedASR / FireRedASR2-AED",
            "params": "AED 模型（工业级全流程 ASR）",
            "languages": ["中文", "方言", "English"],
            "repo": "https://github.com/FireRedTeam/FireRedASR",
        },
        "capabilities": ["时间戳", "长音频", "方言", "歌词识别"],
        "benchmarks": [
            # FireRedTeam GitHub claims new SOTA on public Mandarin ASR benchmarks.
            # No exact CER numbers in primary README; record the SOTA claim with conditions.
            {"metric": "SOTA claim", "value": "公开 Mandarin ASR benchmarks 新 SOTA", "dataset": "公开中文 ASR benchmark", "condition": "官方报告（Mandarin ASR）", "hardware": "官方测试环境", "source": "https://github.com/FireRedTeam/FireRedASR"}
        ],
        "resources": "官方未提供统一硬件需求（2ByteASR 要求 NVIDIA CUDA 用于本地）",
        "twobyte": {
            "position": "字幕时间轴",
            "reason": "时间边界能力更适合第二阶段字幕时间轴。",
        },
    },
    "qwen_local": {
        "purpose": "多语言文字复核与术语证据补充。",
        "strengths": "对专名、多语言片段和文字差异提供第二路本地参考。",
        "limits": "下载体积与显存占用较高；它在本项目中是复核角色，不替代完整任务流程。",
        "io": "输入已分段的音频/文本上下文；输出文字候选和复核证据。",
        "source": "Qwen3-ASR 官方发布版本与 2ByteASR 本地适配。",
        "url": "https://github.com/QwenLM/Qwen3-ASR",
        "hf": "https://huggingface.co/Qwen/Qwen3-ASR-1.7B",
        "official": {
            "developer": "Qwen Team / Alibaba",
            "series": "Qwen3-ASR",
            "params": "1.7B",
            "languages": ["多语言"],
            "repo": "https://github.com/QwenLM/Qwen3-ASR",
        },
        "capabilities": ["多语言", "文字精度"],
        "benchmarks": [],
        "resources": "官方未提供统一硬件需求（本地运行需要 CUDA，较高显存）",
        "twobyte": {
            "position": "文字复核",
            "reason": "文字准确度与专名复核能力适合作为第三阶段复核。",
        },
    },
    "sensevoice": {
        "purpose": "轻量多语言语音识别与文字复核。",
        "strengths": "CPU 也可使用，对中文、粤语和常见多语种较友好。",
        "limits": "当前不提供 MOSS 的多人说话人骨架；更适合做独立文字证据。",
        "io": "输入音频；输出多语言文字结果及可选事件/情感信息。",
        "source": "FunAudioLLM SenseVoice 官方项目。",
        "url": "https://github.com/FunAudioLLM/SenseVoice",
        "hf": "https://huggingface.co/FunAudioLLM/SenseVoiceSmall",
        "official": {
            "developer": "FunAudioLLM (Alibaba)",
            "series": "SenseVoiceSmall",
            "params": "Small",
            "languages": ["中文", "粤语", "English", "日本語", "한국어"],
            "repo": "https://github.com/FunAudioLLM/SenseVoice",
        },
        "capabilities": ["多语言", "LID", "情感", "音频事件"],
        "benchmarks": [],
        "resources": "官方未提供统一硬件需求（轻量，可 CPU）",
    },
    "paraformer": {
        "purpose": "中文长音频识别与轻量时间轴后端。",
        "strengths": "非自回归路线、支持热词，可与 VAD/标点组件配合，速度取向明显。",
        "limits": "当前 2ByteASR 将它用于时间轴角色；主力多人转写仍以 MOSS 为准。",
        "io": "输入音频与可选热词；输出中文文字和后端提供的时间信息。",
        "source": "ModelScope FunASR 官方项目。",
        "url": "https://github.com/modelscope/FunASR",
        "modelscope": "https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/summary",
        "official": {
            "developer": "FunASR / ModelScope",
            "series": "Paraformer Large",
            "params": "Large",
            "languages": ["中文"],
            "repo": "https://github.com/modelscope/FunASR",
        },
        "capabilities": ["热词", "时间戳", "长音频"],
        "benchmarks": [],
        "resources": "官方未提供统一硬件需求（轻量本地部署友好）",
    },
    "whisper": {
        "purpose": "通用多语言语音转写与复核。",
        "strengths": "语言覆盖广，适合混合语种或非中文内容提供第二路证据。",
        "limits": "不包含 MOSS 的说话人区分；不同硬件上的速度差异较大。",
        "io": "输入音频；输出转写文字和片段级时间信息。",
        "source": "OpenAI Whisper 官方项目。",
        "url": "https://github.com/openai/whisper",
        "official": {
            "developer": "OpenAI",
            "series": "Whisper large-v3-turbo",
            "params": "large-v3-turbo",
            "languages": ["多语言"],
            "repo": "https://github.com/openai/whisper",
        },
        "capabilities": ["多语言", "时间戳"],
        "benchmarks": [],
        "resources": "官方未提供统一硬件需求（本地部署需 GPU 加速效果佳）",
    },
    "qwen_aligner": {
        "purpose": "根据已有文字生成字级或词级强制对齐时间轴。",
        "strengths": "适合已有可靠初稿时精修字幕边界，并支持多语种对齐。",
        "limits": "它不是从零转写模型；需要已有文字。没有 NVIDIA CUDA 时用 CPU 运行，较慢。",
        "io": "输入音频加已有文本；输出字/词与音频时间边界的对齐结果。",
        "source": "Qwen3-ForcedAligner 官方模型卡。",
        "url": "https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B",
    },
    "funasr_nano": {
        "purpose": "中文方言与多语种的本地文字复核。",
        "strengths": "覆盖中文方言与多语种，可为已有主流程补充文本证据。",
        "limits": "当前在 2ByteASR 中不是多人主力骨架；性能取决于本机设备与音频条件。",
        "io": "输入音频；输出多语种文字结果，供复核阶段使用。",
        "source": "FunAudioLLM Fun-ASR 官方项目。",
        "url": "https://github.com/FunAudioLLM/Fun-ASR",
    },
}

_TECHNICAL_PROFILES_EN = {
    "moss": {
        "purpose": "First-pass transcription and speaker separation for long Chinese audio.",
        "strengths": "Keeps a complete semantic backbone for later timeline and text-review stages.",
        "limits": "Requires NVIDIA CUDA. Speaker labels distinguish voices; they do not identify real people.",
        "io": "Input: local audio. Output: draft transcript, segments and speaker evidence.",
        "source": "2ByteASR's bundled MOSS transcription and speaker worker.",
        "url": "https://github.com/OpenMOSS/MOSS-Audio",
        "official": {
            "developer": "OpenMOSS / 2ByteASR integration",
            "series": "MOSS-Audio transcription + diarization worker",
            "params": "Packaged worker (no single public checkpoint)",
            "languages": ["Chinese"],
            "repo": "https://github.com/OpenMOSS/MOSS-Audio",
        },
        "capabilities": ["Long audio", "Speaker separation"],
        "benchmarks": [],
        "resources": "Official uniform hardware requirements not published (2ByteASR requires NVIDIA CUDA)",
    },
    "firered": {
        "purpose": "Chinese / dialect recognition with fine-grained subtitle timing.",
        "strengths": "Improves word-boundary timing after a MOSS draft.",
        "limits": "Local use requires CUDA; timestamp quality still depends on the audio and overlapping speakers.",
        "io": "Input: audio. Output: recognized text and subtitle-ready time boundaries.",
        "source": "FireRedASR official project.",
        "url": "https://github.com/FireRedTeam/FireRedASR",
        "hf": "https://huggingface.co/FireRedTeam/FireRedASR2-AED",
        "official": {
            "developer": "FireRedTeam",
            "series": "FireRedASR / FireRedASR2-AED",
            "params": "AED",
            "languages": ["Chinese", "Dialects", "English"],
            "repo": "https://github.com/FireRedTeam/FireRedASR",
        },
        "capabilities": ["Timestamp", "Long audio", "Dialect", "Lyrics"],
        "benchmarks": [
            {"metric": "SOTA", "value": "New SOTA on public Mandarin ASR benchmarks", "dataset": "Public Mandarin ASR", "condition": "Official report", "hardware": "Official test env"}
        ],
        "resources": "Official hardware requirements not uniformly published (2ByteASR uses CUDA locally)",
    },
    "qwen_local": {
        "purpose": "Multilingual text review and terminology evidence.",
        "strengths": "Offers a second local reference for named entities, multilingual clips and wording differences.",
        "limits": "Needs a large download and GPU memory; it is a review role here, not a replacement for the full workflow.",
        "io": "Input: segmented audio / text context. Output: text candidates and review evidence.",
        "source": "Qwen3-ASR official release with the 2ByteASR local adapter.",
        "url": "https://github.com/QwenLM/Qwen3-ASR",
        "hf": "https://huggingface.co/Qwen/Qwen3-ASR-1.7B",
        "official": {
            "developer": "Qwen Team / Alibaba",
            "series": "Qwen3-ASR",
            "params": "1.7B",
            "languages": ["Multilingual"],
            "repo": "https://github.com/QwenLM/Qwen3-ASR",
        },
        "capabilities": ["Multilingual", "Text precision"],
        "benchmarks": [],
        "resources": "Official hardware requirements not uniformly published (local needs CUDA, higher VRAM)",
    },
    "sensevoice": {
        "purpose": "Lightweight multilingual recognition and text review.",
        "strengths": "Can run on CPU and works well for Chinese, Cantonese and common languages.",
        "limits": "Does not provide MOSS's multi-speaker backbone; best used as independent text evidence.",
        "io": "Input: audio. Output: multilingual text plus optional event / emotion signals.",
        "source": "FunAudioLLM SenseVoice official project.",
        "url": "https://github.com/FunAudioLLM/SenseVoice",
        "hf": "https://huggingface.co/FunAudioLLM/SenseVoiceSmall",
        "official": {
            "developer": "FunAudioLLM (Alibaba)",
            "series": "SenseVoiceSmall",
            "params": "Small",
            "languages": ["Chinese", "Cantonese", "English", "Japanese", "Korean"],
            "repo": "https://github.com/FunAudioLLM/SenseVoice",
        },
        "capabilities": ["Multilingual", "LID", "Emotion", "Audio event"],
        "benchmarks": [],
        "resources": "Official uniform hardware requirements not published (lightweight, CPU-capable)",
    },
    "paraformer": {
        "purpose": "Chinese long-audio recognition and a lightweight timeline backend.",
        "strengths": "Non-autoregressive design with hot-word support; pairs with VAD and punctuation components and favors speed.",
        "limits": "2ByteASR currently uses it for the timeline role; MOSS remains the reference for primary multi-speaker transcription.",
        "io": "Input: audio plus optional hot words. Output: Chinese text and backend timing information.",
        "source": "ModelScope FunASR official project.",
        "url": "https://github.com/modelscope/FunASR",
        "modelscope": "https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/summary",
        "official": {
            "developer": "FunASR / ModelScope",
            "series": "Paraformer Large",
            "params": "Large",
            "languages": ["Chinese"],
            "repo": "https://github.com/modelscope/FunASR",
        },
        "capabilities": ["Hotword", "Timestamp", "Long audio"],
        "benchmarks": [],
        "resources": "Official uniform hardware requirements not published (lightweight-friendly local deploy)",
    },
    "whisper": {
        "purpose": "General multilingual transcription and review.",
        "strengths": "Broad language coverage makes it useful as a second source for mixed-language content.",
        "limits": "No MOSS-style speaker separation; speed varies notably by hardware.",
        "io": "Input: audio. Output: transcription text and segment-level timing.",
        "source": "OpenAI Whisper official project.",
    },
    "qwen_aligner": {
        "purpose": "Character- or word-level forced alignment from existing text.",
        "strengths": "Refines subtitle boundaries when a reliable draft already exists and supports multilingual alignment.",
        "limits": "It is not a from-scratch transcriber: existing text is required. Without NVIDIA CUDA it runs on the CPU, more slowly.",
        "io": "Input: audio plus existing text. Output: character / word alignment time boundaries.",
        "source": "Qwen3-ForcedAligner official model card.",
    },
    "funasr_nano": {
        "purpose": "Local text review for Chinese dialects and multiple languages.",
        "strengths": "Covers Chinese dialects and multilingual content, adding evidence to an existing pipeline.",
        "limits": "It is not the multi-speaker primary backbone in 2ByteASR; performance depends on the machine and audio conditions.",
        "io": "Input: audio. Output: multilingual text for the review stage.",
        "source": "FunAudioLLM Fun-ASR official project.",
    },
}


def model_scene(model: WorkshopModel) -> str:
    source = _SCENE_COPY.get(model.key, model.summary)
    return translate(source, current_language())


def model_metric_scene(model: WorkshopModel, scene: str) -> str:
    task = task_for(model.asr_capabilities, model.model_type)
    if task.metric_scope:
        return task.metric_scope
    # An English-only checkpoint's published English evidence is useful even
    # when the surrounding catalog is set to Chinese; never relabel it Chinese.
    if model.languages == ("English",) and scene.startswith("zh"):
        return "en"
    return scene


def model_task_badges(model: WorkshopModel) -> tuple[str, ...]:
    task = task_for(model.asr_capabilities, model.model_type)
    copy = MODEL_COPY.get(model.key, ModelCopy(model.summary))
    badges = [task.label]
    if task.requires_text:
        badges.append("需要已有文本")
    if task.standalone_asr and "DIARIZATION" in model.asr_capabilities:
        badges.append("说话人")
    badges.extend(copy.advantages)
    official = _technical_profile(model).get("official", {})
    languages = official.get("language_summary") or " / ".join(model.languages)
    if languages:
        badges.append(str(languages))
    badges.append("在线 API" if model.api_preset else "本地")
    return tuple(ui_literal(text, current_language()) for text in dict.fromkeys(badges))[:5]


def model_workflow(model: WorkshopModel) -> str:
    task = task_for(model.asr_capabilities, model.model_type)
    copy = MODEL_COPY.get(model.key, ModelCopy(model.summary))
    operation, output = task.operation, task.output
    if task.standalone_asr:
        if "TIMESTAMP" in model.asr_capabilities:
            output += " + 时间轴"
        if "DIARIZATION" in model.asr_capabilities:
            operation = "转写 + 说话人分析"
            output += " + 说话人标签"
    lines = [f"{translate(task.input, current_language())} → {translate(operation, current_language())} → {translate(output, current_language())}"]
    lines.append("可独立转写" if task.standalone_asr else "不能独立转写")
    if copy.best_for:
        lines.append(tr("适合：{use}", use=tr(copy.best_for)))
    if copy.workflow_note:
        lines.append(copy.workflow_note)
    if copy.limitations:
        lines.append(copy.limitations)
    if not model.runtime_available:
        lines.append("本软件当前适配尚未完成，暂不能用于识别。")
    return "\n".join(translate(line, current_language()) for line in lines)


def _technical_profile(model: WorkshopModel) -> dict[str, str]:
    if _get_eval_profile is not None:
        try:
            profile = _get_eval_profile(model.key, current_language())
            if isinstance(profile, dict) and profile:
                return profile
        except Exception:
            pass
    if current_language() == "en":
        return _TECHNICAL_PROFILES_EN.get(model.key, _TECHNICAL_PROFILES.get(model.key, {}))
    return _TECHNICAL_PROFILES.get(model.key, {})


def _official_rtf_note(model: WorkshopModel, language: str) -> str:
    """官方 RTF 仅作参考（硬件/协议各异），绝不参与速度评分。"""
    profile = _technical_profile(model)
    for item in profile.get("benchmarks", []):
        if not isinstance(item, dict):
            continue
        metric = str(item.get("metric") or "").lower()
        if "rtf" in metric and "rtfx" not in metric:
            hardware = str(item.get("hardware") or "官方未声明")
            return (
                f"{translate('官方参考 RTF', language)} {item.get('value')}（{hardware}）"
                f"· {translate('不同硬件不互比', language)}"
            )
    return ""


def _reference_evidence(
    model: WorkshopModel,
    entry: dict,
    kind: str,
    caption: str,
    scene_name: str,
    language: str,
    suffix: str = "",
) -> dict[str, object]:
    """第三层：2ByteASR 参考指数（公开基准换算 / 跨表校准 / 综合估算）。"""
    from twobyteasr.model_benchmarks import REFERENCE_INDEX_VERSION

    score = int(entry["score"])
    approx = bool(entry.get("approx"))
    value = tr("约 {score}", score=score) if approx else str(score)
    note = f"{translate(entry['label'], language)} · {translate(entry['reason'], language)}"
    if suffix:
        note = f"{suffix} · {note}"
    tooltip = "\n".join((
        f"{translate(caption, language)}：{value}/100",
        translate("2ByteASR 参考指数：1–100 相对选型参考，不是识别正确率。", language),
        (translate("估算分（约）：依据间接证据的档位/校准推导，不是官方同台成绩。", language)
         if approx else translate("换算分：来自公开评测表的相对换算。", language)),
        f"{translate('比较场景', language)}: {scene_name}",
        f"{translate('依据类型', language)}: {translate(entry['label'], language)}",
        f"{translate('推导', language)}: {translate(entry['reason'], language)}",
        translate(entry["detail"], language),
        f"{translate('来源', language)}: {' ; '.join(entry['sources'])}",
        f"{translate('参考版本', language)}: {REFERENCE_INDEX_VERSION} · "
        + translate("核实 2026-09-18", language),
    ))
    if suffix:
        tooltip = suffix + "\n" + tooltip
    return {
        "available": True,
        "value": value,
        "note": note,
        "score": score,
        "approx": approx,
        "tooltip": tooltip,
        "caption": caption,
        "group_id": "reference",
        "basis": entry["basis"],
    }


def _api_model_suffix(model: WorkshopModel, api_model: str | None) -> str:
    """API 卡当前配置型号与预设默认不一致时的透明标注。"""
    if not model.api_preset:
        return ""
    from .ui import ASR_API_PRESETS

    preset = ASR_API_PRESETS.get(model.api_preset) or {}
    default_id = str(preset.get("model") or "")
    current = str(api_model or "").strip()
    if not current or not default_id or current.lower() == default_id.lower():
        return ""
    if current.lower() in _BENCHMARK_API_ALIASES:
        return (
            f"{translate('已按当前型号', current_language())} {current}"
            + translate("（托管路由未验证）", current_language())
        )
    return (
        f"{translate('当前型号', current_language())} {current} "
        + translate("未单独收录，按预设默认", current_language())
        + f" {default_id} "
        + translate("给参考", current_language())
    )


def _metric_evidence(
    model: WorkshopModel,
    kind: str,
    role: str | None = None,
    scene: str = _DEFAULT_BENCHMARK_SCENE,
    api_model: str | None = None,
) -> dict[str, object]:
    """2ByteASR 参考指数（第三层，卡片默认）+ 严格同组（第二层，兜底/技术说明）。

    第三层综合直接评测、可解释归一化（跨表校准经共同参照 turbo 锚）与间接证据
    档位，覆盖面优先；估算分带"约"与依据，永不伪装官方成绩。分数绑定
    REFERENCE_INDEX_VERSION 的固定参照目录，搜索/筛选/安装态不影响。
    对齐类模型（ALIGNMENT）的 accuracy 走对齐场景（AAS），不与 CER/WER 混算。
    """
    language = current_language()
    scene_key = model_metric_scene(model, str(scene or _DEFAULT_BENCHMARK_SCENE))
    task = task_for(model.asr_capabilities, model.model_type)
    caption = task.primary_metric if kind == "accuracy" else "速度指数"
    if kind == "accuracy" and task.standalone_asr and scene_key == "en":
        caption = "英语转写准确度"
    scene_name = _benchmark_scene_label(scene_key, language)

    # 自定义入口：按用户配置的 model id 匹配已知模型。
    if model.key == "custom_asr_api" and api_model:
        api_entry = _benchmark_reference_api_model(api_model, kind, scene_key)
        if api_entry is not None and not api_entry.get("unsupported"):
            suffix = f"{api_entry.get('matched_model', api_model)} {translate('参考', language)}"
            return _reference_evidence(
                model, api_entry, kind, caption, scene_name, language, suffix=suffix
            )

    entry = _benchmark_reference_entry(model.key, kind, scene_key)
    if entry is not None and entry.get("unsupported"):
        return {
            "available": False,
            "unsupported": True,
            "value": "不支持该语言",
            "note": f"{scene_name} · " + translate("不支持该场景语言", language)
            + f"（{translate(entry['reason'], language)}）",
            "score": None,
            "tooltip": "\n".join((
                translate("该模型在当前场景明确不支持，不给参考分。", language),
                translate(entry["reason"], language),
                f"{translate('比较场景', language)}: {scene_name}",
            )),
            "caption": caption,
            "group_id": "",
        }
    if entry is not None:
        suffix = _api_model_suffix(model, api_model) if model.api_preset else ""
        return _reference_evidence(
            model, entry, kind, caption, scene_name, language, suffix=suffix
        )

    # 第二层兜底：严格同组（对齐等有直接组的场景仍优先真实表）。
    result = _benchmark_best_score(model.key, kind, scene_key)
    if result is not None:
        group = result["group"]
        score = result["score"]
        metric = group.metric
        raw = f"{metric} {result['value']:g}{group.unit}"
        evidence_label = _benchmark_source_type_label(group.source_type, language)
        note = f"{scene_name} · {evidence_label} · {raw}"
        tooltip = "\n".join((
            f"{translate(caption, language)}：{score}/100",
            translate("同组相对指数：100 = 该基准组相对最佳，不是识别正确率百分比。", language),
            f"{translate('比较场景', language)}: {scene_name}",
            f"{translate('基准组', language)}: {translate(group.label, language)}",
            f"{translate('原始指标', language)}: {raw}（{translate('越低越好', language) if group.direction == 'lower' else translate('越高越好', language)}）",
            f"{translate('评测口径', language)}: {translate(group.protocol, language)}",
            f"{translate('来源', language)}: {translate(group.source_name, language)}",
            f"URL: {group.source_url}",
            f"{translate('核实日期', language)}: {group.verified} · {translate('公式', language)}: {result['formula']}",
        ))
        return {
            "available": True,
            "value": str(score),
            "note": note,
            "score": score,
            "tooltip": tooltip,
            "caption": caption,
            "group_id": group.group_id,
        }
    # 真缺失：写明具体缺口，不编分（不造 0/50/100）。
    gap = translate(_benchmark_reference_gap(model.key, kind), language)
    if kind == "speed":
        rtf_note = _official_rtf_note(model, language)
        parts = [gap or translate("暂无公开速度数据 · 待本机实测", language)]
        if rtf_note:
            parts.append(rtf_note)
        note = " · ".join(parts)
        value = translate("暂无速度数据", language)
    else:
        secondary = _benchmark_secondary_record(model.key, kind, scene_key)
        note = gap or (scene_name + " · " + translate("暂无同组可比数据", language))
        if secondary is not None:
            note += (
                " · " + translate("另有同表数据", language)
                + f" {secondary.metric} {secondary.entries[model.key]:g}{secondary.unit}"
                + f"（{translate(secondary.label, language)}，{translate('见技术说明', language)}）"
            )
        value = translate("暂无可比数据", language)
    return {
        "available": False,
        "value": value,
        "note": note,
        "score": None,
        "tooltip": "\n".join((
            gap or translate("暂无同组可比数据：没有可与该模型直接比较的同协议公开评测。", language),
            translate("不把缺失数据换算成分数；可切换“排序与筛选”中的比较场景。", language),
            f"{translate('比较场景', language)}: {scene_name}",
        )),
        "caption": caption,
        "group_id": "",
    }


def _rating_word(value: int) -> str:
    table = _RATING_WORDS_EN if current_language() == "en" else _RATING_WORDS
    return translate(table.get(value, table[3]), current_language())


def model_is_online(model: WorkshopModel) -> bool:
    return bool(model.api_preset)


def _size_friendly_score(model: WorkshopModel) -> int:
    """Five-step 体积友好 tier derived from the advertised model size."""
    match = re.search(r"(\d+(?:\.\d+)?)", model.size)
    if match is None:
        return 5  # 不占本地空间 / 取决于服务商 → 视为最友好
    gb = float(match.group(1))
    if gb <= 1.0:
        return 5
    if gb <= 1.8:
        return 4
    if gb <= 2.4:
        return 3
    if gb <= 4.4:
        return 2
    return 1


def _install_size_label(size: str) -> str:
    text = str(size or "").strip()
    if not text or text.startswith("安装"):
        return text
    if text.startswith("约") or "GB" in text.upper():
        return f"安装{text}"
    return text


_SCORE_TRACK_HEIGHT = 7
_SCORE_TRACK_MIN_WIDTH = 54


def _active_accent_text() -> str:
    from .theme_manager import theme_key
    from .ui_theme import theme_definition
    return theme_definition(theme_key()).accent_text


def _score_palette() -> tuple[str, str, str, str]:
    """(track, low, mid, high) for the active theme (2026-10-14).

    The warm cream track and fills were fixed literals and drew a bright
    beige stripe on every dark theme; now track and fills come from tokens.
    """
    from .theme_manager import theme_key
    from .ui_theme import blend_hex, theme_definition
    theme = theme_definition(theme_key())
    track = blend_hex(theme.surface, theme.border_strong, 0.45 if theme.is_light else 0.55)
    soften = 0.12 if theme.is_light else 0.18
    return (track, blend_hex(theme.danger, theme.surface, soften), blend_hex(theme.warning, theme.surface, soften),
            blend_hex(theme.success, theme.surface, soften))


def _score_color(score: int) -> QColor:
    score = max(10, min(100, int(score)))
    _track, low, mid, high = (QColor(value) for value in _score_palette())
    left, right, ratio = (
        (low, mid, (score - 10) / 40.0)
        if score <= 50
        else (mid, high, (score - 50) / 50.0)
    )
    return QColor(
        round(left.red() + (right.red() - left.red()) * ratio),
        round(left.green() + (right.green() - left.green()) * ratio),
        round(left.blue() + (right.blue() - left.blue()) * ratio),
    )


class _EvidenceTrack(QWidget):
    """Relative track when comparable; otherwise a deliberately neutral line."""

    def __init__(self, score: int | None, parent=None):
        super().__init__(parent)
        self._score = score
        self.setFixedHeight(16)
        self.setMinimumWidth(_SCORE_TRACK_MIN_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_score(self, score: int | None):
        self._score = score
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track_h = _SCORE_TRACK_HEIGHT
        radius = track_h / 2.0
        track = QRectF(
            0.0, (self.height() - track_h) / 2.0, max(1.0, float(self.width())), track_h
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(_score_palette()[0]))
        painter.drawRoundedRect(track, radius, radius)
        if self._score is not None:
            marker = QRectF(track)
            marker.setWidth(
                max(radius * 2, track.width() * max(10, min(100, self._score)) / 100.0)
            )
            painter.setBrush(_score_color(self._score))
            painter.drawRoundedRect(marker, radius, radius)


class RatingBar(QWidget):
    """Official evidence row with a neutral, non-ranking horizontal track."""

    def __init__(self, label: str, evidence: dict, parent=None, *, label_width: int = 42):
        super().__init__(parent)
        self._label = label
        self._evidence = dict(evidence)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(3)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(7)
        self._caption = QLabel(label)
        self._caption.setObjectName("workshopRatingLabel")
        self._caption.setMinimumWidth(label_width)
        row.addWidget(self._caption)
        self._word = QLabel(str(evidence.get("value") or "—"))
        self._word.setObjectName("workshopRatingWord")
        self._word.setMinimumWidth(0)
        self._word.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._word.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._word, 1)
        box.addLayout(row)
        self._track = _EvidenceTrack(evidence.get("score"))
        box.addWidget(self._track)
        self._note = ElideLabel(str(evidence.get("note") or ""))
        self._note.setObjectName("workshopMetricEvidence")
        box.addWidget(self._note)
        self.setMinimumHeight(50)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.set_evidence(evidence)

    def set_evidence(self, evidence: dict):
        self._evidence = dict(evidence)
        value = str(evidence.get("value") or "—")
        note = str(evidence.get("note") or "")
        self._track.set_score(evidence.get("score"))
        self._track.setVisible(bool(evidence.get("available")) and evidence.get("score") is not None)
        caption = str(evidence.get("caption") or self._label)
        self._current_caption = caption
        self._caption.setText(translate(caption, current_language()))
        self._word.setText(value)
        self._word.setToolTip(value)
        self._note.setText(note)
        self.setAccessibleName(f"{translate(caption, current_language())}, {value}, {note}")
        bind_text(self, str(evidence.get('tooltip') or translate('仅展示可追溯官方证据；不同数据集、指标和硬件不换算成统一分数。', current_language())) + '\n' + translate(COMPARISON_NOTE, current_language()) + ('\n' + translate(SPEED_NOTE, current_language()) if caption == '速度指数' else ''), property='toolTip')

    def apply_compact(self, compact: bool):
        self._caption.setMinimumWidth(42 if compact else 48)
        self._track.setMinimumWidth(54 if compact else _SCORE_TRACK_MIN_WIDTH)


class ElideLabel(QLabel):
    """Single-line label that elides to … instead of wrapping or stretching."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._full_text = text
        self.setWordWrap(False)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._apply_elide()

    def setText(self, text: str):
        self._full_text = str(text)
        self._apply_elide()

    def _apply_elide(self):
        metrics = self.fontMetrics()
        elided = metrics.elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, max(12, self.width())
        )
        super().setText(elided)
        self.setToolTip(self._full_text if elided != self._full_text else "")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_elide()

    def showEvent(self, event):
        # 切换分组时卡片先以窄几何隐藏、再显示；陈旧的省略号必须在
        # 显示时重算（三十二轮：新卡名称在 API tab 首次显示被截断）。
        super().showEvent(event)
        self._apply_elide()


def _icon(name: str, color: str | None = None) -> QIcon:
    return qta.icon(name, color=color or WORKSHOP_TOKENS["ink"])


def _model_logo(model: WorkshopModel, size: QSize) -> QIcon:
    """Load the upstream project/vendor mark and retain a safe built-in fallback."""
    if model.logo_asset:
        path = Path(__file__).resolve().parents[1] / "assets" / "model_logos" / model.logo_asset
        if path.is_file():
            logo = QIcon(str(path))
            if not logo.isNull():
                return logo
    return _icon(model.icon_name, model.icon_color)


def _load_lock(root: Path) -> dict:
    try:
        return json.loads((root / "dependencies.lock.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"models": {}}


_READINESS_STATUS: dict[str, tuple[tuple[int, int], str]] = {}


def _readiness_status(download_key: str) -> str:
    """Status of a model's readiness receipt, re-read only when it changes."""
    from .runtime_paths import user_data_root

    receipt = user_data_root() / 'model-readiness' / (str(download_key) + '.json')
    try:
        stat = receipt.stat()
    except OSError:
        return ''
    stamp = (stat.st_mtime_ns, stat.st_size)
    cached = _READINESS_STATUS.get(str(receipt))
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        readiness = json.loads(receipt.read_text('utf8'))
    except (OSError, ValueError):
        readiness = {}
    status = str(readiness.get('status') or '') if isinstance(readiness, dict) else ''
    _READINESS_STATUS[str(receipt)] = (stamp, status)
    return status


def _registry_fingerprint(registry) -> tuple:
    """What a refresh shows from a registry scan (health and location)."""
    if registry is None:
        return ()
    return (str(registry.error), tuple(sorted(
        (key, record.health.value, str(record.installation_path), tuple(record.missing_files))
        for key, record in registry.records.items())))


def installed_model_keys(root: Path) -> set[str]:
    """Return models whose complete required-file set exists locally.

    Source and packaged launches share RuntimePaths.MODEL_ROOT, so a model
    already downloaded beside the git checkout is still INSTALLED when the
    user opens ``2ByteASR.exe``.
    """
    import time as _t
    from .model_registry import scan_model_registry

    _t0 = _t.perf_counter()
    registry = scan_model_registry(install_root=Path(root))
    installed = registry.installed_keys()
    _dt = (_t.perf_counter() - _t0) * 1000
    try:
        if GUI_PROFILE_ENABLED and _dt > 5:
            print(f"[perf] installed_model_keys scan ~{int(_dt)}ms (keys={len(installed)})")
    except Exception:
        pass
    return installed


def cleanup_orphan_download_temps(root: Path, active_download_keys: set[str] | None = None) -> int:
    """Maintain receipted staging only when enabled, idle and past policy TTL."""
    # Receipt/state and OS lock establish ownership. Legacy unknown files are
    # inventoried for manual review, rather than guessed from a .part suffix.
    from .runtime_paths import get_runtime_paths
    from .model_download_cache import scan_download_transactions, cleanup_download_transaction
    from .storage_service import StorageService
    policy = StorageService().policy()
    if not policy['enabled']: return 0
    staging = get_runtime_paths().model_root / '.downloads'
    removed = 0
    for transaction in scan_download_transactions(staging):
        result = cleanup_download_transaction(transaction, staging_root=staging,
            active_keys=set(active_download_keys or ()), expired_only=True, resume_days=policy['resume_days'])
        removed += len(result['removed'])
    return removed


def model_install_path(root: Path, download_key: str) -> Path | None:
    from .model_registry import scan_model_registry

    record = scan_model_registry(install_root=Path(root)).record(str(download_key))
    if record is None:
        spec = _load_lock(root).get("models", {}).get(str(download_key))
        if not isinstance(spec, dict):
            return None
        candidate = (root / str(spec.get("path", ""))).resolve()
        return candidate if candidate.is_dir() else None
    return record.installation_path if record.installation_path.is_dir() else None




WORKSHOP_QSS = NAVIGATION_QSS + """
QWidget#modelWorkshopRoot {
    background: #f8f6f0;
    color: #28261f;
}
QFrame#workshopSidebar {
    background: #f2f1ea;
    border: 1px solid #ddd6c8;
    border-radius: 18px;
}
QFrame#workshopContent {
    background: #fbfaf6;
    border: 1px solid #ddd6c8;
    border-radius: 18px;
}
QFrame#workshopDownloadActivity {
    background: #f0f4ec;
    border: 1px solid #b8c9ae;
    border-radius: 8px;
}
QLabel#workshopDownloadActivityText {
    color: #355f3a;
    font-size: 12px;
    font-weight: 600;
}
QProgressBar#workshopDownloadActivityProgress {
    background: #dce5d7;
    border: 0;
    border-radius: 4px;
    min-height: 8px;
    max-height: 8px;
}
QProgressBar#workshopDownloadActivityProgress::chunk {
    background: #577d4d;
    border-radius: 4px;
}
QFrame#workshopDetail {
    background: #faf5ea;
    border: 1px solid #ddd6c8;
    border-radius: 18px;
}
QLabel#workshopPageTitle {
    color: #28261f;
    font-family: "Source Han Sans SC", "思源黑体", "Microsoft YaHei UI", "Microsoft YaHei";
    font-size: 21px;
    font-weight: 700;
}
QLabel#workshopDetailTitle {
    color: #28261f;
    font-family: "Source Han Sans SC", "思源黑体", "Microsoft YaHei UI", "Microsoft YaHei";
    font-size: 21px;
    font-weight: 700;
}
QLabel#workshopModelTitle {
    color: #28261f;
    font-family: "Source Han Sans SC", "思源黑体", "Microsoft YaHei UI", "Microsoft YaHei";
    font-size: 16px;
    font-weight: 700;
}
QLabel#workshopMuted { color: #625f57; font-size: 12px; font-weight: 500; }
QLabel#workshopTiny { color: #6f6b61; font-size: 11px; }
QLabel#workshopRatingLabel {
    color: #5f5b53;
    font-size: 11px;
    font-weight: 600;
}
QLabel#workshopRatingWord {
    color: #56534c;
    font-size: 11px;
    font-weight: 600;
}
QLabel#workshopMetricEvidence {
    background: transparent;
    color: #8a857a;
    border: 0;
    font-size: 9px;
    font-weight: 500;
}
QLabel#workshopReferenceIndex {
    background: transparent;
    color: #6f6b61;
    border: 0;
    font-size: 10px;
    font-weight: 700;
}
QLabel#workshopSection { color: #28261f; font-size: 13px; font-weight: 700; }
QLabel#workshopGood { color: #577d4d; font-size: 12px; font-weight: 600; }
QLabel#workshopRatingAccuracy {
    background: #f0f4ec;
    color: #577d4d;
    border: 1px solid #d5e0cb;
    border-radius: 8px;
    padding: 3px 7px;
    font-size: 10px;
    font-weight: 600;
}
QLabel#workshopRatingSpeed {
    background: #f7edd9;
    color: #8f6228;
    border: 1px solid #ead9b9;
    border-radius: 8px;
    padding: 3px 7px;
    font-size: 10px;
    font-weight: 600;
}
QLabel#workshopBadge {
    background: #e4ebdd;
    color: #577d4d;
    border-radius: 9px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 600;
}
QFrame#workshopComboCard {
    background: #fffefa;
    border: 1px solid #ddd6c8;
    border-radius: 15px;
}
QLabel#workshopComboHeading {
    color: #28261f;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei";
    font-size: 15px;
    font-weight: 600;
}
QLabel#workshopComboRole {
    color: #6f6b61;
    font-size: 10px;
}
QLabel#workshopComboModel {
    color: #28261f;
    font-size: 13px;
    font-weight: 600;
}
QLabel#workshopComboStatus {
    color: #8a857a;
    font-size: 10px;
    font-weight: 600;
}
QLabel#workshopComboStatus[ready="true"] { color: #577d4d; }
QFrame#workshopRule { background: #ddd6c8; border: 0; }
QPushButton#workshopNav {
    background: transparent;
    color: #6f6b61;
    border: 0;
    border-radius: 10px;
    text-align: left;
    padding: 8px 10px;
    min-height: 20px;
    font-weight: 600;
}
QPushButton#workshopNav:hover { background: #ebe9e1; color: #28261f; }
QPushButton#workshopNav:checked {
    background: #e4ebdd;
    color: #577d4d;
    font-weight: 600;
}
QPushButton#workshopTab {
    background: #fffefa;
    color: #28261f;
    border: 1px solid #ddd6c8;
    border-radius: 10px;
    padding: 6px 12px;
    min-height: 18px;
    font-weight: 600;
}
QPushButton#workshopTab:hover { border-color: #d4b783; background: #fffaf2; }
QPushButton#workshopTab:checked {
    background: #577d4d;
    color: white;
    border-color: #577d4d;
}
QLineEdit#workshopSearch {
    background: #fffefa;
    color: #28261f;
    border: 1px solid #ddd6c8;
    border-radius: 11px;
    padding: 7px 10px;
    min-height: 24px;
}
QLineEdit#workshopSearch:focus { border: 1.5px solid #577d4d; }
QScrollArea#workshopScroll, QScrollArea#workshopScroll QWidget#qt_scrollarea_viewport {
    background: #fbfaf6;
    border: 0;
}
QWidget#workshopScrollHost {
    background: #fbfaf6;
    border: 0;
}
QFrame#workshopModelCard {
    background: #fffefa;
    border: 1px solid #ded2c0;
    border-radius: 12px;
}
QFrame#workshopModelCard[selected="true"] {
    background: #f0f4ec;
    border: 2px solid #64875b;
}
QFrame#workshopModelCard:hover {
    background: #fffdf8;
    border-color: #c7ad80;
}
QFrame#workshopModelCard[selected="true"]:hover {
    background: #eef3e8;
    border: 2px solid #577d4d;
}
QWidget#workshopCardInfo,
QWidget#workshopCardMetrics,
QWidget#workshopCardActions {
    background: transparent;
    border: 0;
}
QLabel#workshopMonogram {
    background: transparent;
    color: #6f6b61;
    border: 0;
    font-family: "Georgia", "Times New Roman";
    font-size: 12px;
    font-weight: 700;
}
QPushButton#workshopAction, QPushButton#workshopSecondary {
    background: #fffefa;
    color: #28261f;
    border: 1px solid #ddd6c8;
    border-radius: 10px;
    padding: 7px 12px;
    min-height: 18px;
    font-weight: 700;
}
QPushButton#workshopAction:hover, QPushButton#workshopSecondary:hover {
    background: #fffaf2;
    border-color: #d4b783;
}
QPushButton#workshopAction:pressed, QPushButton#workshopSecondary:pressed { padding-top: 9px; padding-bottom: 7px; }
QPushButton#workshopAction:disabled { color: #9a968d; background: #f1eee7; }
QPushButton#workshopCardUninstall {
    background: transparent;
    color: #8a5a4c;
    border: 0;
    padding: 3px 7px;
    min-height: 16px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#workshopCardUninstall:hover { color: #6f4035; text-decoration: underline; }

QLabel#langPill {
    background: #f4efe5;
    color: #665f52;
    border: 1px solid #e5dac8;
    border-radius: 8px;
    padding: 1px 6px;
    font-size: 10px;
    font-weight: 500;
}

QLabel#workshopRecommendationBadge {
    background: #eaf1e5;
    color: #3f6b3c;
    border: 1px solid #b9ccb2;
    border-radius: 8px;
    padding: 1px 7px;
    font-size: 10px;
    font-weight: 700;
}

QLabel#recTag {
    background: #eaf0e3;
    color: #3f6b2f;
    border: 1px solid #b7c8a8;
    border-radius: 9px;
    padding: 0 6px;
    font-size: 11px;
    font-weight: 700;
}

QComboBox#workshopSourceCombo {
    background: #fffefa;
    color: #28261f;
    border: 1px solid #ddd6c8;
    border-radius: 10px;
    padding: 6px 12px;
    min-height: 28px;
    min-width: 180px;
    font-weight: 600;
}
QComboBox#workshopSourceCombo:hover { border-color: #d4b783; }
QComboBox#workshopSourceCombo::drop-down { border: 0; width: 22px; }
QComboBox#workshopSourceCombo QAbstractItemView {
    background: #fffefa;
    color: #28261f;
    border: 1px solid #ddd6c8;
    selection-background-color: #e7efe2;
    selection-color: #315b35;
    padding: 4px;
    outline: 0;
}
QDialog#modelDownloadDialog { background: transparent; }
QFrame#modelDownloadCard {
    background: #fbfaf6;
    border: 1px solid #d9cfbf;
    border-radius: 14px;
}
QFrame#modelDownloadTitleBar {
    background: #fbfaf6;
    border: 0;
    border-bottom: 1px solid #e8e0d4;
}
QLabel#modelDownloadChromeTitle {
    color: #353128;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#modelDownloadChromeClose {
    background: transparent;
    border: 0;
    border-radius: 7px;
    min-width: 30px;
    min-height: 28px;
    max-width: 30px;
    max-height: 28px;
}
QPushButton#modelDownloadChromeClose:hover { background: #f5e5df; }
QPushButton#workshopPrimary {
    background: #577d4d;
    color: white;
    border: 1px solid #577d4d;
    border-radius: 11px;
    padding: 10px 14px;
    min-height: 20px;
    font-weight: 700;
}
QPushButton#workshopPrimary:hover { background: #4b7043; border-color: #4b7043; }
QPushButton#workshopPrimary:pressed { padding-top: 12px; padding-bottom: 10px; }
QProgressBar#workshopCapability {
    background: #e4ded2;
    border: 0;
    border-radius: 4px;
    min-height: 8px;
    max-height: 8px;
}
QProgressBar#workshopCapability::chunk { background: #577d4d; border-radius: 4px; }
QLabel#workshopKindBadge {
    background: #efe8da;
    color: #5b564c;
    border: 1px solid #e2d7c5;
    border-radius: 8px;
    padding: 2px 7px;
    font-size: 11px;
    font-weight: 600;
}
QLabel#workshopSizeBadge {
    background: #f6ecda;
    color: #745f3c;
    border: 1px solid #e8d5b6;
    border-radius: 8px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}
QLabel#workshopStateBadge {
    background: #efebe3;
    color: #666158;
    border: 1px solid #e1d9cc;
    border-radius: 8px;
    padding: 2px 7px;
    font-size: 11px;
    font-weight: 600;
}
QLabel#workshopStateBadge[tone="ready"] {
    background: #e6efe2;
    color: #4f7c4d;
    border-color: #ccddc7;
}
QLabel#workshopStateBadge[tone="missing"] {
    background: #f8eddc;
    color: #94672f;
    border-color: #ead5b5;
}
QLabel#workshopInstallSizeCard {
    background: #f0e9da;
    color: #6f6248;
    border: 1px solid #e2d7c0;
    border-radius: 12px;
    padding: 10px 12px;
    font-size: 12px;
    font-weight: 600;
}
QLabel#workshopRecommendationReason {
    background: transparent;
    color: #53644d;
    border: 0;
    font-size: 12px;
    font-weight: 500;
}
QFrame#workshopHealthCard {
    background: #fffefa;
    border: 1px solid #ddd6c8;
    border-radius: 16px;
}
QWidget#workshopSortPopover {
    background: #fffefa;
    border: 1px solid #ddd6c8;
    border-radius: 12px;
}
QPlainTextEdit#workshopDownloadLog {
    background: #fffefa;
    color: #3f3c35;
    border: 1px solid #ddd6c8;
    border-radius: 12px;
    padding: 10px;
    font-family: "Cascadia Mono", "Microsoft YaHei UI";
    font-size: 11px;
}
QDialog#technicalDetails {
    background: #fffefa;
    border: 0;
}
QFrame#technicalDetailsPanel {
    background: #fffefa;
    border: 0;
    border-radius: 0;
}
QLabel#technicalDetailsTitle {
    background: transparent;
    color: #28261f;
    font-family: "Source Han Sans SC", "思源黑体", "Microsoft YaHei UI", "Microsoft YaHei";
    font-size: 21px;
    font-weight: 700;
}
QLabel#technicalDetailsSummary {
    background: transparent;
    color: #625f57;
    font-size: 13px;
    font-weight: 500;
}
QLabel#technicalDetailsHeading {
    background: transparent;
    color: #28261f;
    font-family: "Source Han Sans SC", "思源黑体", "Microsoft YaHei UI", "Microsoft YaHei";
    font-size: 13px;
    font-weight: 700;
}
QLabel#technicalDetailsBody {
    background: transparent;
    color: #4e4b44;
    font-size: 12px;
    font-weight: 500;
}
QLabel#technicalFactLabel {
    background: transparent;
    color: #777066;
    font-size: 11px;
    font-weight: 600;
}
QLabel#technicalFactValue {
    background: transparent;
    color: #403d37;
    font-size: 12px;
    font-weight: 500;
}
QLabel#technicalLink {
    background: transparent;
    color: #4b7043;
    font-size: 11px;
    font-weight: 600;
}
QFrame#techInfoCard {
    background: #f7f3eb;
    border: 1px solid #e4dbcc;
    border-radius: 10px;
}
QLabel#techInfoLabel {
    background: transparent;
    color: #777066;
    border: 0;
    font-size: 10px;
    font-weight: 500;
}
QLabel#techInfoValue {
    background: transparent;
    color: #302e29;
    border: 0;
    font-size: 12px;
    font-weight: 600;
}
QLabel#technicalCapability {
    background: #f4efe5;
    color: #5f6457;
    border: 1px solid #e1d8c9;
    border-radius: 8px;
    padding: 2px 7px;
    font-size: 10px;
    font-weight: 600;
}
QFrame#technicalBenchmark {
    background: transparent;
    border: 1px solid #e4dbcc;
    border-radius: 8px;
}
QWidget#technicalBenchmarkHeader {
    background: #f3eee5;
    border: 0;
}
QLabel#technicalBenchmarkHeaderText {
    background: transparent;
    color: #6d675d;
    border: 0;
    font-size: 10px;
    font-weight: 600;
}
QLabel#technicalBenchmarkCell {
    background: transparent;
    color: #403d37;
    border: 0;
    font-size: 11px;
    font-weight: 500;
}
QFrame#technicalEvaluation {
    background: #f1f5ee;
    border: 1px solid #dce6d7;
    border-radius: 10px;
}
QFrame#technicalEvaluation QLabel#technicalDetailsHeading,
QFrame#technicalEvaluation QLabel#technicalDetailsBody {
    background: transparent;
}
QWidget#technicalSection {
    background: transparent;
    border: 0;
}
QScrollArea#technicalDetailsScroll, QScrollArea#technicalDetailsScroll QWidget#qt_scrollarea_viewport,
QWidget#technicalDetailsScrollHost { background: transparent; border: 0; }
"""

# The QSS stays readable as ordinary Qt CSS while the actual palette comes
# from the shared application tokens above.
for _source, _token in (
    ("#f8f6f0", "page"),
    ("#f2f1ea", "sidebar"),
    ("#fbfaf6", "content"),
    ("#fffefa", "surface"),
    ("#faf5ea", "detail"),
    ("#f6f0e4", "detail"),
    ("#ddd6c8", "border"),
    ("#d4b783", "border_warm"),
    ("#577d4d", "green"),
    ("#4b7043", "green_hover"),
    ("#e4ebdd", "green_soft"),
    ("#f0f4ec", "green_subtle"),
    ("#28261f", "ink"),
    ("#6f6b61", "muted"),
):
    WORKSHOP_QSS = WORKSHOP_QSS.replace(_source, WORKSHOP_TOKENS[_token])


def _workshop_theme_override(theme) -> str:
    """Pin Workshop-owned surfaces and text to the semantic theme contract."""
    from .typography import TITLE_FONT_STACK, UI_FONT_STACK
    from .design.tokens import WEIGHT_SCALE
    return f"""
QLabel#workshopPageTitle, QLabel#workshopDetailTitle, QLabel#technicalDetailsTitle {{
    font-family: {TITLE_FONT_STACK}; font-weight: {WEIGHT_SCALE['heavy']};
}}
QLabel#workshopModelTitle, QLabel#technicalDetailsHeading {{
    font-family: {UI_FONT_STACK}; font-weight: {WEIGHT_SCALE['semibold']};
}}
QWidget#modelWorkshopRoot {{ background: {theme.app_background}; color: {theme.text}; }}
QFrame#workshopSidebar {{
    background: {theme.surface_muted}; color: {theme.text};
    border-color: {theme.border};
}}
QFrame#workshopContent,
QScrollArea#workshopScroll,
QScrollArea#workshopScroll QWidget#qt_scrollarea_viewport,
QWidget#workshopScrollHost {{
    background: {theme.surface}; color: {theme.text}; border-color: {theme.border};
}}
QFrame#workshopDetail {{
    background: {theme.surface_elevated}; color: {theme.text};
    border-color: {theme.border};
}}
QFrame#workshopDownloadActivity {{
    background: {theme.accent_soft}; border-color: {theme.border};
}}
QLabel#workshopDownloadActivityText,
QLabel#workshopGood,
QLabel#workshopRecommendationReason,
QLabel#technicalLink {{ color: {theme.success}; }}
QProgressBar#workshopDownloadActivityProgress,
QProgressBar#workshopCapability {{ background: {theme.surface_muted}; }}
QProgressBar#workshopDownloadActivityProgress::chunk,
QProgressBar#workshopCapability::chunk {{ background: {theme.success}; }}
QLabel#workshopPageTitle,
QLabel#workshopDetailTitle,
QLabel#workshopModelTitle,
QLabel#workshopSection,
QLabel#workshopComboHeading,
QLabel#workshopComboModel,
QLabel#technicalDetailsTitle,
QLabel#technicalDetailsHeading,
QLabel#technicalFactValue,
QLabel#techInfoValue,
QLabel#technicalBenchmarkCell {{ color: {theme.text}; }}
QLabel#workshopMuted,
QLabel#workshopRatingLabel,
QLabel#workshopRatingWord,
QLabel#workshopComboRole,
QLabel#technicalDetailsSummary,
QLabel#technicalDetailsBody {{ color: {theme.text_secondary}; }}
QLabel#workshopTiny,
QLabel#workshopMetricEvidence,
QLabel#workshopReferenceIndex,
QLabel#workshopComboStatus,
QLabel#workshopMonogram,
QLabel#technicalFactLabel,
QLabel#techInfoLabel,
QLabel#technicalBenchmarkHeaderText {{ color: {theme.text_muted}; }}
QFrame#workshopComboCard,
QFrame#workshopModelCard,
QFrame#workshopHealthCard,
QWidget#workshopSortPopover,
QFrame#modelDownloadCard,
QFrame#modelDownloadTitleBar,
QDialog#technicalDetails,
QFrame#technicalDetailsPanel {{
    background: {theme.surface_elevated}; color: {theme.text};
    border-color: {theme.border};
}}
QFrame#workshopModelCard[selected="true"] {{
    background: {theme.selected}; border-color: {theme.accent};
}}
QFrame#workshopModelCard:hover {{
    background: {theme.control_hover}; border-color: {theme.border_strong};
}}
QFrame#workshopModelCard[selected="true"]:hover {{
    background: {theme.selected}; border-color: {theme.accent_hover};
}}
QPushButton#workshopNav {{ color: {theme.text_secondary}; }}
QPushButton#workshopNav:hover {{ background: {theme.control_hover}; color: {theme.text}; }}
QPushButton#workshopNav:checked {{ background: {theme.accent_tint}; color: {theme.text}; }}
QPushButton#workshopTab,
QPushButton#workshopAction,
QPushButton#workshopSecondary {{
    background: {theme.control_background}; color: {theme.text}; border-color: {theme.border};
}}
QPushButton#workshopTab:hover,
QPushButton#workshopAction:hover,
QPushButton#workshopSecondary:hover {{
    background: {theme.control_hover}; border-color: {theme.border_strong};
}}
QPushButton#workshopTab:checked {{
    background: {theme.accent_tint}; color: {theme.text}; border-color: {theme.accent};
}}
QPushButton#workshopPrimary {{
    background: {theme.accent}; color: {theme.text_on_accent}; border-color: {theme.accent};
}}
QPushButton#workshopPrimary:hover {{ background: {theme.accent_hover}; border-color: {theme.accent_hover}; }}
QPushButton#workshopAction:disabled {{ background: {theme.surface_muted}; color: {theme.disabled}; }}
QLineEdit#workshopSearch,
QComboBox#workshopSourceCombo,
QComboBox#workshopSourceCombo QAbstractItemView,
QPlainTextEdit#workshopDownloadLog {{
    background: {theme.surface_input}; color: {theme.text}; border-color: {theme.border};
    selection-background-color: {theme.selected}; selection-color: {theme.text};
}}
QLineEdit#workshopSearch:focus,
QComboBox#workshopSourceCombo:hover {{ border-color: {theme.accent}; }}
QFrame#workshopRule {{ background: {theme.border}; }}
QLabel#workshopBadge,
QLabel#workshopRecommendationBadge,
QLabel#recTag,
QLabel#workshopStateBadge[tone="ready"],
QFrame#technicalEvaluation {{
    background: {theme.accent_soft}; color: {theme.success}; border-color: {theme.border};
}}
QLabel#workshopRatingAccuracy {{
    background: {theme.accent_soft}; color: {theme.success}; border-color: {theme.border};
}}
QLabel#workshopRatingSpeed,
QLabel#workshopStateBadge[tone="missing"] {{
    background: {theme.warning_soft}; color: {theme.warning}; border-color: {theme.border};
}}
QLabel#workshopKindBadge,
QLabel#workshopSizeBadge,
QLabel#workshopStateBadge,
QLabel#langPill,
QLabel#technicalCapability {{
    background: {theme.surface_muted}; color: {theme.text_secondary}; border-color: {theme.border};
}}
QLabel#workshopInstallSizeCard,
QFrame#techInfoCard,
QWidget#technicalBenchmarkHeader {{
    background: {theme.surface_muted}; color: {theme.text}; border-color: {theme.border};
}}
QFrame#technicalBenchmark {{ border-color: {theme.border}; }}
QLabel#modelDownloadChromeTitle {{ color: {theme.text}; }}
QPushButton#modelDownloadChromeClose:hover {{ background: {theme.danger_soft}; }}
"""


def build_workshop_qss(theme=None) -> str:
    """Build Workshop QSS from the active application theme."""
    from .qss_retheme import retheme_qss
    from .theme_manager import theme_key
    from .ui_theme import theme_definition

    active = theme or theme_definition(theme_key())
    from .design.control_qss import build_control_qss
    from .design.surface_qss import build_surface_qss
    return retheme_qss(WORKSHOP_QSS, active) + _workshop_theme_override(active) + build_control_qss(active) + build_surface_qss(active)


class ModelCard(QFrame):
    selected = Signal(str)
    action_requested = Signal(str)
    download_requested = Signal(str)
    uninstall_requested = Signal(str)
    api_configure_requested = Signal(str)

    def __init__(self, model: WorkshopModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.setObjectName("workshopModelCard")
        self.setProperty("selected", False)
        self.setProperty("recommended", bool(getattr(model, "recommended", False)))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(176)
        self._compact = None
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(16, 13, 16, 13)
        self._root.setSpacing(10)
        self._row = QHBoxLayout()
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(16)
        self._root.addLayout(self._row, 1)

        self.monogram = QLabel()
        self.monogram.setObjectName("workshopMonogram")
        self.monogram.setProperty("selected", False)
        self.monogram.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.monogram.setFixedSize(52, 52)
        self.monogram.setToolTip(model.name)
        logo_size = QSize(44, 44) if model.logo_asset else QSize(28, 28)
        self._paint_monogram(logo_size)
        self._row.addWidget(self.monogram, 0, Qt.AlignmentFlag.AlignVCenter)

        self.info_host = QWidget(self)
        self.info_host.setObjectName("workshopCardInfo")
        text = QVBoxLayout(self.info_host)
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(5)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(7)
        # 长模型名（如 Qwen-Audio-3.0-ASR-Flash）在窄卡片单行必然被省略号
        # 截断（标题列仅 ~170px）；允许两行折行保证完整显示（三十二轮 agy）。
        if len(model.name) > 18:
            self.title_label = QLabel(model.name)
            self.title_label.setWordWrap(True)
            self.title_label.setToolTip(model.name)
        else:
            self.title_label = ElideLabel(model.name)
        bind_text(self.title_label, model.name)
        bind_text(self.title_label, model.name, property='toolTip')
        self.title_label.setObjectName("workshopModelTitle")
        title_row.addWidget(self.title_label, 1)
        self.recommendation_badge = None
        if getattr(model, "recommended", False):
            self.recommendation_badge = PillLabel(
                "★ 2ByteASR 推荐", "workshopRecommendationBadge"
            )
            title_row.addWidget(
                self.recommendation_badge, 0, Qt.AlignmentFlag.AlignVCenter
            )
        text.addLayout(title_row)
        summary_row = QHBoxLayout()
        summary_row.setContentsMargins(0, 0, 0, 0)
        summary_row.setSpacing(7)
        self.summary_label = QLabel(model_scene(model))
        self.summary_label.setWordWrap(True)
        self.summary_label.setMinimumWidth(0)
        self.summary_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.summary_label.setObjectName("workshopMuted")
        summary_row.addWidget(self.summary_label, 1)
        text.addLayout(summary_row)

        meta_stack = QVBoxLayout()
        meta_stack.setContentsMargins(0, 0, 0, 0)
        meta_stack.setSpacing(3)
        size_row = QHBoxLayout()
        size_row.setContentsMargins(0, 0, 0, 0)
        size_text = ui_literal(_install_size_label(model.size), current_language())
        self.size_label = PillLabel(size_text, "workshopSizeBadge")
        bind_text(self.size_label, '体积 {size_text}', property='accessibleName', size_text=size_text)
        self.size_label.setToolTip(SIZE_NOTE)
        size_row.addWidget(self.size_label, 0, Qt.AlignmentFlag.AlignLeft)
        size_row.addStretch(1)
        meta_stack.addLayout(size_row)
        self.language_pills = []
        languages = model_task_badges(model)
        for start in range(0, len(languages), 3):
            language_row = QHBoxLayout()
            language_row.setContentsMargins(0, 0, 0, 0)
            language_row.setSpacing(5)
            for lang in languages[start : start + 3]:
                pill = PillLabel(str(lang), "langPill")
                self.language_pills.append(pill)
                language_row.addWidget(pill, 0, Qt.AlignmentFlag.AlignLeft)
            language_row.addStretch(1)
            meta_stack.addLayout(language_row)
        text.addLayout(meta_stack)
        self._row.addWidget(self.info_host, 4)

        self.metrics_host = QWidget(self)
        self.metrics_host.setObjectName("workshopCardMetrics")
        self.metrics_host.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        metrics = QVBoxLayout(self.metrics_host)
        metrics.setContentsMargins(0, 0, 0, 0)
        metrics.setSpacing(4)
        self.reference_index_label = QLabel("2ByteASR 参考指数")
        self.reference_index_label.setObjectName("workshopReferenceIndex")
        self.reference_index_label.setToolTip(COMPARISON_NOTE)
        metrics.addWidget(self.reference_index_label)
        metric_row = QHBoxLayout()
        metric_row.setContentsMargins(0, 0, 0, 0)
        metric_row.setSpacing(18)
        self.accuracy_bar = RatingBar(
            "转写准确度", _metric_evidence(model, "accuracy"), label_width=72
        )
        self.speed_bar = RatingBar(
            "速度指数", _metric_evidence(model, "speed"), label_width=64
        )
        metric_row.addWidget(self.accuracy_bar, 1)
        metric_row.addWidget(self.speed_bar, 1)
        metrics.addLayout(metric_row)

        self.action_host = QWidget(self)
        self.action_host.setObjectName("workshopCardActions")
        self.action_host.setMinimumWidth(94)
        self.action_host.setMaximumWidth(122)
        action_box = QVBoxLayout(self.action_host)
        action_box.setContentsMargins(0, 0, 0, 0)
        action_box.setSpacing(5)
        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        badge_row.setSpacing(5)
        badge_row.addStretch(1)
        # 卡片右侧空间窄（94-136px）：长徽章会与状态徽章互挤截断成
        # "线 · A"（三十二轮 agy）。在线属性一个词足够，服务商在副标题。
        self.kind_badge = PillLabel(
            "在线" if model_is_online(model) else "本地",
            "workshopKindBadge",
        )
        badge_row.addWidget(self.kind_badge)
        self.state_badge = PillLabel("", "workshopStateBadge")
        self.state_badge.setProperty("tone", "muted")
        badge_row.addWidget(self.state_badge)
        action_box.addLayout(badge_row)
        self.action_controls = QWidget(self.action_host)
        action_controls = QVBoxLayout(self.action_controls)
        action_controls.setContentsMargins(0, 0, 0, 0)
        action_controls.setSpacing(5)
        action_controls.addStretch(1)
        self.action = QPushButton()
        self.action.setObjectName("workshopAction")
        self.action.setMinimumWidth(82)
        self.action.clicked.connect(lambda: self.action_requested.emit(model.key))
        action_controls.addWidget(self.action)
        self.download = bind_text(QPushButton(), "下载")
        self.download.setObjectName("workshopAction")
        self.download.clicked.connect(lambda: self.download_requested.emit(model.key))
        self.download.setVisible(bool(model.variants))
        action_controls.addWidget(self.download)
        self.uninstall = QPushButton("卸载")
        self.uninstall.setObjectName("workshopCardUninstall")
        bind_text(self.uninstall, '永久删除已确认归属的模型文件；再次使用需要下载', property='toolTip')
        self.uninstall.clicked.connect(lambda: self.uninstall_requested.emit(model.key))
        self.uninstall.hide()
        action_controls.addWidget(self.uninstall)
        # 三十四轮：API 卡加显式「配置」入口——配置完成后用户没有任何办法
        # 再次打开 key/模型/地址编辑窗（"使用"已不再弹窗）。
        self.configure = QPushButton("配置")
        self.configure.setObjectName("workshopCardUninstall")
        bind_text(self.configure, '打开该服务的模型、地址与 API Key 配置窗口', property='toolTip')
        self.configure.setCursor(Qt.CursorShape.PointingHandCursor)
        self.configure.clicked.connect(
            lambda: self.api_configure_requested.emit(model.api_preset or "")
        )
        if not model.api_preset:
            self.configure.hide()
        action_controls.addWidget(self.configure)
        action_controls.addStretch(1)
        action_box.addWidget(self.action_controls, 1)
        self._row.addWidget(self.action_host, 0)
        self._root.addWidget(self.metrics_host)
        # Unavailable evidence never acquires a synthetic score. The shared
        # card layout still owns the right-side controls for every model.
        self.metrics_host.setVisible(any(
            bool(_metric_evidence(model, kind).get("available"))
            for kind in ("accuracy", "speed")
        ))
        self.info_host.setMinimumWidth(0)
        self.info_host.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        available_width = self.width()
        ancestor = self.parentWidget()
        while ancestor is not None:
            if isinstance(ancestor,QScrollArea):
                available_width = min(available_width, ancestor.viewport().width())
                break
            ancestor = ancestor.parentWidget()
        self._apply_compact_layout(available_width < 760)

    def _apply_compact_layout(self, compact: bool):
        if self._compact is compact:
            return
        self._compact = compact
        if compact:
            self._root.setContentsMargins(16, 8, 16, 8)
            self._root.setSpacing(8)
            self._row.setSpacing(12)
            self.action_host.setMinimumWidth(94)
            self.action_host.setMaximumWidth(122)
            self.action.setMinimumWidth(82)
        else:
            self._root.setContentsMargins(16, 8, 16, 8)
            self._root.setSpacing(8)
            self._row.setSpacing(16)
            self.action_host.setMinimumWidth(108)
            self.action_host.setMaximumWidth(138)
            self.action.setMinimumWidth(92)
        self.accuracy_bar.apply_compact(compact)
        self.speed_bar.apply_compact(compact)
        self.updateGeometry()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.model.key)
        super().mousePressEvent(event)

    def set_selected(self, selected: bool):
        selected = bool(selected)
        if getattr(self, "_selected_state", None) is selected:
            return
        self._selected_state = selected
        self.setProperty("selected", selected)
        self.monogram.setProperty("selected", selected)
        for widget in (self, self.monogram):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def set_uninstall_available(self, visible: bool, enabled: bool = True):
        visible = bool(visible)
        enabled = bool(enabled)
        if self.uninstall.isVisible() != visible:
            self.uninstall.setVisible(visible)
        if self.uninstall.isEnabled() != enabled:
            self.uninstall.setEnabled(enabled)

    def _paint_monogram(self, logo_size=None):
        """Vendor logos keep their own look; the generic placeholder (models
        without a logo or a vendor colour) follows the active theme instead of
        a light-green tile that glares on dark themes (2026-10-07)."""
        model = self.model
        logo_size = logo_size or (QSize(44, 44) if model.logo_asset else QSize(28, 28))
        generic = not model.logo_asset and model.icon_background == WorkshopModel.icon_background
        if generic:
            from .theme_manager import theme_key
            from .ui_theme import theme_definition
            theme = theme_definition(theme_key())
            self.monogram.setPixmap(_icon(model.icon_name, theme.accent_text).pixmap(logo_size))
            self.monogram.setStyleSheet(
                f"background: {theme.surface_elevated}; border: 1px solid {theme.border}; border-radius: 10px;")
            return
        self.monogram.setPixmap(_model_logo(model, logo_size).pixmap(logo_size))
        if not model.logo_asset:
            # 品牌图标卡（如 MAI 的 fa5b.microsoft）需要实心底色块；
            # QSS 的 workshopMonogram 默认透明，白线框在深色主题下发空
            #（三十三轮 agy）。
            self.monogram.setStyleSheet(
                f"background: {model.icon_background}; border-radius: 10px;"
            )

    def refresh_theme_palette(self):
        self._paint_monogram()

    def set_state_badge(self, text: str, tone: str = "muted"):
        label = str(text or "").strip()
        normalized_tone = tone if tone in {"ready", "missing", "muted"} else "muted"
        state = (label, normalized_tone)
        if getattr(self, "_state_badge_state", None) == state:
            return
        self._state_badge_state = state
        self.state_badge.setProperty("tone", normalized_tone)
        self.state_badge.setText(label)
        self.state_badge.setVisible(bool(label))
        self.state_badge.style().unpolish(self.state_badge)
        self.state_badge.style().polish(self.state_badge)

    def set_reference_role(
        self, role: str, scene: str | None = None, api_model: str | None = None
    ):
        # role 保留给卡片其它语义；评分随「比较场景 + 实际解析型号」变化。
        signature = (role, scene, api_model, current_language())
        if getattr(self, "_reference_signature", None) == signature:
            return  # every filter / refresh pass re-applies the same values
        self._reference_signature = signature
        scope = model_metric_scene(self.model, scene or _DEFAULT_BENCHMARK_SCENE)
        bind_text(self.reference_index_label, '2ByteASR 参考指数 · {value0}', value0=_benchmark_scene_label(scope, current_language()))
        self.accuracy_bar.set_evidence(
            _metric_evidence(self.model, "accuracy", role, scene, api_model)
        )
        self.speed_bar.set_evidence(
            _metric_evidence(self.model, "speed", role, scene, api_model)
        )










class _DownloadTitleBar(QFrame):
    def __init__(self, dialog: "ModelDownloadDialog", title: str):
        super().__init__(dialog)
        self.dialog = dialog
        self._drag_offset: QPoint | None = None
        self.setObjectName("modelDownloadTitleBar")
        self.setFixedHeight(42)
        row = QHBoxLayout(self)
        row.setContentsMargins(15, 5, 8, 5)
        self.title = QLabel(title)
        self.title.setObjectName("modelDownloadChromeTitle")
        row.addWidget(self.title)
        row.addStretch(1)
        close = QPushButton()
        close.setObjectName("modelDownloadChromeClose")
        close.setIcon(qta.icon("fa5s.times", color="#9b5c4f"))
        close.setIconSize(QSize(14, 14))
        bind_text(close, '关闭', property='toolTip')
        bind_text(close, '关闭下载窗口', property='accessibleName')
        close.clicked.connect(dialog._hide_without_stopping)
        row.addWidget(close)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.dialog.windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
            self._drag_offset = (
                event.globalPosition().toPoint() - self.dialog.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.dialog.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)


# Display names for download sources when an event carries only the internal mode.
_SOURCE_NAMES = {'MODELSCOPE': 'ModelScope', 'HF_OFFICIAL': 'Hugging Face 官方', 'HF_MIRROR': 'HF 镜像（可能回源官方）'}

# Plain-language reason shown when AUTO moves on to the next download source.
_SOURCE_FAILURE_REASONS = {
    'network_timeout': '连接超时', 'dns': '域名无法解析', 'connection': '连接中断', 'proxy': '代理无法连接',
    'tls_certificate': '证书验证失败', 'http_access': '拒绝访问', 'source_unavailable': '没有该文件',
    'rate_limited': '暂时限流', 'checksum': '文件校验未通过', 'invalid_response': '返回内容不正确',
    'revision_incompatible': '版本与锁定不同', 'disk_space': '磁盘空间不足', 'permission': '没有写入权限',
}


class ModelDownloadDialog(QDialog):
    diagnostic_finished = Signal(object)
    completed = Signal(bool, str)

    def refresh_theme_palette(self) -> None:
        self.setStyleSheet(build_workshop_qss())

    def __init__(
        self,
        root: Path,
        model: WorkshopModel,
        parent=None,
        *,
        download_keys: tuple[str, ...] | list[str] | None = None,
        display_name: str | None = None,
    ):
        super().__init__(parent)
        self.root = root
        self.model = model
        requested = download_keys or ([model.download_key] if model.download_key else [])
        self.download_keys = tuple(dict.fromkeys(str(key) for key in requested if key))
        self.display_name = display_name or model.name
        language = current_language()
        self._output_buffer = ""
        self._paused = False
        self._finished_ok = False
        self._result_sound_played = False
        self._phase = 'preparing'
        self.process = _HiddenProcessBridge(self) if os.name == "nt" or sys.platform == 'darwin' else QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.finished.connect(self._finished_v2)
        (bind_text(self, f'Download {self.display_name} - 2ByteASR', property='windowTitle') if language == 'en' else bind_text(self, '下载 {value0} - 2ByteASR', property='windowTitle', value0=self.display_name))
        self.setObjectName("modelDownloadDialog")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(False)
        # Do not auto-delete while a download may be running in background.
        # We allow closing the window without stopping the task.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.resize(760, 520)
        self.setMinimumSize(420, 280)
        from .window_constraints import install_window_bounds
        install_window_bounds(self, within_parent=True)
        self.setStyleSheet(build_workshop_qss())

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("modelDownloadCard")
        shell.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 0, 22, 20)
        layout.setSpacing(12)
        self.title_bar = _DownloadTitleBar(self, self.windowTitle())
        layout.addWidget(self.title_bar)
        title = QLabel(
            f"Preparing {self.display_name}"
            if language == "en"
            else ui_literal("正在准备 {name}", language).format(name=self.display_name)
        )
        title.setObjectName("workshopDetailTitle")
        layout.addWidget(title)
        note = QLabel("窗口会一直保留；可断点续传，不需要重新安装 2ByteASR。")
        if sys.platform == 'darwin' and set(self.download_keys) <= MLX_DOWNLOAD_KEYS:
            note.setText('Apple Silicon 本地模型（MLX）：首次准备会联网下载私有运行库（不含 PyTorch）与模型，'
                         '完成后用自带的英文样本实际跑一次推理。社区 MLX 实现，兔白尚未在真机完成验收。')
            note.setWordWrap(True)
        elif sys.platform == 'darwin' and set(self.download_keys) <= MAC_GPU_INSTALL_KEYS:
            note.setText('Apple 芯片 GPU（MPS）：首次准备会联网下载 PyTorch 运行库与模型，完成后在这台 Mac 上用自带样本实际跑一次，'
                         '通过才启用。MOSS 与 FireRed 用的是共享内存，建议 16 GB 以上；内存较小时请先关闭其他程序。')
            note.setWordWrap(True)
        elif sys.platform == 'darwin':
            from .platform_macos import macos_copy
            note.setText(macos_copy(
                '当前使用 SenseVoice CPU：模型 MPS 适配尚未验证。首次准备自动联网；取消后已校验资源保持。',
                'SenseVoice uses CPU: model support for MPS is not verified. Initial preparation connects automatically; verified resources remain after cancellation.',
                'SenseVoice は CPU を使用します。モデルの MPS 対応は未検証です。初回は自動で接続し、中止後も検証済みリソースは保持します。'))
            note.setWordWrap(True)
        note.setObjectName("workshopMuted")
        layout.addWidget(note)
        source_row = QHBoxLayout()
        source_row.setSpacing(7)
        source_label = QLabel("下载源")
        source_label.setObjectName("workshopTiny")
        source_row.addWidget(source_label)
        self.source_combo = QComboBox()
        self.source_combo.setObjectName("workshopSourceCombo")
        for choice in user_facing_source_choices():
            self.source_combo.addItem(choice["label"], choice["mode"])
        self.source_combo.setCurrentIndex(0)
        source_row.addWidget(self.source_combo)
        self.check_download_button = QPushButton('检查模型下载')
        self.check_download_button.setObjectName('workshopSecondary')
        self.check_download_button.clicked.connect(self._check_download)
        source_row.addWidget(self.check_download_button)
        self.copy_diagnostic_button = QPushButton('复制诊断')
        self.copy_diagnostic_button.setObjectName('workshopSecondary')
        self.copy_diagnostic_button.clicked.connect(self._copy_diagnostic)
        self.copy_diagnostic_button.setEnabled(False)
        source_row.addWidget(self.copy_diagnostic_button)
        self._diagnostic_report = None
        self._diagnostic_cancel = threading.Event()
        self.diagnostic_finished.connect(self._diagnostic_complete)
        source_row.addStretch(1)
        layout.addLayout(source_row)
        self.progress = QProgressBar()
        self.progress.setObjectName("workshopCapability")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.progress_status = QLabel("选择下载源后，点击“开始下载”。")
        self.progress_status.setObjectName("workshopTiny")
        self.progress_status.setWordWrap(True)
        layout.addWidget(self.progress_status)
        self.log = QPlainTextEdit()
        self.log.setObjectName("workshopDownloadLog")
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(0)
        self.log_toggle = QPushButton('查看原始日志')
        self.log_toggle.setCheckable(True)
        self.log_toggle.toggled.connect(self.log.setVisible)
        layout.addWidget(self.log_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.log, 1)
        self.log.hide()
        self.activity_status = QLabel('尚未启动')
        self.activity_status.setWordWrap(True)
        layout.addWidget(self.activity_status)
        self._last_log_at = 0.0
        self._activity_timer = QTimer(self)
        self._activity_timer.timeout.connect(self._refresh_activity_clock)
        self._activity_timer.start(1000)
        # Structured runtime state for real progress (P0-5 / P0-6)
        self._current_file = ""
        self._files_seen: list[str] = []
        self._file_total_expected = max(1, len(self.download_keys))
        self._last_bytes = 0
        self._last_time = 0.0
        self._speed = 0.0
        self._started_at = 0.0
        self._total_bytes_hint = 0  # best known total for current file if provided
        self._overall_file_index = 0
        self._overall_file_total = max(1, len(self.download_keys))
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.start_button = QPushButton("开始下载")
        if sys.platform == 'darwin' and self.download_keys == ('sensevoice',):
            self.start_button.setProperty('platformPrepare', 'sensevoice-cpu')
        elif sys.platform == 'darwin' and set(self.download_keys) <= MAC_GPU_INSTALL_KEYS:
            self.start_button.setProperty('platformPrepare', 'mac-gpu')
        self.start_button.setObjectName("workshopPrimary")
        self.start_button.clicked.connect(self.start)
        actions.addWidget(self.start_button)
        # P0-7: "关闭窗口" must not stop a running download. Provide explicit pause control.
        self.close_button = QPushButton("关闭窗口（后台继续）")
        self.close_button.setObjectName("workshopSecondary")
        self.close_button.clicked.connect(self._hide_without_stopping)
        actions.addWidget(self.close_button)
        # Explicit pause control (only visible while running)
        self.pause_button = QPushButton("暂停下载")
        self.pause_button.setObjectName("workshopSecondary")
        self.pause_button.setVisible(False)
        self.pause_button.clicked.connect(self._request_pause)
        actions.addWidget(self.pause_button)
        layout.addLayout(actions)
        apply_ui_language(self, language)


    def _copy_diagnostic(self):
        from PySide6.QtWidgets import QApplication
        if self._diagnostic_report is not None:
            QApplication.clipboard().setText(json.dumps(self._diagnostic_report, ensure_ascii=False, indent=2))

    def _check_download(self):
        from .runtime_paths import get_runtime_paths
        model_root = get_runtime_paths().model_root
        mode = str(self.source_combo.currentData() or 'AUTO')
        self._diagnostic_cancel.clear()
        self.check_download_button.setEnabled(False)
        self.check_download_button.setText('正在检查…')
        def work():
            try:
                from .model_download_diagnostic import check_downloads
                report = check_downloads(self.root, model_root, self.download_keys, mode, cancel=self._diagnostic_cancel)
            except Exception as exc:
                from .download_diagnostics import redact
                report = dict(error=redact(str(exc)), upload=False)
            self.diagnostic_finished.emit(report)
        threading.Thread(target=work, name='model-download-diagnostic', daemon=True).start()

    def _diagnostic_complete(self, report):
        from .runtime_paths import user_data_root
        self._diagnostic_report = report
        self.check_download_button.setEnabled(True)
        self.check_download_button.setText('检查模型下载')
        self.copy_diagnostic_button.setEnabled(True)
        directory = user_data_root() / 'diagnostics'
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / ('model-download-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.json')
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
            self.log.appendPlainText('诊断已保存：' + str(path))
        except OSError as exc:
            self.log.appendPlainText('诊断保存失败；仍可点击“复制诊断”：' + str(exc))
        for model in report.get('models', []):
            for source in model['sources']:
                for probe in source['probes']:
                    self.log.appendPlainText(f"{model['key']} · {source['mode']} · {probe['file']}：{probe['status']} " + str(probe.get('category','')))
        for probe in report.get('bootstrap', []):
            self.log.appendPlainText(f"环境准备 · {probe['stage']}：{probe['status']} " + str(probe.get('category','')))
        if report.get('error'):
            self.log.appendPlainText('自检未完成：' + report['error'])
        self.log.appendPlainText('检查只读取受限大小的文件前缀，不代表完整下载、安装或推理通过；报告未上传。')
        self.log_toggle.setChecked(True)

    def start(self):
        if self._finished_ok:
            self.close()
            return
        if self.process.state() != QProcess.ProcessState.NotRunning:
            return
        from .runtime_paths import get_runtime_paths, model_folder_name
        from .model_associations import is_model_detached
        paths = get_runtime_paths()
        lock = _load_lock(self.root)
        detached = [key for key in self.download_keys if is_model_detached(
            paths.model_root / model_folder_name(str((lock.get('models', {}).get(key) or {}).get('path', key))))]
        if detached:
            self._finish_with_error(tr('模型外部目录已解除关联。请在模型存储管理中选择受管存储位置，或重新关联原目录后再下载；不会覆盖已解除关联的外部文件。'))
            return
        if set(self.download_keys) & MLX_DOWNLOAD_KEYS and not _host_platform_tag() == 'darwin-arm64':
            self._finish_with_error(tr('MLX 模型只能在 Apple Silicon（M 系列芯片）的 Mac 上使用；没有开始下载。'))
            return
        if sys.platform == 'darwin':
            mac_gpu = bool(self.download_keys) and set(self.download_keys) <= MAC_GPU_INSTALL_KEYS
            if mac_gpu and _host_platform_tag() != 'darwin-arm64':
                self._finish_with_error(tr('MOSS 与 FireRed 需要 Apple 芯片（M 系列）Mac 的 GPU；这台 Mac 没有，没有开始下载。'))
                return
            if (self.download_keys != ('sensevoice',) and not set(self.download_keys) <= MLX_DOWNLOAD_KEYS
                    and not mac_gpu):
                from .platform_macos import macos_copy
                self._finish_with_error(macos_copy(
                    '本次 macOS 实验支持 SenseVoice CPU、MLX、MOSS 与 FireRed；其他本地模型尚未完成原生适配。',
                    'This macOS build supports SenseVoice CPU, MLX, MOSS and FireRed. Other local models are not yet adapted.',
                    '今回の macOS 版は SenseVoice CPU・MLX・MOSS・FireRed に対応しています。他のローカルモデルは未対応です。'))
                return
        elif os.name != "nt":
            self.log.appendPlainText(
                "The automatic model workshop installer requires Windows. "
                "For the macOS experiment use scripts/macos_prepare_runtime.py "
                "and scripts/macos_prepare_model.py for SenseVoice CPU. "
                "No Windows installer was started."
            )
            return
        self._finished_ok = False
        import time
        self._started_at = time.monotonic()
        self._last_log_at = 0.0
        self._phase = 'preparing'
        self._output_buffer = ''
        self._files_seen.clear()
        self._current_file = ''
        self._paused = False
        self._result_sound_played = False
        self.progress.setRange(0, 0)
        language = current_language()
        bind_text(self.progress_status, translate('正在准备下载来源…', language))
        self.start_button.show()
        self.source_combo.setEnabled(False)
        self.start_button.setEnabled(False)
        bind_text(self.start_button, translate('正在下载…', language))
        bind_text(self.close_button, translate('关闭窗口（后台继续）', language))
        self.pause_button.setVisible(True)
        bind_text(self.pause_button, translate('暂停下载', language))
        if sys.platform == 'darwin':
            if set(self.download_keys) <= MLX_DOWNLOAD_KEYS:
                self._start_macos_mlx()
            elif set(self.download_keys) <= MAC_GPU_INSTALL_KEYS:
                self._start_macos_local()
            else:
                self._start_macos_cpu()
            return
        script = self.root / "scripts" / "download_models.ps1"
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        program = str(powershell if powershell.is_file() else "powershell.exe")
        arguments = [
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-Yes",
            "-Only",
            ",".join(self.download_keys),
            "-Source",
            str(self.source_combo.currentData() or "AUTO"),
        ]
        self.log.appendPlainText(
            f"[模型工坊] 开始准备 {self.display_name}：{'、'.join(self.download_keys)}\n"
        )
        self.process.setWorkingDirectory(str(self.root))
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUTF8", "1")
        environment.insert("PYTHONIOENCODING", "utf-8")
        try:
            from twobyteasr.runtime_paths import MODEL_ROOT_ENV, get_runtime_paths

            environment.insert(MODEL_ROOT_ENV, str(get_runtime_paths().model_root))
        except Exception:
            pass
        self.process.setProcessEnvironment(environment)
        self.process.start(program, arguments)
        if not self.process.waitForStarted(5000):
            self._finish_with_error("无法启动模型下载器。请运行“配置或修复 2ByteASR”后重试。")

    def _start_macos_mlx(self):
        from twobyteasr.runtime_paths import get_runtime_paths, user_data_root
        from twobyteasr.processes import sanitized_child_environment
        arguments = ['--macos-prepare-mlx', '--root', str(self.root), '--models',
                     str(get_runtime_paths().model_root), '--keys', ','.join(self.download_keys),
                     '--source', str(self.source_combo.currentData() or 'AUTO')]
        program = sys.executable
        if not getattr(sys, 'frozen', False):
            arguments.insert(0, str(self.root / 'scripts/macos_launch.py'))
        environment = QProcessEnvironment()
        for key, value in sanitized_child_environment().items():
            environment.insert(key, value)
        environment.insert('PYTHONUTF8', '1')
        environment.insert('PYTHONIOENCODING', 'utf-8')
        environment.insert('_PYI_RESET_ENVIRONMENT', '1')
        self.process.setProcessEnvironment(environment)
        user_data_root().mkdir(parents=True, exist_ok=True)
        self.process.setWorkingDirectory(str(user_data_root()))
        self.log.appendPlainText('[模型工坊] 准备 Apple Silicon MLX 运行库与模型：' + '、'.join(self.download_keys))
        self.process.start(program, arguments)
        if not self.process.waitForStarted(5000):
            self._finish_with_error('无法启动 MLX 准备进程；已有运行库和模型文件保持。')

    def _start_macos_local(self):
        """MOSS / FireRed: private PyTorch runtimes + locked models, checked on the Apple GPU."""
        from twobyteasr.runtime_paths import get_runtime_paths, user_data_root
        from twobyteasr.processes import sanitized_child_environment
        arguments = ['--macos-prepare-local', '--root', str(self.root), '--models',
                     str(get_runtime_paths().model_root), '--keys', ','.join(self.download_keys),
                     '--source', str(self.source_combo.currentData() or 'AUTO')]
        program = sys.executable
        if not getattr(sys, 'frozen', False):
            arguments.insert(0, str(self.root / 'scripts/macos_launch.py'))
        environment = QProcessEnvironment()
        for key, value in sanitized_child_environment().items():
            environment.insert(key, value)
        environment.insert('PYTHONUTF8', '1')
        environment.insert('PYTHONIOENCODING', 'utf-8')
        environment.insert('_PYI_RESET_ENVIRONMENT', '1')
        self.process.setProcessEnvironment(environment)
        user_data_root().mkdir(parents=True, exist_ok=True)
        self.process.setWorkingDirectory(str(user_data_root()))
        self.log.appendPlainText(tr('[模型工坊] 准备 Apple 芯片 GPU（MPS）运行库与模型：') + '、'.join(self.download_keys)
                                 + tr('；首次需要联网下载运行库（约 1–3 GB）和模型，完成后会在这台 Mac 上实际试跑一次。'))
        self.process.start(program, arguments)
        if not self.process.waitForStarted(5000):
            self._finish_with_error(tr('无法启动 Mac 准备进程；已有运行库和模型文件保持。'))

    def _start_macos_cpu(self):
        from twobyteasr.runtime_paths import get_runtime_paths, user_data_root
        from twobyteasr.processes import sanitized_child_environment
        arguments = ['--macos-prepare-cpu', '--root', str(self.root), '--models',
                     str(get_runtime_paths().model_root), '--source', str(self.source_combo.currentData() or 'AUTO')]
        if getattr(sys, 'frozen', False):
            program = sys.executable
        else:
            program = sys.executable
            arguments.insert(0, str(self.root / 'scripts/macos_launch.py'))
        environment = QProcessEnvironment()
        for key, value in sanitized_child_environment().items():
            environment.insert(key, value)
        environment.insert('PYTHONUTF8', '1')
        environment.insert('PYTHONIOENCODING', 'utf-8')
        environment.insert('_PYI_RESET_ENVIRONMENT', '1')
        self.process.setProcessEnvironment(environment)
        user_data_root().mkdir(parents=True, exist_ok=True)
        self.process.setWorkingDirectory(str(user_data_root()))
        from .platform_macos import macos_copy
        self.log.appendPlainText(macos_copy(
            '[模型工坊] 准备私有原生 CPU 运行库并校验 SenseVoice；首次使用需要联网。',
            '[Model Workshop] Preparing a private native CPU runtime and verifying SenseVoice. Initial preparation requires Internet access.',
            '[モデル工房] 専用 CPU 実行環境と SenseVoice を準備・検証します。初回はインターネット接続が必要です。'))
        self.process.start(program, arguments)
        if not self.process.waitForStarted(5000):
            self._finish_with_error('无法启动 Mac 原生准备进程；已有运行库和模型文件保持。')

    def _read_output(self):
        raw = bytes(self.process.readAllStandardOutput())
        if raw:
            import time
            self._last_log_at = time.monotonic()
            decoded = raw.decode("utf-8", errors="replace")
            self._output_buffer += decoded
            lines = self._output_buffer.split("\n")
            self._output_buffer = lines.pop()
            from .download_diagnostics import redact
            clean_lines = [redact(line.rstrip('\r')) for line in lines]
            for line in clean_lines:
                self._handle_progress_line(line)
            self.log.moveCursor(QTextCursor.MoveOperation.End)
            # Buffer whole lines before redaction: credentials can span pipe reads.
            self.log.insertPlainText('\n'.join(clean_lines) + ('\n' if clean_lines else ''))
            # 下载 URL 行很长：ensureCursorVisible 会把无折行日志横向带到
            # 行尾（与运行日志同族问题）。光标停回行首后再 ensure，纵向
            # 依然追尾、横向落在第 0 列；再显式钉住左缘兜底。
            self.log.moveCursor(QTextCursor.MoveOperation.StartOfLine)
            self.log.ensureCursorVisible()
            from .ui import keep_log_view_at_left

            keep_log_view_at_left(self.log)

    def _refresh_activity_clock(self):
        if not self._started_at:
            return
        import time
        now = time.monotonic()
        active = self.process.state() != QProcess.ProcessState.NotRunning
        age = f'{int(now-self._last_log_at)} 秒前' if self._last_log_at else '尚无日志'
        state = '任务进程存活' if active else '任务进程已结束'
        bind_text(self.activity_status, '{state} · 已用 {value1} 秒 · 最后日志：{age}', state=state, value1=int(now - self._started_at), age=age)

    def _handle_progress_line(self, line: str):
        state = self._download_state()
        if line.startswith("[2BYTEASR_CACHE] "):
            try:
                payload = json.loads(line[len("[2BYTEASR_CACHE] "):])
            except json.JSONDecodeError:
                return
            name = str(payload.get("file") or "")
            state['done'][(state['model_seq'], name)] = int(payload.get("bytes") or 0)
            state['note'] = tr('已沿用校验过的文件：{name}（不重新下载）', name=name)
            state['note_kind'] = 'cache'
            self.progress_status.setText("\n".join(item for item in (self._overall_progress_line(), self._source_detail_line()) if item))
            return
        if '次中断（已有进展' in line or line.lstrip().startswith('[恢复分片]'):
            state['resumes'] += 1
            state['note'] = tr('网络中断，已从断点续传（第 {count} 次），已下载的部分不会重下', count=state['resumes'])
            return
        if line.startswith('[重试] '):
            state['resumes'] += 1
            state['note'] = tr('来源暂时没有响应，稍后自动重试（第 {count} 次），已下载的部分保留', count=state['resumes'])
            self.progress_status.setText("\n".join(item for item in (self._overall_progress_line(), self._source_detail_line()) if item))
            return
        # Structured file marker emitted by downloaders: reveals the real filename immediately
        if line.startswith("[2BYTEASR_FILE] "):
            try:
                payload = json.loads(line[len("[2BYTEASR_FILE] "):])
            except Exception:
                return
            fname = str(payload.get("file") or "").strip()
            fsize = int(payload.get("size") or 0)
            idx = payload.get("index")
            tot = payload.get("total")
            if fname and isinstance(idx, int):
                state['file_key'] = (state['model_seq'], fname)
                if state.get('note_kind') == 'cache':
                    state.update(note='', note_kind='')  # the reuse note belonged to an earlier file
            if fname:
                if not self._files_seen or self._files_seen[-1] != fname:
                    self._files_seen.append(fname)
                self._current_file = fname
                self._total_bytes_hint = fsize
                # The downloader repeats each file with only name and size; the
                # repository marker before it already set "file i / n".
                if isinstance(idx, int) and idx > 0:
                    self._overall_file_index = idx
                elif 'size' not in payload:
                    self._overall_file_index = max(1, len(self._files_seen))
                if isinstance(tot, int) and tot > 0:
                    self._overall_file_total = tot
                elif 'size' not in payload:
                    self._overall_file_total = max(self._overall_file_total, len(self._files_seen))
                # Emit a log line for visibility
                self.log.appendPlainText(f"正在下载：{fname}")
                # Update status line right away with file context
                self._update_real_progress_ui(0, 0, 0, phase="start")
            return

        source_marker = "[2BYTEASR_SOURCE] "
        if line.startswith(source_marker):
            try:
                payload = json.loads(line[len(source_marker):])
            except json.JSONDecodeError:
                return
            label = (payload.get("label") or _SOURCE_NAMES.get(str(payload.get("mode") or ""))
                     or payload.get("mode") or "下载源")
            host = payload.get("host") or ""
            status = payload.get("status") or ""
            attempt = payload.get("attempt")
            total = payload.get("total")
            # Events carrying a URL are the downloader's per-file attempts; only the
            # repository-level events (no URL) say which source the model uses.
            per_file = bool(payload.get('url'))
            if per_file:
                pass
            elif status == 'trying':
                if attempt == 1:
                    state['model_seq'] += 1
                state.update(source=str(label), host=str(host), attempt=int(attempt or 0), total=int(total or 0), note='')
            elif status == 'failed':
                state['failed'].append((str(label), str(payload.get('category') or '')))
            elif status == 'selected':
                state.update(source=str(label), host=str(host), verified=True,
                             note=tr('全部文件已通过 SHA-256 校验，与锁定版本一致'))
            if not per_file and status == 'trying' and attempt and int(attempt) > 1 and state['failed']:
                previous, category = state['failed'][-1]
                language = current_language()
                reason = tr(_SOURCE_FAILURE_REASONS.get(category, '未完成'))
                bind_text(self.progress_status, '{previous} 没有完成（{reason}），自动改试 {label}{host} · 第 {attempt}/{total} 个来源',
                          previous=tr(previous), reason=reason, label=tr(str(label)),
                          host=(f' ({host})' if language == 'en' else f'（{host}）') if host else '', attempt=attempt, total=total)
                return
            host_bit = f"（{host}）" if host else ""
            language = current_language()
            if language == "en":
                host_bit = f" ({host})" if host else ""
            if status == "selected":
                (bind_text(self.progress_status, f'Selected {label}{host_bit}') if language == 'en' else bind_text(self.progress_status, '已选用 {value0}{value1}', value0=label, value1=host_bit))
            elif status == 'skipped':
                bind_text(self.progress_status, '跳过 {label}：{value1}', label=label, value1=payload.get('detail', tr('版本不匹配')))
            elif status == "unavailable":
                (bind_text(self.progress_status, f'{label}{host_bit} does not host this file') if language == 'en' else bind_text(self.progress_status, '{value0}{value1} 没有该文件', value0=label, value1=host_bit))
            elif attempt and total and int(total) > 1:
                (bind_text(self.progress_status, f'Automatic fallback {attempt}/{total}: trying {label}{host_bit}') if language == 'en' else bind_text(self.progress_status, '自动回退 {value0}/{value1}：正在尝试 {value2}{value3}', value0=attempt, value1=total, value2=label, value3=host_bit))
            else:
                (bind_text(self.progress_status, f'Downloading from {label}{host_bit}') if language == 'en' else bind_text(self.progress_status, '正在从 {value0}{value1} 下载', value0=label, value1=host_bit))
            return
        phase_marker = "[2BYTEASR_PHASE] "
        if line.startswith(phase_marker):
            try:
                payload = json.loads(line[len(phase_marker):])
            except json.JSONDecodeError:
                return
            phase = str(payload.get("phase") or "")
            self._phase = phase
            label = {
                "tools_preparing": "正在准备应用私有工具…",
                "preparing": "正在准备…",
                "weights_downloading": "正在下载模型权重…",
                "weights_ready": "权重已就绪，正在检查 Runtime 与 Adapter…",
                "runtime_installing": "Runtime 安装中…",
                "interpreter_preparing": "正在准备应用私有 Python…",
                "dependencies_installing": "正在安装所选模型的独立依赖…",
                "model_loading": "权重已校验，正在实际加载模型…",
                "files_verifying": "正在校验必需文件与锁定版本…",
                "model_forward": "正在验证设备张量运算与模型前向…",
                "inference_verifying": "正在运行本地人声样本验证…",
                "runtime_ready": "Runtime 已就绪，正在验证 Adapter…",
                "adapter_verifying": "Adapter 验证中…",
                "ready": "模型已安装 · 可使用",
                "downloading": "正在下载模型权重…",
                "environment": "正在安装所选模型的独立依赖…",
                "loading": "权重已校验，正在实际加载模型…",
                "completed": "模型已安装 · 可使用" if payload.get('inference_success') else "权重完整 · 推理待验证",
            }.get(phase)
            if label:
                self.progress_status.setText(label)
            if phase in {'environment','loading'}:self.progress.setRange(0,0)
            if phase=='completed' and payload.get('inference_success'):self._phase='ready'
            if payload.get('file'):
                done, total = int(payload.get('downloaded', 0)), int(payload.get('total', 0))
                speed = float(payload.get('bytes_per_second', 0)) / (1024**2)
                self.progress_status.setText(f"{payload['file']} · {done/(1024**2):.1f}/{total/(1024**2):.1f} MiB · {speed:.1f} MiB/s")
                if total:
                    self.progress.setRange(0, 100)
                    self.progress.setValue(min(99, int(done * 100 / total)))
            return
        marker = "[2BYTEASR_PROGRESS] "
        if not line.startswith(marker):
            language = current_language()
            if line.startswith("[回退]") or line.startswith("[自动]"):
                (bind_text(self.progress_status, 'Trying download sources in order...') if language == 'en' else bind_text(self.progress_status, line.lstrip('[回退]').lstrip('[自动]').strip() or '正在按顺序尝试下载源…'))
            elif line.startswith("[下载]"):
                self.progress_status.setText(
                    "Downloading..." if language == "en" else line
                )
            elif line.startswith(('[工具] ', '[运行库] ', '[网络] ')):
                # Runtime preparation (uv, private Python, packages) reports which
                # source it is trying and why it moved on; those lines are written
                # for people, so show them (Chinese UI) instead of a generic label.
                detail = line.split('] ', 1)[1]
                path = re.search(r'[A-Za-z]:\\', detail)
                if path:  # command echoes and install paths are for the raw log only
                    detail = detail[:path.start()].strip()
                if detail and str(language).startswith('zh'):
                    self.progress_status.setText(ui_literal(detail, language))
            elif ("SHA-256" in line or "校验" in line) and self._phase in {
                    'weights_downloading', 'downloading', 'files_verifying', 'weights_ready'}:
                bind_text(self.progress_status, translate('正在校验模型文件完整性…', language))
            return
        try:
            payload = json.loads(line[len(marker):])
            if payload.get('phase')=='verify':self._phase='files_verifying'
            percent = int(round(float(payload.get("percent", 0))))
            downloaded = float(payload.get("downloaded", 0))
            total = float(payload.get("total", 0))
            speed = float(payload.get("speed", 0))
            # Optional richer fields from downloader
            if "file" in payload and not self._current_file:
                self._current_file = str(payload.get("file") or "")
            if "file_index" in payload and isinstance(payload.get("file_index"), (int, float)):
                self._overall_file_index = int(payload["file_index"]) or self._overall_file_index
            if "file_total" in payload and isinstance(payload.get("file_total"), (int, float)) and int(payload["file_total"]) > 0:
                self._overall_file_total = int(payload["file_total"]) or self._overall_file_total
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        if state['file_key'] is not None:
            done = total if payload.get('phase') == 'verify' and total else downloaded
            state['done'][state['file_key']] = max(int(done), state['done'].get(state['file_key'], 0))
        self._update_real_progress_ui(downloaded, total, speed, phase=str(payload.get("phase", "download")), percent_hint=percent)

    def _update_real_progress_ui(self, downloaded: float, total: float, speed: float, *, phase: str, percent_hint: int | None = None):
        # Track speed using deltas when the downloader does not provide it
        import time as _time
        now = _time.monotonic()
        if self._last_time <= 0:
            self._last_time = now
            self._last_bytes = int(downloaded or 0)
        delta_b = max(0, int(downloaded or 0) - self._last_bytes)
        delta_t = max(0.001, now - self._last_time)
        inst_speed = (delta_b / delta_t) if delta_t > 0 else 0.0
        if speed and speed > 0:
            self._speed = speed
        else:
            # EMA smoothing
            self._speed = 0.6 * self._speed + 0.4 * inst_speed if self._speed > 0 else inst_speed
        self._last_bytes = int(downloaded or 0)
        self._last_time = now

        # Compute percent robustly
        pct = 0
        if total and total > 0:
            pct = int(round((downloaded or 0) * 100.0 / total))
        elif percent_hint is not None:
            pct = int(max(0, min(100, percent_hint)))

        self.progress.setRange(0, 100 if total and total > 0 else 0)
        if total and total > 0:
            self.progress.setValue(max(0, min(pct, 100)))

        # Compose a rich status line:
        # e.g. 正在下载 model.safetensors  (2 / 5)
        #      1.82 GB / 4.40 GB   41%   32.4 MB/s   预计剩余 ~1分12秒
        language = current_language()
        parts = []
        fname = self._current_file or ""
        if fname:
            parts.append(
                f"Downloading {fname}"
                if language == "en"
                else ui_literal("正在下载 {name}", language).format(name=fname)
            )
        if self._overall_file_total > 1:
            fi = max(1, self._overall_file_index or (len(self._files_seen) or 1))
            parts.append(
                f"File {fi} / {self._overall_file_total}"
                if language == "en"
                else ui_literal("文件 {index} / {total}", language).format(index=fi, total=self._overall_file_total)
            )
        if phase == "verify":
            bind_text(self.progress_status, translate('下载完成，正在校验 SHA-256 与固定版本…', language))
            return
        overall_line = self._overall_progress_line()
        detail_line = self._source_detail_line()

        size_part = ""
        if total and total > 0:
            d_mb = (downloaded or 0) / (1024 * 1024)
            t_mb = total / (1024 * 1024)
            size_part = f"{d_mb/1024:.2f} GiB / {t_mb/1024:.2f} GiB" if t_mb >= 1024 else f"{d_mb:.2f} MiB / {t_mb:.2f} MiB"
        elif self._total_bytes_hint > 0:
            t_mb = self._total_bytes_hint / (1024 * 1024)
            d_mb = (downloaded or 0) / (1024 * 1024)
            size_part = f"{d_mb/1024:.2f} GiB / {t_mb/1024:.2f} GiB" if t_mb >= 1024 else f"{d_mb:.2f} MiB / {t_mb:.2f} MiB"

        pct_part = f"{pct}%" if pct else ""
        spd_part = ""
        if self._speed and self._speed > 0:
            if self._speed >= 1024 ** 3:
                spd_part = f"{self._speed / (1024**3):.1f} GiB/s"
            elif self._speed >= 1024 ** 2:
                spd_part = f"{self._speed / (1024**2):.1f} MiB/s"
            elif self._speed >= 1024:
                spd_part = f"{self._speed / 1024:.1f} KiB/s"
            else:
                spd_part = f"{self._speed:.0f} B/s"

        # ETA (rough)
        eta = ""
        if total and total > 0 and self._speed and self._speed > 0:
            remain = max(0.0, total - (downloaded or 0))
            secs = int(round(remain / self._speed))
            if secs >= 3600:
                eta = (
                    f"About {secs//3600} h {(secs%3600)//60} min remaining"
                    if language == "en"
                    else ui_literal("预计剩余 {h} 小时 {m} 分", language).format(h=secs//3600, m=(secs%3600)//60)
                )
            elif secs >= 60:
                eta = (
                    f"About {secs//60} min {secs%60} sec remaining"
                    if language == "en"
                    else ui_literal("预计剩余 {m} 分 {s} 秒", language).format(m=secs//60, s=secs%60)
                )
            else:
                eta = (
                    f"About {secs} sec remaining"
                    if language == "en"
                    else ui_literal("预计剩余 {s} 秒", language).format(s=secs)
                )

        if overall_line:
            eta = ""  # the overall line carries the estimate for the whole model
        line = "  ·  ".join([p for p in [size_part, pct_part, spd_part, eta] if p])
        prefix = "  ".join(parts) if parts else (
            "Downloading" if language == "en" else ui_literal("下载中", language)
        )
        if line:
            self.progress_status.setText("\n".join(item for item in (prefix, line, overall_line, detail_line) if item))
        else:
            bind_text(self.progress_status, prefix or translate('下载中…', language))

    def _download_state(self) -> dict:
        """Per-run download facts parsed from the installer's structured lines."""
        state = getattr(self, '_dl', None)
        if state is None or state.get('run') != self._started_at:
            total = 0
            try:
                models = _load_lock(self.root).get('models', {})
                total = sum(int((models.get(key) or {}).get('download_bytes') or 0) for key in self.download_keys)
            except Exception:
                total = 0
            state = self._dl = dict(run=self._started_at, model_total=total, model_seq=0, file_key=None, done={},
                                    source='', host='', attempt=0, total=0, failed=[], resumes=0,
                                    verified=False, note='')
        return state

    def _overall_progress_line(self) -> str:
        state = self._download_state()
        total = state['model_total']
        done = min(sum(state['done'].values()), total) if total else 0
        if not total or not done:
            return ''
        percent = int(done * 100 / total)
        self.progress.setRange(0, 100)
        self.progress.setValue(min(99, percent))
        remain = ''
        # Small config files finish before a speed is meaningful (a 1.6 MB file
        # at 266 B/s gave "about 5337 hours" in the 2026-10-14 mainland run).
        seconds = int((total - done) / self._speed) if self._speed and self._speed > 0 and total > done else -1
        if self._total_bytes_hint >= 8 << 20 and 0 <= seconds < 48 * 3600:
            remain = tr('剩余约 {h} 小时 {m} 分', h=seconds // 3600, m=(seconds % 3600) // 60) if seconds >= 3600 else (
                tr('剩余约 {m} 分 {s} 秒', m=seconds // 60, s=seconds % 60) if seconds >= 60 else tr('剩余约 {s} 秒', s=seconds))
        gib = 1024 ** 3
        size = f'{done / gib:.2f} / {total / gib:.2f} GiB' if total >= gib else f'{done / 1024**2:.0f} / {total / 1024**2:.0f} MiB'
        text = tr('整个模型 {size}（{percent}%）', size=size, percent=percent)
        return f'{text}  ·  {remain}' if remain else text

    def _source_detail_line(self) -> str:
        state = self._download_state()
        if not state['source']:
            return state['note']
        host = f" ({state['host']})" if state['host'] else ''
        parts = [tr('来源：{label}', label=tr(state['source'])) + host]
        if state['total'] > 1:
            parts.append(tr('第 {attempt}/{total} 个来源', attempt=state['attempt'], total=state['total']))
        if state['note']:
            parts.append(state['note'])
        return '  ·  '.join(parts)

    def _actionable_failure_message(self, exit_code: int) -> str:
        output = self.log.toPlainText()
        lowered = output.lower()
        if self._paused:
            return '任务已取消；已校验文件可复用。下次准备会检查文件并在来源支持时续传。'
        # Structured installer failures take precedence over normal log words
        # such as “Qwen 已存在，纳入校验”. Preserve the first failed stage.
        sources=[]
        failures=[]
        for line in output.splitlines():
            if line.startswith('[2BYTEASR_SOURCE] '):
                try:
                    event=json.loads(line.split(' ',1)[1])
                    if event.get('status')=='trying' and event.get('mode') not in sources:
                        sources.append(event['mode'])
                except (ValueError,TypeError): pass
            if line.startswith(('[2BYTEASR_INSTALL_ERROR] ', '[2BYTEASR_ERROR] ')):
                try:
                    failures.append(json.loads(line.split(' ', 1)[1]))
                except (ValueError, TypeError):
                    continue
        if failures:
                failure=failures[-1]
                if sources:
                    tried=' → '.join(tr(_SOURCE_NAMES.get(mode, mode)) for mode in sources)
                    header=f"{self.model.name} · {tried}（{'已尝试备援' if len(sources)>1 else '未尝试备援'}）\n"
                elif failure.get('phase') in {'tools_preparing', 'interpreter_preparing', 'dependencies_installing'}:
                    header=f"{self.model.name} · 运行环境准备阶段（尚未开始下载权重）\n"
                else:
                    header=f"{self.model.name} · 尚未请求权重源（未尝试备援）\n"
                detail=str(failure.get('message') or failure.get('detail') or '').partition('\n')[0][:220]
                category=failure.get('category','')
                if category=='runtime_network':
                    # A conflict, permission or disk problem also makes every source fail.
                    if 'no solution found' in lowered or 'unsatisfiable' in lowered:category='dependency_conflict'
                    elif 'os error 5' in lowered or 'access is denied' in lowered or '拒绝访问' in output:category='permission'
                    elif 'no space left' in lowered or 'disk full' in lowered or 'os error 112' in lowered or '磁盘空间不足' in output:category='disk_space'
                summaries={'permission':'准备目录不可写或文件被占用，请检查日志中的具体路径后重试。',
                    'disk_space':'磁盘空间不足，请为应用数据目录释放空间后重试。',
                    'http_access':'来源拒绝访问（401/403）。请检查该模型的授权要求或选择已验证来源。',
                    'source_unavailable':'锁定版本或文件不存在（404）。请复制诊断反馈，不要反复重下。',
                    'network_timeout':'来源连接或传输停滞超时。请重试或切换已验证来源。',
                    'runtime_network':'运行环境（uv、Python、PyTorch 等）下载失败：官方来源和国内备用来源都没有连通。可以打开代理工具的 TUN（虚拟网卡）模式，或设置 HTTPS_PROXY 环境变量并重启程序后重试；已校验的文件会保留。',
                    'connection':'连接中断。已下载分片保留，请检查网络后重试。',
                    'dns':'来源域名无法解析。请检查当前网络并复制诊断。',
                    'proxy':'程序使用的代理无法连接。请检查下载诊断中的代理状态。',
                    'tls_certificate':'TLS 证书验证失败。请检查系统时间与证书；程序不会关闭安全验证。',
                    'rate_limited':'来源暂时限流（429）。请稍后重试。',
                    'invalid_response':'来源返回了错误页或不正确的文件范围；文件没有安装。请切换已验证来源。',
                    'checksum':'文件未通过锁定哈希校验，未标记安装完成。请重试或切换已验证来源。',
                    'hardware_unsupported':'当前硬件无法执行此模型，已校验权重和运行库会保留。',
                    'dependency_conflict':'依赖版本冲突，请保留包名与版本日志；更换模型下载源不能解决此问题。'}
                if not category and ('no solution found' in lowered or 'unsatisfiable' in lowered):category='dependency_conflict'
                if (len(sources) > 1 and failure.get('phase') == 'weights_downloading'
                        and category in {'network_timeout', 'connection', 'dns', 'proxy', 'tls_certificate', 'rate_limited'}):
                    # AUTO already tried every source; "switch source" is not advice the user can act on.
                    return header+tr('所有下载来源都没有连通。已下载并校验的部分会保留，稍后点“继续重试”会从断点继续。'
                                     '如果一直失败：先确认这台电脑能正常打开网页再重试；仍不行时可开启代理工具的 TUN（虚拟网卡）模式后重试。')+'\n'+detail
                if category in summaries:return header+summaries[category]+'\n'+detail
                stage = {'tools_preparing':'工具准备失败', 'interpreter_preparing':'解释器准备失败', 'dependencies_installing':'依赖安装失败',
                         'weights_downloading':'权重下载或校验失败', 'model_loading':'模型加载失败',
                         'model_forward':'设备/模型前向验证失败', 'inference_verifying':'真实样本推理失败'}.get(failure.get('phase'), '运行库安装失败')
                return header+f"{stage}：{detail}\n已校验的文件会保留。请展开日志查看该阶段的具体错误后重试。"
        if 'no python available to start repair' in lowered:
            return '解释器准备失败：安装器未发现可用于启动修复的 Python。\n这不代表权重损坏；请使用支持私有 Python 自举的安装入口。'
        if "os error 5" in lowered or "拒绝访问" in output or "access is denied" in lowered:
            return (
                "运行库文件无法写入，可能是目录权限不足或文件被占用。\n\n"
                "展开日志查看具体路径，确认该应用数据目录可写后重试。"
            )
        if "no solution found" in lowered or "unsatisfiable" in lowered:
            return (
                "运行库依赖版本无法兼容，安装尚未完成。\n\n"
                "请保留日志中的包名与版本冲突信息；模型权重下载源不会解决依赖冲突。"
            )
        if '磁盘空间不足' in output or 'no space left' in lowered or 'disk full' in lowered:
            return '磁盘空间不足，准备已停止。请为应用数据目录所在磁盘释放空间后重试。'
        if self._phase in {'preparing', 'runtime_installing', 'tools_preparing', 'interpreter_preparing', 'dependencies_installing'}:
            return f'运行环境准备失败（退出码 {exit_code}）。\n展开日志查看工具、Python 或依赖安装的具体错误；模型下载尚未完成。'
        mode = str(self.source_combo.currentData() or "AUTO")
        host = ""
        for line in reversed(output.splitlines()):
            if line.startswith("[2BYTEASR_SOURCE] "):
                try:
                    payload = json.loads(line.split(" ", 1)[1])
                    host = str(payload.get("host") or "")
                    mode = str(payload.get("mode") or mode)
                except (json.JSONDecodeError, IndexError):
                    pass
                break
        if self._paused:
            category = "cancelled"
        else:
            category = classify_error_text(output)
        error = user_facing_error(
            DownloadSourceError(category, source_mode=mode, host=host, detail=output[-800:])
        )
        return f"{error.message}\n{error.next_action}"

    def _finished_v2(self, exit_code: int, _status):
        self._read_output()
        ok = exit_code == 0 and not self._paused
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if ok else self.progress.value())
        bind_text(self.close_button, '关闭')
        self.pause_button.setVisible(False)
        self._finished_ok = ok
        (bind_text(self.start_button, '完成') if ok else bind_text(self.start_button, '继续重试'))
        self.start_button.setEnabled(True)
        self.start_button.setVisible(True)
        self.source_combo.setEnabled(not ok)
        if self._paused:
            message = "任务已暂停。重试会校验已有资源；同一版本且来源支持续传时复用分片。"
        elif ok:
            message = (
                "✓ 已完成真实加载与样本验证"
                if self._phase == 'ready' else
                "✓ 文件与运行库准备完成 · 使用时验证模型加载"
                if self.model.runtime_available
                else "✓ 权重已校验 · Windows 推理适配不可用"
            )
        else:
            message = self._actionable_failure_message(exit_code)
        self.progress_status.setText(message)
        self.log.appendPlainText(f"\n[{'完成' if ok else '未完成'}] {message}")
        if not self._paused:
            self._notify_result_sound(ok)
        self.completed.emit(ok, message)

    def _notify_result_sound(self, ok: bool) -> None:
        if self._result_sound_played:
            return
        self._result_sound_played = True
        _play_download_result_sound(ok)

    def _finished(self, exit_code: int, _status):
        self._read_output()
        ok = exit_code == 0
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if ok else 0)
        (bind_text(self.close_button, '已完成') if ok else bind_text(self.close_button, '关闭'))
        (bind_text(self.start_button, '已完成') if ok else bind_text(self.start_button, '继续重试'))
        self.start_button.setEnabled(not ok)
        self.start_button.setVisible(not ok)
        self.source_combo.setEnabled(not ok)
        message = "模型已经准备好。" if ok else f"下载器退出码：{exit_code}。已完成的分片会保留，可直接重试。"
        self.log.appendPlainText(f"\n[{'完成' if ok else '未完成'}] {message}")
        self.completed.emit(ok, message)

    def _finish_with_error(self, message: str):
        self._finished_ok = False
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        bind_text(self.close_button, '关闭')
        bind_text(self.start_button, '继续重试')
        self.start_button.setEnabled(True)
        self.start_button.show()
        self.source_combo.setEnabled(True)
        self.pause_button.setVisible(False)
        self.log.appendPlainText(f"[错误] {message}")
        self._notify_result_sound(False)
        self.completed.emit(False, message)

    def _request_pause(self):
        """Explicit pause requested by the Pause button (does not close window)."""
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self._paused = True
            process_id = int(self.process.processId())
            if os.name == "nt" and process_id:
                run_hidden_subprocess(
                    ["taskkill", "/PID", str(process_id), "/T", "/F"],
                    purpose="pause model download process tree",
                    runner=subprocess.run,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                return
            self.process.terminate()
            if not self.process.waitForFinished(2500):
                self.process.kill()
            return

    def _hide_without_stopping(self):
        """Close/hide the dialog without terminating the download process.
        The download task keeps running; the dialog can be reopened later.
        """
        if self.process.state() != QProcess.ProcessState.NotRunning:
            # Keep process alive; just hide the window.
            self.hide()
            return
        self.close()

    def _cancel_or_close(self):
        # Legacy path (e.g., title-bar close). For running tasks, prefer hide.
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self._hide_without_stopping()
            return
        self.close()

    def closeEvent(self, event):
        self._diagnostic_cancel.set()
        # P0-7: Closing the details window must NOT stop a running download.
        # The task continues in background. Re-opening the workshop/model page
        # will allow viewing progress by re-showing this dialog instance.
        if self.process.state() != QProcess.ProcessState.NotRunning:
            # Do not kill; just hide the window. Keep process + signals alive.
            self.hide()
            event.accept()
            return
        event.accept()


class ModelTechnicalDialog(QWidget):
    """Compact evidence-first technical panel (content card).

    Intended to be hosted inside MainWindow.ModalHost for no new native HWND.
    When used directly (tests/capture), it can be wrapped by a thin SpringDialog.
    Card is always 100% opaque, shown at final size; only host backdrop fades.
    No geometry animation.
    """

    _ROLE_COPY = {
        "primary": "主力转写：为整段素材建立第一版字幕骨架。",
        "timeline": "字幕时间轴：补足字幕片段、字词的起止时间。",
        "review": "文字复核：用第二路识别结果发现文字和术语差异。",
        "api": "在线识别：作为可配置的云端转写或复核来源。",
    }

    def refresh_theme_palette(self) -> None:
        self.setStyleSheet(build_workshop_qss())

    def __init__(
        self,
        model: WorkshopModel,
        parent=None,
        *,
        role: str | None = None,
        scene: str | None = None,
        api_model: str | None = None,
    ):
        super().__init__(parent)
        self.model = model
        self.reference_role = str(role or model.role)
        self.benchmark_scene = str(
            scene if scene in _BENCHMARK_SCENES else _DEFAULT_BENCHMARK_SCENE
        )
        self.api_model = str(api_model or "")
        self.setObjectName("technicalDetails")
        self.setStyleSheet(build_workshop_qss())
        self.setMinimumSize(0, 0)
        # Detect hosting by MainWindow ModalHost body to avoid assuming QDialog API.
        self._hosted = False
        try:
            p = parent
            while p:
                if hasattr(p, "objectName") and (p.objectName() == "modalCardBody" or hasattr(p, "_modal_host")):
                    self._hosted = True
                    break
                p = p.parentWidget() if hasattr(p, "parentWidget") else None
        except Exception:
            pass
        self._rendered_language = current_language()
        self._build()

    def retranslate_ui(self):
        self.retranslate(current_language())

    def retranslate(self, language: str | None = None):
        """Refresh localized content while preserving the cached panel object."""
        language = language or current_language()
        if language == self._rendered_language:
            return False
        old_panel = getattr(self, "_content_panel", None)
        if old_panel is not None:
            self.layout().removeWidget(old_panel)
            old_panel.hide()
            old_panel.setParent(None)
            old_panel.deleteLater()
        self._rendered_language = language
        self._build()
        return True

    def _build(self):
        outer = self.layout()
        if outer is None:
            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)

        panel = QFrame()
        panel.setObjectName("technicalDetailsPanel")
        self._content_panel = panel
        outer.addWidget(panel, 1)
        # P0-4: wider padding ~24-28px, use dialog width, no full-column yellow.
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(26, 22, 26, 18)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        title = QLabel(self.model.name)
        title.setObjectName("technicalDetailsTitle")
        title.setWordWrap(True)
        title_box.addWidget(title)
        language = current_language()
        # Summary right under name (second line), before param cards.
        summary = QLabel(translate(self.model.summary, language))
        summary.setObjectName("technicalDetailsSummary")
        summary.setWordWrap(True)
        title_box.addWidget(summary)
        top.addLayout(title_box, 1)
        # ★ rec + mode in header row (name is always first visual layer)
        if getattr(self.model, "recommended", False):
            rec = PillLabel(
                translate("★ 2ByteASR 推荐", language), "recTag"
            )
            top.addWidget(rec, 0, Qt.AlignmentFlag.AlignTop)
        mode = PillLabel(
            translate("在线 API" if model_is_online(self.model) else "本地模型", language),
            "workshopKindBadge",
        )
        top.addWidget(mode, 0, Qt.AlignmentFlag.AlignTop)
        if not getattr(self, "_hosted", False):
            xbtn = QPushButton("×")
            xbtn.setObjectName("flat")
            xbtn.setFixedSize(28, 28)
            xbtn.clicked.connect(self._close_self)
            top.addWidget(xbtn, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

        # Fetch profile early so 4 param cards and later sections use the same data.
        profile = _technical_profile(self.model)
        try:
            if _get_eval_profile is not None:
                extra = _get_eval_profile(self.model.key, current_language())
                if isinstance(extra, dict) and extra:
                    # The external module is the audited source of truth.  A
                    # shallow copy is enough because the panel never mutates
                    # nested metadata.
                    profile.update(extra)
        except Exception:
            pass

        # 4 key param mini-cards immediately after header+summary line.
        # Only light bg on these cards (not whole column yellow). Wider padding ~24-28px at panel level.
        off = profile.get("official") or {}
        def _mini(title, val):
            c = QFrame()
            c.setObjectName("techInfoCard")
            c.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            l = QVBoxLayout(c)
            l.setContentsMargins(10, 7, 10, 8)
            l.setSpacing(2)
            t = QLabel(title)
            t.setObjectName("techInfoLabel")
            v = QLabel(str(val) if val else "—")
            v.setObjectName("techInfoValue")
            v.setWordWrap(True)
            v.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            l.addWidget(t)
            l.addWidget(v)
            return c
        info_row = QHBoxLayout()
        info_row.setSpacing(8)
        dev = off.get("developer") or "—"
        prm = off.get("params") or "—"
        langs = off.get("language_summary") or off.get("languages")
        if isinstance(langs, (list, tuple)):
            langs = ", ".join(langs)
        elif not langs:
            langs = "—"
        if profile.get("model_type"):
            mtype = translate(str(profile["model_type"]), language)
        elif model_is_online(self.model):
            mtype = translate("在线 ASR", language)
        elif self.model.key == "moss":
            mtype = translate("ASR · 说话人", language)
        elif self.model.role == "timeline":
            mtype = translate("ASR · 时间轴", language)
        elif self.model.role == "review":
            mtype = translate("ASR · 复核", language)
        else:
            mtype = translate("本地 ASR", language)
        info_row.addWidget(_mini(translate("开发者", language), dev), 1)
        info_row.addWidget(_mini(translate("参数量", language), prm), 1)
        info_row.addWidget(_mini(translate("支持语言", language), langs), 1)
        info_row.addWidget(_mini(translate("模型类型", language), mtype), 1)
        layout.addLayout(info_row)

        rule = QFrame()
        rule.setObjectName("workshopRule")
        rule.setFixedHeight(1)
        layout.addWidget(rule)

        scroll = QScrollArea()
        scroll.setObjectName("technicalDetailsScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("technicalDetailsScrollHost")
        body = QVBoxLayout(host)
        body.setContentsMargins(0, 8, 0, 6)
        body.setSpacing(18)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)

        # Header and four parameter cards carry the high-signal identity
        # metadata. The scroll body adds non-duplicated official fields and
        # workflow context in a single reading order.
        facts = [
            (translate("架构", language), off.get("architecture")),
            (translate("支持方言", language), off.get("dialects")),
            (tr("音频类型"), off.get("audio_type")),
            (tr("许可协议"), off.get("license")),
            (translate("官方 Runtime", language), off.get("runtime")),
        ]
        self._add_facts_section(
            body,
            translate("基础信息", language),
            [(label, str(value)) for label, value in facts if value],
        )

        responsibility = str(profile.get("responsibility") or self._ROLE_COPY.get(self.model.role, ""))
        self._add_section(
            body,
            translate("在 2ByteASR 中的职责", language),
            responsibility,
        )

        caps = [str(item) for item in (profile.get("capabilities") or []) if str(item).strip()]
        self._add_capability_section(body, translate("核心能力", language), caps)

        language_items = off.get("languages") or []
        if isinstance(language_items, str):
            language_items = [language_items]
        language_lines = [f"{translate(label, language)}: {value}" for label, value in (
            ('语言摘要', off.get('language_summary')),
            ('语言列表', ', '.join(map(str, language_items))),
            ('方言与口音', off.get('dialects')),
            ('代码切换', off.get('code_switching')),
            ('歌唱支持', off.get('singing_support')),
            ('来源', off.get('language_source') or off.get('repo')),
        ) if value]
        if "languages_fully_enumerated" in off:
            language_lines.append(f"{translate('枚举状态', language)}: " + translate(
                "官方已完整枚举" if off["languages_fully_enumerated"] else "官方仅提供摘要或未完整枚举", language))
        self._add_section(
            body,
            translate("支持语言与方言", language),
            "\n".join(language_lines),
        )

        benchmarks = [item for item in (profile.get("benchmarks") or []) if isinstance(item, dict)]
        concrete_benchmarks = [
            item for item in benchmarks
            if self._has_concrete_benchmark_value(str(item.get("value", "")))
        ]
        self._add_benchmark_section(
            body,
            translate("官方 Benchmark", language),
            concrete_benchmarks,
            translate("官方未提供可直接比较的公开数值。", language),
            next(
                (
                    str(item.get("source"))
                    for item in benchmarks
                    if str(item.get("source") or "").strip()
                ),
                "",
            ),
        )

        condition_parts: dict[str, list[str]] = {
            translate("评测口径", language): [],
            translate("硬件", language): [],
            translate("指标方向", language): [],
            translate("资料版本", language): [],
        }
        for benchmark in benchmarks:
            for key, label in (
                ("condition", translate("评测口径", language)),
                ("hardware", translate("硬件", language)),
                ("direction", translate("指标方向", language)),
                ("source_updated", translate("资料版本", language)),
            ):
                value = str(benchmark.get(key, "")).strip()
                if value and value not in condition_parts[label]:
                    condition_parts[label].append(value)
        fallback_condition = str(
            profile.get("condition") or profile.get("test_condition") or ""
        ).strip()
        condition_key = translate("评测口径", language)
        if fallback_condition and fallback_condition not in condition_parts[condition_key]:
            condition_parts[condition_key].append(fallback_condition)
        condition_lines = []
        for label, values in condition_parts.items():
            if values:
                condition_lines.append(f"{label}：{'；'.join(values)}")
        condition_text = "\n".join(condition_lines)
        if not condition_text:
            condition_text = translate("官方未单独提供可核对的测试条件。", language)
        condition_heading = "Benchmark 测试条件"
        self._add_section(body, translate(condition_heading, language), condition_text)

        principles = str(profile.get("principles") or "").strip()
        if principles:
            self._add_section(body, translate("技术原理", language), principles)

        self._add_section(
            body,
            translate("优势", language),
            str(profile.get("strengths") or translate(self.model.description, language)),
        )
        self._add_section(
            body,
            translate("局限", language),
            str(profile.get("limits") or translate("实际效果会受音频质量、语言和硬件配置影响。", language)),
        )
        resources = str(profile.get("resources") or "").strip()
        if resources:
            self._add_section(body, translate("硬件 / Runtime", language), resources)

        for section in profile.get("sections") or []:
            if isinstance(section, dict):
                self._add_section(body, translate(str(section.get("heading") or ""), language),
                                  str(section.get("body") or ""))

        for document in profile.get("license_documents") or []:
            if not isinstance(document, dict) or not document.get("path"):
                continue
            button = QPushButton("↗ " + translate(str(document.get("title") or "许可原文"), language))
            button.setObjectName("workshopSecondary")
            from .license_documents import show_document
            button.clicked.connect(lambda _=False, path=str(document["path"]): show_document(self, path))
            body.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)

        # Keep product recommendation separate from official evidence. Unlike
        # datasets, metrics and hardware are never normalized into a score.
        tw = profile.get("twobyte") or {}
        reason = tw.get("reason") or ""
        accuracy = _metric_evidence(
            self.model, "accuracy", self.reference_role, self.benchmark_scene,
            self.api_model,
        )
        speed = _metric_evidence(
            self.model, "speed", self.reference_role, self.benchmark_scene,
            self.api_model,
        )
        eval_text = (
            translate(str(accuracy.get("caption") or "准确度"), language) + "：" +
            str(accuracy["value"]) + "（" + str(accuracy["note"]) + "）" +
            "\n" + translate("速度", language) + "：" + str(speed["value"]) +
            "（" + str(speed["note"]) + "）" +
            "\n" + translate("推荐理由", language) + "：" +
            str(reason or translate("2ByteASR 工作流选型评价，并非官方统一跑分。", language))
        )
        self._add_section(body, translate("2ByteASR 评价", language), eval_text, tone="evaluation")
        self._add_reference_index_section(body, language)
        self._add_scoring_basis_section(body, language)

        # Official resources stay with the scrollable technical content; only
        # the close command remains fixed at the bottom of the modal.
        def _safe_open(u: str):
            QTimer.singleShot(0, lambda: QDesktopServices.openUrl(QUrl(u)))

        urls = []
        if profile.get("url"):
            urls.append((
                translate("GitHub / 官方仓库", language),
                str(profile.get("url")),
            ))
        if profile.get("hf"):
            urls.append(("Hugging Face", str(profile.get("hf"))))
        if profile.get("modelscope"):
            urls.append(("ModelScope", str(profile.get("modelscope"))))
        if profile.get("paper"):
            urls.append((tr("论文"), str(profile.get("paper"))))
        if profile.get("sources"):
            urls = [(translate(str(item.get("title") or item.get("label") or "官方资料"), language), str(item["url"]))
                    for item in profile["sources"] if isinstance(item, dict) and item.get("url")]

        if urls:
            self._add_links_section(
                body,
                translate("官方资源", language),
                urls,
                _safe_open,
            )
        body.addStretch(1)

        links_row = QHBoxLayout()
        links_row.addStretch(1)
        close = QPushButton(translate("关闭", language))
        close.setObjectName("workshopAction")
        close.clicked.connect(self._close_self)
        links_row.addWidget(close, 0)
        layout.addLayout(links_row)

        # No duplicate parameter grid or "官方信息" section below the header.

    def _close_self(self):
        mw = self._find_main_window()
        if mw and hasattr(mw, "_modal_host") and mw._modal_host.isVisible():
            mw._modal_host._request_close()
        else:
            p = self.parentWidget()
            while p and not isinstance(p, QDialog):
                p = getattr(p, "parentWidget", lambda: None)()
            if p:
                try:
                    p.accept()
                except Exception:
                    p.close()
            else:
                self.hide()

    def _find_main_window(self):
        p = self.parentWidget()
        while p:
            if hasattr(p, "_modal_host"):
                return p
            p = getattr(p, "parentWidget", lambda: None)()
        return None

    def _hosted_in_modal(self):
        return getattr(self, "_hosted", False)

    @staticmethod
    def _has_concrete_benchmark_value(value: str) -> bool:
        value = str(value or "").strip()
        if not value:
            return False
        if re.search(r"\d+(?:\.\d+)?\s*%", value):
            return True
        return bool(
            re.fullmatch(
                r"[<>~=≤≥]?\s*\d+(?:\.\d+)?(?:\s*(?:CER|WER|RTF|x|ms|s))?",
                value,
                flags=re.IGNORECASE,
            )
        )

    @staticmethod
    def _add_capability_section(layout: QVBoxLayout, heading: str, capabilities: list[str]):
        if not capabilities:
            return
        section = QWidget()
        section.setObjectName("technicalSection")
        box = QVBoxLayout(section)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(7)
        label = QLabel(heading)
        label.setObjectName("technicalDetailsHeading")
        box.addWidget(label)
        for start in range(0, len(capabilities), 4):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            for capability in capabilities[start : start + 4]:
                row.addWidget(PillLabel(f"{capability} ✓", "technicalCapability"))
            row.addStretch(1)
            box.addLayout(row)
        layout.addWidget(section)

    @staticmethod
    def _add_benchmark_section(
        layout: QVBoxLayout,
        heading: str,
        benchmarks: list[dict],
        empty_text: str,
        source_url: str = "",
    ):
        section = QWidget()
        section.setObjectName("technicalSection")
        box = QVBoxLayout(section)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(7)
        label = QLabel(heading)
        label.setObjectName("technicalDetailsHeading")
        box.addWidget(label)

        table = QFrame()
        table.setObjectName("technicalBenchmark")
        table_box = QVBoxLayout(table)
        table_box.setContentsMargins(0, 0, 0, 0)
        table_box.setSpacing(0)

        def _row(values: tuple[str, str, str], header: bool = False):
            host = QWidget()
            if header:
                host.setObjectName("technicalBenchmarkHeader")
            row = QHBoxLayout(host)
            row.setContentsMargins(10, 6, 10, 6)
            row.setSpacing(10)
            for value, stretch in zip(values, (5, 2, 3)):
                cell = QLabel(value)
                cell.setObjectName(
                    "technicalBenchmarkHeaderText" if header else "technicalBenchmarkCell"
                )
                cell.setWordWrap(True)
                cell.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                if not header:
                    cell.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                row.addWidget(cell, stretch)
            return host

        table_box.addWidget(_row(("数据集", "指标", "数值"), header=True))
        if benchmarks:
            for index, benchmark in enumerate(benchmarks):
                if index:
                    rule = QFrame()
                    rule.setObjectName("workshopRule")
                    rule.setFixedHeight(1)
                    table_box.addWidget(rule)
                table_box.addWidget(
                    _row(
                        (
                            str(benchmark.get("dataset") or "—"),
                            str(benchmark.get("metric") or "—"),
                            str(benchmark.get("value") or "—"),
                        )
                    )
                )
        else:
            empty = QLabel(empty_text)
            empty.setObjectName("technicalBenchmarkCell")
            empty.setWordWrap(True)
            empty.setContentsMargins(10, 8, 10, 9)
            empty.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            table_box.addWidget(empty)
        box.addWidget(table)
        if source_url:
            link = bind_text(QLabel(), '<a href="{source_url}" style="color:#4b7043; text-decoration:none;">查看完整官方 Benchmark ↗</a>', source_url=source_url)
            link.setObjectName("technicalLink")
            link.setOpenExternalLinks(True)
            box.addWidget(link, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(section)

    def _add_reference_index_section(self, layout: QVBoxLayout, language: str):
        """第三层：2ByteASR 参考评分及推导（公开换算 / 跨表校准 / 综合估算）。"""
        from twobyteasr.model_benchmarks import REFERENCE_INDEX_VERSION

        lines = [
            translate(
                "综合直接评测、跨表校准（经共同参照模型）与间接证据档位的 1–100 选型参考；"
                "100 = 当前参考版本与适用场景内的相对领先，不是识别正确率。", language
            ),
            f"{translate('参考版本', language)}: {REFERENCE_INDEX_VERSION}"
            f" · {translate('参照目录固定，不随搜索/筛选/安装态变化', language)}",
        ]
        if self.api_model:
            lines.append(
                f"{translate('当前解析型号', language)}: {self.api_model}"
            )
        for kind, kind_label in (("accuracy", "准确度"), ("speed", "速度")):
            lines.append("")
            kind_caption = kind_label
            if kind == "accuracy" and "ALIGNMENT" in (self.model.asr_capabilities or ()):
                kind_caption = "对齐精度"
            lines.append(f"◆ {translate(kind_caption, language)}")
            found = False
            for scene_key in _BENCHMARK_SCENES:
                evidence = _metric_evidence(
                    self.model, kind, self.reference_role, scene_key, self.api_model
                )
                if evidence is None:
                    continue
                scene_name = _benchmark_scene_label(scene_key, language)
                if evidence.get("available"):
                    found = True
                    lines.append(
                        f"   {scene_name}: {evidence['value']}/100"
                        f"（{translate('依据', language)}: {evidence['note']}）"
                    )
                elif evidence.get("unsupported"):
                    lines.append(f"   {scene_name}: {evidence['note']}")
            gap = translate(_benchmark_reference_gap(self.model.key, kind), language)
            if gap:
                found = True
                lines.append(f"   {translate('缺口', language)}: {gap}")
            if not found:
                lines.append("   " + translate("暂无参考数据", language))
        self._add_section(
            layout,
            translate("2ByteASR 参考评分及推导", language),
            "\n".join(lines),
        )

    def _add_scoring_basis_section(self, layout: QVBoxLayout, language: str):
        """评分依据：基准组、原始指标、公式与来源，全部可追溯。"""
        from twobyteasr.model_benchmarks import SCORE_FORMULA_VERSION, score_in_group

        groups = _benchmark_groups_for_model(self.model.key)
        lines = [
            translate(
                "卡片分数 = 同组相对指数：round(100 × sqrt(组内最佳 / 当前值))（错误率类），"
                "100 = 该基准组相对最佳，不是识别正确率百分比。",
                language,
            ),
            translate(
                "分数绑定「比较场景 + 基准组 + 参照集合 + 公式版本」，与搜索/筛选/安装状态无关。",
                language,
            ) + f"  {translate('公式', language)} {SCORE_FORMULA_VERSION}",
        ]
        if not groups:
            lines.append(
                translate(
                    "该模型暂无同组可比数据（没有同来源、同协议的公开横评表覆盖它），"
                    "因此不显示分数，避免把占位值伪装成评测结论。",
                    language,
                )
            )
        for group in groups:
            result = score_in_group(group, self.model.key)
            direction = (
                translate("越低越好", language)
                if group.direction == "lower"
                else translate("越高越好", language)
            )
            score_text = (
                f"{result['score']}/100"
                if result is not None and not result["solo"]
                else translate("不显示分数（该表仅此一家来源，无法横比）", language)
            )
            scene_name = _benchmark_scene_label(group.scene, language)
            lines.append("")
            lines.append(
                f"◆ {scene_name} · {translate(group.label, language)}"
            )
            lines.append(
                f"   {translate('原始指标', language)}: {group.metric} "
                f"{group.entries[self.model.key]:g}{group.unit}（{direction}） · "
                f"{translate('评分', language)}: {score_text}"
            )
            lines.append(f"   {translate('评测口径', language)}: {translate(group.protocol, language)}")
            lines.append(
                f"   {translate('来源', language)}: {translate(group.source_name, language)} · "
                f"{_benchmark_source_type_label(group.source_type, language)}"
            )
            lines.append(f"   URL: {group.source_url}")
            lines.append(
                f"   {translate('核实日期', language)}: {group.verified}"
            )
            if group.reference_rows:
                refs = "；".join(
                    f"{translate(row.label, language)} {row.value:g}{group.unit}" for row in group.reference_rows
                )
                lines.append(f"   {translate('同表外部参照', language)}: {refs}")
            if group.notes and group.notes != "solo_source":
                lines.append(f"   {translate('备注', language)}: {translate(group.notes, language)}")
        self._add_section(
            layout,
            translate("评分依据（同组相对分）", language),
            "\n".join(lines),
            tone="evaluation",
        )

    @staticmethod
    def _add_facts_section(
        layout: QVBoxLayout,
        heading: str,
        facts: list[tuple[str, str]],
    ):
        if not facts:
            return
        section = QWidget()
        section.setObjectName("technicalSection")
        box = QVBoxLayout(section)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(7)
        label = QLabel(heading)
        label.setObjectName("technicalDetailsHeading")
        box.addWidget(label)

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        for row, (fact_label, fact_value) in enumerate(facts):
            key = QLabel(fact_label)
            key.setObjectName("technicalFactLabel")
            key.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            value = QLabel(fact_value)
            value.setObjectName("technicalFactValue")
            value.setWordWrap(True)
            value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(key, row, 0)
            grid.addWidget(value, row, 1)
        grid.setColumnStretch(1, 1)
        box.addWidget(grid_host)
        layout.addWidget(section)

    @staticmethod
    def _add_links_section(layout, heading, urls, opener):
        section = QWidget()
        section.setObjectName("technicalSection")
        box = QVBoxLayout(section)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(7)
        label = QLabel(heading)
        label.setObjectName("technicalDetailsHeading")
        box.addWidget(label)
        for start in range(0, len(urls), 2):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            for text, url in urls[start:start + 2]:
                button = QPushButton(f"↗ {text}")
                button.setObjectName("workshopSecondary")
                button.clicked.connect(lambda _=None, value=url: opener(value))
                row.addWidget(button, 0)
            row.addStretch(1)
            box.addLayout(row)
        layout.addWidget(section)

    @staticmethod
    def _add_section(
        layout: QVBoxLayout,
        heading: str,
        text: str,
        *,
        tone: str = "plain",
    ):
        if not str(heading or "").strip() or not str(text or "").strip():
            return
        section = QFrame() if tone == "evaluation" else QWidget()
        section.setObjectName(
            "technicalEvaluation" if tone == "evaluation" else "technicalSection"
        )
        section_layout = QVBoxLayout(section)
        if tone == "evaluation":
            section_layout.setContentsMargins(12, 10, 12, 11)
        else:
            section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(4)
        label = QLabel(heading)
        label.setObjectName("technicalDetailsHeading")
        section_layout.addWidget(label)
        value = QLabel(text)
        value.setObjectName("technicalDetailsBody")
        value.setWordWrap(True)
        value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        section_layout.addWidget(value)
        layout.addWidget(section)


class ModelWorkshopPage(QWidget):
    return_requested = Signal()
    terms_requested = Signal()
    history_requested = Signal()
    task_settings_requested = Signal()
    ai_segmentation_requested = Signal()
    update_requested = Signal()
    backend_requested = Signal(str, str)
    api_config_requested = Signal()
    api_preset_requested = Signal(str)
    api_configure_requested = Signal(str)
    models_refreshed = Signal()
    removal_finished = Signal(object)
    removal_planned = Signal(object)
    mac_cpu_runtime_checked = Signal(object)
    registry_checked = Signal(object)

    def __init__(self, root: Path, runtime_settings: dict, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.runtime_settings = runtime_settings
        self._installed: set[str] = set()
        # 2026-10-12: one refresh per real change. _state_memo holds each
        # (model, role) state for the duration of one refresh pass; the
        # signature lets entries skip a refresh whose inputs are unchanged.
        self._state_memo: dict | None = None
        self._last_refresh_signature = None
        self._refresh_count = 0
        self._registry = None
        self._registry_check_running = False
        self._shown_once = False
        self.registry_checked.connect(self._registry_check_done)
        self._cards: dict[str, ModelCard] = {}
        self._removing: set[str] = set()
        self.removal_finished.connect(self._removal_finished)
        self.removal_planned.connect(self._confirm_model_removal)
        self._download_dialogs: list[ModelDownloadDialog] = []
        self._technical_cache: dict[str, ModelTechnicalDialog] = {}
        self._density_comfortable = None
        self._filter_signature = None
        self._mac_cpu_probe_running = False
        self._mac_cpu_probe_result = None
        self.mac_cpu_runtime_checked.connect(self._mac_cpu_runtime_checked)
        self.browser_role = "primary"
        self.detail_model_key = "moss"
        self.api_target_role = "primary"
        stored = QSettings("2ByteASR", "ModelWorkshop")
        self._sort_mode = str(stored.value("sort_mode", "recommended"))
        if self._sort_mode not in {"recommended", "size"}:
            self._sort_mode = "recommended"
        # 比较场景绑定评分口径：切换场景 = 切换基准组，不改变排序与筛选。
        self._benchmark_scene = str(stored.value("benchmark_scene", _DEFAULT_BENCHMARK_SCENE))
        if self._benchmark_scene not in _BENCHMARK_SCENES:
            self._benchmark_scene = _DEFAULT_BENCHMARK_SCENE
        self._filter_chips = set(stored.value("filter_chips", []) or [])
        self.setObjectName("modelWorkshopRoot")
        from .ui_zoom import set_sheet
        set_sheet(self, build_workshop_qss())
        self._build()
        self._download_activity_timer = QTimer(self)
        self._download_activity_timer.setInterval(500)
        self._download_activity_timer.timeout.connect(self._sync_download_activity)
        self._download_activity_timer.start()
        self.refresh()

        # P1-9: safe orphan temp cleanup. The scan can traverse a large runtime
        # evidence tree, so both startup and periodic work stay off the GUI thread.
        self._temp_cleanup_lock = threading.Lock()
        self._temp_cleanup_running = False
        self._temp_cleanup_timer = QTimer(self)
        self._temp_cleanup_timer.setInterval(60_000)
        self._temp_cleanup_timer.timeout.connect(self._periodic_temp_cleanup)
        self._temp_cleanup_timer.start()
        QTimer.singleShot(0, self._periodic_temp_cleanup)

    def refresh_theme_palette(self) -> None:
        from .ui_zoom import set_sheet
        set_sheet(self, build_workshop_qss())


    def _mac_cpu_runtime_checked(self, result):
        self._mac_cpu_probe_running = False
        self._mac_cpu_probe_result = result
        self.refresh()

    def _periodic_temp_cleanup(self):
        """P1-9: periodic safe orphan cleanup. Never touches active/resumable."""
        # Hidden model maintenance must not scan the recording/evidence tree
        # while Studio is playing. Downloads have their own completion cleanup.
        if not self.isVisible():
            return
        active: set[str] = set()
        for dialog in list(self._download_dialogs):
            try:
                if dialog.process.state() != QProcess.ProcessState.NotRunning:
                    active.update(str(key) for key in (dialog.download_keys or ()) if key)
            except Exception:
                pass
        with self._temp_cleanup_lock:
            if self._temp_cleanup_running:
                return
            self._temp_cleanup_running = True

        def work() -> None:
            try:
                cleanup_orphan_download_temps(self.root, active)
            except Exception:
                pass
            finally:
                with self._temp_cleanup_lock:
                    self._temp_cleanup_running = False

        threading.Thread(
            target=work,
            daemon=True,
            name="model-workshop-temp-cleanup",
        ).start()

    def _build(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        outer.addWidget(self._build_sidebar())
        # P0: use QSplitter for content + detail so model clicks NEVER change the right panel width.
        # Width stability is owned by the splitter layout, not by content sizeHint or detail children.
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(self._build_content())
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        detail_scroll.setMinimumWidth(360)
        detail_scroll.setMaximumWidth(400)
        detail_scroll.setWidget(self._build_detail())
        split.addWidget(detail_scroll)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        # Initial sizes give list room and lock detail ~360px; user resize of splitter is allowed but model switch won't push.
        split.setSizes([620, 360])
        outer.addWidget(split, 1)
        self._responsive_split = split
        self._responsive_detail = detail_scroll

    def resizeEvent(self, event):
        super().resizeEvent(event)
        split = getattr(self, '_responsive_split', None)
        if split is None:
            return
        compact = self.width() < 1050
        self.sidebar.setVisible(not compact)
        split.setOrientation(Qt.Orientation.Horizontal)
        self._responsive_detail.setMinimumWidth(0 if compact else 300)
        self._responsive_detail.setMaximumWidth(16777215 if compact else 400)
        if self._responsive_detail.parentWidget() is split:
            self._responsive_detail.setVisible(not compact)
        self.compact_details_button.setVisible(compact)
        self.role_subtitle.setVisible(self.height() >= 480)

    def _show_compact_details(self):
        if self._responsive_detail.parentWidget() is not self._responsive_split:
            self._responsive_detail.window().show()
            return
        from .main_ui_dialogs import SpringDialog, DialogSurface
        dialog=SpringDialog(self)
        dialog.setWindowTitle(self.detail_title.text())
        dialog.resize(min(600,self.width()),min(640,self.height()))
        layout=QVBoxLayout(dialog);layout.setContentsMargins(0,0,0,0)
        surface=DialogSurface(dialog,title=self.detail_title.text(),close_callback=dialog.reject)
        layout.addWidget(surface)
        surface.body_layout.setContentsMargins(0,0,0,0)
        surface.body_layout.addWidget(self._responsive_detail)
        self._responsive_detail.show()
        close=QPushButton('关闭');close.clicked.connect(dialog.reject)
        surface.footer_layout.addStretch();surface.footer_layout.addWidget(close)
        def restore(_result):
            self._responsive_split.addWidget(self._responsive_detail)
            self._responsive_detail.setVisible(self.width() >= 1050)
            dialog.deleteLater()
        dialog.finished.connect(restore)
        dialog.show()
        self._compact_detail_dialog=dialog

    def _build_sidebar(self) -> QFrame:
        # 2026-10-12: the shared sidebar column (same fixed width, heading and
        # navigation as Recognition History and Term Library); the workshop's
        # own sections below word-wrap inside it.
        from .ui_navigation import WorkspaceSidebar

        sidebar = WorkspaceSidebar("workshop", object_name="workshopSidebar")
        self.sidebar = sidebar
        layout = sidebar.body

        self.workspace_navigation = sidebar.navigation
        self.workspace_navigation.recognition_requested.connect(self.return_requested)
        self.workspace_navigation.terms_requested.connect(self.terms_requested)
        self.workspace_navigation.history_requested.connect(self.history_requested)
        self.nav_group = self.workspace_navigation.group
        self.workshop_nav_button = self.workspace_navigation.buttons["workshop"]

        layout.addSpacing(12)
        label = QLabel("当前组合")
        label.setObjectName("workshopMuted")
        label.setWordWrap(True)
        layout.addWidget(label)
        combo = QFrame()
        combo.setObjectName("workshopComboCard")
        combo_layout = QVBoxLayout(combo)
        combo_layout.setContentsMargins(12, 10, 12, 12)
        combo_layout.setSpacing(6)
        title_row = QHBoxLayout()
        self.combo_title = QLabel("质量优先")
        self.combo_title.setObjectName("workshopComboHeading")
        self.combo_title.setWordWrap(True)
        title_row.addWidget(self.combo_title, 1)
        badge = QLabel("推荐")
        badge.setObjectName("workshopRecommendationBadge")
        title_row.addWidget(badge)
        combo_layout.addLayout(title_row)
        rule = QFrame()
        rule.setObjectName("workshopRule")
        rule.setFixedHeight(1)
        combo_layout.addWidget(rule)
        self.combo_model_labels: dict[str, QLabel] = {}
        self.combo_status_labels: dict[str, QLabel] = {}
        for key, role, model_name in (
            ("primary", "主力转写", "MOSS"),
            ("timeline", "字幕时间轴", "FireRed"),
            ("review", "文字复核", "Qwen3-ASR"),
        ):
            row = QHBoxLayout()
            row.setSpacing(8)
            text_box = QVBoxLayout()
            text_box.setSpacing(2)
            role_label = QLabel(role)
            role_label.setObjectName("workshopComboRole")
            text_box.addWidget(role_label)
            model_label = QLabel(model_name)
            model_label.setObjectName("workshopComboModel")
            # 左栏窄列：API 组合的"服务商 · 模型"允许两行折行，避免像
            # "…mai-transcribe"这样丢尾（三十三轮 agy 复审）。
            model_label.setWordWrap(True)
            text_box.addWidget(model_label)
            row.addLayout(text_box, 1)
            status_label = QLabel()
            status_label.setObjectName("workshopComboStatus")
            status_label.setWordWrap(True)
            status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(status_label)
            combo_layout.addLayout(row)
            self.combo_model_labels[key] = model_label
            self.combo_status_labels[key] = status_label
            if key != "review":
                combo_layout.addSpacing(2)
        layout.addWidget(combo)
        self.download_estimate = QLabel()
        self.download_estimate.setObjectName("workshopTiny")
        self.download_estimate.setWordWrap(True)
        layout.addWidget(self.download_estimate)
        health = QFrame()
        health.setObjectName("workshopHealthCard")
        health_layout = QVBoxLayout(health)
        health_layout.setContentsMargins(12, 10, 12, 12)
        health_layout.setSpacing(6)
        health_title = QLabel("模型组合健康")
        health_title.setObjectName("workshopSection")
        health_title.setWordWrap(True)
        health_layout.addWidget(health_title)
        self.health_summary = QLabel("已安装 0 · 未安装 0")
        self.health_summary.setObjectName("workshopTiny")
        self.health_summary.setWordWrap(True)
        health_layout.addWidget(self.health_summary)
        self.storage_button = QPushButton("存储管理")
        self.storage_button.setObjectName("workshopSecondary")
        self.storage_button.clicked.connect(self._show_storage_manager)
        health_layout.addWidget(self.storage_button)
        layout.addWidget(health)
        layout.addStretch(1)
        return sidebar

    def restore_active_navigation(self):
        self.workspace_navigation.set_active("workshop")

    def focus_primary_backend(self, backend: str):
        """Open the primary tab on the model chosen by the setup wizard."""
        key = {
            "moss": "moss",
            "firered": "firered",
            "qwen_local": "qwen_local",
            "whisper_turbo": "whisper",
            "sensevoice": "sensevoice",
            "paraformer": "paraformer",
            "funasr_nano": "funasr_nano",
            "glm_asr_nano": "glm_asr_nano",
            "api": next((m.key for m in MODELS if m.api_preset ==
                         self.runtime_settings.get("models", {}).get("qwen_asr_api_provider", "qwen31_filetrans")),
                        "custom_asr_api"),
        }.get(str(backend))
        self._set_role("api" if backend == "api" else "primary")
        if key in self._cards:
            self._view_model(key)

    def _build_content(self) -> QFrame:
        content = QFrame()
        content.setObjectName("workshopContent")
        content.setMinimumWidth(0)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("模型工坊")
        title.setObjectName("workshopPageTitle")
        style_workspace_page_title(title)
        self.page_title = title
        title_box.addWidget(title)
        self.role_subtitle = QLabel("按角色组合识别能力；每个角色都可替换、关闭或改用在线 API。")
        subtitle = self.role_subtitle
        subtitle.setObjectName("workshopMuted")
        subtitle.setWordWrap(True)
        title_box.addWidget(subtitle)
        top.addLayout(title_box, 1)
        self.available_badge = QLabel()
        self.available_badge.setObjectName("workshopBadge")
        top.addWidget(self.available_badge, 0, Qt.AlignmentFlag.AlignTop)
        self.compact_details_button=QPushButton('模型详情')
        self.compact_details_button.clicked.connect(self._show_compact_details)
        self.compact_details_button.hide()
        top.addWidget(self.compact_details_button,0,Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

        self.download_activity = QFrame()
        self.download_activity.setObjectName("workshopDownloadActivity")
        activity_layout = QHBoxLayout(self.download_activity)
        activity_layout.setContentsMargins(10, 7, 8, 7)
        activity_layout.setSpacing(9)
        activity_icon = QLabel()
        activity_icon.setPixmap(
            _icon("fa5s.download", _active_accent_text()).pixmap(18, 18)
        )
        activity_layout.addWidget(activity_icon)
        self.download_activity_text = QLabel("模型正在后台下载")
        self.download_activity_text.setObjectName("workshopDownloadActivityText")
        self.download_activity_text.setMinimumWidth(150)
        activity_layout.addWidget(self.download_activity_text)
        self.download_activity_progress = QProgressBar()
        self.download_activity_progress.setObjectName(
            "workshopDownloadActivityProgress"
        )
        self.download_activity_progress.setTextVisible(False)
        self.download_activity_progress.setRange(0, 100)
        self.download_activity_progress.setValue(0)
        activity_layout.addWidget(self.download_activity_progress, 1)
        self.download_activity_button = QPushButton("查看下载")
        self.download_activity_button.setObjectName("workshopSecondary")
        self.download_activity_button.clicked.connect(
            lambda _checked=False: self._show_active_download()
        )
        activity_layout.addWidget(self.download_activity_button)
        self.download_activity.hide()
        layout.addWidget(self.download_activity)

        tabs = QHBoxLayout()
        tabs.setSpacing(7)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        for text, role in (("主力转写", "primary"), ("字幕时间轴", "timeline"), ("文字复核", "review"), ("在线 API", "api")):
            button = QPushButton(text)
            button.setObjectName("workshopTab")
            button.setCheckable(True)
            button.setProperty("role", role)
            button.setChecked(role == self.browser_role)
            button.clicked.connect(lambda _checked=False, value=role: self._set_role(value))
            self.tab_group.addButton(button)
            tabs.addWidget(button)
        tabs.addStretch(1)
        layout.addLayout(tabs)

        self.ai_segmentation_button = QPushButton("AI 模型 / 智能断句")
        self.ai_segmentation_button.setObjectName("workshopSecondary")
        install_themed_icon(self.ai_segmentation_button, "fa5s.project-diagram")
        self.ai_segmentation_button.clicked.connect(self.ai_segmentation_requested)
        self.task_settings_button = QPushButton("高级设置 / 任务设置")
        self.task_settings_button.setObjectName("workshopSecondary")
        install_themed_icon(self.task_settings_button, "fa5s.sliders-h")
        self.task_settings_button.clicked.connect(self.task_settings_requested)

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName("workshopSearch")
        bind_text(self.search, '搜索模型或使用场景', property='placeholderText')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.ai_segmentation_button)
        search_row.addWidget(self.task_settings_button)
        self.sort_filter_button = QPushButton("排序与筛选")
        self.sort_filter_button.setObjectName("workshopSecondary")
        self.sort_filter_button.clicked.connect(self._toggle_sort_filter)
        search_row.addWidget(self.sort_filter_button)
        layout.addLayout(search_row)
        self.sort_filter_popover = QFrame(self)
        self.sort_filter_popover.setObjectName("workshopSortPopover")
        self.sort_filter_popover.setWindowFlags(Qt.WindowType.Popup)
        self.sort_filter_popover.hide()
        pop = QVBoxLayout(self.sort_filter_popover)
        pop.setContentsMargins(12, 10, 12, 12)
        pop.addWidget(QLabel("排序"))
        self._sort_group = QButtonGroup(self.sort_filter_popover)
        for key, label in (
            ("recommended", "推荐"),
            ("size", "体积"),
        ):
            radio = QRadioButton(label)
            radio.setProperty("sort", key)
            radio.setChecked(key == self._sort_mode)
            self._sort_group.addButton(radio)
            radio.toggled.connect(self._sort_changed)
            pop.addWidget(radio)
        # 比较场景：决定卡片相对分使用哪个基准组（入口收进排序与筛选弹层，
        # 不新增工具栏；切换不影响排序/筛选/安装状态）。
        pop.addWidget(QLabel("比较场景"))
        self._scene_group = QButtonGroup(self.sort_filter_popover)
        self._scene_group.setExclusive(True)
        for key, (label_zh, _label_en) in _BENCHMARK_SCENES.items():
            radio = QRadioButton(label_zh)
            radio.setProperty("scene", key)
            radio.setChecked(key == self._benchmark_scene)
            bind_text(radio, '相对评分的比较口径；无该场景同组数据的模型会如实显示“暂无同组数据”', property='toolTip')
            self._scene_group.addButton(radio)
            radio.toggled.connect(self._scene_changed)
            pop.addWidget(radio)
        pop.addWidget(QLabel("筛选"))
        self._filter_buttons: dict[str, QPushButton] = {}
        # "all" clears other filters → show everything for this role.
        all_chip = QPushButton("全部")
        all_chip.setCheckable(True)
        all_chip.setChecked(len(self._filter_chips) == 0)
        def _select_all(checked=True):
            if not checked:
                # If user unchecks 全部, treat as "全部" still (no chips).
                all_chip.setChecked(True)
                return
            for k, b in self._filter_buttons.items():
                if k != "__all__":
                    b.setChecked(False)
            self._filter_chips = set()
            QSettings("2ByteASR", "ModelWorkshop").setValue("filter_chips", [])
            self._apply_filter()
        all_chip.toggled.connect(_select_all)
        self._filter_buttons["__all__"] = all_chip
        pop.addWidget(all_chip)
        for key, label in (
            ("local", "本地"),
            ("online", "在线"),
            ("installed", "已安装"),
            ("not_installed", "未安装"),
        ):
            chip = QPushButton(label)
            chip.setCheckable(True)
            chip.setChecked(key in self._filter_chips)
            def _on_toggle(checked, k=key, c=chip):
                if checked:
                    # uncheck 全部 when a real filter is chosen
                    if "__all__" in self._filter_buttons:
                        self._filter_buttons["__all__"].setChecked(False)
                    self._filter_chips.add(k)
                else:
                    self._filter_chips.discard(k)
                # persist and apply
                QSettings("2ByteASR", "ModelWorkshop").setValue("filter_chips", list(self._filter_chips))
                self._apply_filter()
            chip.toggled.connect(_on_toggle)
            self._filter_buttons[key] = chip
            pop.addWidget(chip)

        scroll = QScrollArea()
        scroll.setObjectName("workshopScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("workshopScrollHost")
        self.card_layout = QVBoxLayout(host)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(10)  # P0-2: 8~12px spacing between cards so they don't visually merge
        by_key = {model.key: model for model in MODELS}
        for key in CANONICAL_MODEL_ORDER:
            model = by_key.get(key)
            if model is None:
                continue
            card = ModelCard(model)
            card.selected.connect(self._select_model)
            card.action_requested.connect(self._perform_action)
            card.download_requested.connect(self._download_card)
            card.uninstall_requested.connect(self._uninstall_model)
            card.api_configure_requested.connect(self.api_configure_requested.emit)
            self._cards[model.key] = card
            self.card_layout.addWidget(card)
        self.empty_label = QLabel("没有符合当前筛选的模型。")
        self.empty_label.setObjectName("workshopMuted")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setMinimumHeight(100)
        self.card_layout.addWidget(self.empty_label)
        self.card_layout.addStretch(1)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)
        return content

    def _build_detail(self) -> QFrame:
        detail = QFrame()
        detail.setObjectName("workshopDetail")
        # P0 Resize: allow detail to participate in horizontal expansion but keep a sane max
        # so middle list gets the majority of new space.
        self.detail = detail
        # P0: width is owned by the outer splitter / workshop layout.
        # Never mutate geometry from content. Title and body only wrap.
        # P0: lock detail width so model switch never changes panel width (content wraps only).
        detail.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        detail.setMinimumWidth(0)
        detail.setMaximumWidth(380)
        layout = QVBoxLayout(detail)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)
        self.detail_badge = PillLabel("", "workshopStateBadge")
        layout.addWidget(self.detail_badge, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(2)
        self.detail_title = QLabel()
        self.detail_title.setObjectName("workshopDetailTitle")
        self.detail_title.setWordWrap(True)
        # Explicitly prevent the title from affecting panel width.
        self.detail_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.detail_title)
        self.detail_description = QLabel()
        self.detail_description.setObjectName("workshopMuted")
        self.detail_description.setWordWrap(True)
        self.detail_description.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.detail_description)
        self.detail_task = QLabel()
        self.detail_task.setObjectName("workshopMuted")
        self.detail_task.setWordWrap(True)
        self.detail_task.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.detail_task)
        workflow_title = QLabel("工作方式")
        workflow_title.setObjectName("workshopSection")
        layout.addWidget(workflow_title)
        self.detail_workflow = QLabel()
        self.detail_workflow.setObjectName("workshopMuted")
        self.detail_workflow.setWordWrap(True)
        self.detail_workflow.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.detail_workflow)
        layout.addSpacing(2)
        self.install_size_card = QLabel()
        self.install_size_card.setObjectName("workshopInstallSizeCard")
        self.install_size_card.setToolTip(SIZE_NOTE)
        self.install_size_card.setWordWrap(True)
        self.install_size_card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.install_size_card)
        layout.addSpacing(2)
        self.detail_rec_note = PillLabel("★ 2ByteASR 推荐", "recTag")
        self.detail_rec_note.setVisible(False)
        layout.addWidget(self.detail_rec_note, 0, Qt.AlignmentFlag.AlignLeft)
        self.detail_rec_reason = QLabel()
        self.detail_rec_reason.setObjectName("workshopRecommendationReason")
        self.detail_rec_reason.setVisible(False)
        self.detail_rec_reason.setWordWrap(True)
        self.detail_rec_reason.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.detail_rec_reason)
        layout.addSpacing(6)
        self.detail_metric_section = QLabel("2ByteASR 参考指数")
        self.detail_metric_section.setObjectName("workshopSection")
        self.detail_metric_section.setToolTip(COMPARISON_NOTE)
        layout.addWidget(self.detail_metric_section)
        self.capability_rows: list[RatingBar] = []
        for label in ("转写准确度", "速度指数"):
            bar = RatingBar(
                label,
                {"available": False, "value": "—", "note": "读取官方资料"},
                label_width=52,
            )
            layout.addWidget(bar)
            self.capability_rows.append(bar)
        layout.addSpacing(6)
        rule = QFrame()
        rule.setObjectName("workshopRule")
        rule.setFixedHeight(1)
        layout.addWidget(rule)
        install_title = QLabel("安装与兼容")
        install_title.setObjectName("workshopSection")
        layout.addWidget(install_title)
        self.detail_install = QLabel()
        self.detail_install.setObjectName("workshopMuted")
        self.detail_install.setWordWrap(True)
        layout.addWidget(self.detail_install)
        # 文案保持紧凑，主要操作稳定落在详情栏底部。
        layout.addStretch(1)
        layout.addSpacing(16)
        self.detail_action = QPushButton()
        self.detail_action.setObjectName("workshopPrimary")
        self.detail_action.clicked.connect(lambda: self._perform_action(self.detail_model_key))
        layout.addWidget(self.detail_action)
        self.detail_docs = QPushButton("查看技术说明")
        self.detail_docs.setObjectName("workshopSecondary")
        install_themed_icon(self.detail_docs, "fa5s.file-alt")
        self.detail_docs.clicked.connect(self._show_technical_details)
        layout.addWidget(self.detail_docs)
        # API 模型详情：显式配置入口（三十四轮——配置完成后没有再次编辑
        # key/模型/地址的办法）。
        self.detail_configure = QPushButton("配置密钥与接口")
        self.detail_configure.setObjectName("workshopSecondary")
        install_themed_icon(self.detail_configure, "fa5s.key")
        self.detail_configure.setCursor(Qt.CursorShape.PointingHandCursor)
        self.detail_configure.clicked.connect(self._configure_current_api)
        layout.addWidget(self.detail_configure)
        self.detail_configure.hide()
        manage_row = QHBoxLayout()
        manage_row.setSpacing(8)
        self.detail_repair = QPushButton("校验并修复")
        self.detail_repair.setObjectName("workshopSecondary")
        self.detail_repair.clicked.connect(self._repair_selected)
        manage_row.addWidget(self.detail_repair)
        self.detail_uninstall = QPushButton("永久删除模型文件")
        self.detail_uninstall.setObjectName("workshopSecondary")
        self.detail_uninstall.clicked.connect(self._uninstall_selected)
        manage_row.addWidget(self.detail_uninstall)
        layout.addLayout(manage_row)
        note = QLabel("模型切换只影响下一次字幕任务")
        note.setObjectName("workshopTiny")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(note)
        return detail

    def apply_density(self, comfortable: bool):
        """Responsive typography only. Do NOT force fixed widths that break free resize (P0)."""
        from .typography import TITLE_FONT_STACK
        from .design.tokens import WEIGHT_SCALE
        comfortable = bool(comfortable)
        if self._density_comfortable is comfortable:
            return
        self._density_comfortable = comfortable
        # Sidebar/detail widths are now set via SizePolicy + max in _build_*; keep only font scaling here.
        self.page_title.setStyleSheet(
            f"font-family: {TITLE_FONT_STACK}; "
            f"font-size: {24 if comfortable else 21}px; font-weight: {WEIGHT_SCALE['heavy']};"
        )
        self.detail_title.setStyleSheet(
            f"font-family: {TITLE_FONT_STACK}; "
            f"font-size: {24 if comfortable else 21}px; font-weight: {WEIGHT_SCALE['heavy']};"
        )
        for card in self._cards.values():
            card.setMinimumHeight(176)

    def update_runtime_settings(self, runtime_settings: dict):
        self.runtime_settings = runtime_settings
        # Entering the page or returning home used to rebuild every card's
        # state (a second refresh right after construction). Refresh only
        # when something it shows can differ; downloads, removals, storage
        # changes and language switches call refresh() themselves.
        if self._refresh_signature() != self._last_refresh_signature:
            self.refresh()

    def _refresh_signature(self) -> tuple:
        from .environment import preflight_cache_token
        from .llm_config import secrets_path
        from .runtime_paths import user_data_root

        def stamp(path: Path):
            try:
                stat = path.stat()
                return stat.st_mtime_ns, stat.st_size
            except OSError:
                return None
        try:
            models = json.dumps(self.runtime_settings.get("models", {}), sort_keys=True, default=str)
        except (TypeError, ValueError):
            models = repr(self.runtime_settings.get("models", {}))
        downloads = []
        for dialog in self._download_dialogs:
            try:
                if dialog.process.state() != QProcess.ProcessState.NotRunning:
                    downloads.extend(str(key) for key in (dialog.download_keys or ()))
            except RuntimeError:
                continue
        return (models, current_language(), stamp(secrets_path()),
                stamp(user_data_root() / 'model-readiness'), preflight_cache_token(),
                _registry_fingerprint(self._registry), tuple(sorted(downloads)),
                tuple(sorted(self._removing)), id(self._mac_cpu_probe_result))

    def background_busy(self) -> bool:
        return self._registry_check_running

    def showEvent(self, event):
        super().showEvent(event)
        if self._shown_once:
            # Files may have changed outside the app since the last visit:
            # re-check the registry off the GUI thread; refresh only on change.
            QTimer.singleShot(0, self._check_registry_in_background)
        self._shown_once = True

    def _check_registry_in_background(self):
        if self._registry_check_running:
            return
        self._registry_check_running = True
        root = Path(self.root)
        signal = self.registry_checked

        def work():
            try:
                from .model_registry import scan_model_registry
                registry = scan_model_registry(install_root=root)
            except Exception:  # noqa: BLE001 - the visible state stays as it was
                registry = None
            try:
                signal.emit(registry)
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True, name="workshop-registry-check").start()

    def _registry_check_done(self, registry):
        self._registry_check_running = False
        if registry is None:
            return
        if _registry_fingerprint(registry) != _registry_fingerprint(self._registry):
            self.refresh(registry=registry)

    def _active_download_dialog(
        self, download_key: str | None = None
    ) -> ModelDownloadDialog | None:
        for dialog in reversed(self._download_dialogs):
            try:
                running = (
                    dialog.process.state() != QProcess.ProcessState.NotRunning
                )
            except RuntimeError:
                continue
            if not running:
                continue
            if download_key is None or download_key in dialog.download_keys:
                return dialog
        return None

    def _show_active_download(self, download_key: str | None = None):
        dialog = self._active_download_dialog(download_key)
        if dialog is None:
            dialog = self._active_download_dialog()
        if dialog is None:
            self._sync_download_activity()
            return
        dialog.showNormal()
        dialog.raise_()
        dialog.activateWindow()

    def _sync_download_activity(self):
        dialog = self._active_download_dialog()
        if dialog is None:
            self.download_activity.hide()
            return

        self.download_activity.show()
        minimum = dialog.progress.minimum()
        maximum = dialog.progress.maximum()
        if maximum <= minimum:
            self.download_activity_progress.setRange(0, 0)
            percent_text = ""
        else:
            value = max(minimum, min(dialog.progress.value(), maximum))
            self.download_activity_progress.setRange(minimum, maximum)
            self.download_activity_progress.setValue(value)
            percent_text = f" · {value}%"
        status = dialog.progress_status.text().splitlines()[0].strip()
        if len(status) > 44:
            status = status[:43] + "…"
        label = dialog.display_name
        if status:
            label += f" · {status}"
        self.download_activity_text.setText(label + percent_text)

    def refresh(self, registry=None):
        self._refresh_count += 1
        self._state_memo = {}
        try:
            self._refresh(registry)
        finally:
            self._state_memo = None
        self._last_refresh_signature = self._refresh_signature()
        self.models_refreshed.emit()

    def _refresh(self, registry=None):
        language = current_language()
        self._refresh_role_subtitle()
        if registry is None:
            from .model_registry import scan_model_registry
            registry = scan_model_registry(install_root=Path(self.root))
        self._registry = registry
        self._installed = self._registry.installed_keys()
        bind_text(self.available_badge, f'{self._available_count()} ' + ('models available' if language == 'en' else ui_literal('个模型可用', language)))
        local_models = tuple(model for model in MODELS if model.install_keys)
        installed_count = sum(
            1
            for model in local_models
            if all(key in self._installed for key in model.install_keys)
        )
        self.set_health(installed_count, len(local_models))
        if self._registry.error:
            self.health_summary.setText(self._registry.error)
            self.health_summary.setWordWrap(True)
        self._refresh_combo()
        for key, card in self._cards.items():
            model = card.model
            state = self._model_state(model, self.browser_role)
            text, enabled = self._action_text(model, state)
            card.action.setText(translate(text, language))
            card.action.setEnabled(enabled)
            card.set_selected(state == "selected")
            manageable = self._has_managed_local_files(model)
            card.set_uninstall_available(manageable, not self._model_is_current(model) and key not in self._removing)
            if model.api_preset:
                ready = state in {"configured", "selected"}
                card.set_state_badge(
                    translate(
                        "已配置" if ready else "未配置",
                        language,
                    ),
                    "ready" if ready else "missing",
                )
            else:
                ready = state in {"selected", "installed", "downloaded"}
                badge_text = (
                    "下载中"
                    if state == "downloading"
                    else ("已安装" if ready else "未安装")
                )
                if state=='checking':badge_text='检查独立环境'
                if state=='runtime_missing':badge_text='权重已安装 · 环境未就绪'
                if state=='inference_pending':badge_text='模型已加载 · 人声推理待验证'
                if state=='load_failed':badge_text='文件已校验 · 加载未通过'
                if state=='partial':badge_text='权重不完整'
                if state=='unreadable':badge_text='目录无法读取'
                if state=='platform_unverified':badge_text='当前平台未验证'
                if state=='platform_unavailable' and (model.platforms or model.download_key in MAC_GPU_DOWNLOAD_KEYS):
                    badge_text='仅限 Apple Silicon Mac'
                card.set_state_badge(
                    translate(badge_text, language),
                    "ready"
                    if ready
                    else ("muted" if state == "downloading" else "missing"),
                )
        self._apply_filter()
        self._refresh_detail()


    def _model_is_current(self, model: WorkshopModel) -> bool:
        return model.key in self._current_model_keys()

    def _download_card(self, key: str):
        if key in self._cards:
            self._view_model(key)
            self._download(self._cards[key].model)



    def set_health(self, installed_count: int, total_count: int):
        missing = max(0, int(total_count) - int(installed_count))
        (bind_text(self.health_summary, f'Installed {installed_count} · Not installed {missing}') if current_language() == 'en' else bind_text(self.health_summary, '已安装 {value0} · 未安装 {value1}', value0=installed_count, value1=missing))

    def _current_model_keys(self) -> set[str]:
        models = self.runtime_settings.get("models", {})
        current: set[str] = set()
        selected = {
            "primary": str(models.get("primary_asr_backend", "moss")),
            "timeline": str(models.get("firered_asr_backend", "local")),
            "review": str(models.get("qwen_asr_backend", "api")),
        }
        for model in MODELS:
            if not model.download_key:
                continue
            bindings = dict(model.adapter_bindings)
            if any(bindings.get(role) == backend for role, backend in selected.items()):
                current.add(model.key)
        return current

    def _show_storage_manager(self):
        dialog = ModelStorageDialog(
            self.root,
            MODELS,
            self._current_model_keys,
            lambda key, name: self.download_combination([key], name),
            self._uninstall_model,
            self,
        )
        dialog.exec()
        self.refresh()

    def _available_count(self) -> int:
        return sum(
            self._model_state(self._cards[model.key].model) in {"installed", "selected", "configured"}
            for model in MODELS
            if model.available and model.runtime_available
        )

    def _has_managed_local_files(self, model: WorkshopModel) -> bool:
        if not model.download_key:return False
        record=self._registry.record(model.download_key) if self._registry else None
        return bool(model.download_key in self._installed or
                    (record and record.installation_path.exists()))

    def _model_state(self, model: WorkshopModel, role: str | None = None) -> str:
        role = role or self.browser_role
        memo = self._state_memo
        if memo is not None:
            key = (model.key, role)
            if key not in memo:
                memo[key] = self._compute_model_state(model, role)
            return memo[key]
        return self._compute_model_state(model, role)

    def _compute_model_state(self, model: WorkshopModel, role: str) -> str:
        models = self.runtime_settings.get("models", {})
        if model.platforms and _host_platform_tag() not in model.platforms:
            return 'platform_unavailable'
        mac_gpu = sys.platform == 'darwin' and model.download_key in MAC_GPU_DOWNLOAD_KEYS
        if mac_gpu and _host_platform_tag() != 'darwin-arm64':
            return 'platform_unavailable'
        if (sys.platform == 'darwin' and model.download_key and model.download_key != 'sensevoice'
                and not model.platforms and not mac_gpu):
            return 'platform_unavailable'
        if not model.available:
            return "planned"
        if model.download_key and self._active_download_dialog(model.download_key):
            return "downloading"
        registry = getattr(self, '_registry', None)
        if registry and registry.error and model.install_keys:
            return 'unreadable'
        records = [registry.record(key) for key in model.install_keys] if registry else []
        if any(record and record.health.value == 'UNREADABLE' for record in records):
            return 'unreadable'
        if any(record and record.health.value in {'PARTIAL', 'CORRUPT'} for record in records):
            return 'partial'
        if model.api_preset:
            from .llm_config import read_asr_api_key
            if model.key == 'mai_latest' and self._api_model_for(model) in {'', 'microsoft/mai-transcribe-2'}:
                return 'configure'

            configured = bool(
                read_asr_api_key(
                    model.api_preset, str(models.get("qwen_asr_api_url", "") or "")
                )[0]
            )
            if model.api_preset=='spark_asr_v2':
                from .llm_config import read_spark_credentials
                from .spark_asr import URL
                configured=all(read_spark_credentials(URL).values())
            if role == "primary":
                role_backend = models.get("primary_asr_backend")
            elif role in {"api", "review"}:
                # 「在线 API」浏览/详情视角：主力或复核任一角色在用即视为
                # 当前使用（此前只查复核后端，详情面板永不显示选中态）。
                role_backend = (
                    "api"
                    if "api" in {
                        models.get("primary_asr_backend"),
                        models.get("qwen_asr_backend"),
                    }
                    else models.get("qwen_asr_backend")
                )
            else:
                role_backend = models.get("qwen_asr_backend")
            active = (
                role_backend == "api"
                and models.get("qwen_asr_api_provider", "qwen31_filetrans") == model.api_preset
            )
            if active and configured:
                return "selected"
            if configured:
                return "configured"
            return "configure"
        installed = bool(model.install_keys) and all(key in self._installed for key in model.install_keys)
        if not installed:
            return "missing"
        if model.platforms:
            # MLX models run in their own torch-free runtime (2026-10-13).
            from .mlx_backend import runtime_python as mlx_runtime_python
            if not mlx_runtime_python():
                return 'runtime_missing'
        if mac_gpu:
            # Registered only after the readiness check ran on this Mac (prepare_local).
            from .runtime_registry import resolve_runtime_python
            roles = ('main', 'moss') if model.download_key == 'moss' else ('main',)
            if not all(resolve_runtime_python(name, register=False) for name in roles):
                return 'runtime_missing'
        if sys.platform == 'darwin' and model.download_key == 'sensevoice':
            from .environment import fast_preflight
            runtime_check = fast_preflight('main')
            if runtime_check is None:
                runtime_check = self._mac_cpu_probe_result
                if runtime_check is None and not self._mac_cpu_probe_running:
                    self._mac_cpu_probe_running = True
                    def probe_cpu():
                        from .environment import preflight, PreflightResult
                        try:
                            result = preflight('main')
                        except Exception as exc:
                            result = PreflightResult(role='main', ok=False, problems=[str(exc)])
                        try:
                            self.mac_cpu_runtime_checked.emit(result)
                        except RuntimeError:
                            pass
                    threading.Thread(target=probe_cpu, daemon=True, name='macos-cpu-runtime-check').start()
                if runtime_check is None:
                    return 'checking'
            if not runtime_check.ok:
                return 'runtime_missing'
        if not _runtime_role_available(model, role):
            if model.auto_stage and _readiness_status(model.download_key) in {'FAIL', 'BLOCKED'}:
                return 'load_failed'
            return "downloaded"
        if _readiness_status(model.download_key) in {'FAIL','BLOCKED'}:
            return 'load_failed'
        setting_key = {
            "primary": "primary_asr_backend",
            "timeline": "firered_asr_backend",
            "review": "qwen_asr_backend",
        }[role]
        default = {"primary": "moss", "timeline": "local", "review": "api"}[role]
        return (
            "selected"
            if _adapter_backend(model, role) == str(models.get(setting_key, default))
            else "installed"
        )

    def _action_text(self, model: WorkshopModel, state: str) -> tuple[str, bool]:
        if state=='platform_unverified':return '当前平台未验证',False
        if model.key in self._removing: return '正在永久删除…', False
        if state == 'platform_unavailable':
            if model.platforms or model.download_key in MAC_GPU_DOWNLOAD_KEYS:
                return '仅限 Apple Silicon Mac', False
            from .platform_macos import macos_copy
            return macos_copy('尚未适配 macOS', 'Not yet adapted to macOS', 'macOS 未対応'), False
        if state == 'partial': return '补齐缺失文件', True
        if state == 'unreadable': return '请检查目录权限', False
        if state=='checking':return '检查独立环境…',False
        if state=='runtime_missing':return '安装 / 修复独立环境',True
        if state=='inference_pending':return '选择样本验证推理',True
        if state=='load_failed':return '重试加载验证',True
        if state == "planned":
            return "尚未接入", False
        if state == "missing":
            return "下载", True
        if state == "downloading":
            return "查看进度", True
        if state == "downloaded":
            if model.auto_stage:
                # 2026-10-14: an installed helper (日语 CTC) is the user's to turn
                # off and on, like any selected model.
                return ("取消使用" if _auto_stage_enabled(model, self.runtime_settings) else "使用"), True
            return "已下载 · 接入中", False
        if state == "configure":
            return "配置", True
        if state == "configured":
            return "使用", True
        if state == "selected":
            return "取消使用", True
        # Reaching "installed" means the selected role has a verified adapter;
        # _model_state already maps capability-only downloads to "downloaded".
        return "使用", True

    def _refresh_combo(self):
        models = self.runtime_settings.get("models", {})
        moss_ready = {"moss", "firered_vad", "speaker_embedding"} <= self._installed
        # P0/P1: if MOSS files present but its CUDA env is broken, surface "已安装 · 环境异常"
        # so user can "校验并修复" the correct .venv-moss without touching main.
        if moss_ready:
            try:
                from twobyteasr.environment import fast_preflight
                fr = fast_preflight("moss")
                if fr is not None and not fr.ok:
                    # files ok but env not healthy (e.g. CPU torch) → mark abnormal
                    moss_ready = False
                    # stash for label logic below
                    self._moss_env_abnormal = True
                else:
                    self._moss_env_abnormal = False
            except Exception:
                self._moss_env_abnormal = False
        else:
            self._moss_env_abnormal = False
        primary_backend = models.get("primary_asr_backend", "moss")
        firered_backend = models.get("firered_asr_backend", "local")
        firered_ready = "firered_aed" in self._installed
        aligner_ready = "qwen_aligner" in self._installed
        whisper_ready = "whisper_turbo" in self._installed
        paraformer_ready = "paraformer" in self._installed
        qwen_backend = models.get("qwen_asr_backend", "api")

        if firered_backend == "qwen_aligner":
            timeline_value = (
                "Qwen ForcedAligner",
                "已安装" if aligner_ready else "未安装",
                aligner_ready,
            )
        elif firered_backend == "paraformer":
            timeline_value = (
                "Paraformer",
                "已安装" if paraformer_ready else "未安装",
                paraformer_ready,
            )
        elif firered_backend == "whisper_turbo":
            timeline_value = (
                "Whisper",
                "已安装" if whisper_ready else "未安装",
                whisper_ready,
            )
        elif firered_backend == "local":
            timeline_value = (
                "FireRed",
                "已安装" if firered_ready else "未安装",
                firered_ready,
            )
        else:
            timeline_value = ("字幕时间轴", "已关闭 / 仅 TXT", False)

        moss_label = "已安装"
        if getattr(self, "_moss_env_abnormal", False):
            moss_label = "已安装 · 环境异常"
        combo_values = {
            "primary": ("MOSS", moss_label, moss_ready),
            "timeline": timeline_value,
        }
        primary_options = {
            "moss": ("MOSS", moss_ready),
            "firered": ("FireRed", "firered_aed" in self._installed),
            "qwen_local": ("Qwen3-ASR", "qwen_asr" in self._installed),
            "whisper_turbo": ("Whisper Turbo", "whisper_turbo" in self._installed),
            "sensevoice": ("SenseVoice", "sensevoice" in self._installed),
            "paraformer": ("Paraformer", "paraformer" in self._installed),
            "funasr_nano": ("Fun-ASR Nano", "funasr_nano" in self._installed),
            "glm_asr_nano": ("GLM-ASR Nano", "glm_asr_nano" in self._installed),
            "api": _api_combo_label(models),
        }
        primary_name, primary_ready = primary_options.get(
            primary_backend, (primary_backend, False)
        )
        combo_values["primary"] = (
            primary_name,
            "已安装" if primary_ready else "未安装",
            primary_ready,
        )
        if qwen_backend == "local":
            qwen_ready = "qwen_asr" in self._installed
            combo_values["review"] = ("Qwen3-ASR", "已安装" if qwen_ready else "未安装", qwen_ready)
        elif qwen_backend == "whisper_turbo":
            qwen_ready = "whisper_turbo" in self._installed
            combo_values["review"] = (
                "Whisper Turbo",
                "已安装" if qwen_ready else "未安装",
                qwen_ready,
            )
        elif qwen_backend in {"sensevoice", "funasr_nano"}:
            qwen_ready = qwen_backend in self._installed
            qwen_name = "SenseVoice" if qwen_backend == "sensevoice" else "Fun-ASR Nano"
            combo_values["review"] = (
                qwen_name,
                "已安装" if qwen_ready else "未安装",
                qwen_ready,
            )
        elif qwen_backend == "api":
            review_label, qwen_ready = _api_combo_label(models)
            combo_values["review"] = (review_label, "已配置" if qwen_ready else "待配置", qwen_ready)
        else:
            from .i18n import translate as _iw_translate, current_language as _iw_lang
            combo_values["review"] = ("Qwen3-ASR", _iw_translate("已关闭", _iw_lang()), False)

        for key, (model_name, status, ready) in combo_values.items():
            self.combo_model_labels[key].setText(model_name)
            status_label = self.combo_status_labels[key]
            status_label.setText(translate(status, current_language()))
            status_label.setProperty("ready", ready)
            status_label.style().unpolish(status_label)
            status_label.style().polish(status_label)
        missing_sizes = []
        recorded = set()

        def add_missing(key, label):
            if key not in self._installed and key not in recorded:
                missing_sizes.append(label)
                recorded.add(key)

        primary_downloads = {
            "moss": ("moss", "MOSS 约 1.7 GB"),
            "firered": ("firered_aed", "FireRed 约 4.4 GB"),
            "qwen_local": ("qwen_asr", "Qwen 约 4.7 GB"),
            "whisper_turbo": ("whisper_turbo", "Whisper Turbo 约 1.6 GB"),
            "sensevoice": ("sensevoice", "SenseVoice 约 0.9 GB"),
            "paraformer": ("paraformer", "Paraformer 约 1.0 GB"),
            "funasr_nano": ("funasr_nano", "Fun-ASR Nano 约 2.4 GB"),
            "glm_asr_nano": ("glm_asr_nano", "GLM-ASR Nano 约 4.21 GiB"),
        }
        if primary_backend in primary_downloads:
            add_missing(*primary_downloads[primary_backend])
        if firered_backend == "local":
            add_missing("firered_aed", "FireRed 约 4.4 GB")
        elif firered_backend == "qwen_aligner":
            add_missing("qwen_aligner", "Qwen ForcedAligner 约 1.8 GB")
        elif firered_backend == "whisper_turbo":
            add_missing("whisper_turbo", "Whisper Turbo 约 1.6 GB")
        elif firered_backend == "paraformer":
            add_missing("paraformer", "Paraformer 约 1.0 GB")
        review_downloads = {
            "local": ("qwen_asr", "Qwen 约 4.7 GB"),
            "whisper_turbo": ("whisper_turbo", "Whisper Turbo 约 1.6 GB"),
            "sensevoice": ("sensevoice", "SenseVoice 约 0.9 GB"),
            "funasr_nano": ("funasr_nano", "Fun-ASR Nano 约 2.4 GB"),
        }
        if qwen_backend in review_downloads:
            add_missing(*review_downloads[qwen_backend])
        if current_language() == "en":
            sizes = ", ".join(label.replace("约", "≈") for label in missing_sizes)
            self.download_estimate.setText(
                "Estimated additional download: " + (sizes or "No download needed")
            )
        else:
            bind_text(self.download_estimate, '预计新增下载：{value0}', value0=ui_literal('、'.join(missing_sizes)) if missing_sizes else tr('无需下载'))

    def _set_role(self, role: str):
        self.browser_role = role
        self._refresh_role_subtitle()
        for button in self.tab_group.buttons():
            button.setChecked(button.property("role") == role)
        selected = self._cards.get(self.detail_model_key)
        if selected is None or role not in _browser_groups(selected.model):
            replacement = next((model.key for model in MODELS if role in _browser_groups(model)), None)
            if replacement:
                self.detail_model_key = replacement
        self._apply_filter()
        self._view_model(self.detail_model_key)

    def _refresh_role_subtitle(self):
        label = getattr(self, "role_subtitle", None)
        if label is None:
            return
        default_text = "按角色组合识别能力；每个角色都可替换、关闭或改用在线 API。"
        if self.browser_role != "api":
            label.setText(default_text)
            return
        models = self.runtime_settings.get("models", {})
        from .ui import ASR_API_PRESETS
        from .llm_config import read_asr_api_key

        provider = str(models.get("qwen_asr_api_provider", "qwen31_filetrans") or "qwen31_filetrans")
        preset = ASR_API_PRESETS.get(provider, {})
        model_id = str(models.get("qwen_asr_api_model", "") or "")
        (bind_text(label, '当前使用：{value0} · {value1}', value0=tr(preset.get('label', provider)), value1=model_id) if model_id else bind_text(label, '当前使用：{value0}', value0=tr(preset.get('label', provider))))
        del read_asr_api_key

    def _toggle_sort_filter(self):
        if self.sort_filter_popover.isVisible():
            self.sort_filter_popover.hide()
            return
        button = self.sort_filter_button
        self.sort_filter_popover.adjustSize()
        self.sort_filter_popover.move(button.mapToGlobal(button.rect().bottomLeft()))
        self.sort_filter_popover.show()

    def _api_model_for(self, model: WorkshopModel) -> str:
        """API 卡当前实际型号：活动 provider 用已保存值，否则用预设默认。"""
        if not model.api_preset:
            return ""
        from .ui import ASR_API_PRESETS

        models = dict(self.runtime_settings.get("models", {}) or {})
        active = str(models.get("qwen_asr_api_provider", "") or "")
        if active == model.api_preset:
            current = str(models.get("qwen_asr_api_model", "") or "")
            if current:
                return current
        return str((ASR_API_PRESETS.get(model.api_preset) or {}).get("model") or "")

    def _scene_changed(self, checked=False):
        if not checked:
            return
        button = self._scene_group.checkedButton()
        if button is None:
            return
        scene = str(button.property("scene") or _DEFAULT_BENCHMARK_SCENE)
        if scene == self._benchmark_scene:
            return
        self._benchmark_scene = scene if scene in _BENCHMARK_SCENES else _DEFAULT_BENCHMARK_SCENE
        QSettings("2ByteASR", "ModelWorkshop").setValue("benchmark_scene", self._benchmark_scene)
        # 场景只改评分口径：排序与筛选语义不变（分数本来就与筛选无关）。
        for card in self._cards.values():
            card.set_reference_role(
                self.browser_role, self._benchmark_scene, self._api_model_for(card.model)
            )
        self._refresh_detail()

    def _sort_changed(self, checked=False):
        if not checked:
            return
        button = self._sort_group.checkedButton()
        if button is None:
            return
        self._sort_mode = str(button.property("sort") or "recommended")
        QSettings("2ByteASR", "ModelWorkshop").setValue("sort_mode", self._sort_mode)
        self._apply_filter()

    def _filters_changed(self, _checked=False):
        self._filter_chips = {
            key for key, button in self._filter_buttons.items() if button.isChecked()
        }
        QSettings("2ByteASR", "ModelWorkshop").setValue("filter_chips", list(self._filter_chips))
        self._apply_filter()

    def _ordered_models(self):
        models = [self._cards[m.key].model if m.key in self._cards else m for m in MODELS]
        if self._sort_mode == "size":
            models.sort(key=lambda item: (item.size, CANONICAL_MODEL_ORDER.index(item.key) if item.key in CANONICAL_MODEL_ORDER else 99))
        else:
            models.sort(key=lambda item: CANONICAL_MODEL_ORDER.index(item.key) if item.key in CANONICAL_MODEL_ORDER else 99)
        return models

    def _card_matches_chips(self, model: WorkshopModel) -> bool:
        chips = self._filter_chips
        if not chips:
            return True
        state = self._model_state(model, self.browser_role)
        online = model_is_online(model)
        if "local" in chips and online:
            return False
        if "online" in chips and not online:
            return False
        if "installed" in chips and state in {"missing", "configure", "planned"}:
            return False
        if "not_installed" in chips and state not in {"missing", "configure"}:
            return False
        return True

    def _apply_filter(self):
        # P0: Sorting and Filtering are completely separate.
        # Sorting only reorders. Filtering changes the visible set.
        # _apply_filter must never drop models just because a sort changed.
        needle = self.search.text().strip().casefold()
        ordered = self._ordered_models()
        visibility = []
        for model in ordered:
            card = self._cards[model.key]
            card.set_reference_role(
                self.browser_role, self._benchmark_scene, self._api_model_for(model)
            )
            haystack = " ".join(
                (model.name, model_scene(model), model.mode, model.proof, model.description,
                 " ".join(model_task_badges(model)))
            ).casefold()
            show = (
                self.browser_role in _browser_groups(model)
                and (not needle or needle in haystack)
                and self._card_matches_chips(model)
            )
            visibility.append((model.key, show))
        signature = tuple(visibility)
        if signature == self._filter_signature:
            return
        self._filter_signature = signature
        visible = 0
        for model, (_key, show) in zip(ordered, visibility):
            card = self._cards[model.key]
            self.card_layout.insertWidget(visible if show else self.card_layout.count() - 2, card)
            card.setVisible(show)
            visible += int(show)
        self.empty_label.setVisible(visible == 0)

    def _view_model(self, key: str):
        if key not in self._cards:
            return
        self.detail_model_key = key
        self._refresh_detail()

    def _select_model(self, key: str, *, role: str | None = None):
        """Handle a card click without conflating detail focus and runtime state."""
        if key not in self._cards:
            return
        self._view_model(key)
        model = self._cards[key].model
        effective_role = role or self.browser_role
        state = self._model_state(model, effective_role)
        if state in {"selected", "installed", "configured"}:
            self._request_model_selection(model, state, role=effective_role)

    def _refresh_detail(self):
        model = self._cards[self.detail_model_key].model
        language = current_language()
        if hasattr(self, "detail_configure"):
            self.detail_configure.setVisible(bool(model.api_preset))
        state = self._model_state(model, self.browser_role)
        badge = {
            "selected": "当前使用",
            "installed": "已安装",
            "configured": "在线 · 已配置",
            "configure": "在线 · 未配置",
            "missing": "尚未安装",
            "partial": "权重不完整 · 保留已有文件",
            "unreadable": "模型目录无法读取",
            "downloading": "正在下载",
            "downloaded": "已下载 · 接入中",
            "planned": "规划中",
            "checking": "正在检查独立环境",
            "runtime_missing": "权重已安装 · 环境未就绪",
            "inference_pending": "模型已加载 · 人声推理待验证",
            "load_failed": "文件与运行库已准备 · 加载或设备验证未通过",
            "platform_unavailable": "尚未适配 macOS",
            "platform_unverified": "当前平台未验证",
        }[state]
        if state == 'platform_unavailable':
            badge = self._action_text(model,state)[0]
        auto_ready = (state == "downloaded" and bool(model.auto_stage)
                      and _auto_stage_enabled(model, self.runtime_settings))
        if auto_ready:
            badge = model.auto_stage
        elif state == "downloaded" and model.auto_stage:
            badge = "已安装 · 已停用"
        self.detail_badge.setText(translate(badge, language))
        badge_tone = "ready" if state in {"selected", "installed", "configured"} or auto_ready else "missing"
        if state in {"downloaded", "downloading", "planned"} and not auto_ready:
            badge_tone = "muted"
        self.detail_badge.setProperty("tone", badge_tone)
        self.detail_badge.style().unpolish(self.detail_badge)
        self.detail_badge.style().polish(self.detail_badge)
        bind_text(self.detail_title, model.name)
        is_online = model_is_online(model)
        size_heading = "本地磁盘占用" if is_online else "本地磁盘占用（预计）"
        size_value = "无需本地下载" if is_online else _install_size_label(model.size)
        self.install_size_card.setText(
            f"{translate(size_heading, language)}\n"
            f"{translate(size_value, language)}"
        )
        self.detail_description.setText(model_scene(model))
        self.detail_task.setText(" · ".join(model_task_badges(model)))
        self.detail_workflow.setText(model_workflow(model))
        is_rec = bool(getattr(model, "recommended", False))
        self.detail_rec_note.setVisible(is_rec)
        self.detail_rec_reason.setVisible(is_rec)
        if is_rec:
            rationale = {
                "moss": "中文长音频与说话人区分，适合作为第一阶段主力转写。",
                "firered": "字级时间轴精度适合作为第二阶段字幕时间轴。",
                "qwen_local": "多语言与专名复核适合作为第三阶段文字复核。",
            }.get(model.key, "适合当前 2ByteASR 工作流角色。")
            self.detail_rec_reason.setText(translate(rationale, language))
        detail_evidence = (
            _metric_evidence(
                model, "accuracy", self.browser_role, self._benchmark_scene,
                self._api_model_for(model),
            ),
            _metric_evidence(
                model, "speed", self.browser_role, self._benchmark_scene,
                self._api_model_for(model),
            ),
        )
        bind_text(self.detail_metric_section, translate('2ByteASR 参考指数', language) + ' · ' + _benchmark_scene_label(model_metric_scene(model, self._benchmark_scene), language))
        for bar, evidence in zip(self.capability_rows, detail_evidence):
            bar.set_evidence(evidence)
        compatibility = translate(model_mode_text(model), language)
        if model.download_key:
            compatibility += "\n" + translate("自动来源先试 ModelScope，再试 Hugging Face 官方；HF 镜像可在下载窗口手动选择（可能回源官方）；可断点续传。", language)
            if model.auto_stage:
                compatibility += f"\n{translate('安装后默认用于对应识别步骤；点「取消使用」停用，点「使用」恢复。不会替换现有后端。', language)}"
            elif not _runtime_role_available(model, self.browser_role):
                compatibility += f"\n{translate('模型文件可先下载；当前角色适配尚未完成，不会替换现有后端。', language)}"
        elif model.api_preset:
            compatibility += "\n" + translate("在设置页保存对应服务的模型、地址与 API Key。", language)
        self.detail_install.setText(compatibility)
        registry = getattr(self, '_registry', None)
        records = [registry.record(key) for key in model.install_keys] if registry else []
        issues = []
        complete_issues = []
        for record in records:
            if not record or not record.missing_files: continue
            missing = record.missing_files
            summary = '、'.join(missing[:8])
            if len(missing) > 8:
                summary += str(tr('…另有 {count} 项（悬停查看完整路径与清单）', count=len(missing)-8))
            issues.append(f'{record.installation_path}：' + summary)
            complete_issues.append(str(record.installation_path)+'\n'+'\n'.join(missing))
        self.detail_install.setToolTip('\n\n'.join(complete_issues))
        if issues:
            self.detail_install.setText(compatibility + '\n' + '\n'.join(issues))
        if registry and registry.error:
            self.detail_install.setText(registry.error)
        action_text, enabled = self._action_text(model, state)
        if state == "missing":
            action_text = f"{translate('下载', language)} {model.name}"
        self.detail_action.setText(translate(action_text, language))
        from .design.presentation import button_role
        self.detail_action.setObjectName('studioButton' if state == 'selected' else 'studioPrimary')
        button_role(self.detail_action, 'secondary' if state == 'selected' else 'primary')
        self.detail_action.style().unpolish(self.detail_action)
        self.detail_action.style().polish(self.detail_action)
        self.detail_action.setEnabled(enabled)
        manageable = self._has_managed_local_files(model)
        self.detail_repair.setVisible(bool(model.download_key))
        self.detail_repair.setEnabled(manageable and state != "downloading" and model.key not in self._removing)
        self.detail_uninstall.setVisible(bool(model.download_key))
        self.detail_uninstall.setEnabled(manageable and not self._model_is_current(model) and model.key not in self._removing)

    def _perform_action(self, key: str, *, role: str | None = None):
        if key not in self._cards:
            return
        self._view_model(key)
        model = self._cards[key].model
        effective_role = role or self.browser_role
        if effective_role == "api":
            # 「在线 API」浏览视角的操作作用于主力转写。此前 role="api" 落进
            # _selection_target 的角色字典直接 KeyError、被 Qt 吞掉——点多少次
            # "使用/取消使用"都没有任何反应（三十四轮用户实录）。
            effective_role = "primary"
        state = self._model_state(model, effective_role)
        if state == "planned":
            return
        if state == "downloading":
            self._show_active_download(model.download_key)
            return
        if state in {"missing","partial","runtime_missing","inference_pending","load_failed"} and model.download_key:
            self._download(model)
            return
        if state == "configure" and model.api_preset:
            self.api_target_role = effective_role
            self.api_preset_requested.emit(model.api_preset)
            return
        if state == "downloaded" and model.auto_stage:
            try:
                _set_auto_stage_enabled(model, not _auto_stage_enabled(model, self.runtime_settings),
                                        self.runtime_settings)
            except (OSError, RuntimeError, ValueError) as exc:
                QMessageBox.warning(self, tr('无法保存设置'), str(exc))
            self.refresh()
            return
        if state in {"selected", "installed", "configured"}:
            self._request_model_selection(model, state, role=effective_role)

    def _selection_target(
        self, model: WorkshopModel, role: str | None = None
    ) -> tuple[str, str] | None:
        role = role or self.browser_role
        if role == "api":
            role = "primary"
        backend = _adapter_backend(model, role)
        if not backend:
            return None
        setting_role = {"primary": "primary", "timeline": "firered", "review": "qwen"}[role]
        return setting_role, backend

    def _selected_model_key_for_role(self, role: str) -> str | None:
        models = self.runtime_settings.get("models", {})
        if role == "api":
            role = "primary"
        setting_key = {
            "primary": "primary_asr_backend",
            "timeline": "firered_asr_backend",
            "review": "qwen_asr_backend",
        }[role]
        selected_backend = str(models.get(setting_key, ""))
        selected_provider = str(models.get("qwen_asr_api_provider", "qwen31_filetrans"))
        for candidate in MODELS:
            if _adapter_backend(candidate, role) != selected_backend:
                continue
            if selected_backend == "api" and candidate.api_preset != selected_provider:
                continue
            return candidate.key
        return None

    def _request_model_selection(
        self, model: WorkshopModel, state: str, *, role: str | None = None
    ):
        requested_role = role or self.browser_role
        target = self._selection_target(model, requested_role)
        if target is None:
            return
        if state != "selected" and requested_role in {"primary", "review"}:
            other_role = "review" if requested_role == "primary" else "primary"
            if self._selected_model_key_for_role(other_role) == model.key:
                answer = QMessageBox.warning(
                    self,
                    tr('重复 ASR 证据'),
                    tr('主力转写与文字复核使用同一模型时，无法提供独立 ASR 证据。\n\n默认不推荐这样配置；高级用户仍可继续。'),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
        role, backend = target
        disabled_backend = "none" if role == "primary" else "off"
        self.backend_requested.emit(
            role,
            disabled_backend if state == "selected" else backend,
        )
        if model.api_preset and state != "selected":
            self.api_target_role = role or self.browser_role
            self.api_preset_requested.emit(model.api_preset)
        self.refresh()

    def _download(self, model: WorkshopModel):
        if model.key == "omni_asr_llm_7b":
            try:
                from twobyteasr.hardware import _visible_nvidia_gpu

                gpu_name, memory_mb = _visible_nvidia_gpu()
            except Exception:
                gpu_name, memory_mb = "", 0
            if memory_mb and memory_mb < 17 * 1024:
                answer = QMessageBox.warning(
                    self,
                    tr('显存可能不足'),
                    tr('检测到 {value0}（{value1:.1f} GiB）。\n\nOmnilingual ASR LLM 7B 官方 BF16 推理约需 17 GiB 显存，当前 GPU 可能无法完整加载。你仍然可以先下载模型文件。', value0=gpu_name or 'NVIDIA GPU', value1=memory_mb / 1024),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
        self.download_combination([model.download_key], model.name)

    def download_combination(
        self,
        download_keys,
        display_name="所选模型组合",
        *,
        auto_start=False,
    ):
        keys = tuple(dict.fromkeys(str(key) for key in download_keys if key))
        if not keys:
            return None
        if any(card.model.download_key in keys for key, card in self._cards.items() if key in self._removing):
            QMessageBox.information(self, tr('模型正在处理'), tr('请等待当前删除范围扫描或删除完成，再下载或修复。'))
            return None
        for existing in self._download_dialogs:
            same_keys = (existing.download_keys == keys)
            running = (existing.process.state() != QProcess.ProcessState.NotRunning)
            if same_keys or running:
                # P0-7: Surface even if previously hidden (download continues in background)
                existing.showNormal()
                existing.raise_()
                existing.activateWindow()
                if same_keys and auto_start and not running:
                    QTimer.singleShot(0, existing.start)
                if not same_keys:
                    existing.log.appendPlainText(
                        "\n[提示] 已有一个模型准备任务正在运行。为避免重复安装依赖，"
                        "请等待它完成后再开始下一组。"
                    )
                return existing
        representative = next(
            (model for model in MODELS if model.download_key in keys),
            next(model for model in MODELS if model.download_key),
        )
        dialog = ModelDownloadDialog(
            self.root,
            representative,
            self,
            download_keys=keys,
            display_name=display_name,
        )
        self._download_dialogs.append(dialog)
        dialog.completed.connect(lambda ok, message, current=dialog: self._download_completed(current, ok, message))
        dialog.destroyed.connect(
            lambda: self._download_dialogs.remove(dialog)
            if dialog in self._download_dialogs else None
        )
        dialog.show()
        dialog.raise_()
        self._sync_download_activity()
        # First-run presets stay one-click. Individual model cards remain idle
        # so users can choose AUTO / MODELSCOPE / HF_MIRROR / HF_OFFICIAL.
        if auto_start:
            QTimer.singleShot(0, dialog.start)
        return dialog

    def _repair_selected(self):
        model = self._cards[self.detail_model_key].model
        if model.download_key:
            self._download(model)

    def _uninstall_selected(self):
        model = self._cards[self.detail_model_key].model
        self._uninstall_model(model.key)

    def _uninstall_model(self, key: str):
        if key not in self._cards:
            return
        self._view_model(key)
        model = self._cards[key].model
        if not model.download_key:
            return
        main = self._find_main_window()
        if main and (getattr(main, '_run_in_progress', False) or
                     (getattr(main, 'worker', None) is not None and main.worker.isRunning())):
            QMessageBox.information(self, tr('任务正在运行'), tr('请先等待任务结束或正常取消任务，再永久删除模型。'))
            return
        if key in self._removing or self._active_download_dialog(model.download_key):
            QMessageBox.information(self, tr('模型正在处理'), tr('请等待当前下载或删除完成。'))
            return
        if self._model_is_current(model):
            QMessageBox.information(
                self,
                tr('正在使用这个模型'),
                tr('请先为当前角色选择另一个模型，再卸载。'),
            )
            return
        from .model_removal import plan_model_removal
        self._removing.add(key)
        self._cards[key].action.setEnabled(False)
        self._cards[key].action.setText(tr('正在扫描删除范围…'))
        def scan():
            try: payload = (key, plan_model_removal(self.root, model.download_key), '')
            except Exception as exc: payload = (key, None, str(exc))
            try: self.removal_planned.emit(payload)
            except RuntimeError: pass
        threading.Thread(target=scan, daemon=True, name='model-removal-plan').start()

    def _model_removal_busy(self, download_key):
        main = self._find_main_window()
        return bool((main and (getattr(main, '_run_in_progress', False) or
                    (getattr(main, 'worker', None) is not None and main.worker.isRunning()))) or
                    self._active_download_dialog(download_key))

    def _confirm_model_removal(self, payload):
        key, plan, error = payload
        self._removing.discard(key)
        self.refresh()
        model = self._cards[key].model
        from .model_removal import plan_model_removal, execute_removal
        from .model_storage import format_bytes
        if error:
            QMessageBox.warning(self, tr('无法确定删除范围'), error)
            return
        if self._model_removal_busy(model.download_key) or self._model_is_current(model):
            QMessageBox.information(self, tr('任务正在运行'), tr('请先等待任务结束或正常取消任务，再永久删除模型。'))
            return
        if plan.model_key != model.download_key:
            QMessageBox.information(self, tr('模型选择已变化'), tr('请重新选择需要卸载的版本，再查看删除范围。'))
            return
        preview = '\n'.join(str(p.relative_to(plan.root)) if p != plan.root else tr('模型目录链接自身') for p in plan.paths[:8])
        if len(plan.paths) > 8:
            preview += '\n' + tr('…另有 {count} 项', count=len(plan.paths) - 8)
        retained = '\n' + tr('保留 {count} 项共享或未登记文件。', count=len(plan.retained)) if plan.retained else ''
        prompt = tr('永久删除 {name}？\n\n{path}\n\n相对此目录的清单：\n{preview}\n\n'
                    '模型文件总逻辑大小 {actual}。\n'
                    '删除清单：{count} 项，逻辑大小 {logical}。\n'
                    '其中独占文件 {exclusive}；硬链接的实际空间由其他引用决定。{retained}\n\n'
                    '不会移入回收站或备份目录。',
                    name=model.name, path=str(plan.root), preview=preview, count=len(plan.paths), actual=format_bytes(plan.installed_bytes),
                    logical=format_bytes(plan.logical_bytes), exclusive=format_bytes(plan.exclusive_bytes), retained=retained)
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setWindowTitle(tr('永久删除模型文件'))
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(str(prompt) + '\n' + tr('再次使用需要下载。字幕工程、个人词库、配置和其他模型保持；共享运行环境不删除。'))
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText(tr('永久删除模型文件'))
        dialog.button(QMessageBox.StandardButton.No).setText(tr('取消'))
        delete_external = None
        if plan.mode == 'detach':
            dialog.setWindowTitle(tr('解除外部模型关联'))
            dialog.setText(tr('此模型来自手动关联的外部目录：\n{name}\n{path}\n模型逻辑大小 {size}。\n\n默认只解除关联，文件保留，预计释放 0 B。\n如要删除外部文件，请选择单独的永久删除操作并再次确认。',
                              name=model.name, path=str(plan.root), size=format_bytes(plan.installed_bytes)))
            dialog.button(QMessageBox.StandardButton.Yes).setText(tr('仅解除关联'))
            delete_external = dialog.addButton(tr('永久删除外部模型文件…'), QMessageBox.ButtonRole.DestructiveRole)
        elif plan.mode == 'unlink':
            dialog.setText(tr('模型目录是链接：\n{name}\n{path}\n\n只移除链接，外部权重文件保持。预计释放 0 B；共享运行环境不删除。',
                              name=model.name, path=str(plan.root)))
            dialog.button(QMessageBox.StandardButton.Yes).setText(tr('仅解除关联'))
        answer = dialog.exec()
        if delete_external is not None and dialog.clickedButton() == delete_external:
            try: explicit = plan_model_removal(self.root, model.download_key, allow_external_delete=True)
            except Exception as exc:
                QMessageBox.warning(self, tr('无法确定删除范围'), str(exc)); return
            confirm = QMessageBox(self)
            confirm.setWindowTitle(tr('永久删除外部模型文件'))
            confirm.setTextFormat(Qt.TextFormat.PlainText)
            confirm.setText(tr('永久删除外部模型 {name}？\n实际路径：{path}\n删除 {count} 项，逻辑大小 {logical}，预计独占大小 {exclusive}。\n保留 {retained} 项共享或未登记文件。\n删除后需要重新下载；不会删除字幕工程、词库、配置或共享运行环境。',
                               name=model.name, path=str(explicit.root), count=len(explicit.paths),
                               logical=format_bytes(explicit.logical_bytes), exclusive=format_bytes(explicit.exclusive_bytes), retained=len(explicit.retained)))
            confirm.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            confirm.setDefaultButton(QMessageBox.StandardButton.No)
            confirm.button(QMessageBox.StandardButton.Yes).setText(tr('永久删除外部模型文件'))
            confirm.button(QMessageBox.StandardButton.No).setText(tr('取消'))
            answer = confirm.exec()
            plan = explicit
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self._model_is_current(model):
            QMessageBox.information(self, tr('正在使用这个模型'), tr('请先为当前角色选择另一个模型，再卸载。'))
            return
        self._removing.add(key)
        self._cards[key].action.setEnabled(False)
        self._cards[key].action.setText(tr('正在永久删除…'))
        def remove():
            try:
                from .asr import end_local_asr_session
                result = execute_removal(plan, release=lambda: end_local_asr_session(force=True),
                                         busy_check=lambda: self._model_removal_busy(model.download_key) or self._model_is_current(model))
                payload = (key, result, '')
            except Exception as exc:
                payload = (key, None, str(exc))
            try: self.removal_finished.emit(payload)
            except RuntimeError: pass
        threading.Thread(target=remove, daemon=False, name='model-permanent-removal').start()

    def _removal_finished(self, payload):
        from .model_storage import format_bytes
        key, result, error = payload
        self._removing.discard(key)
        self.refresh()
        self.models_refreshed.emit()
        if error:
            QMessageBox.warning(self, tr('永久删除失败'), error)
            return
        if result.detached:
            QMessageBox.information(self, tr('关联已解除'), tr('已解除此模型的关联，外部文件保持，释放 0 B。\n{path}', path='\n'.join(result.detached)))
            return
        message = str(tr('已永久删除 {count} 项，逻辑大小 {logical}。\n'
                         '预计独占文件大小 {exclusive}（稀疏文件、共享或压缩文件可能更少）。\n'
                         '本磁盘可用空间变化 {delta}（包含同期其他磁盘活动）。',
                         count=len(result.removed), logical=format_bytes(result.logical_bytes),
                         exclusive=format_bytes(result.exclusive_bytes), delta=(f'{result.disk_free_delta:+d} B' if result.disk_free_delta is not None else tr('未测量'))))
        if result.failures:
            message += '\n\n' + tr('未能删除：') + '\n' + '\n'.join(f'{p}: {why}' for p, why in result.failures.items())
        if result.retained:
            message += '\n\n' + tr('保留共享或未登记文件：') + '\n' + '\n'.join(result.retained[:15])
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Information if result.completed else QMessageBox.Icon.Warning)
        dialog.setWindowTitle(tr('永久删除完成') if result.completed else tr('部分清理完成，仍有保留文件'))
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(message)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.button(QMessageBox.StandardButton.Ok).setText(tr('确定'))
        retry = None
        if result.failures:
            retry = dialog.addButton(tr('重试未删除文件'), QMessageBox.ButtonRole.ActionRole)
        dialog.exec()
        if retry is not None and dialog.clickedButton() == retry:
            QTimer.singleShot(0, lambda: self._uninstall_model(key))

    def _download_completed(self, dialog: ModelDownloadDialog, ok: bool, message: str):
        self._mac_cpu_probe_result=None
        from .environment import reset_preflight_cache
        from .runtime_registry import reset_runtime_registry_cache
        reset_runtime_registry_cache()
        reset_preflight_cache()
        self.refresh()
        self._sync_download_activity()
        # Completion and failure remain in the persistent download dialog. A
        # second native message box duplicated state and reintroduced dark
        # Windows chrome after the task had already finished.

    def _technical_details_text(self, model: WorkshopModel) -> str:
        """Plain-text counterpart for accessibility and lightweight callers."""
        online = model_is_online(model)
        privacy = (
            "在线 API：音频会离开本机，按服务商计费，需要 Key。"
            if online
            else "本地模型：音频留在本机。下载一次后可离线使用。"
        )
        profile = _technical_profile(model)
        api_model = self._api_model_for(model)
        accuracy = _metric_evidence(
            model, "accuracy", self.browser_role, self._benchmark_scene, api_model
        )
        speed = _metric_evidence(
            model, "speed", self.browser_role, self._benchmark_scene, api_model
        )
        location = "云端推理" if online else f"本机运行，占用 {model.size}"
        return (
            f"隐私与费用\n{privacy}\n\n"
            f"适合场景\n{model_scene(model)}\n\n"
            f"模型用途\n{profile.get('purpose', model.description)}\n\n"
            f"网络与位置\n{location}\n"
            f"{'需要联网。' if online else '下载时需要网络；识别可不联网。'}\n\n"
            f"输入与输出\n{profile.get('io', '输入音频；输出字幕流程所需的文字或时间信息。')}\n\n"
            f"主要优点\n{profile.get('strengths', model.description)}\n\n"
            f"主要限制\n{profile.get('limits', '实际效果会受音频质量、语言和硬件配置影响。')}\n\n"
            f"技术说明\n使用方式：{model_mode_text(model)}\n"
            f"同组证据：{accuracy.get('caption', '准确度')} {accuracy['value']}"
            f"（{accuracy['note']}） / "
            f"速度 {speed['value']}（{speed['note']}）\n"
            f"来源：{profile.get('source', model.proof)}"
        )

    def _configure_current_api(self):
        model = self._cards.get(self.detail_model_key)
        if model is not None and model.model.api_preset:
            self.api_configure_requested.emit(model.model.api_preset)

    def _show_technical_details(self):
        import time as _t
        _t0 = _t.perf_counter()
        model = self._cards[self.detail_model_key].model
        # Prefer MainWindow internal ModalHost (no new native HWND, backdrop fade only, card at final size).
        mw = self._find_main_window()
        host_parent = None
        if mw and hasattr(mw, "_modal_host"):
            try:
                host_parent = mw._modal_host.body
            except Exception:
                host_parent = None
        cache_key = (model.key, model.download_key, self.browser_role, self._benchmark_scene, self._api_model_for(model))
        content = self._technical_cache.get(cache_key)
        if content is None:
            content = ModelTechnicalDialog(
                model, host_parent, role=self.browser_role, scene=self._benchmark_scene,
                api_model=self._api_model_for(model),
            )
            self._technical_cache[cache_key] = content
        else:
            content.retranslate(current_language())
        if host_parent is not None and content.parentWidget() is not host_parent:
            content.setParent(host_parent)
        if mw and hasattr(mw, "_modal_host"):
            def _closed():
                pass
            mw._modal_host.show_content(
                content,
                title=translate("技术说明", current_language()),
                size=(710, 650),
                min_size=(590, 500),
                on_closed=_closed,
                retain_content=True,
            )
        else:
            # Fallback: wrap in a lightweight dialog if not hosted (tests/capture).
            from twobyteasr.ui import SpringDialog
            host = SpringDialog(self)
            bind_text(host, '{value0} · 技术说明', property='windowTitle', value0=model.name)
            lay = QVBoxLayout(host)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(content, 1)
            host.resize(710, 650)
            host.show()
        _dt = (_t.perf_counter() - _t0) * 1000
        try:
            if GUI_PROFILE_ENABLED:
                print(f"[perf] _show_technical_details({model.key}) -> host ~{int(_dt)}ms")
        except Exception:
            pass

    def _find_main_window(self):
        p = self.parentWidget()
        while p:
            if hasattr(p, "_modal_host"):
                return p
            p = p.parentWidget()
        return None


class ModelPickerPanel(QWidget):
    """Shared role-scoped model picker used by the recognition home.

    It intentionally delegates state, downloads, API setup and backend changes
    to ``ModelWorkshopPage`` instead of keeping a second model catalog or a
    second installation path.
    """

    close_requested = Signal()

    ROLE_LABELS = {
        "primary": "主力转写",
        "timeline": "字幕时间轴",
        "review": "文字复核",
    }

    def __init__(self, controller: ModelWorkshopPage, role: str, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.role = role if role in self.ROLE_LABELS else "primary"
        self.cards: dict[str, ModelCard] = {}
        self._pinned_keys: list[str] = []
        self.setStyleSheet(build_workshop_qss())
        self._build()
        self.controller.models_refreshed.connect(self.refresh)
        # Populate from the controller's cached install state before first paint.
        # This is widget-only work; the controller owns all disk scans.
        self.refresh()

    def refresh_theme_palette(self) -> None:
        self.setStyleSheet(build_workshop_qss())

    def begin_session(self) -> None:
        """Reset temporary pinning when the cached picker is opened again."""
        self._pinned_keys.clear()
        self.refresh()
        self.scroll.verticalScrollBar().setValue(0)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.breadcrumb = QLabel()
        self.breadcrumb.setObjectName("workshopMuted")
        title_box.addWidget(self.breadcrumb)
        title = QLabel("选择模型")
        title.setObjectName("workshopPageTitle")
        title_box.addWidget(title)
        note = QLabel("可直接下载、安装、使用或切换；模型工坊保留全部参数和高级信息。")
        note.setObjectName("workshopMuted")
        title_box.addWidget(note)
        header.addLayout(title_box, 1)
        self.current_badge = QLabel()
        self.current_badge.setObjectName("workshopBadge")
        header.addWidget(self.current_badge, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        scroll = QScrollArea()
        self.scroll = scroll
        scroll.setObjectName("workshopScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("workshopScrollHost")
        cards_layout = QVBoxLayout(host)
        self.cards_layout = cards_layout
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(10)  # P0-2: consistent 8-12px spacing in picker too
        by_key = {key: card.model for key, card in self.controller._cards.items()}
        for key in CANONICAL_MODEL_ORDER:
            model = by_key.get(key)
            if model is None or self.role not in _model_roles(model):
                continue
            card = ModelCard(model)
            card.selected.connect(self._select)
            card.action_requested.connect(self._perform_action)
            card.download_requested.connect(self.controller._download_card)
            # 三十八轮：主页选择弹窗此前没接"配置"红链的信号——点了没有任何
            # 反应（工坊页有接，弹窗漏了）。转发给 controller 的同名信号，
            # 由 MainWindow 打开对应服务商的密钥窗口。
            card.api_configure_requested.connect(
                self.controller.api_configure_requested.emit
            )
            card.set_uninstall_available(False)
            card.setToolTip(model.description)
            self.cards[key] = card
            cards_layout.addWidget(card)
        cards_layout.addStretch(1)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)
        footer = QHBoxLayout()
        footer.addStretch(1)
        close = QPushButton("完成")
        close.setObjectName("workshopAction")
        close.clicked.connect(self.close_requested)
        footer.addWidget(close)
        layout.addLayout(footer)

    def _select(self, key: str):
        if key not in self.cards:
            return
        self.controller._select_model(key, role=self.role)
        self.refresh()

    def _perform_action(self, key: str):
        self.controller._perform_action(key, role=self.role)
        self.refresh()

    def refresh(self):
        language = current_language()
        role_label = translate(self.ROLE_LABELS[self.role], language)
        (bind_text(self.breadcrumb, f'Recognition plan · {role_label}') if language == 'en' else bind_text(self.breadcrumb, '识别方案 · {value0}', value0=role_label))
        selected_name = "尚未选择"
        for key, card in self.cards.items():
            state = self.controller._model_state(card.model, self.role)
            text, enabled = self.controller._action_text(card.model, state)
            if state == "selected":
                selected_name = card.model.name
                if key not in self._pinned_keys:
                    self._pinned_keys.append(key)
            elif state == "missing":
                text = "下载并安装"
            card.action.setText(translate(text, language))
            card.action.setEnabled(enabled)
            card.set_selected(state == "selected")
            card.set_uninstall_available(False)
            if card.model.api_preset:
                ready = state in {"selected", "configured"}
                card.set_state_badge(
                    translate("已配置" if ready else "未配置", language),
                    "ready" if ready else "missing",
                )
            else:
                ready = state in {"selected", "installed", "downloaded"}
                badge_text = {'partial': '权重不完整', 'unreadable': '目录无法读取',
                              'runtime_missing': '权重已安装 · 环境未就绪',
                              'checking': '检查运行库', 'inference_pending': '推理待验证',
                              'load_failed': '权重已校验 · 加载未通过'}.get(state, "已安装" if ready else "未安装")
                card.set_state_badge(
                    translate(badge_text, language),
                    "ready" if ready else "missing",
                )
        selected_key = self.controller._selected_model_key_for_role(self.role)
        if selected_key in self.cards:
            selected_name = self.cards[selected_key].model.name
        (bind_text(self.current_badge, f'Current: {selected_name}') if language == 'en' else bind_text(self.current_badge, '当前：{value0}', value0=ui_literal(selected_name)))
        # Pin for this opening. Canceling a model must not move the button
        # away under the pointer; begin_session restores catalog order.
        selected = [key for key, card in self.cards.items() if card.property("selected")]
        pinned = selected + [key for key in self._pinned_keys if key not in selected]
        ordered = pinned + [key for key in self.cards if key not in pinned]
        for index, key in enumerate(ordered):
            card = self.cards[key]
            if self.cards_layout.itemAt(index).widget() is not card:
                self.cards_layout.removeWidget(card)
                self.cards_layout.insertWidget(index, card)
