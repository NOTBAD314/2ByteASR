"""Portable cover documents. No Studio state, video decoder or model dependency."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import uuid
import zipfile

VERSION = 1
MAX_PIXELS = 64_000_000
MAX_ASSET_BYTES = 256 * 1024 * 1024
MAX_DOCUMENT_BYTES = 1024 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat()


def new_id():
    return uuid.uuid4().hex


def valid_size(width, height):
    width, height = int(width), int(height)
    if not 16 <= width <= 16384 or not 16 <= height <= 16384 or width * height > MAX_PIXELS:
        raise ValueError('画布尺寸须为 16–16384 px，且总像素不超过 6400 万。')
    return width, height


@dataclass
class CoverLayer:
    id: str = field(default_factory=new_id)
    kind: str = 'image'
    name: str = '图片'
    x: float = 0
    y: float = 0
    width: float = 100
    height: float = 100
    opacity: float = 1
    visible: bool = True
    locked: bool = False
    keep_aspect: bool = True
    asset: str = ''
    text: str = ''
    style: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload):
        layer = cls(**{k: v for k, v in payload.items() if k in cls.__dataclass_fields__})
        if layer.kind not in ('image', 'text') or not layer.id:
            raise ValueError('封面图层类型或 ID 无效。')
        for key in ('x', 'y', 'width', 'height', 'opacity'):
            number = float(getattr(layer, key))
            if not math.isfinite(number):
                raise ValueError('封面图层含无效数值。')
            setattr(layer, key, number)
        if not 0 < layer.width <= 32768 or not 0 < layer.height <= 32768:
            raise ValueError('图层尺寸超出可编辑范围。')
        if not 0 <= layer.opacity <= 1 or not isinstance(layer.style, dict):
            raise ValueError('图层样式无效。')
        if abs(layer.x) > 1000000 or abs(layer.y) > 1000000:
            raise ValueError('图层位置超出可编辑范围。')
        if not isinstance(layer.text, str) or len(layer.text) > 20000:
            raise ValueError('文字内容无效或超过 2 万字。')
        if layer.kind == 'text':
            for key, low, high in [('size', 8, 2048), ('weight', 1, 1000), ('stroke', 0, 100),
                                   ('shadow_blur', 0, 100), ('shadow_x', -200, 200), ('shadow_y', -200, 200)]:
                value = float(layer.style.get(key, default_text_style()[key]))
                if not math.isfinite(value) or not low <= value <= high:
                    raise ValueError('文字样式参数无效：'+key)
            for key in ('family', 'font_style', 'color', 'stroke_color', 'shadow_color', 'alignment'):
                if key in layer.style and not isinstance(layer.style[key], str):
                    raise ValueError('文字样式参数无效：'+key)
        return layer


def default_text_style():
    return dict(family='Source Han Sans SC', weight=900, font_style='Heavy', size=96,
                color='#ffffff', stroke_color='#152c28', stroke=5,
                shadow_color='#b0000000', shadow_blur=8, shadow_x=4, shadow_y=6,
                shadow=True, alignment='left')


@dataclass
class CoverDocument:
    width: int = 1920
    height: int = 1080
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=now)
    modified_at: str = field(default_factory=now)
    source: dict = field(default_factory=dict)
    background: str = '#00000000'
    jpeg_background: str = '#ffffff'
    background_id: str = ''
    background_fit: str = 'fit'
    layers: list[CoverLayer] = field(default_factory=list)
    assets: dict[str, bytes] = field(default_factory=dict, repr=False)
    asset_names: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def snapshot(self):
        # Bytes are immutable: snapshots share originals, never preview pixels.
        return deepcopy(self)

    def manifest(self):
        layers = []
        for layer in self.layers:
            payload = asdict(layer)
            for field_name in ('x', 'y', 'width', 'height', 'opacity'):
                payload[field_name] = float(payload[field_name])
            layers.append(payload)
        return dict(format='2ByteASR-cover', version=VERSION, id=self.id,
                    width=self.width, height=self.height, created_at=self.created_at,
                    modified_at=self.modified_at, source=deepcopy(self.source),
                    background=self.background, jpeg_background=self.jpeg_background,
                    background_id=self.background_id, background_fit=self.background_fit,
                    layers=layers,
                    assets={key: {'entry': f'assets/{key}', 'name': self.asset_names.get(key, '图片')}
                            for key in dict.fromkeys(layer.asset for layer in self.layers if layer.asset)})

    def signature(self):
        data = self.manifest()
        data.pop('modified_at', None)
        return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

    def layer(self, layer_id):
        return next((layer for layer in self.layers if layer.id == layer_id), None)

    def add_asset(self, data, name):
        if not data or len(data) > MAX_ASSET_BYTES:
            raise ValueError('单张素材须小于 256 MB。')
        key = hashlib.sha256(data).hexdigest()
        self.assets[key] = data
        self.asset_names[key] = str(name)
        return key

    def add_image(self, data, name, size, *, background=False):
        key = self.add_asset(data, name)
        width, height = size
        ratio = min(self.width / width, self.height / height, 1.0)
        layer = CoverLayer(asset=key, name=name, width=width*ratio, height=height*ratio,
                           x=(self.width-width*ratio)/2, y=(self.height-height*ratio)/2)
        if background:
            previous = self.layer(self.background_id)
            if previous:
                previous.asset = key
                previous.name = '底图 · ' + name
                layer = previous
            else:
                layer.name = '底图 · ' + name
                layer.locked = False
                self.layers.insert(0, layer)
                self.background_id = layer.id
            self.fit_background(size)
        else:
            self.layers.append(layer)
        return layer

    def fit_background(self, size):
        layer = self.layer(self.background_id)
        if not layer:
            return
        width, height = size
        ratio = 1.0 if self.background_fit == 'original' else (
            max(self.width/width, self.height/height) if self.background_fit == 'fill'
            else min(self.width/width, self.height/height))
        layer.width, layer.height = width*ratio, height*ratio
        layer.x, layer.y = (self.width-layer.width)/2, (self.height-layer.height)/2

    def add_text(self, text='在这里输入标题'):
        style = default_text_style()
        style['size'] = max(20, round(self.width/20))
        layer = CoverLayer(kind='text', name='标题', text=text, x=self.width*.07,
                           y=self.height*.12, width=self.width*.8, height=self.height*.3, style=style)
        self.layers.append(layer)
        return layer

    @classmethod
    def load(cls, filename):
        try:
            with zipfile.ZipFile(filename) as archive:
                manifest_info = archive.getinfo('document.json')
                if manifest_info.file_size > 8*1024*1024:
                    raise ValueError('封面文档描述过大。')
                payload = json.loads(archive.read(manifest_info).decode('utf-8'))
                if payload.get('format') != '2ByteASR-cover' or payload.get('version') != VERSION:
                    raise ValueError('封面工程版本不支持；请保留原文件并用对应版本打开。')
                width, height = valid_size(payload['width'], payload['height'])
                doc = cls(width=width, height=height)
                for key in ('id', 'created_at', 'modified_at', 'source', 'background', 'jpeg_background', 'background_id', 'background_fit'):
                    if key in payload:
                        setattr(doc, key, payload[key])
                if not isinstance(doc.source, dict) or doc.background_fit not in ('fit', 'fill', 'original'):
                    raise ValueError('封面来源或底图布局无效。')
                if not isinstance(payload.get('layers'), list) or len(payload['layers']) > 500:
                    raise ValueError('图层列表无效或超过 500 层。')
                doc.layers = [CoverLayer.from_dict(layer) for layer in payload['layers']]
                if len({layer.id for layer in doc.layers}) != len(doc.layers):
                    raise ValueError('图层 ID 重复，原工程未修改。')
                total = 0
                for key, metadata in payload.get('assets', {}).items():
                    if not re_asset_id(key):
                        raise ValueError('素材 ID 无效。')
                    doc.asset_names[key] = str(metadata.get('name', '图片'))
                    try:
                        info = archive.getinfo(f'assets/{key}')
                        total += info.file_size
                        if info.file_size > MAX_ASSET_BYTES or total > MAX_DOCUMENT_BYTES:
                            raise ValueError('素材超过可用内存限制。')
                        data = archive.read(info)
                        if hashlib.sha256(data).hexdigest() != key:
                            raise ValueError('素材校验失败')
                        doc.assets[key] = data
                    except (KeyError, ValueError, zipfile.BadZipFile) as exc:
                        doc.warnings.append(f'素材缺失或损坏：{doc.asset_names[key]}；选择该图层后点“重新定位素材”。{exc}')
                return doc
        except (OSError, zipfile.BadZipFile, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f'无法打开封面工程，当前内容保持不变：{exc}') from exc

    def save(self, filename):
        valid_size(self.width, self.height)
        for layer in self.layers:
            CoverLayer.from_dict(asdict(layer))
        destination = Path(filename)
        if not destination.parent.is_dir():
            raise OSError('工程目录不存在，请选择可写目录。')
        used = {layer.asset for layer in self.layers if layer.asset}
        if used - self.assets.keys():
            raise ValueError('请先重新定位缺失素材，再保存工程；原文件保持不变。')
        descriptor, temporary = tempfile.mkstemp(prefix='.'+destination.stem+'-', suffix='.partial', dir=destination.parent)
        try:
            with os.fdopen(descriptor, 'w+b') as handle:
                with zipfile.ZipFile(handle, 'w', compression=zipfile.ZIP_STORED) as archive:
                    payload = self.manifest()
                    payload['modified_at'] = now()
                    archive.writestr('document.json', json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8'))
                    for key in sorted(used):
                        archive.writestr(f'assets/{key}', self.assets[key])
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)


def re_asset_id(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)
