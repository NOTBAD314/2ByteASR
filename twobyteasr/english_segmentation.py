"""English line breaking (2026-10-14).

English subtitles are cut between words, never inside one. Each recognizer
utterance (one speaker, one natural sentence from MOSS) stays one subtitle
when it fits; a longer one is split at the best places, chosen by these rules
(also written into the AI prompt below, so both follow the same rules):

1. Break after a sentence end (. ! ? …) first, then after a clause mark
   (, ; : — –), then before a conjunction or relative word (and, but, or, so,
   because, when, which, who…), then before a preposition (in, on, at, to,
   with…). A clear pause in the audio between two words also favours a break.
2. Never end a line with an article or determiner (a, an, the, this, my…),
   a preposition, a conjunction, an auxiliary (is, was, can, will, have…) or
   a subject pronoun about to get its verb (I, you, we…): it leaves the line
   hanging.
3. Never split a name (Capitalised words in a row), a number from its unit or
   noun (10 minutes, 3 kills, 50%), "not"/"n't" from its verb, or a word from
   the possessive or particle that completes it.
4. Lines up to 42 characters (spaces included), preferably about 32; at most
   6 seconds; avoid a piece of one or two short words when a balanced split
   exists.

Timing comes from the aligner's words when they can be matched to the text
(Qwen3-ForcedAligner in English); otherwise it is shared out by characters
inside the utterance and the final per-caption alignment measures it.

The optional AI pass sends numbered words and gets back only the indexes after
which to break, so it can never change a word; anything invalid falls back to
these local rules.
"""
from __future__ import annotations

import difflib
import json
import re

from .english_text import RULES, display_length, join, normalize_spaces, word_core, words as split_words
from .models import SubtitleCue

SENTENCE_END = re.compile(r"[.!?…]+[\"'”’)\]]*$")
CLAUSE_END = re.compile(r"[,;:—–]+[\"'”’)\]]*$|-{2,}$")
CONJUNCTIONS = {"and", "but", "or", "so", "because", "cause", "'cause", "when", "while", "if", "although", "though",
                "since", "unless", "until", "till", "whereas", "yet", "then", "after", "before", "which", "who",
                "whom", "whose", "where", "nor", "once", "whether"}
PREPOSITIONS = {"in", "on", "at", "to", "for", "with", "from", "about", "into", "onto", "over", "under", "of", "by",
                "through", "across", "against", "between", "around", "without", "within", "behind", "during",
                "toward", "towards", "near", "like", "than", "via", "off", "up"}
DETERMINERS = {"a", "an", "the", "this", "that", "these", "those", "my", "your", "his", "her", "its", "our", "their",
               "some", "any", "no", "every", "each", "another", "such", "what", "which", "whose", "all", "both"}
AUXILIARIES = {"is", "are", "was", "were", "be", "been", "being", "am", "will", "would", "can", "could", "shall",
               "should", "may", "might", "must", "have", "has", "had", "do", "does", "did", "gonna", "wanna",
               "gotta", "i'm", "you're", "we're", "they're", "he's", "she's", "it's", "i've", "you've", "we've",
               "i'll", "you'll", "we'll", "they'll", "i'd", "you'd", "let's"}
SUBJECTS = {"i", "you", "we", "they", "he", "she", "it", "there"}
NEGATIONS = {"not", "never"}
UNIT_WORDS = {"seconds", "second", "minutes", "minute", "hours", "hour", "days", "day", "times", "percent", "kills",
              "kill", "points", "point", "levels", "level", "hp", "mp", "dollars", "bucks", "k", "gold", "coins"}
_NUMBER = re.compile(r"^[$€£¥]?\d[\d,.]*(%|k|m|st|nd|rd|th|s)?$", re.IGNORECASE)


def _capitalised(word: str) -> bool:
    """A name-like word (Capitalised; the pronoun I and its contractions do not count)."""
    core = re.sub(r"^[\"'“‘(\[]+", "", word)
    return bool(core) and core[0].isupper() and word_core(core) not in SUBJECTS | AUXILIARIES


def break_scores(tokens: list[str], gaps: list[float] | None = None) -> list[float]:
    """Score for breaking after token i (higher is better; very negative is forbidden)."""
    scores = []
    gaps = gaps or [0.0] * max(0, len(tokens) - 1)
    for index in range(len(tokens) - 1):
        left, right = tokens[index], tokens[index + 1]
        left_core, right_core = word_core(left), word_core(right)
        score = 0.0
        if SENTENCE_END.search(left):
            score += 100
        elif CLAUSE_END.search(left):
            score += 60
        if right_core in CONJUNCTIONS:
            score += 40
        elif right_core in PREPOSITIONS:
            score += 15
        pause = gaps[index] if index < len(gaps) else 0.0
        if pause >= 0.35:
            score += 50
        elif pause >= 0.2:
            score += 20
        if not SENTENCE_END.search(left) and not CLAUSE_END.search(left):
            if left_core in DETERMINERS:
                score -= 90
            elif left_core in PREPOSITIONS or left_core in CONJUNCTIONS:
                score -= 45
            elif left_core in AUXILIARIES or left_core in NEGATIONS:
                score -= 40
            elif left_core in SUBJECTS:
                score -= 35
            if _NUMBER.match(left_core or left) and (right_core in UNIT_WORDS or right_core.isalpha()):
                score -= 70
            if right_core in NEGATIONS or right_core.startswith("n't"):
                score -= 50
            if _capitalised(left) and _capitalised(right) and index > 0 and not SENTENCE_END.search(tokens[index - 1]):
                score -= 60
            if right_core in {"'s", "s"}:
                score -= 80
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
    lengths = [len(token) for token in tokens]

    def piece_cost(start, end):
        length = sum(lengths[start:end]) + (end - start - 1)
        if length > rules.max_chars and end - start > 1:
            return None
        seconds = sum(durations[start:end]) if durations else 0.0
        # Every extra line costs a little (fewer, fuller lines read better); short scraps cost more.
        cost = 18 + abs(length - rules.preferred_chars) * 0.5
        if length < max(rules.min_chars, 12) or end - start <= 2:
            cost += 45
        if end - start == 1 and not SENTENCE_END.search(tokens[start]):
            cost += 90     # one word on its own ("Okay,") only when it is a sentence by itself
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
    """Each token's (start, end) from aligner words matched by spelling, else None."""
    pool = [row for row in aligned if float(row.get("end", 0)) > segment.start - 0.3
            and float(row.get("start", 0)) < segment.end + 0.3 and word_core(row.get("text", ""))]
    if not pool:
        return [None] * len(tokens)
    left = [word_core(token) for token in tokens]
    right = [word_core(row.get("text", "")) for row in pool]
    times: list[tuple[float, float] | None] = [None] * len(tokens)
    matcher = difflib.SequenceMatcher(a=left, b=right, autojunk=False)
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            row = pool[block.b + offset]
            times[block.a + offset] = (float(row["start"]), float(row["end"]))
    return times


def _fill_times(segment, tokens: list[str], times):
    """Measured times kept; the rest shared out by characters between their neighbours."""
    start, end = float(segment.start), max(float(segment.end), float(segment.start) + 0.05)
    filled = list(times)
    weights = [max(1, len(token)) for token in tokens]
    index = 0
    while index < len(tokens):
        if filled[index] is not None:
            index += 1
            continue
        run_end = index
        while run_end < len(tokens) and filled[run_end] is None:
            run_end += 1
        low = filled[index - 1][1] if index > 0 else start
        high = filled[run_end][0] if run_end < len(tokens) else end
        high = max(high, low + 0.02 * (run_end - index))
        total = sum(weights[index:run_end])
        cursor = low
        for position in range(index, run_end):
            span = (high - low) * weights[position] / total
            filled[position] = (cursor, cursor + span)
            cursor += span
        index = run_end
    return filled


def group_english(segments, firered_tokens=(), *, breaks_for=None) -> list[SubtitleCue]:
    """English cues from recognizer utterances: one per utterance, long ones split by the rules.

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
ENGLISH_GROUPING_PROMPT_VERSION = "english-word-breaks-v1"
ENGLISH_GROUPING_SYSTEM_PROMPT = f"""You split English game-stream subtitles into readable lines.
You receive utterances as numbered words. Return ONLY JSON: {{"breaks": {{"<utterance id>": [word numbers]}}}}
where each number n means "a new subtitle starts after word n". Never change, add or remove words.
Rules:
1. Each subtitle at most {RULES.max_chars} characters including spaces, ideally about {RULES.preferred_chars}; at most {RULES.max_seconds:g} seconds.
2. Prefer breaking after . ! ? first, then after , ; : — , then before and/but/or/so/because/when/which/who, then before a preposition.
3. Never end a subtitle with an article or determiner (a, an, the, this, my, your…), a preposition, a conjunction, an auxiliary verb (is, was, can, will, have…) or a subject pronoun waiting for its verb.
4. Never split a name, a number from its unit (10 minutes, 50%), "not" from its verb, or a phrasal verb (pick up, log in).
5. Keep a short utterance whole; avoid one- or two-word pieces when a balanced split exists.
Utterances that already fit need no breaks: return [] for them."""


def build_ai_messages(batch: list[tuple[str, list[str]]]) -> list[dict]:
    payload = [{"id": key, "words": {str(i): token for i, token in enumerate(tokens)}} for key, tokens in batch]
    return [{"role": "system", "content": ENGLISH_GROUPING_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({"utterances": payload}, ensure_ascii=False)}]


def parse_ai_breaks(content: str) -> dict[str, list[int]]:
    text = str(content or "").strip()
    start, end = text.find("{"), text.rfind("}")
    data = json.loads(text[start:end + 1]) if start >= 0 and end > start else {}
    breaks = data.get("breaks") if isinstance(data, dict) else None
    return {str(key): list(value) for key, value in (breaks or {}).items() if isinstance(value, list)}


def ai_breaks(segments, provider_snapshot, *, complete=None) -> dict:
    """Break indexes per long utterance from the grouping AI (one request per ~40 utterances).

    ``complete(messages) -> str`` sends one request; by default the task's
    grouping provider. Failures leave the utterance to the local rules.
    """
    if complete is None:
        from .ai_providers import provider_for_stage
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


def group_english_with_ai(segments, firered_tokens=(), provider_snapshot=None, *, complete=None) -> list[SubtitleCue]:
    answers = ai_breaks(segments, provider_snapshot, complete=complete) if (provider_snapshot or complete) else {}
    return group_english(segments, firered_tokens,
                         breaks_for=lambda segment, _tokens: answers.get(str(segment.segment_id)) or None)


def describe_rules() -> str:
    return normalize_spaces(__doc__.split("\n\n", 2)[1])
