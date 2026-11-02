"""One owned process with bounded HTTP workers; cancel joins the entire subtree."""
import json
import tempfile
from pathlib import Path


# MAI-Transcribe 2 through OpenRouter (2026-10-25): Azure's ``phraseList.phrases``
# is forwarded as-is and biases recognition toward the glossary (measured: 鸣潮 /
# 今汐 / 无妄者 / 守岸人 right only with it). Microsoft publishes no count limit;
# the head of the ranked list is sent and the rest is reported, never silently cut.
MAI_TRANSCRIBE_2 = 'microsoft/mai-transcribe-2'
MAX_MAI_PHRASES = 100
MAX_MAI_PHRASE_CHARS = 50


def mai_phrase_hints(canonical_terms) -> dict:
    sent, dropped, seen = [], [], set()
    for raw in canonical_terms or ():
        term = str(raw or '').strip()
        if not term or term in seen or '\n' in term or '\r' in term:
            continue
        seen.add(term)
        if len(term) > MAX_MAI_PHRASE_CHARS:
            dropped.append({'term': term, 'reason': 'longer_than_50_characters'})
        elif len(sent) >= MAX_MAI_PHRASES:
            dropped.append({'term': term, 'reason': 'over_100_phrases'})
        else:
            sent.append(term)
    return {'azure_phrases': sent, 'azure_phrases_dropped': dropped[:200],
            'hint_counts': {'phrase_list': len(sent), 'dropped': len(dropped)}}


def cloud_request_hints(endpoint, settings, requested_language=None):
    """Provider hints added to the request (and to its cache identity).

    Bailian Filetrans: per-model hotwords/context/language; MOSS Pro cloud:
    keyterms within the official 20 x 30-character limit; MAI-Transcribe 2
    (OpenRouter → Azure): the glossary as ``phraseList``.
    """
    from .qwen31_asr import filetrans_hints_for_model, is_filetrans_model
    from .mosi_asr import MODEL as MOSI_MODEL, keyterm_hints
    from ..glossary.terminology import recognition_hotwords, runtime_snapshot
    models = (settings or {}).get('models', {})
    if is_filetrans_model(endpoint.get('model')):
        return filetrans_hints_for_model(endpoint['model'], recognition_hotwords(runtime_snapshot()),
                                         vocabulary_id=models.get('asr_vocabulary_id', ''),
                                         vocabulary_model=models.get('asr_vocabulary_model', ''),
                                         language=requested_language)
    if endpoint.get('model') == MOSI_MODEL:
        return keyterm_hints(recognition_hotwords(runtime_snapshot()))
    if endpoint.get('protocol') == 'openrouter_verbose_json' and endpoint.get('model') == MAI_TRANSCRIBE_2:
        return mai_phrase_hints(recognition_hotwords(runtime_snapshot()))
    return {}


def cache_hint_signature(endpoint, settings, requested_language=None):
    """Cache identity of the new hint keys only (empty for routes that predate them)."""
    import hashlib
    from .qwen31_asr import QWEN3_FILETRANS
    from .mosi_asr import MODEL as MOSI_MODEL
    from .asr_language_control import policy
    language_control=policy(endpoint,requested_language)
    if endpoint.get('model') not in {QWEN3_FILETRANS, MOSI_MODEL, MAI_TRANSCRIBE_2}:
        return {'source_language_constraint':language_control['request_language']} if language_control['parameter_sent'] else {}
    hints = cloud_request_hints(endpoint, settings, requested_language)
    keep = {k: hints.get(k) for k in ('filetrans_language', 'mosi_keyterms', 'mosi_diarize', 'azure_phrases') if k in hints}
    if endpoint.get('model') == MAI_TRANSCRIBE_2:
        # Results from before 2026-10-25 were asked with an ignored style option.
        keep['mai_request'] = 'enhanced-mode-style-v1'
    return {'api_hints_v1': hashlib.sha256(json.dumps(keep, ensure_ascii=False, sort_keys=True).encode('utf8')).hexdigest()}


def transcribe(audio_path,chunks,*,publish_primary=False,cache_root=None,storage_credentials=None,prepared_source=None):
    import numpy as np
    from ..recognition import asr
    from ..recognition.cache import record_run_event
    from .llm_config import qwen_asr_endpoint_from_settings, validate_qwen_asr_endpoint
    from ..recognition.run_context import get_runtime_context
    from ..runtime_paths import detect_install_root
    context=get_runtime_context()
    settings=context.asr_settings_snapshot or asr._legacy_runtime_value('RUNTIME_SETTINGS',asr.RUNTIME_SETTINGS)
    endpoint=dict(context.asr_endpoint_snapshot or qwen_asr_endpoint_from_settings(settings))
    validate_qwen_asr_endpoint(endpoint)
    endpoint['speaker_source']=context.speaker_source or 'single'
    from .qwen31_asr import is_filetrans_model
    from .mosi_asr import MODEL as MOSI_MODEL
    endpoint.update(cloud_request_hints(endpoint, settings, context.requested_language))
    from .asr_language_control import hints as language_hints,policy as language_policy
    endpoint.update(language_hints(endpoint,context.requested_language))
    control=language_policy(endpoint,context.requested_language)
    context.language_evidence['remote_language_control']=dict(control,phase='request_intent')
    context.language_decision['remote_language_control']=dict(control,phase='request_intent')
    record_run_event('asr_language_control',phase='request_intent',provider=endpoint.get('provider'),model=endpoint.get('model'),**control)
    policy = (context.recognition_snapshot or {}).get('language_recovery_policy') or {}
    if policy.get('force_cloud'):
        endpoint['asr_request_generation'] = context.job_id
        record_run_event('asr_cache_policy', operation='new_cloud_transcription',
            reason='explicit_user_range_retry', generation=context.job_id,
            aggregate_reuse=False, native_result_reuse=False, previous_responses_preserved=True)
    if endpoint.get('model') == MOSI_MODEL:
        from .mosi_asr import language_policy
        record_run_event('cloud_language_policy', provider=endpoint.get('provider'),
                         **language_policy(context.requested_language))
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
        if kind == 'asr_shard_ready' and publish_primary and callable(context.primary_ready_callback):
            context.primary_ready_callback(payload)
            record_run_event(kind, **{key:value for key,value in payload.items() if key != 'rows'})
            return
        if kind=='cue_delta' and publish_primary:
            context.asr_manifest_key=payload['manifest_key']
            rows.update((row['id'],row) for row in payload['cues'])
            context.asr_provisional_cues=sorted(rows.values(),key=lambda r:(r['start_ms'],r['id']))
        record_run_event(kind,**payload)
    with tempfile.TemporaryDirectory(prefix='2byte-api-') as directory:
        root=Path(directory);array=root/'audio.npy';output=root/'output.json'
        manifest=[];offset=0
        if prepared_source is not None:
            array=Path('unused-prepared-source.npy');shape=int(prepared_source['expected_samples'])
        elif native_job and len(chunks)==1:
            from ..recognition.alignment_audio import prepare_audio
            spec=prepare_audio(chunks[0]['audio'][0],root,check=asr._raise_if_queue_cancelled)
            array=Path(spec['path'])
            manifest=[dict(offset=0,samples=spec['samples'],start=chunks[0]['start'],end=chunks[0]['end'])]
            shape=spec['samples']
        else:
            shape=sum(len(c['audio'][0]) for c in chunks)
            audio=np.lib.format.open_memmap(array,mode='w+',dtype='float32',shape=(shape,))
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
            job_id=context.job_id,requested_language=context.requested_language,
            publish_primary=publish_primary,workers=max(1,min(6,int(asr.CLOUD_BATCH_WORKERS))))
        if prepared_source is not None:request['prepared_source']=prepared_source
        if storage_credentials: request['storage_credentials'] = storage_credentials
        # Set only for one run after the user confirmed resubmission (retry dialog).
        if (settings or {}).get('models', {}).get('cloud_resubmit_confirmed') is True:
            request['restart_terminal'] = True
        # Set only for one run after the user chose 切成小段再交 MOSI (2026-10-24).
        if (settings or {}).get('models', {}).get('mosi_resplit_blocked') is True:
            request['resplit_blocked'] = True
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
        rows=payload['results']
        blocked=[dict(row['cloud_gap'],start=row['start'],end=row['end']) for row in rows if row.get('cloud_gap')]
        if blocked:
            # Ranges the provider's content review stopped (2026-10-24). The
            # primary transcript keeps them as markers for the local fill;
            # review evidence simply has nothing there.
            record_run_event('cloud_asr_blocked',role='primary' if publish_primary else 'review',requests=blocked)
            if not publish_primary:
                rows=[row for row in rows if not row.get('cloud_gap')]
        return rows
