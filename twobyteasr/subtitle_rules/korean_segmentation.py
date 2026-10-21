"""Korean line breaking (2026-10-19).

Korean subtitles are cut between words (어절, separated by spaces), never
inside one. Each recognizer utterance stays one subtitle when it fits; a
longer one is split at the best places, chosen by these rules (also written
into the AI prompt below, so both follow the same rules):

1. Break after a sentence end (. ? ! … or a final ending such as -요, -니다,
   -죠, -다) first, then after a comma, then after a connective ending
   (-고, -지만, -는데, -서, -니까, -면, -면서…). A clear pause in the audio
   between two words also favours a break.
2. Never break before an auxiliary verb (먹어 | 봐, 하고 | 있어, 하지 | 않아,
   가고 | 싶어), before a dependent noun (할 | 수, 먹을 | 것, 갈 | 때, 본 | 적),
   after a determiner or number word (이 | 사람, 그런 | 거, 몇 | 개, 세 | 번),
   after 안 / 못 (안 | 해), or between a number and its counter (3 | 개).
3. Lines up to 16 characters, preferably about 12 (Netflix Korean guide: a
   space, Latin letter, digit or mark counts half); at most 6 seconds; avoid a
   one-word piece unless it is a sentence by itself.

Timing comes from the aligner's units (Qwen3-ForcedAligner in Korean, which
may split a word into stem and particle) matched character by character;
otherwise it is shared out by characters inside the utterance and the final
per-caption alignment measures it.

The optional AI pass sends numbered words and gets back only the indexes after
which to break, so it can never change a word; anything invalid falls back to
these local rules.
"""
from __future__ import annotations

import difflib
import json
import re

from .english_segmentation import _fill_times
from .korean_text import RULES, display_length, join, normalize_spaces, word_core, words as split_words
from ..recognition.transcript_data import SubtitleCue

SENTENCE_END = re.compile(r"[.!?…。？！]+[\"'”’)\]」』]*$")
CLAUSE_END = re.compile(r"[,;:，、—–]+[\"'”’)\]」』]*$")
# Endings that close a spoken sentence even without punctuation.
FINAL_ENDINGS = ("요", "니다", "니까요", "죠", "다", "냐", "까", "군요", "네요", "거든", "잖아")
# Connective endings: a clause ends here.
CONNECTIVE_ENDINGS = ("고", "지만", "는데", "은데", "인데", "던데", "서", "니까", "면", "면서", "며", "거나",
                      "도록", "자마자", "려고", "다가", "든지", "더니", "아도", "어도", "해도", "니")
# A word starting like this completes the previous verb (보조 용언).
AUXILIARY_STARTS = ("싶", "있", "없", "않", "말", "주", "줘", "줄", "보", "봐", "봤", "버리", "버렸", "놓", "놔", "두",
                    "계", "못", "되", "돼", "됐", "하", "해", "했", "가", "와", "오")
AUXILIARY_AFTER = ("고", "어", "아", "여", "지", "게", "야", "러", "려", "도")
DEPENDENT_NOUNS = {"수", "것", "거", "게", "걸", "건", "때", "적", "줄", "데", "뿐", "만큼", "듯", "척", "채", "대로", "바",
                   "지", "중", "편", "번", "개", "명", "분", "초", "시", "판", "킬", "레벨", "원", "살", "등"}
DETERMINERS = {"이", "그", "저", "이런", "그런", "저런", "어떤", "무슨", "몇", "한", "두", "세", "네", "다섯", "여섯",
               "일곱", "여덟", "아홉", "열", "이번", "저번", "다음", "모든", "각", "첫", "새", "웬", "온", "전", "제"}
NEGATIONS = {"안", "못"}
_NUMBER = re.compile(r"^[$€£¥₩]?\d[\d,.]*%?$")


def _core(word: str) -> str:
    return word_core(word)


def _final(word: str) -> bool:
    core = _core(word)
    return bool(SENTENCE_END.search(word)) or (len(core) >= 2 and core.endswith(FINAL_ENDINGS))


def _connective(word: str) -> bool:
    core = _core(word)
    return bool(CLAUSE_END.search(word)) or (len(core) >= 2 and core.endswith(CONNECTIVE_ENDINGS))


def break_scores(tokens: list[str], gaps: list[float] | None = None) -> list[float]:
    """Score for breaking after token i (higher is better; very negative is forbidden)."""
    scores = []
    gaps = gaps or [0.0] * max(0, len(tokens) - 1)
    for index in range(len(tokens) - 1):
        left, right = tokens[index], tokens[index + 1]
        left_core, right_core = _core(left), _core(right)
        score = 0.0
        punctuated = bool(SENTENCE_END.search(left) or CLAUSE_END.search(left))
        if SENTENCE_END.search(left):
            score += 100
        elif CLAUSE_END.search(left):
            score += 60
        elif _final(left):
            score += 70
        elif _connective(left):
            score += 40
        pause = gaps[index] if index < len(gaps) else 0.0
        if pause >= 0.35:
            score += 50
        elif pause >= 0.2:
            score += 20
        if not punctuated:
            if right_core in DEPENDENT_NOUNS or (len(right_core) <= 2 and right_core[:1] in {"수", "것", "거", "때", "적", "줄"}):
                score -= 90
            if right_core.startswith(AUXILIARY_STARTS) and left_core.endswith(AUXILIARY_AFTER) and len(left_core) >= 2:
                score -= 70
            if left_core in DETERMINERS:
                score -= 80
            if left_core in NEGATIONS:
                score -= 80
            if _NUMBER.match(left_core or left):
                score -= 70
        scores.append(score)
    return scores


def split_tokens(tokens: list[str], gaps: list[float] | None = None, *, durations: list[float] | None = None,
                 rules=RULES) -> list[tuple[int, int]]:
    """Best split of ``tokens`` into (start, end) ranges, end exclusive."""
    count = len(tokens)
    if count == 0:
        return []
    if display_length(" ".join(tokens)) <= rules.max_chars and (durations is None or sum(durations) <= rules.max_seconds):
        return [(0, count)]
    scores = break_scores(tokens, gaps)
    lengths = [display_length(token) for token in tokens]

    def piece_cost(start, end):
        length = sum(lengths[start:end]) + 0.5 * (end - start - 1)
        if length > rules.max_chars and end - start > 1:
            return None
        seconds = sum(durations[start:end]) if durations else 0.0
        # Every extra line costs a little (fewer, fuller lines read better); short scraps cost more.
        cost = 18 + abs(length - rules.preferred_chars) * 1.5
        if length < rules.min_chars:
            cost += 45
        if end - start == 1 and not _final(tokens[start]):
            cost += 60     # one word on its own only when it is a sentence by itself
        if durations and seconds > rules.max_seconds:
            cost += 40 * (seconds - rules.max_seconds)
        return cost

    best = [0.0] + [float("inf")] * count
    back = [0] * (count + 1)
    for end in range(1, count + 1):
        for start in range(end - 1, -1, -1):
            cost = piece_cost(start, end)
            if cost is None:
                break
            bonus = -scores[start - 1] if start > 0 else 0.0
            total = best[start] + cost + bonus
            if total < best[end]:
                best[end], back[end] = total, start
    pieces, end = [], count
    while end > 0:
        start = back[end]
        pieces.append((start, end))
        end = start
    return list(reversed(pieces))


# ---------------------------------------------------------------- timing
def _word_times(segment, tokens: list[str], aligned: list[dict]) -> list[tuple[float, float] | None]:
    """Each token's (start, end) from aligner units matched character by character, else None.

    The Korean aligner may split one word into stem and particle (방송 + 을), so
    units are matched on their characters, not as whole words.
    """
    pool = [row for row in aligned if float(row.get("end", 0)) > segment.start - 0.3
            and float(row.get("start", 0)) < segment.end + 0.3 and _core(row.get("text", ""))]
    if not pool:
        return [None] * len(tokens)
    left, owner_left = [], []
    for index, token in enumerate(tokens):
        for char in _core(token):
            left.append(char)
            owner_left.append(index)
    right, owner_right = [], []
    for index, row in enumerate(pool):
        for char in _core(row.get("text", "")):
            right.append(char)
            owner_right.append(index)
    matched = [0] * len(tokens)
    shares: dict[int, dict[int, int]] = {}      # row -> {token: matched characters}, in text order
    matcher = difflib.SequenceMatcher(a=left, b=right, autojunk=False)
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            token, row = owner_left[block.a + offset], owner_right[block.b + offset]
            matched[token] += 1
            per_row = shares.setdefault(row, {})
            per_row[token] = per_row.get(token, 0) + 1
    # One unit may cover several words (the aligner can return one coarse span
    # for a repeated "0715 0715 …"): its time is shared out between them in
    # order, by matched characters, so the words never all start together.
    spans: dict[int, list[float]] = {}
    for row, per_row in shares.items():
        start, end = float(pool[row]["start"]), float(pool[row]["end"])
        total = sum(per_row.values())
        cursor = start
        for token in sorted(per_row):
            part = (end - start) * per_row[token] / total
            span = spans.setdefault(token, [cursor, cursor + part])
            span[0], span[1] = min(span[0], cursor), max(span[1], cursor + part)
            cursor += part
    # A token counts as measured only when every character of it was matched.
    return [(spans[index][0], spans[index][1]) if index in spans and matched[index] == len(_core(token)) else None
            for index, token in enumerate(tokens)]


def group_korean(segments, firered_tokens=(), *, breaks_for=None) -> list[SubtitleCue]:
    """Korean cues from recognizer utterances: one per utterance, long ones split by the rules.

    ``breaks_for(segment, tokens)`` may return break indexes for one utterance
    (the AI pass); invalid answers fall back to :func:`split_tokens`.
    """
    cues: list[SubtitleCue] = []
    aligned = [row for row in (firered_tokens or ()) if isinstance(row, dict)]
    for segment in sorted(segments, key=lambda item: (item.start, item.end, item.segment_id)):
        tokens = split_words(segment.text)
        if not tokens:
            continue
        times = _fill_times(segment, tokens, _word_times(segment, tokens, aligned))
        gaps = [max(0.0, times[i + 1][0] - times[i][1]) for i in range(len(tokens) - 1)]
        durations = [max(0.0, end - start) for start, end in times]
        pieces = None
        if breaks_for is not None and display_length(segment.text) > RULES.max_chars:
            try:
                pieces = pieces_from_breaks(tokens, breaks_for(segment, tokens))
            except Exception:
                pieces = None
        pieces = pieces or split_tokens(tokens, gaps, durations=durations)
        for first, last in pieces:
            cue_start = times[first][0] if first else float(segment.start)
            cue_end = times[last - 1][1] if last < len(tokens) else float(segment.end)
            cues.append(SubtitleCue(len(cues) + 1, round(cue_start, 3), round(max(cue_end, cue_start + 0.2), 3),
                                    join(tokens[first:last]), bool(getattr(segment, "timing_locked", False)),
                                    segment.speaker or "S00"))
    return cues


def pieces_from_breaks(tokens: list[str], breaks) -> list[tuple[int, int]] | None:
    """Ranges from 'break after word i' indexes; None when they are not valid or a piece is too long."""
    try:
        cuts = sorted({int(value) for value in breaks})
    except (TypeError, ValueError):
        return None
    if any(cut < 0 or cut >= len(tokens) - 1 for cut in cuts):
        return None
    edges = [0] + [cut + 1 for cut in cuts] + [len(tokens)]
    pieces = [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]
    if any(display_length(" ".join(tokens[a:b])) > RULES.max_chars and b - a > 1 for a, b in pieces):
        return None
    return pieces


# ---------------------------------------------------------------- the AI pass
KOREAN_GROUPING_PROMPT_VERSION = "korean-word-breaks-v2"   # v2: shared aligner units are split between words
KOREAN_GROUPING_SYSTEM_PROMPT = f"""You split Korean game-stream subtitles into readable lines.
You receive utterances as numbered words (어절, separated by spaces). Return ONLY JSON: {{"breaks": {{"<utterance id>": [word numbers]}}}}
where each number n means "a new subtitle starts after word n". Never change, add, remove or join words.
Rules:
1. Each subtitle at most {RULES.max_chars:g} characters (a Hangul syllable counts 1; a space, Latin letter, digit or punctuation mark counts 0.5), ideally about {RULES.preferred_chars:g}; at most {RULES.max_seconds:g} seconds.
2. Prefer breaking after a sentence end (. ? ! or a final ending such as -요, -니다, -죠, -다), then after a comma, then after a connective ending (-고, -지만, -는데, -서, -니까, -면, -면서).
3. Never break before an auxiliary verb (먹어 봐, 하고 있어, 하지 않아, 가고 싶어), before a dependent noun (할 수, 먹을 것, 갈 때, 본 적), after a determiner or number word (이 사람, 그런 거, 몇 개, 세 번), after 안/못, or between a number and its counter.
4. Keep a short utterance whole; avoid one-word pieces unless the word is a sentence by itself.
Utterances that already fit need no breaks: return [] for them."""


def build_ai_messages(batch: list[tuple[str, list[str]]]) -> list[dict]:
    payload = [{"id": key, "words": {str(i): token for i, token in enumerate(tokens)}} for key, tokens in batch]
    return [{"role": "system", "content": KOREAN_GROUPING_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({"utterances": payload}, ensure_ascii=False)}]


def ai_breaks(segments, provider_snapshot, *, complete=None) -> dict:
    """Break indexes per long utterance from the grouping AI (one request per ~40 utterances)."""
    from .english_segmentation import parse_ai_breaks
    if complete is None:
        from ..providers.ai_providers import provider_for_stage
        from .grouping import post_chat_completion
        provider = provider_for_stage(provider_snapshot.execution_settings(), "group", sender=post_chat_completion)

        def complete(messages):
            return provider.complete(messages, stage="grouped", operation_kind="group", max_tokens=1200,
                                     temperature=0.0, timeout=provider_snapshot.timeout_policy.total,
                                     _timeout_policy=provider_snapshot.timeout_policy, enable_thinking=False,
                                     response_format={"type": "json_object"})
    long = [(str(segment.segment_id), split_words(segment.text)) for segment in segments
            if display_length(segment.text) > RULES.max_chars]
    found: dict = {}
    for offset in range(0, len(long), 40):
        batch = long[offset:offset + 40]
        try:
            found.update(parse_ai_breaks(complete(build_ai_messages(batch))))
        except Exception:
            continue
    return found


def group_korean_with_ai(segments, firered_tokens=(), provider_snapshot=None, *, complete=None) -> list[SubtitleCue]:
    answers = ai_breaks(segments, provider_snapshot, complete=complete) if (provider_snapshot or complete) else {}
    return group_korean(segments, firered_tokens,
                        breaks_for=lambda segment, _tokens: answers.get(str(segment.segment_id)) or None)


def describe_rules() -> str:
    return normalize_spaces(__doc__.split("\n\n", 2)[1])
