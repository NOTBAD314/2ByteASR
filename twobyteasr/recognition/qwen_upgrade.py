"""Activate the existing Qwen choice only after current Ultra file/inference proof."""
from __future__ import annotations
import copy
import hashlib
import json
import os
import threading
import time
from pathlib import Path

PROFILE='ultra-v5'
_LOCK=threading.RLock()


def file_stamp(directory):
    from ..model_integrity import load_dependency_lock
    spec=load_dependency_lock()['models']['qwen_ultra_aligner'];directory=Path(directory)
    return {name:[(directory/name).stat().st_size,(directory/name).stat().st_mtime_ns] for name in spec['sha256']}


def receipt_from_payload(payload):
    from .alignment_backend import profile,receipt_matches,model_directory
    expected=profile('qwen_ultra_aligner')
    if not receipt_matches(payload,expected) or not any(r.get('segments') for r in payload.get('results',[])):
        raise ValueError('Ultra readiness requires an actual matching inference result')
    directory=model_directory('qwen_ultra_aligner')
    return dict(status='PASS',model_loaded=True,inference_verified=True,quality_claim=None,
        alignment_receipt={k:payload.get(k) for k in ('model','model_revision','code','unit_policy','alignment_identity','execution_identity')},
        ultra_directory=str(Path(directory).resolve()),ultra_file_stats=file_stamp(directory),runtime_python=payload.get('python'),checked_at=time.time())


def current_readiness(data_root=None):
    from ..runtime_paths import user_data_root
    from .alignment_backend import model_directory,readiness_matches
    from .asr import _main_worker_python
    data_root=Path(data_root) if data_root is not None else user_data_root()
    try:
        receipt=json.loads((data_root/'model-readiness/qwen_ultra_aligner.json').read_text('utf8'))
        if not readiness_matches('qwen_ultra_aligner',receipt):return None
        directory=Path(model_directory('qwen_ultra_aligner')).resolve()
        if str(directory)!=receipt.get('ultra_directory') or file_stamp(directory)!=receipt.get('ultra_file_stats'):return None
        if receipt.get('runtime_python') and Path(receipt['runtime_python']).resolve()!=Path(_main_worker_python()).resolve():return None
        from ..local_models.alignment_readiness import runtime_matches
        if not runtime_matches(receipt,_main_worker_python()):return None
        return receipt
    except (OSError,ValueError,KeyError,RuntimeError):return None


def activate_if_ready(settings,*,data_root=None,persist=True):
    """Only future snapshots change. No projects, model files or other model choices are migrated."""
    from ..runtime_paths import user_data_root
    from ..storage.settings import save_runtime_settings,project_settings_path
    data_root=Path(data_root) if data_root is not None else user_data_root()
    with _LOCK:
        receipt=current_readiness(data_root)
        if receipt is None:return False
        models=settings.setdefault('models',{});switches=settings.setdefault('switches',{})
        first=models.get('qwen_alignment_profile')!=PROFILE
        backend=models.get('firered_asr_backend')
        normalize=backend=='qwen_ultra_aligner' or (first and backend in {'qwen_aligner','qwen_ultra_head'})
        if not first and not normalize and switches.get('use_ja_ctc_aligner') is False:return True
        before=dict(models={k:models.get(k) for k in ('firered_asr_backend','qwen_alignment_profile')},switches={'use_ja_ctc_aligner':switches.get('use_ja_ctc_aligner')})
        marker=data_root/'migrations/qwen-ultra-v5.json';marker.parent.mkdir(parents=True,exist_ok=True)
        settings_path=project_settings_path()
        if persist and not marker.exists():
            backup=marker.with_name('qwen-ultra-v5.settings-before.json')
            if settings_path.is_file() and not backup.exists():backup.write_bytes(settings_path.read_bytes())
        models['qwen_alignment_profile']=PROFILE
        if normalize:
            from .qwen_family import normalize_models
            normalize_models(models)
            models['firered_asr_backend']='qwen_aligner'
        switches['use_ja_ctc_aligner']=False
        try:
            if persist:save_runtime_settings(settings)
        except Exception:
            for k,v in before['models'].items():
                if v is None:models.pop(k,None)
                else:models[k]=v
            for k,v in before['switches'].items():
                if v is None:switches.pop(k,None)
                else:switches[k]=v
            raise
        if persist and not marker.exists():
            marker.write_text(json.dumps(dict(before=before,after=dict(models={k:models.get(k) for k in before['models']},switches={'use_ja_ctc_aligner':False}),
                model=receipt['alignment_receipt']['model'],revision=receipt['alignment_receipt']['model_revision'],
                inference_receipt_sha256=hashlib.sha256(json.dumps(receipt,sort_keys=True).encode()).hexdigest(),settings_path=str(settings_path),
                old_projects_rewritten=False,model_files_deleted=False,changed_at=time.time()),ensure_ascii=False,indent=2),'utf8')
        return True


def prove_current_ultra(*,cancel_token=None):
    """Reuse the normal managed worker, without loading torch into the GUI."""
    import sys,wave
    import numpy as np
    from ..runtime_paths import detect_install_root,user_data_root
    from .run_context import RuntimeContext,activate_runtime_context
    from . import asr
    roots=[detect_install_root()]
    if getattr(sys,'frozen',False):roots.append(Path(sys._MEIPASS))
    sample=next((p/'assets/diagnostics/speech_en.wav' for p in roots if (p/'assets/diagnostics/speech_en.wav').is_file()),None)
    if sample is None:raise RuntimeError('Missing bundled alignment readiness audio')
    with wave.open(str(sample),'rb') as stream:audio=np.frombuffer(stream.readframes(stream.getnframes()),'<i2').astype('float32')/32768
    context=RuntimeContext(alignment_checkpoint_dir=str(user_data_root()/'cache/qwen-upgrade-readiness'),
        asr_settings_snapshot={'models':{'firered_asr_backend':'qwen_ultra_aligner'}},cancellation_token=cancel_token)
    try:
        with activate_runtime_context(context):
            payload=asr.run_qwen_aligner_worker(audio,[dict(id='upgrade-readiness',text='Hello this is a local speech recognition test the weather is sunny today',language='English',window_start_ms=0,window_end_ms=round(len(audio)/16))])
        receipt=receipt_from_payload(payload)
        target=user_data_root()/'model-readiness/qwen_ultra_aligner.json';target.parent.mkdir(parents=True,exist_ok=True)
        pending=target.with_suffix('.pending');pending.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf8');os.replace(pending,target)
        from ..local_models.model_state_events import notify
        notify(['qwen_ultra_aligner'],'validation_success')
        return receipt
    finally:context.close_resources()
