"""Effective text-review permissions, checked against the actual edit.

This is a text-only review: a model cannot claim it listened to audio. The
same policy fences requests, returned edits, retained rows and adoption.
"""
from difflib import SequenceMatcher
import hashlib
import json
import re

VERSION = 'proofread-content-v3-japanese-speech'
# Deliberately not Unicode ``\W``: ー, ・, apostrophes, + and name symbols
# can carry meaning. Changing those must pass the lexical/content checks.
PUNCTUATION = frozenset('，,。.!！?？、;；:：…“”‘’「」『』（）()[]【】《》〈〉{}')


def policy_of(project):
    from ..subtitle_rules.punctuation_style import project_mode, MODE_ADD
    value = getattr(project, '_proofread_edit_policy', {}) or {}
    return dict(version=VERSION, cleanup=bool(value.get('cleanup', False)),
                punctuation=bool(value.get('punctuation', False)) and project_mode(project) == MODE_ADD)


def policy_key(policy, entries=()):
    rows = [(entry.key, entry.target.to_dict(), entry.text) for entry in entries]
    return hashlib.sha256(json.dumps([policy, rows], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def request_rule(policy):
    return ('\n本次校对权限（独立开关，优先遵守）：' + json.dumps(policy, ensure_ascii=False) +
        '\n标点关闭时不新增、替换或删除现有标点，不为排版或句长提建议。口吃关闭时保留正常重复、强调、助词、长音、语气词；'
        '口吃开启也不授权标点调整。不为更顺口补词或重复短语。真实漏词/误识别须引用已提供原文或独立识别证据。'
        '没有音频输入，不能声称听到了声音。修改用edit_type说明类型；补漏/增删附evidence_source和evidence_quote，'
        '引用必须逐字出现在对应source_reference/dialogue_context或独立ASR中；重复当前句不能证明漏词。'
        'suspects须有issue_type=spelling|proper_name|translation_conflict|missing_word|truncated_content及具体证据。'
        '没有依据返回空changes。')


def _punct_only(before, after):
    chars = before + after
    return bool(chars and any(c in PUNCTUATION for c in chars)
                and all(c in PUNCTUATION or c.isspace() for c in chars))


def punctuation_change_only(before, after):
    edits = [(before[a:b],after[c:d]) for tag,a,b,c,d in
             SequenceMatcher(None,before,after,autojunk=False).get_opcodes() if tag != 'equal']
    return bool(edits and all(_punct_only(old,new) for old,new in edits))


def local_reference_support(before, after, references):
    """A localized changed phrase, not a loose word occurring elsewhere."""
    if not after.strip():return False
    references = [str(value) for value in references if value and str(value) != before]
    edits = [(a,b,c,d) for tag,a,b,c,d in SequenceMatcher(None,before,after,autojunk=False).get_opcodes()
             if tag != 'equal']
    return bool(edits and all(any(after[max(0,c-4):min(len(after),d+4)] in reference
                    and len(after[max(0,c-4):min(len(after),d+4)]) >= min(4,len(after))
                    for reference in references) for a,b,c,d in edits))


def _without_extra_punctuation(before, after):
    """Only split an independently removable addition, never re-place marks."""
    old = ''.join(c for c in before if c in PUNCTUATION)
    new = ''.join(c for c in after if c in PUNCTUATION)
    if old == new:
        return after
    if not old:
        return ''.join(c for c in after if c not in PUNCTUATION)
    return None  # mixed replacement/deletion cannot be safely separated


def repeated_deletion(text, start, end):
    unit = text[start:end]
    for size in range(1, len(unit)+1):
        piece = unit[:size]
        if len(unit) % size == 0 and piece * (len(unit)//size) == unit and (
                text[:start].rstrip().endswith(piece) or text[end:].lstrip().startswith(piece)):
            return True
    return False


def _inline_spelling(before, after, a, b, c, d):
    old = next((m.group() for m in re.finditer(r'[A-Za-z]+',before) if m.start()<=a<=b<=m.end()), '')
    new = next((m.group() for m in re.finditer(r'[A-Za-z]+',after) if m.start()<=c<=d<=m.end()), '')
    changed = before[a:b]+after[c:d]
    return bool(len(old)>=2 and len(new)>=2 and changed.isascii() and changed.isalpha()
                and set(old.lower()) & set(new.lower()))


def constrain_text(before, after, policy, *, evidence=False, lexical=False):
    """Keep independent corrections while dropping forbidden edits.

    Existing punctuation is immutable with punctuation off. Bare insertions
    and deletions need evidence; repetition cleanup is independently enabled.
    Substitutions remain subject to the existing lexical safety adjudicator.
    """
    if not isinstance(after, str):
        return before
    edits = []
    for tag, a, b, c, d in SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        if tag == 'equal':
            continue
        old, new = before[a:b], after[c:d]
        if not policy.get('punctuation'):
            if _punct_only(old, new):
                continue
            new = _without_extra_punctuation(old, new)
            if new is None:
                continue
        if old == new:
            continue
        # Enabling cleanup alone does not make kana, particles or an elongated
        # Japanese vowel an error. A confirmed alias or localized reference
        # evidence can still support a genuine transcription correction.
        if not lexical and not evidence and old and not new and any(
                '\u3040' <= char <= '\u30ff' or '\uff66' <= char <= '\uff9f' or char in '〜～' for char in old):
            continue
        if not lexical and not evidence and (not old.strip() or not new.strip()):
            if _punct_only(old, new) and policy.get('punctuation'):
                pass
            elif policy.get('cleanup') and old and not new and repeated_deletion(before, a, b):
                pass
            elif _inline_spelling(before,after,a,b,c,d) and not (old and not new and repeated_deletion(before,a,b)):
                pass  # spelling within one word, never inserting a new word
            else:
                continue
        # Repeat insertion/reduction is content, even if a model labels it typo.
        if not lexical and not evidence and not policy.get('cleanup'):
            compact_old = ''.join(c for c in old if not c.isspace())
            compact_new = ''.join(c for c in new if not c.isspace())
            if compact_old and compact_new and (compact_old in compact_new or compact_new in compact_old):
                continue
        edits.append((a, b, new))
    value = before
    for a, b, replacement in reversed(edits):
        value = value[:a] + replacement + value[b:]
    return value


def quoted_evidence(change, sources):
    source, quote = change.get('evidence_source'), change.get('evidence_quote')
    return bool(source in sources and isinstance(quote, str) and quote.strip()
                and quote in str(sources[source]) and str(change.get('reason', '')).strip())


def issue_allowed(issue, text, policy):
    if issue.get('checked'):
        return True  # do not silently undo a human action
    if issue.get('kind') == 'suspect':
        from ..subtitle_rules.review_evidence_policy import retired_review_reason
        return not retired_review_reason(issue.get('issue_type'), issue.get('rule_source'))
    span = issue.get('span', ())
    if len(span) != 2:
        return False
    a, b = span
    if not isinstance(a, int) or not isinstance(b, int) or not 0 <= a <= b <= len(text):
        return False
    old, new = text[a:b], issue.get('replacement', '')
    if old != issue.get('original'):
        return False
    candidate = text[:a] + new + text[b:]
    lexical = issue.get('kind') in {'term', 'near', 'association', 'consistency'} or bool(issue.get('lexical'))
    return constrain_text(text, candidate, policy, lexical=lexical,
                          evidence=bool(issue.get('content_evidence_verified'))) == candidate
