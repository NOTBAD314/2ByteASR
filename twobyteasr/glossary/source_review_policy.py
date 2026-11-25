"""Recognition may analyze alternate wording. Only the source owns the draft."""
from difflib import SequenceMatcher
from collections import Counter
from hashlib import sha256
import json


VERSION = 'manual-source-review-v1'


def proposal_identity(segment_id, text, start, end, replacement):
    revision = sha256(text.encode('utf-8')).hexdigest()
    key = [VERSION, str(segment_id), revision, start, end, replacement]
    return sha256(json.dumps(key, ensure_ascii=False).encode('utf-8')).hexdigest()[:24]


def preserve_source_for_delivery(baseline, analysis, *, record, summary=None):
    """Transfer review metadata only. Audio, timings, source words and text stay owned by baseline."""
    from ..recognition.language_guard import conflict, settings_policy
    from ..recognition.run_context import get_runtime_context
    context = get_runtime_context()
    guard = settings_policy(context.asr_settings_snapshot, context.requested_language)
    analyzed = {segment.segment_id: segment for segment in analysis}
    total = 0
    for segment in baseline:
        result = analyzed.get(segment.segment_id)
        if result is None:
            continue
        before = segment.text
        detail = dict(result.caption_arbitration.get('terminology_polish') or {})
        alternatives = []
        for tag, start, end, left, right in SequenceMatcher(
                None, before, result.text, autojunk=False).get_opcodes():
            if tag != 'equal':
                alternatives.append(dict(start=start, end=end, **{
                    'from': before[start:end], 'to': result.text[left:right],
                }))
        if not detail and not alternatives:
            continue
        analyzed_edits = detail.pop('accepted_edits', [])
        prior_input = detail.get('input_text')
        detail.update(analysis_input_text=prior_input, analysis_final_text=result.text,
                      analysis_accepted_edits=analyzed_edits, accepted_edits=[],
                      input_text=before, validated_text=before, final_text=before,
                      review_policy=VERSION, base_text_revision=sha256(before.encode('utf-8')).hexdigest())
        if prior_input is not None and prior_input != before:
            # Existing span receipts belong to the draft that was analyzed.
            for field in ('rejected_edits', 'new_suspects', 'suspect_results'):
                detail['analysis_' + field] = detail.pop(field, [])
        proposals = []
        foreign_candidate = conflict(result.text, guard['language']) if guard['strict'] else None
        for edit in alternatives:
            start, end = edit['start'], edit['end']
            matching = next((row for row in analyzed_edits if all(row.get(k) == edit[k]
                for k in ('start', 'end', 'from', 'to'))), None)
            proof = bool(matching and (matching.get('acoustic_verified') or matching.get('terminology_evidence')))
            if foreign_candidate and foreign_candidate != conflict(before, guard['language']):
                detail.setdefault('draft_rejections', []).append(dict(edit, reason='language_guard'))
                continue
            # Keep larger or disputed draft rewrites in diagnostics. No user
            # is asked to approve a patch without a sensible, visible anchor.
            if end == start or not edit['to'] or max(end-start, len(edit['to'])) > 4 and not proof:
                detail.setdefault('draft_rejections', []).append(dict(edit, reason='unverified_or_unanchored_rewrite'))
                continue
            proposals.append(dict(edit, proposal_id=proposal_identity(segment.segment_id, before, start, end, edit['to']),
                                  source='recognition_analysis', evidence='识别校对建议 · 等待采用'))
        detail['proposed_edits'] = proposals
        detail['disposition'] = 'pending' if proposals or detail.get('rejected_edits') else 'unchanged'
        segment.caption_arbitration['terminology_polish'] = detail
        total += len(proposals)
    if isinstance(summary, dict) and summary:
        summary['analysis_disposition_counts'] = summary.get('disposition_counts', {})
        summary['disposition_counts'] = dict(Counter(
            segment.caption_arbitration.get('terminology_polish', {}).get('disposition', 'unprocessed')
            for segment in baseline))
        term_context = summary.get('term_context')
        if isinstance(term_context, dict):
            term_context['analysis_accepted_edits'] = term_context.get('accepted_edits', 0)
            term_context['accepted_edits'] = 0
        summary['review_policy'] = VERSION
        summary['proposed_text_edits'] = total
        summary['body_edits_applied'] = 0
    record('recognition_text_proposals', actor='background_analysis', policy=VERSION,
           proposal_count=total, body_edits_applied=0)
    return baseline
