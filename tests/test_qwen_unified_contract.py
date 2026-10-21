import hashlib,json,sys,types,runpy
from pathlib import Path
import numpy as np
import pytest
import subtitle_core as core
from twobyteasr.recognition import asr
from twobyteasr.subtitle_rules.correction_safety import reference_consensus_edits,apply_reference_consensus_corrections
from twobyteasr.recognition.caption_arbitration import arbitrate

@pytest.mark.parametrize("frozen",[False,True])
def test_source_frozen_identical_context_pcm_policy(monkeypatch,tmp_path,frozen):
    monkeypatch.setattr(sys,"frozen",frozen,raising=False)
    for k,v in dict(USE_QWEN_ASR_REFERENCE=True,QWEN_ASR_BACKEND='local',QWEN_ASR_BATCH_SIZE=2,QWEN_ASR_MAX_NEW_TOKENS=160).items():monkeypatch.setattr(core,k,v)
    pcm=np.array([.123456789,.000001,-.399991],dtype=np.float32)
    monkeypatch.setattr(asr,'build_qwen_asr_chunks',lambda *a,**k:[dict(start=0,end=3/16000,audio=(pcm,16000))])
    monkeypatch.setattr(asr,'resolve_qwen_asr_local_source',lambda:'fixed-model')
    monkeypatch.setattr(asr,'media_cache_context',lambda p:{'cache_dir':str(tmp_path)})
    monkeypatch.setattr(asr,'_main_worker_python',lambda:sys.executable)
    monkeypatch.setattr(asr,'SCRIPT_DIR',str(Path(asr.__file__).resolve().parents[2]))
    def run(cmd,output,**kw):
        m=json.loads(Path(cmd[cmd.index('--manifest')+1]).read_text('utf8'));j=m['jobs'][0]
        assert '真实标题' in j['context'] and 'shared_audio' not in j['context']
        assert m['policy']['max_new_tokens']==160 and m['policy']['batch_size']==2
        assert np.array_equal(np.load(j['path'],allow_pickle=False),pcm)
        assert j['pcm_sha256']==hashlib.sha256(pcm.tobytes()).hexdigest()
        return {'results':[dict(segment_id=1,text='实际窗口',confidence=0.0,samples=j['samples'],pcm_sha256=j['pcm_sha256'],start=j['start'],end=j['end'],context_sha256=hashlib.sha256(j['context'].encode('utf8')).hexdigest())],'policy':m['policy']}
    monkeypatch.setattr(asr,'_run_isolated_asr_worker',run)
    assert asr.transcribe_qwen_reference('真实标题.mp4',[],pcm)[0]['text']=='实际窗口'
    audit=json.loads((tmp_path/'speaker-evidence/qwen-native-windows.json').read_text('utf8'))
    assert audit['raw_worker_payload']['results'][0]['text']=='实际窗口'
    # An output with the right text and window ID must still prove its actual
    # generation policy and input/context identity, not merely echo a result.
    for field in ['policy','samples','pcm_sha256','start','context_sha256']:
        def corrupt(cmd,output,**kw):
            payload=run(cmd,output,**kw)
            if field=='policy':payload['policy']={**payload['policy'],'max_new_tokens':512}
            else:payload['results'][0][field]='wrong-receipt'
            return payload
        monkeypatch.setattr(asr,'_run_isolated_asr_worker',corrupt)
        with pytest.raises(RuntimeError,match='receipt mismatch'):
            asr.transcribe_qwen_reference('真实标题.mp4',[],pcm)
        preserved=json.loads((tmp_path/'speaker-evidence/qwen-native-windows.json').read_text('utf8'))
        assert preserved['raw_worker_payload']['results'][0]['text']=='实际窗口'

@pytest.mark.parametrize('rows',[[],[dict(segment_id=2,text='错号')],[dict(segment_id=1,text='多段'),dict(segment_id=1,text='重复')]])
def test_partial_reordered_duplicate_errors(monkeypatch,tmp_path,rows):
    monkeypatch.setattr(asr,'_main_worker_python',lambda:sys.executable)
    monkeypatch.setattr(asr,'SCRIPT_DIR',str(Path(asr.__file__).resolve().parents[2]))
    monkeypatch.setattr(asr,'_run_isolated_asr_worker',lambda *a,**k:{'results':rows})
    pcm=np.ones(3,dtype=np.float32)
    with pytest.raises(RuntimeError,match='missing, reordered or duplicate'):
        asr._transcribe_qwen_worker(pcm,[dict(start=0,end=1,audio=(pcm,16000))],'model',context='真实标题',evidence_root=str(tmp_path))

def test_particle_refusal_and_supported_homophone_and_manual():
    primary='温酒斩华雄啊你';ref='温酒斩华雄啊哦'
    assert arbitrate(primary,ref,ref)['accepted_spans']==[]
    assert reference_consensus_edits(primary,[ref,ref])==[]
    row=core.SpeechSegment(segment_id=49,start=92.78,end=93.81,text=primary,confidence=.78,words=[],moss_text=primary,firered_text=ref,qwen_asr_text=ref)
    apply_reference_consensus_corrections([row]);assert row.text==primary and row.caption_arbitration['accepted_spans']==[]
    assert row.caption_arbitration['unresolved_spans'][0]['to']=='哦'
    assert reference_consensus_edits('例如环境易散',['例如环境易赛']*2)[0]['to']=='赛'
    row.manual_text='用户确认正文';apply_reference_consensus_corrections([row]);assert row.text=='用户确认正文'

def test_worker_batch_pcm_and_tail_protocol_only(monkeypatch,tmp_path):
    jobs=[];arrays=[]
    for n in range(3):
        pcm=np.array([.1234567+n],dtype=np.float32);arrays.append(pcm);path=tmp_path/f'{n}.npy';np.save(path,pcm,allow_pickle=False)
        jobs.append(dict(segment_id=n+1,path=str(path),context='标题术语',samples=1,pcm_sha256=hashlib.sha256(pcm.tobytes()).hexdigest(),start=n,end=n+1))
    policy=dict(version='qwen-worker-shared-float32-v1',audio_format='float32-mono-npy-v1',sample_rate=16000,batch_size=2,max_new_tokens=160)
    m=tmp_path/'manifest.json';m.write_text(json.dumps(dict(jobs=jobs,policy=policy)),'utf8');out=tmp_path/'out.json';calls=[]
    torch=types.SimpleNamespace(__version__='TEST-ONLY',bfloat16='bf16',float16='fp16',cuda=types.SimpleNamespace(is_available=lambda:True,is_bf16_supported=lambda:True,empty_cache=lambda:None))
    class Qwen:
        @staticmethod
        def from_pretrained(*a,**k):
            assert k['max_inference_batch_size']==2 and k['max_new_tokens']==160
            return Qwen()
        def transcribe(self,**k):
            calls.append(k);return [types.SimpleNamespace(text='测试窗口',confidence=None) for _ in k['audio']]
    monkeypatch.setitem(sys.modules,'torch',torch);monkeypatch.setitem(sys.modules,'qwen_asr',types.SimpleNamespace(Qwen3ASRModel=Qwen))
    monkeypatch.setattr('twobyteasr.model_integrity.verify_model_files',lambda *a,**k:None)
    monkeypatch.setattr(sys,'argv',['worker','--manifest',str(m),'--output',str(out),'--model-dir',str(tmp_path)])
    runpy.run_path(str(Path(asr.__file__).resolve().parents[2]/'qwen_asr_worker.py'),run_name='__main__')
    assert [len(c['audio']) for c in calls]==[2,1]
    for got,want in zip([a[0] for c in calls for a in c['audio']],arrays):assert np.array_equal(got,want)
    result=json.loads(out.read_text('utf8'));assert [r['segment_id'] for r in result['results']]==[1,2,3] and result['policy']==policy
    for received,sent in zip(result['results'],jobs):
        assert received['samples']==sent['samples'] and received['pcm_sha256']==sent['pcm_sha256']
        assert received['context_sha256']==hashlib.sha256(sent['context'].encode('utf8')).hexdigest()
    # Corrupt only the final short batch's PCM: no partial success receipt can
    # replace the retained successful output.
    before=out.read_bytes();np.save(jobs[-1]['path'],np.array([99],dtype=np.float32),allow_pickle=False)
    with pytest.raises(SystemExit) as failed:
        runpy.run_path(str(Path(asr.__file__).resolve().parents[2]/'qwen_asr_worker.py'),run_name='__main__')
    assert failed.value.code==1 and out.read_bytes()==before
