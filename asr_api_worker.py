"""Owned API request process. Credentials arrive only through stdin, never argv/disk."""
import json
import sys
import threading
from pathlib import Path


def main():
    root=Path(__file__).resolve().parent
    if root.name=='workers':root=root.parent
    # Frozen installation contains a different Python ABI; stdlib/site-packages
    # from this runtime must win over DLLs beside the GUI executable.
    sys.path.append(str(root))
    request=json.loads(sys.stdin.read())
    import numpy as np
    import subtitle_core as legacy
    from twobyteasr import asr
    from twobyteasr.runtime import RuntimeContext, activate_runtime_context
    from twobyteasr.cache import run_event_observer
    audio=np.load(request['audio_array'],mmap_mode='r')
    chunks=[dict(audio=(audio[row['offset']:row['offset']+row['samples']],16000),
                 start=row['start'],end=row['end']) for row in request['chunks']]
    asr.CLOUD_BATCH_WORKERS=request['workers']
    legacy.RUNTIME_SETTINGS=request['settings']
    lock=threading.Lock()
    def event(kind,payload):
        if kind not in {'cue_delta','asr_progress','asr_reference_delta'}:return
        with lock:print('[2BYTEASR_API] '+json.dumps(dict(kind=kind,payload=payload),ensure_ascii=False),flush=True)
    context=RuntimeContext(job_id=request['job_id'],speaker_source=request.get('speaker_source','single'))
    with activate_runtime_context(context),run_event_observer(event):
        if request.get('native_job'):
            from twobyteasr.cloud_asr_jobs import filetrans, transcribe_chunks, FILETRANS
            from twobyteasr.runtime_paths import user_data_root
            from twobyteasr.llm_config import validate_qwen_asr_endpoint
            endpoint=request['endpoint']; validate_qwen_asr_endpoint(endpoint)
            def check():
                if Path(request['cancel_file']).exists():raise RuntimeError('本地识别已取消；远端受理任务需按回执核对')
            cache=Path(user_data_root())/'cache'/'asr-jobs'
            def progress(state,done,total):
                event('asr_progress',dict(backend=endpoint['provider'],model=endpoint['model'],
                    state=state,completed_batches=done,total_batches=total))
            if endpoint['model']==FILETRANS:
                from twobyteasr.temp_audio_storage import oss_storage_from_settings
                storage=oss_storage_from_settings(request['settings'])
                if storage is None:raise RuntimeError('Qwen 3.1 长文件转写需要配置临时 OSS 存储。')
                results=filetrans(audio,endpoint,cache,storage,progress=progress,check=check,
                    restart_terminal=True,
                    auto_delete=bool(request['settings'].get('models',{}).get('oss_auto_delete',True)))
            else:
                results=transcribe_chunks(audio,endpoint,cache,progress=progress,check=check)
        else:
            results=asr._transcribe_qwen_api(request['source_path'],chunks,publish_primary=request['publish_primary'],
                _endpoint=request['endpoint'],_context=request['context'])
    path=Path(request['output']);temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'results':results},ensure_ascii=False),'utf8');temporary.replace(path)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        from twobyteasr.provider_diagnostics import redact_diagnostics
        print(redact_diagnostics(str(exc)),file=sys.stderr)
        raise SystemExit(1)
