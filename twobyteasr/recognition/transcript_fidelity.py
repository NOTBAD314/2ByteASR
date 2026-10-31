"""Map measured provider pieces onto the transcript, without inventing spaces.

The transcript owns spelling and word boundaries. A timing token can be a
subword, punctuation or several words; its existence never proves a word break.
"""
from __future__ import annotations
import unicodedata

RULE_VERSION = 'provider-transcript-spans-v1'


def clean_transcript(text):
    """Preserve Latin punctuation even before automatic language detection.

    Cloud workers may not yet have a task language; default Chinese display
    rules must not erase commas/periods from a foreign transcript.
    """
    text = str(text or '')
    latin = sum('LATIN' in unicodedata.name(c, '') for c in text)
    letters = sum(c.isalpha() for c in text)
    if latin and latin >= letters / 2:
        return ' '.join(text.split())
    from ..subtitle_rules.text_rules import clean_subtitle_text
    return clean_subtitle_text(text)


def transcript_spans(text, pieces):
    """Original character spans, only for a complete exact content mapping.

    NFKC maps width/combining representations; accents, case and apostrophes
    remain significant. Failure grants no permission to rewrite the transcript.
    """
    from ..forced_alignment import content_char_map
    source = content_char_map(str(text))
    cursor, spans = 0, []
    for piece in pieces:
        chars = content_char_map(str(piece))
        size = len(chars)
        if not size:
            spans.append(None)
            continue
        part = source[cursor:cursor + size]
        if [c[0] for c in chars] != [c[0] for c in part]:
            return None
        spans.append((part[0][1], part[-1][2]))
        cursor += size
    return spans if cursor == len(source) else None


def word_tokens(text, tokens):
    """Keep measured bounds, merge subpieces inside an original word.

    No timing interpolation. Ambiguous/missing text yields no fine timing.
    Callers retain the original sentence and its coarse measured interval.
    """
    spans = transcript_spans(text, [t.get('text', t.get('word', '')) for t in tokens])
    if spans is None:
        return []
    result = []
    for token, span in zip(tokens, spans):
        if span is None:
            continue
        a, b = span
        row = {**token, 'text': text[a:b], 'char_start': a, 'char_end': b}
        if result:
            previous = result[-1]
            gap = text[previous['char_end']:a]
            left, right = text[a - 1:a], text[a:a + 1]
            def spaced(char):
                return char in "'’" or char.isdigit() or any(
                    script in unicodedata.name(char, '') for script in ('LATIN', 'CYRILLIC', 'GREEK', 'HANGUL'))
            if not gap and left and right and spaced(left) and spaced(right):
                previous.update(text=text[previous['char_start']:b], char_end=b,
                                end=max(previous['end'], row['end']))
                continue
        result.append(row)
    return result
