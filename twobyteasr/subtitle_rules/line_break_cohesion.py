"""How well a Chinese line break sits between the words around it.

2026-10-21 (user clip, no API key, local line breaks): fast speech without
pauses was cut by length alone. The local repair kept every line near 8-12
characters and only knew pauses and punctuation, so it cut 就凭你还想阻止｜我？,
银河｜联军, 还是太｜保守了 and 乘客｜们. These costs feed that repair
(``segmentation.locally_repair_resegmented_cue``): a cut right after ？！ is
preferred, a cut that leaves one to three characters before ？！ to start the
next line, or that separates a word from the word it leans on, costs extra.
They only reorder the cuts the repair may already choose; the forbidden cuts
(inside a word, a number or a glossary term), real long pauses and the
16-character / 5-second limits are unchanged.
"""

import re

from twobyteasr.subtitle_rules.language_rules import CONTENT_CHAR_CLASS

# Extra preference for a cut right after a sentence end, on top of the -8 every
# punctuation / space hint already gets.
SENTENCE_END_CUT_BONUS = 6.0
# Next line = 1, 2 or 3 characters and then ？！ (阻止｜我？, 多少｜代价吗？).
SENTENCE_TAIL_CUT_COSTS = {1: 60.0, 2: 36.0, 3: 18.0}
# This line = ... ？！ and then 1 or 2 more characters (史书啊！啊｜难说).
SENTENCE_HEAD_CUT_COSTS = {1: 10.0, 2: 6.0}

# A word that needs what follows it when it ends a line. One more (shorter)
# line costs the repair about 8-9, so the words that are nearly never a line
# end weigh well above that; the others only break ties.
LEFT_LEANING_WORDS = {
    # prepositions
    **dict.fromkeys(("在", "把", "被", "跟", "给", "从", "向", "为", "为了", "关于", "对于", "按照",
                     "通过", "根据", "除了", "比", "往", "朝", "由", "请"), 24.0),
    # negation, degree and scope adverbs
    **dict.fromkeys(("太", "很", "最", "更", "挺", "非常", "特别", "比较", "有点", "都", "也", "就", "才",
                     "又", "再", "还", "不", "没", "别", "简直", "明明", "甚至", "竟然", "居然", "几乎"), 24.0),
    # time adverbs and modal verbs
    **dict.fromkeys(("已经", "正在", "将", "将会", "即将", "快要", "终于", "仍然", "依然", "一直", "马上", "立刻", "刚", "刚刚", "只", "只是", "一定",
                     "必须", "应该", "能", "会", "要", "想", "可以", "就会", "就要", "还要", "也要", "都要"), 16.0),
    # conjunctions
    **dict.fromkeys(("和", "与", "及", "以及", "而", "而且", "并且", "或者", "还是", "但", "但是", "因为",
                     "所以", "如果", "虽然", "不过", "然后", "只要", "只有", "就算", "即使", "要是", "而是",
                     "可是", "并"), 20.0),
    # attributive words and quantities waiting for their noun
    **dict.fromkeys(("最终", "唯一", "所有", "整个", "各种", "这种", "那种", "某种", "任何", "其他", "其它",
                     "另外", "一些", "这些", "那些", "那么", "这么", "多少", "每", "每个", "某", "某个",
                     "各", "哪个"), 10.0),
    **dict.fromkeys(("重新", "一起", "互相", "正式"), 10.0),
    **dict.fromkeys(("这个", "那个", "是", "有", "没有"), 6.0),
    # complement / attributive particles
    "得": 12.0, "的": 4.0, "地": 4.0,
}
# A word that leans on what precedes it when it starts a line. Particles only
# count when nothing (a space, ？！) separates them from the previous word:
# “啊 还是换种风格” starts with an interjection.
RIGHT_LEANING_WORDS = {
    "们": 40.0,
    **dict.fromkeys(("过", "着", "得", "吗", "啊", "啦", "呀", "而已", "罢了"), 14.0),
    **dict.fromkeys(("之间", "之后", "之前", "之中", "之上", "之下", "以后", "以前", "以来", "以上", "以下",
                     "期间", "当中", "里面", "外面", "上面", "下面", "中间"), 14.0),
    # verbal measures after their verb (再笑｜一次)
    **dict.fromkeys(("一次", "一遍", "一番", "一趟", "一眼", "一口", "一把"), 10.0),
}
# Where an unpunctuated clause most likely ends: after a sentence particle
# (走吧｜去, 一样啊｜感觉) and before a conjunction, an interjection or a
# subject pronoun (对不起｜但我不想后悔, 地方｜我想看你).
CLAUSE_BREAK_BONUS = 5.0
CLAUSE_END_PARTICLES = frozenset(("吧", "呢", "嘛", "啊", "呀", "啦", "哦", "咯", "呗", "吗"))
# An interjection inside unpunctuated speech marks a restart: the word before
# it may be left hanging (银河联军也｜哎这绿幕没抠干净).
INTERJECTIONS = frozenset(("哎", "哎呀", "嗯", "诶", "欸", "唉", "哈哈"))
CLAUSE_START_WORDS = frozenset((
    "但", "但是", "可是", "不过", "所以", "然后", "因为", "如果", "而且", "结果", "要是", "其实", "反正",
    "总之", "于是", *INTERJECTIONS,
))
SUBJECT_WORDS = frozenset((
    "我", "你", "他", "她", "它", "我们", "你们", "他们", "她们", "咱们", "咱", "大家", "这", "那",
    "这是", "那是", "这些", "那些",
))
# After a verb, a preposition or an adverb a pronoun is not a new subject
# (看｜我, 跟｜你, 就｜我).
NO_SUBJECT_AFTER_TAGS = frozenset(("v", "p", "d", "vn"))
# A pronoun ending a line when the next line goes on with its verb or adverb
# (开心我｜以为, 看你｜再笑一次).
SUBJECT_PRONOUNS = frozenset(("我", "你", "他", "她", "它", "我们", "你们", "他们", "她们", "咱们", "咱"))
PREDICATE_TAGS = frozenset(("v", "vn", "d", "c", "p", "a", "ad"))
SUBJECT_SPLIT_CUT_COST = 10.0
# A one-character verb and its result or direction (没抠｜干净, 画｜出来).
VERB_COMPLEMENTS = frozenset((
    "干净", "清楚", "明白", "完", "掉", "住", "到", "懂", "透", "光", "够", "坏", "好",
    "出来", "起来", "下去", "过来", "回来", "出去", "进去", "下来", "上来", "上去", "过去", "回去",
))
VERB_COMPLEMENT_CUT_COST = 14.0
# A line starting with one character and 的 is the tail of a name (芒果｜台的电视剧).
SINGLE_CHARACTER_DE_START_COST = 10.0
# A number ending a line before its noun or measure word (2.0｜版本).
NUMBER_BEFORE_NOUN_CUT_COST = 10.0
# Two dictionary nouns side by side read as one name (银河｜联军, 宇宙｜命运).
NOUN_TAGS = frozenset(("n", "nr", "nrt", "nrfg", "ns", "nt", "nz"))
NOUN_COMPOUND_CUT_COST = 8.0
# A numeral with its measure word (一个, 三个) waiting for the noun.
NUMERAL_TAGS = frozenset(("m", "mq"))
NUMERAL_CUT_COST = 10.0

_SENTENCE_END = re.compile(r"[?!？！。]")
_CONTENT = re.compile(f"[{CONTENT_CHAR_CLASS}]")


def _gaps_after(text):
    """[(content offset, text between that character and the next)]."""
    positions = [index for index, char in enumerate(text) if _CONTENT.match(char)]
    return [(offset, text[position + 1:positions[offset]] if offset < len(positions) else text[position + 1:])
            for offset, position in enumerate(positions, start=1)]


def sentence_end_offsets(text):
    """Content offsets right after ？！。 (the end of the text included)."""
    return {offset for offset, between in _gaps_after(text) if _SENTENCE_END.search(between)}


def _word_tags():
    import jieba.posseg

    return jieba.posseg.dt.word_tag_tab


def line_break_cut_costs(text):
    """{content offset: added cost} for cutting ``text`` there (Chinese only).

    Negative values prefer the cut (right after ？！), positive ones avoid it.
    """
    from twobyteasr.subtitle_rules.language_rules import is_japanese
    from twobyteasr.subtitle_rules.segmentation import chinese_word_spans
    from subtitle_core import content_exact

    if is_japanese():
        return {}
    source = content_exact(text)
    count = len(source)
    if count < 2:
        return {}
    costs = {}

    def add(offset, value):
        if 0 < offset < count and value:
            costs[offset] = costs.get(offset, 0.0) + value

    ends = sorted(sentence_end_offsets(text))
    for end in ends:
        add(end, -SENTENCE_END_CUT_BONUS)
        # A cut that is itself a sentence end starts a short sentence of its
        # own (娃娃？｜这什么？), not a stray tail.
        for distance, value in SENTENCE_TAIL_CUT_COSTS.items():
            if end - distance not in ends:
                add(end - distance, value)
        for distance, value in SENTENCE_HEAD_CUT_COSTS.items():
            if end + distance not in ends:
                add(end + distance, value)

    separated = {offset for offset, between in _gaps_after(text) if between}
    tags = _word_tags()
    spans = chinese_word_spans(source)
    for index, ((_start, end, left), (start, right_end, right)) in enumerate(zip(spans, spans[1:])):
        if end != start:
            continue
        left_tag, right_tag = tags.get(left), tags.get(right)
        cost = 0.0 if right in INTERJECTIONS else LEFT_LEANING_WORDS.get(left, 0.0)
        # 一样啊｜感觉 ends a clause; 新角色｜啊 都出场了 may start one.
        if end not in separated and right_end not in separated:
            cost += RIGHT_LEANING_WORDS.get(right, 0.0)
        if end not in separated and left in CLAUSE_END_PARTICLES:
            cost -= CLAUSE_BREAK_BONUS
        if right in CLAUSE_START_WORDS or (
                right in SUBJECT_WORDS and left_tag not in NO_SUBJECT_AFTER_TAGS and left not in LEFT_LEANING_WORDS):
            cost -= CLAUSE_BREAK_BONUS
        if (end not in separated and left in SUBJECT_PRONOUNS and right not in CLAUSE_START_WORDS
                and (right_tag in PREDICATE_TAGS or right in LEFT_LEANING_WORDS)):
            cost += SUBJECT_SPLIT_CUT_COST
        if end not in separated and len(left) == 1 and tags.get(left) == "v" and right in VERB_COMPLEMENTS:
            cost += VERB_COMPLEMENT_CUT_COST
        if (len(right) == 1 and right not in SUBJECT_WORDS and index + 2 < len(spans)
                and spans[index + 2][2] == "的" and right_end not in separated):
            cost += SINGLE_CHARACTER_DE_START_COST
        if (end not in separated and all(char.isdigit() for char in left)
                and (right_tag in NOUN_TAGS or right_tag in ("q", "m"))):
            cost += NUMBER_BEFORE_NOUN_CUT_COST
        if end not in separated and len(left) >= 2 and len(right) >= 2 and {left_tag, right_tag} <= NOUN_TAGS:
            cost += NOUN_COMPOUND_CUT_COST
        elif end not in separated and left_tag in NUMERAL_TAGS and left not in LEFT_LEANING_WORDS:
            cost += NUMERAL_CUT_COST
        add(end, cost)
    return costs
