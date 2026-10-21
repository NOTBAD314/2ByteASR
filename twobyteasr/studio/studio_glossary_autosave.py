"""Studio side of saving manual fixes into the project's glossary (2026-10-15).

``glossary.glossary_autosave`` decides what is name-like and where it goes;
this module runs it after the learning store has recorded a manual edit,
keeps what each edit added (keyed by its evidence token) and removes it again
when the edit is undone. The ledger lives as long as the page's undo stack.
"""
from __future__ import annotations

import os

from ..i18n import bind_text


def _ledger(page) -> dict:
    ledger = getattr(page, "_auto_glossary_saves", None)
    if ledger is None:
        ledger = page._auto_glossary_saves = {}
    return ledger


def _applied(page, glossary_ids):
    """(snapshot, canonical terms) of the applied libraries, reread when the
    learned-terms file changes."""
    import subtitle_core as legacy
    from ..glossary.glossary_autosave import applied_terms
    ids = tuple(str(item) for item in glossary_ids if str(item).strip())
    try:
        stamp = os.stat(legacy.LEARNED_TERMS_PATH).st_mtime_ns
    except OSError:
        stamp = 0
    cached = getattr(page, "_auto_glossary_terms", None)
    if cached is None or cached[0] != (ids, stamp):
        cached = page._auto_glossary_terms = ((ids, stamp), applied_terms(ids))
    return cached[1]


def remember_learned_edit(page, project, entries, before: str, after: str, token: str, *,
                          explicit: bool = False) -> list:
    """Write the name pair of one recorded manual edit into the project glossary.

    ``entries`` are what the learning store recorded for the same edit; they
    are marked as saved (or skipped when the user ignored that pair before).
    ``explicit``: the pair is the user's own find-and-replace text."""
    ids = tuple(getattr(project, "glossary_ids", None) or ()) if project is not None else ()
    if not ids:
        return []
    from ..glossary.glossary_autosave import AMBIGUOUS, CONFLICT, SAVED, autosave_pairs, remember
    entries = [entry for entry in (entries or ()) if isinstance(entry, dict)]
    learned = [(str(entry.get("original_term") or ""), str(entry.get("corrected_term") or ""))
               for entry in entries if entry.get("status") != "ignored"]
    ignored = {(str(entry.get("original_term") or ""), str(entry.get("corrected_term") or ""))
               for entry in entries if entry.get("status") == "ignored"}
    try:
        snapshot, terms = _applied(page, ids)
        pairs = [pair for pair in autosave_pairs(before, after, canonical_terms=terms, learned_pairs=learned,
                                                 explicit=explicit) if pair not in ignored]
    except Exception:  # a broken library never blocks editing
        return []
    results = []
    for source, target in pairs:
        result = remember(snapshot, source, target)
        results.append(result)
        if result.status == SAVED:
            for original, corrected in learned:
                page._learning_store.mark_auto_saved(original, corrected, result.library_id)
    if not results:
        return []
    _ledger(page).setdefault(str(token), []).extend(result for result in results if result.added)
    label = getattr(page, "save_state", None)
    saved = [result for result in results if result.status == SAVED]
    if label is not None:
        if saved:
            first = saved[0]
            bind_text(label, '已记入词库「{library}」：{old} → {new}（撤销会一并取消）',
                      library=first.library_name or first.library_id, old=first.source, new=first.target)
        elif any(result.status == AMBIGUOUS for result in results):
            first = next(result for result in results if result.status == AMBIGUOUS)
            bind_text(label, '已记下「{old} → {new}」；工程用了多个词库，请在术语库页选择加入哪一个',
                      old=first.source, new=first.target)
        elif any(result.status == CONFLICT for result in results):
            first = next(result for result in results if result.status == CONFLICT)
            bind_text(label, '没有记入词库：{reason}', reason=first.reason[:120])
    if saved:
        _library_changed(page)
    return results


def forget_tokens(page, tokens) -> int:
    """Undo: remove the glossary rows saved by these evidence tokens."""
    from ..glossary.glossary_autosave import forget
    ledger = _ledger(page)
    removed = 0
    for token in tokens or ():
        for result in ledger.pop(str(token), ()):
            try:
                removed += forget(result)
            except (OSError, ValueError, TypeError):
                continue
    if removed:
        _library_changed(page)
        label = getattr(page, "save_state", None)
        if label is not None:
            bind_text(label, '已撤销，并从词库删掉刚才自动记入的写法')
    return removed


def _library_changed(page) -> None:
    """Let the main window's term library and Home choices pick up the change."""
    window = page.window() if hasattr(page, "window") else None
    library = getattr(getattr(window, "term_library_page", None), "library", None)
    notify = getattr(library, "_notify_library_changed", None)
    if callable(notify):
        try:
            notify()
        except Exception:
            pass


__all__ = ["forget_tokens", "remember_learned_edit"]
