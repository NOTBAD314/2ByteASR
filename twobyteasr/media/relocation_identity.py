"""Verify known metadata fingerprints across a directory/drive relocation."""
import hashlib
import json

FINGERPRINT_FIELDS=('size','mtime_ns','duration_ms','video_codec','audio_codec','width','height','fps',
    'video_timebase','audio_timebase','sample_rate','channels','rotation','container_start_ms',
    'source_start_ms','video_start_ms','audio_start_ms','video_first_pts_ms','audio_first_pts_ms',
    'video_best_effort_timestamp_ms','audio_best_effort_timestamp_ms','sample_timeline_origin_ms')


def fingerprint_at_source(metadata, source):
    """Same fingerprint contract as MediaService, substituting only the path.

    This is a metadata identity, not a full-file cryptographic content hash.
    Incomplete/legacy identities never authorize a batch filename match.
    """
    data=dict(metadata)
    data.setdefault('size',data.get('source_size'))
    data.setdefault('mtime_ns',data.get('source_mtime_ns'))
    if any(data.get(key) is None for key in FINGERPRINT_FIELDS):return ''
    core={key:data[key] for key in FINGERPRINT_FIELDS}
    core['path']=str(source)
    return hashlib.sha256(json.dumps(core,sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest()[:20]


def verified_relocation(asset, candidate, previous_identity=None):
    if candidate.get('status')!='available' or not asset.fingerprint:return False
    sources=[asset.canonical_source]
    previous_identity=previous_identity or {}
    # Path.resolve may have expanded a SUBST/volume alias when the original
    # identity was made. Reuse only a previously verified matching identity.
    if previous_identity.get('fingerprint')==asset.fingerprint and previous_identity.get('source_path'):
        sources.append(previous_identity['source_path'])
    return any(fingerprint_at_source(candidate.get('identity',{}),source)==asset.fingerprint for source in sources)
