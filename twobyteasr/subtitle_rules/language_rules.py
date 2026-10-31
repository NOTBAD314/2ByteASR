"""Task language: requested value, detection evidence and per-language capabilities.

Language is a property of a recognition task (and of the project it creates),
never of a speaker: switching language does not touch speaker identities.

Detection counts scripts in the primary transcript. Kanji alone never decide
Japanese vs Chinese (Japanese text is full of kanji); kana do. A transcript is
Japanese when kana make up a clear share of its CJK letters.

Model capabilities are recorded separately per role, because a model that can
transcribe a language cannot necessarily align or diarize it.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import re
import threading
import unicodedata

# Content characters shared by every text comparison: CJK ideographs, kana
# (incl. ー and 々, not the ・ separator), Hangul syllables and jamo, accented
# Latin and Cyrillic letters (2026-10-19) and ASCII letters/digits.
CONTENT_CHAR_CLASS = (r"\u3400-\u9fff\u3005\u3041-\u3096\u309d-\u309f\u30a1-\u30fa\u30fc-\u30ff"
                      r"\u31f0-\u31ff\uff66-\uff9f\uac00-\ud7a3\u3131-\u318e"
                      r"\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u024f\u0400-\u04ffA-Za-z0-9")

AUTO, ZH, JA, EN, KO = "auto", "zh", "ja", "en", "ko"
# 2026-10-19: the six other languages Qwen3-ForcedAligner times.
ES, DE, FR, PT, IT, RU = "es", "de", "fr", "pt", "it", "ru"
EUROPEAN = (ES, DE, FR, PT, IT, RU)
SUPPORTED_REQUESTS = (AUTO, ZH, JA, EN, KO, *EUROPEAN,'pt-BR','pt-PT')
TASK_LANGUAGES = (ZH, JA, EN, KO, *EUROPEAN)
QWEN_LANGUAGE_NAMES = {ZH: "Chinese", JA: "Japanese", EN: "English", KO: "Korean", ES: "Spanish", DE: "German",
                       FR: "French", PT: "Portuguese", IT: "Italian", RU: "Russian"}
_ALIASES = {"": AUTO, "auto": AUTO, "zh": ZH, "zh-cn": ZH, "zh-hans": ZH, "zh-hant": ZH, "chinese": ZH, "cn": ZH,
            "ja": JA, "ja-jp": JA, "jp": JA, "japanese": JA,
            "en": EN, "en-us": EN, "en-gb": EN, "eng": EN, "english": EN,
            "ko": KO, "ko-kr": KO, "kr": KO, "kor": KO, "korean": KO,
            "es": ES, "es-es": ES, "es-mx": ES, "es-419": ES, "spa": ES, "spanish": ES,
            "de": DE, "de-de": DE, "deu": DE, "ger": DE, "german": DE,
            "fr": FR, "fr-fr": FR, "fra": FR, "fre": FR, "french": FR,
            "pt": PT, "pt-br": PT, "pt-pt": PT, "por": PT, "portuguese": PT,
            "it": IT, "it-it": IT, "ita": IT, "italian": IT,
            "ru": RU, "ru-ru": RU, "rus": RU, "russian": RU}

# Kana share of (kana + kanji) above which a transcript is Japanese.
KANA_SHARE_JA = 0.12
MIN_KANA_JA = 4
# 2026-10-14: a transcript is English when Latin letters clearly dominate: at
# least this many letters, and CJK letters under this share of all letters
# (a Chinese stream with English words stays Chinese).
MIN_LATIN_EN = 20
CJK_SHARE_EN = 0.10
# 2026-10-19: Korean when Hangul syllables are a clear majority of the CJK
# letters (Chinese and Japanese transcripts have none; Korean has few hanja).
MIN_HANGUL_KO = 6
HANGUL_SHARE_KO = 0.5
# Cyrillic decides Russian the same way; a Latin transcript is then told apart
# by its common short words and accented letters (English when unsure).
MIN_CYRILLIC_RU = 12
CYRILLIC_SHARE_RU = 0.5
_LATIN_MARKERS = {
    EN: ("the and you is to of it that in what this we my have was are just so like don't it's i'm gonna "
         "yeah okay right for with on be not but they he she", ""),
    ES: ("que de el los las y en es lo un una por para con se pero muy está qué eso esto vamos aquí yo tú "
         "pues bueno hay al del porque hoy también como más ya mi me te le la no", "ñ¿¡áíóú"),
    FR: ("le les des et est je tu il pas une ce c'est on du au mais ça oui très vous nous avec suis "
         "alors voilà qui pour dans sur faire aujourd'hui la à", "çèêâîôûëïœ"),
    DE: ("der die das und ist nicht ich du ein eine zu mit auf es wir ja aber auch was wie den dem sie "
         "hier mal jetzt im von für sind noch schon dann heute", "äöüß"),
    PT: ("que não de é o os as eu você um uma para com isso está mas muito aqui vamos tá né ele ela do da "
         "no na gente em hoje também porque já pessoal", "ãõçâêô"),
    IT: ("che non di è il lo gli e un una per sono ho questo mi ma molto qui andiamo cosa del della ci "
         "anche allora oggi perché già ragazzi la", "àèìòù"),
}

# Which roles each local model fills for each language. "transcribe" is
# speech-to-text; "align" is forced alignment of a given text; "speakers" is
# diarization; "language_id" is spoken-language identification.
MODEL_LANGUAGE_ROLES = {
    "moss": {"transcribe": {ZH, JA, EN, KO, *EUROPEAN}, "speakers": {ZH, JA, EN, KO, *EUROPEAN}, "align": set(),
             "language_id": set()},
    "qwen3_asr": {"transcribe": {ZH, JA, EN, KO, *EUROPEAN}, "language_id": {ZH, JA, EN, KO, *EUROPEAN},
                  "align": set(), "speakers": set()},
    "qwen_aligner": {"align": {ZH, JA, EN, KO, *EUROPEAN}, "transcribe": set(), "speakers": set(),
                     "language_id": set()},
    "mlx_qwen3_asr": {"transcribe": {ZH, JA, EN, KO, *EUROPEAN}, "language_id": {ZH, JA, EN, KO, *EUROPEAN},
                      "align": set(), "speakers": set()},
    "mlx_qwen3_asr_1_7b": {"transcribe": {ZH, JA, EN, KO, *EUROPEAN}, "language_id": {ZH, JA, EN, KO, *EUROPEAN},
                           "align": set(), "speakers": set()},
    "mlx_qwen_aligner": {"align": {ZH, JA, EN, KO, *EUROPEAN}, "transcribe": set(), "speakers": set(),
                         "language_id": set()},
    # 2026-10-19: experimental Montreal Forced Aligner; only these two model sets are installed.
    "mfa_aligner": {"align": {ZH, JA}, "transcribe": set(), "speakers": set(), "language_id": set()},
    "firered_aed": {"transcribe": {ZH}, "align": {ZH}, "speakers": set(), "language_id": set()},
    "firered_llm": {"transcribe": {ZH}, "align": set(), "speakers": set(), "language_id": set()},
    "paraformer": {"transcribe": {ZH}, "align": {ZH}, "speakers": set(), "language_id": set()},
    "firered_vad": {"vad": {ZH, JA, EN, KO, *EUROPEAN}},
}


def supports(model: str, role: str, language: str) -> bool:
    return normalize_language(language) in MODEL_LANGUAGE_ROLES.get(model, {}).get(role, set())


def normalize_language(value) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    known=_ALIASES.get(text)
    if known is not None:return known
    from .segmentation_profiles import language_tag
    tag=language_tag(text)
    return tag.split('-')[0] if tag!='und' else AUTO


def qwen_language_name(language: str):
    """Language argument for qwen-asr: a name, or None to let it identify."""
    return QWEN_LANGUAGE_NAMES.get(normalize_language(language))


def language_from_qwen_name(name) -> str:
    return {name.lower(): code for code, name in QWEN_LANGUAGE_NAMES.items()}.get(str(name or "").strip().lower(), "")


def _is_kana(code: int) -> bool:
    return 0x3041 <= code <= 0x309F or 0x30A0 <= code <= 0x30FF or 0x31F0 <= code <= 0x31FF or 0xFF66 <= code <= 0xFF9D


def script_counts(texts) -> dict:
    counts = {"kana": 0, "han": 0, "latin": 0, "hangul": 0, "cyrillic": 0}
    for text in texts if isinstance(texts, (list, tuple)) else [texts]:
        for char in str(text or ""):
            code = ord(char)
            if char in "・ー" or not unicodedata.category(char).startswith("L"):
                continue
            if _is_kana(code):
                counts["kana"] += 1
            elif 0x3400 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF or 0x20000 <= code <= 0x2FA1F:
                counts["han"] += 1
            elif 0xAC00 <= code <= 0xD7AF:
                counts["hangul"] += 1
            elif char.isascii() or 0xC0 <= code <= 0x24F:
                counts["latin"] += 1
            elif 0x400 <= code <= 0x4FF:
                counts["cyrillic"] += 1
    return counts


def latin_language(texts) -> tuple[str, dict]:
    """English, Spanish, French, German, Portuguese or Italian for a Latin transcript (2026-10-19).

    Counts each language's common short words and accented letters; English
    wins ties and anything undecided (the behaviour before these languages).
    """
    text = " ".join(texts if isinstance(texts, (list, tuple)) else [texts]).lower()
    tokens = re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)?", text)
    scores = {}
    for code, (markers, accents) in _LATIN_MARKERS.items():
        words = set(markers.split())
        scores[code] = sum(1 for token in tokens if token in words) + 2 * sum(text.count(ch) for ch in accents)
    best = max(scores, key=lambda code: (scores[code], code == EN))
    if best != EN and scores[best] < max(3, 1.3 * scores[EN]):
        best = EN
    return best, scores


def detect_language(texts) -> tuple[str, dict]:
    counts = script_counts(texts)
    cjk = counts["kana"] + counts["han"]
    share = counts["kana"] / cjk if cjk else 0.0
    letters = cjk + counts["latin"]
    cjk_share = cjk / letters if letters else 0.0
    hangul_share = counts["hangul"] / (cjk + counts["hangul"]) if cjk + counts["hangul"] else 0.0
    evidence = dict(counts, kana_share=round(share, 4), cjk_share=round(cjk_share, 4),
                    hangul_share=round(hangul_share, 4),
                    rule=f"hangul >= {MIN_HANGUL_KO} and hangul/(hangul+kana+han) >= {HANGUL_SHARE_KO} = ko; "
                         f"kana/(kana+han) >= {KANA_SHARE_JA} and kana >= {MIN_KANA_JA}; "
                         f"latin >= {MIN_LATIN_EN} and cjk/(cjk+latin) < {CJK_SHARE_EN} = en")
    if counts["hangul"] >= MIN_HANGUL_KO and hangul_share >= HANGUL_SHARE_KO:
        return KO, evidence
    if counts["kana"] >= MIN_KANA_JA and share >= KANA_SHARE_JA:
        return JA, evidence
    alphabet = counts["cyrillic"] + counts["latin"] + cjk + counts["hangul"]
    if counts["cyrillic"] >= MIN_CYRILLIC_RU and counts["cyrillic"] >= CYRILLIC_SHARE_RU * alphabet:
        return RU, dict(evidence, cyrillic_share=round(counts["cyrillic"] / alphabet, 4))
    if counts["latin"] >= MIN_LATIN_EN and cjk_share < CJK_SHARE_EN:
        language, scores = latin_language(texts)
        return language, dict(evidence, latin_scores=scores)
    if counts["han"]:
        return ZH, evidence
    return "", evidence


def resolve_task_language(requested, texts, *, asr_detected=None) -> tuple[str, dict]:
    """The language one task runs with, plus how it was decided.

    A manual choice wins. ``auto`` uses the transcript's scripts, then the
    recognizer's own language identification. Undecidable non-empty foreign
    text uses the conservative Unicode policy; empty legacy input stays Chinese.
    """
    from .segmentation_profiles import language_tag,PROFILES
    texts=tuple(texts)
    raw_requested=requested
    requested = normalize_language(requested)
    detected, evidence = detect_language(texts)
    evidence = dict(evidence, requested=requested, asr_detected=asr_detected or "",requested_locale=language_tag(raw_requested))
    if requested in PROFILES and requested!='und':
        evidence["decided_by"] = "manual"
        evidence['locale']=language_tag(raw_requested)
        if detected and detected != requested:
            evidence["disagrees_with_transcript"] = detected
        return requested, evidence
    from_asr = language_from_qwen_name(asr_detected) or normalize_language(asr_detected)
    # Script evidence is strong for kana/Hangul/Han/Cyrillic. Latin names
    # alone are not a reason to override a recognizer's declared language.
    if from_asr in PROFILES and from_asr!='und' and detected not in (ZH,JA,KO,RU):
        evidence.update(decided_by='asr_language_id',locale=language_tag(asr_detected))
        return from_asr,evidence
    if detected:
        evidence["decided_by"] = "transcript_scripts"
        evidence['locale']=detected
        return detected, evidence
    if from_asr in PROFILES and from_asr!='und':
        evidence["decided_by"] = "asr_language_id"
        evidence['locale']=language_tag(asr_detected)
        return from_asr, evidence
    joined=''.join(str(t) for t in texts)
    for code,low,high in (('ar',0x600,0x6ff),('hi',0x900,0x97f),('th',0xe00,0xe7f)):
        letters=sum(ch.isalpha() for ch in joined)
        count=sum(low<=ord(ch)<=high and ch.isalpha() for ch in joined)
        if count>=6 and count>=letters*.5:
            evidence.update(decided_by='script_generic_policy',locale=code)
            return code,evidence
    if any(ch.isalpha() for ch in joined):
        evidence.update(decided_by='unknown_conservative_policy',locale='und')
        return 'und',evidence
    evidence["decided_by"] = "default_chinese"
    return ZH, evidence


_SCOPE = threading.local()


@contextmanager
def language_scope(language):
    """Run text rules for one project's language on this thread (Studio work)."""
    previous = getattr(_SCOPE, "language", None)
    previous_tag = getattr(_SCOPE,'language_tag',None)
    from .segmentation_profiles import language_tag
    _SCOPE.language_tag = language_tag(language) if language else None
    _SCOPE.language = normalize_language(language) if language else None
    try:
        yield
    finally:
        _SCOPE.language = previous
        _SCOPE.language_tag = previous_tag


def active_task_language() -> str:
    """Language for text rules: a scoped project language, else the running task's."""
    tag=getattr(_SCOPE,'language_tag',None)
    if tag is not None:return tag.split('-')[0]
    scoped = getattr(_SCOPE, "language", None)
    if scoped in TASK_LANGUAGES:
        return scoped
    try:
        from ..recognition.run_context import get_runtime_context
        return str(getattr(get_runtime_context(), "task_language", "") or "")
    except Exception:
        return ""


def project_language(project) -> str:
    """The spoken language recorded for a project ('' for older projects = Chinese rules)."""
    metadata = getattr(project, "generation_metadata", None) or {}
    value = (metadata.get("language") or {}) if isinstance(metadata, dict) else {}
    raw = value.get("code") if isinstance(value, dict) else value
    code = normalize_language(raw)
    from .segmentation_profiles import PROFILES
    if code == AUTO and raw:
        return 'und'
    return code if code in PROFILES else ""


def is_japanese(language=None) -> bool:
    return (active_task_language() if language is None else normalize_language(language)) == JA


# 2026-10-21 (user: every language except Chinese should keep whole sentences): a
# finished Japanese subtitle holds two lines (Netflix Japanese guide: 13 full-width
# characters a line) and up to 7 seconds; Chinese stays one line of 16 / 5 seconds.
JAPANESE_CUE_MAX_CHARS = 26
JAPANESE_CUE_MAX_SECONDS = 7.0


def finished_cue_limits(chinese_chars, chinese_seconds):
    """(characters, seconds) one finished subtitle may hold in the active task language.

    Callers pass the Chinese limits they used before, so Chinese is unchanged.
    """
    from .segmentation_profiles import current_profile
    profile=current_profile()
    return profile.hard_max, profile.max_seconds


def is_english(language=None) -> bool:
    return (active_task_language() if language is None else normalize_language(language)) == EN


def is_korean(language=None) -> bool:
    return (active_task_language() if language is None else normalize_language(language)) == KO


def is_spaced(language=None) -> bool:
    """English, Korean and the European languages: words separated by spaces, never cut inside a word."""
    from .segmentation_profiles import profile_for
    value=active_task_language() if language is None else language
    return bool(value) and profile_for(value).strategy in ('space','eojeol')


def is_european(language=None) -> bool:
    """Spanish, German, French, Portuguese, Italian or Russian (2026-10-19)."""
    return (active_task_language() if language is None else normalize_language(language)) in EUROPEAN


_JA_PAUSE_PUNCTUATION = re.compile(r"[、。，．,]+")


def japanese_display_source(text: str) -> str:
    """Keep the pause of a Japanese 、/。 as a space before Chinese-style cleanup removes them."""
    return _JA_PAUSE_PUNCTUATION.sub(" ", str(text or ""))


@dataclass(frozen=True)
class SegmentationRules:
    """Per-language limits for forming display cues (lengths in display units)."""
    language: str
    preferred_max: int
    soft_max: int
    hard_max: int
    fallback_comfort_max: int
    raw_segment_max: int
    sentence_end: str
    clause_marks: str


CHINESE_SEGMENTATION = SegmentationRules(ZH, 10, 16, 16, 12, 24, "。！？!?", "，、；：,;:")
# Japanese counts kana: a comfortable line is longer in characters than Chinese.
JAPANESE_SEGMENTATION = SegmentationRules(JA, 16, 22, 24, 18, 30, "。！？!?", "、，,")


def segmentation_rules(language=None) -> SegmentationRules:
    from .segmentation_profiles import profile_for, task_language_tag
    p=profile_for(language if language is not None else task_language_tag())
    return SegmentationRules(p.code,int(p.preferred),int(p.soft_max),int(p.hard_max),
        12 if p.code=='zh' else int(p.preferred),24 if p.code=='zh' else 30 if p.code=='ja' else int(p.hard_max),
        '。！？!?' if p.strategy=='cjk' else '.!?…', '、，,;:' if p.strategy=='cjk' else ',;:—–')


_ADNOMINALS = ("この", "その", "あの", "どの", "こんな", "そんな", "あんな", "どんな")


def _script_class(char: str) -> str:
    code = ord(char)
    if 0x3041 <= code <= 0x309F:
        return "hira"
    if 0x30A0 <= code <= 0x30FF or 0x31F0 <= code <= 0x31FF or 0xFF66 <= code <= 0xFF9F:
        return "kata"
    if 0x3400 <= code <= 0x9FFF or char == "々" or 0xF900 <= code <= 0xFAFF:
        return "kanji"
    if char.isascii() and char.isalnum():
        return "latin"
    return "other"


def japanese_phrase_spans(text: str) -> list[tuple[int, int, str]]:
    """Bunsetsu spans of ``text`` for cue-boundary protection.

    Inside a recognition task the spans come from real morphology of the
    task's segment texts (``japanese_morphology``); elsewhere (Studio edits)
    the script-class heuristic below is used.
    """
    from twobyteasr.subtitle_rules.japanese_morphology import document_phrase_spans
    measured = document_phrase_spans(text)
    if measured is not None:
        return split_repeated_chants([span for span in measured if span[1] > span[0]])
    return split_repeated_chants(heuristic_japanese_phrase_spans(text))


def repeat_unit_offsets(text: str) -> set[int]:
    """Offsets between whole units of a chant said 3+ times (メガネメガネメガネ…).

    A run of one character (ーーーー, ははは) has no units to cut between.
    """
    text = str(text or "")
    count = len(text)
    offsets = set()
    for size in range(2, 7):
        start = 0
        while start + 3 * size <= count:
            end = start + size
            while end < count and text[end] == text[end - size]:
                end += 1
            if end - start >= 3 * size and len(set(text[start:start + size])) > 1:
                offsets.update(range(start + size, end + 1, size))
                start = end
            else:
                start += 1
    return {offset for offset in offsets if 0 < offset < count}


def split_repeated_chants(spans):
    """A phrase that is one unit said 3+ times is that many phrases.

    2026-10-18 (日常 19): morphology read 「メガネ」×11 as one phrase, so every
    offset inside it was "inside a word": line breaking found no cut, a hard
    break measured inside it was moved and then reported missing (the AI
    batch fell back), and the last-resort split cut メ|ガネ. Between whole
    units is where a person cuts.
    """
    result = []
    for start, end, word in spans:
        cuts = sorted(repeat_unit_offsets(word))
        if not cuts:
            result.append((start, end, word))
            continue
        edges = [0, *cuts, len(word)]
        result.extend((start + a, start + b, word[a:b]) for a, b in zip(edges, edges[1:]) if b > a)
    return result


def japanese_strong_breaks(text: str) -> set[int]:
    """Content offsets where a Japanese line should preferably break."""
    from twobyteasr.subtitle_rules.japanese_morphology import INTERJECTION_RE, content_positions, document_strong_breaks
    measured = document_strong_breaks(text)
    if measured is not None:
        return measured
    positions = content_positions(text)
    rank = {position: index for index, position in enumerate(positions)}
    strong = set()
    for match in INTERJECTION_RE.finditer(text):
        for edge in match.span():
            if edge in rank and 0 < rank[edge] < len(positions):
                strong.add(rank[edge])
    return strong


def heuristic_japanese_phrase_spans(text: str) -> list[tuple[int, int, str]]:
    """Approximate bunsetsu spans of ``text`` for cue-boundary protection.

    A content run (kanji, katakana, latin/digits) starts a phrase; the
    hiragana that follows (okurigana, particles, auxiliaries) belongs to it.
    A hiragana run that starts the text or follows another hiragana phrase is
    its own phrase, except a trailing adnominal (この/その/...) which belongs
    to the next phrase. Cuts are allowed only between phrases. This is a
    conservative protection heuristic, not a morphological analysis.
    """
    text = str(text or "")
    runs = []
    for index, char in enumerate(text):
        kind = _script_class(char)
        if kind == "kata" and char == "ー" and runs and runs[-1][2] in ("hira", "kanji"):
            kind = runs[-1][2]
        if runs and runs[-1][2] == kind and kind != "other":
            runs[-1][1] = index + 1
        else:
            runs.append([index, index + 1, kind])
    phrases = []
    for start, end, kind in runs:
        if kind == "kanji" and phrases and phrases[-1][2] == "latin" and phrases[-1][1] == start                 and text[phrases[-1][0]:phrases[-1][1]].isdigit():
            phrases[-1][1] = end      # 2024年, 6人: a number keeps its counter
            phrases[-1][2] = "kanji"
            continue
        if kind == "other":
            phrases.append([start, end, "other"])
            continue
        if kind == "hira" and phrases and phrases[-1][2] in ("kanji", "kata", "latin", "phrase") \
                and phrases[-1][1] == start:
            phrases[-1][1] = end
            phrases[-1][2] = "phrase"
            continue
        phrases.append([start, end, kind])
    # An adnominal at the end of a phrase introduces the next content word.
    for index in range(len(phrases) - 1):
        start, end, kind = phrases[index]
        following = phrases[index + 1]
        if following[2] == "other" or following[0] != end:
            continue
        # Honourific prefixes introduce the following kanji word (お目,
        # お金, ご飯); a script-run heuristic must not attach お to the
        # preceding clause and leave it stranded at a cue edge.
        if following[2] in ('kanji', 'phrase') and text[start:end].endswith(('お', 'ご')):
            phrases[index][1] = end - 1
            following[0] = end - 1
            continue
        for word in _ADNOMINALS:
            if text[start:end].endswith(word) and end - len(word) > start:
                phrases[index][1] = end - len(word)
                following[0] = end - len(word)
                break
            if text[start:end] == word:
                following[0] = start
                phrases[index][1] = start
                break
    # A lengthened interjection after a finished clause (のにね|いやー|こんな)
    # is its own phrase even inside one hiragana run.
    from twobyteasr.subtitle_rules.japanese_morphology import FINAL_CHARS, INTERJECTION_RE
    cuts = set()
    for match in INTERJECTION_RE.finditer(text):
        start, end = match.span()
        if start == 0 or text[start - 1] in FINAL_CHARS or _script_class(text[start - 1]) == "other":
            cuts.update(edge for edge in (start, end) if 0 < edge < len(text))
    if cuts:
        split = []
        for start, end, kind in phrases:
            edges = [start] + sorted(cut for cut in cuts if start < cut < end) + [end]
            split.extend([left, right, kind] for left, right in zip(edges, edges[1:]))
        phrases = split
    return [(start, end, text[start:end]) for start, end, kind in phrases if end > start and kind != "other"]
