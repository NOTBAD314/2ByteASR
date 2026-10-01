"""Versioned PSD templates and drafts; only the metadata pointer is replaced."""
from copy import deepcopy
import json
from pathlib import Path
import struct
import time
import uuid

from .cover_psd import atomic_bytes


class CoverLibrary:
    def __init__(self, root=None):
        if root is None:
            from .settings import stable_settings_root
            root = stable_settings_root()/'cover-workspace'
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.templates = self.root/'templates'
        self.templates.mkdir(exist_ok=True)
        self.seed_bundled()

    def seed_bundled(self):
        directory=Path(__file__).resolve().parents[1]/'assets/cover-templates'
        manifest=directory/'index.json'
        if not manifest.is_file():return
        for item in json.loads(manifest.read_text(encoding='utf8')):
            if self._manifest(item['id']).exists():continue
            if Path(item['psd']).name!=item['psd'] or Path(item['thumbnail']).name!=item['thumbnail']:continue
            self.save(item['name'],(directory/item['psd']).read_bytes(),(directory/item['thumbnail']).read_bytes(),
                      key=item['id'],slots=item['slots'],strategy=item.get('strategy','fill'),focus=item.get('focus',(.5,.5)))

    @staticmethod
    def check_psd(data):
        if not data.startswith(b'8BPS\x00\x01') or len(data) < 30:
            raise ValueError('模板需要有效的 PSD 文件。')
        height, width = struct.unpack_from('>II', data, 14)
        if not 0 < width <= 16384 or not 0 < height <= 16384:
            raise ValueError('PSD 尺寸超出范围。')
        return width, height

    def _manifest(self, key):
        if not key or any(c not in '0123456789abcdef' for c in key):
            raise ValueError('模板标识无效。')
        return self.templates/(key+'.json')

    def entries(self):
        entries=[]
        for path in self.templates.glob('*.json'):
            try:
                item=json.loads(path.read_text(encoding='utf8'))
                if not item.get('deleted') and self.asset(item,'psd').is_file():
                    entries.append(item)
            except (OSError, ValueError, KeyError):
                continue
        return sorted(entries,key=lambda item:item.get('used',0),reverse=True)

    def get(self,key):
        return json.loads(self._manifest(key).read_text(encoding='utf8'))

    def asset(self,entry,kind):
        name=entry[kind]
        if Path(name).name != name:
            raise ValueError('模板资源路径无效。')
        return self.templates/name

    def metadata(self,entry):
        atomic_bytes(self._manifest(entry['id']), json.dumps(entry,ensure_ascii=False,indent=2).encode('utf8'))

    def save(self,name,data,thumbnail,*,slots=None,strategy='fill',focus=(.5,.5),key=None):
        width,height=self.check_psd(data)
        if not thumbnail.startswith(b'\x89PNG'):
            raise ValueError('模板缩略图尚未生成，模板未更新。')
        key=key or uuid.uuid4().hex
        old=self.get(key) if self._manifest(key).exists() else {}
        generation=uuid.uuid4().hex
        psd_name=f'{key}-{generation}.psd';png_name=f'{key}-{generation}.png'
        atomic_bytes(self.templates/psd_name,data)
        atomic_bytes(self.templates/png_name,thumbnail)
        entry=dict(id=key,name=name.strip() or '未命名模板',psd=psd_name,thumbnail=png_name,width=width,height=height,
                   slots=deepcopy(slots or {}),strategy=strategy,focus=list(focus),favorite=old.get('favorite',False),
                   used=old.get('used',0),updated=time.time(),version=1)
        self.metadata(entry)  # Old valid generation remains intact on any failure.
        return entry

    def duplicate(self,entry):
        return self.save(entry['name']+' 副本',self.asset(entry,'psd').read_bytes(),self.asset(entry,'thumbnail').read_bytes(),
                         slots=entry.get('slots'),strategy=entry.get('strategy','fill'),focus=entry.get('focus',(.5,.5)))

    def mark_used(self,entry):
        entry=deepcopy(entry);entry['used']=time.time();self.metadata(entry)

    def draft(self):
        path=self.root/'draft.json'
        if not path.is_file(): return None
        try:
            entry=json.loads(path.read_text(encoding='utf8'))
            if entry.get('active') and Path(entry['file']).name==entry['file'] and (self.root/entry['file']).is_file():
                return entry
        except (OSError,ValueError,KeyError): pass
        return None

    def save_draft(self,data,*,kind='psd',document='',filename='',template='',slots=None):
        if kind=='psd': self.check_psd(data)
        generation=uuid.uuid4().hex
        name=f'draft-{generation}.{kind}'
        atomic_bytes(self.root/name,data)
        metadata=dict(active=True,file=name,kind=kind,document=document,filename=filename,template=template,slots=slots or {},time=time.time())
        atomic_bytes(self.root/'draft.json',json.dumps(metadata,ensure_ascii=False).encode('utf8'))
        # Keep the current and previous generation; cleanup only this owned namespace.
        old=sorted(self.root.glob('draft-*.*'),key=lambda p:p.stat().st_mtime,reverse=True)
        for path in old[2:]:
            try: path.unlink()
            except OSError: pass
        return metadata

    def dismiss_draft(self):
        atomic_bytes(self.root/'draft.json',b'{"active":false}')
