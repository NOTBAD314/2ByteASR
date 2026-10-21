"""Shared terminology thresholds without pipeline import dependencies."""

ASR_CONSENSUS_MIN_SIMILARITY = 0.82

ASR_CONSENSUS_PROTECTED_PHRASES = (
    "满命",
    "卡池",
    "抽卡",
    "小保底",
    "大保底",
    "双黄",
    "连金",
    "没问题",
    "没关系",
    "没垫",
    "垫那么",
)

MOSS_TERM_STABILITY_MIN_SEGMENTS = 2
MOSS_TERM_STABILITY_MIN_CHARS = 2
MOSS_TERM_STABILITY_MAX_CHARS = 6
MOSS_DOMAIN_TERM_SUFFIXES = frozenset(
    "兽灵蛙刺药环线印势袭刃角桥潮涌增扉盒豹岩皇"
)
MOSS_TERM_STABILITY_STOPWORDS = frozenset(
    (
        "我们", "你们", "他们", "这个", "那个", "然后", "但是", "因为",
        "所以", "就是", "现在", "还是", "可以", "不是", "没有", "一个",
        "一下", "一点", "的话", "真的", "直接", "感觉", "知道", "可能",
        "已经", "不会", "不要", "什么", "怎么", "时候", "这里", "那里",
        "自己", "对面", "进行", "还有", "把他", "他会", "我的", "他的",
        "让他", "给他", "是他",
    )
)
GLOBAL_DOMAIN_TERM_SUFFIXES = MOSS_DOMAIN_TERM_SUFFIXES | frozenset(
    "点术技招宠队林绞泻"
)

__all__ = [
    "GAME_LEXICON_MAX_PROMPT_TERMS",
    "ASR_CONSENSUS_MIN_SIMILARITY",
    "ASR_CONSENSUS_PROTECTED_PHRASES",
    "MOSS_TERM_STABILITY_MIN_SEGMENTS",
    "MOSS_TERM_STABILITY_MIN_CHARS",
    "MOSS_TERM_STABILITY_MAX_CHARS",
    "MOSS_DOMAIN_TERM_SUFFIXES",
    "MOSS_TERM_STABILITY_STOPWORDS",
    "GLOBAL_DOMAIN_TERM_SUFFIXES",
]

GAME_LEXICON_MAX_PROMPT_TERMS = 120
