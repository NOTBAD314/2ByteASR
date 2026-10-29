"""Graphics card check before a local model is downloaded (2026-10-15).

User report: on an RTX 2060 (6 GB) local recognition was very slow or ran out
of graphics memory. Before a download, the model workshop and the first-run
chooser read the NVIDIA card and its memory, and say plainly when a model will
not fit, will struggle, or needs an NVIDIA card this computer does not have,
recommending MOSS Pro 云端 (online) instead. It is a reminder only: the user
can still download.

Thresholds are total graphics memory in GiB, as ``nvidia-smi`` reports it.
Where they come from (all measurements on the RTX 5070 Ti 16 GB development
PC; no 4-12 GB card has been measured):

- MOSS: 1.7 GiB weights; peak 2.0 GB on short clips, 2.6 GB with 300 s
  windows, 3.5 GB for 688 s in one pass (docs/architecture/recognition.md).
  Long audio is split by free memory, at least 180 s per window, which needs
  about 3.8 GiB free; a 6 GB card splits long videos into many windows.
- FireRed AED: 2.2-2.5 GiB allocated, 2.76 GiB reserved at batch 1
  (2026-09-16 47-minute run); ``asr_progress`` keeps one model at a time below
  6 GiB free.
- Qwen3-ASR 1.7B: 4.4 GB of fp16/bf16 weights; Windows commit (which counts
  graphics allocations 1:1) grew 4.8 GiB after load and 6.2 GiB at peak during
  the load check (exec plan 2026-10-15-worker-page-file-1455). A 6 GB card
  minus what the desktop uses cannot hold that.
- Qwen3-ForcedAligner 0.6B: 1.75 GB file, commit +3.5 GiB at peak; it falls
  back to the CPU without CUDA.
- Japanese CTC aligner: 1.27 GB fp32 weights, commit peak 3.4 GB; CPU fallback.
- FireRedASR2-LLM: the pipeline itself requires 15.5 GB
  (``FIRERED_LLM_MIN_GPU_GB``); Omnilingual 7B: official BF16 needs ~17 GiB;
  Whisper large-v3-turbo: official card ~6 GB.
- Models without a measurement (Fun-ASR-Nano, GLM-ASR-Nano, Canary-Qwen,
  SenseVoice, Paraformer): weights plus about 2 GB, rounded up to a card size.

Models run one after another unless the card has 14 GB or more, so a
combination needs what its largest model needs.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Cards report a little under their nominal size (an 8 GB card: 8188 MiB).
_TOLERANCE_GB = 0.25


@dataclass(frozen=True)
class VramNeed:
    label: str
    minimum_gb: float      # below this the model very likely runs out of memory
    comfortable_gb: float  # below this it runs, but slowly or with little headroom
    needs_cuda: bool       # False: runs on the CPU (slower) without an NVIDIA card


MODEL_VRAM: dict[str, VramNeed] = {
    "moss": VramNeed("MOSS", 5, 8, True),
    "firered_aed": VramNeed("FireRed AED", 4, 6, True),
    "qwen_asr": VramNeed("Qwen3-ASR 1.7B", 8, 10, True),
    "qwen_aligner": VramNeed("Qwen3-ForcedAligner 0.6B", 4, 6, False),
    "ja_ctc_aligner": VramNeed("日语 CTC 对齐模型", 3, 4, False),
    "mfa_aligner": VramNeed("Montreal Forced Aligner（CPU）", 0, 0, False),
    "whisper_turbo": VramNeed("Whisper large-v3-turbo", 4, 6, False),
    "sensevoice": VramNeed("SenseVoice", 2, 4, False),
    "paraformer": VramNeed("Paraformer", 2, 4, False),
    "funasr_nano": VramNeed("Fun-ASR-Nano", 4, 6, True),
    "glm_asr_nano": VramNeed("GLM-ASR-Nano", 6, 8, True),
    "canary_qwen": VramNeed("Canary-Qwen 2.5B", 6, 8, True),
    "firered_llm": VramNeed("FireRedASR2-LLM", 15.5, 16, True),
    "omni_asr_llm_7b": VramNeed("Omnilingual ASR LLM 7B", 17, 20, True),
}

MOSS_PRO_PRESET = "mosi_moss_pro"


@dataclass(frozen=True)
class GpuInventory:
    """``status``: ``nvidia`` (name and memory read), ``no_nvidia``, ``unknown``
    (an NVIDIA tool exists but the card or its memory could not be read) or
    ``not_applicable`` (macOS: Apple GPUs use shared memory, checked elsewhere)."""

    status: str
    name: str = ""
    total_mb: int = 0
    detail: str = ""

    @property
    def total_gb(self) -> float:
        return self.total_mb / 1024.0


@dataclass(frozen=True)
class VramAssessment:
    """``level``: ``ok``, ``tight``, ``insufficient``, ``no_nvidia``,
    ``cpu_only`` (no NVIDIA card, but every model falls back to the CPU),
    ``unknown`` or ``not_applicable``."""

    level: str
    inventory: GpuInventory
    keys: tuple[str, ...]          # the models that set the level
    minimum_gb: float = 0.0
    comfortable_gb: float = 0.0

    @property
    def warn(self) -> bool:
        return self.level not in {"ok", "not_applicable"}

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(MODEL_VRAM[key].label for key in self.keys)


def parse_nvidia_smi(text: str) -> list[tuple[str, int]]:
    """``name, memory.total`` CSV rows (``--format=csv,noheader,nounits``)."""
    cards = []
    for line in str(text or "").splitlines():
        name, _, memory = line.strip().rpartition(",")
        memory = memory.strip()
        if name.strip() and memory.isdigit():
            cards.append((name.strip(), int(memory)))
    return cards


def _nvidia_smi() -> str:
    found = shutil.which("nvidia-smi")
    if found:
        return found
    # Older drivers install it here without adding it to PATH.
    for candidate in (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe",
                      Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe"):
        if candidate.is_file():
            return str(candidate)
    return ""


_CACHED: GpuInventory | None = None


def read_gpu_inventory(*, refresh: bool = False) -> GpuInventory:
    """The NVIDIA card with the most memory. A successful read is kept for the session."""
    global _CACHED
    if sys.platform == "darwin":
        return GpuInventory("not_applicable")
    if _CACHED is not None and not refresh:
        return _CACHED
    tool = _nvidia_smi()
    if not tool:
        return GpuInventory("no_nvidia", detail="nvidia-smi not found")
    try:
        from .processes import run_hidden_subprocess, run_subprocess_with_tree_kill
        result = run_hidden_subprocess(
            [tool, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            purpose="nvidia-smi VRAM check before model download",
            runner=run_subprocess_with_tree_kill,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return GpuInventory("unknown", detail=str(exc)[:200])
    cards = parse_nvidia_smi(result.stdout)
    if not cards:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        name = str(result.stdout or "").split(",", 1)[0].strip() if "," in str(result.stdout or "") else ""
        return GpuInventory("unknown", name=name, detail=(detail[0] if detail else f"exit {result.returncode}")[:200])
    name, total = max(cards, key=lambda card: card[1])
    _CACHED = GpuInventory("nvidia", name=name, total_mb=total)
    return _CACHED


def inventory_from_cuda_status(status) -> GpuInventory:
    """Reuse a ``hardware.detect_cuda_runtime`` result the dialog already has."""
    if sys.platform == "darwin":
        return GpuInventory("not_applicable")
    if status is None:
        return GpuInventory("unknown", detail="check failed")
    name = str(getattr(status, "gpu_name", "") or "")
    memory = int(getattr(status, "memory_mb", 0) or 0)
    if name and memory > 0:
        return GpuInventory("nvidia", name=name, total_mb=memory)
    if name:
        return GpuInventory("unknown", name=name, detail=str(getattr(status, "summary", "") or ""))
    return GpuInventory("no_nvidia", detail=str(getattr(status, "code", "") or ""))


def assess(keys, inventory: GpuInventory) -> VramAssessment:
    """How the combination ``keys`` (download keys) fits this card."""
    needs = [(key, MODEL_VRAM[key]) for key in dict.fromkeys(str(key) for key in keys) if key in MODEL_VRAM]
    if inventory.status == "not_applicable":
        return VramAssessment("not_applicable", inventory, ())
    if not needs:
        return VramAssessment("ok", inventory, ())
    if inventory.status == "no_nvidia":
        cuda = tuple(key for key, need in needs if need.needs_cuda)
        if cuda:
            return VramAssessment("no_nvidia", inventory, cuda)
        return VramAssessment("cpu_only", inventory, tuple(key for key, _need in needs))
    if inventory.status != "nvidia":
        top = max(need.comfortable_gb for _key, need in needs)
        return VramAssessment("unknown", inventory, tuple(key for key, need in needs if need.comfortable_gb == top),
                              max(need.minimum_gb for _key, need in needs), top)
    total = inventory.total_gb + _TOLERANCE_GB
    short = [(key, need) for key, need in needs if total < need.minimum_gb]
    if short:
        return VramAssessment("insufficient", inventory, tuple(key for key, _need in short),
                              max(need.minimum_gb for _key, need in short),
                              max(need.comfortable_gb for _key, need in short))
    tight = [(key, need) for key, need in needs if total < need.comfortable_gb]
    if tight:
        return VramAssessment("tight", inventory, tuple(key for key, _need in tight),
                              max(need.minimum_gb for _key, need in tight),
                              max(need.comfortable_gb for _key, need in tight))
    return VramAssessment("ok", inventory, ())


# A combination the user has already been warned about and chose to keep, so
# the first-run chooser and the workshop download that follows do not ask twice.
_ACKNOWLEDGED: set[frozenset[str]] = set()


def acknowledge(keys) -> None:
    _ACKNOWLEDGED.add(frozenset(str(key) for key in keys))


def acknowledged(keys) -> bool:
    wanted = frozenset(str(key) for key in keys)
    return any(wanted <= seen for seen in _ACKNOWLEDGED)


def _gb(value: float) -> str:
    return f"{value:g}"


def _models(assessment: VramAssessment) -> str:
    from ..i18n import current_language, ui_literal
    separator = "、" if current_language().startswith("zh") else ", "
    return separator.join(ui_literal(label) for label in assessment.labels)


def warning_text(assessment: VramAssessment) -> tuple[str, str]:
    """``(title, body)`` in the interface language, for a reminder dialog."""
    from ..i18n import tr

    models = _models(assessment)
    card = assessment.inventory
    online = tr("MOSS Pro 云端（在线识别）不用下载本地模型、不占显卡，需要 API Key，识别时会上传音频。")
    if assessment.level == "insufficient":
        return tr("显存不足"), tr(
            "检测到 {gpu}（{memory:.1f} GB 显存）。\n{models} 运行时约需 {need} GB 以上显存，"
            "这张显卡很可能显存溢出、无法完成识别。\n\n建议改用 MOSS Pro 云端。{online}",
            gpu=card.name, memory=card.total_gb, models=models, need=_gb(assessment.minimum_gb), online=online)
    if assessment.level == "tight":
        return tr("显存偏紧"), tr(
            "检测到 {gpu}（{memory:.1f} GB 显存）。\n{models} 建议至少 {need} GB 显存。这张显卡能运行，但会比较吃力："
            "长视频更慢，同时开着游戏、浏览器等占显存的程序时可能显存不足。\n\n更省事的选择：改用 MOSS Pro 云端。{online}",
            gpu=card.name, memory=card.total_gb, models=models, need=_gb(assessment.comfortable_gb), online=online)
    if assessment.level == "no_nvidia":
        return tr("没有检测到 NVIDIA 显卡"), tr(
            "这台电脑没有检测到 NVIDIA 显卡（或没有安装 NVIDIA 驱动）。{models} 需要 NVIDIA 显卡（CUDA），"
            "下载后也无法运行。\n\n建议改用 MOSS Pro 云端。{online}\n如果这台电脑确实有 NVIDIA 显卡，请先安装或更新 NVIDIA 驱动。",
            models=models, online=online)
    if assessment.level == "cpu_only":
        return tr("没有检测到 NVIDIA 显卡"), tr(
            "这台电脑没有检测到 NVIDIA 显卡。{models} 会改用 CPU 运行，速度明显较慢。\n\n想更快可以改用 MOSS Pro 云端。{online}",
            models=models, online=online)
    if assessment.level == "unknown":
        found = tr("检测到 {gpu}，但读不到显存", gpu=card.name) if card.name else tr("读不到显卡型号和显存")
        return tr("读不到显卡信息"), tr(
            "{found}（{detail}）。\n{models} 需要 NVIDIA 显卡，建议至少 {need} GB 显存。"
            "不确定这台电脑是否满足时，建议改用 MOSS Pro 云端。{online}",
            found=found, detail=card.detail or "nvidia-smi", models=models, need=_gb(assessment.comfortable_gb),
            online=online)
    return "", ""


def inline_text(assessment: VramAssessment) -> str:
    """One or two sentences under the first-run model choice ('' when it fits)."""
    from ..i18n import tr

    card = assessment.inventory
    models = _models(assessment)
    if assessment.level == "insufficient":
        return tr("检测到 {gpu}（{memory:.1f} GB 显存）：{models} 约需 {need} GB 以上显存，很可能显存溢出、无法运行。"
                  "建议改用在线识别（MOSS Pro 云端）。",
                  gpu=card.name, memory=card.total_gb, models=models, need=_gb(assessment.minimum_gb))
    if assessment.level == "tight":
        return tr("检测到 {gpu}（{memory:.1f} GB 显存）：{models} 建议至少 {need} GB 显存，能运行但会比较吃力。"
                  "也可以改用在线识别（MOSS Pro 云端）。",
                  gpu=card.name, memory=card.total_gb, models=models, need=_gb(assessment.comfortable_gb))
    if assessment.level == "unknown":
        return tr("读不到显卡显存，无法确认能否运行 {models}（建议至少 {need} GB 显存）。不确定时建议改用在线识别（MOSS Pro 云端）。",
                  models=models, need=_gb(assessment.comfortable_gb))
    return ""


def card_summary(assessment: VramAssessment) -> str:
    """One line for the first-run 本机识别 card."""
    from ..i18n import tr

    card = assessment.inventory
    if assessment.level == "insufficient":
        return tr("⚠ {gpu} · {memory:.1f} GB 显存，不够运行本机识别，建议云端识别", gpu=card.name, memory=card.total_gb)
    if assessment.level == "tight":
        return tr("⚠ {gpu} · {memory:.1f} GB 显存，本机识别会比较吃力", gpu=card.name, memory=card.total_gb)
    if assessment.level == "unknown":
        return tr("⚠ 读不到显存，无法确认能否运行本机识别")
    return ""


__all__ = [
    "GpuInventory", "MODEL_VRAM", "MOSS_PRO_PRESET", "VramAssessment", "VramNeed", "acknowledge", "acknowledged",
    "assess", "card_summary", "inline_text", "inventory_from_cuda_status", "parse_nvidia_smi", "read_gpu_inventory",
    "warning_text",
]
