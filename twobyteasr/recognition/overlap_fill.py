"""Words of a second voice that the primary transcript dropped under another line.

2026-11-20, reported jobs (streamer reacting to game trailers): MOSS Pro
diarizes one speaker at a time. While the trailer narrator talked for 40 s
the streamer's own lines were dropped (11 of 16 proofread lines in a 110 s
clip were typed by hand), yet FireRedASR2-AED, run beside it, wrote them
into its mixed transcript ("因为不歪所以导致很多常驻角色很难获取所以").
Speech coverage only checks *time*, and that time already had text, so the
gap fill never saw them.

A FireRed run becomes a candidate line when all of these hold:

- it is not matched (3+ character blocks) by the primary text;
- it lies under primary text of exactly one speaker. Where the primary
  already has two speakers at that moment it did separate the overlap, and
  FireRed's extra words were, in the zero-change job, garbles of the mix;
- the primary nearby does not contain most of it (reordered overlapping
  rows) and FireRed did not just say it (window seams);
- it does not sound like what the primary says there (pinyin, digits read
  as Chinese): a misheard copy of the same line is not a second voice.

Rows keep FireRed's character times, the gap-fill row source (so a language
discard removes them too) and one speaker label, and each one is a
"listen and confirm" review item.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from twobyteasr.recognition.speech_coverage import FILL_ROW_SOURCE, _usable_tokens

# A recovery label: kept by the host-only filters and left out of voice
# clustering, like the gap fill's RECOVERY_<sample>_FIRERED rows. One label
# for all of them, so renaming it once names the second voice.
SPEAKER = 'RECOVERY_OVERLAP_FIRERED'
MIN_CHARS = 4          # 先是小玉 in the reported job
MATCH_BLOCK = 3        # shorter common blocks are chance (的、一个)
PRESENT_SHARE = .6
SOUND_ALIKE = .6       # true runs scored .35–.55, misheard copies .64+
CONTEXT_SECONDS = 3.0
WINDOW_SECONDS = 120.0
WINDOW_MARGIN = 10.0
_DIGITS = dict(zip('0123456789', '零一二三四五六七八九'))
_CONTENT = re.compile(r'[0-9A-Za-z㐀-鿿]')


def _chars(rows):
    return [(char.lower(), index) for index, row in enumerate(rows)
            for char in str(row.get('text') or '') if _CONTENT.match(char)]


def _spoken(text):
    from twobyteasr.subtitle_rules.text_similarity import phonetic_text
    return phonetic_text(''.join(_DIGITS.get(c, c) for c in str(text)))


def _spoken_values(text):
    """Digits read as a number (150 → 一百五十), as people say them."""
    from twobyteasr.subtitle_rules.text_rules import _arabic_integer_to_chinese
    return _spoken(re.sub(r'\d+', lambda m: _arabic_integer_to_chinese(m.group()), str(text)))


def _sounds_like(run, reference):
    """Best match of ``run`` anywhere inside ``reference`` (free ends), 0..1.

    2026-11-22 (user, 1 h stream): the primary's 150 against FireRed's
    一百五十 scored low when digits were read one by one (一五零) and became a
    "second voice". Both readings of the reference are tried.
    """
    score = _sounds_like_text(_spoken(run), _spoken(reference))
    if re.search(r'\d', str(reference)) or re.search(r'\d', str(run)):
        score = max(score, _sounds_like_text(_spoken_values(run), _spoken_values(reference)))
    return score


def _sounds_like_text(query, ref):
    if not query:
        return 1.0
    if not ref:
        return 0.0
    previous = [0] * (len(ref) + 1)
    for i, left in enumerate(query, 1):
        current = [i] + [0] * len(ref)
        for j, right in enumerate(ref, 1):
            current[j] = min(previous[j] + 1, current[j-1] + 1, previous[j-1] + (left != right))
        previous = current
    return 1 - min(previous) / len(query)


def _common(run, text):
    if not run or not text:
        return 0
    return SequenceMatcher(None, run, text, autojunk=False).find_longest_match(0, len(run), 0, len(text)).size


def _rows_between(rows, start, end):
    return [row for row in rows if float(row['start']) < end and float(row['end']) > start]


def _content_text(rows):
    return ''.join(c for c, _ in _chars(rows))


def _runs(rows, tokens):
    """Unmatched FireRed character runs as (first, last) token indices."""
    primary = _content_text(rows)
    chars = _chars(tokens)
    heard = ''.join(c for c, _ in chars)
    blocks = [b for b in SequenceMatcher(None, heard, primary, autojunk=False).get_matching_blocks()
              if b.size >= MATCH_BLOCK]
    cursor, result = 0, []
    for block in [*blocks, None]:
        stop = block.a if block else len(heard)
        if stop - cursor >= MIN_CHARS:
            result.append((chars[cursor][1], chars[stop-1][1]))
        if block:
            cursor = block.a + block.size
    return result


def _candidate(rows, tokens, first, last):
    part = tokens[first:last+1]
    start, end = part[0]['start'], max(t['end'] for t in part)
    if any(b['start'] < a['start'] for a, b in zip(part, part[1:])) or end <= start:
        return None, 'window_seam'
    if any(b['start'] - a['end'] > 2 for a, b in zip(part, part[1:])):
        return None, 'unsupported_acoustic_gap'
    text = ''.join(t['text'] for t in part)
    if len(text) > 80 and len(text) / (end-start) > 20:
        return None, 'unsupported_character_rate'
    run = _content_text([dict(text=text)])
    # Gap-fill rows are FireRed's own words, not a primary speaker.
    covering = [r for r in _rows_between(rows, start, end) if r.get('source') != FILL_ROW_SOURCE]
    if not covering:
        return None, 'not_under_primary'   # the gap fill owns uncovered speech
    if len({str(r.get('speaker') or '') for r in covering}) != 1:
        return None, 'primary_has_both_voices'
    nearby = _content_text(_rows_between(rows, start-CONTEXT_SECONDS, end+CONTEXT_SECONDS))
    just_said = _content_text([t for t in tokens[:first] if t['start'] >= start-4])
    if max(_common(run, nearby), _common(run, just_said)) >= PRESENT_SHARE * len(run):
        return None, 'already_present'
    same_time = ''.join(str(r.get('text') or '') for r in _rows_between(rows, start-1, end+1))
    score = _sounds_like(run, same_time)
    if score >= SOUND_ALIKE:
        return None, 'misheard_primary'
    return dict(text=text, start=round(start, 3), end=round(end, 3), speaker=SPEAKER, confidence=.6,
                source=FILL_ROW_SOURCE, fill_kind='overlap', timestamp_source='firered_aed_characters',
                overlap_evidence=dict(primary_speaker=str(covering[0].get('speaker') or ''),
                                      sounds_like_primary=round(score, 3))), ''


def find_overlap_rows(rows, tokens):
    """Candidate rows plus counts of the runs that were rejected and why."""
    tokens = _usable_tokens(tokens)
    rows = sorted((r for r in rows if str(r.get('text') or '').strip()),
                  key=lambda r: (float(r['start']), float(r['end'])))
    if not tokens or not rows:
        return [], {}
    found, rejected, seen = [], {}, set()
    low, last_end = tokens[0]['start'], max(t['end'] for t in tokens)
    while low < last_end:
        high = low + WINDOW_SECONDS
        window = [t for t in tokens if low-WINDOW_MARGIN <= t['start'] < high+WINDOW_MARGIN]
        primary = _rows_between(rows, low-WINDOW_MARGIN, high+WINDOW_MARGIN)
        for first, last in _runs(primary, window):
            if not low <= window[first]['start'] < high:
                continue
            row, reason = _candidate(primary, window, first, last)
            if row is None:
                rejected[reason] = rejected.get(reason, 0) + 1
            elif (row['start'], row['text']) not in seen:
                seen.add((row['start'], row['text']))
                found.append(row)
        low = high
    return found, rejected


def add_overlap_rows(state, payload, tokens, legacy=None, *, insert=True):
    """Append candidate rows to the primary payload and record them on the coverage state.

    ``insert=False`` (2026-11-22, speakers turned off): one lane cannot hold a
    second voice over its own line, so the rows stay out of the subtitles and
    their text goes to the review list only.
    """
    rows, rejected = find_overlap_rows(payload.get('segments', []), tokens)
    if state is not None:
        state['overlap_fill'] = dict(rows=[dict(start=r['start'], end=r['end'], characters=len(_content_text([r])),
                                                primary_speaker=r['overlap_evidence']['primary_speaker'],
                                                **({} if insert else dict(text=r['text'], inserted=False)))
                                           for r in rows],
                                     rejected=rejected, review='listen_and_confirm')
    if legacy is not None:
        legacy.record_run_event('overlap_speech_fill', rows=len(rows), rejected=rejected, inserted=bool(insert),
                                characters=sum(len(_content_text([r])) for r in rows))
    if rows and insert:
        payload['segments'] = sorted([*payload.get('segments', []), *rows],
                                     key=lambda r: (float(r['start']), float(r['end'])))
        payload.setdefault('references', []).extend(dict(r) for r in rows)
    return rows
