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
4. A subtitle shows up to two lines of 42 characters (spaces included), so an
   utterance of up to 84 characters and 7 seconds stays whole (2026-10-21; it
   was one line of 42 before, which chopped sentences into scraps); a longer
   one is split into pieces of about 60; avoid a piece of one or two short
   words when a balanced split exists.

Timing comes from the aligner's words when they can be matched to the text
(Qwen3-ForcedAligner in English); otherwise it is shared out by characters
inside the utterance and the final per-caption alignment measures it. An
aligner word timed outside its own utterance is not used (2026-10-21, real
Russian clip: one word stretched 0.2 s past the sentence end, the cut landed
outside the sentence and the whole grouping stage failed its source check).

The optional AI pass sends numbered words and gets back only the indexes after
which to break, so it can never change a word; anything invalid, a break after
a word that must not end a line, or more pieces than these local rules need,
falls back to the local rules. Every utterance's pieces are checked against
the source contract before they are returned; one that fails stays a single
subtitle with a review note instead of failing the whole stage.

2026-10-19: Spanish, German, French, Portuguese, Italian and Russian use the
same breaker with their own word lists (european_text.Lexicon, passed as
``lexicon``); English stays the default and behaves exactly as before.
"""
from __future__ import annotations

import difflib
import json
import math
import time
import re
from statistics import median

from . import european_text
from .english_text import RULES, display_length, join, normalize_spaces, word_core, words as split_words
from .european_text import Lexicon
from .grouping_request import (
    ENGLISH_GROUPING_PROMPT_VERSION, compose_grouping_prompt, english_grouping_system_prompt, grouping_prompt_key,
)
from ..recognition.transcript_data import SubtitleCue

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
ENGLISH = Lexicon("en", "English", frozenset(CONJUNCTIONS), frozenset(PREPOSITIONS), frozenset(DETERMINERS),
                  frozenset(AUXILIARIES), frozenset(SUBJECTS), frozenset(NEGATIONS), frozenset(UNIT_WORDS),
                  possessives=frozenset({"'s", "s"}), negation_after_verb=True, rules=RULES)

# Short expressions whose meaning is damaged by a cue boundary. These are
# case-insensitive whole words and never bridge punctuation or speaker turns.
PROTECTED_ENGLISH_PHRASES = (
    ('set', 'up'), ('going', 'to'), ('talk', 'to', 'you'),
    ('color', 'space'), ('colour', 'space'), ('timeline', 'color', 'space'),
    ('davinci', 'resolve'), ('davinci', 'wide', 'gamut'),
    ('resolve', 'color', 'management'),
)


def _tools(lexicon):
    """(word core, display length, split, join) for a lexicon's language."""
    if lexicon is None or lexicon.code == "en":
        return word_core, display_length, split_words, join
    return european_text.word_core, european_text.display_length, european_text.words, european_text.join


def _capitalised(word: str, lexicon=None) -> bool:
    """A name-like word (Capitalised; the pronoun I and its contractions do not count)."""
    lex = lexicon or ENGLISH
    core = re.sub(r"^[\"'“‘(\[¿¡«]+", "", word)
    return bool(core) and core[0].isupper() and _tools(lex)[0](core) not in lex.subjects | lex.auxiliaries


def break_scores(tokens: list[str], gaps: list[float] | None = None, lexicon=None) -> list[float]:
    """Score for breaking after token i (higher is better; very negative is forbidden)."""
    lex = lexicon or ENGLISH
    core_of = _tools(lex)[0]
    scores = []
    gaps = gaps or [0.0] * max(0, len(tokens) - 1)
    protected = set()
    if lex.code == 'en':
        cores = [core_of(token) for token in tokens]
        for phrase in PROTECTED_ENGLISH_PHRASES:
            for start in range(len(tokens) - len(phrase) + 1):
                if tuple(cores[start:start + len(phrase)]) != phrase:
                    continue
                # A sentence/clause mark is stronger evidence than a phrase
                # string that happens to occur across it.
                if any(SENTENCE_END.search(tokens[i]) or CLAUSE_END.search(tokens[i])
                       for i in range(start, start + len(phrase) - 1)):
                    continue
                protected.update(range(start, start + len(phrase) - 1))
    for index in range(len(tokens) - 1):
        left, right = tokens[index], tokens[index + 1]
        left_core, right_core = core_of(left), core_of(right)
        score = 0.0
        if SENTENCE_END.search(left):
            score += 100
        elif CLAUSE_END.search(left):
            score += 60
        if right_core in lex.conjunctions:
            score += 40
        elif right_core in lex.prepositions:
            score += 15
        pause = gaps[index] if index < len(gaps) else 0.0
        if pause >= 0.35:
            score += 50
        elif pause >= 0.2:
            score += 20
        if not SENTENCE_END.search(left) and not CLAUSE_END.search(left):
            if left_core in lex.determiners:
                score -= 90
            elif left_core in lex.prepositions or left_core in lex.conjunctions:
                score -= 45
            elif left_core in lex.negations or (left_core in lex.auxiliaries and not (
                    # German closes a clause on its auxiliary: "… geschafft haben | und ehrlich gesagt …".
                    lex.clause_final_auxiliaries and right_core in lex.conjunctions)):
                score -= 40
            elif left_core in lex.subjects:
                score -= 35
            if _NUMBER.match(left_core or left) and (right_core in lex.unit_words or right_core.isalpha()):
                score -= 70
            if lex.negation_after_verb and (right_core in lex.negations or right_core.startswith("n't")):
                score -= 50
            if (lex.names_by_case and _capitalised(left, lex) and _capitalised(right, lex) and index > 0
                    and not SENTENCE_END.search(tokens[index - 1])):
                score -= 60
            if right_core in lex.possessives:
                score -= 80
            if lex.clause_final_auxiliaries and right_core in lex.auxiliaries:
                score -= 60
        scores.append(-1000.0 if index in protected else score)
    return scores


def split_tokens(tokens: list[str], gaps: list[float] | None = None, *, durations: list[float] | None = None,
                 rules=None, lexicon=None, source_text=None) -> list[tuple[int, int]]:
    """Best split of ``tokens`` into (start, end) ranges, end exclusive."""
    lex = lexicon or ENGLISH
    rules = rules or lex.rules
    length_of = _tools(lex)[1]
    count = len(tokens)
    if count == 0:
        return []
    from .segmentation_profiles import profile_for,word_spans
    forced=[i+1 for i,gap in enumerate(gaps or ()) if gap>=profile_for(lex.code).long_pause_seconds]
    raw_spans=word_spans(source_text) if source_text is not None else []
    def raw(first,last):
        return source_text[raw_spans[first][0]:raw_spans[last-1][1]] if len(raw_spans)==count else ' '.join(tokens[first:last])
    if forced:
        edges=[0,*forced,count];pieces=[]
        for a,b in zip(edges,edges[1:]):
            pieces.extend((a+x,a+y) for x,y in split_tokens(tokens[a:b],(gaps or [])[a:b-1],
                durations=durations[a:b] if durations is not None else None,rules=rules,lexicon=lex,source_text=raw(a,b)))
        return pieces
    if length_of(raw(0,count)) <= rules.cue_max_chars and (durations is None or sum(durations) <= rules.max_seconds):
        return [(0, count)]
    scores = break_scores(tokens, gaps, lex)
    lengths = [length_of(token) for token in tokens]

    def piece_cost(start, end):
        length = length_of(raw(start,end))
        if length > rules.cue_max_chars and end - start > 1:
            return None
        seconds = sum(durations[start:end]) if durations else 0.0
        # Every extra subtitle costs about what a conjunction break earns, so only a sentence end, a
        # comma or a real pause pays for one (2026-10-21: whole sentences, not scraps); short scraps cost more.
        cost = 40 + abs(length - rules.cue_preferred_chars) * 0.5
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
MIN_SECONDS_PER_LETTER = 0.02
# The grouping source contract lets a cue start or end this far outside its utterance.
SOURCE_TIME_TOLERANCE = 0.05


def _word_times(segment, tokens: list[str], aligned: list[dict], core=word_core, *, measured_endpoints=False) -> list[tuple[float, float] | None]:
    """Each token's (start, end) from aligner words matched by spelling, else None."""
    pool = [row for row in aligned if float(row.get("end", 0)) > segment.start - 0.3
            and float(row.get("start", 0)) < segment.end + 0.3 and core(row.get("text", ""))]
    if not pool:
        return [None] * len(tokens)
    left = [core(token) for token in tokens]
    right = [core(row.get("text", "")) for row in pool]
    times: list[tuple[float, float] | None] = [None] * len(tokens)
    first, last = float(segment.start), float(segment.end)
    matcher = difflib.SequenceMatcher(a=left, b=right, autojunk=False)
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            row = pool[block.b + offset]
            start, end = float(row["start"]), float(row["end"])
            # 2026-10-19 (real Russian clip): on garbled text the aligner can squeeze
            # several words into a few milliseconds, which left a one-frame subtitle.
            # Faster than 20 ms a letter is not speech: share it out like unmeasured words.
            minimum = .02 if measured_endpoints else MIN_SECONDS_PER_LETTER * max(1, len(left[block.a + offset]))
            if end - start < minimum:
                continue
            # 2026-10-21 (real Russian clip): the aligner hears 0.3 s on either side of the
            # utterance and stretched "дом" 0.2 s past its end; a cut placed from it left the
            # sentence. Word evidence cannot widen the sentence: such a word is unmeasured.
            if start < first - SOURCE_TIME_TOLERANCE or end > last + SOURCE_TIME_TOLERANCE:
                continue
            start = min(max(start, first), last)
            times[block.a + offset] = (start, max(start, min(end, last)))
    return times


def _fill_times(segment, tokens: list[str], times):
    """Measured times kept; the rest shared out by characters between their neighbours, inside the utterance."""
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
        high = min(max(high, low + 0.02 * (run_end - index)), max(low, end))
        total = sum(weights[index:run_end])
        cursor = low
        for position in range(index, run_end):
            span = (high - low) * weights[position] / total
            filled[position] = (cursor, cursor + span)
            cursor += span
        index = run_end
    return filled


def _english_evidence(segment, tokens, aligned):
    arbitration = getattr(segment, "caption_arbitration", {})
    if (arbitration.get("edited_text_alignment") or {}).get("status") == "pending":
        return [None] * len(tokens)
    measured = (arbitration.get("word_timing") or {}).get("measured_words")
    if not measured:
        measured = arbitration.get("acoustic_words")
    if measured:
        aligned = [dict(row, start=row["start_ms"] / 1000, end=row["end_ms"] / 1000)
                   for row in measured]
    else:
        job = (arbitration.get("forced_alignment_window") or {}).get("job")
        aligned = [row for row in aligned
                   if not row.get("alignment_key") or (job and row["alignment_key"] == job)]
    measured_rows = [row for row in aligned
                     if row.get("start_basis", "model") == row.get("end_basis", "model") == "model"
                     and math.isfinite(float(row["start"]) + float(row["end"]))]
    return _word_times(segment, tokens, measured_rows, measured_endpoints=True)


def _measured_gaps(times):
    return {index: round((right[0] - left[1]) * 1000)
            for index, (left, right) in enumerate(zip(times, times[1:]))
            if left is not None and right is not None and left[1] <= right[0]}


def _vad_gap_activity(times, gaps, regions):
    if not regions:
        return {}
    active = {}
    for index, gap in gaps.items():
        if gap < 150:
            continue
        left, right = times[index][1], times[index + 1][0]
        active[index] = min(gap, round(1000 * sum(
            max(0, min(right, row["end"]) - max(left, row["start"])) for row in regions
            if row["start"] < right and left < row["end"])))
    return active


def _english_request(segment, aligned, regions=()):
    from .segmentation_profiles import word_spans
    tokens = [span[2] for span in word_spans(segment.text)]
    times = _english_evidence(segment, tokens, aligned)
    gaps = _measured_gaps(times)
    vad = _vad_gap_activity(times, gaps, regions)
    word_durations = [end - start for interval in times if interval is not None for start, end in [interval]]
    threshold = max(950, min(1450, round(350 + 2600 * median(word_durations)))) if word_durations else 1100
    quiet_gaps = {index: gap - vad.get(index, 0) for index, gap in gaps.items()}
    scores = break_scores(tokens, [quiet_gaps.get(i, 0) / 1000 for i in range(len(tokens) - 1)])
    required = [index for index, gap in quiet_gaps.items() if gap >= threshold and scores[index] > -1000]
    allowed = [i for i in gaps if scores[i] > FORBIDDEN_BREAK or i in required]
    return tokens, times, gaps, required, allowed, vad


def group_english(segments, firered_tokens=(), *, breaks_for=None, lexicon=None,
                  ai_only=False, timing_evidence=None) -> list[SubtitleCue]:
    """English cues from recognizer utterances: one per utterance, long ones split by the rules.

    ``breaks_for(segment, tokens)`` may return break indexes for one utterance
    (the AI pass); invalid answers fall back to :func:`split_tokens`.
    ``lexicon`` selects another spaced language's word lists (2026-10-19).
    """
    lex = lexicon or ENGLISH
    core_of, length_of, split_of, join_of = _tools(lex)
    cues: list[SubtitleCue] = []
    aligned = [row for row in (firered_tokens or ()) if isinstance(row, dict)]
    for segment in sorted(segments, key=lambda item: (item.start, item.end, item.segment_id)):
        from .segmentation_profiles import word_spans,slice_word_pieces,task_language_tag
        raw_spans=word_spans(segment.text)
        tokens=[part[2] for part in raw_spans]
        if not tokens:
            continue
        measured_times = (timing_evidence[str(segment.segment_id)][1] if timing_evidence is not None
                          else _english_evidence(segment, tokens, aligned) if lex.code == 'en'
                          else _word_times(segment, tokens, aligned, core_of))
        measured_mask=[t is not None for t in measured_times]
        times = _fill_times(segment, tokens, measured_times)
        gaps = [max(0.0, times[i + 1][0] - times[i][1]) for i in range(len(tokens) - 1)]
        durations = [max(0.0, end - start) for start, end in times]
        status = 'source_unchanged_short'
        piece_origins = None
        pieces = [(0, len(tokens))] if ai_only else split_tokens(tokens, gaps, durations=durations, lexicon=lex, source_text=segment.text)
        if timing_evidence is not None:
            _, _, _, required, allowed, _ = timing_evidence[str(segment.segment_id)]
            needs_break = (bool(required) or length_of(segment.text) > lex.rules.cue_max_chars
                           or segment.end - segment.start > lex.rules.max_seconds)
            if needs_break:
                answer = breaks_for(segment, tokens) if breaks_for is not None else None
                if _valid_english_breaks(tokens, measured_times, required, allowed, answer):
                    edges = [0, *(index + 1 for index in answer), len(tokens)]
                    pieces = list(zip(edges, edges[1:]))
                    status = 'ai_accepted'

                    def can_join(first, last, cut):
                        start, end = measured_times[first], measured_times[last - 1]
                        return cut not in required and (start is not None and end is not None
                                                       and end[1] - start[0] <= RULES.max_seconds)

                    pieces, changed = join_orphan_words(pieces, tokens, length_of=length_of,
                                                        max_chars=RULES.cue_max_chars, can_join=can_join)
                    if changed:
                        piece_origins = ['local_orphan_join' if last in changed else status for _, last in pieces]
                elif required:
                    edges = [0, *(index + 1 for index in sorted(required)), len(tokens)]
                    pieces = list(zip(edges, edges[1:]))
                    status = 'local_measured_pause_fallback'
                else:
                    local = split_tokens(tokens, gaps, durations=durations, lexicon=lex, source_text=segment.text)
                    local_breaks = [last - 1 for _, last in local[:-1]]
                    if _valid_english_breaks(tokens, measured_times, required, allowed, local_breaks):
                        pieces = local
                        status = 'local_fallback_split'
                    else:
                        status = 'unresolved'
                        _note_sentence_kept(segment, 'no_accepted_measured_boundary')
        elif breaks_for is not None and length_of(segment.text) > lex.rules.cue_max_chars:
            raw_breaks = breaks_for(segment, tokens)
            answer = pieces_from_breaks(tokens, raw_breaks, lexicon=lex, gaps=gaps, strict=ai_only)
            from .segmentation_profiles import profile_for as _profile_for
            repaired = None if answer or not ai_only else ai_pieces_with_local_repair(
                tokens, raw_breaks, scores=break_scores(tokens, gaps, lex),
                forced={i for i, gap in enumerate(gaps) if gap >= _profile_for(lex.code).long_pause_seconds},
                length_of=length_of, max_chars=lex.rules.cue_max_chars,
                local_split=lambda a, b: split_tokens(tokens[a:b], gaps[a:b - 1], durations=durations[a:b],
                                                      lexicon=lex, source_text=' '.join(tokens[a:b])))
            if answer and (ai_only or len(answer) <= len(pieces)):
                pieces = answer
                status = 'ai_accepted'
            elif repaired:
                pieces, piece_origins = repaired
                status = 'ai_accepted' if set(piece_origins) == {'ai_accepted'} else 'local_fallback_split'
            if ai_only and status in ('ai_accepted', 'local_fallback_split') and len(pieces) > 1:
                joined, changed = join_orphan_words(pieces, tokens, length_of=length_of, max_chars=lex.rules.cue_max_chars)
                if changed:
                    before = dict(zip((b for a, b in pieces), piece_origins or [status] * len(pieces)))
                    pieces = joined
                    piece_origins = ['local_orphan_join' if b in changed else before.get(b, status) for a, b in pieces]
            if ai_only and status == 'source_unchanged_short':
                # 2026-11-25: an utterance the AI could not answer after its retry
                # is split by the local word rules instead of staying an over-long
                # line that fails the final length gate. Labelled local, never AI.
                local = split_tokens(tokens, gaps, durations=durations, lexicon=lex, source_text=segment.text)
                if local and len(local) > 1:
                    pieces = local
                    status = 'local_fallback_split'
                    from ..recognition.cache import record_run_event
                    record_run_event('word_grouping_local_fallback', language=lex.code,
                                     segment_id=getattr(segment, 'segment_id', None), pieces=len(local))
                else:
                    status = 'unresolved'
                    _note_sentence_kept(segment, 'ai_boundary_unresolved')
        locked, speaker = bool(getattr(segment, "timing_locked", False)), segment.speaker or "S00"
        own = []
        source_pieces=slice_word_pieces(segment.text,pieces)
        for (first,last),(char_start,char_end,raw_piece) in zip(pieces,source_pieces):
            cue_start = times[first][0] if first else float(segment.start)
            cue_end = times[last - 1][1] if last < len(tokens) else float(segment.end)
            own.append(SubtitleCue(0, round(cue_start, 3), round(max(cue_end, cue_start + 0.2), 3),
                                   raw_piece, locked, speaker))
            own[-1].source_spans=[dict(source_id=segment.segment_id,char_start=char_start,char_end=char_end,
                raw_text=raw_piece,index_unit='python_unicode_codepoint',source_time=[segment.start,segment.end])]
            own[-1].timing_basis='matched_word_evidence' if all(measured_mask[first:last]) else 'estimated_within_source_sentence'
            if timing_evidence is not None:
                if len(pieces) == 1:
                    own[-1].timing_basis = 'original_source_sentence'
                else:
                    _, _, actual_gaps, mandatory, _, vad = timing_evidence[str(segment.segment_id)]
                    receipt = {"source_id": segment.segment_id, "source": status,
                               "source_interval_ms": [round(cue_start * 1000), round(cue_end * 1000)]}
                    if first:
                        receipt["start_ms"] = round(cue_start * 1000)
                        receipt["preceding_gap_ms"] = actual_gaps[first - 1]
                    if last < len(tokens) and cue_end >= cue_start + .2 - 1e-8:
                        receipt["end_ms"] = round(cue_end * 1000)
                        receipt["following_gap_ms"] = actual_gaps[last - 1]
                        receipt["required_pause"] = last - 1 in mandatory
                        if last - 1 in vad:
                            receipt["following_vad_activity_ms"] = vad[last - 1]
                    own[-1].grouping_boundary_receipt = {"measured_english_break": receipt}
            tag=task_language_tag(lex.code)
            from .segmentation_profiles import profile_for
            own[-1].segmentation_language=tag if profile_for(tag).code==lex.code else lex.code
        if piece_origins and len(piece_origins) == len(own):
            for cue, origin in zip(own, piece_origins):
                cue._piece_origin = origin
        problem = _source_problem(segment, own)
        if problem:
            own = [SubtitleCue(0, round(float(segment.start), 3),
                               round(max(float(segment.end), float(segment.start) + 0.2), 3),
                               segment.text, locked, speaker)]
            _note_sentence_kept(segment, problem)
            own[0].source_spans=[dict(source_id=segment.segment_id,char_start=0,char_end=len(segment.text),raw_text=segment.text,
                index_unit='python_unicode_codepoint',source_time=[segment.start,segment.end])]
            own[0].timing_basis='original_source_sentence'
            own[0].segmentation_language=task_language_tag(lex.code)
        for cue in own:
            if ai_only:
                cue.grouping_origin = 'unresolved' if problem else getattr(cue, '_piece_origin', status)
            cue.cue_id = len(cues) + 1
            cues.append(cue)
    return cues


def _source_problem(segment, cues) -> str:
    """Why these pieces of one utterance would fail the grouping source contract ('' when they pass)."""
    from .grouping_contract import GroupingContractError, validate_grouping_result
    row = {"segment_id": 0, "start": segment.start, "end": segment.end, "text": segment.text,
           "speaker": segment.speaker or "S00"}
    try:
        # The undecorated check: the stage validates the whole result once and records it.
        validate_grouping_result.__wrapped__([row], cues)
    except GroupingContractError as error:
        return error.category
    except (TypeError, ValueError, AttributeError, KeyError) as error:
        return type(error).__name__
    return ""


def _note_sentence_kept(segment, problem: str) -> None:
    """One utterance stays a single subtitle: tell the user instead of failing the whole stage."""
    from subtitle_core import add_review_item
    from ..recognition.cache import record_run_event
    record_run_event("word_grouping_sentence_kept", segment_id=getattr(segment, "segment_id", None),
                     start=round(float(segment.start), 3), end=round(float(segment.end), 3), reason=problem)
    add_review_item(segment.start, "断句回退",
                    "这一句按单词切开后，文字或时间对不上原句，已保留为一整条字幕（原文和时间不变）；需要时可在这里手动拆开。",
                    segment.text, priority=3, severity="warning", reason=problem)


def drop_closing_break(tokens, breaks):
    """A break after the last word is the utterance end, not a cut (2026-11-25: Arabic and
    Hindi answers ended every list with it and every utterance was rejected)."""
    return [v for v in breaks if not (type(v) is int and v == len(tokens) - 1)]


def break_problem(tokens, breaks, *, length_of, max_chars, scores, preferred=None):
    """Why an answer is not usable, in words the model can act on; '' when it is."""
    if not isinstance(breaks, (list, tuple)):
        return 'breaks must be a list of word IDs'
    breaks = drop_closing_break(tokens, breaks)
    bad = [v for v in breaks if type(v) is not int or not 0 <= v < len(tokens) - 1]
    if bad:
        return f'word IDs {bad[:5]} are outside 0..{len(tokens) - 2}'
    hanging = [v for v in breaks if scores[v] <= FORBIDDEN_BREAK]
    if hanging:
        return 'a line may not end on ' + ', '.join(repr(tokens[v]) for v in hanging[:4])
    edges = [0] + [v + 1 for v in sorted(set(breaks))] + [len(tokens)]
    long = [(n + 1, length_of(' '.join(tokens[a:b]))) for n, (a, b) in enumerate(zip(edges, edges[1:]))
            if b - a > 1 and length_of(' '.join(tokens[a:b])) > max_chars]
    if long:
        return '; '.join(f'line {n} has {size} characters' for n, size in long) + f' (max {max_chars})'
    # 2026-11-25 (live Russian/German/Korean runs): a lone last word (…почти двойной | урон)
    # and runs of very short lines the limit would let stay together.
    pieces = list(zip(edges, edges[1:]))
    lines = [' '.join(tokens[a:b]) for a, b in pieces]
    for n, (a, b) in enumerate(pieces):
        if b - a != 1 or len(pieces) == 1:
            continue
        neighbour = n - 1 if n == len(pieces) - 1 or n > 0 and length_of(lines[n - 1]) <= length_of(lines[n + 1]) else n + 1
        if length_of(lines[min(n, neighbour)] + ' ' + lines[max(n, neighbour)]) <= max_chars:
            return f'line {n + 1} is the single word {tokens[a]!r}; join it with line {neighbour + 1}'
    if preferred:
        for n in range(len(lines) - 1):
            both = length_of(lines[n] + ' ' + lines[n + 1])
            if length_of(lines[n]) <= preferred / 2 and length_of(lines[n + 1]) <= preferred / 2 and both <= preferred:
                return (f'lines {n + 1} and {n + 2} are very short ({length_of(lines[n])} and {length_of(lines[n + 1])} '
                        f'characters); together they have {both}, within the preferred {preferred:g}: join them '
                        'unless they are separate sentences')
    return ''


def join_orphan_words(pieces, tokens, *, length_of, max_chars, can_join=None):
    """Lone single-word lines joined to the shorter neighbour when it fits; returns (pieces, changed ends)."""
    pieces = list(pieces)
    changed = set()
    n = 0
    while n < len(pieces) and len(pieces) > 1:
        a, b = pieces[n]
        if b - a == 1:
            options = [m for m in (n - 1, n + 1) if 0 <= m < len(pieces)]
            options.sort(key=lambda m: length_of(' '.join(tokens[pieces[m][0]:pieces[m][1]])))
            for m in options:
                left, right = min(pieces[n][0], pieces[m][0]), max(pieces[n][1], pieces[m][1])
                if can_join is not None and not can_join(left, right, pieces[min(n, m)][1] - 1):
                    continue
                if length_of(' '.join(tokens[left:right])) <= max_chars:
                    pieces[min(n, m)] = (left, right)
                    del pieces[max(n, m)]
                    changed.add(right)
                    n = -1
                    break
        n += 1
    return pieces, changed


def refine_long_lines(found, tokens_of, *, length_of, max_chars, scorer, ask, record=None, language='',
                      allowed_of=None):
    """Ask once more for only the lines that are still too long, each as its own short utterance.

    2026-11-25 (live English run, deepseek-v4-flash): with a 40-character limit the
    model kept good clause edges but could not count, also when given the lengths
    and the exact error. Each over-long line (45-59 characters) sent alone needs one
    cut, which it gets right. ``ask(batch) -> decoded answers``; returns the number
    of lines fixed. ``found`` is updated in place with the merged cuts.
    """
    from ..recognition.service import CancelledError

    work, sub_tokens, problems = [], {}, {}
    for key, breaks in list(found.items()):
        tokens = tokens_of.get(key)
        if not tokens or not isinstance(breaks, (list, tuple)):
            continue
        allowed = (allowed_of(key) if allowed_of is not None
                   else {i for i, score in enumerate(scorer(tokens)) if score > FORBIDDEN_BREAK})
        legal = sorted({v for v in drop_closing_break(tokens, breaks)
                        if type(v) is int and 0 <= v < len(tokens) - 1 and v in allowed})
        edges = [0] + [v + 1 for v in legal] + [len(tokens)]
        for n, (a, b) in enumerate(zip(edges, edges[1:]), 1):
            if b - a > 1 and length_of(' '.join(tokens[a:b])) > max_chars:
                sub = f'{key}~{n}'
                size = length_of(' '.join(tokens[a:b]))
                need = -(-size // max_chars)
                sub_tokens[sub] = (key, a, legal, need)
                problems[sub] = ([], f'this line has {size} characters (max {max_chars}); split it into {need} '
                                     f'lines of similar length at a clause or phrase edge, not more')
                work.append((sub, tokens[a:b]))
    if not work:
        return 0
    try:
        decoded = ask(work, problems)
    except CancelledError:
        raise
    except Exception as error:
        if record:
            record('word_grouping_line_repair', language=language, lines=len(work), fixed=0,
                   error=getattr(error, 'category', type(error).__name__))
        return 0
    fixed = 0
    merged = {}
    for sub, tokens in work:
        key, offset, legal, need = sub_tokens[sub]
        merged.setdefault(key, set(legal))
        answer = decoded.get(sub)
        if not isinstance(answer, (list, tuple)):
            continue
        allowed = ({i - offset for i in allowed_of(key)} if allowed_of is not None
                   else {i for i, score in enumerate(scorer(tokens)) if score > FORBIDDEN_BREAK})
        cuts = [v for v in drop_closing_break(tokens, answer) if type(v) is int and 0 <= v < len(tokens) - 1
                and v in allowed]
        edges = [0] + [v + 1 for v in sorted(set(cuts))] + [len(tokens)]
        if (cuts and len(cuts) + 1 <= need + 1
                and all(b - a == 1 or length_of(' '.join(tokens[a:b])) <= max_chars for a, b in zip(edges, edges[1:]))):
            merged[key] |= {offset + v for v in cuts}
            fixed += 1
    for key, cuts in merged.items():
        found[key] = sorted(cuts)
    if record:
        record('word_grouping_line_repair', language=language, lines=len(work), fixed=fixed)
    return fixed


def ai_pieces_with_local_repair(tokens, breaks, *, scores, forced, length_of, max_chars, local_split):
    """The AI's legal cuts, with only its still over-long lines split locally.

    Returns (pieces, origins) or None when the answer holds no legal cut at all.
    2026-11-25 (live English run): the model's cuts were good clause edges but
    every line was 45-59 characters for a 40 limit; the whole answer was thrown
    away. Its cuts now stay and only the long lines are split by the word rules.
    """
    if not isinstance(breaks, (list, tuple)):
        return None
    legal = {v for v in drop_closing_break(tokens, breaks) if type(v) is int and 0 <= v < len(tokens) - 1
             and (v in forced or scores[v] > FORBIDDEN_BREAK)} | set(forced)
    if not legal:
        return None
    edges = [0] + [v + 1 for v in sorted(legal)] + [len(tokens)]
    pieces, origins = [], []
    for a, b in zip(edges, edges[1:]):
        if b - a > 1 and length_of(' '.join(tokens[a:b])) > max_chars:
            inner = local_split(a, b) or [(0, b - a)]
            pieces.extend((a + x, a + y) for x, y in inner)
            origins.extend(['local_fallback_split'] * len(inner))
        else:
            pieces.append((a, b))
            origins.append('ai_accepted')
    return pieces, origins


# A break scoring this low leaves a line hanging on a word that needs the next one
# (a subject pronoun waiting for its verb scores -35, a preposition -45, an article -90).
FORBIDDEN_BREAK = -30


def pieces_from_breaks(tokens: list[str], breaks, lexicon=None, gaps=None, *, strict=False) -> list[tuple[int, int]] | None:
    """Ranges from 'break after word i' indexes.

    None when they are not valid, a piece is longer than one subtitle, or a
    break comes after a word that must not end a line (2026-10-21, real Italian
    clip: "per un piano con | due fessure", "delle due non | osservandole").
    """
    if not isinstance(breaks,(list,tuple)):
        return None
    breaks = drop_closing_break(tokens, breaks)
    lex = lexicon or ENGLISH
    from .segmentation_profiles import profile_for
    scores=break_scores(tokens,gaps,lex)
    forced={i for i,gap in enumerate(gaps or ()) if gap>=profile_for(lex.code).long_pause_seconds}
    accepted = {v for v in breaks if type(v) is int and 0 <= v < len(tokens)-1
                and (v in forced or scores[v] > FORBIDDEN_BREAK)}
    if strict and (len(accepted) != len(breaks) or not forced <= accepted):
        return None
    cuts = sorted(accepted if strict else forced | accepted)
    edges = [0] + [cut + 1 for cut in cuts] + [len(tokens)]
    pieces = [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]
    if any(_tools(lex)[1](" ".join(tokens[a:b])) > lex.rules.cue_max_chars and b - a > 1 for a, b in pieces):
        return None
    return pieces


# ---------------------------------------------------------------- the AI pass
# 2026-10-18: the prompt text lives in grouping_request (the rules part can be
# replaced by the user); this name keeps the built-in prompt. 2026-10-21: one
# subtitle holds two lines (cue_max_chars).
ENGLISH_GROUPING_SYSTEM_PROMPT = compose_grouping_prompt("en", RULES.cue_max_chars, RULES.max_seconds)


def _examples(words, count=8) -> str:
    return ", ".join(sorted(words)[:count])


def grouping_system_prompt(lexicon=None) -> str:
    """The English prompt (with the user's rules, 2026-10-18), or the same rules with
    another language's word lists (2026-10-19; not editable)."""
    lex = lexicon or ENGLISH
    from .grouping_request import word_grouping_system_prompt
    return word_grouping_system_prompt(lex.code)


def _legacy_word_guidance(lex):
    return f"""You split {lex.name} game-stream subtitles into readable lines.
You receive utterances as numbered words. Return ONLY JSON: {{"breaks": {{"<utterance id>": [word numbers]}}}}
where each number n means "a new subtitle starts after word n". Never change, add or remove words.
Rules:
1. A subtitle shows up to two lines: at most {lex.rules.cue_max_chars} characters including spaces, ideally about {lex.rules.cue_preferred_chars}; at most {lex.rules.max_seconds:g} seconds.
   Keep a whole sentence or clause in one subtitle whenever it fits; use as few subtitles as these limits allow.
2. Prefer breaking after . ! ? first, then after , ; : — , then before a conjunction or relative word ({_examples(lex.conjunctions)}), then before a preposition.
3. Never end a subtitle with an article or determiner ({_examples(lex.determiners)}), a preposition ({_examples(lex.prepositions)}), a conjunction, an auxiliary verb ({_examples(lex.auxiliaries)}), a subject pronoun waiting for its verb ({_examples(lex.subjects)}) or a negation ({_examples(lex.negations)}).
4. Never split a name, a number from its unit, or a negation from its verb.
5. Keep a short utterance whole; avoid one- or two-word pieces when a balanced split exists.
Utterances that already fit need no breaks: return [] for them."""


def grouping_prompt_version(lexicon=None) -> str:
    lex = lexicon or ENGLISH
    # v2: squeezed aligner words are shared out; v3: number words never end a line (2026-10-19);
    # v4 (English v2): two-line subtitles, checked AI breaks, word times kept inside the utterance (2026-10-21).
    # English: the built-in prompt keeps its version; the user's rules add a digest (2026-10-18).
    from .segmentation_profiles import task_language_tag,profile_for
    tag=task_language_tag(lex.code)
    if profile_for(tag).code!=lex.code:tag=lex.code
    return grouping_prompt_key(tag)


def _valid_english_breaks(tokens, times, required, allowed, breaks):
    if not isinstance(breaks, list) or not breaks or any(type(value) is not int for value in breaks):
        return False
    if breaks != sorted(set(breaks)) or not set(required) <= set(breaks) <= set(allowed):
        return False
    edges = [0, *(index + 1 for index in breaks), len(tokens)]
    for first, last in zip(edges, edges[1:]):
        if last - first > 1 and display_length(" ".join(tokens[first:last])) > RULES.cue_max_chars:
            return False
        start, end = times[first], times[last - 1]
        if start is not None and end is not None and end[1] - start[0] > RULES.max_seconds:
            return False
    return True


def build_ai_messages(batch: list[tuple[str, list[str]]], lexicon=None, problems=None, *, evidence=None, retry_ids=()) -> list[dict]:
    # 2026-11-25: characters_through_word[i] is the line length if a line ran from word 0
    # through word i, so the model reads lengths instead of counting them.
    length_of = _tools(lexicon or ENGLISH)[1]
    payload = [{"id": key, "words": {str(i): token for i, token in enumerate(tokens)},
                'allowed_break_after':[i for i,score in enumerate(break_scores(tokens,lexicon=lexicon)) if score>FORBIDDEN_BREAK],
                'characters_through_word':[length_of(' '.join(tokens[:i + 1])) for i in range(len(tokens))],
                **(dict(previous_breaks=problems[key][0], problem=problems[key][1]) if problems and key in problems else {})}
                for key, tokens in batch]
    if evidence is not None:
        for row in payload:
            _, _, gaps, required, allowed, vad = evidence[row["id"]]
            row.update(allowed_break_after=allowed, required_break_after=required, measured_gap_ms_after=gaps)
            if vad:
                row["speech_activity_ms_in_gap_after"] = vad
            if row["id"] in retry_ids:
                row["retry_reason"] = ("Previous response missing or invalid. Return sorted allowed IDs, "
                                       "including every required ID, and keep each subtitle within the limits.")
    return [{"role": "system", "content": grouping_system_prompt(lexicon)},
            {"role": "user", "content": json.dumps({"utterances": payload}, ensure_ascii=False)}]


class BreakAnswers(dict):
    partial = False


def parse_ai_breaks(content: str) -> dict[str, list[int]]:
    text = str(content or "").strip()
    start, end = text.find("{"), text.rfind("}")
    partial=False
    try:
        if start<0 or end<=start:raise json.JSONDecodeError('Incomplete boundary envelope',text,0)
        duplicates=[]
        def unique_pairs(pairs):
            counts={key:sum(k==key for k,v in pairs) for key,value in pairs}
            duplicates.extend(key for key,count in counts.items() if count>1)
            return {key:value for key,value in pairs if counts[key]==1}
        data=json.loads(text[start:end+1],object_pairs_hook=unique_pairs)
        partial=bool(duplicates)
    except json.JSONDecodeError:
        # Only fully closed integer arrays are recoverable from a truncated
        # word-boundary response. Known utterance IDs are checked by the caller.
        pairs=[]
        for match in re.finditer(r'"([^"\\]+)"\s*:\s*(\[[^\[\]]*\])',text):
            try:value=json.loads(match.group(2))
            except json.JSONDecodeError:continue
            if isinstance(value,list) and all(type(v) is int for v in value):
                pairs.append((match.group(1),value))
        counts={key:sum(k==key for k,v in pairs) for key,value in pairs}
        data={'breaks':{key:value for key,value in pairs if counts[key]==1}}
        partial=True
    breaks = data.get("breaks") if isinstance(data, dict) else None
    result=BreakAnswers({str(key):list(value) for key,value in breaks.items() if isinstance(value,list)}) if isinstance(breaks,dict) else BreakAnswers()
    result.partial=partial or not isinstance(breaks,dict)
    return result


def ai_breaks(segments, provider_snapshot, *, complete=None, lexicon=None, timing_evidence=None) -> dict:
    """Break indexes per long utterance from the grouping AI (one request per ~40 utterances).

    ``complete(messages) -> str`` sends one request; by default the task's
    grouping provider. Failures leave the utterance to the local rules.
    """
    if complete is None:
        from ..providers.ai_providers import provider_for_stage
        from .grouping import post_chat_completion
        provider = provider_for_stage(provider_snapshot.execution_settings(), "group", sender=post_chat_completion)

        def complete(messages):
            return provider.complete(messages, stage="grouped", operation_kind="group", max_tokens=provider_snapshot.max_output_tokens,
                                     temperature=0.0, timeout=provider_snapshot.timeout_policy.total,
                                     _timeout_policy=provider_snapshot.timeout_policy, enable_thinking=provider_snapshot.enable_thinking, thinking_protocol=provider_snapshot.thinking_protocol,
                                     response_format={"type": "json_object"})
    lex = lexicon or ENGLISH
    _core, length_of, split_of, _join = _tools(lex)
    if timing_evidence is not None:
        long = []
        for segment in segments:
            key = str(segment.segment_id)
            tokens, _, _, required, allowed, _ = timing_evidence[key]
            if allowed and (required or length_of(segment.text) > lex.rules.cue_max_chars
                            or segment.end - segment.start > lex.rules.max_seconds):
                long.append((key, tokens))
    else:
        long = [(str(segment.segment_id), split_of(segment.text)) for segment in segments
                if length_of(segment.text) > lex.rules.cue_max_chars and len(split_of(segment.text))>1
                and any(s>FORBIDDEN_BREAK for s in break_scores(split_of(segment.text),lexicon=lex))]
    found: dict = {}
    from ..recognition.cache import record_run_event
    from ..recognition.service import CancelledError
    for offset in range(0, len(long), 40):
        batch = long[offset:offset + 40]
        if timing_evidence is not None:
            found.update(_request_measured_breaks(batch, complete, lex, timing_evidence, offset // 40 + 1))
            continue
        # 2026-11-25: one failed request (429, broken JSON) used to leave all 40
        # utterances unanswered; a missing utterance was never asked again. Each
        # batch now gets one retry, and a second request carries only what is
        # still missing or invalid.
        pending = list(batch)
        failures = resent = 0
        problems = {}
        for attempt in (1, 2, 3):
            if not pending:
                break
            try:
                decoded = parse_ai_breaks(complete(build_ai_messages(pending, lex, problems)))
            except CancelledError:
                raise
            except Exception as error:
                record_run_event('word_grouping_batch_unresolved', language=lex.code, batch_index=offset//40+1,
                    attempt=attempt, source_ids=[key for key, tokens in pending],
                    reason=getattr(error, 'category', type(error).__name__),
                    action='retry_once' if not failures else 'local_word_rules')
                failures += 1
                if failures > 1:
                    break
                if failures == 1:
                    from ..providers.provider_input_budget import retry_delay
                    delay = retry_delay(error, 1)
                    if delay is None:
                        break
                    time.sleep(min(delay, 30.0))
                continue
            wanted = {key for key, tokens in pending}
            # Every answer is kept (group_english keeps its legal cuts even if the resend
            # fails); missing and failing utterances are asked again once.
            accepted = {key: value for key, value in decoded.items() if key in wanted}
            found.update(accepted)
            # 2026-11-25: an answer that would fail the line check is asked again once,
            # with the exact problem (which line, how long, the limit).
            tokens_of = dict(pending)
            problems = {}
            for key, value in accepted.items():
                problem = break_problem(tokens_of[key], value, length_of=length_of, max_chars=lex.rules.cue_max_chars,
                                        scores=break_scores(tokens_of[key], lexicon=lex),
                                        preferred=lex.rules.cue_preferred_chars)
                if problem:
                    problems[key] = (value, problem)
            accepted = {key: value for key, value in accepted.items() if key not in problems}
            record_run_event('word_grouping_batch', language=lex.code, prompt_version=grouping_prompt_version(lex),
                batch_index=offset//40+1, attempt=attempt, source_ids=sorted(wanted), received_ids=sorted(accepted),
                partial_response=bool(decoded.partial), source_retained_ids=sorted(wanted-set(accepted)))
            pending = [(key, tokens) for key, tokens in pending if key not in accepted]
            if pending and resent:
                break
            resent = bool(pending)
        refine_long_lines(found, dict(batch), length_of=length_of, max_chars=lex.rules.cue_max_chars,
                          scorer=lambda tokens: break_scores(tokens, lexicon=lex),
                          ask=lambda work, problems: parse_ai_breaks(complete(build_ai_messages(work, lex, problems))),
                          record=record_run_event, language=lex.code)
    return found


def _request_measured_breaks(batch, complete, lex, evidence, batch_index):
    from ..recognition.cache import record_run_event
    from ..recognition.service import CancelledError

    accepted = {}
    overlong = {}
    problems = {}
    remaining = batch
    for attempt in (1, 2):
        expected = [key for key, _ in remaining]
        try:
            messages = build_ai_messages(remaining, lex, problems, evidence=evidence,
                                         retry_ids=expected if attempt > 1 else ())
            decoded = parse_ai_breaks(complete(messages))
        except CancelledError:
            raise
        except Exception as error:
            record_run_event('word_grouping_batch_unresolved', language=lex.code, batch_index=batch_index,
                             attempt=attempt, source_ids=expected,
                             reason=getattr(error, 'category', type(error).__name__))
            if attempt == 1:
                from ..providers.provider_input_budget import retry_delay
                delay = retry_delay(error, 1)
                if delay is None:
                    break
                time.sleep(min(delay, 30.0))
            continue
        for key in expected:
            tokens, times, _, required, allowed, _ = evidence[key]
            answer = decoded.get(key)
            if answer is None:
                continue
            answer = drop_closing_break(tokens, answer)
            if any(type(index) is not int for index in answer):
                continue
            if answer != sorted(set(answer)) or not set(required) <= set(answer) <= set(allowed):
                continue
            if _valid_english_breaks(tokens, times, required, allowed, answer):
                accepted[key] = answer
                continue
            problem = break_problem(tokens, answer, length_of=display_length, max_chars=RULES.cue_max_chars,
                                    scores=[0 if i in allowed else FORBIDDEN_BREAK for i in range(len(tokens))])
            if problem.startswith('line ') and 'characters' in problem:
                overlong[key] = answer
            problems[key] = (answer, problem or 'Respect the measured times and the maximum cue duration.')
        remaining = [(key, tokens) for key, tokens in remaining if key not in accepted]
        record_run_event('word_grouping_batch', language=lex.code, batch_index=batch_index, attempt=attempt,
                         source_ids=expected, received_ids=[key for key in expected if key in decoded],
                         accepted_ids=[key for key in expected if key in accepted],
                         source_retained_ids=[key for key, _ in remaining],
                         partial_response=bool(decoded.partial))
        if not remaining:
            break

    def ask_slices(work, details):
        sliced = {}
        for sub, words in work:
            key, ordinal = sub.rsplit('~', 1)
            tokens, times, gaps, required, allowed, vad = evidence[key]
            first = ([0] + [index + 1 for index in overlong[key]])[int(ordinal) - 1]
            last = first + len(words)
            def inside(index):
                return first <= index < last - 1
            sliced[sub] = (words, times[first:last], {i - first: gap for i, gap in gaps.items() if inside(i)},
                           [i - first for i in required if inside(i)], [i - first for i in allowed if inside(i)],
                           {i - first: duration for i, duration in vad.items() if inside(i)})
        return parse_ai_breaks(complete(build_ai_messages(work, lex, details, evidence=sliced)))

    repairable = {key: value for key, value in overlong.items() if key not in accepted}
    refine_long_lines(repairable, dict(batch), length_of=display_length, max_chars=RULES.cue_max_chars,
                      scorer=break_scores, allowed_of=lambda key: evidence[key][4], ask=ask_slices,
                      record=record_run_event, language=lex.code)
    for key, answer in repairable.items():
        tokens, times, _, required, allowed, _ = evidence[key]
        if _valid_english_breaks(tokens, times, required, allowed, answer):
            accepted[key] = answer
    return accepted


def group_english_with_ai(segments, firered_tokens=(), provider_snapshot=None, *, complete=None,
                          lexicon=None, speech_regions=()) -> list[SubtitleCue]:
    segments = list(segments)
    firered_tokens = list(firered_tokens)
    vad_execution = getattr(speech_regions, "execution", {})
    regions = ([row for row in speech_regions if not row.get("processing_only")]
               if vad_execution.get("actual_backend") == "firered_vad" and not vad_execution.get("degraded") else [])
    evidence = ({str(segment.segment_id): _english_request(segment, firered_tokens, regions) for segment in segments}
                if (lexicon or ENGLISH).code == 'en' else None)
    answers = (ai_breaks(segments, provider_snapshot, complete=complete, lexicon=lexicon, timing_evidence=evidence)
               if (provider_snapshot or complete) else {})
    return group_english(segments, firered_tokens, lexicon=lexicon,
                         breaks_for=lambda segment, _tokens: answers.get(str(segment.segment_id)), ai_only=True,
                         timing_evidence=evidence)


def describe_rules() -> str:
    return normalize_spaces(__doc__.split("\n\n", 2)[1])
