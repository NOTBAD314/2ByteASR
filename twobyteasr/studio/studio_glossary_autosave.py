"""Collect review-only evidence without writing or undoing formal terminology."""
from __future__ import annotations

import os


def _applied(page, glossary_ids):
    import subtitle_core as legacy
    from ..glossary.glossary_autosave import applied_terms
    ids = tuple(str(item) for item in glossary_ids if str(item).strip())
    try:
        stat = os.stat(legacy.LEARNED_TERMS_PATH)
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = (0, 0)
    cached = getattr(page, "_auto_glossary_terms", None)
    if cached is None or cached[0] != (ids, stamp):
        cached = page._auto_glossary_terms = ((ids, stamp), applied_terms(ids))
    return cached[1]


def _failed(page, exc):
    label = getattr(page, "save_state", None)
    if label is not None:
        label.setText("字幕修改已保留，学习候选暂未记录。" + str(exc)[:120])


def collect_manual_edit(page, studio_project, before, after, token, **metadata):
    """Sampling failure never prevents the caption transaction from completing."""
    ids = tuple(getattr(studio_project, "glossary_ids", None) or ())
    try:
        snapshot, terms = _applied(page, ids)
        existing = {(alias, term.canonical) for library in snapshot.libraries for term in library.terms
                    if term.confirmed for alias in term.aliases} if snapshot else set()
        from ..subtitle_rules.language_rules import project_language
        return page._learning_store.record_manual_edit(before, after, token=token,
            glossary_id=ids[0] if len(ids) == 1 else "", glossary_ids=ids,
            language=project_language(studio_project) or "und", scope="original",
            canonical_terms=terms, existing_pairs=existing, **metadata)
    except Exception as exc:
        _failed(page, exc)
        return []


def revert_learning(page, tokens, *, cue_after_text=None):
    try:
        return page._learning_store.revert_evidence_tokens(tokens, cue_after_text=cue_after_text)
    except Exception as exc:
        _failed(page, exc)
        return []
