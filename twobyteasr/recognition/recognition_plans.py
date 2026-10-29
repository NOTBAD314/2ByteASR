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


#: Plan language for every spoken language other than Chinese, Japanese and auto.
FOREIGN = "foreign"


def chinese_or_auto(language: str) -> bool:
    return str(language or "") in ("", "auto", "zh", "zh-Hant")


@dataclass(frozen=True)
class RecognitionPlan:
    key: str
    label: str
    description: str
    primary: str
    timeline: str
    review: str
    estimated_vram_gb: float
    # The spoken language the plan is for ("" = any, FOREIGN = not Chinese or
    # Japanese). 日语 and 外语 use the same backends; the language tells them
    # apart (2026-10-14).
    language: str = ""
    # Cloud transcription service the plan selects ("" = keep the current one).
    api_provider: str = ""
    # Timeline for a spoken language other than Chinese / auto, and on a
    # computer that cannot run ``timeline`` ("" = always ``timeline``).
    foreign_timeline: str = ""

    def backends(self, language: str = "", host=None) -> tuple[str, str, str]:
        """(primary, timeline, review) this plan selects for the spoken language.

        ``host``: a ``recognition_choices.HostProfile``; FireRedASR2 needs an
        NVIDIA GPU, so without one the plan's other timeline is used.
        """
        timeline = self.timeline
        if self.foreign_timeline:
            unavailable = False
            if host is not None:
                from .recognition_choices import unavailable_on_host
                unavailable = bool(unavailable_on_host("timeline", timeline, host))
            if unavailable or not chinese_or_auto(language):
                timeline = self.foreign_timeline
        return self.primary, timeline, self.review

    def for_language(self, language: str) -> bool:
        if not self.language:
            return True
        if self.language == FOREIGN:
            return not chinese_or_auto(language) and str(language) != "ja"
        return self.language == str(language or "")


RECOGNITION_PLANS: tuple[RecognitionPlan, ...] = (
    # 2026-10-23 (user): the menu is 本地识别 / API 转写 / 日语 / 外语; 自定义
    # only shows itself when the models were changed by hand.
    RecognitionPlan(
        "quality", "本地识别", "主稿 + 字级时间轴 + 独立复核，适合多人和长视频", "moss", "local", "local", 10.8
    ),
    # Cloud MOSS Pro transcription, no review pass; word times by FireRedASR2
    # for Chinese (and auto), by Qwen3-ForcedAligner for other languages or
    # without an NVIDIA GPU. Choosing it asks for the MOSS Pro key when none
    # is saved (2026-10-22: replaced 速度优先 / 省显存 / 仅转写 / the old API 转写).
    RecognitionPlan(
        "moss_pro_qwen", "API 转写",
        "云端 MOSS Pro 转写 + 本机字级时间轴（中文用 FireRedASR2，其他语言用 Qwen3 对齐），不做复核；需 MOSS Pro API Key",
        "api", "local", "off", 4.5, api_provider="mosi_moss_pro", foreign_timeline="qwen_aligner",
    ),
    # 2026-10-14 (user request): language presets. For Japanese and the other
    # languages the Chinese timeline model is never used; words are timed by
    # Qwen3-ForcedAligner-0.6B and, for Japanese, line starts are checked by the
    # Japanese CTC aligner. Review is the local Qwen3-ASR 1.7B.
    RecognitionPlan(
        "japanese", "日语", "MOSS 主稿 + Qwen3 对齐字词时间、日语 CTC 校正句首 + Qwen3-ASR 1.7B 复核",
        "moss", "qwen_aligner", "local", 10.8, "ja",
    ),
    RecognitionPlan(
        "english", "外语", "MOSS 主稿 + Qwen3-ForcedAligner 0.6B 单词时间 + Qwen3-ASR 1.7B 复核",
        "moss", "qwen_aligner", "local", 10.8, FOREIGN,
    ),
    RecognitionPlan(
        "custom", "自定义", "保留当前底层模型组合", "", "", "", 0.0
    ),
)

_BY_KEY = {plan.key: plan for plan in RECOGNITION_PLANS}


#: Plans removed on 2026-10-22; saved profiles naming them read as custom.
REMOVED_PLANS = frozenset({"speed", "low_memory", "transcribe_only", "api"})


def recognition_plan(key: str) -> RecognitionPlan:
    """Return a known plan, falling back to custom for stale settings."""
    return _BY_KEY.get(str(key), _BY_KEY["custom"])


def matching_plan(primary: str, timeline: str, review: str, language: str = "",
                  provider: str | None = None) -> str:
    """The plan with these backends; a language plan only for its language.

    ``provider``: the selected cloud service; a plan naming one matches only
    it (``None`` = not known, do not check). A plan with two timelines
    (API 转写) matches either."""
    values = (str(primary), str(timeline), str(review))
    for plan in RECOGNITION_PLANS:
        timelines = {plan.timeline, plan.foreign_timeline} - {""}
        if (plan.key != "custom" and (values[0], values[2]) == (plan.primary, plan.review)
                and values[1] in timelines and plan.for_language(language)
                and (not plan.api_provider or provider is None or plan.api_provider == provider)):
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
    # 2026-10-22: the light local plans are gone; without a GPU the cloud plan
    # is the light first pass. No expensive media inspection is needed here.
    if files and has_gpu is False:
        recommended = "moss_pro_qwen"
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
        "estimated_minutes_per_hour": 18 if plan.key == "moss_pro_qwen" else 42,
    }


def plan_options() -> tuple[RecognitionPlan, ...]:
    """The plans people choose from; 自定义 is a state, shown only when it is the current one."""
    return tuple(plan for plan in RECOGNITION_PLANS if plan.key != "custom")
