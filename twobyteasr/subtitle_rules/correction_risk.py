"""Language-aware local patch evidence; retrieval normalization is not equality."""
from __future__ import annotations
from collections import Counter
import re
import unicodedata

RULE_VERSION = 'content-language-risk-v2'
SPACED_LANGUAGES = frozenset({'en','it','es','fr','de','pt','ru'})
WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)
NEGATION = frozenset({'non','no','not','never','ne','pas','nicht','kein','keine','não','nem','ни','не','нет'})
SEMANTIC_ACCENTS = frozenset({frozenset({'e','è'}), frozenset({'si','sì'}),
                             frozenset({'da','dà'}), frozenset({'la','là'}),
                             frozenset({'li','lì'}), frozenset({'se','sé'})})


def visible_text(text):
    return unicodedata.normalize('NFC', str(text)).replace('\r\n','\n')


def words(text):
    return [m.group() for m in WORD.finditer(visible_text(text))]


def _exact_reference(source, target, original, start, end, references):
    """A full local statement must match, retaining word boundaries/accents.

    An unrelated occurrence of target elsewhere in a long reference is no vote.
    Source and target may differ only in this one localized patch.
    """
    candidate = original[:start] + target + original[end:]
    normalize = lambda s: ' '.join(visible_text(s).replace('’', "'").split()).casefold().strip('.,!?;: ')
    expected = normalize(candidate)
    return any(normalize(reference) == expected for reference in references if reference)


def _original_word_boundary(target, original, start, end, references):
    from ..forced_alignment import content_char_map
    positions=content_char_map(original)
    selected=[i for i,(_,a,b) in enumerate(positions) if a>=start and b<=end]
    if not selected:return False
    for reference in references:
        mapped=content_char_map(reference)
        if [c for c,_,_ in positions]!=[c for c,_,_ in mapped]:continue
        a,b=mapped[selected[0]][1],mapped[selected[-1]][2]
        if visible_text(reference[a:b])==visible_text(target):return True
    return False


def assess_patch(source, target, original, start, end, *, language, references=(), authoritative=(), lexicon=()):
    """Return (allow, reason). Only called for content languages using spaces.

    Ordinary spelling can use one independently recognized local sentence.
    Names, negation, quantities and semantic accents never inherit permission
    from an unrelated dictionary hit or a second copy of forced alignment.
    """
    from .number_fidelity import numeric_events
    before, after = original, original[:start] + target + original[end:]
    if (re.sub(r'\s+', '', source) == re.sub(r'\s+', '', target)
            and _original_word_boundary(target,original,start,end,authoritative)):
        return True, 'original_transcript_word_boundary'
    if tuple(x.value for x in numeric_events(before)) != tuple(x.value for x in numeric_events(after)):
        return False, 'ordered_numeric_events_changed'
    if Counter(w.casefold() for w in words(before) if w.casefold() in NEGATION) != Counter(
            w.casefold() for w in words(after) if w.casefold() in NEGATION):
        return False, 'negation_changed'
    norm = lambda s: visible_text(s).replace('’', "'")
    # Whitespace adjacent to punctuation and Unicode apostrophe glyphs do not
    # authorize changes to word boundaries, accents or punctuation itself.
    formatting = lambda s: re.sub(r"\s*([,.;:!?()'\[\]])\s*", r'\1', re.sub(r'\s+', ' ', norm(s)))
    if formatting(source) == formatting(target):
        return True, 'punctuation_whitespace'
    # Proven original transcript owns word boundaries (not a new ASR vote).
    old, new = words(source), words(target)
    if len(old)==len(new)==1 and frozenset({old[0].casefold(),new[0].casefold()}) in SEMANTIC_ACCENTS:
        return (_exact_reference(source,target,original,start,end,references), 'semantic_accent_requires_local_reference')
    # A same-letter join requires a lexical anchor AND a fragment which is
    # not itself an ordinary task word. "a casa" must never become "acasa".
    known = {str(w).casefold() for w in lexicon}
    if (len(new)==1 and len(old)>1 and ''.join(old).casefold()==new[0].casefold()
            and new[0].casefold() in known and any(w.casefold() not in known for w in old)):
        return True, 'task_lexical_fragment_join'
    # Entity/abbreviation replacements retain strict upstream term validation.
    if any(w[:1].isupper() or any(c.isdigit() for c in w) for w in old+new):
        return False, 'entity_change_requires_verified_term'
    if len(old)==len(new)==1 and len(old[0])>=3 and len(new[0])>=3:
        if _exact_reference(source,target,original,start,end,references):
            return True, 'independent_local_spelling_reference'
    return False, 'insufficient_local_language_evidence'
