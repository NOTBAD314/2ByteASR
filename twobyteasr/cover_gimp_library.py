"""Non-destructive XCF template generations and independent document drafts."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import struct
import time
import uuid

from .cover_library import CoverLibrary
from .cover_psd import atomic_bytes


def check_xcf(data):
    if not data.startswith(b'gimp xcf ') or len(data)<26:raise ValueError('不是有效的 XCF 文件')
    end=data.index(b'\0',9)
    width,height=struct.unpack_from('>II',data,end+1)
    if not 0<width<=16384 or not 0<height<=16384 or width*height>64_000_000:raise ValueError('XCF 画布尺寸超出范围')
    return width,height


class GimpCoverLibrary(CoverLibrary):
    def __init__(self, root=None):
        if root is None:
            from .settings import stable_settings_root
            root=stable_settings_root()/'cover-workspace'
        self.root=Path(root)
        self.root.mkdir(parents=True,exist_ok=True)
        self.backup_legacy()
        super().__init__(self.root)
        self.recovery=self.root/'drafts-xcf';self.recovery.mkdir(exist_ok=True)
        self.adopt_bundled()

    def backup_legacy(self):
        marker=self.root/'gimp-migration-backup.json'
        if marker.exists():return
        backup=self.root/'migration-backups'/('before-gimp-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
        files=[]
        if (self.root/'templates').exists():files.extend((self.root/'templates').rglob('*'))
        files.extend(self.root.glob('draft*.*'))
        receipt=[]
        for src in files:
            if not src.is_file() or src.is_symlink():continue
            relative=src.relative_to(self.root);out=backup/relative;out.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(src,out)
            digest=hashlib.sha256(src.read_bytes()).hexdigest()
            if hashlib.sha256(out.read_bytes()).hexdigest()!=digest:raise OSError('旧封面库备份校验失败')
            receipt.append(dict(file=relative.as_posix(),sha256=digest))
        atomic_bytes(marker,json.dumps(dict(backup=str(backup),files=receipt,time=time.time()),ensure_ascii=False,indent=2).encode('utf8'))

    def entries(self):
        result=[]
        for path in self.templates.glob('*.json'):
            try:
                entry=json.loads(path.read_text(encoding='utf8'))
                if not entry.get('deleted') and self.asset(entry,'xcf' if entry.get('xcf') else 'psd').is_file():result.append(entry)
            except (OSError,ValueError,KeyError):continue
        return sorted(result,key=lambda entry:entry.get('used',0),reverse=True)

    def save_xcf(self,name,data,thumbnail,*,slots=None,strategy='fill',focus=(.5,.5),key=None,warnings=None):
        width,height=check_xcf(data)
        if not thumbnail.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('缩略图生成失败；模板未更新')
        key=key or uuid.uuid4().hex
        old=self.get(key) if self._manifest(key).exists() else {}
        generation=uuid.uuid4().hex
        xcf=f'{key}-{generation}.xcf';png=f'{key}-{generation}.png'
        atomic_bytes(self.templates/xcf,data);atomic_bytes(self.templates/png,thumbnail)
        entry=deepcopy(old)
        if old.get('psd') and not old.get('xcf'):
            entry['legacy_psd']=old['psd'];entry['legacy_slots']=old.get('slots',{})
        entry.update(id=key,name=name.strip() or '未命名模板',xcf=xcf,thumbnail=png,width=width,height=height,
                     slots=deepcopy(slots or {}),strategy=strategy,focus=list(focus),version=2,
                     favorite=old.get('favorite',False),used=old.get('used',0),updated=time.time(),warnings=list(warnings or []))
        self.metadata(entry)
        return entry

    def duplicate(self,entry):
        if not entry.get('xcf'):return super().duplicate(entry)
        return self.save_xcf(entry['name']+' 副本',self.asset(entry,'xcf').read_bytes(),self.asset(entry,'thumbnail').read_bytes(),
                             slots=entry.get('slots'),strategy=entry.get('strategy','fill'),focus=entry.get('focus',(.5,.5)),warnings=entry.get('warnings'))

    def adopt_bundled(self):
        directory=Path(__file__).resolve().parents[1]/'assets/cover-templates'
        manifest=directory/'gimp-index.json'
        if not manifest.is_file():return
        for bundled in json.loads(manifest.read_text(encoding='utf8')):
            try:
                entry=self.get(bundled['id'])
                if entry.get('xcf') or entry.get('deleted'):continue
                original=self.asset(entry,'psd').read_bytes()
                # Only migrate an EXACT bundled original. Edited user masters are
                # opened and checked separately, never replaced by sample content.
                if hashlib.sha256(original).hexdigest()!=bundled['source_psd_sha256']:continue
                for field in ('xcf','thumbnail'):
                    if Path(bundled[field]).name!=bundled[field]:raise ValueError('内置模板路径无效')
                self.save_xcf(entry['name'],(directory/bundled['xcf']).read_bytes(),(directory/bundled['thumbnail']).read_bytes(),
                              key=entry['id'],slots=bundled['slots'],strategy=entry.get('strategy','fill'),
                              focus=entry.get('focus',(.5,.5)),warnings=bundled.get('warnings'))
            except (OSError,KeyError,ValueError):continue

    def drafts(self):
        rows=[]
        for path in self.recovery.glob('*.json'):
            try:
                row=json.loads(path.read_text(encoding='utf8'))
                file=self._draft_asset(row['file'])
                if row.get('active') and file.is_file():rows.append(row)
            except (OSError,KeyError,ValueError):continue
        return sorted(rows,key=lambda row:row.get('time',0),reverse=True)

    def _draft_asset(self,name):
        if Path(name).name!=name:raise ValueError('草稿资源路径无效')
        return self.recovery/name

    def save_xcf_draft(self,document,data,*,filename='',template='',slots=None,saved_time=None):
        if not document or any(c not in '0123456789abcdef' for c in document):raise ValueError('草稿文档标识无效')
        check_xcf(data)
        file=document+'-'+uuid.uuid4().hex+'.xcf';atomic_bytes(self.recovery/file,data)
        row=dict(document=document,file=file,filename=filename,template=template,slots=slots or {},time=saved_time or time.time(),active=True)
        atomic_bytes(self.recovery/(document+'.json'),json.dumps(row,ensure_ascii=False).encode('utf8'))
        owned=sorted(self.recovery.glob(document+'-*.xcf'),key=lambda p:p.stat().st_mtime,reverse=True)
        for old in owned[2:]:
            try:old.unlink()
            except OSError:pass
        return row

    def dismiss_xcf_draft(self,document):
        if not document or any(c not in '0123456789abcdef' for c in document):raise ValueError('草稿文档标识无效')
        path=self.recovery/(document+'.json')
        if path.exists():
            row=json.loads(path.read_text(encoding='utf8'));row['active']=False
            atomic_bytes(path,json.dumps(row,ensure_ascii=False).encode('utf8'))

    def collect_session_drafts(self):
        """Recover durable snapshots even if the host quit before receiving an event."""
        for pointer in (self.root/'gimp-sessions').glob('*/draft-*.json'):
            try:
                row=json.loads(pointer.read_text(encoding='utf8'));document=row['document']
                if (pointer.parent/('closed-'+document+'.json')).exists():continue
                saved=pointer.parent/('saved-'+document+'.json')
                if saved.exists() and json.loads(saved.read_text(encoding='utf8'))['time']>=row['time']:
                    self.dismiss_xcf_draft(document);continue
                current=self.recovery/(document+'.json')
                if current.exists() and json.loads(current.read_text(encoding='utf8')).get('time',0)>=row['time']:continue
                path=(pointer.parent/row['file']).resolve()
                if not path.is_relative_to((pointer.parent/'outputs').resolve()):continue
                data=path.read_bytes()
                if hashlib.sha256(data).hexdigest()!=row['sha256']:continue
                meta_path=pointer.parent/'documents'/(document+'.json')
                meta=json.loads(meta_path.read_text(encoding='utf8')) if meta_path.exists() else {}
                self.save_xcf_draft(document,data,filename=row.get('state',{}).get('file',''),
                                    template=meta.get('template',''),slots=meta.get('slots',{}),saved_time=row['time'])
            except (OSError,KeyError,ValueError):continue
