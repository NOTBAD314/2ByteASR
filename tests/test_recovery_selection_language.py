"""Accepted project text belongs to the language of its own recognition task."""
import hashlib
import numpy as np
import pytest
from twobyteasr.recognition.run_context import RuntimeContext
from twobyteasr.recognition.transcript_acceptance import digest,project_selection
from twobyteasr.recognition.transcript_acceptance import gate_primary,identity_for,pending_ranges


@pytest.mark.parametrize('saved,current,where,replay',[
    ('it','en','identity',False),('en','it','identity',False),
    ('en','auto','identity',False),('en','en','identity',True),
    ('en-US','en','identity',True),('it','it','legacy',True),
    ('it','en','legacy',False),(None,'en','legacy',False),
    ('en','it','range',False),('en','en','range',True),
])
def test_replay_checks_saved_language_before_reusing_accepted_text(tmp_path,saved,current,where,replay):
    source=tmp_path/'same-media.bin';source.write_bytes(b'one unchanged audio source')
    region=dict(id='selected',start=0.,end=2.,status='accepted',accepted_cue_ids=['cue'])
    state=dict(version=1,audio_graph_digest=digest({}),source_identities={str(source):{
        'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}},ranges=[region])
    metadata={'transcript_acceptance':state}
    if where=='identity':state['identity']={'requested_language':saved}
    if where=='legacy' and saved is not None:metadata['language']={'requested':saved}
    if where=='range':
        # A later range can have its own choice while the first task identity
        # remains in the project archive. Its per-range receipt takes priority.
        state['identity']={'requested_language':'it'};region['requested_language']=saved
    snapshot={'audio_graph':{},'project':{'generation_metadata':metadata,'cues':[
        dict(id='cue',start_ms=0,end_ms=2000,text='Accepted text from the previous task.',speaker_id='stable')]}}
    context=RuntimeContext(requested_language=current,task_language=current,recognition_snapshot=snapshot)
    actual=project_selection(context,np.zeros(64000,np.float32))
    if replay:
        assert actual['ranges'][0]['accepted_rows'][0]['text']=='Accepted text from the previous task.'
    else:
        assert actual is None,'Changing the requested source language must not relabel old accepted text as a new result'


@pytest.mark.parametrize('current_raw_conflicts',[False,True])
def test_pre_guard_cache_cannot_reapply_another_language(tmp_path,current_raw_conflicts):
    import json
    from types import SimpleNamespace
    from tests.test_asr_language_provenance import IT,EN
    audio=np.zeros(64000,np.float32)
    wrong=dict(id='wrong',start_sample=0,end_sample=32000,start=0.,end=2.,status='accepted',
        requested_language='it',accepted_rows=[dict(start=0.,end=2.,text=IT)])
    wrong['accepted_rows_sha256']=digest(wrong['accepted_rows'])
    good=dict(id='good',start_sample=48000,end_sample=64000,start=3.,end=4.,status='accepted',
        requested_language='en',accepted_rows=[dict(start=3.,end=4.,text='Chosen later English stays')])
    good['accepted_rows_sha256']=digest(good['accepted_rows'])
    # Version 0f could carry an Italian choice into an English task and write
    # that new task identity around the old per-range language receipt.
    state=dict(version=1,identity=identity_for(audio,'en'),ranges=[wrong,good])
    path=tmp_path/'primary-selection-en.json';path.write_text(json.dumps(state),encoding='utf8')
    raw=[dict(start=0.,end=2.,text=IT if current_raw_conflicts else EN),dict(start=3.,end=4.,text='Raw later English')]
    audit=dict(conflicts=int(current_raw_conflicts),regions=[dict(start=0.,end=2.,transcript={'language':'it'})] if current_raw_conflicts else [])
    context=RuntimeContext(requested_language='en',task_language='en')
    result=gate_primary({'segments':raw},audio,context,SimpleNamespace(record_run_event=lambda *a,**k:None),{'cache_dir':str(tmp_path)},audit)
    assert result['segments'][-1]['text']=='Chosen later English stays'
    assert all(r['text']!=IT for r in result['segments'])
    assert len(pending_ranges(context.transcript_acceptance))==int(current_raw_conflicts)
    assert len(context.transcript_acceptance['invalidated_selections'])==1
    if not current_raw_conflicts:assert result['segments'][0]['text']==EN
