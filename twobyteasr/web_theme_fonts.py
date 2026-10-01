"""Application-owned, offline font faces; models cannot inject asset URLs."""
import base64
import json
from functools import lru_cache
from .runtime_paths import detect_install_root

FONT_FILES={'Cubic 11':('Cubic11.ttf','truetype'),
            'Source Han Sans SC':('SourceHanSansSC-Medium.woff2','woff2'),
            'Source Han Sans SC Heavy':('SourceHanSansSC-Heavy.otf','opentype'),
            '思源黑体 Heavy':('SourceHanSansSC-Heavy.otf','opentype'),
            'Source Han Sans SC Medium':('SourceHanSansSC-Medium.otf','opentype'),
            'Smiley Sans':('SmileySans-Oblique.woff2','woff2'),
            'ZCOOL KuaiLe':('ZCOOLKuaiLe-Regular.ttf','truetype'),
            'ZCOOL QingKe HuangYou':('ZCOOLQingKeHuangYou-Regular.ttf','truetype')}


def font_use_receipt(family,diagnostics):
    declared=str(family).split(',')[0].strip().strip('\"\'')
    actual=sorted({font['familyName'] for row in diagnostics.get('rendered_fonts',[])
        for font in row['fonts'] if font.get('glyphCount',0)})
    aliases={'思源黑体 Heavy':'Source Han Sans SC Heavy','Source Han Sans SC':'Source Han Sans SC Medium'}
    expected=aliases.get(declared,declared)
    matched=any(name.casefold()==expected.casefold() or name.casefold().startswith(expected.casefold()+' ') for name in actual)
    warning=('请求字体“'+declared+'”未用于此正文；实际替代为'+ '、'.join(actual)) if actual and not matched else ''
    if not actual:warning='浏览器未返回实际字形字体，不能确认请求字体已使用。'
    return dict(requested=declared,actual=actual,warning=warning)


def css_font_stack(family):
    """Quote each named face: a bare number makes an entire CSS stack invalid."""
    generic={'serif','sans-serif','monospace','cursive','fantasy','system-ui','ui-serif','ui-sans-serif','ui-monospace','ui-rounded','emoji','math','fangsong'}
    names=[n.strip().strip('"\'') for n in str(family or '').split(',')]
    return ', '.join(n.lower() if n.lower() in generic else json.dumps(n,ensure_ascii=False)
                     for n in names if n) or 'sans-serif'


def offline_font_css(family):
    sources=[]
    for name in [name.strip().strip('\"\'') for name in str(family).split(',')]:
        if name not in FONT_FILES:continue
        filename,format_name=FONT_FILES[name]
        path=detect_install_root()/'assets/fonts'/filename
        stat=path.stat()  # Missing bundled faces are explicit errors, not silent claims.
        sources.append((name,str(path),format_name,stat.st_mtime_ns,stat.st_size))
    return _offline_font_css(tuple(sources))


@lru_cache(maxsize=16)
def _offline_font_css(sources):
    faces=[]
    from pathlib import Path
    for name,path,format_name,mtime,size in sources:
        data=Path(path).read_bytes()
        encoded=base64.b64encode(data).decode('ascii')
        faces.append(f'@font-face{{font-family:"{name}";src:url(data:font/{format_name};base64,{encoded}) format("{format_name}");font-weight:100 900;font-style:normal;font-display:block;}}')
    return '\n'.join(faces)
