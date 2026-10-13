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
# (incl. ー and 々, not the ・ separator) and ASCII letters/digits.
CONTENT_CHAR_CLASS = (r"\u3400-\u9fff\u3005\u3041-\u3096\u309d-\u309f\u30a1-\u30fa\u30fc-\u30ff"
                      r"\u31f0-\u31ff\uff66-\uff9fA-Za-z0-9")

AUTO, ZH, JA = "auto", "zh", "ja"
SUPPORTED_REQUESTS = (AUTO, ZH, JA)
QWEN_LANGUAGE_NAMES = {ZH: "Chinese", JA: "Japanese"}
_ALIASES = {"": AUTO, "auto": AUTO, "zh": ZH, "zh-cn": ZH, "zh-hans": ZH, "zh-hant": ZH, "chinese": ZH, "cn": ZH,
            "ja": JA, "ja-jp": JA, "jp": JA, "japanese": JA}

# Kana share of (kana + kanji) above which a transcript is Japanese.
KANA_SHARE_JA = 0.12
MIN_KANA_JA = 4

# Which roles each local model fills for each language. "transcribe" is
# speech-to-text; "align" is forced alignment of a given text; "speakers" is
# diarization; "language_id" is spoken-language identification.
MODEL_LANGUAGE_ROLES = {
    "moss": {"transcribe": {ZH, JA}, "speakers": {ZH, JA}, "align": set(), "language_id": set()},
    "qwen3_asr": {"transcribe": {ZH, JA}, "language_id": {ZH, JA}, "align": set(), "speakers": set()},
    "qwen_aligner": {"align": {ZH, JA}, "transcribe": set(), "speakers": set(), "language_id": set()},
    "firered_aed": {"transcribe": {ZH}, "align": {ZH}, "speakers": set(), "language_id": set()},
    "firered_llm": {"transcribe": {ZH}, "align": set(), "speakers": set(), "language_id": set()},
    "paraformer": {"transcribe": {ZH}, "align": {ZH}, "speakers": set(), "language_id": set()},
    "firered_vad": {"vad": {ZH, JA}},
}


def supports(model: str, role: str, language: str) -> bool:
    return language in MODEL_LANGUAGE_ROLES.get(model, {}).get(role, set())


def normalize_language(value) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    return _ALIASES.get(text, AUTO)


def qwen_language_name(language: str):
    """Language argument for qwen-asr: a name, or None to let it identify."""
    return QWEN_LANGUAGE_NAMES.get(normalize_language(language))


def language_from_qwen_name(name) -> str:
    return {"chinese": ZH, "japanese": JA}.get(str(name or "").strip().lower(), "")


def _is_kana(code: int) -> bool:
    return 0x3041 <= code <= 0x309F or 0x30A0 <= code <= 0x30FF or 0x31F0 <= code <= 0x31FF or 0xFF66 <= code <= 0xFF9D


def script_counts(texts) -> dict:
    counts = {"kana": 0, "han": 0, "latin": 0, "hangul": 0}
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
            elif char.isascii():
                counts["latin"] += 1
    return counts


def detect_language(texts) -> tuple[str, dict]:
    counts = script_counts(texts)
    cjk = counts["kana"] + counts["han"]
    share = counts["kana"] / cjk if cjk else 0.0
    evidence = dict(counts, kana_share=round(share, 4), rule=f"kana/(kana+han) >= {KANA_SHARE_JA} and kana >= {MIN_KANA_JA}")
    if counts["kana"] >= MIN_KANA_JA and share >= KANA_SHARE_JA:
        return JA, evidence
    if counts["han"]:
        return ZH, evidence
    return "", evidence


def resolve_task_language(requested, texts, *, asr_detected=None) -> tuple[str, dict]:
    """The language one task runs with, plus how it was decided.

    A manual choice wins. ``auto`` uses the transcript's scripts, then the
    recognizer's own language identification; an undecidable transcript keeps
    the established Chinese behaviour.
    """
    requested = normalize_language(requested)
    detected, evidence = detect_language(texts)
    evidence = dict(evidence, requested=requested, asr_detected=asr_detected or "")
    if requested in (ZH, JA):
        evidence["decided_by"] = "manual"
        if detected and detected != requested:
            evidence["disagrees_with_transcript"] = detected
        return requested, evidence
    if detected:
        evidence["decided_by"] = "transcript_scripts"
        return detected, evidence
    from_asr = language_from_qwen_name(asr_detected) or normalize_language(asr_detected)
    if from_asr in (ZH, JA):
        evidence["decided_by"] = "asr_language_id"
        return from_asr, evidence
    evidence["decided_by"] = "default_chinese"
    return ZH, evidence


_SCOPE = threading.local()


@contextmanager
def language_scope(language):
    """Run text rules for one project's language on this thread (Studio work)."""
    previous = getattr(_SCOPE, "language", None)
    _SCOPE.language = normalize_language(language) if language else None
    try:
        yield
    finally:
        _SCOPE.language = previous


def active_task_language() -> str:
    """Language for text rules: a scoped project language, else the running task's."""
    scoped = getattr(_SCOPE, "language", None)
    if scoped in (ZH, JA):
        return scoped
    try:
        from .runtime import get_runtime_context
        return str(getattr(get_runtime_context(), "task_language", "") or "")
    except Exception:
        return ""


def project_language(project) -> str:
    """The spoken language recorded for a project ('' for older projects = Chinese rules)."""
    metadata = getattr(project, "generation_metadata", None) or {}
    value = (metadata.get("language") or {}) if isinstance(metadata, dict) else {}
    code = value.get("code") if isinstance(value, dict) else value
    code = normalize_language(code)
    return code if code in (ZH, JA) else ""


def is_japanese(language=None) -> bool:
    return (active_task_language() if language is None else normalize_language(language)) == JA


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
    return JAPANESE_SEGMENTATION if is_japanese(language) else CHINESE_SEGMENTATION


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
    from twobyteasr.japanese_morphology import document_phrase_spans
    measured = document_phrase_spans(text)
    if measured is not None:
        return [span for span in measured if span[1] > span[0]]
    return heuristic_japanese_phrase_spans(text)


def japanese_strong_breaks(text: str) -> set[int]:
    """Content offsets where a Japanese line should preferably break."""
    from twobyteasr.japanese_morphology import INTERJECTION_RE, content_positions, document_strong_breaks
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
    from twobyteasr.japanese_morphology import FINAL_CHARS, INTERJECTION_RE
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
