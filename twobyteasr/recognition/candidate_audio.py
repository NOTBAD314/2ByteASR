"""Lossless recovery input from the original, verified analysis PCM cache."""
from __future__ import annotations
import hashlib,json,os,struct,uuid
from pathlib import Path


def prepare_candidate_input(snapshot, cache_root, *, token=None):
    import numpy as np
    from .transcript_acceptance import digest
    from .alignment_audio import pcm_digest
    from ..storage.storage_service import cache_lease
    from ..storage.atomic_files import write_text_atomic
    policy=snapshot['language_recovery_policy']
    if not (policy.get('confirmed_after_listening') or policy.get('kept_manual_choice')):
        raise ValueError('候选还没有经过明确核对。')
    if digest(snapshot.get('audio_graph') or {}) != policy.get('audio_graph_digest'):
        raise ValueError('音轨或混音已变化，未复用旧输入。')
    expected_sources=policy.get('source_identities') or {}
    current_sources=snapshot.get('sources') or {}
    # Queue preparation hashes current sources before calling this function.
    # Path/graph equality alone cannot authorize reusing a replaced media file.
    if not expected_sources or set(expected_sources)!=set(current_sources):
        raise ValueError('缺少原始输入来源身份，不能复用旧PCM。')
    for source,expected in expected_sources.items():
        actual=current_sources[source]
        if not expected.get('sha256') or expected['sha256']!=actual.get('sha256'):
            raise ValueError('输入素材已变化，不能复用旧候选。')
    ref=policy['input_pcm'];path=Path(ref['path'])
    start,end=policy['candidate_scope']
    origin=float(ref.get('range_origin_ms') or 0)/1000
    pcm_start,pcm_end=policy.get('pcm_scope') or [start,end]
    if abs(pcm_start-start)>.001 or pcm_end>end+.001 or pcm_end<=pcm_start:
        raise ValueError('原PCM与恢复时间轴起点或范围不匹配。')
    left,right=round((pcm_start-origin)*16000),round((pcm_end-origin)*16000)
    if pcm_end<end-.001:
        tolerance=float(policy.get('frame_tail_tolerance_seconds') or 0)
        if (not policy.get('full_pcm_sha256') or tolerance<=0 or end-pcm_end>tolerance+.001
                or abs(pcm_end-origin-int(ref.get('samples') or 0)/16000)>.001):
            raise ValueError('尾帧范围缺少可验证原PCM边界，不能复用。')
    window=snapshot.get('range_ms') or [round(start*1000),round(end*1000)]
    if (abs(window[0]/1000-start)>.001 or abs(window[1]/1000-end)>.001
            or abs(end-start-snapshot['duration_ms']/1000)>.001):
        raise ValueError('恢复范围已变化，不能复用旧PCM。')
    if token is not None:token.raise_if_cancelled()
    with cache_lease(path):
        try:
            audio=np.load(path,mmap_mode='r',allow_pickle=False)
        except (OSError,ValueError) as exc:
            raise ValueError('原始PCM缓存不可用；请恢复原缓存或明确重新识别此范围。') from exc
        try:
            if audio.dtype!=np.float32 or audio.ndim!=1 or len(audio)!=ref.get('samples') or not 0<=left<right<=len(audio):
                raise ValueError('原始PCM格式或范围不匹配。')
            selected=audio[left:right]
            checksum=pcm_digest(selected,check=token.raise_if_cancelled if token is not None else None)
            if policy.get('full_pcm_sha256'):
                if pcm_digest(audio,check=token.raise_if_cancelled if token is not None else None)!=policy['full_pcm_sha256']:
                    raise ValueError('原始完整PCM摘要不匹配。')
                policy['pcm_sha256']=checksum  # this job's verified widened slice
            elif not policy.get('pcm_sha256') or checksum!=policy['pcm_sha256']:
                raise ValueError('原始PCM摘要不匹配，未复用旧候选。')
            key=digest([checksum,snapshot['fingerprint'],left,right])
            directory=Path(cache_root)/'candidate-inputs'/key;directory.mkdir(parents=True,exist_ok=True)
            target=directory/'timeline.wav';manifest=directory/'input.json'
            temporary=directory/('input-'+uuid.uuid4().hex+'.wav')
            size=len(selected)*4
            if size>0xffffffff-36:
                raise ValueError('此范围超过单个WAV容量，请分范围恢复。')
            # IEEE float32 WAV avoids a second int16 quantization/resampling.
            # The ordinary decoder/alignment chain reads exactly these values.
            header=struct.pack('<4sI4s4sIHHIIHH4sI',b'RIFF',size+36,b'WAVE',b'fmt ',16,
                3,1,16000,64000,4,32,b'data',size)
            cached=False
            if target.is_file() and manifest.is_file():
                try:
                    previous=json.loads(manifest.read_text('utf8'))
                    with target.open('rb') as stream:
                        valid=stream.read(len(header))==header
                        checksum_on_disk=hashlib.sha256()
                        for block in iter(lambda:stream.read(1024*1024),b''):
                            if token is not None:token.raise_if_cancelled()
                            checksum_on_disk.update(block)
                    cached=(valid and previous.get('pcm_sha256')==checksum
                            and target.stat().st_size==len(header)+size and checksum_on_disk.hexdigest()==checksum)
                except (OSError,ValueError,TypeError):
                    cached=False
            if not cached:
                try:
                    with temporary.open('wb') as stream:
                        stream.write(header)
                        for offset in range(0,len(selected),1024*1024):
                            if token is not None:token.raise_if_cancelled()
                            stream.write(memoryview(np.asarray(selected[offset:offset+1024*1024],dtype='<f4')).cast('B'))
                    os.replace(temporary,target)
                finally:
                    temporary.unlink(missing_ok=True)
            receipt=dict(input_path=str(target),operation='verified_original_pcm_slice',sample_rate=16000,
                samples=len(selected),pcm_sha256=checksum,origin_pcm=str(path),origin_range_samples=[left,right],timeline_scope=[start,end],pcm_scope=[pcm_start,pcm_end],
                audio_graph_digest=policy['audio_graph_digest'],new_cloud_request=False,input_artifact_cache_hit=cached)
            if not cached:
                write_text_atomic(manifest,json.dumps(receipt,ensure_ascii=False,indent=2))
            from .cache import record_run_event
            record_run_event('candidate_input_reused',**receipt)
            return str(target)
        finally:
            mapping=getattr(audio,'_mmap',None)
            if mapping is not None:mapping.close()
