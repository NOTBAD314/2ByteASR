"""One setting boundary for all pending repetition-cleanup proposals."""
from difflib import SequenceMatcher
import re

_SEPARATORS = re.compile(r'[\s，,、…呃嗯额唔]+')
_CLEANUP_KINDS = frozenset({'stutter', 'merge'})
_LEXICAL_KINDS = frozenset({'term', 'near', 'association', 'consistency'})


def whole_repetition(original, replacement):
    before,after=_SEPARATORS.sub('',original),_SEPARATORS.sub('',replacement)
    return bool(after and len(before)>len(after) and len(before)%len(after)==0
                and before==after*(len(before)//len(after)))


def repetition_cleanup(issue, text=''):
    """Classify the *edit*, not the presence of repeated letters in a cue.

    Explicit local cleanup includes both spoken restarts and unsupported
    merged duplicates. A confirmed glossary alias remains a lexical edit.
    AI/evidence deletions qualify only if every removed non-separator unit
    is an immediately repeated copy, with no insertion or substitution.
    """
    kind = issue.get('kind')
    if kind in _CLEANUP_KINDS:
        return True
    if kind in _LEXICAL_KINDS or issue.get('lexical'):
        return False
    if issue.get('cleanup'):
        return True
    if not text:
        return False
    a, b = issue['span']
    original = issue['original']
    if text[a:b] != original:
        return False
    operations = SequenceMatcher(None, original, issue['replacement'], autojunk=False).get_opcodes()
    deletions = []
    for tag, i, j, _x, _y in operations:
        if tag == 'equal':
            continue
        if tag != 'delete':
            return False
        unit = _SEPARATORS.sub('', original[i:j])
        if not unit:
            continue
        before = _SEPARATORS.sub('', text[:a+i])
        after = _SEPARATORS.sub('', text[a+j:])
        if not (before.endswith(unit) or after.startswith(unit)):
            return False
        deletions.append(unit)
    return bool(deletions)


def issue_enabled(issue, cleanup=True, text=''):
    """Already-applied edits stay visible; the switch never reverts text."""
    return bool(cleanup or issue.get('checked') or not repetition_cleanup(issue, text))


def pending_issue(issue, cleanup=True, text=''):
    return (issue_enabled(issue, cleanup, text) and not issue.get('checked')
            and not issue.get('stale') and not issue.get('reviewed'))
