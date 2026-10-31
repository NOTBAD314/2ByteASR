"""Real saved I/O task, parsed and spliced through the actual frozen Studio."""
import copy,json
from collections import Counter


def verify(page, output, spec, check):
    from PySide6.QtTest import QTest
    from ..projects.studio_project import create_studio_outputs,load_project
    from ..recognition.recognition_input import capture_recognition_snapshot
    from ..recognition.recognition_result import media_identity_for_task
    from ..recognition.run_context import RuntimeContext
    from ..providers.mosi_asr import result_rows
    from ..recognition.speaker_evidence import scope_request_speakers
    import subtitle_core,wave
    config=spec['range_replay'];start,end=config['window_ms']
    def require(name,value,detail=None):
        check(name,value,detail)
        if not value:raise AssertionError(name)
    def read(name):return json.loads((output/name).read_text('utf8'))
    raw=read('replay-raw.json');primary=read('replay-primary.json')['data']
    aligned=read('replay-aligned.json')['data'];final=read('replay-final.json')['data'];manifest=read('replay-manifest.json')
    parsed=scope_request_speakers(result_rows(raw,offset=0,duration=(end-start)/1000),0,1)
    stages=[]
    def stage(name,rows,key='speaker'):
        counts=Counter(str(r.get(key))for r in rows)
        stages.append(dict(name=name,count=len(rows),labels=dict(counts),identities=len(counts)))
    for name,rows in [('raw',raw['segments']),('parsed',parsed),('primary',primary),('aligned',aligned),('final',final)]:stage(name,rows)
    require('real response retains three native labels',len({r['speaker']for r in parsed})==3,stages)
    require('current parse matches saved primary labels',Counter(r['speaker']for r in parsed)==Counter(r['speaker']for r in primary))
    project=page.project;before=copy.deepcopy(project.to_dict());index=page.undo_stack.index()
    snapshot=capture_recognition_snapshot(project,str(page.project_path),range_ms=(start,end));snapshot['requested_range_ms']=config['requested_ms']
    require('recorded edit sequence is heard',snapshot['sequence']==manifest['sequence'])
    require('recorded selected audio graph is heard',snapshot['audio_graph']==manifest['audio_graph'])
    heard=output/'replay-heard.wav'
    with wave.open(str(heard),'rb')as w:require('real selected PCM sample count',w.getnframes()==663104 and w.getframerate()==16000)
    metadata=dict(job_id='offline-frozen-'+config['job_id'],media_identity=media_identity_for_task(str(heard),RuntimeContext()),
        speaker_recovery=dict(raw_segments=primary,processing=dict(mode='native'),source='native'))
    result=create_studio_outputs(str(heard),subtitle_core.deserialize_cues(final),txt_path='',segments=subtitle_core.deserialize_segments(aligned),
        generation_metadata=metadata,recognition_snapshot=snapshot,target_project_path=output/'recognition-results/replay/识别结果.2byteproj')
    delivered=load_project(result['project']);info=delivered.generation_metadata['timeline_recognition']['range']
    inserted=set(info['cue_ids']);removed=set(info['replaced_cue_ids']);rows=[vars(c)for c in delivered.cues if c.id in inserted]
    stage('worker result',rows,'speaker_id')
    require('worker namespaces three different identities',len({c['speaker_id']for c in rows})==3)
    require('nonzero range lands on project clock',all(start<=c['start_ms']<c['end_ms']<=end for c in rows))
    require('actual Studio accepts range result',page.apply_range_recognition_result(result['project'],snapshot))
    require('range apply is one undo step',page.undo_stack.index()==index+1)
    require('three new identities have roster entries',set(info['speaker_map'].values())<={s.id for s in page.project.speakers})
    page.save();QTest.qWait(120);saved=load_project(page.project_path)
    require('actual Studio save preserves names',{s.id:s.name for s in saved.speakers}=={s.id:s.name for s in page.project.speakers})
    stage('Studio save/reopen',[vars(c)for c in saved.cues if c.id in inserted],'speaker_id')
    expected=[c for c in before['cues']if c['id']not in removed]
    require('573 outside captions unchanged',[vars(c)for c in saved.cues if c.id not in inserted]==expected,len(expected))
    page.undo_stack.undo();page.save();QTest.qWait(100);undone=load_project(page.project_path)
    for key in ('cues','speakers'):require('undo/save restores '+key,undone.to_dict()[key]==before[key])
    page.undo_stack.redo();page.save();QTest.qWait(100);redone=load_project(page.project_path)
    require('redo/save retains three identities',len({c.speaker_id for c in redone.cues if c.id in inserted})==3)
    receipt=dict(passed=True,new_provider_calls=0,window_ms=[start,end],requested_ms=config['requested_ms'],stages=stages,
        mapping=info['speaker_map'],outside_cues=len(expected),undo=True,redo=True,actual_studio_save=True)
    (output/'range-replay-result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf8')
    return receipt
