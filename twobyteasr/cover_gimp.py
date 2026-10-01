"""Private local GIMP process and correlated file-queue transport.

The editor has no remote page, socket or arbitrary-code RPC. Assets are staged;
only the host publishes operation results to a user-selected destination.
"""
from __future__ import annotations
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from PySide6.QtCore import QObject, QTimer, Signal
from .cover_psd import atomic_bytes
from .cover_gimp_runtime import inspect_runtime, profile_path, seed_profile

class GimpSession(QObject):
    ready=Signal()
    state=Signal(dict)
    event=Signal(dict)
    failed=Signal(str)
    _shared={}

    @classmethod
    def acquire(cls,workspace,runtime,*,mode='cover',dark=True):
        from PySide6.QtCore import QCoreApplication
        key=str(profile_path(workspace,runtime).resolve())
        if key in cls._shared and cls._shared[key].process and cls._shared[key].process.poll() is not None:
            cls._shared[key].dead=True
        if key not in cls._shared or cls._shared[key].dead:
            cls._shared[key]=cls(workspace,runtime,QCoreApplication.instance(),mode=mode,dark=dark)
        return cls._shared[key]

    def __init__(self, workspace, runtime, parent=None, *, mode='cover', dark=True):
        super().__init__(parent)
        self.workspace=Path(workspace);self.id=uuid.uuid4().hex;self.token=uuid.uuid4().hex+uuid.uuid4().hex
        self.runtime=runtime;self.mode=mode;self.dark=dark
        self.profile=profile_path(workspace,runtime).resolve()
        self.root=self.workspace/'gimp-sessions'/self.id
        for folder in ('requests','events','inputs','outputs','capabilities'):
            (self.root/folder).mkdir(parents=True,exist_ok=True)
        self.queue=deque();self.pending=None;self.seen=set();self.sequence=0
        self.is_ready=False;self.process=None;self.log=None;self.started=time.monotonic();self.metrics=[]
        self.timer=QTimer(self);self.timer.setInterval(150);self.timer.timeout.connect(self.poll)
        self.dead=False
        self.meta={};self.documents=[];self._started=False;self.attached=False
        self.bridge_hash=hashlib.sha256((Path(__file__).resolve().parents[1]/'assets/gimp/2byte-cover-bridge.py').read_bytes()).hexdigest()

    def metadata(self,document,**values):
        current=self.meta.setdefault(document,{})
        current.update(values)
        folder=self.root/'documents';folder.mkdir(exist_ok=True)
        atomic_bytes(folder/(document+'.json'),json.dumps(current,ensure_ascii=False).encode('utf8'))
        return current

    def start(self):
        if self._started:return
        self._started=True
        for live in sorted((self.workspace/'gimp-sessions').glob('*/live.json'),key=lambda p:p.stat().st_mtime,reverse=True):
            try:
                value=json.loads(live.read_text(encoding='utf8'))
                cfg=json.loads((live.parent/'session.json').read_text(encoding='utf8'))
                if time.time()-value['time']>10 or value['version']!=self.runtime.version or value['token']!=cfg['token']:continue
                if cfg.get('profile')!=str(self.profile) or cfg.get('runtime')!=str(self.runtime.root):continue
                if cfg.get('root')!=str(live.parent.resolve()):continue
                if value.get('bridge_sha256')!=self.bridge_hash:
                    self.dead=True
                    raise RuntimeError('旧版 GIMP 封面会话仍在运行。请在该 GIMP 窗口保存并关闭后重新打开工作台；当前文档没有被强制关闭。')
                self.root=live.parent;self.id=cfg['session'];self.token=cfg['token']
                self.sequence=max([int(p.stem) for p in (self.root/'requests').glob('*.json')]+[0])
                self.seen={p.name for p in (self.root/'events').glob('*.json')}
                self.meta={p.stem:json.loads(p.read_text(encoding='utf8')) for p in (self.root/'documents').glob('*.json')}
                self.documents=value['documents'];self.is_ready=True;self.attached=True
                self.mode=cfg.get('workspace_mode','cover')
                self.timer.start();QTimer.singleShot(0,self.ready.emit)
                return
            except (OSError,KeyError,ValueError):continue
        # Revalidate at the launch boundary in case the selected install moved.
        self.runtime=inspect_runtime(self.runtime.executable)
        runtime=self.runtime.root
        profile=seed_profile(self.workspace,self.runtime,mode=self.mode,dark=self.dark)
        atomic_bytes(self.root/'session.json',json.dumps(dict(session=self.id,token=self.token,root=str(self.root.resolve()),
            profile=str(profile),runtime=str(runtime),workspace_mode=self.mode)).encode())
        env=os.environ.copy()
        env.update(GIMP3_DIRECTORY=str(profile.resolve()),GIMP3_CACHEDIR=str((self.workspace/'gimp-cache').resolve()),
                   GIMP3_TEMPDIR=str((self.root/'outputs').resolve()),GIMP3_LOCALEDIR=str(runtime/'share/locale'),
                   TWOBYTE_COVER_SESSION=str(self.root.resolve()),LANG='zh_CN.UTF-8',LANGUAGE='zh_CN',
                   XDG_DATA_HOME=str(self.workspace/'gimp-private-data'),XDG_CONFIG_HOME=str(self.workspace/'gimp-private-config'),
                   XDG_CACHE_HOME=str(self.workspace/'gimp-cache'))
        # Remove application/dev overrides; GIMP must discover its bundled Python/GI.
        for key in ('PYTHONHOME','PYTHONPATH','QT_PLUGIN_PATH','QT_QPA_PLATFORM','QT_SCALE_FACTOR','MSYSTEM','SHELL',
                    'LC_ALL','LC_CTYPE','LC_MESSAGES','TERM'):
            env.pop(key,None)
        self.log=(self.root/'runtime.log').open('ab')
        self.process=subprocess.Popen([str(runtime/'bin/gimp-3.exe'),'--new-instance','--no-splash'],
                                      env=env,cwd=str(runtime),stdout=self.log,stderr=subprocess.STDOUT,
                                      creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.timer.start()

    def stage(self, data, suffix):
        suffix=suffix if suffix in ('.png','.jpg','.webp','.psd','.xcf','.json','.otf','.ttf') else '.bin'
        name='inputs/'+uuid.uuid4().hex+suffix
        atomic_bytes(self.root/name,data)
        return name

    def stage_model(self, document):
        model=document.manifest()
        for layer in model['layers']:
            if layer['kind']=='image':
                layer['file']=self.stage(document.assets[layer['asset']],'.png')
        return self.stage(json.dumps(model,ensure_ascii=False).encode('utf8'),'.json')

    def request(self, op, document, callback=None, error=None, *, target=None, **payload):
        request=uuid.uuid4().hex
        if target is not None:
            capability=uuid.uuid4().hex
            atomic_bytes(self.root/'capabilities'/(capability+'.json'),json.dumps(dict(
                token=self.token,document=document,request=request,operation='xcf-target',target=str(Path(target).resolve()))).encode('utf8'))
            payload['capability']=capability
        message=dict(op=op,document=document,request=request,session=self.id,token=self.token,**payload)
        self.queue.append((message,callback,error));self.dispatch()
        return request

    def save(self, document, target, callback, error=None, *, expected_file=None):
        target=Path(target).resolve()
        if target.suffix.lower()!='.xcf':raise ValueError('封面工程保存为 .xcf')
        output='outputs/save-'+uuid.uuid4().hex+'.xcf'
        def snapshot(result):
            try:
                if expected_file is not None and result['state']['file']!=expected_file:
                    raise ValueError('文件已在 GIMP 中另存为；本次未覆盖旧目标，请重新保存')
                data=self.output_bytes(result)
                if not data.startswith(b'gimp xcf '):raise ValueError('GIMP 未返回有效 XCF')
                atomic_bytes(target,data)
                def committed(receipt):
                    receipt.update(file=str(target),sha256=result['sha256'],time=time.time())
                    callback(receipt)
                self.request('commit-save',document,committed,error,target=target,sha256=result['sha256'],
                             file_before=result['state']['file'])
            except (ValueError,OSError) as exc:
                if error:error(str(exc))
                else:self.failed.emit(str(exc))
        return self.request('snapshot',document,snapshot,error,output=output)

    def dispatch(self):
        if not self.is_ready or self.pending or not self.queue or self.dead:return
        self.pending=(*self.queue.popleft(),time.monotonic())
        self.sequence+=1
        atomic_bytes(self.root/'requests'/f'{self.sequence:010d}.json',json.dumps(self.pending[0],ensure_ascii=False).encode('utf8'))

    def poll(self):
        try:
            for path in sorted((self.root/'events').glob('*.json')):
                if path.name in self.seen:continue
                event=json.loads(path.read_text(encoding='utf8'))
                self.seen.add(path.name)
                if event.get('session')!=self.id or event.get('token')!=self.token:continue
                if event['event']=='ready':
                    if event['version'] != self.runtime.version:raise RuntimeError('GIMP 版本不符：'+event['version'])
                    if event.get('bridge_sha256')!=self.bridge_hash:raise RuntimeError('GIMP 桥接插件版本不符，未发送编辑操作')
                    self.is_ready=True
                    self.metrics.append(dict(action='gimp-ready',seconds=time.monotonic()-self.started))
                    self.ready.emit();self.dispatch()
                elif event['event']=='result':
                    if not self.pending:continue
                    req,callback,error,started=self.pending
                    if event.get('request')!=req['request'] or event.get('document')!=req['document']:continue
                    self.pending=None
                    self.metrics.append(dict(action=req['op'],document=req['document'],seconds=time.monotonic()-started))
                    if event.get('ok'):
                        if callback:callback(event['result'])
                    elif error:error(event.get('error','GIMP 操作失败'))
                    else:self.failed.emit(event.get('error','GIMP 操作失败'))
                    self.dispatch()
                else:
                    if event['event']=='documents':self.documents=event['documents']
                    self.event.emit(event)
            if self.process and self.process.poll() is not None and not self.dead:
                self.dead=True;self.is_ready=False;self.timer.stop()
                self.failed.emit('GIMP 已退出。已落盘的工程和各文档草稿仍保留，可重新打开。')
            elif not self.is_ready and time.monotonic()-self.started>120 and not self.dead:
                self.dead=True;self.failed.emit('GIMP 启动超过 120 秒；未自动重启或关闭文档。可检查运行日志后重试。')
            elif self.attached and not self.pending and time.time()-(self.root/'live.json').stat().st_mtime>20 and not self.dead:
                self.dead=True;self.is_ready=False;self.failed.emit('GIMP 会话没有回应；草稿仍保留，当前操作未报告成功。')
            elif self.pending and time.monotonic()-self.pending[3]>120:
                # Keep association and pending operation. A late result remains valid;
                # no next save is sent into an unknown state.
                if not getattr(self,'_warned_timeout',False):
                    self._warned_timeout=True;self.failed.emit('GIMP 操作仍在等待，尚未报告保存成功；未重试或关闭当前文档。')
        except (OSError,ValueError,RuntimeError) as exc:self.failed.emit(str(exc))

    def output_bytes(self, result):
        path=(self.root/result['file']).resolve()
        if not path.is_relative_to((self.root/'outputs').resolve()):raise ValueError('返回路径不在会话输出目录')
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=result['sha256']:raise ValueError('GIMP 返回文件校验不匹配')
        return data
