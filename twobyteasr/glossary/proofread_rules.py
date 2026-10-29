"""Word-sized glossary proposals and content-scoped review decisions."""
from __future__ import annotations

import hashlib
from dataclasses import replace


WORD_SOURCES = {"local_confirmed", "local_review", "ai_review", "association"}
WORD_KINDS = {"term", "near", "ai_review", "association", "suspect"}
WORD_DECISION_KINDS = {"term", "near", "ai", "ai_review", "association", "consistency"}
DECISIONS_KEY = "glossary_proofread_decisions"


def effective_length(value):
    return sum(char.isalnum() for char in str(value or ""))


def full_word_pair(original, replacement):
    return effective_length(original) >= 2 and effective_length(replacement) >= 2


def normalize_occurrence(hit, text, resolver=None):
    """Recover a whole *matched alias*, never pad a one-letter diff with context.

    The legacy service diffed the final sentence, turning 古龙→骨龙 into
    古→骨. Only an actual resolver hit at that exact location may expand it.
    Unrelated text AI edits (pronouns, deletion cleanup) retain their rules.
    """
    a, b = hit.span
    if text[a:b] != hit.original:
        return None
    matched = False
    if resolver is not None and hit.replacement:
        for word in resolver.resolve(text).hits:
            if word.start <= a < b <= word.end:
                changed = text[word.start:a] + hit.replacement + text[b:word.end]
                if changed == word.canonical:
                    hit = replace(hit, span=(word.start, word.end), original=word.source,
                                  replacement=word.canonical)
                    matched = True
                    break
    word_proposal = hit.source in WORD_SOURCES or matched
    if hit.source == "ai_accepted" and resolver is not None:
        from .proposal_safety import contains_name
        word_proposal |= contains_name(resolver.snapshot, hit.replacement)
    if hit.source == "ai_accepted" and resolver is not None and hit.replacement and not full_word_pair(hit.original, hit.replacement):
        # A bare model diff inside a known name is not a complete matched
        # word. A separately retrieved whole-word proposal can still survive.
        changed = text[:a] + hit.replacement + text[b:]
        for body, end in ((text, b), (changed, a + len(hit.replacement))):
            for name in resolver.snapshot.canonical_terms:
                at = body.find(name)
                while at >= 0:
                    if at <= a < end <= at + len(name):
                        word_proposal = True
                        break
                    at = body.find(name, at + 1)
                if word_proposal:
                    break
            if word_proposal:
                break
    if word_proposal and not full_word_pair(hit.original, hit.replacement):
        return None
    if resolver is not None:
        from .proposal_safety import review_change_reason, contains_name
        if hit.source in WORD_SOURCES and not contains_name(resolver.snapshot, hit.replacement):
            return None
        if review_change_reason(text, hit.span, hit.replacement, snapshot=resolver.snapshot,
                                inferred=word_proposal and hit.source != "local_confirmed" and not matched,
                                protect_exact=not matched):
            return None
    return hit


def text_version(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def decision_for(row, issue):
    return {"state": "ignored", "text_sha": text_version(row["base"]),
            "kind": "word" if issue["kind"] in WORD_DECISION_KINDS else issue["kind"],
            "span": list(issue["span"]), "original": issue["original"], "replacement": issue["replacement"]}


def is_ignored(project, row, issue):
    state = (getattr(project, "studio_state", None) or {}).get(DECISIONS_KEY) or {}
    if not isinstance(state, dict):
        return False
    records = state.get(row["cue_id"], ())
    if not isinstance(records, (list, tuple)):
        return False
    expected = decision_for(row, issue)
    # Same word pair remains the same decision when local vs AI provenance
    # changes. Independent evidence/stutter checks keep separate identities.
    return any(expected == (dict(record, kind="word") if record.get("kind") in WORD_DECISION_KINDS else record)
               for record in records if isinstance(record, dict))
