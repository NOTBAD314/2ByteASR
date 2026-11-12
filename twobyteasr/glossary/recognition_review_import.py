"""Read existing recognition review through exact source/character lineage.

No request, document mutation, inferred numeric cue ID, or glossary dependency.
Unmapped evidence remains available in the returned diagnostic receipt.
"""
from difflib import SequenceMatcher
from collections import defaultdict
import hashlib


def equal_span(before, after, start, end):
    if not (type(start) is int and type(end) is int and 0 <= start < end <= len(before)):
        return None
    for a,b,n in SequenceMatcher(None, before, after, autojunk=False).get_matching_blocks():
        if a <= start < end <= a+n:
            return b+start-a, b+end-a
    return None


def existing_review(project, entries):
    from .studio_glossary_service import GlossaryReviewPreview
    from ..studio.studio_text_tools import TextOccurrence
    from ..studio.subtitle_text_targets import bind_occurrence
    from ..subtitle_rules.proofread_identity import validate_new_suspects as _validate_new_suspects
    entries = {e.target.cue_id:e for e in entries if e.target.layer=='original'}
    sources = {}
    for ref,row in project.asr_evidence.items():
        if not ref.startswith('segment:') or not ref[8:].isdigit():
            continue
        detail = (row.get('caption_arbitration') or {}).get('terminology_polish') or {}
        if detail.get('input_text'):
            sources[int(ref[8:])] = (row,detail)
    index = defaultdict(list)
    cues = {c.id:c for c in project.cues}
    for cue_id,record in (project.generation_metadata.get('segmentation_source_spans') or {}).get('cues',{}).items():
        cue = cues.get(cue_id)
        if cue is None or cue_id not in entries:
            continue
        parts = record.get('parts') or []
        joined = ''.join(str(p.get('raw_text') or '') for p in parts)
        offset = 0
        for part in parts:
            raw = str(part.get('raw_text') or '')
            if type(part.get('source_id')) is int and part.get('index_unit') == 'python_unicode_codepoint':
                index[part['source_id']].append((cue,part,joined,offset))
            offset += len(raw)

    diagnostic={'kind':'recognition_review_import','asr_run':False,'ai_requested':False,
        'unassigned':[], 'completed_no_change':[], 'source_segments':len(sources), 'pending_rows':[]}
    hits=[]; seen=set()
    def attach(source_id, proposal, *, replacement=''):
        source,detail=sources[source_id]
        baseline=detail['input_text']
        a,b=proposal.get('start'),proposal.get('end')
        surface=str(proposal.get('from') or proposal.get('surface') or '')
        if not surface or type(a) is not int or type(b) is not int or baseline[a:b]!=surface:
            diagnostic['unassigned'].append({'source_segment_id':source_id,'reason':'invalid_primary_span','proposal':proposal})
            return
        final=str(detail.get('final_text') or detail.get('validated_text') or baseline)
        span=equal_span(baseline,final,a,b)
        owners=[]
        if span:
            for cue,part,joined,offset in index[source_id]:
                low,high=part.get('char_start'),part.get('char_end')
                if type(low) is not int or type(high) is not int or not low <= span[0] < span[1] <= high:
                    continue
                local=(offset+span[0]-low,offset+span[1]-low)
                mapped=equal_span(joined,cue.text,*local)
                if mapped and cue.text[mapped[0]:mapped[1]]==surface:
                    owners.append((cue,mapped))
        if len(owners)!=1:
            diagnostic['unassigned'].append({'source_segment_id':source_id,'reason':'ambiguous_or_changed_lineage',
                'source_span':[a,b],'candidate_cue_ids':[c.id for c,_ in owners], 'proposal':proposal})
            return
        cue,(start,end)=owners[0]; entry=entries[cue.id]
        identity=hashlib.sha256(repr((source_id,a,b,surface,replacement,entry.text)).encode()).hexdigest()[:24]
        if identity in seen:return
        seen.add(identity)
        reason=str(proposal.get('evidence') or proposal.get('basis') or '识别后校对疑点，需要试听确认')
        if replacement and replacement!=surface:
            hit=TextOccurrence(cue.id,cue.start_ms,surface,replacement,(start,end),reason=reason,
                default_selected=False,source='recognition_review',evidence=f'source_segment:{source_id}',
                missing_evidence='未核验原音')
            hits.append(bind_occurrence(hit,entry))
        else:
            diagnostic['pending_rows'].append({'cue_id':entry.key,'state':'speech_review','span':[start,end],
                'surface':surface,'reason':reason,'suspect_id':proposal.get('suspect_id') or identity,
                'source_segment_id':source_id,'text_revision':hashlib.sha256(entry.text.encode()).hexdigest()})

    for source_id,(row,detail) in sources.items():
        for proposal in detail.get('new_suspects',()):
            if proposal.get('validation_state')!='invalid':attach(source_id,proposal)
        for proposal in detail.get('rejected_edits',()):
            a,b=proposal.get('start'),proposal.get('end');before=detail['input_text']; target=proposal.get('to')
            if (proposal.get('rule_id')=='source_quote_not_found' and type(a) is int and target
                    and len(target)==len(str(proposal.get('from') or ''))
                    and before[a:a+len(target)]==target and b==a+len(str(proposal.get('from') or ''))):
                diagnostic['completed_no_change'].append({'source_segment_id':source_id,'proposal':proposal})
                continue
            if proposal.get('rule_id') not in {'length_change_without_support','local_difference_without_two_sources',
                    'unsupported_phonetic_change','insufficient_asr_support','japanese_semantic_needs_listening','japanese_particle_preservation'}:
                continue
            refs=(row.get('caption_arbitration') or {}).get('independent_input_evidence') or {}
            independent=[str(refs.get(k) or row.get(k+'_text') or '') for k in ('qwen','firered')]
            if not any(text and text!=before for text in independent):continue
            supported=bool(target and any(target in text for text in independent))
            attach(source_id,proposal,replacement=target if supported else '')
    # Old malformed discoveries are repaired only by the same exact, unique
    # span contract as new responses, with the raw record still retained.
    summary=project.generation_metadata.get('polishing_summary') or {}
    rows=list(summary.get('unassigned_new_suspects') or [])
    for group in (summary.get('term_context') or {}).get('unassigned_new_suspects',()):
        rows.extend(group.get('rows') or [])
    if rows:
        scoped,unassigned=_validate_new_suspects(rows,{key:value[1]['input_text'] for key,value in sources.items()})
        for source_id,proposals in scoped.items():
            for proposal in proposals:
                if proposal['validation_state']!='invalid':attach(source_id,proposal)
        diagnostic['unassigned'].extend(unassigned)
    return GlossaryReviewPreview(tuple(hits),diagnostic)
