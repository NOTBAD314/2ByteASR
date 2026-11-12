"""Credential-free, read-only source-to-translation diagnostic samples."""
import hashlib


def subtitle_lineage(project,cue_id):
    from ..subtitle_rules.subtitle_translation import records_of,container_target
    ordered=sorted(project.cues,key=lambda c:(c.start_ms,c.end_ms,c.id))
    i=next(i for i,c in enumerate(ordered) if c.id==cue_id);cue=ordered[i]
    lineage=(project.generation_metadata.get('segmentation_source_spans') or {}).get('cues',{}).get(cue.id,{})
    sources=[]
    for source_id in dict.fromkeys(part.get('source_id') for part in lineage.get('parts',())):
        if type(source_id) is not int:continue
        row=project.asr_evidence.get(f'segment:{source_id}',{})
        decision=row.get('caption_arbitration') or {}
        polish=decision.get('terminology_polish') or {}
        sources.append({'source_segment_id':source_id,'speaker_id':row.get('speaker_id'),
            'time':[row.get('start_ms'),row.get('end_ms')],
            'original_asr':(decision.get('independent_input_evidence') or {}).get('primary') or row.get('moss_text') or row.get('text'),
            'reference_asr_texts':decision.get('independent_input_evidence') or {},
            'reference_windows':decision.get('source_coverage') or {},
            'reference_mapping':decision.get('independent_reference_mapping'),
            'confidence_provenance':{'compatibility_value':row.get('confidence'),
                'kind':decision.get('confidence_kind','not_recorded_in_old_project'),
                'provider_source':decision.get('provider_source')},
            'polish':{k:polish.get(k) for k in ('input_text','validated_text','final_text','prompt_version',
                'returned_edits','accepted_edits','rejected_edits','completed_no_change_edits','new_suspects','quality_state')}})
    record=records_of(project).get(cue.id) or {}
    context=[{'cue_id':c.id,'speaker_id':c.speaker_id,'start_ms':c.start_ms,'end_ms':c.end_ms,'text':c.text}
        for c in ordered[max(0,i-3):i+4]]
    return {'cue_id':cue.id,'source_segment_ids':[r['source_segment_id'] for r in sources],
        'layer':'original','speaker_id':cue.speaker_id,'start_ms':cue.start_ms,'end_ms':cue.end_ms,
        'editable_primary_text':cue.text,'text_revision':hashlib.sha256(cue.text.encode()).hexdigest(),
        'source_chain':sources,'split_merge_lineage':lineage,'dialogue_context':context,
        'translation_input':{'source_text':record.get('source_text'),'source_sha':record.get('source_sha'),
            'context_sha':record.get('context_sha'),'target':record.get('target',container_target(project)),
            'provider':record.get('provider'),'model':record.get('model'),
            'note':'saved record; dialogue_context is reconstructed from this current revision, not the original HTTP request'},
        'translation':record.get('text') or (project.generation_metadata.get('translations') or {}).get(cue.id,''),
        'translation_status':record.get('status'),'translation_origin':record.get('origin'),
        'manual_listening':'pending','reference_translation':'','human_verdict':''}
