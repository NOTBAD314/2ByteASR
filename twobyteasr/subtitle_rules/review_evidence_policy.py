"""Missing corroboration is diagnostic; a concrete conflict remains actionable."""

EVIDENCE_ONLY_REASONS = frozenset({
    'current_projection_difference', 'insufficient_word_coverage',
    'missing_independent_source', 'unverified_word_anchor',
    '当前全文缺少局部证据', '局部证据覆盖说明', '时间锚覆盖低',
    '字锚覆盖不足', '没有第二份独立证据',
})


def evidence_only_reason(kind):
    return str(kind or '') in EVIDENCE_ONLY_REASONS
