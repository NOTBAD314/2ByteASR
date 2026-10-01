"""Resumable native ASR jobs executed inside the existing owned API process."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from .qwen31_asr import ASRProtocolError, FLASH, FILETRANS
from .spark_asr import MODEL as SPARK


def validate_speaker_strategy(endpoint):
    if endpoint.get('model')==SPARK and endpoint.get('speaker_source') in {'native','filetrans'}:
        raise ASRProtocolError('Spark-ASR V2没有供应商原生说话人能力；请选择关闭或独立说话人后端。', 'unsupported_speaker_strategy')


def worker_timeout(model, samples):
    import math
    seconds=samples/16000
    if model==SPARK:return max(3600,seconds+math.ceil(seconds/51)*65+120)
    if model==FLASH:return max(3600,math.ceil(seconds/291)*200+120)
    if model==FILETRANS:return 9300
    return 3600


def public_identity(endpoint):
    from .network_policy import public_url
    return dict(version=1,provider=endpoint.get('provider'), model=endpoint.get('model'),
                protocol=endpoint.get('protocol'),url=public_url(endpoint.get('url','')),
                speaker_source=endpoint.get('speaker_source','single'))


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
        if endpoint.get('speaker_source') in {'native','filetrans'}:
            converted=scope_request_speakers(converted,index,len(ranges))
        else:
            for row in converted:row.pop('speaker',None)
        rows.extend(converted);progress('completed',index+1,len(ranges))
    return rows


def filetrans(audio, endpoint, cache_root, storage, *, check=lambda:None, progress=lambda *a:None,
              client=None, max_wait=7200, sleep=time.sleep, auto_delete=True, restart_terminal=False):
    from . import network_policy
    from .asr import _pcm16_wav_bytes, _filetrans_task_url, _filetrans_task_rows, _api_transcription_rows
    from .speaker_evidence import scope_request_speakers
    client=client or network_policy
    duration=len(audio)/16000
    native=endpoint.get('speaker_source') in {'native','filetrans'}
    if endpoint.get('model')!=FILETRANS or not 0 < duration <= 12*3600:
        raise ASRProtocolError('Filetrans模型ID错误或音频超过12小时', 'input_limit')
    if native and duration>2*3600:
        raise ASRProtocolError('原生分离按官方建议限2小时；请缩小范围或选择外部Nemotron', 'input_limit')
    root=job_root(audio,endpoint,cache_root)
    state_path=root/'task.json';raw_path=root/'result.json'
    state=json.loads(state_path.read_text('utf8')) if state_path.is_file() else {}
    headers={'Authorization':'Bearer '+endpoint['api_key']}
    check()
    if raw_path.is_file():
        payload=json.loads(raw_path.read_text('utf8'));progress('cached_result',0,1)
    else:
        if state.get('status')=='SUBMITTING' and not state.get('task_id'):
            raise ASRProtocolError('上次提交是否受理未知，已阻止自动重复收费；需核对账户任务后显式处理', 'submission_uncertain')
        if state.get('status') in {'FAILED','CANCELED'}:
            if not restart_terminal:
                raise ASRProtocolError('已保存远端终态 '+state['status']+'；请显式重新开始识别', 'remote_terminal')
            import uuid
            save(root/('previous-task-'+uuid.uuid4().hex+'.json'),state)
            state={k:v for k,v in state.items() if k in {'object_key','created_at','native_diarization'}}
            state['status']='UPLOADED';save(state_path,state)
            progress('explicit_restart_terminal',0,1)
        if not state.get('task_id'):
            progress('uploading',0,1)
            if not state.get('object_key'):
                stored=storage.upload_audio(_pcm16_wav_bytes(audio),'wav')
                # State owns an object key, never a signed URL.
                state=dict(status='UPLOADED',object_key=stored.key,created_at=time.time(),native_diarization=native)
                save(state_path,state)
            url=storage.create_download_url(state['object_key'],ttl_seconds=86400)
            storage.verify_download_url(url)
            check();state['status']='SUBMITTING';save(state_path,state)
            response=client.post(endpoint['url'],headers={**headers,'X-DashScope-Async':'enable'},
                json=dict(model=FILETRANS,input={'file_urls':[url]},parameters={'diarization_enabled':native}),
                timeout=(10,60),allow_redirects=False)
            if response.status_code!=200:
                # Explicit auth/limit/validation refusal is safe to retry on a
                # later user run. 5xx may have accepted a job: retain uncertainty.
                state.update(status='REJECTED' if response.status_code in {400,401,403,404,413,422,429} else 'SUBMITTING',
                             http_status=response.status_code);save(state_path,state)
                raise ASRProtocolError(f'Filetrans提交HTTP {response.status_code}','submission_failed')
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
                    raise ASRProtocolError(f'Filetrans查询HTTP {response.status_code}；未重新提交','poll_failed')
                output=response.json().get('output') or {}
                status=output.get('task_status')
                if status not in {'PENDING','RUNNING','SUCCEEDED','FAILED','CANCELED'}:
                    raise ASRProtocolError('Filetrans未知任务状态','invalid_response')
                state.update(status=status,last_poll_at=time.time());save(state_path,state)
                progress(status,0,1)
                if status in {'FAILED','CANCELED'}:
                    raise ASRProtocolError('Filetrans远端任务 '+status,'remote_terminal')
                if status=='SUCCEEDED':
                    results=output.get('results') or []
                    if len(results)!=1 or results[0].get('subtask_status')!='SUCCEEDED':
                        raise ASRProtocolError('Filetrans单文件子任务未成功','subtask_failed')
                    url=str(results[0].get('transcription_url',''))
                    from .glossary_skill import is_safe_web_url
                    if not is_safe_web_url(url)[0]:
                        raise ASRProtocolError('Filetrans结果URL不安全','invalid_result_url')
                    # No bearer token is sent to the separate signed result host.
                    result=client.get(url,timeout=(10,60),allow_redirects=False)
                    if result.status_code!=200:
                        raise ASRProtocolError(f'结果获取HTTP {result.status_code}；保留原task_id','result_fetch_failed')
                    payload=result.json()
                    if not isinstance(payload.get('transcripts'),list):
                        raise ASRProtocolError('Filetrans结果缺少transcripts','parse_failed')
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
                        state['cancel_requested']=result.status_code==200;save(state_path,state)
                    except Exception:pass
            raise
    converted=_filetrans_task_rows(payload,duration)
    rows=_api_transcription_rows(converted,dict(start=0,end=duration))
    if native:rows=scope_request_speakers(rows,0,1)
    else:
        for row in rows:row.pop('speaker',None)
    # Cleanup only after result is durable and parsed; failed polling never
    # deletes an upload the accepted task may still need to read.
    if auto_delete and state.get('object_key') and not state.get('object_deleted'):
        try:
            storage.delete_object(state['object_key'],strict=True);state['object_deleted']=True;save(state_path,state)
        except Exception:
            state['cleanup_pending']=True;save(state_path,state)
    return rows
