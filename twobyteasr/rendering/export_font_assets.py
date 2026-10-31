"""Job-local browser fonts from the exact face already resolved by Qt.

Only a font parsed by the local face resolver is embedded. These transient
assets belong to composition props, never to the saved subtitle project.
"""
from collections import OrderedDict
import base64
import hashlib
import json
from pathlib import Path
import threading

_CACHE=OrderedDict()
_LOCK=threading.Lock()
_BUDGET=32*1024*1024
_BUNDLED=frozenset({'Cubic 11','Source Han Sans SC','Source Han Sans SC Heavy','思源黑体 Heavy',
    'Source Han Sans SC Medium','Smiley Sans','ZCOOL KuaiLe','ZCOOL QingKe HuangYou'})


def font_asset(snapshot):
    resolved=getattr(snapshot,'resolved_caption',None)
    if resolved is None:return None
    face=json.loads(resolved.font_face_json)
    path=Path(face.get('file') or '')
    bundled=Path(__file__).resolve().parents[2]/'assets/fonts'
    if snapshot.font_family in _BUNDLED and path.resolve().is_relative_to(bundled):return None
    if path.suffix.lower() not in {'.ttf','.otf'}:return None
    stat=path.stat();key=(str(path),stat.st_mtime_ns,stat.st_size)
    with _LOCK:
        cached=_CACHE.get(key)
        if cached is not None:_CACHE.move_to_end(key)
    if cached is None:
        data=path.read_bytes()
        if data[:4] not in (b'\x00\x01\x00\x00',b'OTTO',b'true'):return None
        mime='otf' if data[:4]==b'OTTO' else 'ttf'
        cached=('data:font/'+mime+';base64,'+base64.b64encode(data).decode('ascii'),hashlib.sha256(data).hexdigest())
        with _LOCK:
            # Large fonts can render without occupying the persistent cache.
            if len(cached[0])<=_BUDGET:
                _CACHE[key]=cached;_CACHE.move_to_end(key)
                while sum(len(v[0])for v in _CACHE.values())>_BUDGET:_CACHE.popitem(last=False)
    italic=any(word in str(face.get('style','')).casefold()for word in ('italic','oblique'))
    return dict(family=snapshot.font_family,weight=int(face.get('weight')or snapshot.font_weight),
        style='italic' if italic else 'normal',source=cached[0],sha256=cached[1])
