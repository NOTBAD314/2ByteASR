"""Pure helpers for upgraded AI Glossary Proofreading (2026-11-25):

1. In-place term lookup & single-alias removal (kills false-positive alias across
   the whole project in 1 click, returning an undoable ``LibraryEdit``).
2. Extract repeated manual edits from proofread rows to feed ``QuickTermCaptureDialog``.
3. Keyboard-driven 4-key speed-review helpers (circular jump strictly across
   pending/unreviewed captions, option slot resolution for keys 1/2/3 & A).
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

from .term_editing import LibraryEdit, LibraryTerm, edit_term, library_terms


def find_term_record_for_issue(
    snapshot: Any,
    canonical: str,
    alias: str = "",
) -> LibraryTerm | None:
    """Locate the matching ``LibraryTerm`` behind a proofreading suggestion."""
    if snapshot is None:
        return None
    records = library_terms(snapshot)
    canon_cf = str(canonical or "").strip().casefold()
    alias_cf = str(alias or "").strip().casefold()
    if not canon_cf and not alias_cf:
        return None

    # Exact canonical + alias match wins first
    if canon_cf and alias_cf:
        for rec in records:
            if rec.canonical.casefold() == canon_cf and any(a.casefold() == alias_cf for a in rec.aliases):
                return rec
    # Exact canonical match
    if canon_cf:
        for rec in records:
            if rec.canonical.casefold() == canon_cf:
                return rec
    # Fallback: alias match alone
    if alias_cf:
        for rec in records:
            if any(a.casefold() == alias_cf for a in rec.aliases):
                return rec
    return None


def remove_alias_from_term(legacy: Any, record: LibraryTerm, alias: str) -> LibraryEdit:
    """Remove ONE mis-triggering alias from ``record`` while keeping the canonical term."""
    target_cf = str(alias or "").strip().casefold()
    if not target_cf:
        raise ValueError("未指定要删除的别名")
    remaining = tuple(a for a in record.aliases if a.casefold() != target_cf)
    if len(remaining) == len(record.aliases):
        raise ValueError(f"词条「{record.canonical}」里没有别名「{alias}」")
    return edit_term(legacy, record, record.canonical, remaining, delete=False)


def collect_manual_edit_pairs(rows: Sequence[dict[str, Any]], single_diff_fn: Callable[[str, str], tuple[str, str] | None]) -> list[dict[str, Any]]:
    """Aggregate repeated manual edits made during a proofread session for Quick Term Capture."""
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        origin = str(row.get("origin") or "")
        base = str(row.get("base") or "")
        if not origin or not base or origin == base:
            continue
        pair = single_diff_fn(origin, base)
        if pair is None:
            continue
        src, dst = pair
        if src and dst and src != dst:
            counts[(src, dst)] = counts.get((src, dst), 0) + 1
    return [
        {"source": src, "target": dst, "count": cnt, "left": 0}
        for (src, dst), cnt in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def next_pending_cue_id(
    visible_cue_ids: Sequence[str],
    current_cue_id: str,
    is_pending: Callable[[str], bool],
    *,
    reverse: bool = False,
) -> str:
    """Return the next (or previous) cue_id in ``visible_cue_ids`` that still needs review.

    Wraps around cleanly; returns ``""`` when zero pending cues remain.
    """
    ids = list(visible_cue_ids)
    if not ids:
        return ""
    try:
        start = ids.index(current_cue_id)
    except ValueError:
        start = 0 if reverse else -1
    n = len(ids)
    step = -1 if reverse else 1
    for offset in range(1, n + 1):
        cid = ids[(start + step * offset) % n]
        if is_pending(cid):
            return cid
    return ""


def pick_adopt_index(
    groups: Sequence[dict[str, Any]],
    *,
    option_slot: int | None = None,
) -> tuple[int | None, str]:
    """Pick the proposal index to adopt for keyboard speed-review (A or 1/2/3).

    Returns ``(issue_index, hint_message)``.
    """
    open_group = next((g for g in groups if g.get("state") != "adopted" and not g.get("reviewed")), None)
    if open_group is None:
        return None, "当前字幕没有待处理建议"
    parts = list(open_group.get("parts") or ())
    if not parts:
        return None, "当前字幕没有待处理建议"
    if option_slot is not None:
        if 0 <= option_slot < len(parts):
            return int(parts[option_slot]), ""
        return None, f"当前这处只有 {len(parts)} 个候选"
    if open_group.get("options") and len(parts) > 1:
        return None, f"这处有 {len(parts)} 个候选，请按数字键 1～{min(9, len(parts))} 直接选用"
    return int(parts[0]), ""


__all__ = [
    "collect_manual_edit_pairs",
    "find_term_record_for_issue",
    "next_pending_cue_id",
    "pick_adopt_index",
    "remove_alias_from_term",
]
