"""Resumable native ASR jobs executed inside the existing owned API process."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from .qwen31_asr import ASRProtocolError, FLASH, FILETRANS  # noqa: F401  (FILETRANS kept for callers)
from .spark_asr import MODEL as SPARK


def validate_speaker_strategy(endpoint):
    # Native-only is a policy, not a demand for nonexistent model capability.
    # Spark remains a valid primary selection and never starts another model.
    return endpoint


def worker_timeout(model, samples):
    import math
    from .qwen31_asr import is_filetrans_model
    from .mosi_asr import MODEL as MOSI_MODEL, worker_timeout_seconds as mosi_timeout
    seconds=samples/16000
    if model==SPARK:return max(3600,seconds+math.ceil(seconds/51)*65+120)
    if model==FLASH:return max(3600,math.ceil(seconds/291)*200+120)
    if is_filetrans_model(model):return 9300
    if model==MOSI_MODEL:return mosi_timeout(seconds)
    return 3600


def public_identity(endpoint):
    from .network_policy import public_url
    hints={k:endpoint.get(k) for k in ('vocabulary','vocabulary_id','vocabulary_model','filetrans_context')}
    # Keys added 2026-10-13 join the hash only when set, so in-flight jobs of
    # the existing Qwen-Audio-3.1 route keep their cache directory.
    hints.update({k:endpoint[k] for k in ('filetrans_language','mosi_keyterms','mosi_diarize')
                  if endpoint.get(k) is not None})
    return dict(version=2,provider=endpoint.get('provider'), model=endpoint.get('model'),
                protocol=endpoint.get('protocol'),url=public_url(endpoint.get('url','')),
                speaker_source=endpoint.get('speaker_source','single'),
                native_hints_sha256=hashlib.sha256(json.dumps(hints,
                    ensure_ascii=False,sort_keys=True).encode('utf8')).hexdigest())


def save(path, payload):
    from .theme_persistence import write_text_atomic
    from .speaker_evidence import public_evidence
    write_text_atomic(path, json.dumps(public_evidence(payload),ensure_ascii=False,indent=2))


def job_root(audio, endpoint, cache_root):
    import numpy as np
    digest=hashlib.sha256(np.asarray(audio,dtype='<f4').tobytes()).hexdigest()
    identity=public_identity(endpoint)
    identity.update(audio_sha256=digest, samples=len(audio), sample_rate=16000)
    # Account changes invalidate reuse without ever persisting credentials.
    identity['account_fingerprint']=hashlib.sha256(str(endpoint.get('api_key','')).encode()).hexdigest()
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    root=Path(cache_root)/'native-asr-v1'/key;root.mkdir(parents=True,exist_ok=True)
    save(root/'input.json',identity)
    return root


def validate_filetrans_result(payload, duration):
    """Reject malformed native timing before the compatibility parser can clamp it."""
    from .qwen31_asr import seconds
    if not isinstance(payload,dict) or not isinstance(payload.get('transcripts'),list):
        raise ASRProtocolError('Filetrans结果缺少transcripts', 'parse_failed')
    for transcript in payload['transcripts']:
        if not isinstance(transcript,dict) or not isinstance(transcript.get('sentences',[]),list):
            raise ASRProtocolError('Filetrans句列表格式非法', 'parse_failed')
        for sentence in transcript.get('sentences',[]):
            if not isinstance(sentence,dict): raise ASRProtocolError('Filetrans句格式非法','parse_failed')
            start,end=seconds(sentence.get('begin_time')),seconds(sentence.get('end_time'))
            # A zero-length sentence/word is a point the provider measured, not
            # a reason to throw away a paid job (2026-10-14); reversed or
            # out-of-range times still are.
            if not 0 <= start <= end <= duration + .1:
                raise ASRProtocolError('Filetrans原生句时间非法或越出提交音频', 'invalid_timing')
            if not isinstance(sentence.get('words',[]),list):
                raise ASRProtocolError('Filetrans词列表格式非法','parse_failed')
            for word in sentence.get('words',[]):
                if not isinstance(word,dict): raise ASRProtocolError('Filetrans词格式非法','parse_failed')
                ws,we=seconds(word.get('begin_time')),seconds(word.get('end_time'))
                if not start - .01 <= ws <= we <= end + .01:
                    raise ASRProtocolError('Filetrans原生词时间非法或越出所属句', 'invalid_timing')


def verify_compiled_vocabulary(endpoint, vocabulary, client, headers, root):
    """Read the actual workspace binding; a saved model label is not proof."""
    vocabulary_id=endpoint.get('vocabulary_id')
    if not vocabulary_id:return
    base=str(endpoint['url'])
    marker='/api/v1/'
    if marker not in base:
        raise ASRProtocolError('无法确定当前工作空间的热词库查询端点。', 'vocabulary_model_mismatch')
    response=client.post(base.split(marker,1)[0]+'/api/v1/services/audio/asr/customization',
        headers=headers,json=dict(model='speech-biasing',input=dict(action='query_vocabulary',
        vocabulary_id=vocabulary_id)),timeout=(10,60),allow_redirects=False)
    if response.status_code!=200:
        raise ASRProtocolError(f'热词库绑定核对HTTP {response.status_code}；未上传或提交音频。', 'vocabulary_model_mismatch')
    output=response.json().get('output') or {}
    if output.get('status')!='OK' or output.get('target_model')!=endpoint.get('model'):
        raise ASRProtocolError('当前工作空间热词库不可用或绑定了其它模型；未提交音频。','vocabulary_model_mismatch')
    compiled=output.get('vocabulary')
    if not isinstance(compiled,list) or any(not isinstance(x,dict) or not isinstance(x.get('text'),str) for x in compiled):
        raise ASRProtocolError('热词库查询结果缺少有效词条。','invalid_response')
    if len(compiled)+len(vocabulary)>2000:
        raise ASRProtocolError('预编译与本场热词总计超过2000项，已阻止服务端随机采样。','input_limit')
    save(root/'vocabulary-binding.json',dict(target_model=output['target_model'],status=output['status'],
        compiled_count=len(compiled),instantaneous_count=len(vocabulary)))


def filetrans_result_url(output):
    """Result file URL of a SUCCEEDED query, for both documented shapes.

    Qwen-Audio-3.1 Filetrans: ``output.results[]`` with one SUCCEEDED subtask.
    Qwen3-ASR Filetrans: ``output.result.transcription_url`` (example shows a
    plain-http Alibaba OSS URL; it is requested over https instead).
    """
    from urllib.parse import urlsplit, urlunsplit
    if isinstance(output.get('result'),dict) and output['result'].get('transcription_url'):
        url=str(output['result']['transcription_url'])
    else:
        results=output.get('results') or []
        if len(results)!=1 or results[0].get('subtask_status')!='SUCCEEDED':
            raise ASRProtocolError('Filetrans单文件子任务未成功','subtask_failed')
        url=str(results[0].get('transcription_url',''))
    parts=urlsplit(url)
    if parts.scheme=='http' and str(parts.hostname or '').endswith('.aliyuncs.com'):
        url=urlunsplit(('https',)+tuple(parts[1:]))
    return url


def _service_error(response, endpoint, category, suffix=''):
    """A provider refusal explained for a person (balance, key, model, ...)."""
    from .dashscope_service import _json, explain
    problem=explain(response.status_code,_json(response),model=str(endpoint.get('model') or ''),
                    host=urlsplit(str(endpoint.get('url') or '')).hostname or '')
    error=ASRProtocolError(f'{problem.text()}{suffix}（HTTP {response.status_code}'
                           + (f' {problem.code}' if problem.code else '') + '）',category)
    error.problem=problem
    return error


def chunk_ranges(audio, max_seconds=55):
    """Contiguous, nonoverlapping bounded chunks; prefer a quiet recent cut.

    No offsets removed, silence time compressed or textual overlap deduplicated.
    Full samples, including the final tail, belong to exactly one request.
    """
    import numpy as np
    start=0;limit=int(max_seconds*16000)
    while start < len(audio):
        end=min(len(audio),start+limit)
        if end < len(audio) and end-start > 5*16000:
            lo=end-4*16000
            windows=np.asarray(audio[lo:end],dtype=np.float64).reshape(-1,3200)
            quiet=int(np.argmin(np.mean(windows*windows,axis=1)))
            if np.mean(windows[quiet]*windows[quiet]) < .0004:
                end=lo+quiet*3200+1600
        yield start,end
        start=end


def transcribe_chunks(audio, endpoint, cache_root, *, check=lambda:None, progress=lambda *a:None, caller=None):
    from .asr import _api_transcription_rows
    from .speaker_evidence import scope_request_speakers
    validate_speaker_strategy(endpoint)
    root=job_root(audio,endpoint,cache_root)
    ranges=list(chunk_ranges(audio,55 if endpoint['model']==SPARK else 295))
    rows=[]
    for index,(start,end) in enumerate(ranges):
        check();path=root/f'chunk-{start}-{end}.json'
        if path.is_file():
            payload=json.loads(path.read_text('utf8'));progress('cached',index,len(ranges))
        else:
            progress('request',index,len(ranges))
            from .qwen31_asr import flash
            from .spark_asr import transcribe
            run=caller or (transcribe if endpoint['model']==SPARK else flash)
            chunk_endpoint={**endpoint,'audit_root':str(root/'evidence'),'audit_request':f'chunk-{index}'}
            try:
                payload=run(audio[start:end],chunk_endpoint,check=check)
            except Exception as exc:
                save(root/'failure.json',dict(chunk=index,completed_chunks=index,category=getattr(exc,'category','request_failed'),
                    message='本块失败；成功块已保留。下一次显式重试仅请求未完成块。'))
                raise
            check();save(path,payload)
        converted=_api_transcription_rows(payload,dict(start=start/16000,end=end/16000))
        if any(row.get('speaker') is not None for row in converted):
            converted=scope_request_speakers(converted,index,len(ranges))
        rows.extend(converted);progress('completed',index+1,len(ranges))
    return rows


def filetrans(audio, endpoint, cache_root, storage, *, check=lambda:None, progress=lambda *a:None,
              client=None, max_wait=7200, sleep=time.sleep, auto_delete=True, restart_terminal=False):
    from . import network_policy
    from .asr import _pcm16_wav_bytes, _filetrans_task_url, _filetrans_task_rows, _api_transcription_rows
    from .speaker_evidence import scope_request_speakers
    client=client or network_policy
    import numpy as np
    samples = np.asarray(audio)
    if samples.ndim != 1 or not np.isfinite(samples).all():
        raise ASRProtocolError('Filetrans输入必须是有效的16kHz单声道分析音频。', 'input_limit')
    duration=len(audio)/16000
    from .qwen31_asr import filetrans_spec
    spec=filetrans_spec(endpoint.get('model'))
    model=spec.model
    native=spec.diarization and endpoint.get('speaker_source') in {'native','filetrans'}
    if not 0 < duration <= spec.max_hours*3600:
        raise ASRProtocolError(f'录音文件识别单个文件最长{spec.max_hours:g}小时（官方限制）；请先缩小识别范围。', 'input_limit')
    if '/api/v1/' not in str(endpoint.get('url') or ''):
        raise ASRProtocolError('Filetrans端点缺少当前工作空间API根路径；已阻止使用其它地域默认查询地址。','input_limit')
    if native and duration>spec.diarization_max_hours*3600:
        raise ASRProtocolError('本模型原生说话人任务限2小时；请先选择不超过2小时的识别范围。', 'input_limit')
    # The source may be a large video, but the submitted object is our own
    # 16-bit mono WAV. Validate that exact container before upload/allocation.
    if len(samples) * 2 + 44 > 2_000_000_000:
        raise ASRProtocolError('实际提交的WAV超过Filetrans 2GB限制。', 'input_limit')
    parameters = {'channel_id': [0]}
    if spec.diarization: parameters['diarization_enabled'] = native
    if spec.word_timestamps == 'enable_words':
        # Word timestamps are opt-in for Qwen3-ASR Filetrans (default false).
        parameters['enable_words'] = True
    if spec.language_parameter and endpoint.get('filetrans_language'):
        parameters['language'] = str(endpoint['filetrans_language'])
    if spec.vocabulary:
        for key in ('vocabulary', 'vocabulary_id'):
            if endpoint.get(key): parameters[key] = endpoint[key]
        if endpoint.get('vocabulary_id') and endpoint.get('vocabulary_model') != model:
            raise ASRProtocolError('预编译热词库未绑定当前录音文件识别模型。', 'vocabulary_model_mismatch')
    vocabulary = parameters.get('vocabulary') or {}
    if not isinstance(vocabulary, dict) or len(vocabulary) > 2000 or any(
            not isinstance(k,str) or not k or isinstance(v,bool) or v not in (1,2,3,4,5,50)
            for k,v in vocabulary.items()):
        raise ASRProtocolError('Filetrans原生热词格式或权重非法。', 'input_limit')
    context = (endpoint.get('filetrans_context') or []) if spec.context else []
    if not isinstance(context,list) or len(context) > 5:
        raise ASRProtocolError('Filetrans上下文消息超过接口限制。', 'input_limit')
    for message in context:
        if not isinstance(message,dict) or message.get('role') != 'user' or not isinstance(message.get('content'),list):
            raise ASRProtocolError('Filetrans领域上下文必须是user/input_text消息。', 'input_limit')
        pieces=message['content']
        if any(not isinstance(p,dict) or p.get('type')!='input_text' or not isinstance(p.get('text'),str) for p in pieces) or sum(len(p['text']) for p in pieces)>400:
            raise ASRProtocolError('Filetrans每轮上下文不得超过400字符，已阻止尾部静默截断。', 'input_limit')
    root=job_root(audio,endpoint,cache_root)
    state_path=root/'task.json';raw_path=root/'result.json'
    state=json.loads(state_path.read_text('utf8')) if state_path.is_file() else {}
    headers={'Authorization':'Bearer '+endpoint['api_key']}
    check()
    if raw_path.is_file():
        payload=json.loads(raw_path.read_text('utf8'));progress('cached_result',0,1)
    else:
        if state.get('status')=='SUBMITTING' and not state.get('task_id') and restart_terminal:
            # The user checked their account and explicitly chose to submit again.
            import uuid
            save(root/('previous-task-'+uuid.uuid4().hex+'.json'),state)
            state={k:v for k,v in state.items() if k in {'object_key','created_at','native_diarization','storage_kind'}}
            state['status']='UPLOADED';save(state_path,state)
            progress('explicit_restart_uncertain',0,1)
        if state.get('status')=='SUBMITTING' and not state.get('task_id'):
            raise ASRProtocolError('上次提交是否受理未知，已阻止自动重复收费；需核对账户任务后显式处理', 'submission_uncertain')
        if state.get('status') in {'FAILED','CANCELED','UNKNOWN'}:
            if not restart_terminal:
                raise ASRProtocolError('已保存远端终态 '+state['status']+'；请显式重新开始识别', 'remote_terminal')
            import uuid
            save(root/('previous-task-'+uuid.uuid4().hex+'.json'),state)
            state={k:v for k,v in state.items() if k in {'object_key','created_at','native_diarization','storage_kind'}}
            state['status']='UPLOADED';save(state_path,state)
            progress('explicit_restart_terminal',0,1)
        if not state.get('task_id'):
            verify_compiled_vocabulary(endpoint,vocabulary,client,headers,root)
            progress('uploading',0,1)
            # The provider's own temporary upload expires after 48 hours; an
            # object that was uploaded but never submitted is uploaded again.
            max_age=getattr(storage,'max_object_age_seconds',None)
            if state.get('object_key') and max_age and time.time()-float(state.get('created_at') or 0)>max_age:
                state={k:v for k,v in state.items() if k not in {'object_key','created_at'}}
            if not state.get('object_key'):
                stored=storage.upload_audio(_pcm16_wav_bytes(audio),'wav')
                # State owns an object key, never a signed URL.
                state=dict(status='UPLOADED',object_key=stored.key,created_at=time.time(),native_diarization=native,
                           storage_kind=getattr(storage,'kind','oss'))
                save(state_path,state)
            url=storage.create_download_url(state['object_key'],ttl_seconds=86400)
            storage.verify_download_url(url)
            check();state['status']='SUBMITTING';save(state_path,state)
            inputs={'file_urls':[url]} if spec.input_field=='file_urls' else {'file_url':url}
            if context: inputs['context'] = context
            save(root/'submission-parameters.json',dict(model=model, input_field=spec.input_field,
                 parameters=parameters, context=context, hint_counts=endpoint.get('hint_counts', {}),
                 storage_kind=getattr(storage,'kind','oss')))
            from .dashscope_service import OSS_RESOLVE_HEADER, needs_oss_resolve
            if needs_oss_resolve(url): headers={**headers,**OSS_RESOLVE_HEADER}
            response=client.post(endpoint['url'],headers={**headers,'X-DashScope-Async':'enable'},
                json=dict(model=model,input=inputs,parameters=parameters),
                timeout=(10,60),allow_redirects=False)
            if response.status_code!=200:
                # Explicit auth/limit/validation refusal is safe to retry on a
                # later user run. 5xx may have accepted a job: retain uncertainty.
                state.update(status='REJECTED' if response.status_code in {400,401,403,404,413,422,429} else 'SUBMITTING',
                             http_status=response.status_code);save(state_path,state)
                raise _service_error(response,endpoint,'submission_failed')
            output=response.json().get('output') or {}
            if not output.get('task_id'):
                raise ASRProtocolError('Filetrans提交响应缺少task_id；禁止自动重提','submission_uncertain')
            state.update(task_id=str(output['task_id']),status=str(output.get('task_status') or 'PENDING'))
            save(state_path,state)
        deadline=time.monotonic()+max_wait
        try:
            while True:
                check()
                if time.monotonic()>=deadline:
                    raise ASRProtocolError('本地轮询达到时限；task_id已保存，继续将查询原任务','poll_timeout')
                response=client.get(_filetrans_task_url(endpoint,state['task_id']),headers=headers,
                                    timeout=(10,60),allow_redirects=False)
                if response.status_code!=200:
                    raise _service_error(response,endpoint,'poll_failed','（task_id 已保存，未重新提交）')
                output=response.json().get('output') or {}
                status=output.get('task_status')
                if status=='UNKNOWN':
                    # Official meaning: the task does not exist or has expired
                    # (task records and results are kept 24 hours).
                    state.update(status='UNKNOWN',last_poll_at=time.time());save(state_path,state)
                    raise ASRProtocolError('百炼查不到这个任务（不存在或已超过官方保留的24小时）；未自动重新提交。','remote_unknown')
                if status not in {'PENDING','RUNNING','SUCCEEDED','FAILED','CANCELED'}:
                    raise ASRProtocolError('Filetrans未知任务状态','invalid_response')
                state.update(status=status,last_poll_at=time.time());save(state_path,state)
                from .provider_diagnostics import redact_diagnostics
                save(root/'last-poll.json',dict(task_id=state['task_id'],status=status,
                     code=output.get('code'),message=redact_diagnostics(str(output.get('message') or '')),
                     subtask_statuses=[{'status':r.get('subtask_status'),'code':r.get('code'),
                                       'message':redact_diagnostics(str(r.get('message') or ''))}
                                      for r in output.get('results') or []]))
                progress(status,0,1)
                if status in {'FAILED','CANCELED'}:
                    failure=next((r for r in output.get('results') or [] if r.get('code')),output)
                    if status=='FAILED' and (failure.get('code') or failure.get('message')):
                        from .dashscope_service import explain
                        problem=explain(None,{'code':failure.get('code'),'message':failure.get('message')},
                                        model=model,host=urlsplit(str(endpoint.get('url') or '')).hostname or '')
                        error=ASRProtocolError('远端识别任务失败：'+problem.text(),'remote_terminal')
                        error.problem=problem
                        raise error
                    raise ASRProtocolError('Filetrans远端任务 '+status,'remote_terminal')
                if status=='SUCCEEDED':
                    url=filetrans_result_url(output)
                    from .glossary_skill import is_safe_web_url
                    if not is_safe_web_url(url)[0]:
                        raise ASRProtocolError('Filetrans结果URL不安全','invalid_result_url')
                    # No bearer token is sent to the separate signed result host.
                    result=client.get(url,timeout=(10,60),allow_redirects=False)
                    if result.status_code!=200:
                        raise ASRProtocolError(f'结果获取HTTP {result.status_code}；保留原task_id','result_fetch_failed')
                    payload=result.json()
                    validate_filetrans_result(payload,duration)
                    save(raw_path,payload)
                    break
                for _ in range(20):check();sleep(.1)
        except BaseException:
            # Only PENDING can be cancelled. RUNNING remains recoverable and may
            # continue billing remotely; do not claim server cancellation.
            try:
                check()
            except BaseException:
                state['local_cancel_requested']=True;save(state_path,state)
                if state.get('status')=='PENDING':
                    try:
                        result=client.post(_filetrans_task_url(endpoint,state['task_id'])+'/cancel',
                                           headers=headers,timeout=(5,15),allow_redirects=False)
                        state['cancel_requested']=result.status_code==200
                        cancelled_output = result.json().get('output', {}) if result.status_code==200 else {}
                        state['remote_cancel_confirmed'] = cancelled_output.get('task_status') == 'CANCELED'
                        if state['remote_cancel_confirmed']: state['status']='CANCELED'
                        save(state_path,state)
                    except Exception:pass
                progress('remote_cancel_confirmed' if state.get('remote_cancel_confirmed') else
                         'local_cancel_remote_unconfirmed',0,1)
            raise
    validate_filetrans_result(payload,duration)
    converted=_filetrans_task_rows(payload,duration)
    converted['timestamp_source'] = spec.timestamp_source
    rows=_api_transcription_rows(converted,dict(start=0,end=duration))
    if any(row.get('speaker') is not None for row in rows):
        rows=scope_request_speakers(rows,0,1)
    # Cleanup only after result is durable and parsed; failed polling never
    # deletes an upload the accepted task may still need to read.
    if auto_delete and state.get('object_key') and not state.get('object_deleted'):
        try:
            storage.delete_object(state['object_key'],strict=True);state['object_deleted']=True;save(state_path,state)
        except Exception:
            state['cleanup_pending']=True;save(state_path,state)
    return rows
