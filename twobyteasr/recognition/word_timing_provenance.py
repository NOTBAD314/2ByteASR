"""Distinguish measured token clocks from legacy and suspicious timings."""

import re
from typing import NamedTuple


class WordClock(NamedTuple):
    start: str
    end: str


WEBSITE_ONSET = "website_onset"
WEBSITE_END = "website_end"
MODEL_TIME = "asr_model"
ALIGNED_TIME = "forced_alignment"
ACOUSTIC_TIME = "acoustic_refinement"
ESTIMATED_TIME = "estimated"
UNVERIFIED_TIME = "unverified"
MANUAL_TIME = "manual_locked"


_NUMERIC_TOKEN = re.compile(r"(?:[0-9０-９零〇一二两兩三四五六七八九十百千万萬亿億][.,，．点點]?)+")


def suspicious_numeric_word(text, start, end):
    return end - start > 3.0 and bool(_NUMERIC_TOKEN.fullmatch(str(text).strip()))


def estimated_word_timing(row):
    arbitration = row.get('caption_arbitration') or {}
    if (arbitration.get('word_timing') or {}).get('basis') in {'uniform_display_estimate', 'unavailable'}:
        return True
    if (arbitration.get('timing_degradation') or {}).get('display_estimates'):
        return True
    # Legacy MOSS builds distributed every character over the sentence before
    # assigning FireRed's *sentence* endpoints as final_timing_owner. Confirm
    # the producer and exact distribution, not merely an equal pair of words.
    words = row.get('words') or []
    if not str(row.get('primary_source', '')).startswith('moss') or len(words) < 4:
        return False
    if (arbitration.get('timing_evidence') or {}).get('independent_acoustic') is not False:
        return False
    def ms(word, key):
        return float(word[key+'_ms']) if key+'_ms' in word else float(word[key])*1000
    try:
        a, b = ms(words[0], 'start'), ms(words[-1], 'end')
        step = (b-a)/len(words)
        return all(abs(ms(w,'start')-(a+i*step)) <= 2 and abs(ms(w,'end')-(a+(i+1)*step)) <= 2
                   for i,w in enumerate(words))
    except (KeyError, TypeError, ValueError):
        return False


def word_clock(row, *, site_start=False, site_end=False, forced=False, manual=False):
    """Classify the source of both edges independently of a usable cue boundary."""
    if manual:
        return WordClock(MANUAL_TIME, MANUAL_TIME)
    if site_start or row.get("link_source"):
        return WordClock(WEBSITE_ONSET, WEBSITE_END if site_end else ESTIMATED_TIME)
    arbitration = row.get("caption_arbitration") or {}
    if row.get("acoustic_word_observation") or arbitration.get("acoustic_boundary_refinement"):
        return WordClock(ACOUSTIC_TIME, ACOUSTIC_TIME)
    if forced or row.get("cue_alignment"):
        return WordClock(ALIGNED_TIME, ALIGNED_TIME)
    timing = arbitration.get("word_timing") or {}
    if timing.get("basis") == "unavailable":
        return WordClock(UNVERIFIED_TIME, UNVERIFIED_TIME)
    if estimated_word_timing(row):
        return WordClock(ESTIMATED_TIME, ESTIMATED_TIME)
    if row.get("primary_source") and (row.get("words") or arbitration.get("acoustic_words")):
        return WordClock(MODEL_TIME, MODEL_TIME)
    return WordClock(UNVERIFIED_TIME, UNVERIFIED_TIME)


def caption_word_clocks(project, cue):
    from .cue_word_alignment import DOWNLOADED_WORD_ONSETS, cue_words
    from ..timeline.studio_caption_timeline import KEY
    words, reason = cue_words(project, cue, allow_realign=False)
    receipt = (project.studio_state.get(KEY) or {}).get("instances", {}).get(cue.id, {})
    explicit_ends = {(anchor["start_ms"], anchor.get("end_ms"))
                     for anchor in receipt.get("segment_anchors", ())
                     if anchor.get("precision") == "segment_interval"}
    return [(word, word_clock(project.asr_evidence.get(word.evidence_ref, {}),
                             site_start=reason == DOWNLOADED_WORD_ONSETS,
                             site_end=(word.start_ms, word.end_ms) in explicit_ends,
                             forced=word.evidence_ref.startswith("realign:"))) for word in words]
