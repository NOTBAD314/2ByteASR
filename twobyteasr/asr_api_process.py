"""One owned process with bounded HTTP workers; cancel joins the entire subtree."""
import json
import tempfile
from pathlib import Path


def transcribe(audio_path,chunks,*,publish_primary=False):
    import numpy as np
    from . import asr
    from .cache import record_run_event
    from .llm_config import qwen_asr_endpoint_from_settings
    from .runtime import get_runtime_context
    from .runtime_paths import detect_install_root
    from .runtime_registry import resolve_runtime_python
    context=get_runtime_context()
    settings=context.asr_settings_snapshot or asr._legacy_runtime_value('RUNTIME_SETTINGS',asr.RUNTIME_SETTINGS)
    endpoint=dict(context.asr_endpoint_snapshot or qwen_asr_endpoint_from_settings(settings))
    endpoint['speaker_source']=context.speaker_source or 'single'
    from .cloud_asr_jobs import FLASH, FILETRANS, SPARK, worker_timeout
    native_job=endpoint['model'] in {FLASH,FILETRANS,SPARK}
    worker=detect_install_root()/'asr_api_worker.py'
    if (worker.parent/'workers'/worker.name).is_file():worker=worker.parent/'workers'/worker.name
    python=resolve_runtime_python('main')
    if not python or not worker.is_file():raise RuntimeError('API隔离worker运行环境缺失')
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
        request=dict(source_path=str(audio_path),audio_array=str(array),output=str(output),chunks=manifest,
            endpoint=endpoint,context=asr.build_qwen_asr_context(audio_path),settings=settings,
            native_job=native_job,speaker_source=endpoint['speaker_source'],
            cancel_file=str(root/'cancel'),
            job_id=context.job_id,publish_primary=publish_primary,workers=max(1,min(6,int(asr.CLOUD_BATCH_WORKERS))))
        record_run_event('asr_wait',backend='api',state='connecting',total_batches=len(chunks),
            message='上传短块并等待真实转写；本地独立证据可同时运行')
        payload=asr._run_isolated_asr_worker([python,'-u',str(worker)],str(output),model_id='PRIMARY_API',
            audio_input=str(audio_path),model_path='',entrypoint=str(worker),
            input_text=json.dumps(request,ensure_ascii=False),event_handler=forward,
            timeout_seconds=worker_timeout(endpoint['model'],shape),
            cancel_handler=lambda:(root/'cancel').write_text('local cancellation requested','utf8'))
        return payload['results']
