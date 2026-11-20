"""AI boundary acceptance: hard validation and strictly owned repair windows.

Two layers (2026-11-18):

* Hard constraints decide acceptance and local fallback: protected
  boundaries, explicit terms/numbers, and the character limit.
* Advisory risks only send a window back to the AI for a bounded second look:
  a cut inside a dictionary word, a named entity or a grammatical dependency
  (的|名词, 也|可以, 两个|快捷键, 说话|人, 记得|在…), and a short tail that
  depends on the previous cue. When the AI keeps its answer, or no request is
  available, the AI boundary stays. Local POS guesses never overrule it.
"""
import re

from .grouping_contract import validate_boundary_offsets

HARD_KINDS = frozenset({'protected_boundary_missing', 'semantic_boundary', 'length'})
ADVISORY_KINDS = frozenset({'word_or_dependency_split', 'dependent_tail'})


def _reliable_interiors(quality):
    """Edges whose damage is evidenced by more than an HMM/unknown token."""
    reliable = (getattr(quality, 'known_word_interiors', set())
                | getattr(quality, 'named_entity_interiors', set())
                | getattr(quality, 'named_component_interiors', set())
                | getattr(quality, 'pos_dependency_edges', set())
                | set(getattr(quality, 'syntax_reasons', {})))
    return (reliable & quality.forbidden) - quality.required


def _dependent_tail(quality, start, end, boundaries):
    """A 1–2 character cue that only completes its neighbour (做成｜字幕)."""
    if end-start > 2 or len(boundaries) < 2:
        return False
    if start in quality.required and end in quality.required:
        return False
    if (start, end) in getattr(quality, 'source_ranges', set()):
        return False
    independent = getattr(quality, 'independent_short', None)
    if callable(independent) and independent(start, end):
        return False
    return bool(re.search(r'[㐀-鿿A-Za-z0-9]', quality.index.content[start:end]))


def inspect(quality, boundaries, *, advisory=False):
    validate_boundary_offsets(list(boundaries), quality.total)
    issues = [dict(kind='protected_boundary_missing', start=x, end=x)
              for x in sorted(quality.required-set(boundaries))]
    # Explicit terms and numeric units are hard evidence. POS/HMM, relative
    # length, inferred timing and complete-expression preferences are advisory.
    confirmed = quality.explicit_word_interiors-quality.required
    issues.extend(dict(kind='semantic_boundary', start=x, end=x, reason='confirmed_term_split')
                  for x in boundaries if x in confirmed and x != quality.total)
    for left, right in zip([0,*boundaries],boundaries):
        if right-left > quality.max_chars:
            issues.append(dict(kind='length',start=left,end=right,length=right-left))
    if advisory:
        reliable = _reliable_interiors(quality)-confirmed
        issues.extend(dict(kind='word_or_dependency_split', start=x, end=x,
                           reason=quality.syntax_reasons.get(x, 'word_or_dependency'))
                      for x in boundaries if x in reliable and x != quality.total)
        for left, right in zip([0,*boundaries],boundaries):
            if _dependent_tail(quality, left, right, boundaries):
                issues.append(dict(kind='dependent_tail', start=left, end=right))
    return issues


def windows(quality, boundaries, *, advisory=False):
    """The minimal invalid AI segment; a bad edge owns its two adjacent pieces."""
    edges=[0,*boundaries]
    ranges=[]
    for issue in inspect(quality,boundaries,advisory=advisory):
        a,b=issue['start'],issue['end']
        if a==b:
            a=max((x for x in edges if x<a),default=0)
            b=min((x for x in edges if x>b),default=quality.total)
        elif issue['kind'] == 'dependent_tail':
            # The tail and both neighbours: it may belong to either side.
            a=max((x for x in edges if x<a),default=0)
            b=min((x for x in edges if x>b),default=quality.total)
        ranges.append((a,b))
    result=[]
    for a,b in sorted(set(ranges)):
        if result and a < result[-1][1]:
            result[-1]=(result[-1][0],max(b,result[-1][1]))
        else:
            result.append((a,b))
    return result


def _retry_status(statuses, left, right):
    """The AI retry status of the window overlapping [left, right)."""
    found = [status for (a, b), status in (statuses or {}).items() if a < right and left < b]
    if not found:
        return 'retry_not_attempted'
    order = ('request_failed', 'input_budget_conflict', 'not_allocated', 'no_answer',
             'rejected_by_gate', 'unchanged_with_violations', 'unchanged', 'improved')
    return min(found, key=lambda s: order.index(s) if s in order else len(order))


FALLBACK_REASONS = {
    'not_allocated': 'retry_budget_not_allocated',
    'input_budget_conflict': 'retry_input_budget_conflict',
    'request_failed': 'retry_request_failed',
    'no_answer': 'retry_no_answer',
    'rejected_by_gate': 'retry_answer_rejected',
    'unchanged_with_violations': 'retry_unchanged_with_violations',
    'retry_not_attempted': 'retry_not_attempted',
}


def minimal_fallback(quality, boundaries, *, record=None, statuses=None):
    """Never borrow characters from accepted neighbours or relax the limit.

    Only hard failures (length, protected edges, explicit terms) are repaired
    locally; advisory risks keep the AI answer. The receipt reason says why
    the AI did not fix the window (budget not allocated, request failed,
    answer rejected...), never a blanket 'retry exhausted'.
    """
    result=list(boundaries)
    receipts=[]
    # Conservative local construction may avoid an inferred quantity/noun
    # seam. This scoring constraint never participates in AI acceptance.
    import copy
    solver=copy.copy(quality)
    quantity_tails={m.end() for m in re.finditer(r'(?:非常多|这么多|那么多|很多|许多|大量)(?:的)?',quality.index.content)}
    solver.allowed=[x for x in quality.allowed if x not in quantity_tails]
    for left,right in windows(quality,boundaries):
        before=[x for x in result if left < x <= right]
        candidate=solver._solve(left,right,set(before),fixed={left,right}|quality.required,
                                 relax_time=True)
        proposed=sorted({x for x in result if not left < x <= right}|set(candidate or before))
        failures=[x for x in inspect(quality,proposed) if left <= x['start'] < right]
        accepted=bool(candidate) and not failures
        if accepted:
            result=proposed
        status=_retry_status(statuses,left,right)
        receipt=dict(content_start=left,content_end=right,
                     origin='local_minimal_fallback' if accepted else 'unresolved',
                     before=before,after=candidate if accepted else before,
                     reason=FALLBACK_REASONS.get(status, 'retry_'+status),retry_status=status,
                     remaining_issues=failures,
                     remaining_advisory=[x for x in inspect(quality,proposed if accepted else result,advisory=True)
                                         if left <= x['start'] < right and x['kind'] in ADVISORY_KINDS])
        receipts.append(receipt)
        if record:
            record('grouping_minimal_fallback',**receipt)
    return result,receipts


def annotate(cues, model_boundaries, final_boundaries, receipts):
    cursor=0
    for cue,end in zip(cues,final_boundaries):
        overlaps=[r for r in receipts if r['content_start'] < end and cursor < r['content_end']]
        cue.grouping_origin=next((r['origin'] for r in reversed(overlaps)), 'ai_accepted')
        cue.grouping_boundary_receipt=dict(origin=cue.grouping_origin,content_start=cursor,
            content_end=end,model_boundaries=[x for x in model_boundaries if cursor < x <= end],
            final_boundaries=[end],repairs=overlaps)
        cursor=end


def provenance(cues, validated):
    origins={getattr(c,'grouping_origin','ai_accepted') for c in cues}
    if not validated or 'unresolved' in origins:
        return 'fallback','unresolved'
    if any(o.startswith(('local_','source_retained')) for o in origins):
        return 'mixed','local_minimal_fallback'
    return 'ai','ai_targeted_correction' if 'ai_targeted_correction' in origins else 'ai_accepted'
