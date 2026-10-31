"""Read a bounded excerpt of the existing recognition PCM, never decode it all.

Only an unchanged primary mono recognition input can use this path. Edited
mixes, other streams, gains/envelopes and missing/mismatched caches keep the
normal export-graph decoder. This cache is read-only and remains disposable.
"""
import json
import os
from pathlib import Path


def cached_recognition_pcm(plan):
    import numpy as np
    identity = plan.recognition_identity
    if not identity or identity.get('selection') or len(plan.layers) != 1:
        return None
    layer = plan.layers[0]
    if (int(layer.get('stream_index') or 0) != 0 or float(layer.get('playback_rate') or 1) != 1
            or float(layer.get('gain_db') or 0) != 0 or layer.get('audio_envelopes')):
        return None
    a, b = plan.play_range_ms
    if a < layer['timeline_in_ms'] or b > layer['timeline_out_ms']:
        return None
    source = Path(layer['source_path'])
    if os.path.normcase(str(source.resolve())) != os.path.normcase(str(Path(identity.get('path', '')).resolve())):
        return None
    try:
        stat = source.stat()
        if stat.st_size != identity.get('size') or stat.st_mtime_ns != identity.get('mtime_ns'):
            return None
        from ..recognition.cache import CACHE_ROOT, CACHE_SCHEMA_VERSION, cache_stage_signature, stable_digest
        folder = Path(CACHE_ROOT) / stable_digest(identity)[:24]
        meta = json.loads((folder / 'audio_meta.json').read_text('utf-8'))
        if (meta.get('schema') != CACHE_SCHEMA_VERSION or meta.get('identity') != identity
                or meta.get('signature') != cache_stage_signature('audio')
                or meta.get('sample_rate') != 16000):
            return None
        from ..storage.storage_service import cache_lease
        with cache_lease(folder / 'audio_16k.npy'):
            audio = np.load(folder / 'audio_16k.npy', mmap_mode='r', allow_pickle=False)
            try:
                if audio.ndim != 1 or audio.dtype != np.float32 or len(audio) != meta.get('samples'):
                    return None
                start = round((layer['source_in_ms'] + a-layer['timeline_in_ms']) * 16)
                count = round((b-a)*16)
                if start < 0 or start+count > len(audio) or count > 16000*60:
                    return None
                # Three output samples per input sample. The whole file stays
                # memory-mapped; only the requested seconds enter RAM.
                clip = np.asarray(audio[start:start+count])
                if not np.isfinite(clip).all():
                    return None
                values = np.interp(np.arange(count*3)/3., np.arange(count), clip)
                pcm = np.rint(np.clip(values, -1., 1.)*32767).astype('<i2')
                return np.repeat(pcm[:, None], 2, axis=1).tobytes()
            finally:
                audio._mmap.close()
    except (OSError, ValueError, TypeError, KeyError):
        return None
