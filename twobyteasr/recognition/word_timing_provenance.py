"""Distinguish measured token clocks from legacy and suspicious timings."""

import re


_NUMERIC_TOKEN = re.compile(r"(?:[0-9０-９零〇一二两兩三四五六七八九十百千万萬亿億][.,，．点點]?)+")


def suspicious_numeric_word(text, start, end):
    return end - start > 3.0 and bool(_NUMERIC_TOKEN.fullmatch(str(text).strip()))


def estimated_word_timing(row):
    arbitration = row.get('caption_arbitration') or {}
    if (arbitration.get('word_timing') or {}).get('basis') == 'uniform_display_estimate':
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
