#!/usr/bin/env python3
"""2ByteASR's private GIMP 3 persistent plug-in (GPL-3.0-or-later).

Runs in the official runtime's Python/GI, never the application's Python.
All PDB calls run on the GLib main thread. No network listener or eval endpoint.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
import uuid
import ctypes

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gegl, Gio, GLib

PARASITE = '2byte-cover-slot-v1'
DOC_TAG = '2byte-cover-document-v1'
ROLES_TAG = '2byte-cover-roles-v1'


def atomic_json(path, value):
    temp = path.with_suffix('.tmp')
    with temp.open('w', encoding='utf8') as f:
        json.dump(value, f, ensure_ascii=False)
        f.flush(); os.fsync(f.fileno())
    os.replace(temp, path)


def tag(item, name, value):
    data=value.encode('utf8')
    item.attach_parasite(Gimp.Parasite.new(name, Gimp.PARASITE_PERSISTENT, [b if b<128 else b-256 for b in data]))


def read_tag(item, name):
    p = item.get_parasite(name)
    return bytes(b & 255 for b in p.get_data()).decode('utf8') if p else ''


def layers(image):
    def visit(items):
        for item in items:
            yield item
            if item.is_group():
                yield from visit(item.get_children())
    return list(visit(image.get_layers()))


class Bridge:
    def __init__(self, plugin):
        self.plugin = plugin
        self.root = Path(os.environ['TWOBYTE_COVER_SESSION']).resolve()
        self.config = json.loads((self.root/'session.json').read_text(encoding='utf8'))
        if self.config.get('root') and self.config['root']!=str(self.root):raise ValueError('会话路径不匹配')
        self.token = self.config['token']; self.session = self.config['session']
        self.bridge_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self.docs = {}; self.displays = {}; self.completed = set(); self.active = False
        self.last_status=0; self.last_draft={}; self.drafts={}; self.last_states={}
        self.known_ids={}
        self.counter = 0

    def path(self, name):
        # Only host-staged files and private outputs are reachable via IPC.
        path = (self.root/name).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError('文件超出本次会话范围')
        return path

    def emit(self, kind, **data):
        self.counter += 1
        event=dict(session=self.session,token=self.token,event=kind,time=time.time())
        event.update(data)
        atomic_json(self.root/'events'/f'{self.counter:010d}.json',
                    event)

    def document(self, key):
        image = self.docs.get(key)
        if image is None or not image.is_valid():
            raise ValueError('文档已关闭；未写入任何目标文件')
        return image

    def describe(self, key):
        image = self.document(key)
        self.ensure_ids(image)
        file = image.get_xcf_file()
        return dict(document=key, image_id=image.get_id(), width=image.get_width(), height=image.get_height(),
                    dirty=image.is_dirty(), file=file.get_path() if file else '',
                    selected=[read_tag(l,PARASITE) for l in image.get_selected_layers()],
                    metadata=json.loads(read_tag(image,ROLES_TAG) or '{}'),
                    layers=[dict(id=read_tag(l, PARASITE), native_id=l.get_id(), name=l.get_name(),
                                 source_psd_id=int(read_tag(l,'2byte-source-psd-id') or l.get_tattoo()),
                                 reference=bool(read_tag(l,'2byte-cover-reference-v1')),
                                 text=l.get_text() if l.is_text_layer() else None,
                                 font=l.get_font().get_name() if l.is_text_layer() else '',
                                 group=l.is_group(), visible=l.get_visible(), opacity=l.get_opacity(),
                                 locked=l.get_lock_content(), position_locked=l.get_lock_position(),
                                 width=l.get_width(), height=l.get_height(), offsets=list(l.get_offsets())[1:],
                                 filters=[f.get_name() for f in l.get_filters()]) for l in layers(image)])

    def snapshot(self, image, out, verify=True):
        copy=image.duplicate()
        try:
            if not Gimp.file_save(Gimp.RunMode.NONINTERACTIVE,copy,Gio.File.new_for_path(str(out))):
                raise RuntimeError('XCF 保存失败')
            if verify:
                reopened=Gimp.file_load(Gimp.RunMode.NONINTERACTIVE,Gio.File.new_for_path(str(out)))
                if reopened is None: raise RuntimeError('XCF 写入后无法重开')
                reopened.delete()
            return hashlib.sha256(out.read_bytes()).hexdigest()
        finally: copy.delete()

    def capability(self, req):
        cap=json.loads(self.path('capabilities/'+req['capability']+'.json').read_text(encoding='utf8'))
        if cap.get('token')!=self.token or cap.get('document')!=req['document'] or cap.get('request')!=req['request']:
            raise ValueError('保存目标授权不匹配')
        if cap.get('operation')!='xcf-target' or Path(cap['target']).suffix.lower()!='.xcf':
            raise ValueError('无效的 XCF 目标')
        return cap

    def ensure_ids(self, image):
        known=self.known_ids.setdefault(image.get_id(),{})
        seen = set()
        for l in layers(image):
            key = read_tag(l, PARASITE)
            previous=known.get(key)
            still_exists=previous and any(x.get_id()==previous for x in layers(image))
            if not key or key in seen or (still_exists and previous!=l.get_id()):
                key = uuid.uuid4().hex; tag(l, PARASITE, key)
            seen.add(key);known[key]=l.get_id()

    def font(self, face):
        # These are localized names of the SAME bundled OpenType face, verified
        # against the runtime font list; this is not a visual substitution.
        candidates=[face]
        if face=='SourceHanSansSC-Heavy':candidates+=['Source Han Sans SC Heavy','思源黑体 Heavy']
        if face=='Source Han Sans SC Heavy':candidates.append('思源黑体 Heavy')
        if face=='思源黑体 Heavy':candidates.append('Source Han Sans SC Heavy')
        for name in candidates:
            font=Gimp.Font.get_by_name(name)
            if font:return font
        fallback=Gimp.Font.get_by_name('思源黑体 Heavy') or Gimp.Font.get_by_name('Source Han Sans SC Heavy')
        if not fallback:raise RuntimeError('应用本地字体尚不可用，请检查专用 fonts 目录后重新启动编辑器')
        self.emit('font-substitution',requested=face,actual=fallback.get_name())
        return fallback

    def rebuild_psd_text(self,image,plan):
        for row in plan.get('text_layers',[]):
            original=next((l for l in layers(image) if int(read_tag(l,'2byte-source-psd-id') or l.get_tattoo())==row['source_id'] and not l.is_group()),None)
            if original is None or original.is_text_layer():continue
            style=row['style'];font=self.font((style['family']+' '+style.get('font_style','')).strip())
            layer=Gimp.TextLayer.new(image,row['text'],font,style['size'],Gimp.Unit.pixel())
            image.insert_layer(layer,original.get_parent(),image.get_item_position(original))
            layer.set_name(row['name']);layer.set_offsets(round(row['x']),round(row['y']))
            layer.set_opacity(row['opacity']*100);layer.set_visible(row['visible']);layer.set_color(Gegl.Color.new(style['color']))
            layer.set_justification({'center':Gimp.TextJustification.CENTER,'right':Gimp.TextJustification.RIGHT}.get(style.get('alignment'),Gimp.TextJustification.LEFT))
            if style.get('stroke'):
                layer.set_outline(Gimp.TextOutline.STROKE_FILL);layer.set_outline_width(style['stroke'],Gimp.Unit.pixel());layer.set_outline_color(Gegl.Color.new(style['stroke_color']))
            if style.get('shadow'):
                effect=Gimp.DrawableFilter.new(layer,'gegl:dropshadow','PSD 阴影重建');config=effect.get_config()
                for source,target in [('shadow_x','x'),('shadow_y','y'),('shadow_blur','radius')]:config.set_property(target,float(style[source]))
                color=style['shadow_color'];config.set_property('color',Gegl.Color.new('#'+color[3:]+color[1:3]))
                effect.update();layer.append_filter(effect)
            tag(layer,'2byte-source-psd-id',str(row['source_id']));tag(layer,'2byte-cover-original-text-v1',json.dumps(row,ensure_ascii=False))
            tag(original,'2byte-cover-reference-v1','PSD 原外观，未删除');original.set_name(row['name']+' · PSD原外观参考');original.set_visible(False)
        tag(image,'2byte-psd-import-notes',json.dumps(plan.get('warnings',[]),ensure_ascii=False))

    def build_model(self, model):
        image = Gimp.Image.new(int(model['width']), int(model['height']), Gimp.ImageBaseType.RGB)
        image.undo_disable()
        try:
            for row in model['layers']:
                if row['kind'] == 'text':
                    style = row.get('style', {})
                    family = style.get('family', 'Source Han Sans SC')
                    face = (family+' '+style.get('font_style', 'Heavy')).strip()
                    font = self.font(face)
                    layer = Gimp.TextLayer.new(image, row['text'], font, float(style.get('size', 96)), Gimp.Unit.pixel())
                    image.insert_layer(layer, None, 0)
                    layer.set_color(Gegl.Color.new(style.get('color', '#ffffff')))
                    layer.set_justification({'left':Gimp.TextJustification.LEFT,'center':Gimp.TextJustification.CENTER,'right':Gimp.TextJustification.RIGHT}.get(style.get('alignment'),Gimp.TextJustification.LEFT))
                    if style.get('stroke', 0):
                        layer.set_outline(Gimp.TextOutline.STROKE_FILL)
                        layer.set_outline_width(float(style['stroke']), Gimp.Unit.pixel())
                        layer.set_outline_color(Gegl.Color.new(style.get('stroke_color', '#152c28')))
                    if style.get('shadow'):
                        shadow = Gimp.DrawableFilter.new(layer, 'gegl:dropshadow', '标题阴影')
                        c = shadow.get_config()
                        for source, dest, default in [('shadow_x','x',4),('shadow_y','y',6),('shadow_blur','radius',8)]:
                            c.set_property(dest, float(style.get(source, default)))
                        color = style.get('shadow_color', '#b0000000')
                        if len(color) == 9: color = '#'+color[3:]+color[1:3]  # Qt ARGB -> CSS RGBA
                        c.set_property('color', Gegl.Color.new(color))
                        shadow.update(); layer.append_filter(shadow)
                    tag(layer, '2byte-cover-original-text-v1', json.dumps(row,ensure_ascii=False))
                else:
                    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(str(self.path(row['file']))))
                    image.insert_layer(layer, None, 0)
                    layer.scale(max(1,round(row['width'])), max(1,round(row['height'])), False)
                tag(layer, PARASITE, row['id'])
                layer.set_name(row['name']); layer.set_offsets(round(row['x']), round(row['y']))
                layer.set_visible(row.get('visible', True)); layer.set_opacity(float(row.get('opacity', 1))*100)
                layer.set_lock_content(row.get('locked', False)); layer.set_lock_position(row.get('locked', False))
        except Exception:
            image.delete(); raise
        finally:
            if image.is_valid(): image.undo_enable()
        return image

    def run(self, req):
        op, key = req['op'], req['document']
        if op=='offline-evidence' and os.environ.get('TWOBYTEASR_COVER_OFFLINE_AUDIT')=='1':
            from ctypes import wintypes
            import _socket
            kernel=ctypes.windll.kernel32;adv=ctypes.windll.advapi32
            kernel.GetCurrentProcess.restype=wintypes.HANDLE
            adv.OpenProcessToken.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.POINTER(wintypes.HANDLE)]
            adv.GetTokenInformation.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
            handle=wintypes.HANDLE();adv.OpenProcessToken(kernel.GetCurrentProcess(),8,ctypes.byref(handle))
            value=wintypes.DWORD();size=wintypes.DWORD();ok=adv.GetTokenInformation(handle,29,ctypes.byref(value),4,ctypes.byref(size))
            kernel.CloseHandle(handle)
            result=dict(pid=os.getpid(),appcontainer=value.value if ok else None,network={})
            for host in ('1.1.1.1','140.82.114.4'):
                sock=_socket.socket();sock.settimeout(2)
                try:sock.connect((host,443));result['network'][host]='connected'
                except OSError as exc:result['network'][host]=getattr(exc,'winerror',None)
                finally:sock.close()
            return result
        if op=='fonts-refresh':return dict(refreshed=Gimp.fonts_refresh())
        if op in ('open-model', 'open-file'):
            if key in self.docs: raise ValueError('文档 ID 已打开')
            if op == 'open-model':
                image = self.build_model(json.loads(self.path(req['file']).read_text(encoding='utf8')))
            else:
                imported = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(str(self.path(req['file']))))
                if not imported: raise ValueError('GIMP 未能读取文件')
                if req.get('psd_rebuild'):
                    # GIMP's duplicate renumbers tattoos. Persist actual PSD IDs
                    # before duplicating; names and list positions are ambiguous.
                    for layer in layers(imported):tag(layer,'2byte-source-psd-id',str(layer.get_tattoo()))
                image=imported.duplicate();imported.delete()  # Never bind a template master or staging file.
                if req.get('psd_rebuild'):self.rebuild_psd_text(image,req['psd_rebuild'])
            self.ensure_ids(image); tag(image, DOC_TAG, key)
            if req.get('metadata'):tag(image,ROLES_TAG,json.dumps(req['metadata'],ensure_ascii=False))
            self.docs[key] = image
            self.displays[key]=Gimp.Display.new(image)
            selectable=[l for l in image.get_layers() if not l.get_lock_position()]
            if selectable:image.set_selected_layers([selectable[-1]])
            Gimp.displays_flush()
            return self.describe(key)
        image = self.document(key)
        self.ensure_ids(image)
        if op == 'describe':
            self.ensure_ids(image);return self.describe(key)
        if op == 'metadata':
            tag(image,ROLES_TAG,json.dumps(req['metadata'],ensure_ascii=False));return self.describe(key)
        if op == 'present':
            self.displays[key].present();return self.describe(key)
        if op == 'close':
            if image.is_dirty() and not req.get('discard'):raise ValueError('文档有未保存修改，请先保存或明确放弃')
            self.displays[key].delete();return dict(closed=True)
        if op == 'set-target':
            cap=self.capability(req)
            image.set_file(Gio.File.new_for_path(cap['target']))
            return self.describe(key)  # This does not claim a save or clean the document.
        if op == 'commit-save':
            cap=self.capability(req)
            current=self.describe(key)
            if current['file']!=req['file_before']:
                return dict(clean=False,reason='文件已在 GIMP 中另存为；保留新的原生保存目标',state=current)
            check=self.path('outputs/verify-'+req['request']+'.xcf')
            try: same=self.snapshot(image,check,verify=False)==req['sha256']
            finally:
                if check.exists():check.unlink()
            if not same:return dict(clean=False,reason='已保存快照；文档在保存期间有更新，仍需保存',state=self.describe(key))
            target=Path(cap['target'])
            if hashlib.sha256(target.read_bytes()).hexdigest()!=req['sha256']:
                raise ValueError('目标文件与本次快照不一致，未更新已保存状态')
            image.set_file(Gio.File.new_for_path(str(target)));image.clean_all()
            atomic_json(self.root/('saved-'+key+'.json'),dict(time=time.time(),file=str(target),sha256=req['sha256']))
            return dict(clean=True,state=self.describe(key))
        if op == 'replace-background':
            old=next((l for l in layers(image) if read_tag(l,PARASITE)==req['slot']),None)
            if old is None or old.is_group() or old.is_text_layer():raise ValueError('未找到底图槽位，请重新指定图片层')
            image.undo_group_start()
            try:
                new=Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE,image,Gio.File.new_for_path(str(self.path(req['file']))))
                parent=old.get_parent();position=image.get_item_position(old)
                image.insert_layer(new,parent,position)
                w,h=new.get_width(),new.get_height();cw,ch=image.get_width(),image.get_height()
                factor=(min if req.get('strategy')=='fit' else max)(cw/w,ch/h)
                w,h=max(1,round(w*factor)),max(1,round(h*factor));new.scale(w,h,False)
                fx,fy=req.get('focus',[.5,.5]);fx=max(0,min(1,float(fx)));fy=max(0,min(1,float(fy)))
                new.set_offsets(round((cw-w)*fx),round((ch-h)*fy))
                new.set_name(old.get_name());new.set_opacity(old.get_opacity());new.set_visible(old.get_visible())
                tag(new,PARASITE,req['slot']);image.remove_layer(old);image.set_selected_layers([new])
            finally:image.undo_group_end()
            Gimp.displays_flush();return self.describe(key)
        if op == 'add-image':
            image.undo_group_start()
            try:
                layer=Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE,image,Gio.File.new_for_path(str(self.path(req['file']))))
                image.insert_layer(layer,None,0);tag(layer,PARASITE,uuid.uuid4().hex)
                layer.set_name(req.get('name','贴图'))
                f=min(1,image.get_width()*.6/layer.get_width(),image.get_height()*.85/layer.get_height())
                layer.scale(max(1,round(layer.get_width()*f)),max(1,round(layer.get_height()*f)),False)
                layer.set_offsets((image.get_width()-layer.get_width())//2,(image.get_height()-layer.get_height())//2)
                image.set_selected_layers([layer])
            finally:image.undo_group_end()
            Gimp.displays_flush();return self.describe(key)
        if op == 'add-text':
            image.undo_group_start()
            try:
                font=self.font('Source Han Sans SC Heavy')
                layer=Gimp.TextLayer.new(image,req.get('text','中文标题'),font,max(24,image.get_width()/15),Gimp.Unit.pixel())
                image.insert_layer(layer,None,0);tag(layer,PARASITE,uuid.uuid4().hex)
                layer.set_offsets(round(image.get_width()*.07),round(image.get_height()*.32))
                layer.set_color(Gegl.Color.new('#ffffff'));layer.set_outline(Gimp.TextOutline.STROKE_FILL)
                layer.set_outline_width(4,Gimp.Unit.pixel());layer.set_outline_color(Gegl.Color.new('#152c28'))
                image.set_selected_layers([layer])
            finally:image.undo_group_end()
            Gimp.displays_flush();return self.describe(key)
        if op == 'title':
            layer = next((l for l in layers(image) if read_tag(l,PARASITE)==req['slot']),None)
            if layer is None or not layer.is_text_layer(): raise ValueError('主标题槽位不是可编辑文字，请在槽位设置中选择文字层')
            image.undo_group_start()
            try: layer.set_text(req['text'])
            finally: image.undo_group_end()
            Gimp.displays_flush(); return self.describe(key)
        if op == 'snapshot':
            self.ensure_ids(image)
            before=self.describe(key)
            out = self.path(req['output'])
            if not out.is_relative_to(self.root/'outputs'):raise ValueError('仅允许会话输出路径')
            if out.suffix.lower() != '.xcf': raise ValueError('快照只允许 XCF')
            result=dict(file=req['output'],sha256=self.snapshot(image,out),state=before)
            if req.get('preview'):
                source=Gimp.file_load(Gimp.RunMode.NONINTERACTIVE,Gio.File.new_for_path(str(out)))
                try:result['preview']=self.export_image(source,'png',req['preview'])
                finally:source.delete()
            return result
        if op == 'export':
            copy=image.duplicate()
            try:
                return self.export_image(copy,req['format'],req['output'])
            finally: copy.delete()
        raise ValueError('未知操作')

    def export_image(self,image,fmt,name):
        procedure={'png':'file-png-export','jpg':'file-jpeg-export','psd':'file-psd-export'}[fmt]
        out=self.path(name)
        if not out.is_relative_to(self.root/'outputs'):raise ValueError('仅允许会话输出路径')
        proc=Gimp.get_pdb().lookup_procedure(procedure);cfg=proc.create_config()
        cfg.set_property('run-mode',Gimp.RunMode.NONINTERACTIVE);cfg.set_property('image',image)
        cfg.set_property('file',Gio.File.new_for_path(str(out)))
        result=proc.run(cfg)
        if result.index(0)!=Gimp.PDBStatusType.SUCCESS:raise RuntimeError(str(result.index(0)))
        return dict(file=name,sha256=hashlib.sha256(out.read_bytes()).hexdigest())

    @staticmethod
    def idle():
        # Reading native input state never sends keystrokes or commits a tool.
        if sys.platform!='win32':return False
        class InputInfo(ctypes.Structure):_fields_=[('cbSize',ctypes.c_uint),('dwTime',ctypes.c_uint)]
        info=InputInfo();info.cbSize=ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):return False
        if ((ctypes.windll.kernel32.GetTickCount()-info.dwTime)&0xffffffff)<8000:return False
        if any(ctypes.windll.user32.GetAsyncKeyState(key)&0x8000 for key in (1,2,4,16,17,18)):return False
        # During native composition, defer even if the user has paused.
        from ctypes import wintypes
        class GUIInfo(ctypes.Structure):
            _fields_=[('cbSize',wintypes.DWORD),('flags',wintypes.DWORD)]+[(n,wintypes.HWND) for n in ('active','focus','capture','menu','move','caret')]+[('rect',wintypes.RECT)]
        gui=GUIInfo();gui.cbSize=ctypes.sizeof(gui)
        if ctypes.windll.user32.GetGUIThreadInfo(0,ctypes.byref(gui)):
            imm=ctypes.windll.imm32;imm.ImmGetContext.restype=ctypes.c_void_p;imm.ImmGetContext.argtypes=[wintypes.HWND]
            context=imm.ImmGetContext(gui.focus)
            if context:
                imm.ImmGetCompositionStringW.argtypes=[ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
                composing=imm.ImmGetCompositionStringW(context,8,None,0)>0
                imm.ImmReleaseContext.argtypes=[wintypes.HWND,ctypes.c_void_p];imm.ImmReleaseContext(gui.focus,context)
                if composing:return False
        return True

    def monitor(self):
        now=time.time()
        if now-self.last_status<2:return
        self.last_status=now
        states=[]
        for key,image in list(self.docs.items()):
            if not image.is_valid():
                self.docs.pop(key);atomic_json(self.root/('closed-'+key+'.json'),dict(time=now))
                self.emit('closed',document=key);continue
            state=self.describe(key);old=self.last_states.get(key)
            if not state['dirty'] and state['file'] and (not old or old['dirty'] or old['file']!=state['file']):
                path=Path(state['file'])
                try:
                    data=path.read_bytes()
                    if data.startswith(b'gimp xcf '):
                        atomic_json(self.root/('saved-'+key+'.json'),dict(time=now,file=state['file'],sha256=hashlib.sha256(data).hexdigest()))
                        self.emit('native-saved',document=key,file=state['file'],sha256=hashlib.sha256(data).hexdigest(),state=state)
                except OSError:pass
            self.last_states[key]=state
            state['draft']=self.drafts.get(key);states.append(state)
        atomic_json(self.root/'live.json',dict(session=self.session,token=self.token,time=now,version=Gimp.version(),bridge_sha256=self.bridge_hash,documents=states))
        self.emit('documents',documents=states)
        if self.idle():
            for state in states:
                key=state['document']
                if state['dirty'] and now-self.last_draft.get(key,0)>30:
                    self.ensure_ids(self.docs[key])
                    name='outputs/draft-'+key+'-'+uuid.uuid4().hex+'.xcf'
                    digest=self.snapshot(self.docs[key],self.path(name))
                    draft=dict(document=key,file=name,sha256=digest,time=time.time(),state=self.describe(key))
                    # Publish the durable pointer only after save AND reopen succeeded.
                    atomic_json(self.root/('draft-'+key+'.json'),draft)
                    self.drafts[key]=draft;self.last_draft[key]=time.time();self.emit('draft',**draft)
                    old=sorted((self.root/'outputs').glob('draft-'+key+'-*.xcf'),key=lambda p:p.stat().st_mtime,reverse=True)
                    for path in old[2:]:
                        try:path.unlink()
                        except OSError:pass
                    break

    def tick(self):
        if self.active: return True
        self.active=True
        try:
            handled=False
            for path in sorted((self.root/'requests').glob('*.json')):
                req=json.loads(path.read_text(encoding='utf8'))
                request=req.get('request','')
                if request in self.completed: continue
                if req.get('token') != self.token or req.get('session') != self.session: continue
                self.completed.add(request)
                handled=True
                start=time.perf_counter()
                try:
                    result=self.run(req)
                    self.emit('result',request=request,document=req['document'],ok=True,result=result,seconds=time.perf_counter()-start)
                except Exception:
                    self.emit('result',request=request,document=req.get('document'),ok=False,error=traceback.format_exc())
                break  # One command per GLib turn; never interleave saves.
            if not handled:self.monitor()
        except Exception:
            self.emit('bridge-error', error=traceback.format_exc())
        finally: self.active=False
        return True

    def menu(self,procedure,run_mode,image,drawables,config,action):
        key=next((key for key,value in self.docs.items() if value==image),None)
        if key:self.emit('action',document=key,action=action)
        else:Gimp.message('此图像由 GIMP 自行打开。请先在 2ByteASR 导入封面工程，或使用 GIMP 原生保存。')
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS,None)

    def install_menus(self):
        for action,title in [('return','返回 2ByteASR'),('save','保存封面（XCF）'),('export','导出图片'),('templates','封面模板')]:
            p=Gimp.ImageProcedure.new(self.plugin,'plug-in-2byte-cover-'+action,Gimp.PDBProcType.TEMPORARY,self.menu,action)
            p.set_image_types('*');p.set_menu_label(title);p.add_menu_path('<Image>/2ByteASR')
            p.set_documentation(title,'由2ByteASR管理当前封面文档',p.get_name());p.set_attribution('2ByteASR','2ByteASR','2026')
            self.plugin.add_temp_procedure(p)


class CoverPlugin(Gimp.PlugIn):
    def do_set_i18n(self, name):
        return False, None, None

    def do_query_procedures(self):
        return ['extension-2byte-cover-session']

    def do_create_procedure(self, name):
        p=Gimp.Procedure.new(self,name,Gimp.PDBProcType.PERSISTENT,self.start,None)
        p.set_documentation('2ByteASR private local document bridge','No network. Only the current private session directory.',name)
        p.set_attribution('2ByteASR','2ByteASR','2026')
        return p

    def start(self, procedure, config, data):
        if not os.environ.get('TWOBYTE_COVER_SESSION'):
            procedure.persistent_ready()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS,None)
        try:
            bridge=Bridge(self)
            bridge.install_menus()
        except Exception:
            procedure.persistent_ready()
            Gimp.message('2ByteASR 本地桥接初始化失败：'+traceback.format_exc())
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR,None)
        procedure.persistent_ready(); self.persistent_enable()
        bridge.emit('ready',version=Gimp.version(),bridge_sha256=bridge.bridge_hash,pid=os.getpid())
        GLib.timeout_add(200,bridge.tick)
        GLib.MainLoop().run()
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS,None)


Gimp.main(CoverPlugin.__gtype__,sys.argv)
