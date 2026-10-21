"""Which languages each model handles, for the language badges (2026-10-18).

Users could not tell which models work for Chinese, Japanese and so on: the
cards only showed a one-word summary such as "中文" (MOSS) or nothing (cloud
services). Every model now carries the same six badges, in the same order, on
the model cards of the role pickers and the workshop and on the home cards.

Tiers come only from official sources (README, model card, paper, API docs;
URL in ``source``), checked 2026-10-18:

- ``strong``: officially listed as a main language, or official per-language
  results are good;
- ``usable``: supported, but official results are clearly weaker, or it is only
  covered by a broad "N languages" claim with no per-language evidence;
- ``no``: officially out of scope (e.g. an English-only model);
- a language left out of ``tiers`` is unknown: the sources do not say.

On screen there are three colours (2026-10-19, the user found four badge
styles and a "日语" sample in the legend confusing): green = supported
(``strong`` and ``usable``; the tooltip says when official results are
weaker), orange = not sure (``unknown``), red = not supported (``no``).
Large cloud models cover the common languages (MAI-Transcribe-2 lists 60), so
they are rated from their family's published list instead of "not stated".

``more`` is how many further languages the model covers beyond the badges
(``"50+"`` when only a lower bound is published). ``summary`` is a short
Chinese source string (translated through the locales) used on the home card
and in the badge tooltips. The full enumerated lists stay in
``model_evaluation_metadata`` (technical details page).

Pure data and functions: no Qt.
"""

from __future__ import annotations

BADGE_LANGUAGES = ("zh", "yue", "dialects", "en", "ja", "ko")
TIERS = ("strong", "usable", "no", "unknown")

# Chinese source strings; the locales translate them.
LANGUAGE_NAMES = {"zh": "中文", "yue": "粤语", "dialects": "方言", "en": "英语", "ja": "日语", "ko": "韩语"}
TIER_NAMES = {"strong": "支持", "usable": "支持（官方成绩稍弱）", "no": "不支持", "unknown": "不确定"}
# Badge colour per tier, and the three colours the legend explains.
TIER_COLORS = {"strong": "yes", "usable": "yes", "unknown": "unsure", "no": "no"}
LEGEND = (("yes", "支持"), ("unsure", "不确定"), ("no", "不支持"))

# One-character labels for the narrow home cards, per interface language.
_SHORT_NAMES = {
    "zh": {"zh": "中", "yue": "粤", "dialects": "方", "en": "英", "ja": "日", "ko": "韩"},
    "zh-Hant": {"zh": "中", "yue": "粵", "dialects": "方", "en": "英", "ja": "日", "ko": "韓"},
    "en": {"zh": "ZH", "yue": "YUE", "dialects": "DIA", "en": "EN", "ja": "JA", "ko": "KO"},
    "ja": {"zh": "中", "yue": "粤", "dialects": "方", "en": "英", "ja": "日", "ko": "韓"},
    "ko": {"zh": "중", "yue": "광", "dialects": "방", "en": "영", "ja": "일", "ko": "한"},
}


def _tiers(text: str) -> dict[str, str]:
    return dict(item.split(":") for item in text.split())


_QWEN3_ASR = {
    "tiers": _tiers("zh:strong yue:strong dialects:strong en:strong ja:strong ko:strong"),
    "more": 25, "summary": "30 种语言 · 22 种方言",
    "source": "https://github.com/QwenLM/Qwen3-ASR",
}
_QWEN3_ALIGNER = {
    "tiers": _tiers("zh:strong yue:strong dialects:no en:strong ja:strong ko:strong"),
    "more": 6, "summary": "11 种语言",
    "source": "https://github.com/QwenLM/Qwen3-ASR",
}
_FIRERED = {
    "tiers": _tiers("zh:strong yue:strong dialects:strong en:strong ja:no ko:no"),
    "summary": "中英 · 20+ 种方言口音",
    "source": "https://github.com/FireRedTeam/FireRedASR2S",
}
_WHISPER = {
    "tiers": _tiers("zh:strong yue:usable en:strong ja:strong ko:strong"),
    "more": 95, "summary": "约 100 种语言",
    "source": "https://github.com/openai/whisper",
}

_MOSS = {
    "tiers": _tiers("zh:strong yue:usable en:strong ja:usable ko:usable"),
    "more": "50+", "summary": "50+ 种语言",
    "source": "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize",
}

LANGUAGE_SUPPORT: dict[str, dict] = {
    # README: "supports 50+ languages", no list; evaluated on Mandarin
    # meetings, podcasts and mainly Chinese/English films (some ja/ko/yue).
    "moss": _MOSS,
    # The cloud Pro API docs name no languages; it is the hosted MOSS family,
    # whose card claims 50+ languages (and won the 14-language MLC-SLM
    # challenge, ja/ko/en included), so it is rated like the open model.
    "mosi_moss_pro": dict(_MOSS, source="https://huggingface.co/OpenMOSS-Team/MOSS-Transcribe-Diarize"),
    "firered": _FIRERED,
    "firered_llm": _FIRERED,
    "qwen_local": _QWEN3_ASR,
    "qwen_aligner": _QWEN3_ALIGNER,
    # Qwen-Audio-3.1: 30 languages + dialects; Qwen3-ASR-Flash lists 26.
    "qwen_cloud_filetrans": {
        "tiers": _tiers("zh:strong yue:strong dialects:strong en:strong ja:strong ko:strong"),
        "more": 25, "summary": "30 种语言 · 10 种方言",
        "source": "https://docs.qwencloud.com/developer-guides/speech/speech-to-text-models",
    },
    "qwen31_filetrans": {
        "tiers": _tiers("zh:strong yue:strong dialects:strong en:strong ja:strong ko:strong"),
        "more": 25, "summary": "30 种语言 · 多种方言",
        "source": "https://help.aliyun.com/zh/model-studio/asr-model",
    },
    # 中英听写: Chinese, English and 202 dialects; the language is fixed to zh_cn.
    "spark_asr_v2": {
        "tiers": _tiers("zh:strong yue:strong dialects:strong en:strong ja:no ko:no"),
        "summary": "中英 · 202 种方言",
        "source": "https://www.xfyun.cn/doc/spark/spark_zh_iat_new.html",
    },
    # 17 languages without Korean; Japanese is in the weaker WER <= 20% group.
    "glm_asr_nano": {
        "tiers": _tiers("zh:strong yue:strong dialects:usable en:strong ja:usable ko:no"),
        "more": 13, "summary": "17 种语言",
        "source": "https://github.com/zai-org/GLM-ASR",
    },
    "canary_qwen": {
        "tiers": _tiers("zh:no yue:no dialects:no en:strong ja:no ko:no"),
        "summary": "仅英语",
        "source": "https://huggingface.co/nvidia/canary-qwen-2.5b",
    },
    # Official per-language CER: zh 11.5, yue 17.0, ja 19.2, ko 5.8, en 3.0 (%).
    "omni_asr_llm_7b": {
        "tiers": _tiers("zh:usable yue:usable dialects:usable en:strong ja:usable ko:strong"),
        "more": "1600+", "summary": "1600+ 种语言",
        "source": "https://github.com/facebookresearch/omnilingual-asr",
    },
    # English is the weakest of the five in the official chart.
    "sensevoice": {
        "tiers": _tiers("zh:strong yue:strong en:usable ja:strong ko:strong"),
        "summary": "5 种语言",
        "source": "https://github.com/FunAudioLLM/SenseVoice",
    },
    # The checkpoint card says Mandarin training only; FunASR's list adds en.
    "paraformer": {
        "tiers": _tiers("zh:strong en:usable ja:no ko:no"),
        "summary": "中文普通话",
        "source": "https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    },
    "whisper": _WHISPER,
    # Fun-ASR-Nano-2512 (not the 31-language MLT-Nano).
    "funasr_nano": {
        "tiers": _tiers("zh:strong yue:strong dialects:strong en:strong ja:strong ko:no"),
        "summary": "中英日 · 7 大方言",
        "source": "https://github.com/FunAudioLLM/Fun-ASR",
    },
    "ja_ctc_aligner": {
        "tiers": _tiers("zh:no yue:no dialects:no en:no ja:strong ko:no"),
        "summary": "仅日语",
        "source": "https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-japanese",
    },
    # Only the Mandarin (China) and Japanese model sets are installed; Japanese
    # is weaker in the 2026-10-19 comparison (names it does not know).
    "mfa_aligner": {
        "tiers": _tiers("zh:strong yue:no dialects:no en:no ja:usable ko:no"),
        "summary": "中文 · 日语（实验）",
        "source": "https://huggingface.co/MontrealCorpusTools",
    },
    "groq_api": dict(_WHISPER, more="99+", summary="99+ 种语言",
                     source="https://console.groq.com/docs/speech-to-text"),
    # The default gpt-transcribe has no per-language results; the docs accept
    # cmn / yue codes; gpt-4o-transcribe FLEURS: en 2.46, ja 3.0, ko 4.07, zh ~7.
    "openai_api": {
        "tiers": _tiers("zh:strong yue:usable en:strong ja:strong ko:strong"),
        "source": "https://platform.openai.com/docs/guides/speech-to-text",
    },
    # The MAI-Transcribe family's newest published list (MAI-Transcribe-2):
    # 60 languages, zh / yue / en / ja / ko each listed. Dialects not named.
    "mai_latest": {
        "tiers": _tiers("zh:strong yue:strong en:strong ja:strong ko:strong"),
        "more": 55, "summary": "60 种语言",
        "source": "https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe",
    },
    # Whatever service the user connects: nothing can be said in advance.
    "custom_asr_api": {"tiers": {}, "source": ""},
    # Apple Silicon ports of the same checkpoints.
    "mlx_qwen3_asr_0_6b": _QWEN3_ASR,
    "mlx_qwen3_asr_1_7b": _QWEN3_ASR,
    "mlx_qwen_aligner": _QWEN3_ALIGNER,
}


def language_support(key: str) -> dict | None:
    """``{"tiers": {code: tier for all six}, "more", "summary", "source"}`` or None."""
    record = LANGUAGE_SUPPORT.get(key)
    if record is None:
        return None
    tiers = record.get("tiers", {})
    return {
        "tiers": {code: tiers.get(code, "unknown") for code in BADGE_LANGUAGES},
        "more": record.get("more"),
        "summary": record.get("summary", ""),
        "source": record.get("source", ""),
    }


# Interfaces without their own row read the codes the English one uses
# (es / de / fr / pt / it / ru, 2026-10-19).
_LATIN_CODE_LANGUAGES = frozenset({"es", "de", "fr", "pt", "it", "ru"})


def short_name(code: str, ui_language: str) -> str:
    fallback = "en" if ui_language in _LATIN_CODE_LANGUAGES else "zh"
    return _SHORT_NAMES.get(ui_language, _SHORT_NAMES[fallback])[code]


def more_text(more, *, short: bool = False) -> str:
    """Chinese source text of the "more languages" badge ("" when none)."""
    if not more:
        return ""
    if isinstance(more, str):  # a published lower bound such as "50+"
        return more if short else "共 {count} 种"
    return "+{count}" if short else "+{count} 种"
