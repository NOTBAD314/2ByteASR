"""Ordinary-word guards and stutter cleanup for caption *display* text.

2026-10-10 (proofread workspace, user report): the glossary review treated
every reduplication (刚刚, 再再, 这这, 学学) as a missing proper-noun
association, and a near-sound rule turned the ordinary phrase 学聪明了 into
学虫鸣了. Reduplication is mostly ordinary language or a stammer, and a
common word that reads naturally in its sentence is not evidence of a
misheard game term.

Stutter cleanup here only *proposes* deletions for the display text. It never
merges across captions or speakers, never touches numbers, interjections,
emphatic repeats or glossary terms, and it separates a spoken repetition
(word timing / independent transcripts agree) from a duplicate that no
recognizer heard (left for data repair, not hidden by cleanup).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

HANZI = re.compile(r"[一-鿿]")
FILLERS = re.compile(r"[呃嗯额唔]")
SEPARATORS = " 　，,、…"

# Single characters that speakers restart on; an immediate repeat of one is a
# stammer unless the doubled form is itself a common word (个个, 往往…).
CLOSED = set("这那我你他她它咱您谁哪啥再就还也都又才很太更最挺先已正在不没别只光"
             "和跟与但而把被给让从往向比因所如要若虽可是会能得的地了着过该个每各某其此")
# Repeats of these are deliberate (agreement, cheering, calls, counting).
INTERJECTIONS = set("对好嗯啊哈嘿喂哦诶哎呀哇嗷哟唉噢嘛呃额吼耶咦呵嘻喔欸哼啧呜嗨行冲快来走")
NUMERALS = set("一二三四五六七八九十零两百千万亿半第")
# Verb + its own doubled form cannot take a result/direction complement
# (学学聪明了, 叠叠出): the first copy is a restart.
COMMON_VERBS = set("学看听说讲打走跑跳飞拿放给叫想试写读算用开关吃喝玩买卖找等送带帮教问做干搞弄"
                   "选换升叠保交留丢扔推拉追杀砍射抓挡切点按控冲收补刷打堆攒聚摸")
COMPLEMENTS = set("出到完好上下进起过掉成住开回死坏满光穿透清懂")
FUNCTION_UNITS = {
    "这个", "那个", "我的", "你的", "他的", "我们", "你们", "他们", "咱们", "因为", "所以", "但是",
    "然后", "就是", "那就", "如果", "可是", "不是", "还是", "这样", "那样", "这种", "那种", "其实",
    "反正", "我觉得", "我感觉", "就是说", "一个", "这边", "那边", "这里", "那里", "我是", "他是",
    "你是", "我要", "这次", "那次", "我们这", "他这", "我这", "你这", "然后就", "就是这",
}
EMPHATIC_UNITS = {
    "算了", "等一下", "等等", "快点", "来了", "好了", "可以", "没事", "不行", "漂亮", "稳住", "走了",
    "加油", "完了", "对的", "是的", "有了", "没了", "不要", "快快", "冲啊", "上啊", "打他", "过来",
    "赢了", "输了", "好的", "行了", "对对", "牛逼", "厉害", "完蛋",
}
COMMON_REDUPLICATION_FREQ = 50
ORDINARY_WORD_FREQ = 300
NOUN_TAGS = {"n", "nr", "nrfg", "nrt", "ns", "nt", "nz", "eng", "x", "vn", "an"}


@lru_cache(maxsize=1)
def _lexicon():
    import logging
    import jieba
    import jieba.posseg as posseg
    jieba.setLogLevel(logging.ERROR)
    jieba.dt.check_initialized()
    return jieba.dt.FREQ, posseg.dt.word_tag_tab


def warm_lexicon():
    """Load the dictionaries off the UI thread before the first lookup.

    jieba and pypinyin parse multi-megabyte dictionaries once per process;
    pypinyin's C json decode holds the interpreter lock ~0.8 s, which froze
    the proofreading page when it happened during its first match."""
    try:
        _tokens("预热")
        from .text_similarity import phonetic_text
        phonetic_text("预热")
    except Exception:
        pass


_WARMING = []


def warm_text_analysis():
    """Start ``warm_lexicon`` on a daemon thread once per process."""
    if _WARMING:
        return
    import threading
    thread = threading.Thread(target=warm_lexicon, name="text-dictionary-warmup", daemon=True)
    _WARMING.append(thread)
    thread.start()


def word_frequency(word):
    return int(_lexicon()[0].get(word) or 0)


def word_tag(word):
    return str(_lexicon()[1].get(word) or "")


@lru_cache(maxsize=4096)
def _tokens(text):
    import jieba
    _lexicon()
    return tuple(jieba.tokenize(text, HMM=False))


def ordinary_word_in_context(text, start, end):
    """``text[start:end]`` is a common non-noun word, segmented as one word.

    Such a word reading naturally in its sentence (聪明 in 学聪明了, 刚刚)
    is not evidence of a misheard proper noun, however close it sounds."""
    word = str(text)[start:end]
    if not word or not any((a, b) == (start, end) for _, a, b in _tokens(str(text))):
        return False
    return word_frequency(word) >= ORDINARY_WORD_FREQ and word_tag(word) not in NOUN_TAGS


def common_word_in_context(text, start, end):
    """A common noun is also legitimate speech; sound alone is insufficient."""
    word = str(text)[start:end]
    aligned = any((a, b) == (start, end) for _, a, b in _tokens(str(text)))
    return aligned and (ordinary_word_in_context(text, start, end)
                        or word_tag(word) in {"n", "v", "a", "ad", "an", "vn"} and word_frequency(word) >= 100)


def word_span(text, start, end):
    """Smallest word-aligned span covering [start, end) of ``text``."""
    text = str(text)
    start, end = max(0, start), min(len(text), max(start, end))
    for _word, a, b in _tokens(text):
        if a < max(end, start + 1) and start < b:
            start, end = min(start, a), max(end, b)
    return start, end


def word_aligned(text, start, end):
    """Chinese span boundaries fall between words (题他 inside 话题他 does not)."""
    text = str(text)
    if not HANZI.search(text[start:end]):
        return True
    cuts = {0, len(text)}
    for _word, a, b in _tokens(text):
        cuts.update((a, b))
    return start in cuts and end in cuts


FUNCTION_TAGS = {"r", "d", "c", "p", "u", "ul", "uj", "uz", "ug", "uv", "y", "e", "o", "m", "q", "f", "zg"}
COMMON_VERBS_FUNCTION = {"是", "有", "在", "要", "会", "能", "说", "看", "去", "来", "给", "让"}


def function_words_only(text, start, end):
    """The span is made only of particles, pronouns, adverbs and the like
    (哦 又是): such a span is ordinary speech, not a misheard name."""
    text = str(text)
    span = text[start:end]
    if len(span) >= 2 and len(set(span)) == 1 and word_frequency(span) < COMMON_REDUPLICATION_FREQ:
        return False  # 又又 is no ordinary word: it may be a doubled name (优优)
    words = [word for word, a, b in _tokens(text) if start <= a and b <= end and word.strip()]
    if not words or "".join(words).replace(" ", "") != text[start:end].replace(" ", ""):
        return False
    return all(word in COMMON_VERBS_FUNCTION or word_tag(word) in FUNCTION_TAGS
               or (len(word) == 1 and (word in CLOSED or word in INTERJECTIONS)) for word in words)


def plausible_name_span(text, start, end):
    """A span worth proposing a glossary spelling for (any source)."""
    return (word_aligned(text, start, end) and not ordinary_word_in_context(text, start, end)
            and not function_words_only(text, start, end))


def ordinary_reduplication(text, start, end):
    """A doubled-character span that is ordinary language, not a name signal."""
    text = str(text)
    span = text[start:end]
    if len(span) < 2 or len(set(span)) != 1 or not HANZI.fullmatch(span[0]):
        return False
    char = span[0]
    if word_frequency(char * 2) >= COMMON_REDUPLICATION_FREQ:
        return True
    if char in CLOSED or char in INTERJECTIONS or char in NUMERALS:
        return True
    following = text[end:end + 1]
    return char in COMMON_VERBS and bool(following) and following in COMPLEMENTS


def reduplication_names_nothing(text, start, end):
    """A doubled-character span that cannot be a doubled nickname (球球, 莎莎).

    Besides ordinary doubled words: three or more copies (帅帅帅), a span
    inside or across a longer word (冥冥之中, 小心翼翼, 一下下, 神神秘,
    应应该, 养分分给) and a doubled verb or particle (去去上海, 拜拜, 海之之)
    are speech. 2026-10-28: these were most of the user's 术语召回缺口 items.
    """
    text = str(text)
    span = text[start:end]
    if ordinary_reduplication(text, start, end) or len(span) >= 3:
        return True
    if any(a < end and start < b and b - a > 1 and (a, b) != (start, end)
           for _word, a, b in _tokens(text)):
        return True
    tag = word_tag(span[:1])
    return tag in FUNCTION_TAGS or tag.startswith("v")


@dataclass(frozen=True)
class RepeatFinding:
    delete_span: tuple[int, int]
    run_span: tuple[int, int]
    unit: str
    count: int
    kind: str          # 'stutter' | 'ambiguous' | 'merge_suspect'
    reason: str
    evidence: str
    default_selected: bool


def _runs(text):
    """Immediate repeats of a 1-4 character Hanzi unit, longest unit first."""
    taken = [False] * len(text)
    found = []
    for size in (4, 3, 2, 1):
        index = 0
        while index + size <= len(text):
            unit = text[index:index + size]
            if any(taken[index:index + size]) or not all(HANZI.fullmatch(c) for c in unit):
                index += 1
                continue
            starts, cursor = [index], index + size
            while True:
                probe = cursor
                while probe < len(text) and text[probe] in SEPARATORS and probe - cursor < 1:
                    probe += 1
                if text[probe:probe + size] == unit and not any(taken[probe:probe + size]):
                    starts.append(probe)
                    cursor = probe + size
                else:
                    break
            if len(starts) >= 2:
                for position in range(index, cursor):
                    taken[position] = True
                found.append((unit, starts, (index, cursor)))
                index = cursor
            else:
                index += 1
    return sorted(found, key=lambda row: row[2])


def _unit_kind(text, unit, count, end):
    """('stutter'|'ambiguous'|'keep', reason) from wording alone."""
    following = text[end:end + 1]
    if any(c in NUMERALS for c in unit):
        return "keep", "数字或报数"
    if len(unit) == 1:
        if unit in INTERJECTIONS:
            return "keep", "语气或口号的有意重复"
        if unit in CLOSED:
            if count == 2 and word_frequency(unit * 2) >= ORDINARY_WORD_FREQ:
                return "keep", "常用叠词"
            return "stutter", "虚词/代词起句重来"
        if unit in COMMON_VERBS and count == 2:
            after = text[end:end + 3]
            if following in COMPLEMENTS:
                return "stutter", "动词重叠后不能再接补语（如“叠叠出”）"
            for word, a, b in _tokens(text):
                if a == end and word_tag(word) == "a" and text[b:b + 1] == "了":
                    return "stutter", "动词重叠后不能再接“形容词+了”（如“学学聪明了”）"
            if word_frequency(unit * 2) >= COMMON_REDUPLICATION_FREQ:
                return "keep", "常用动词重叠"
            return "ambiguous", "动词重叠，可能是口吃也可能是“试一试”的意思"
        if word_frequency(unit * 2) >= COMMON_REDUPLICATION_FREQ:
            return "keep", "常用叠词"
        if count >= 3:
            return "keep", "多次重复，可能是有意强调"
        return "keep", "名字或叠字称呼"
    if unit in EMPHATIC_UNITS:
        return "keep", "口语中有意的重复"
    tags = [word_tag(word) for word, _, _ in _tokens(unit)]
    if unit in FUNCTION_UNITS or (tags and all(tag[:1] in {"r", "d", "c", "p", "u", "y", "q", "f"} for tag in tags)):
        return "stutter", "起句重来"
    return "ambiguous", "实词重复，可能是强调"


def find_repeats(text, *, char_times=None, protected_terms=(), spoken_texts=()):
    """Proposals for one caption's text.

    ``char_times``: per character (start_ms, end_ms) or None, from verified
    word timing. ``spoken_texts``: independent recognizer transcripts covering
    this caption. ``protected_terms``: glossary spellings never shortened."""
    text = str(text or "")
    protected = []
    for term in protected_terms:
        term = str(term or "")
        if len(term) >= 2:
            protected.extend((m.start(), m.end()) for m in re.finditer(re.escape(term), text))
    heard = [FILLERS.sub("", re.sub(r"[^一-鿿A-Za-z0-9]", "", str(t))) for t in spoken_texts if t]
    findings = []
    for unit, starts, (a, b) in _runs(text):
        count = len(starts)
        if any(pa < b and a < pb for pa, pb in protected) or unit in set(protected_terms):
            continue
        kind, reason = _unit_kind(text, unit, count, b)
        restart = re.compile(re.escape(unit) + "[呃嗯额唔啊，, ]+" + re.escape(unit))
        if (kind in {"keep", "ambiguous"} and reason not in {"数字或报数", "语气或口号的有意重复", "常用叠词", "常用动词重叠"}
                and any(restart.search(str(t)) for t in spoken_texts if t)):
            # The recognizers heard a hesitation between the copies (火呃火狗).
            kind, reason = "stutter", "识别原文里两次之间有“呃”等停顿，是起句重来"
        if kind == "keep":
            continue
        evidence, selected = [], kind == "stutter"
        if char_times:
            spans = []
            for start in starts:
                times = [char_times[i] for i in range(start, start + len(unit)) if i < len(char_times) and char_times[i]]
                spans.append((min(t[0] for t in times), max(t[1] for t in times)) if len(times) == len(unit) else None)
            if all(spans):
                if any(nxt[0] < cur[1] - 30 for cur, nxt in zip(spans, spans[1:])):
                    kind, selected = "merge_suspect", False
                    reason = "两份相同文字的时间重叠，像是分块/融合重复而不是说了两遍"
                    evidence.append("字级时间重叠")
                else:
                    evidence.append("字级时间显示确实说了 %d 遍" % count)
        run_text = unit * count
        if heard:
            hits = sum(run_text in value for value in heard)
            if hits:
                evidence.append("%d/%d 路识别都听到重复" % (hits, len(heard)))
            elif kind != "merge_suspect":
                kind, selected = "merge_suspect", False
                reason = "各路识别原文都没有这段重复，可能是融合时多出的文字"
                evidence.append("识别原文无此重复")
        if not char_times:
            evidence.append("无逐字时间")
        findings.append(RepeatFinding((a, starts[-1]), (a, b), unit, count, kind, reason,
                                      "；".join(evidence), selected))
    return findings


def caption_char_times(project, cue):
    """Per-character (start_ms, end_ms) from verified word timing, else None."""
    from ..recognition.cue_word_alignment import cue_words
    words, _reason = cue_words(project, cue)
    if not words:
        return None
    times = [None] * len(cue.text)
    for word in words:
        # A multi-character token's interval is an envelope for each of its
        # characters; no finer acoustic anchor is invented.
        for index in range(word.char_start, word.char_end):
            if 0 <= index < len(times):
                times[index] = (int(word.start_ms), int(word.end_ms))
    return times


def caption_spoken_texts(project, cue):
    """Independent recognizer transcripts of the caption's evidence segments."""
    texts = []
    for ref in getattr(cue, "evidence_refs", ()) or ():
        row = (getattr(project, "asr_evidence", {}) or {}).get(ref) or {}
        for key in ("moss_text", "firered_text", "qwen_asr_text"):
            value = str(row.get(key) or "")
            if value:
                texts.append(value)
    return texts


def stutter_occurrences(project, cue, protected_terms=()):
    """Deletion proposals (``TextOccurrence``) for one caption."""
    from ..studio.studio_text_tools import TextOccurrence
    output = []
    for finding in find_repeats(cue.text, char_times=caption_char_times(project, cue),
                                protected_terms=protected_terms,
                                spoken_texts=caption_spoken_texts(project, cue)):
        a, b = finding.delete_span
        output.append(TextOccurrence(cue.id, cue.start_ms, cue.text[a:b], "", (a, b),
                                     reason=finding.reason, confidence=.8 if finding.default_selected else .4,
                                     default_selected=finding.default_selected,
                                     source="stutter" if finding.kind != "merge_suspect" else "merge_suspect",
                                     evidence=finding.evidence,
                                     missing_evidence="" if finding.kind == "stutter" else "需要你确认"))
    return output


# --------------------------------------------------------------------------
# One spelling per spoken word across the transcript (2026-10-10, user):
# once 原石 appears, a later 源石 for the same sound should follow it, so a
# later batch replace finds every occurrence. Not a claim of correctness.
# --------------------------------------------------------------------------

def _sound_key(word):
    from .text_similarity import phonetic_text
    keys = []
    for char in word:
        key = phonetic_text(char) or char
        key = re.sub(r"^(zh|ch|sh)", lambda match: match.group(1)[0], key)
        keys.append(re.sub(r"(?<=[aeiouv])ng$", "n", key))
    return tuple(keys)


@lru_cache(maxsize=8192)
def word_tokens(text):
    import jieba
    _lexicon()
    return tuple((word, a, b) for word, a, b in jieba.tokenize(text, HMM=True)
                 if 2 <= len(word) <= 4 and HANZI.fullmatch(word[0]) and all(HANZI.fullmatch(c) for c in word))


def consistency_occurrences(entries, *, preferred=(), common_freq=ORDINARY_WORD_FREQ, cancel_check=None):
    """Proposals that make later spellings of one sound follow one spelling.

    ``entries``: (cue_id, start_ms, text) in time order. ``preferred``:
    spellings that win when present (library terms, the user's own edits);
    otherwise the first spelling heard wins. Groups whose spellings are all
    ordinary words with their own meanings (攻势/公式, 那个/哪个) are left
    alone. Returns {cue_id: [TextOccurrence]}."""
    from ..studio.studio_text_tools import TextOccurrence
    preferred = set(preferred)
    first_seen, occurrences, groups = {}, [], {}
    texts = {}
    for order, (cue_id, start_ms, text) in enumerate(entries):
        if cancel_check is not None and cancel_check():
            return {}
        texts[cue_id] = str(text)
        for word, a, b in word_tokens(str(text)):
            first_seen.setdefault(word, order)
            occurrences.append((cue_id, start_ms, word, a, b))
            groups.setdefault(_sound_key(word), set()).add(word)
    canonical_of = {}
    for spellings in groups.values():
        if len(spellings) < 2:
            continue
        common = [word for word in spellings if word_frequency(word) >= common_freq]
        if len(common) >= 2:
            continue  # distinct ordinary words, not variants of one name
        favourites = [word for word in spellings if word in preferred]
        if len(favourites) > 1:
            continue  # two library spellings share this sound: a real choice
        canonical = favourites[0] if favourites else min(spellings, key=lambda word: first_seen[word])
        confident = bool(favourites) or all(word_frequency(word) < common_freq
                                            for word in spellings if word != canonical)
        for word in spellings:
            if word != canonical:
                canonical_of[word] = (canonical, confident, bool(favourites))
    found = {}
    for cue_id, start_ms, word, a, b in occurrences:
        if word not in canonical_of:
            continue
        canonical, confident, from_preferred = canonical_of[word]
        from ..glossary.proposal_safety import review_change_reason
        if review_change_reason(texts[cue_id], (a, b), canonical, names=tuple(preferred)):
            continue
        from ..i18n import tr
        reason = (tr("全片统一写法：采用「{word}」（词库或你的修改）", word=canonical) if from_preferred
                  else tr("全片统一写法：采用最先出现的「{word}」", word=canonical))
        found.setdefault(cue_id, []).append(TextOccurrence(
            cue_id, start_ms, word, canonical, (a, b), reason=reason, confidence=.6,
            default_selected=confident, source="consistency"))
    return found
