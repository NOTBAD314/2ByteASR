"""Text request coverage and the outcome of individual edit proposals."""

from collections import Counter


_CONCLUSIVE_REJECTIONS = {
    "invalid_or_no_effect", "noop_source_missing", "unknown_or_mismatched_candidate_id",
    "pronoun_proposal_contradicts_retain_reason", "ordered_numeric_events_changed",
}


def unresolved_edit(edit):
    if not isinstance(edit, dict) or edit.get("rule_id") in _CONCLUSIVE_REJECTIONS:
        return False
    source, target = edit.get("from"), edit.get("to")
    return isinstance(source, str) and isinstance(target, str) and bool(source and target and source != target)


def disposition(detail, *, processed=True):
    if not processed:
        return "unprocessed"
    rejected = detail.get("rejected_edits", ())
    usage = detail.get("candidate_usage", {})
    if (any(unresolved_edit(edit) for edit in rejected) or detail.get("unreviewed_suspects")
            or detail.get("new_suspects") or usage.get("unresolved_recall_gaps", detail.get("recall_gaps"))
            or usage.get("unresolved_candidates")
            or any(row.get("disposition") in {"review", "missing_candidate"}
                   for row in detail.get("suspect_results", ()) if isinstance(row, dict))):
        return "pending"
    if detail.get("accepted_edits") and detail.get("final_text") != detail.get("input_text"):
        return "applied"
    return "kept_with_rejections" if rejected else "unchanged"


def summarize_dispositions(rows):
    return dict(Counter(
        detail.get("disposition") or disposition(detail) for detail in rows
    ))
