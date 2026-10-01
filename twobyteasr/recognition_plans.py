"""Small, deterministic recognition-plan layer for the desktop workflow.

The UI should let a new user choose an outcome before exposing model details.
These plans are intentionally data-only: applying one still goes through the
existing backend selectors and persistence path, so advanced users retain the
same controls and validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True)
class RecognitionPlan:
    key: str
    label: str
    description: str
    primary: str
    timeline: str
    review: str
    estimated_vram_gb: float


RECOGNITION_PLANS: tuple[RecognitionPlan, ...] = (
    RecognitionPlan(
        "quality", "质量优先（推荐）", "主稿 + 字级时间轴 + 独立复核，适合多人和长视频", "moss", "local", "local", 10.8
    ),
    RecognitionPlan(
        "speed", "速度优先", "轻量主稿，尽快得到可编辑字幕", "sensevoice", "off", "off", 1.2
    ),
    RecognitionPlan(
        "low_memory", "省显存", "CPU 友好或在线处理，适合低配置设备", "sensevoice", "off", "off", 1.2
    ),
    RecognitionPlan(
        "transcribe_only", "仅转写", "只生成文字稿，不额外建立字幕时间轴", "moss", "off", "off", 1.7
    ),
    RecognitionPlan(
        # 三十三轮：用户点名"API 接管主力转写+字幕时间轴"——timeline 关闭时
        # 管线沿用主力 ASR 的转写块边界作为时间轴（moss_firered_pipeline
        # timeline-off 语义），即由 API 块接管时间轴；复核同走 API。
        "api", "API 转写", "在线 API 接管主力转写与时间轴（块边界）；免下载，需 API Key", "api", "off", "api", 0.0
    ),
    RecognitionPlan(
        "custom", "自定义", "保留当前底层模型组合", "", "", "", 0.0
    ),
)

_BY_KEY = {plan.key: plan for plan in RECOGNITION_PLANS}


def recognition_plan(key: str) -> RecognitionPlan:
    """Return a known plan, falling back to custom for stale settings."""
    return _BY_KEY.get(str(key), _BY_KEY["custom"])


def matching_plan(primary: str, timeline: str, review: str) -> str:
    values = (str(primary), str(timeline), str(review))
    for plan in RECOGNITION_PLANS:
        if plan.key != "custom" and values == (plan.primary, plan.timeline, plan.review):
            return plan.key
    return "custom"


def lightweight_media_profile(paths: Sequence[str | Path], *, has_gpu: bool | None = None) -> dict[str, object]:
    """Build a cheap recommendation profile without decoding media or calling AI."""
    files = []
    total_bytes = 0
    for raw in paths:
        path = Path(str(raw))
        try:
            stat = path.stat()
        except OSError:
            continue
        files.append(path)
        total_bytes += int(stat.st_size)
    audio_like = all(path.suffix.lower() in {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg"} for path in files) if files else False
    # Large batches and audio-only files are more likely to benefit from a
    # lighter first pass; no expensive media inspection is needed here.
    if not files:
        recommended = "quality"
    elif audio_like and total_bytes < 2 * 1024**3:
        recommended = "speed"
    elif total_bytes > 8 * 1024**3 or len(files) > 4:
        recommended = "low_memory"
    else:
        recommended = "quality"
    plan = recognition_plan(recommended)
    return {
        "file_count": len(files),
        "total_bytes": total_bytes,
        "audio_only": audio_like,
        "has_gpu": has_gpu,
        "recommended_plan": plan.key,
        "estimated_vram_gb": plan.estimated_vram_gb,
        "estimated_minutes_per_hour": 18 if plan.key in {"speed", "low_memory"} else 42,
    }


def plan_options() -> tuple[RecognitionPlan, ...]:
    return RECOGNITION_PLANS
