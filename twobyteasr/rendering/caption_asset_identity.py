"""Content dependencies for reusable browser assets, separate from code builds.

Only cue-local renderers can omit inactive cues. A composition-wide WebTheme
retains its complete clock, ordering and dependencies, including ambient layers.
"""
from fractions import Fraction
from functools import lru_cache
from functools import wraps
from contextvars import ContextVar
import hashlib
import json
import math
import os
import platform
from pathlib import Path

_IDENTITY_SCOPE=ContextVar('export_renderer_identity',default=None)

def current_identity_cache():
    return _IDENTITY_SCOPE.get()

def renderer_identity_scope(function):
    """One immutable runtime observation per job, refreshed by the next job."""
    @wraps(function)
    def run(*args,**kwargs):
        if _IDENTITY_SCOPE.get() is not None:return function(*args,**kwargs)
        token=_IDENTITY_SCOPE.set({})
        try:return function(*args,**kwargs)
        finally:_IDENTITY_SCOPE.reset(token)
    return run


def font_catalog_identity():
    """Observe platform fallback-font changes without opening every font file."""
    scoped=current_identity_cache()
    if scoped is not None and 'font_catalog' in scoped:return scoped['font_catalog']
    if os.name=='nt':
        roots=[Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts',
               Path.home()/'AppData/Local/Microsoft/Windows/Fonts']
    else:
        roots=[Path('/System/Library/Fonts'),Path('/Library/Fonts'),Path.home()/'Library/Fonts',
               Path('/usr/share/fonts'),Path.home()/'.local/share/fonts']
    rows=[]
    for index,root in enumerate(roots):
        pending=[(root,'')]
        while pending:
            folder,prefix=pending.pop()
            try:
                with os.scandir(folder) as entries:
                    for item in entries:
                        if item.is_dir(follow_symlinks=False):pending.append((Path(item.path),prefix+item.name+'/'))
                        elif item.name.lower().endswith(('.ttf','.otf','.ttc','.woff','.woff2')):
                            stat=item.stat(follow_symlinks=False)
                            rows.append((index,prefix+item.name,f'{stat.st_size}:{stat.st_mtime_ns}'))
            except OSError:continue
    app_root=Path(__file__).resolve().parents[2]
    for folder in ('assets/fonts','renderer/public/fonts'):
        for path in (app_root/folder).glob('*'):
            if path.suffix.casefold() in {'.ttf','.otf','.ttc','.woff','.woff2'} and path.is_file():
                rows.append((len(roots),path.relative_to(app_root).as_posix(),file_digest(path)))
    value=hashlib.sha256(json.dumps([platform.system(),platform.version(),sorted(rows)],
        ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    if scoped is not None:scoped['font_catalog']=value
    return value

_FONTS={
 'Cubic 11':'Cubic11.ttf','Source Han Sans SC':'SourceHanSansSC-Medium.woff2',
 'Source Han Sans SC Heavy':'SourceHanSansSC-Heavy.otf','思源黑体 Heavy':'SourceHanSansSC-Heavy.otf',
 'Source Han Sans SC Medium':'SourceHanSansSC-Medium.otf','Smiley Sans':'SmileySans-Oblique.woff2',
 'ZCOOL KuaiLe':'ZCOOLKuaiLe-Regular.ttf','ZCOOL QingKe HuangYou':'ZCOOLQingKeHuangYou-Regular.ttf'}

@lru_cache(maxsize=128)
def _file_digest(path, size, modified):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def file_digest(path):
    path=Path(path)
    stat=path.stat()
    return _file_digest(str(path),stat.st_size,stat.st_mtime_ns)

def _families(value):
    result=set()
    if isinstance(value,dict):
        for name,child in value.items():
            if name=='fontFamily' or name=='family' and isinstance(child,str):
                result.update(x.strip().strip('\"\'') for x in str(child).split(','))
            else:result.update(_families(child))
    elif isinstance(value,(tuple,list)):
        for child in value:result.update(_families(child))
    return result

def font_dependencies(props, cues):
    families=_families([c.get('visual') or props.get('recipes',{}).get(c.get('styleId')) for c in cues])
    root=Path(__file__).resolve().parents[2]/'renderer/public/fonts'
    bundled={name:file_digest(root/_FONTS[name]) for name in sorted(families) if name in _FONTS}
    embedded=[]
    for face in props.get('fontFaces',[]):
        if face.get('family') in families:
            embedded.append({**{k:v for k,v in face.items() if k!='source'},
                'source_digest':hashlib.sha256(str(face.get('source','')).encode()).hexdigest()})
    return dict(bundled=bundled,embedded=embedded,fallback_catalog=font_catalog_identity())

def asset_dependencies(props, first=None, last=None, *, still=False):
    from .advanced_renderer import _web_theme_composition
    if _web_theme_composition(props):
        return dict(schema='caption-asset-v2-global',props=props,first=first,last=last,
                    fonts=font_dependencies(props,props.get('cues',[])))
    cues=props.get('cues',[])
    rate=Fraction(str(props.get('fps') or 30)).limit_denominator(100100)
    if first is not None:
        stop=first+1 if still else last+1
        cues=[c for c in cues if Fraction(c['startMs'],1000)*rate < stop
              and Fraction(c['endMs'],1000)*rate > first]
    values=[]
    for cue in cues:
        # IDs, generation counters, snapshot hashes, recipe names and unused
        # style definitions do not draw pixels. Keep visual graphs untouched.
        value={k:v for k,v in cue.items() if k not in {'id','styleId','snapshotHash','resolvedStyleHash'}}
        visual=cue.get('visual') or props.get('recipes',{}).get(cue.get('styleId'))
        value['visual']={k:v for k,v in (visual or {}).items() if k!='name'}
        if still:
            value={k:v for k,v in value.items() if k not in {'startMs','endMs','localOffsetMs','cueDurationMs'}}
        values.append(value)
    return dict(schema='caption-asset-v2-local',width=props['width'],height=props['height'],fps=props['fps'],
                cues=values,frames=None if still else [0,props['durationInFrames']-1] if first is None else [first,last],
                fonts=font_dependencies(props,cues))

def asset_key(props, first=None, last=None, *, still=False, fingerprint=None):
    from .advanced_renderer import _renderer_cache_fingerprint
    return hashlib.sha256(json.dumps([fingerprint or _renderer_cache_fingerprint(),asset_dependencies(props,first,last,still=still)],
        ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def asset_windows(props,total_frames):
    from .advanced_renderer import _web_theme_composition
    if _web_theme_composition(props):return [(0,total_frames-1)]
    rate=Fraction(str(props.get('fps') or 30)).limit_denominator(100100)
    spans=[]
    for cue in props.get('cues',[]):
        a=max(0,math.ceil(Fraction(cue['startMs'],1000)*rate))
        b=min(total_frames-1,math.ceil(Fraction(cue['endMs'],1000)*rate)-1)
        if b>=a:spans.append((a,b))
    result=[]
    for a,b in sorted(spans):
        if result and a<=result[-1][1]:result[-1]=(result[-1][0],max(result[-1][1],b))
        else:result.append((a,b))
    return result
