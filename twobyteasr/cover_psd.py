"""Offline RGB/8 PSD writer with real type layers; original assets in XMP.

The Qt reader never silently flattens changed or unsupported external PSDs
and overwrites their source.
"""
import base64
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

from .cover_document import CoverDocument
from .cover_render import CoverRenderer, text_font

ROOT = Path(__file__).resolve().parents[1]


def atomic_bytes(path, data):
    path = Path(path)
    fd, temp = tempfile.mkstemp(prefix='.'+path.name+'.', suffix='.partial', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _adapter(mode, source, target):
    result = subprocess.run([str(ROOT/'tools/node/node.exe'), str(ROOT/'third_party/cover-psd.cjs'), mode, str(source), str(target)],
        capture_output=True, timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError('PSD 处理失败：'+result.stderr.decode('utf8', errors='replace')[-1200:])


def _pixels(image):
    image = image.convertToFormat(QImage.Format_RGBA8888)
    return dict(width=image.width(), height=image.height(), data=base64.b64encode(bytes(image.constBits())).decode('ascii'))


def _color(value):
    color = QColor(value)
    return dict(r=color.red(), g=color.green(), b=color.blue())


def psd_id(key):
    import hashlib
    return int(hashlib.sha256(key.encode()).hexdigest()[:7], 16)+1


def encode_psd(document):
    renderer = CoverRenderer()
    doc = dict(width=document.width, height=document.height, children=[], imageData=_pixels(renderer.render(document)))
    canvas_color=QColor(document.background)
    if canvas_color.alpha():
        canvas=QImage(document.width,document.height,QImage.Format_RGBA8888);canvas.fill(canvas_color)
        doc['children'].append(dict(name='画布底色',id=psd_id('cover-canvas-fill'),left=0,top=0,opacity=1,
            hidden=False,blendMode='normal',protected=dict(composite=True,position=True,transparency=True),imageData=_pixels(canvas)))
    for layer in document.layers:
        image = renderer.layer_image(document, layer)
        if layer.kind == 'image':
            image = image.scaled(max(1, round(layer.width)), max(1, round(layer.height)), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        entry = dict(name=layer.name, id=psd_id(layer.id), left=round(layer.x), top=round(layer.y),
                     opacity=layer.opacity, hidden=not layer.visible, blendMode='normal',
                     protected=dict(composite=layer.locked,position=layer.locked,transparency=layer.locked), imageData=_pixels(image))
        if layer.kind == 'text':
            style = layer.style
            _, warning, face = text_font(style)
            if warning:
                raise ValueError(warning+'；选择已安装字体后保存 PSD，避免静默替换。')
            size = float(style.get('size',96))
            stroke = float(style.get('stroke',0))
            blur = float(style.get('shadow_blur',0)) if style.get('shadow') else 0
            dx, dy = (float(style.get('shadow_x',0)),float(style.get('shadow_y',0))) if style.get('shadow') else (0,0)
            pad = math.ceil(stroke+blur*3+max(abs(dx),abs(dy))+4)
            entry['text'] = dict(text=layer.text, transform=[1,0,0,1,layer.x+pad,layer.y+pad+size],
                shapeType='box', boxBounds=[0,-size,max(16,layer.width-pad*2),image.height()-size],
                bounds={key:dict(units='Points',value=value) for key,value in [('left',0),('top',-size),('right',layer.width-pad*2),('bottom',image.height()-size)]},
                boundingBox={key:dict(units='Points',value=value) for key,value in [('left',0),('top',-size),('right',layer.width-pad*2),('bottom',image.height()-size)]},
                antiAlias='smooth', style=dict(font=dict(name=face.postscript,script=0,type=1,synthetic=0),fontSize=size,fillColor=_color(style.get('color','#ffffff'))),
                paragraphStyle=dict(justification=style.get('alignment','left')))
            effects = dict(scale=1,disabled=False)
            if stroke:
                effects['stroke'] = [dict(enabled=True,present=True,showInDialog=True, size=dict(units='Pixels',value=stroke), position='outside', fillType='color',
                    color=_color(style.get('stroke_color','#152c28')), blendMode='normal',opacity=1)]
            if style.get('shadow'):
                effects['dropShadow'] = [dict(enabled=True,present=True,showInDialog=True,antialiased=False,layerConceals=True,
                    contour=dict(name='Linear',curve=[dict(x=0,y=0),dict(x=255,y=255)]),noise=0,
                    color=_color(style.get('shadow_color','#000000')),
                    opacity=QColor(style.get('shadow_color','#000000')).alphaF(), blendMode='multiply',useGlobalLight=False,
                    angle=math.degrees(math.atan2(-dy,dx)), distance=dict(units='Pixels',value=math.hypot(dx,dy)),
                    size=dict(units='Pixels',value=blur), choke=dict(units='Pixels',value=0))]
            if stroke or style.get('shadow'):
                entry['effects'] = effects
        doc['children'].append(entry)
    with tempfile.TemporaryDirectory(prefix='2byte-psd-') as folder:
        folder = Path(folder)
        archive = folder/'original.2bytecover'
        document.save(archive)
        doc['archive'] = base64.b64encode(archive.read_bytes()).decode('ascii')
        (folder/'input.json').write_text(json.dumps(doc,ensure_ascii=False),encoding='utf8')
        _adapter('write', folder/'input.json', folder/'output.psd')
        return (folder/'output.psd').read_bytes()


def save_psd(document, path):
    data = encode_psd(document)
    atomic_bytes(path, data)
    return dict(path=str(path),bytes=len(data))


def inspect_psd(path):
    with tempfile.TemporaryDirectory(prefix='2byte-psd-read-') as folder:
        target=Path(folder)/'structure.json'
        _adapter('read', path, target)
        return json.loads(target.read_text(encoding='utf8'))


def psd_metadata(path):
    with tempfile.TemporaryDirectory(prefix='2byte-psd-meta-') as folder:
        target=Path(folder)/'structure.json'
        _adapter('meta',path,target)
        return json.loads(target.read_text(encoding='utf8'))


def load_local_psd(path):
    result = inspect_psd(path)
    xmp = result['document'].get('imageResources',{}).get('xmpMetadata','')
    match = re.search(r'bc:data="([A-Za-z0-9+/=]+)"', xmp)
    if match:
        metadata = json.loads(base64.b64decode(match[1]))
        if metadata.get('fingerprint') == result['fingerprint']:
            with tempfile.TemporaryDirectory(prefix='2byte-cover-original-') as folder:
                archive = Path(folder)/'original.2bytecover'
                archive.write_bytes(base64.b64decode(metadata['archive']))
                return CoverDocument.load(archive)
    raise ValueError('此 PSD 已由外部编辑器修改或包含本地编辑器不支持的结构。可用原编辑器导出 PNG 后添加为图片；原文件未修改。')
