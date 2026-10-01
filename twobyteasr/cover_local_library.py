"""Self-contained local templates, reusing the existing library metadata UI."""
from copy import deepcopy
import json
import time
import uuid

from .cover_document import CoverDocument, new_id, now
from .cover_library import CoverLibrary
from .cover_psd import atomic_bytes, load_local_psd


class LocalCoverLibrary(CoverLibrary):
    def entries(self):
        result = []
        for path in self.templates.glob('*.json'):
            try:
                entry = json.loads(path.read_text(encoding='utf8'))
                # A migrated XCF's old PSD may be stale. Do not present that
                # old image as the current template; leave both files intact.
                kind = 'cover' if entry.get('cover') else 'psd' if not entry.get('xcf') else ''
                if kind and not entry.get('deleted') and self.asset(entry, kind).is_file():
                    result.append(entry)
            except (OSError, ValueError, KeyError):
                continue
        return sorted(result, key=lambda entry: entry.get('used', 0), reverse=True)

    def load_copy(self, entry):
        document = (CoverDocument.load(self.asset(entry, 'cover')) if entry.get('cover')
                    else load_local_psd(self.asset(entry, 'psd')))
        if document.warnings:
            raise ValueError('模板素材不完整，请重新定位后另存模板；当前封面保持不变。')
        document.id = new_id()
        document.created_at = document.modified_at = now()
        return document

    def save_native(self, name, document, thumbnail):
        if not thumbnail.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('缩略图生成失败，模板未保存。')
        # Saving as a template always creates a new master. Document filenames
        # and ordinary saves never point into this library.
        key = uuid.uuid4().hex
        cover, preview = key + '.2bytecover', key + '.png'
        document.save(self.templates / cover)
        atomic_bytes(self.templates / preview, thumbnail)
        entry = dict(id=key, name=name.strip() or '未命名模板', cover=cover, thumbnail=preview,
                     width=document.width, height=document.height, version=1,
                     favorite=False, used=0, updated=time.time())
        self.metadata(entry)
        return entry

    def duplicate(self, entry):
        return self.save_native(entry['name'] + ' 副本', self.load_copy(entry),
                                self.asset(entry, 'thumbnail').read_bytes())

    @staticmethod
    def replace_frame(document, frame_document):
        """Replace the explicit background slot, preserving every foreground."""
        background = document.layer(document.background_id)
        source = frame_document.layer(frame_document.background_id)
        if source is None:
            raise ValueError('没有有效冻结帧；原封面保持不变。')
        from .cover_render import read_image_bytes
        data = frame_document.assets[source.asset]
        image = read_image_bytes(data)
        if background is None:
            document.add_image(data, '当前截图.png', (image.width(), image.height()), background=True)
        else:
            background.asset = document.add_asset(data, '当前截图.png')
            background.name = '底图 · 当前截图.png'
            background.visible, background.opacity = True, 1.0
            document.fit_background((image.width(), image.height()))
        document.source = deepcopy(frame_document.source)

    @staticmethod
    def frame_obstructions(document):
        """Name opaque foreground artwork without deleting or reclassifying it."""
        import io
        from PIL import Image
        names=[]
        for layer in document.layers:
            if (layer.id==document.background_id or layer.kind!='image' or not layer.visible
                    or layer.opacity<1 or layer.x>0 or layer.y>0
                    or layer.x+layer.width<document.width or layer.y+layer.height<document.height):continue
            with Image.open(io.BytesIO(document.assets[layer.asset])) as image:
                if image.convert('RGBA').getchannel('A').getextrema()==(255,255):names.append(layer.name)
        return names
