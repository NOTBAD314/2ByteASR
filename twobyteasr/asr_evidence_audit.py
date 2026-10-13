"""Review checks for an already opened isolated real-project GUI audit.

The caller owns the normal startup, media readiness, screenshots and shutdown.
No ASR response is synthesized and this module starts no model or provider.
"""
from pathlib import Path


def _review_cases(project):
    """Choose honest real-data cases; a same-text card may be partial."""
    from .studio_review import ReviewEvidenceAggregator
    from .studio_qc import review_candidates
    aggregate = ReviewEvidenceAggregator()
    agreeable, conflicting = [], []
    tail = None
    for cue in project.cues:
        item = aggregate.aggregate(project, cue)
        candidates = review_candidates(project, cue)
        if item.models_agree_text and len(candidates) == 1 and {'MOSS', 'FireRed', 'Qwen'}.issubset(set(candidates[0].sources)):
            agreeable.append((item.requires_review, cue))
        if item.source_coverage.get('conflict') and not item.models_agree_text and item.requires_review:
            conflicting.append((item.source_coverage.get('known_count') != 3, cue))
        if (cue.id == '48' and cue.text == '他会遇到一个什么样的情况'
                and item.hypotheses and all(row['text'] == '他会遇到一个什么样的' for row in item.hypotheses)):
            tail = cue
    if not agreeable or not conflicting:
        raise RuntimeError('Real evidence audit needs a three-source same-text card and an independent-model text conflict')
    agreeable.sort(key=lambda pair: pair[0])
    conflicting.sort(key=lambda pair: pair[0])
    cases = [('agreement', agreeable[0][1]), ('conflict', conflicting[0][1])]
    if tail is not None:
        cases.append(('tail-projection', tail))
    return cases


def review_ui_checks(page, output):
    """Generator: yield UI-settle delays; return real-widget receipts."""
    from .blank_project_audit import _capture
    from .studio_review import ReviewEvidenceAggregator, cached_qc_result
    from .studio_qc import review_candidates
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    project = page.project
    if project is None:
        raise RuntimeError('Open the real isolated project before review audit')
    aggregate = ReviewEvidenceAggregator()
    cases = _review_cases(project)
    selected_before = page.selected_cue_id
    review_before = page._review_mode
    rows = []
    try:
        page._set_review_mode(True)
        yield .1
        for case, cue in cases:
            page.select_cue(cue.id)
            page._refresh_review_summary_strip()
            yield .2
            candidates = review_candidates(project, cue)
            headline = page.review_summary_text.text()
            item = aggregate.aggregate(project, cue)
            if case == 'agreement':
                coverage = item.source_coverage
                partial_or_unknown = coverage.get('partial') or coverage.get('coverage_unknown')
                honest_headline = (item.requires_review and not headline.startswith('✓')
                    and any(text in headline for text in ('局部来源覆盖', '分段来源覆盖', '来源信息缺失'))
                    if partial_or_unknown else not item.requires_review and '3 路独立来源' in headline)
                passed = len(candidates) == 1 and {'MOSS', 'FireRed', 'Qwen'}.issubset(set(candidates[0].sources)) and item.models_agree_text and honest_headline
            elif case == 'tail-projection':
                reason_text = page.review_reason_label.text()
                low_confidence = [issue for issue in cached_qc_result(project).for_cue(cue.id)
                    if issue.issue_type == 'low_confidence']
                no_placeholder_zero = (all(row.get('confidence') is None for row in item.hypotheses)
                    and not any(e.confidence == 0 for issue in low_confidence for e in issue.evidence)
                    and '置信度约0%' not in reason_text.replace(' ', ''))
                passed = (item.requires_review and not item.models_agree_text
                    and item.source_coverage.get('partial') and not item.source_coverage.get('conflict')
                    and len(candidates) == 2 and '差异' in headline and no_placeholder_zero)
            else:
                passed = item.source_coverage.get('conflict') and item.requires_review and not item.models_agree_text and '差异' in headline
            screenshot = output/f'review-{case}.png'
            _capture(page, screenshot)
            rows.append(dict(name='real review '+case, passed=passed, cue_id=cue.id,
                text=cue.text, headline=headline, sources=[list(c.sources) for c in candidates],
                coverage=item.source_coverage, screenshot=str(screenshot)))
            if case == 'tail-projection':
                rows[-1].update(qc_hint_widget='review_reason_label', qc_hint_text=reason_text,
                    low_confidence_issues=[issue.to_dict() for issue in low_confidence],
                    no_placeholder_zero_confidence=no_placeholder_zero)
            if not passed:
                raise AssertionError(rows[-1])
    finally:
        page._set_review_mode(review_before)
        if selected_before:
            page.select_cue(selected_before)
    return dict(passed=all(row['passed'] for row in rows), checks=rows,
        verification_layer='normal GUI on a real saved-project copy; no ASR inference')
