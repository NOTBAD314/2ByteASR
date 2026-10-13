"""One owned process with bounded HTTP workers; cancel joins the entire subtree."""
import json
import tempfile
from pathlib import Path


def cloud_request_hints(endpoint, settings, requested_language=None):
    """Provider hints added to the request (and to its cache identity).

    Bailian Filetrans: per-model hotwords/context/language; MOSS Pro cloud:
    keyterms within the official 20 x 30-character limit.
    """
    from .qwen31_asr import filetrans_hints_for_model, is_filetrans_model
    from .mosi_asr import MODEL as MOSI_MODEL, keyterm_hints
    from .terminology import runtime_snapshot
    models = (settings or {}).get('models', {})
    if is_filetrans_model(endpoint.get('model')):
        return filetrans_hints_for_model(endpoint['model'], runtime_snapshot().canonical_terms,
                                         vocabulary_id=models.get('asr_vocabulary_id', ''),
                                         vocabulary_model=models.get('asr_vocabulary_model', ''),
                                         language=requested_language)
    if endpoint.get('model') == MOSI_MODEL:
        return keyterm_hints(runtime_snapshot().canonical_terms)
    return {}


def cache_hint_signature(endpoint, settings, requested_language=None):
    """Cache identity of the new hint keys only (empty for routes that predate them)."""
    import hashlib
    from .qwen31_asr import QWEN3_FILETRANS
    from .mosi_asr import MODEL as MOSI_MODEL
    if endpoint.get('model') not in {QWEN3_FILETRANS, MOSI_MODEL}:
        return {}
    hints = cloud_request_hints(endpoint, settings, requested_language)
    keep = {k: hints.get(k) for k in ('filetrans_language', 'mosi_keyterms', 'mosi_diarize') if k in hints}
    return {'api_hints_v1': hashlib.sha256(json.dumps(keep, ensure_ascii=False, sort_keys=True).encode('utf8')).hexdigest()}


def transcribe(audio_path,chunks,*,publish_primary=False,cache_root=None,storage_credentials=None):
    import numpy as np
    from . import asr
    from .cache import record_run_event
    from .llm_config import qwen_asr_endpoint_from_settings, validate_qwen_asr_endpoint
    from .runtime import get_runtime_context
    from .runtime_paths import detect_install_root
    context=get_runtime_context()
    settings=context.asr_settings_snapshot or asr._legacy_runtime_value('RUNTIME_SETTINGS',asr.RUNTIME_SETTINGS)
    endpoint=dict(context.asr_endpoint_snapshot or qwen_asr_endpoint_from_settings(settings))
    validate_qwen_asr_endpoint(endpoint)
    endpoint['speaker_source']=context.speaker_source or 'single'
    from .qwen31_asr import is_filetrans_model
    from .mosi_asr import MODEL as MOSI_MODEL
    endpoint.update(cloud_request_hints(endpoint, settings, context.requested_language))
    if endpoint.get('hint_counts'):
        record_run_event('cloud_request_hints', model=endpoint['model'], **endpoint['hint_counts'],
                         language=endpoint.get('filetrans_language') or '')
    from .cloud_asr_jobs import FLASH, SPARK, worker_timeout
    native_job=endpoint['model'] in {FLASH,SPARK,MOSI_MODEL} or is_filetrans_model(endpoint['model'])
    # Cloud recognition never needs the local model runtime (PyTorch etc.):
    # the packaged app runs the worker with its own executable.
    from .cloud_api_worker import cloud_worker_command
    command=cloud_worker_command(detect_install_root())
    rows={row['id']:row for row in context.asr_provisional_cues}
    def forward(event):
        asr._raise_if_queue_cancelled()
        kind,payload=event['kind'],event['payload']
        if kind=='cue_delta' and publish_primary:
            context.asr_manifest_key=payload['manifest_key']
            rows.update((row['id'],row) for row in payload['cues'])
            context.asr_provisional_cues=sorted(rows.values(),key=lambda r:(r['start_ms'],r['id']))
        record_run_event(kind,**payload)
    with tempfile.TemporaryDirectory(prefix='2byte-api-') as directory:
        root=Path(directory);array=root/'audio.npy';output=root/'output.json'
        shape=sum(len(c['audio'][0]) for c in chunks)
        audio=np.lib.format.open_memmap(array,mode='w+',dtype='float32',shape=(shape,))
        manifest=[];offset=0
        for chunk in chunks:
            asr._raise_if_queue_cancelled()
            size=len(chunk['audio'][0]);audio[offset:offset+size]=chunk['audio'][0]
            manifest.append(dict(offset=offset,samples=size,start=chunk['start'],end=chunk['end']))
            offset+=size
        audio.flush();del audio
        from .llm_config import read_oss_credentials
        if storage_credentials is None:
            storage_credentials = read_oss_credentials() if is_filetrans_model(endpoint['model']) else ()
        request=dict(source_path=str(audio_path),audio_array=str(array),output=str(output),chunks=manifest,
            endpoint=endpoint,context=asr.build_qwen_asr_context(audio_path),settings=settings,
            native_job=native_job,speaker_source=endpoint['speaker_source'],
            cancel_file=str(root/'cancel'),
            job_id=context.job_id,publish_primary=publish_primary,workers=max(1,min(6,int(asr.CLOUD_BATCH_WORKERS))))
        if storage_credentials: request['storage_credentials'] = storage_credentials
        # Set only for one run after the user confirmed resubmission (retry dialog).
        if (settings or {}).get('models', {}).get('cloud_resubmit_confirmed') is True:
            request['restart_terminal'] = True
        if cache_root: request['cache_root'] = str(cache_root)
        record_run_event('asr_wait',backend='api',state='connecting',total_batches=len(chunks),
            message='上传音频并等待云端转写；本地独立证据可同时运行')
        record_run_event('cloud_worker_launch',launcher='frozen_app' if command[1:2]==['--asr-api-worker'] else 'app_interpreter',
            runtime=str(command[0]))
        payload=asr._run_isolated_asr_worker(command,str(output),model_id='PRIMARY_API',
            audio_input=str(audio_path),model_path='',entrypoint='asr_api_worker.py',
            input_text=json.dumps(request,ensure_ascii=False),event_handler=forward,
            timeout_seconds=worker_timeout(endpoint['model'],shape),
            cancel_handler=lambda:(root/'cancel').write_text('local cancellation requested','utf8'))
        return payload['results']
