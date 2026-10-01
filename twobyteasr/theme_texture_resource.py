"""Small, self-contained vector textures; no network, code, fonts or recursion."""
from __future__ import annotations
import math
import re
from urllib.parse import unquote_to_bytes
from xml.etree import ElementTree

SVG_TEXTURE_PREFIX='data:image/svg+xml,'
_URL=re.compile(r'''url\(\s*(?:"([^"\\]*)"|'([^'\\]*)'|([^\s)'"\\]*))\s*\)''',re.I)
_NUMBER=re.compile(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?')
_TAGS={'svg','g','rect','circle','ellipse','line','polyline','polygon','path'}
_GEOMETRY={'x','y','width','height','rx','ry','cx','cy','r','x1','y1','x2','y2','stroke-width'}
_PAINT={'fill','stroke'}
_OPACITY={'opacity','fill-opacity','stroke-opacity'}
_NAMESPACE='{http://www.w3.org/2000/svg}'
RESOURCE_POLICY_VERSION='static-svg-3'

def _numbers(value,count=None):
    tokens=_NUMBER.findall(value)
    if not tokens or (count is not None and len(tokens)!=count):raise ValueError('SVG texture numeric shape')
    if re.sub(_NUMBER,'',value).strip(' ,\t\r\n'):raise ValueError('SVG texture numeric syntax')
    values=[float(v) for v in tokens]
    if any(not math.isfinite(v) or abs(v)>4096 for v in values):raise ValueError('SVG texture coordinate limit')
    return values

def validate_svg_texture(url):
    if not url.startswith(SVG_TEXTURE_PREFIX):raise ValueError('Only percent-encoded static SVG texture data URLs are supported')
    if len(url)>12288:raise ValueError('SVG texture encoded size limit')
    encoded=url[len(SVG_TEXTURE_PREFIX):]
    if re.search(r'%(?![0-9a-fA-F]{2})',encoded) or '\\' in encoded:raise ValueError('SVG texture URL encoding')
    raw=unquote_to_bytes(encoded)
    if len(raw)>4096:raise ValueError('SVG texture decoded size limit')
    xml=raw.decode('utf8',errors='strict')
    if '<!' in xml or '<?' in xml:raise ValueError('SVG texture declarations/entities are prohibited')
    try:root=ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:raise ValueError('Malformed SVG texture') from exc
    if root.tag not in ('svg',_NAMESPACE+'svg'):raise ValueError('SVG texture root required')
    nodes=list(root.iter())
    if len(nodes)>64:raise ValueError('SVG texture node limit')
    # Only a bounded static noise filter; no image, href, input graph or recursion.
    # SVG noise has a deterministic default seed of zero.
    parents={child:parent for parent in nodes for child in parent}
    filters={}
    for node in nodes:
        if node.tag.removeprefix(_NAMESPACE)=='filter':
            ident=node.get('id','')
            if not re.fullmatch(r'[A-Za-z_][\w.-]{0,47}',ident) or ident in filters:
                raise ValueError('SVG texture filter ID missing or duplicate')
            filters[ident]=node
    if len(filters)>4:raise ValueError('SVG texture filter limit')
    for node in nodes:
        tag=node.tag.removeprefix(_NAMESPACE)
        if tag not in _TAGS|{'defs','filter','feTurbulence'} or (node is not root and tag=='svg'):
            raise ValueError('SVG texture tag prohibited: '+tag)
        if tag=='feTurbulence':
            parent=parents.get(node)
            if parent is None or parent.tag.removeprefix(_NAMESPACE)!='filter' or len(parent)!=1:
                raise ValueError('SVG noise must be the sole primitive in its filter')
        if tag in {'defs','filter'} and parents.get(node) is not root and not (
                tag=='filter' and parents.get(node) is not None and parents[node].tag.removeprefix(_NAMESPACE)=='defs'):
            raise ValueError('SVG texture filter nesting prohibited')
        if tag=='filter' and (len(node)!=1 or node[0].tag.removeprefix(_NAMESPACE)!='feTurbulence'):
            raise ValueError('SVG texture supports only a single bounded noise filter')
        if (node.text or '').strip() or (node.tail or '').strip():raise ValueError('SVG textures cannot contain text')
        for key,value in node.attrib.items():
            if tag=='feTurbulence':
                if key=='type' and value in {'fractalNoise','turbulence'}:pass
                elif key=='baseFrequency':
                    values=_numbers(value)
                    if len(values) not in (1,2) or any(not 0.001<=v<=1 for v in values):
                        raise ValueError('SVG noise frequency must be 0.001..1')
                elif key in {'numOctaves','seed'}:
                    number=_numbers(value,1)[0]
                    low,high=(1,4) if key=='numOctaves' else (0,4096)
                    if not number.is_integer() or not low<=number<=high:raise ValueError('SVG noise '+key+' limit')
                elif key=='stitchTiles' and value in {'stitch','noStitch'}:pass
                else:raise ValueError('SVG noise attribute prohibited: '+key)
            elif key=='id' and tag=='filter':pass
            elif key=='filter' and tag in _TAGS-{'svg','g'}:
                match=re.fullmatch(r'url\(#([A-Za-z_][\w.-]{0,47})\)',value)
                if not match or match.group(1) not in filters:raise ValueError('SVG texture filter reference must resolve locally')
            elif tag in {'filter','defs'}:raise ValueError('SVG texture filter attribute prohibited: '+key)
            elif key in _GEOMETRY:_numbers(value,1)
            elif key=='viewBox' and node is root:
                v=_numbers(value,4)
                if v[2]<=0 or v[3]<=0 or v[2]>1024 or v[3]>1024:raise ValueError('SVG texture viewBox limit')
            elif key in _PAINT:
                if not re.fullmatch(r'#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?|none',value):raise ValueError('SVG texture paint must be a solid color')
            elif key in _OPACITY:
                if not 0<=_numbers(value,1)[0]<=1:raise ValueError('SVG texture opacity limit')
            elif key=='points' and tag in {'polygon','polyline'}:
                if len(_numbers(value))>256:raise ValueError('SVG texture point limit')
            elif key=='d' and tag=='path':
                if len(value)>2048 or re.search(r'[^MmZzLlHhVvCcSsQqTtAa0-9eE+.,\s-]',value):raise ValueError('SVG texture path syntax')
                if any(abs(float(v))>4096 or not math.isfinite(float(v)) for v in _NUMBER.findall(value)):raise ValueError('SVG texture path limit')
            elif key=='shape-rendering' and value=='crispEdges':pass
            elif key=='preserveAspectRatio' and value in {'none','xMidYMid meet'}:pass
            elif key=='stroke-linecap' and value in {'butt','round','square'}:pass
            elif key=='stroke-linejoin' and value in {'miter','round','bevel'}:pass
            else:raise ValueError('SVG texture attribute prohibited: '+key)
    for key in ('width','height'):
        if key not in root.attrib or not 0<float(root.attrib[key])<=1024:raise ValueError('SVG texture dimensions must be 1..1024')
    return {'bytes':len(raw),'nodes':len(nodes),'width':float(root.attrib['width']),'height':float(root.attrib['height'])}

def checked_css_urls(text, *, allow_texture=True):
    """Validate every url(), returning masked CSS for the remaining token checks."""
    matches=list(_URL.finditer(text))
    remainder=_URL.sub('',text)
    # Escaped function names must not turn an unchecked URL into a fetch.
    def unescape(match):
        if match.group(1):
            code=int(match.group(1),16)
            return chr(code) if 0<code<=0x10ffff else '\ufffd'
        return match.group(2)
    remainder=re.sub(r'\\(?:\r\n|[\r\n\f])','',remainder)
    remainder=re.sub(r'\\([0-9a-fA-F]{1,6})(?:\r\n|[ \t\r\n\f])?|\\([^\r\n\f])',unescape,remainder)
    if re.search(r'url\s*\(',remainder,re.I):raise ValueError('Malformed or escaped CSS URL')
    # These functions can load string URLs without url(). Keep the resource
    # grammar deliberately bounded; gradients/ordinary CSS remain unchanged.
    if re.search(r'(?<![\w-])(?:-webkit-image-set|image-set|image|src)\s*\(', remainder, re.I):
        raise ValueError('CSS string resource functions are prohibited')
    for match in matches:
        value=next(v for v in match.groups() if v is not None).strip()
        if re.fullmatch(r'#[A-Za-z_][\w:.-]*',value):continue
        if not allow_texture:raise ValueError('SVG presentation references must be internal fragments')
        validate_svg_texture(value)
    return remainder

def valid_data_block(value):
    return bool(re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,47}',str(value or '')))
