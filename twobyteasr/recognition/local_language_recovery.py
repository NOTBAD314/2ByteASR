"""Bounded, offline ASR attempts for a rejected language range.

The existing Qwen worker owns one model instance for all windows. Raw cloud
responses stay untouched; this cache records a separate selectable attempt.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import time
import uuid

VERSION = 'local-language-range-v1'
MODEL = 'Qwen3-ASR-1.7B'


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf8')).hexdigest()


def _save(path, value):
    from ..storage.atomic_files import write_text_atomic
    write_text_atomic(Path(path), json.dumps(value, ensure_ascii=False, indent=2))


def plan_windows(audio, start_sample, end_sample, *, sample_rate=16000, max_seconds=26, target_seconds=22):
    """Contiguous sample-exact windows, cut at quiet 40ms frames near target.

    Every input sample is retained, including speech a VAD may have missed.
    There is no accumulating timestamp rounding or textual overlap dedupe.
    """
    import numpy as np
    start, end = int(start_sample), int(end_sample)
    if not 0 <= start < end <= len(audio):
        raise ValueError('替代识别范围超出音频')
    rows = []
    frame = max(1, int(sample_rate * .04))
    cap = int(sample_rate * max_seconds)
    target = int(sample_rate * target_seconds)
    while end-start > cap:
        lo, hi = start+target-int(2*sample_rate), min(end, start+cap)
        count = (hi-lo)//frame
        x = np.asarray(audio[lo:lo+count*frame], dtype=np.float64).reshape(count, frame)
        energy = np.mean(x*x, axis=1)
        # Prefer a quiet 160ms interval, rather than a zero crossing in speech.
        smooth = np.convolve(energy, np.ones(4)/4, mode='valid')
        cut = lo+(int(np.argmin(smooth))+2)*frame
        rows.append((start, cut))
        start = cut
    rows.append((start, end))
    return rows


def recognize_range(audio, start_sample, end_sample, *, language, cache_root, token=None,
                    progress=None, acoustic_samples=(), source_identity=None, retry=False):
    """Run or replay one local attempt. Failed/cancelled attempts need explicit retry.

    No model download, HTTP fallback, global language mutation or automatic
    repeated attempt is permitted here. Callers keep the pending range on error.
    """
    import numpy as np
    from . import asr
    from ..subtitle_rules.language_rules import qwen_language_name
    requested = qwen_language_name(language)
    if not requested:
        raise ValueError('本地替代识别需要明确的受支持源语言')
    source = np.asarray(audio)
    if source.ndim != 1 or not np.isfinite(source).all():
        raise ValueError('替代识别输入必须是有限的单声道PCM')
    windows = plan_windows(source, start_sample, end_sample)
    model_path = asr.resolve_qwen_asr_local_source()
    runtime = asr._main_worker_python()
    worker = Path(asr.SCRIPT_DIR)/'qwen_asr_worker.py'
    if not model_path or not runtime or not Path(runtime).is_file() or not worker.is_file():
        raise RuntimeError('本地Qwen3-ASR或运行环境未就绪；已保留正常字幕和待处理范围，请选择已有可用方案')
    model_config = Path(model_path)/'config.json'
    identity = dict(version=VERSION, model=MODEL, language=requested,
        range_samples=[int(start_sample), int(end_sample)], sample_rate=16000,
        pcm_sha256=hashlib.sha256(np.asarray(source[start_sample:end_sample], dtype='<f4').tobytes()).hexdigest(),
        windows=[list(w) for w in windows], source_identity=source_identity or {},
        worker_sha256=hashlib.sha256(worker.read_bytes()).hexdigest(),
        model_config_sha256=hashlib.sha256(model_config.read_bytes()).hexdigest())
    root = Path(cache_root)/_sha(identity)
    root.mkdir(parents=True, exist_ok=True)
    state_path, result_path = root/'state.json', root/'accepted.json'
    if result_path.is_file():
        result = json.loads(result_path.read_text('utf8'))
        if result.get('identity') == identity and result.get('status') == 'accepted':
            if progress:
                progress({'event': 'cache_hit', 'completed': len(result['rows']), 'total': len(result['rows'])})
            return result
    state = json.loads(state_path.read_text('utf8')) if state_path.exists() else {}
    if state and not retry:
        raise RuntimeError('该范围的本地恢复尚未完成；保留原回执，请在恢复入口明确重试')
    attempt_id = uuid.uuid4().hex
    attempt = root/attempt_id
    attempt.mkdir()
    jobs = []
    for index, (start, end) in enumerate(windows, 1):
        if token:
            token.raise_if_cancelled()
        pcm = np.ascontiguousarray(source[start:end], dtype=np.float32)
        path = attempt/f'window-{index:04d}.npy'
        np.save(path, pcm, allow_pickle=False)
        jobs.append(dict(segment_id=index, path=str(path), samples=len(pcm), start=start/16000,
                         end=end/16000, pcm_sha256=hashlib.sha256(pcm.tobytes()).hexdigest(), language=requested))
    production_count = len(jobs)
    for start, end in acoustic_samples:
        start, end = int(start), int(end)
        if not 0 <= start < end <= len(source):
            raise ValueError('声学核对样本超出音频')
        pcm = np.ascontiguousarray(source[start:end], dtype=np.float32)
        path = attempt/f'probe-{len(jobs)+1:04d}.npy'
        np.save(path, pcm, allow_pickle=False)
        jobs.append(dict(segment_id=len(jobs)+1, path=str(path), samples=len(pcm), start=start/16000,
                         end=end/16000, pcm_sha256=hashlib.sha256(pcm.tobytes()).hexdigest(), language=None))
    policy = dict(version='qwen-worker-shared-float32-v1', audio_format='float32-mono-npy-v1',
                  batch_size=4, max_new_tokens=512, sample_rate=16000, language=requested,
                  checkpoint=True, generation_evidence=True)
    resume_path=root/'resume.json'
    resumed=[]
    if retry and resume_path.is_file():
        previous=json.loads(resume_path.read_text('utf8'))
        if previous.get('identity')==identity:
            wanted={j['segment_id']:j for j in jobs}
            for row in previous.get('results',[]):
                job=wanted.get(row.get('segment_id'))
                if (job and all(row.get(k)==job[k] for k in ('samples','pcm_sha256','start','end'))
                        and row.get('request_language')==job['language'] and row.get('text')
                        and not (row.get('generation') or {}).get('token_limit_reached')):
                    resumed.append(row)
    done={r['segment_id'] for r in resumed}
    remaining=[j for j in jobs if j['segment_id'] not in done]
    manifest, output = attempt/'manifest.json', attempt/'worker-result.json'
    _save(manifest, dict(jobs=remaining, policy=policy))
    state = dict(status='running', attempt_id=attempt_id, identity=identity, started_at=time.time(),
                 production_windows=production_count, acoustic_windows=len(jobs)-production_count,
                 resumed_windows=len(resumed))
    _save(state_path, state)
    started = time.perf_counter()
    try:
        def note(event):
            if progress:
                value=dict(event)
                if event.get('event')=='batch_completed':
                    value.update(completed=len(resumed)+int(event['completed']),total=len(jobs))
                progress(value)
        payload = asr._run_isolated_asr_worker(
            [runtime, '-I', '-u', str(worker), '--manifest', str(manifest), '--output', str(output),
             '--model-dir', str(model_path)], str(output), model_id='QWEN3-ASR', audio_input='shared_audio',
            model_path=str(model_path), entrypoint='qwen_asr_worker.py', event_handler=note,
            timeout_seconds=max(600, (end_sample-start_sample)/16000*4)) if remaining else {'results':[]}
        values = sorted([*resumed,*(payload.get('results') or [])],key=lambda r:r['segment_id'])
        if len(values) != len(jobs) or [v.get('segment_id') for v in values] != [j['segment_id'] for j in jobs]:
            raise RuntimeError('本地识别窗口缺失或身份不一致，未接受恢复结果')
        for row, job in zip(values, jobs):
            if any(row.get(k) != job[k] for k in ('samples', 'pcm_sha256', 'start', 'end')):
                raise RuntimeError('本地识别音频/时间身份不一致，未接受恢复结果')
        rows = values[:production_count]
        if any((r.get('generation') or {}).get('token_limit_reached') for r in rows):
            raise RuntimeError('本地识别达到生成上限；保留部分结果与范围，请缩小范围后重试')
        if any(not str(r.get('text') or '').strip() for r in rows):
            raise RuntimeError('本地识别存在空窗口；保留检查点，未将该范围标成恢复成功')
        from .language_diagnostics import transcript_language_sample
        observed = transcript_language_sample(r.get('text') for r in rows)
        if observed.get('language') not in {None, language}:
            raise RuntimeError('替代识别结果仍有明显文字语言冲突，未接受为主稿')
        result = dict(status='accepted', attempt_id=attempt_id, identity=identity, rows=rows,
                      acoustic_samples=values[production_count:], raw_payload=str(output),
                      elapsed_seconds=time.perf_counter()-started, language_evidence=observed,
                      model=MODEL, backend='qwen_local', policy=policy, production_windows=production_count)
        result['resumed_windows']=len(resumed)
        _save(result_path, result)
        _save(state_path, dict(state, status='accepted', elapsed_seconds=result['elapsed_seconds']))
        return result
    except BaseException as exc:
        partial=output.with_suffix('.partial.json')
        if partial.is_file():
            try:
                rows=json.loads(partial.read_text('utf8')).get('results') or []
                _save(resume_path,{'identity':identity,'results':[*resumed,*rows]})
            except (OSError,ValueError,TypeError):
                pass
        cancelled = bool(token and token.is_cancelled)
        _save(state_path, dict(state, status='cancelled' if cancelled else 'failed', error=str(exc)[:1200],
                              elapsed_seconds=time.perf_counter()-started))
        raise
