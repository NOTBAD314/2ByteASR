"""Repair only proven legacy source spans, never subtitle text or time."""
import copy
import math
import unicodedata

RULE='legacy-caption-source-spans-v2-exact'


def content(text):
    return ''.join(c for c in str(text or '') if not c.isspace())


def repair(project):
    container=project.generation_metadata.get('segmentation_source_spans') or {}
    if not isinstance(container,dict):return []
    mapped=container.get('cues')
    if not isinstance(mapped,dict):return []
    repaired=[]
    for cue in project.cues:
        entry=mapped.get(cue.id)
        new_entry=entry is None
        if new_entry:entry={'parts':[],'origin':'legacy_exact_source_repair','timing_basis':'linked_source_reference'}
        if not isinstance(entry,dict):continue
        parts=entry.get('parts') or []
        if not isinstance(parts,list) or any(not isinstance(p,dict) or not isinstance(p.get('raw_text',''),str) for p in parts):continue
        wanted=content(cue.text)
        if not wanted or content(''.join(p.get('raw_text','') for p in parts))==wanted:continue
        refs={str(p.get('source_id')) for p in parts if p.get('source_id') is not None}
        refs.update(str(ref).split(':',1)[1] for ref in cue.evidence_refs if str(ref).startswith('segment:'))
        rows=[]
        for source in refs:
            evidence=project.asr_evidence.get('segment:'+source,{})
            if not isinstance(evidence,dict) or evidence.get('speaker_id')!=cue.speaker_id:continue
            bounds=[evidence.get('start_ms'),evidence.get('end_ms')]
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in bounds):continue
            text=evidence.get('final_text') or evidence.get('text') or ''
            if isinstance(text,str) and text and evidence.get('end_ms',0)>evidence.get('start_ms',0):
                rows.append(dict(source_id=source,text=text,start=evidence['start_ms']/1000,end=evidence['end_ms']/1000))
        rows.sort(key=lambda r:(r['start'],r['end'],r['source_id']))
        positions=[]
        for row in rows:
            positions.extend((c,row,i) for i,c in enumerate(row['text']) if not c.isspace())
        corpus=''.join(c for c,row,i in positions)
        if corpus.count(wanted)!=1:continue
        start=corpus.index(wanted);hits=positions[start:start+len(wanted)];new=[]
        for char,row,index in hits:
            if not new or str(new[-1]['source_id'])!=row['source_id']:
                if new and row['start']-new[-1]['source_time'][1]>.6:break
                fallback=int(row['source_id']) if row['source_id'].isdecimal() and any(type(p.get('source_id')) is int for p in parts) else row['source_id']
                identity=next((p['source_id'] for p in parts if str(p.get('source_id'))==row['source_id']),fallback)
                new.append(dict(source_id=identity,char_start=index,char_end=index+1,raw_text='',
                    index_unit='python_unicode_codepoint',source_time=[row['start'],row['end']],audible=True))
            else:new[-1]['char_end']=index+1
        else:
            source_by_id={r['source_id']:r for r in rows}
            for part in new:
                part['raw_text']=source_by_id[str(part['source_id'])]['text'][part['char_start']:part['char_end']]
            if content(''.join(p['raw_text'] for p in new))!=wanted:continue
            if new_entry:mapped[cue.id]=entry
            entry['parts']=new
            entry['source_span_repair']=dict(rule=RULE,previous_parts=copy.deepcopy(parts),
                basis='exact_unique_current_text_same_speaker_linked_source',text_changed=False)
            repaired.append(cue.id)
    return repaired
