"""Missing corroboration is diagnostic; a concrete conflict remains actionable."""

EVIDENCE_ONLY_REASONS = frozenset({
    'current_projection_difference', 'insufficient_word_coverage',
    'missing_independent_source', 'unverified_word_anchor',
    '当前全文缺少局部证据', '局部证据覆盖说明', '时间锚覆盖低',
    '字锚覆盖不足', '没有第二份独立证据',
})

# Rules retired from default review, in every language. Keep original records
# as diagnostics, without manufacturing a human acknowledgement or text edit.
RETIRED_LAYOUT_REASONS = frozenset({
    'line_too_long', 'unbalanced_lines', 'high_cps', 'dense_short_cue',
    'long_duration', 'too_many_lines', 'suggest_split', 'layout_split',
    'abnormal_punctuation', 'duplicate_punctuation',
})


def retired_review_reason(kind, source=''):
    return str(kind or '') in RETIRED_LAYOUT_REASONS or str(source or '') == 'readability_rule'


def evidence_only_reason(kind):
    return str(kind or '') in EVIDENCE_ONLY_REASONS


def unsupported_repeat_pattern(issue):
    """User rule: repetition alone is not evidence of a content error.

    Only the two deterministic pattern producers without any evidence or
    evidence receipt qualify. A real conflict of the same type remains in
    review; no text, timeline, user decision or original record is removed.
    """
    return (issue.issue_type in {'repeated_character','consecutive_duplicate'}
            and issue.source in {'text_rule','timeline_rule'}
            and not issue.evidence and not issue.fix_metadata.get('evidence_scope'))
