"""Japanese line-break evidence: bunsetsu boundaries from real morphology.

Chinese segmentation (jieba spans, 的/了 rules) does not apply to Japanese,
and a script-class heuristic cannot see inside long hiragana stretches
(もっとみんなにわかるように), so cue splitting used to fall back to hard
cuts in the middle of words. Japanese tasks therefore tag the exact segment
texts that grouping sees with nagisa (words + part of speech) in the main
managed runtime (model-free mode of ``qwen_aligner_worker.py``; the GUI and
pipeline processes never import nagisa) and derive:

* allowed breaks: bunsetsu starts (an independent word that is not part of
  a compound noun, a suru-verb, a te-form auxiliary or a fixed expression);
* strong breaks: after punctuation/MOSS pauses and sentence-final particles,
  before interjections and conjunctions.

Offsets live on the task's *content* string (``content_exact``: punctuation
and spaces removed), which is what every segmentation helper indexes. A cue
or batch text is located in the task document by its content; when it is
not found (Studio edits, other tasks) callers keep the heuristic in
``language_rules``.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

PROTOCOL = "ja-morphology-v1"
BUNSETSU_POLICY = "ja-bunsetsu-v1"

INDEPENDENT = {"名詞", "代名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "接続詞", "感動詞", "接頭辞",
               "英単語", "URL"}
NOMINAL = {"名詞", "代名詞", "接尾辞", "英単語"}
NON_CONTENT = {"補助記号", "記号", "空白"}
SURU = {"する", "し", "さ", "せ", "しよ", "すれ", "しろ", "できる", "でき", "出来", "出来る"}
# Verbs that are auxiliaries after the te-form (して|いる is one phrase).
AFTER_TE = {"い", "いる", "いれ", "いろ", "いら", "る", "ある", "あっ", "あり", "おく", "おい", "おか", "とく",
            "とい", "とか", "しまう", "しまっ", "しまい", "ちゃう", "ちゃっ", "じゃう", "じゃっ", "くる", "き",
            "こ", "来", "来る", "いく", "いっ", "いか", "行く", "行っ", "みる", "み", "みよ", "もらう", "もらっ",
            "もらい", "あげる", "あげ", "くれる", "くれ", "やる", "やっ", "ください", "下さい", "ほしい", "欲しい"}
NEGATIVE_HEADS = ("ない", "なく", "なかっ", "なけれ")
# Formal/auxiliary nominals that a predicate needs (わかる|ように, する|ことが).
ATTACH_AFTER_PREDICATE = {"よう", "そう", "みたい", "ん", "の", "こと", "もの", "ところ", "わけ", "はず",
                          "とき", "ため", "まま", "つもり", "ほう"}
PREDICATE = {"動詞", "形容詞", "助動詞"}
FINAL_PARTICLES = {"ね", "よ", "な", "わ", "ぞ", "ぜ", "さ", "か", "かな", "よね", "わね", "のね", "もん",
                   "じゃん", "ねー", "よー", "なー", "かー"}
# Fixed expressions nagisa sometimes splits (もし|か|し|て): no cut inside.
FIXED_EXPRESSIONS = ("もしかして", "もしかしたら", "なんて", "なんか", "なんで", "どうして", "やっぱり",
                     "やっぱ", "ちょっと", "とにかく", "それでも", "だから", "じゃあ", "ところで",
                     "そういえば", "いつも", "みんな", "ありがとう", "おはよう", "こんにちは", "すみません",
                     "っていう", "という", "っていうか")
# Auxiliary verbs fused to the previous stem (高|すぎる, 言い|出す).
STEM_AUXILIARIES = ("すぎ", "過ぎ", "やす", "にく", "づら", "がる", "がっ")
# Lengthened interjections (いやー, あー, うわー): their own phrase when they
# follow a finished clause; nagisa mis-tags some (ね|い|やー).
INTERJECTION_RE = re.compile(r"(?:いや|うわ|よし|あ|え|お|わ|ま|ほ|へ|は|ふ|ん)ー+")
FINAL_CHARS = set("ねよなわぞぜさかのー")
# A modifier and its head noun (襲われた|人が, ハオの|レベル) stay on one line
# while the whole noun phrase is this short (content characters).
ATTRIBUTIVE_KEEP_CHARS = 10

_CONTENT_RE = None


def _content_re():
    global _CONTENT_RE
    if _CONTENT_RE is None:
        from twobyteasr.language_rules import CONTENT_CHAR_CLASS
        _CONTENT_RE = re.compile(f"[{CONTENT_CHAR_CLASS}]")
    return _CONTENT_RE


def content_positions(text: str) -> list[int]:
    """Indices of content characters (the ``content_exact`` alphabet) in ``text``."""
    pattern = _content_re()
    return [index for index, char in enumerate(text) if pattern.match(char)]


class MorphologyUnavailable(RuntimeError):
    pass


def tag_texts(texts, *, timeout: float = 180.0) -> dict:
    """nagisa words/POS for ``texts`` from the main managed runtime (no model, no GPU)."""
    from twobyteasr.asr import SCRIPT_DIR, _main_worker_python
    from twobyteasr.processes import python_utf8_command, run_hidden_subprocess
    texts = [str(text) for text in texts]
    try:
        runtime = _main_worker_python()
    except RuntimeError as error:
        raise MorphologyUnavailable(str(error)) from error
    worker = os.path.join(os.path.abspath(SCRIPT_DIR), "qwen_aligner_worker.py")
    if not os.path.isfile(runtime) or not os.path.isfile(worker):
        raise MorphologyUnavailable(f"日语分词运行库缺失：python={runtime}, worker={worker}")
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="ja_morphology_") as temp_dir:
        manifest = Path(temp_dir) / "manifest.json"
        output = Path(temp_dir) / "result.json"
        manifest.write_text(json.dumps({"protocol": PROTOCOL, "texts": texts}, ensure_ascii=False), "utf-8")
        completed = run_hidden_subprocess(
            python_utf8_command([runtime, "-I", worker, "--tag-only", "--manifest", str(manifest),
                                 "--output", str(output)]),
            purpose="japanese-morphology", capture_output=True, timeout=timeout)
        if completed.returncode != 0 or not output.is_file():
            detail = (completed.stderr or b"")[-600:]
            detail = detail.decode("utf-8", "replace") if isinstance(detail, bytes) else str(detail)
            raise MorphologyUnavailable(f"日语分词失败（exit {completed.returncode}）：{detail.strip()}")
        payload = json.loads(output.read_text("utf-8"))
    rows = payload.get("results") if isinstance(payload, dict) else None
    if (payload.get("protocol") != PROTOCOL or not isinstance(rows, list)
            or [row.get("text") for row in rows] != texts):
        raise MorphologyUnavailable("日语分词回执与输入不一致")
    payload["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    return payload


def word_spans(text: str, words) -> list[tuple[int, int, str, str]] | None:
    """Place tagged words back on ``text``; None when the tagger changed the text."""
    spans, cursor = [], 0
    for word, tag in words:
        word = str(word)
        if not word.strip():
            # Whitespace is a MOSS pause/punctuation mark: keep it as a break token.
            end = cursor
            while end < len(text) and text[end].isspace():
                end += 1
            if end > cursor:
                spans.append((cursor, end, text[cursor:end], "空白"))
                cursor = end
            continue
        while cursor < len(text) and text[cursor].isspace():
            end = cursor
            while end < len(text) and text[end].isspace():
                end += 1
            spans.append((cursor, end, text[cursor:end], "空白"))
            cursor = end
        piece = text[cursor:cursor + len(word)]
        if piece != word and unicodedata.normalize("NFKC", piece) != unicodedata.normalize("NFKC", word):
            return None
        spans.append((cursor, cursor + len(word), word, str(tag)))
        cursor += len(word)
    if text[cursor:].strip():
        return None
    return spans


def _starts_phrase(word: str, tag: str, previous: tuple[str, str] | None) -> bool:
    if previous is None:
        return True
    if tag not in INDEPENDENT:
        return False
    before_word, before_tag = previous
    if before_tag in ("接頭辞", "連体詞"):
        return False                              # この|子ら: an adnominal needs its noun
    if tag == "動詞" and before_tag == "動詞":
        return False                              # compound verb
    if word.startswith(STEM_AUXILIARIES) and before_tag in ("動詞", "形容詞", "形状詞"):
        return False                              # 高|すぎた
    if tag in NOMINAL and before_tag in NOMINAL:
        return False                              # compound noun / number + counter
    if tag == "動詞" and before_tag in ("名詞", "形状詞") and word in SURU:
        return False                              # 勉強|する
    if tag == "動詞" and before_word in ("て", "で") and word in AFTER_TE:
        return False                              # して|いる, 見て|みる
    if tag in ("形容詞", "助動詞") and word.startswith(NEGATIVE_HEADS) and before_tag in ("動詞", "助詞", "助動詞"):
        return False                              # 引け|ない, じゃ|ない, て|ない
    if word in ATTACH_AFTER_PREDICATE and before_tag in PREDICATE:
        return False                              # わかる|ように, する|ことが
    return True


def bunsetsu_breaks(text: str, spans) -> tuple[set[int], set[int]]:
    """Allowed and strong break offsets in ``text`` (a break at i starts a phrase at i)."""
    allowed: set[int] = set()
    strong: set[int] = set()
    attributive: list[int] = []
    previous = None
    pending_strong = False
    for start, end, word, tag in spans:
        if tag == "空白" or not content_positions(word):
            pending_strong = previous is not None
            continue
        if tag in NON_CONTENT:
            # Symbols that are letters here: a long-vowel mark joins the
            # previous word, anything else (a lone わ) is a word of its own.
            tag = "接尾辞" if set(word) <= {"ー", "〜", "~"} else "名詞"
        new = _starts_phrase(word, tag, previous) or pending_strong
        if new and previous is not None:
            allowed.add(start)
            if (pending_strong or tag in ("感動詞", "接続詞")
                    or (previous[1] == "助詞" and previous[0] in FINAL_PARTICLES)):
                strong.add(start)
            elif tag in ("名詞", "代名詞") and (previous[1] in PREDICATE or previous == ("の", "助詞")):
                attributive.append(start)
        previous = (word, tag)
        pending_strong = False
    for offset in attributive:
        before = max((value for value in allowed if value < offset), default=0)
        after = min((value for value in allowed if value > offset), default=len(text))
        if len(content_positions(text[before:after])) <= ATTRIBUTIVE_KEEP_CHARS:
            allowed.discard(offset)
    for expression in FIXED_EXPRESSIONS:
        index = text.find(expression)
        while index >= 0:
            for offset in range(index + 1, index + len(expression)):
                allowed.discard(offset)
                strong.discard(offset)
            index = text.find(expression, index + 1)
    for match in INTERJECTION_RE.finditer(text):
        start, end = match.span()
        left = text[:start].rstrip()
        if start == 0 or not left or left[-1] in FINAL_CHARS or not content_positions(left[-1]):
            for offset in range(start + 1, end):
                allowed.discard(offset)
            if start > 0:
                allowed.add(start)
                strong.add(start)
            if end < len(text.rstrip()):
                allowed.add(end)
                strong.add(end)
    return allowed, strong


@dataclass
class PhraseDocument:
    """All segment texts of one Japanese task on one content axis."""
    content: str = ""
    allowed: frozenset = field(default_factory=frozenset)
    strong: frozenset = field(default_factory=frozenset)
    measured_segments: int = 0
    heuristic_segments: int = 0
    tagger: str = ""

    def receipt(self) -> dict:
        return {"policy": BUNSETSU_POLICY, "tagger": self.tagger, "content_characters": len(self.content),
                "allowed_breaks": len(self.allowed), "strong_breaks": len(self.strong),
                "measured_segments": self.measured_segments, "heuristic_segments": self.heuristic_segments}


def _heuristic_breaks(text: str) -> tuple[set[int], set[int]]:
    from twobyteasr.language_rules import heuristic_japanese_phrase_spans
    starts = {start for start, _end, _word in heuristic_japanese_phrase_spans(text)}
    strong = {index for index in range(1, len(text)) if text[index - 1].isspace() and not text[index].isspace()}
    return starts - {0}, strong


def build_document(texts, payload: dict | None) -> PhraseDocument:
    """Map each text's breaks onto the joined content string (segment joins are strong breaks)."""
    rows = (payload or {}).get("results") or []
    content, allowed, strong = [], set(), set()
    measured = heuristic = 0
    base = 0
    for index, text in enumerate(texts):
        text = str(text)
        row = rows[index] if index < len(rows) else None
        spans = word_spans(text, row.get("words") or []) if row and row.get("text") == text else None
        if spans:
            text_allowed, text_strong = bunsetsu_breaks(text, spans)
            measured += 1
        else:
            text_allowed, text_strong = _heuristic_breaks(text)
            heuristic += 1
        positions = content_positions(text)
        to_content = {position: rank for rank, position in enumerate(positions)}
        # A break between two content characters, wherever spaces/punctuation sit.
        for offsets, target in ((text_allowed, allowed), (text_strong, strong)):
            for offset in offsets:
                following = next((p for p in positions if p >= offset), None)
                if following is not None and to_content[following] > 0:
                    target.add(base + to_content[following])
        if base:
            allowed.add(base)
            strong.add(base)
        content.append("".join(text[p] for p in positions))
        base += len(positions)
    return PhraseDocument("".join(content), frozenset(allowed), frozenset(strong), measured, heuristic,
                          f"nagisa {(payload or {}).get('tagger_version', '')}".strip() if measured else "")


def install(document: PhraseDocument | None) -> None:
    from twobyteasr.runtime import get_runtime_context
    get_runtime_context().japanese_phrases = document


_SCOPE = threading.local()


@contextmanager
def phrase_scope(document: PhraseDocument | None):
    """Studio: use ``document`` (the open project's tagged texts) on this thread."""
    previous = getattr(_SCOPE, "document", None)
    _SCOPE.document = document
    try:
        yield document
    finally:
        _SCOPE.document = previous


def document_for_texts(texts) -> PhraseDocument | None:
    """Tag ``texts`` (main runtime, no model); None when the tagger is unavailable."""
    texts = [str(text) for text in texts if str(text or "").strip()]
    if not texts:
        return None
    try:
        payload = tag_texts(texts)
    except (MorphologyUnavailable, OSError, ValueError):
        return None
    return build_document(texts, payload)


def _document() -> PhraseDocument | None:
    scoped = getattr(_SCOPE, "document", None)
    if scoped is not None:
        return scoped
    try:
        from twobyteasr.runtime import get_runtime_context
        return getattr(get_runtime_context(), "japanese_phrases", None)
    except Exception:
        return None


def _locate(content: str, document: PhraseDocument, limit: int = 16) -> list[int]:
    found, index = [], document.content.find(content)
    while index >= 0 and len(found) < limit:
        found.append(index)
        index = document.content.find(content, index + 1)
    return found


def _content_breaks(text: str, attribute: str) -> tuple[list[int], set[int]] | None:
    document = _document()
    if document is None or not document.content:
        return None
    positions = content_positions(text)
    content = "".join(text[p] for p in positions)
    if not content:
        return None
    places = _locate(content, document)
    if not places:
        return None
    marks = getattr(document, attribute)
    # A repeated line must agree everywhere it occurs before a cut is allowed.
    breaks = {k for k in range(1, len(content)) if all(place + k in marks for place in places)}
    return positions, breaks


def document_phrase_spans(text: str) -> list[tuple[int, int, str]] | None:
    """Bunsetsu spans of ``text`` (indices into ``text``) from the task document, or None."""
    located = _content_breaks(text, "allowed")
    if located is None:
        return None
    positions, breaks = located
    cuts = [0] + sorted(breaks) + [len(positions)]
    spans = []
    for left, right in zip(cuts, cuts[1:]):
        start, end = positions[left], positions[right - 1] + 1
        spans.append((start, end, text[start:end]))
    return spans


def document_strong_breaks(text: str) -> set[int] | None:
    """Strong break offsets on the content of ``text`` (content indices), or None."""
    located = _content_breaks(text, "strong")
    return None if located is None else located[1]
