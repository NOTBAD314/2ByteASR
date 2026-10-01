"""Official Photopea iframe, with a narrow client-only binary bridge.

Only the parent owns QWebChannel. The cross-origin editor cannot see host paths
or call filesystem functions. Saves are fulfilled by the cover window, never JS.
"""
from __future__ import annotations

import base64
from collections import deque
import json
import time
import uuid

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

ORIGIN = 'https://www.photopea.com'
MAX_BYTES = 512 * 1024 * 1024

HTML = r'''<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;width:100%;height:100%;overflow:clip;background:#202623;color:#d6e1d9}
iframe{display:block;width:100%;height:100%;border:0}#state{position:absolute;top:45%;width:100%;text-align:center}</style>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script></head><body>
<div id="state">正在连接 Photopea…需要联网，已有草稿保留在本机。</div><iframe id="editor" allow="clipboard-read; clipboard-write"></iframe>
<script>
const origin='https://www.photopea.com', frame=document.getElementById('editor');
let bridge, ready=false, active=null, parts=[];
const send = x=>bridge.receive(JSON.stringify(x));
addEventListener('message', e=>{
  if(!bridge || e.origin!==origin || e.source!==frame.contentWindow) return;
  if(e.data instanceof ArrayBuffer) {
    if(!active || !active.begin || !active.binary || active.receiving) return;
    active.receiving=true;
    const bytes=new Uint8Array(e.data), id=active.id;
    send({type:'binary-start',id,size:bytes.length});
    for(let p=0;p<bytes.length;p+=65536) {
      let text=''; for(const c of bytes.subarray(p,p+65536)) text+=String.fromCharCode(c);
      send({type:'binary-chunk',id,data:btoa(text)});
    }
    send({type:'binary-end',id}); return;
  }
  if(typeof e.data!=='string') return;
  if(e.data==='done') {
    if(!ready) {ready=true;document.getElementById('state').style.display='none';send({type:'ready'});}
    if(active && active.loading) {active.loading=false;send({type:'loaded',id:active.id});}
    return; // done is NEVER a save acknowledgement.
  }
  let message; try { message=JSON.parse(e.data); } catch(_) {return;}
  if(message.hostAction) {send({type:'action',action:message.hostAction});return;}
  if(!active || message.token!==active.token || message.id!==active.id) return;
  if(message.phase==='begin') active.begin=true;
  send({type:'marker',...message});
});
window.begin=(id,token,binary)=>{active={id,token,binary,begin:false};};
window.command=script=>frame.contentWindow.postMessage(script,origin);
window.inputBegin=()=>{parts=[];};
window.inputChunk=chunk=>{const s=atob(chunk), b=new Uint8Array(s.length);for(let i=0;i<s.length;i++)b[i]=s.charCodeAt(i);parts.push(b);};
window.inputEnd=()=>{let size=parts.reduce((n,p)=>n+p.length,0), b=new Uint8Array(size),at=0;
for(const p of parts){b.set(p,at);at+=p.length;}parts=[];active.loading=true;frame.contentWindow.postMessage(b.buffer,origin,[b.buffer]);};
new QWebChannel(qt.webChannelTransport, channel=>{bridge=channel.objects.bridge;
const config={environment:{theme:2,lang:'zh-CN',intro:false,customIO:{
open:'app.echoToOE(JSON.stringify({hostAction:"open"}));',
save:'app.echoToOE(JSON.stringify({hostAction:"save"}));',
saveAsPSD:'app.echoToOE(JSON.stringify({hostAction:"save-as"}));'}}};
frame.src=origin+'/#'+encodeURIComponent(JSON.stringify(config));});
</script></body></html>'''


class Bridge(QObject):
    message = Signal(object)

    @Slot(str)
    def receive(self, value):
        if len(value) > 100000:
            return
        try:
            payload = json.loads(value)
            if isinstance(payload, dict):
                self.message.emit(payload)
        except (ValueError, TypeError):
            pass


class SafePage(QWebEnginePage):
    console = Signal(str)

    def chooseFiles(self, *args):
        return []  # Local file input is mediated by the host picker/customIO.

    def createWindow(self, _type):
        return None

    def acceptNavigationRequest(self, url, kind, main):
        if main:
            return url.scheme() == 'data' or url.toString() == 'https://cover.2byteasr.invalid/'
        return url.scheme() in ('https', 'about', 'blob')

    def javaScriptConsoleMessage(self, level, message, line, source):
        self.console.emit(message[:1000])


class PhotopeaPane(QWidget):
    ready = Signal()
    state = Signal(str)
    failed = Signal(str)
    action = Signal(str)
    dirty_hint = Signal()
    viewport_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_ready = False
        self.faulted = False
        self.pending = None
        self.queue = deque()
        self.metrics = []
        self.events = []
        self.started = time.perf_counter()
        self.profile = QWebEngineProfile(self)  # Off-the-record: no user browser profile.
        self.profile.downloadRequested.connect(lambda request: request.cancel())
        self.web = QWebEngineView(self)
        self.web.setContextMenuPolicy(Qt.NoContextMenu)
        self.page = SafePage(self.profile, self.web)
        self.web.setPage(self.page)
        self.page.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, False)
        self.page.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        self.page.settings().setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, False)
        self.page.permissionRequested.connect(lambda permission: permission.deny())
        self.page.renderProcessTerminated.connect(lambda *_: self.fail('编辑页面进程已退出；未自动刷新。可恢复最近草稿或保留本地文档。'))
        self.page.console.connect(lambda message: self.events.append(dict(time=time.perf_counter()-self.started, console=message)))
        self.channel = QWebChannel(self.page)
        self.bridge = Bridge(self.channel)
        self.channel.registerObject('bridge', self.bridge)
        self.page.setWebChannel(self.channel)
        self.bridge.message.connect(self.receive)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.web)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(lambda: self.fail('Photopea 加载或操作超时；页面保持原状，请检查网络。重新加载前请先保留草稿。'))
        self.timeout.start(45000)
        self.page.setHtml(HTML, QUrl('https://cover.2byteasr.invalid/'))

    def run_js(self, code, callback=None):
        if callback:
            self.page.runJavaScript(code, callback)
        else:
            self.page.runJavaScript(code)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'web'):
            # Keep the official editor's menus, panels and advertising inside
            # a usable browser viewport at small host-window sizes. This is
            # ordinary browser zoom, without modifying the remote page DOM.
            factor=max(.5,min(1.,self.width()/1200.))
            if abs(self.web.zoomFactor()-factor)>.005:self.web.setZoomFactor(factor)
            self.viewport_changed.emit()

    def reset_viewport_scroll(self):
        from shiboken6 import isValid
        if not isValid(self) or not isValid(self.page):return
        # Chromium can scroll the entire iframe to an old text-input caret
        # after resize. Recenter the browser viewport; no remote DOM, branding
        # or advertising is changed. Canvas panning stays inside Photopea.
        for frame in self.page.mainFrame().children():
            if frame.url().toString().startswith(ORIGIN+'/'):
                frame.runJavaScript('window.scrollTo(0,0);',lambda _:None)

    def command(self, script, callback, *, document='', binary='', label='编辑操作'):
        operation = dict(id=uuid.uuid4().hex, token=uuid.uuid4().hex, script=script,
                         callback=callback, document=document, binary=binary, label=label)
        self.queue.append(operation)
        self.pump()

    def open_bytes(self, data, document, callback, *, font=False):
        if not data or len(data) > MAX_BYTES:
            raise ValueError('文件为空或超过 512 MB。')
        self.queue.append(dict(id=uuid.uuid4().hex, token=uuid.uuid4().hex, input=bytes(data),
                               document=document, font=font, callback=callback, binary='', label='加载字体' if font else '打开文档'))
        self.pump()

    def pump(self):
        if not self.is_ready or self.pending or self.faulted or not self.queue:
            return
        op = self.pending = self.queue.popleft()
        op.update(started=time.perf_counter(), received=bytearray(), ended=False, binary_done=False)
        focus=QApplication.focusWidget()
        op['restore_focus']=focus is self.web or (focus is not None and self.web.isAncestorOf(focus))
        self.state.emit(op['label']+'…')
        # Photopea defers scripts during a native text/transform operation.
        # Keep input available until its correlated begin marker, so users can
        # confirm/cancel that operation instead of being trapped by the host.
        if 'input' in op:self.web.setEnabled(False)
        self.timeout.start(60000)
        self.run_js('window.begin('+json.dumps(op['id'])+','+json.dumps(op['token'])+','+json.dumps(bool(op['binary']))+');')
        if 'input' in op:
            if not op.get('font'):
                op['target_document'],op['document']=op['document'],''
                op['stage']='preflight'
                self.send_script('var m=__HOST_DATA__;m.value={count:app.documents.length};app.echoToOE(JSON.stringify(m));')
            else:
                self.send_input(op)
        else:
            self.send_script(op['script'])

    def send_input(self,op):
        op['stage']='upload'
        self.run_js('window.inputBegin();')
        data=op.pop('input')
        chunks=deque(base64.b64encode(data[p:p+196608]).decode('ascii') for p in range(0,len(data),196608))
        def next_chunk(_=None):
            if self.pending is not op:return
            if chunks:self.run_js('window.inputChunk('+json.dumps(chunks.popleft())+');',next_chunk)
            else:self.run_js('window.inputEnd();')
        next_chunk()

    def check_loaded_document(self,op):
        if self.pending is not op:return
        op['stage']='check-load'
        script='var m=__HOST_DATA__;m.value={loaded:false};if(app.documents.length>'+str(op['before_count'])+'){' \
            'app.activeDocument.source='+json.dumps(op['target_document'])+';m.value={loaded:true,source:app.activeDocument.source};}app.echoToOE(JSON.stringify(m));'
        self.send_script(script)

    def send_script(self, script):
        op = self.pending
        marker = dict(token=op['token'], id=op['id'])
        begin = json.dumps(dict(marker, phase='begin'))
        end = json.dumps(dict(marker, phase='end'))
        error = json.dumps(dict(marker, phase='error'))
        script = script.replace('__HOST_DATA__', json.dumps(dict(marker, phase='data')))
        script = script.replace('__HOST_ERROR__', error)
        expected = op['document']
        mismatch = ('(!app.documents.length||app.activeDocument.source!=='+json.dumps(expected)+')') if expected else 'false'
        # Photopea's interpreter does not implement every JS exception path.
        # Refuse the whole operation via an explicit else branch, not throw.
        wrapped = ('if('+mismatch+'){var m='+error+';m.error="当前文档已切换，请重新选择原文档";app.echoToOE(JSON.stringify(m));}else{'
                   'try {var b='+begin+';b.document=app.documents.length?app.activeDocument.source:"";app.echoToOE(JSON.stringify(b));'+script+
                   ';var e='+end+';e.document=app.documents.length?app.activeDocument.source:"";app.echoToOE(JSON.stringify(e));}catch(e){var m='+error+';m.error=String(e);app.echoToOE(JSON.stringify(m));}}')
        self.run_js('window.command('+json.dumps(wrapped)+');')

    def receive(self, message):
        kind = message.get('type')
        if kind == 'ready' and not self.is_ready:
            self.timeout.stop()
            self.is_ready = True
            self.metrics.append(dict(action='Photopea 首次加载', seconds=time.perf_counter()-self.started))
            self.ready.emit()
            self.pump()
            return
        if kind == 'action':
            if message.get('action') in ('open', 'save', 'save-as'):
                self.action.emit(message['action'])
            return
        op = self.pending
        if not op or message.get('id') != op['id']:
            return
        if kind == 'loaded':
            if op.get('stage')!='upload':return
            if op.get('font'):
                op['document'] = ''
                self.send_script('')
            else:
                self.check_loaded_document(op)
        elif kind == 'marker' and message.get('token') == op['token']:
            if message.get('phase') == 'error':
                self.fail(str(message.get('error', '编辑命令失败')), fatal=False)
                return
            if message.get('phase') == 'begin':
                if op['document'] and 'font' not in op and message.get('document') != op['document']:
                    self.fail('返回数据的文档标识不匹配，未写入目标。')
                    return
                op['begun'] = True
                self.web.setEnabled(False)
            if message.get('phase') == 'end' and op.get('begun'):
                if op['document'] and message.get('document') != op['document']:
                    self.fail('操作完成时文档标识不匹配，未写入目标。')
                    return
                op['ended'] = True
            if message.get('phase') == 'data' and op.get('begun'):
                op['result'] = message.get('value')
        elif kind == 'binary-start' and op.get('begun') and op['binary']:
            size = message.get('size', 0)
            if not isinstance(size, int) or not 0 < size <= MAX_BYTES:
                self.fail('返回文件超出允许大小。')
                return
            op['expected_bytes'] = size
        elif kind == 'binary-chunk' and 'expected_bytes' in op:
            try:
                op['received'].extend(base64.b64decode(message['data'], validate=True))
            except (ValueError, KeyError):
                self.fail('返回文件数据无效。')
                return
            if len(op['received']) > op['expected_bytes']:
                self.fail('返回文件长度不匹配。')
                return
        elif kind == 'binary-end' and len(op['received']) == op.get('expected_bytes', -1):
            data = bytes(op['received'])
            magic = {'psd': b'8BPS', 'png': b'\x89PNG', 'jpg': b'\xff\xd8'}
            if not data.startswith(magic.get(op['binary'], b'invalid')):
                self.fail('返回文件格式不匹配，未写入目标。')
                return
            op['binary_done'] = True
        if op['ended'] and (not op['binary'] or op['binary_done']):
            if op.get('stage')=='preflight':
                op['before_count']=op['result']['count']
                op.update(ended=False,begun=False)
                op.pop('result',None)
                self.send_input(op)
                return
            if op.get('stage')=='check-load':
                result=op.get('result') or {}
                if not result.get('loaded'):
                    op.update(ended=False,begun=False)
                    op.pop('result',None)
                    QTimer.singleShot(150,lambda:self.check_loaded_document(op))
                    return
                if result.get('source')!=op['target_document']:
                    self.fail('新文档标识未确认，原文档未标记保存。')
                    return
            self.timeout.stop()
            self.pending = None
            self.web.setEnabled(True)
            if op.get('restore_focus'):self.web.setFocus(Qt.OtherFocusReason)
            self.state.emit('Photopea 已就绪')
            self.metrics.append(dict(action=op['label'], seconds=time.perf_counter()-op['started'], bytes=len(op['received'])))
            try:
                op['callback'](bytes(op['received']) if op['binary'] else op.get('result'))
            except Exception as exc:
                self.fail(str(exc),fatal=False)
            QTimer.singleShot(20, self.pump)

    def export(self, document, format, callback):
        if format not in ('psd', 'png', 'jpg'):
            raise ValueError('不支持的导出格式')
        self.command('app.activeDocument.saveToOE('+json.dumps(format)+');', callback,
                     document=document, binary=format, label='返回 '+format.upper())

    def query(self, expression, callback, *, document=''):
        self.command('var m=__HOST_DATA__;m.value=('+expression+');app.echoToOE(JSON.stringify(m));', callback, document=document, label='读取文档状态')

    def fail(self, message, *, fatal=True):
        self.timeout.stop()
        self.faulted = fatal
        self.queue.clear()
        self.pending = None
        self.web.setEnabled(True)
        self.failed.emit(message)
        self.state.emit(message)
