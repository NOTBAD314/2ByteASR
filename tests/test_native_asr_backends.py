import base64
import hashlib
import json
from types import SimpleNamespace
from urllib.parse import urlsplit,parse_qs
import numpy as np
import pytest
from twobyteasr.qwen31_asr import SentenceRevisions,ASRProtocolError,FLASH,FILETRANS
from twobyteasr.spark_asr import DynamicTranscript,MODEL,URL,signed_url


def sentence(text='你好。',sid=1,**extra):
    return dict(sentence_id=sid,channel_id=0,begin_time=0,end_time=1000,text=text,sentence_end=True,**extra)


def test_flash_revisions_replace_previous_native_speaker_and_preserve_punctuation():
    state=SentenceRevisions(native=True)
    row=sentence(words=[dict(text='你好',punctuation='。',begin_time=0,end_time=900,speaker_id=0)])
    state.consume({'output':{'sentences':[row]}})
    row['words'][0]['speaker_id']=2
    state.consume({'output':{'sentences':[row]}})
    result=state.result(2)
    assert len(result['segments'])==1 and result['words'][0]['speaker']==2
    assert result['words'][0]['word']=='你好。' and result['words'][0]['end']==.9


def test_flash_short_final_only_never_loses_cumulative_text():
    state=SentenceRevisions()
    state.consume({'output':{'text':'前一句。后一句。','sentence':sentence('后一句。',2)}})
    result=state.result(5)
    assert result['text']=='前一句。后一句。' and not result['words']
    assert result['segments'][0]['end']==5 and result['timing_granularity']=='coarse'


def test_flash_nested_envelope_keeps_outer_cumulative_text():
    state=SentenceRevisions()
    state.consume({'output':{'text':'前一句。后一句。','output':{'sentence':sentence('后一句。',2)}}})
    assert state.result(5)['text']=='前一句。后一句。'


def test_protocol_deadline_and_non_diarizing_primary_remains_valid(tmp_path):
    from twobyteasr.cloud_asr_jobs import transcribe_chunks,worker_timeout
    from twobyteasr.cloud_asr_jobs import validate_speaker_strategy
    # Choosing a non-diarizing primary remains valid; no independent model is
    # selected and genuine native labels returned by any provider are retained.
    endpoint=dict(model=MODEL,speaker_source='native')
    assert validate_speaker_strategy(endpoint) is endpoint
    assert worker_timeout(MODEL,7200*16000)>7200
    assert worker_timeout(FILETRANS,16000)>7200


def test_flash_unfixed_words_cannot_erase_final_text_or_become_speaker():
    state=SentenceRevisions()
    state.consume({'output':{'sentence':sentence(words=[dict(text='你好',begin_time=0,end_time=900,fixed=False,speaker_id=4)])}})
    result=state.result(2)
    assert not result['words'] and 'speaker' not in result['segments'][0]
    state.consume({'output':{'sentence':{**sentence(), 'sentence_end':False}}})
    with pytest.raises(ASRProtocolError,match='未完成'):state.result(2)


def spark_packet(sn,text,status=1,**extra):
    content=dict(sn=sn,ws=[dict(cw=[dict(w=text),dict(w='错误备选')])],**extra)
    return dict(header=dict(code=0,status=status),payload=dict(result=dict(text=base64.b64encode(json.dumps(content).encode()).decode())))


def test_spark_business_sequence_replacement_not_transport_sequence():
    state=DynamicTranscript()
    state.consume(spark_packet(1,'错'));state.consume(spark_packet(2,'文'))
    state.consume(spark_packet(5,'正文',pgs='rpl',rg=[1,2]))
    state.consume(spark_packet(6,'。',status=2))
    assert state.result()['text']=='正文。' and not state.result()['words']
    with pytest.raises(ASRProtocolError):DynamicTranscript().result()


def test_spark_signature_exact_endpoint_credentials_and_tls(monkeypatch):
    endpoint=dict(url=URL,model=MODEL,app_id='app',api_key='key',api_secret='secret')
    signed=signed_url(endpoint,now=0);query=parse_qs(urlsplit(signed).query)
    auth=base64.b64decode(query['authorization'][0]).decode()
    assert 'hmac-sha256' in auth and query['host']==['iat.cn-huabei-1.xf-yun.com']
    from twobyteasr.spark_asr import transcribe
    import ssl
    packets=[]
    class Socket:
        def send(self,body):packets.append(json.loads(body))
        def recv(self,**kw):
            import time
            while not packets or packets[-1]['header']['status']!=2:time.sleep(.001)
            return json.dumps(spark_packet(1,'好',status=2))
        def close(self):pass
    def connect(uri,**kw):
        assert kw['ssl'].verify_mode==ssl.CERT_REQUIRED and kw['ssl'].check_hostname
        return Socket()
    result=transcribe(np.zeros(160),endpoint,connection_factory=connect)
    assert result['text']=='好'
    assert packets[0]['parameter']['iat']['fa_nbest'] is True
    assert packets[0]['parameter']['iat']['eos']==60000
    assert packets[-1]['payload']['audio']['status']==2


def test_spark_early_server_close_rejects_missing_tail():
    from twobyteasr.spark_asr import transcribe
    class Early:
        def send(self,*a):pass
        def recv(self,**kw):return json.dumps(spark_packet(1,'仅开头',status=2))
        def close(self):pass
    with pytest.raises(ASRProtocolError,match='尾部音频'):
        transcribe(np.zeros(16000),dict(url=URL,model=MODEL,app_id='a',api_key='k',api_secret='s'),connection_factory=lambda *a,**kw:Early())


def test_chunks_cover_all_samples_retry_only_unfinished_and_offset_once(tmp_path):
    from twobyteasr.cloud_asr_jobs import transcribe_chunks,chunk_ranges
    wave=np.ones(121*16000,dtype=np.float32)*.1
    ranges=list(chunk_ranges(wave))
    assert ranges[0][0]==0 and ranges[-1][1]==len(wave)
    assert all(b==c for (_,b),(c,_) in zip(ranges,ranges[1:]))
    assert all(b-a<=60*16000 for a,b in ranges)
    endpoint=dict(model=MODEL,provider='spark_asr_v2',protocol='spark_wss',url=URL,api_key='k',speaker_source='single')
    calls=[]
    def call(audio,e,**kw):
        calls.append(len(audio))
        if len(calls)==2:raise RuntimeError('network')
        return dict(text='原文',segments=[dict(start=.1,end=.5,text='原文')])
    with pytest.raises(RuntimeError):transcribe_chunks(wave,endpoint,tmp_path,caller=call)
    rows=transcribe_chunks(wave,endpoint,tmp_path,caller=call)
    assert len(calls)==4 and len(rows)==3
    assert [r['start'] for r in rows]==[.1,55.1,110.1]
    assert all('speaker' not in r for r in rows)


class Response:
    def __init__(self,data,code=200):self.data=data;self.status_code=code
    def json(self):return self.data


class Storage:
    def __init__(self):self.uploads=0;self.deletes=0
    def upload_audio(self,*a):self.uploads+=1;return SimpleNamespace(key='owned/audio.wav')
    def create_download_url(self,*a,**kw):return 'https://bucket.example.com/audio.wav?secret=signature'
    def verify_download_url(self,url):pass
    def delete_object(self,key,**kw):assert key=='owned/audio.wav';self.deletes+=1


def test_filetrans_resume_same_remote_task_and_word_speaker_precedence(tmp_path):
    from twobyteasr.cloud_asr_jobs import filetrans
    storage=Storage();calls=[];fail=[True]
    payload={'transcripts':[{'text':'你好。','sentences':[sentence(speaker_id=1,words=[dict(text='你好',punctuation='。',begin_time=0,end_time=900,speaker_id=2)])]}]}
    class Client:
        @staticmethod
        def post(url,**kw):
            calls.append(('post',url));assert kw['json']['parameters']=={'channel_id':[0],'diarization_enabled':True}
            return Response({'output':{'task_id':'id1','task_status':'PENDING'}})
        @staticmethod
        def get(url,**kw):
            calls.append(('get',url))
            if fail[0]:fail[0]=False;raise OSError('network')
            if '/tasks/' in url:return Response({'output':{'task_status':'SUCCEEDED','results':[{'subtask_status':'SUCCEEDED','transcription_url':'https://result.example.com/x?sig=secret'}]}})
            assert 'headers' not in kw
            return Response(payload)
    endpoint=dict(model=FILETRANS,provider='qwen31_filetrans',protocol='dashscope_filetrans',url='https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription',api_key='key',speaker_source='native')
    audio=np.zeros(32000)
    with pytest.raises(OSError):filetrans(audio,endpoint,tmp_path,storage,client=Client)
    assert storage.deletes==0
    rows=filetrans(audio,endpoint,tmp_path,storage,client=Client)
    assert len([c for c in calls if c[0]=='post'])==1 and storage.uploads==1 and storage.deletes==1
    assert rows[0]['speaker']=='API_S02' and rows[0]['tokens'][0]['end']==.9
    assert rows[0]['timestamp_source']=='qwen31_native_word' and rows[0]['native_timing_owner']
    disk=''.join(p.read_text('utf8') for p in tmp_path.rglob('*.json'))
    assert '?sig=' not in disk and 'secret=signature' not in disk and 'Bearer' not in disk


def test_filetrans_uncertain_submission_not_automatically_resubmitted(tmp_path):
    from twobyteasr.cloud_asr_jobs import filetrans
    storage=Storage();calls=[]
    class Client:
        @staticmethod
        def post(*a,**kw):calls.append(1);raise OSError('lost response')
    endpoint=dict(model=FILETRANS,provider='qwen31_filetrans',protocol='dashscope_filetrans',url='https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription',api_key='key')
    with pytest.raises(OSError):filetrans(np.zeros(32000),endpoint,tmp_path,storage,client=Client)
    with pytest.raises(ASRProtocolError,match='禁止|阻止'):filetrans(np.zeros(32000),endpoint,tmp_path,storage,client=Client)
    assert len(calls)==1 and storage.uploads==1


def test_explicit_retry_archives_failed_filetrans_task_without_reupload(tmp_path):
    from twobyteasr.cloud_asr_jobs import filetrans,job_root,save
    endpoint=dict(model=FILETRANS,provider='qwen31_filetrans',protocol='dashscope_filetrans',
        url='https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription',api_key='key')
    audio=np.zeros(16000);root=job_root(audio,endpoint,tmp_path)
    save(root/'task.json',dict(task_id='old',status='FAILED',object_key='owned/audio.wav'))
    class Client:
        @staticmethod
        def post(*a,**kw):return Response({'output':{'task_id':'new','task_status':'PENDING'}})
        @staticmethod
        def get(*a,**kw):raise OSError('pause new task')
    storage=Storage()
    with pytest.raises(ASRProtocolError):filetrans(audio,endpoint,tmp_path,storage,client=Client)
    with pytest.raises(OSError):filetrans(audio,endpoint,tmp_path,storage,client=Client,restart_terminal=True)
    assert storage.uploads==0
    assert json.loads((root/'task.json').read_text())['task_id']=='new'
    assert json.loads(next(root.glob('previous-task-*.json')).read_text())['task_id']=='old'


def test_owned_worker_uses_frozen_settings_and_endpoint(monkeypatch,tmp_path):
    from twobyteasr import asr_api_process,asr
    from twobyteasr.runtime import RuntimeContext,activate_runtime_context
    captured=[]
    endpoint=dict(model=FILETRANS,provider='qwen31_filetrans',protocol='dashscope_filetrans',url='https://example.com',api_key='private')
    context=RuntimeContext(asr_endpoint_snapshot=endpoint,asr_settings_snapshot={'models':{'oss_bucket':'frozen-bucket'}},speaker_source='native')
    monkeypatch.setattr(asr,'_legacy_runtime_value',lambda *a:{'models':{'oss_bucket':'changed-bucket'}})
    monkeypatch.setattr(asr,'build_qwen_asr_context',lambda *a:'')
    monkeypatch.setattr('twobyteasr.terminology.runtime_snapshot',lambda:SimpleNamespace(canonical_terms=['S0pp']))
    monkeypatch.setattr('twobyteasr.llm_config.read_oss_credentials',lambda:('frozen-id','frozen-secret'))
    monkeypatch.setattr('twobyteasr.runtime_registry.resolve_runtime_python',lambda *a:'python')
    def run(*a,**kw):captured.append(json.loads(kw['input_text']));return {'results':[]}
    monkeypatch.setattr(asr,'_run_isolated_asr_worker',run)
    with activate_runtime_context(context):
        asr_api_process.transcribe('fixture.wav',[dict(start=0,end=1,audio=(np.zeros(16000),16000))])
    assert captured[0]['settings']['models']['oss_bucket']=='frozen-bucket'
    assert captured[0]['endpoint']['model']==FILETRANS
    assert captured[0]['storage_credentials']==['frozen-id','frozen-secret']
    assert captured[0]['endpoint']['vocabulary']=={'S0pp':2}


def test_filetrans_hints_preserve_canonical_spelling_and_pack_without_silent_tail_cut():
    from twobyteasr.qwen31_asr import filetrans_hints
    terms=['S0pp','BerLIN','Zhe']+[f'Player{i:04d}' for i in range(100)]
    hints=filetrans_hints(terms)
    assert [hints['vocabulary'][x] for x in terms]==[2]*len(terms)
    assert 'sopp' not in hints['vocabulary'] and 'Berlin' not in hints['vocabulary']
    message=hints['filetrans_context'][0]
    assert message['role']=='user' and message['content'][0]['type']=='input_text'
    assert len(message['content'][0]['text'])<=400
    assert hints['hint_counts']['context_omitted_terms']>0
    assert hints['filetrans_vocabulary_dropped']==[] and hints['hint_counts']['vocabulary_dropped']==0
    # 2026-10-17: an over-limit term is skipped and listed, not a failed request.
    hints=filetrans_hints(['中文'*8])
    assert hints['vocabulary']=={} and hints['filetrans_context']==[]
    assert hints['filetrans_vocabulary_dropped']==[{'term':'中文'*8,'reason':'non_ascii_longer_than_15_characters'}]


def test_filetrans_hints_skip_over_limit_terms_and_keep_the_ranked_rest():
    from twobyteasr.qwen31_asr import filetrans_hints
    long_row='这是用户个人词库里写成一整句的说明行'
    terms=['S0pp',long_row,'中'*15,'one two three four five six seven','one two three four five six seven eight',
           '换\n行','BerLIN']
    hints=filetrans_hints(terms)
    assert list(hints['vocabulary'])==['S0pp','中'*15,'one two three four five six seven','BerLIN']
    text=hints['filetrans_context'][0]['content'][0]['text']
    assert text.endswith('：S0pp、'+'中'*15+'、one two three four five six seven、BerLIN')
    assert long_row not in text
    assert hints['filetrans_vocabulary_dropped']==[
        {'term':long_row,'reason':'non_ascii_longer_than_15_characters'},
        {'term':'one two three four five six seven eight','reason':'ascii_more_than_7_words'},
        {'term':'换\n行','reason':'contains_line_break'}]
    assert hints['hint_counts']['native_vocabulary']==4 and hints['hint_counts']['vocabulary_dropped']==3


def test_filetrans_hints_send_the_first_2000_ranked_terms():
    from twobyteasr.qwen31_asr import filetrans_hints
    terms=[f'T{i:04d}' for i in range(2300)]
    hints=filetrans_hints(['中文'*8]+terms)
    assert list(hints['vocabulary'])==terms[:2000]
    dropped=hints['filetrans_vocabulary_dropped']
    assert dropped[0]['reason']=='non_ascii_longer_than_15_characters'
    assert {row['reason'] for row in dropped[1:]}=={'over_2000_terms'} and dropped[1]['term']=='T2000'
    assert len(dropped)==200 and hints['hint_counts']['vocabulary_dropped']==301


def test_filetrans_hints_still_reject_a_wrong_compiled_vocabulary_binding():
    from twobyteasr.qwen31_asr import filetrans_hints
    with pytest.raises(ASRProtocolError) as error:
        filetrans_hints(['S0pp','中文'*8],vocabulary_id='library',vocabulary_model='qwen-audio-3.0-asr-flash-filetrans')
    assert error.value.category=='vocabulary_model_mismatch'
    hints=filetrans_hints(['S0pp','中文'*8],vocabulary_id='library',vocabulary_model=FILETRANS)
    assert hints['vocabulary_id']=='library' and list(hints['vocabulary'])==['S0pp']


def test_owned_worker_gets_filetrans_hints_without_the_long_term(monkeypatch):
    from twobyteasr import asr_api_process
    from twobyteasr import asr
    from twobyteasr.runtime import RuntimeContext,activate_runtime_context
    captured=[];events=[]
    endpoint=dict(model=FILETRANS,provider='qwen31_filetrans',protocol='dashscope_filetrans',url='https://example.com',api_key='private')
    context=RuntimeContext(asr_endpoint_snapshot=endpoint,asr_settings_snapshot={'models':{}},speaker_source='native')
    monkeypatch.setattr(asr,'build_qwen_asr_context',lambda *a:'')
    monkeypatch.setattr('twobyteasr.terminology.runtime_snapshot',lambda:SimpleNamespace(canonical_terms=['S0pp','中文'*8]))
    monkeypatch.setattr('twobyteasr.llm_config.read_oss_credentials',lambda:('id','secret'))
    monkeypatch.setattr('twobyteasr.runtime_registry.resolve_runtime_python',lambda *a:'python')
    monkeypatch.setattr('twobyteasr.cache.record_run_event',lambda kind,**kw:events.append((kind,kw)))
    def run(*a,**kw):captured.append(json.loads(kw['input_text']));return {'results':[]}
    monkeypatch.setattr(asr,'_run_isolated_asr_worker',run)
    with activate_runtime_context(context):
        asr_api_process.transcribe('fixture.wav',[dict(start=0,end=1,audio=(np.zeros(16000),16000))])
    sent=captured[0]['endpoint']
    assert sent['vocabulary']=={'S0pp':2}
    assert sent['filetrans_vocabulary_dropped']==[{'term':'中文'*8,'reason':'non_ascii_longer_than_15_characters'}]
    hint_event=next(kw for kind,kw in events if kind=='cloud_request_hints')
    assert hint_event['native_vocabulary']==1 and hint_event['vocabulary_dropped']==1


def test_compiled_vocabulary_real_binding_is_checked_before_audio_upload(tmp_path):
    from twobyteasr.cloud_asr_jobs import filetrans
    storage=Storage();calls=[]
    endpoint=dict(model=FILETRANS,provider='qwen31_filetrans',protocol='dashscope_filetrans',
        url='https://my-workspace.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/asr/transcription',
        api_key='key',vocabulary_id='owned-library',vocabulary_model=FILETRANS,vocabulary={'S0pp':2})
    class Client:
        @staticmethod
        def post(url,**kw):
            calls.append(url)
            assert url.startswith('https://my-workspace.') and url.endswith('/asr/customization')
            assert kw['json']['input']['action']=='query_vocabulary'
            return Response({'output':{'status':'OK','target_model':'qwen-audio-3.0-asr-flash-filetrans','vocabulary':[]}})
    with pytest.raises(ASRProtocolError,match='绑定了其它模型'):
        filetrans(np.zeros(16000),endpoint,tmp_path,storage,client=Client)
    assert storage.uploads==0 and len(calls)==1


def test_filetrans_rejects_succeeded_failed_subtask_without_result_fetch_or_reupload(tmp_path):
    from twobyteasr.cloud_asr_jobs import filetrans
    storage=Storage();posts=[];gets=[]
    class Client:
        @staticmethod
        def post(*a,**kw):posts.append(1);return Response({'output':{'task_id':'same','task_status':'PENDING'}})
        @staticmethod
        def get(url,**kw):
            gets.append(url)
            return Response({'output':{'task_status':'SUCCEEDED','results':[{'subtask_status':'FAILED','code':'InvalidAudio'}]}})
    endpoint=dict(model=FILETRANS,provider='qwen31_filetrans',protocol='dashscope_filetrans',
        url='https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription',api_key='key')
    for _ in range(2):
        with pytest.raises(ASRProtocolError,match='子任务未成功'):
            filetrans(np.zeros(16000),endpoint,tmp_path,storage,client=Client)
    assert storage.uploads==1 and storage.deletes==0 and len(posts)==1 and len(gets)==2


@pytest.mark.parametrize('remote_status',['PENDING','RUNNING'])
def test_local_cancel_preserves_remote_task_and_does_not_claim_cancellation(tmp_path,remote_status):
    from twobyteasr.cloud_asr_jobs import filetrans
    storage=Storage();posts=[];cancelled=[False]
    class Client:
        @staticmethod
        def post(url,**kw):
            posts.append(url)
            return Response({'output':{'task_id':'same','task_status':'PENDING'}})
        @staticmethod
        def get(*a,**kw):return Response({'output':{'task_status':remote_status}})
    def check():
        if cancelled[0]:raise RuntimeError('local cancel')
    def progress(state,*a):
        if state==remote_status:cancelled[0]=True
    endpoint=dict(model=FILETRANS,provider='qwen31_filetrans',protocol='dashscope_filetrans',
        url='https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription',api_key='key')
    with pytest.raises(RuntimeError,match='local cancel'):
        filetrans(np.zeros(16000),endpoint,tmp_path,storage,client=Client,check=check,progress=progress)
    state=json.loads(next(tmp_path.rglob('task.json')).read_text('utf8'))
    assert state['local_cancel_requested'] and state['task_id']=='same' and state['status']==remote_status
    assert not state.get('remote_cancel_confirmed') and storage.deletes==0
    assert len(posts)==(2 if remote_status=='PENDING' else 1)


def test_filetrans_native_bad_word_timing_is_rejected_before_clamping():
    from twobyteasr.cloud_asr_jobs import validate_filetrans_result
    payload={'transcripts':[{'sentences':[sentence(words=[{'begin_time':500,'end_time':400}])]}]}
    with pytest.raises(ASRProtocolError,match='词时间非法'):
        validate_filetrans_result(payload,1)
