"""Verified cropped Qt stills; font bytes and drawing code own their identity."""
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import uuid

@lru_cache(maxsize=1)
def _engine():
    from PySide6.QtCore import qVersion
    import PySide6
    root=Path(__file__).resolve().parents[1]
    h=hashlib.sha256(f'qt-export-still-v1:{PySide6.__version__}:{qVersion()}'.encode())
    paths=[*root.joinpath('caption_style').glob('*.py'),root/'rendering/advanced_live_renderer.py',
           root/'rendering/alpha_geometry.py',root/'rendering/static_export_cache.py',
           root/'rendering/marked_glyphs.py',root/'rendering/letter_motion_live.py',
           root/'caption_design/visual_design_graph.py',root/'studio/studio_helpers.py']
    for path in sorted(paths):
        h.update(path.relative_to(root).as_posix().encode());h.update(path.read_bytes())
    return h.hexdigest()

def cache_key(snapshot,width,height):
    from .caption_asset_identity import file_digest,font_catalog_identity
    face=json.loads(getattr(snapshot.resolved_caption,'font_face_json','{}'))
    font=Path(face.get('file') or '')
    if not font.is_file():return None
    pixel=snapshot.pixel_hash(renderer_version=_engine(),resolution=(width,height),device_pixel_ratio=1.)
    face={k:v for k,v in face.items() if k!='file'}
    # pixel_hash deliberately omits graph/name/motion metadata for preview
    # reuse. Export stills must also cover static panels and graph parameters.
    recipe={k:v for k,v in (snapshot.style_recipe or {}).items() if k!='name'}
    return hashlib.sha256(json.dumps([pixel,recipe,getattr(snapshot,'word_animation',{}),face,
        file_digest(font),font_catalog_identity()],sort_keys=True).encode()).hexdigest()

def _paths(key):
    from .advanced_renderer import _overlay_cache_dir
    image=_overlay_cache_dir()/('qt-'+key+'.still.png')
    return image,image.with_suffix('.geometry.json')

def restore(key,target,width,height):
    if not key:return None
    from PySide6.QtGui import QImage
    from .advanced_renderer import _copy_verified_overlay,_overlay_digest
    source,meta=_paths(key)
    try:
        data=json.loads(meta.read_text('utf8'));box=data['bounds']
        if (data.get('key')!=key or data.get('canvas')!=[width,height] or len(box)!=4
            or not all(type(v) is int for v in box)
            or not (0<=box[0]<box[2]<=width and 0<=box[1]<box[3]<=height)
            or data.get('sha256')!=_overlay_digest(source)):
            return None
        if not _copy_verified_overlay(source,target):return None
        image=QImage(str(target))
        if image.isNull() or (image.width(),image.height())!=(box[2]-box[0],box[3]-box[1]):
            target.unlink(missing_ok=True);return None
        os.utime(source,None)
        return (target,tuple(box),None)
    except (OSError,ValueError,KeyError,TypeError):return None

def store(key,source,bounds,width,height):
    if not key:return
    from .advanced_renderer import _cache_overlay,_overlay_digest
    target,meta=_paths(key);staged=meta.with_suffix('.'+uuid.uuid4().hex+'.tmp')
    try:
        _cache_overlay(source,target)
        staged.write_text(json.dumps(dict(key=key,bounds=list(bounds),canvas=[width,height],
                          sha256=_overlay_digest(source))),encoding='utf8')
        os.replace(staged,meta)
    except OSError:pass
    finally:staged.unlink(missing_ok=True)
