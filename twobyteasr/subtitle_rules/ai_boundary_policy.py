"""AI boundary acceptance: hard validation and strictly owned repair windows.

Local linguistic scoring remains available to the explicit local segmenter.
It cannot invalidate an accepted AI boundary.
"""
from .grouping_contract import validate_boundary_offsets


def inspect(quality, boundaries):
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
    return issues


def windows(quality, boundaries):
    """The minimal invalid AI segment; a bad edge owns its two adjacent pieces."""
    edges=[0,*boundaries]
    ranges=[]
    for issue in inspect(quality,boundaries):
        a,b=issue['start'],issue['end']
        if a==b:
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


def minimal_fallback(quality, boundaries, *, record=None):
    """Never borrow characters from accepted neighbours or relax the limit."""
    result=list(boundaries)
    receipts=[]
    # Conservative local construction may avoid an inferred quantity/noun
    # seam. This scoring constraint never participates in AI acceptance.
    import copy
    import re
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
        receipt=dict(content_start=left,content_end=right,
                     origin='local_minimal_fallback' if accepted else 'unresolved',
                     before=before,after=candidate if accepted else before,
                     reason='bounded_retry_exhausted',remaining_issues=failures)
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
