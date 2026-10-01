"""Compact local cover desk around a managed, native GIMP single window."""
from __future__ import annotations
import json
from pathlib import Path
import time
import uuid

from PySide6.QtCore import Qt,QSettings,QTimer,QUrl
from PySide6.QtGui import QAction,QDesktopServices,QPixmap
from PySide6.QtWidgets import (QApplication,QComboBox,QDialog,QDialogButtonBox,QFileDialog,QFormLayout,
    QHBoxLayout,QInputDialog,QLabel,QListWidget,QListWidgetItem,QMenu,QMessageBox,QPushButton,
    QSplitter,QTextEdit,QToolBar,QToolButton,QVBoxLayout,QWidget)

from .cover_document import CoverDocument
from .cover_editor import CoverEditor,CoverJob
from .cover_gimp import GimpSession
from .cover_gimp_library import GimpCoverLibrary
from .cover_gimp_psd import rebuild_plan
from .cover_psd import atomic_bytes,load_local_psd,psd_id,psd_metadata
from .cover_templates_ui import TemplatePicker

from .i18n import bind_text

from .i18n import tr


class CoverWorkbench(QDialog):
    def __init__(self,document=None,parent=None,*,runtime,initial_path=None):
        super().__init__(parent,Qt.Window)
        bind_text(self, '封面工作台 · 本地 GIMP', property='windowTitle');self.resize(1060,720);self.setMinimumSize(760,510)
        self.settings=QSettings('2ByteASR','2ByteASR');self.library=GimpCoverLibrary()
        self.library.collect_session_drafts()
        from .theme_manager import theme_key
        from .ui_theme import theme_definition
        from PySide6.QtGui import QColor
        theme=theme_definition(theme_key())
        self.session=GimpSession.acquire(self.library.root,runtime,
            mode=str(self.settings.value('cover/gimp_workspace','cover')),
            dark=QColor(theme.app_background).lightness()<128)
        self._has_initial_document=document is not None;self._initial_path=initial_path
        self.original=(document or CoverDocument()).snapshot()
        base=self.original.layer(self.original.background_id)
        self.frame=self.original.assets.get(base.asset) if base else None
        self.current='';self.documents={};self.jobs=set();self.busy=False;self._initialized=False
        self._preview=None;self._preview_requested=set();self._seen_draft={};self._local=[]
        self._quick_pending={};self._quick_syncing=False
        self._build()
        self.session.ready.connect(self.initialize);self.session.event.connect(self.on_event);self.session.failed.connect(self.failed)
        if self.session.is_ready:QTimer.singleShot(0,self.initialize)
        else:
            try:self.session.start()
            except Exception as exc:self.session.dead=True;self.failed(str(exc))

    def _build(self):
        layout=QVBoxLayout(self);layout.setContentsMargins(10,8,10,8);layout.setSpacing(8)
        bar=QToolBar();layout.addWidget(bar);self.cover_actions={}
        def action(key,label,slot):
            value=QAction(label,self);value.triggered.connect(slot);bar.addAction(value);self.cover_actions[key]=value
        action('templates','模板',self.templates)
        action('edit','进入 GIMP 编辑',self.present)
        action('open','打开封面',self.open_dialog)
        action('save','保存封面（XCF）',self.save_dialog)
        action('export','导出图片',self.export_dialog)
        menu=QMenu(self)
        for label,slot in [('打开 XCF / PSD / 旧封面…',self.open_dialog),('另存为 XCF…',lambda:self.save_dialog(save_as=True)),
                           ('导出 PSD…',self.export_psd_dialog),('当前封面保存为模板…',self.save_template_dialog),
                           ('更新此模板…',lambda:self.save_template_dialog(update=True)),('导入 XCF / PSD 模板…',self.import_template),
                           ('设置模板槽位…',self.slot_dialog),('添加透明贴图…',self.add_image),('添加中文文字',self.add_text),
                           ('换入当前冻结帧',self.replace_frame),('空白新建',self.new_document),('恢复草稿…',self.restore_dialog),
                           ('载入本地字体…',self.add_font),('旧 .2bytecover 轻量编辑',self.open_local)]:
            menu.addAction(label,slot)
        menu.addSeparator()
        menu.addAction('封面精简工作区（下次启动）',lambda:self.set_workspace('cover'))
        menu.addAction('完整工具 / 恢复默认工作区（下次启动）',lambda:self.set_workspace('full'))
        more=QToolButton();bind_text(more, '更多');more.setMenu(menu);more.setPopupMode(QToolButton.InstantPopup);bar.addWidget(more)
        self.notice=QLabel('独立 GIMP 编辑窗口 · 已安装后的日常编辑无需联网');self.notice.setWordWrap(True);layout.addWidget(self.notice)
        splitter=QSplitter();layout.addWidget(splitter,1)
        self.list=QListWidget();self.list.setMinimumWidth(155);self.list.setMaximumWidth(280)
        self.list.currentItemChanged.connect(self.select_document);splitter.addWidget(self.list)
        body=QWidget();center=QVBoxLayout(body);center.setContentsMargins(8,0,0,0)
        self.preview=QLabel('正在启动本地编辑器…');self.preview.setAlignment(Qt.AlignCenter);self.preview.setMinimumSize(320,200)
        self.preview.setBackgroundRole(self.palette().ColorRole.Base);self.preview.setAutoFillBackground(True);center.addWidget(self.preview,1)
        self.preview.mouseDoubleClickEvent=lambda e:self.present()
        self.quick=QTextEdit();bind_text(self.quick, '模板主标题：可在此快速修改，也可在 GIMP 中直接编辑', property='placeholderText');self.quick.setMaximumHeight(82)
        self.quick.textChanged.connect(self.quick_changed)
        quickrow=QHBoxLayout();quickrow.addWidget(self.quick,1)
        apply=QPushButton('应用标题');apply.clicked.connect(self.change_title);quickrow.addWidget(apply)
        center.addLayout(quickrow)
        controls=QHBoxLayout()
        for label,slot in [('换入当前帧',self.replace_frame),('刷新预览',self.refresh_preview),('打开导出结果',self.open_result),('返回 Studio',self.return_studio)]:
            button=QPushButton(label);button.clicked.connect(slot);controls.addWidget(button)
        center.addLayout(controls);splitter.addWidget(body);splitter.setSizes([185,840])
        self.status=QLabel('正在等待 GIMP 文档桥接…');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.help=QLabel('GIMP：M 移动 · Shift+S 缩放 · 链条控制比例 · Enter 确认 / Esc 取消 · Ctrl+Z 撤销。\n'
                         '在 GIMP 顶部“2ByteASR”菜单可返回、保存或导出；关闭此工作台会返回 Studio，GIMP 文档继续保留。')
        self.help.setWordWrap(True);layout.addWidget(self.help)
        from .studio_theme import apply_secondary_surface_theme
        apply_secondary_surface_theme(self)
        bar.setMovable(False)

    def set_workspace(self,mode):
        self.settings.setValue('cover/gimp_workspace',mode)
        bind_text(self.notice, '{value0}已记住。请自行保存并关闭专用 GIMP，下次“使用 GIMP 编辑”生效；当前窗口不重启。', value0='完整工具 / 默认工作区' if mode == 'full' else '封面精简工作区')

    def initialize(self):
        if self._initialized:return
        self._initialized=True
        if self.session.documents:
            for state in self.session.documents:self.accept_state(state)
            bind_text(self.status, '已重新连接仍在运行的本地 GIMP 文档。')
            if not self._has_initial_document and not self._initial_path:self.refresh_preview();return
        if self._initial_path:
            self.open_document(self._initial_path,confirmed=True);return
        key=str(self.settings.value('cover/last_template',''))
        if key and str(self.settings.value('cover/start_last_template','false')).lower()=='true':
            try:
                entry=self.library.get(key)
                if not entry.get('deleted'):self.apply_template(entry,True);return
            except (OSError,ValueError):pass
        self.open_model(self.original)
        if self.library.drafts() or self.library.draft():
            bind_text(self.notice, '发现未完成草稿。通过“更多 → 恢复草稿”选择文档；恢复不会覆盖手动保存或模板。')

    def accept_state(self,state):
        key=state['document'];self.documents[key]=state
        meta=self.session.meta.setdefault(key,{})
        if not meta.get('slots') and state.get('metadata',{}).get('slots'):
            meta.update(state['metadata'])
        if state.get('file'):meta['filename']=state['file']
        found=next((self.list.item(i) for i in range(self.list.count()) if self.list.item(i).data(Qt.UserRole)==key),None)
        name=Path(state.get('file','')).name or meta.get('name','未命名封面')
        text=('● ' if state.get('dirty') else '')+name
        if found:found.setText(text)
        else:
            found=QListWidgetItem(text);found.setData(Qt.UserRole,key);self.list.addItem(found)
        if not self.current:self.list.setCurrentItem(found)
        if key==self.current:self.sync_quick();self.update_status()

    def quick_changed(self):
        if self.current and not self._quick_syncing:self._quick_pending[self.current]=self.quick.toPlainText()

    def sync_quick(self):
        meta=self.session.meta.get(self.current,{})
        state=self.documents.get(self.current,{})
        slot=meta.get('slots',{}).get('title')
        layer=next((l for l in state.get('layers',[]) if l['id']==slot),None)
        value=self._quick_pending.get(self.current,(layer.get('text') or '') if layer else '')
        if value!=self.quick.toPlainText():
            self._quick_syncing=True
            try:self.quick.setPlainText(value)
            finally:self._quick_syncing=False

    def select_document(self,item,*_):
        if not item:return
        self.current=item.data(Qt.UserRole);self.sync_quick()
        self._preview=None;bind_text(self.preview, '双击此处进入 GIMP 原生编辑');self.update_status()
        self.refresh_preview()

    def update_status(self):
        state=self.documents.get(self.current,{});meta=self.session.meta.get(self.current,{})
        saved=meta.get('saved_time');draft=meta.get('draft_time')
        bind_text(self.status, ('未保存修改' if state.get('dirty', True) else '文档已保存') + (' · 手动保存 ' + time.strftime('%H:%M:%S', time.localtime(saved)) if saved else '') + (' · 草稿落盘 ' + time.strftime('%H:%M:%S', time.localtime(draft)) if draft else '') + (' · ' + state['file'] if state.get('file') else ''))

    def on_event(self,event):
        kind=event['event'];key=event.get('document','')
        if kind=='documents':
            for state in event['documents']:self.accept_state(state)
        elif kind=='native-saved':
            self.session.metadata(key,filename=event['file'],saved_time=event['time'])
            self.accept_state(event['state']);self.library.dismiss_xcf_draft(key)
        elif kind=='draft':
            if self._seen_draft.get(key,0)>=event['time']:return
            self._seen_draft[key]=event['time'];meta=self.session.meta.get(key,{})
            try:
                self.library.save_xcf_draft(key,self.session.output_bytes(event),filename=event['state'].get('file',''),
                                            template=meta.get('template',''),slots=meta.get('slots',{}),saved_time=event['time'])
                self.session.metadata(key,draft_time=event['time'])
                if key==self.current:self.update_status()
            except (OSError,ValueError) as exc:self.failed('草稿保存失败：'+str(exc))
        elif kind=='closed':
            self._quick_pending.pop(key,None)
            self.documents.pop(key,None);self.library.dismiss_xcf_draft(key)
            for i in range(self.list.count()-1,-1,-1):
                if self.list.item(i).data(Qt.UserRole)==key:self.list.takeItem(i)
            if key==self.current:self.current='';self.preview.clear()
        elif kind=='font-substitution':bind_text(self.notice, '缺少字体“{value0}”，当前替代为“{value1}”；原字体信息保留。', value0=event['requested'], value1=event['actual'])
        elif kind=='action':
            for i in range(self.list.count()):
                if self.list.item(i).data(Qt.UserRole)==key:self.list.setCurrentRow(i);break
            self.show();self.raise_();self.activateWindow()
            {'save':self.save_dialog,'export':self.export_dialog,'templates':self.templates,'return':lambda:None}[event['action']]()
        elif kind=='bridge-error':self.failed(event.get('error','GIMP 插件异常'))

    def failed(self,message):
        self.busy=False;bind_text(self.status, '{value0}；未报告保存成功，当前文档未关闭。', value0=str(message).strip().splitlines()[-1])

    def job(self,function,callback):
        worker=CoverJob(self);self.jobs.add(worker)
        def done(value):
            self.jobs.discard(worker);worker.deleteLater()
            try:callback(value)
            except Exception as exc:self.failed(str(exc))
        worker.finished.connect(done);worker.failed.connect(self.failed);worker.start(function)

    def open_model(self,doc,*,slots=None,template='',name='未命名封面',after=None):
        key=uuid.uuid4().hex
        if slots is None:
            slots={'background':doc.background_id} if doc.background_id else {}
            texts=[l for l in doc.layers if l.kind=='text']
            if texts:slots['title']=texts[-1].id
        self.session.metadata(key,slots=slots,template=template,name=name)
        def opened(state):
            self.accept_state(state);self.choose(key);self.present()
            if after:after(key)
        self.session.request('open-model',key,opened,self.failed,file=self.session.stage_model(doc),metadata={'slots':slots})
        return key

    def choose(self,key):
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole)==key:self.list.setCurrentRow(i);break

    def open_file_bytes(self,data,suffix,*,name='未命名封面',slots=None,template='',filename='',after=None,psd_rebuild=None,legacy_slots=None):
        key=uuid.uuid4().hex;self.session.metadata(key,slots=slots or {},template=template,name=name,filename=filename)
        def opened(state):
            if legacy_slots:
                mapping={l['source_psd_id']:l['id'] for l in state['layers'] if not l.get('reference')}
                roles={role:mapping[int(value)] for role,value in legacy_slots.items() if str(value).isdigit() and int(value) in mapping}
                if roles:self.update_metadata(key,slots=roles)
            self.accept_state(state);self.choose(key)
            if filename and suffix=='.xcf':self.session.request('set-target',key,self.accept_state,self.failed,target=filename)
            self.present()
            if after:after(key)
        self.session.request('open-file',key,opened,self.failed,file=self.session.stage(data,suffix),metadata={'slots':slots} if slots else None,psd_rebuild=psd_rebuild)
        return key

    def present(self):
        if self.current:self.session.request('present',self.current,self.accept_state,self.failed)

    def return_studio(self):
        self.hide()
        if self.parentWidget():
            parent=self.parentWidget().window();parent.show();parent.raise_();parent.activateWindow()

    def new_document(self):self.open_model(CoverDocument())

    def new_frame(self,document):
        self.original=document.snapshot();base=document.layer(document.background_id)
        self.frame=document.assets.get(base.asset) if base else None
        key=str(self.settings.value('cover/last_template',''))
        if key and str(self.settings.value('cover/start_last_template','false')).lower()=='true':
            try:
                entry=self.library.get(key)
                if not entry.get('deleted'):self.apply_template(entry,True);return
            except (OSError,ValueError):pass
        self.open_model(document)

    def update_metadata(self,key,**values):
        meta=self.session.metadata(key,**values)
        persistent={field:meta[field] for field in ('slots','strategy','focus') if field in meta}
        self.session.request('metadata',key,self.accept_state,self.failed,metadata=persistent)

    def refresh_preview(self):
        key=self.current
        if not key or key in self._preview_requested:return
        self._preview_requested.add(key)
        def done(result):
            self._preview_requested.discard(key)
            pixmap=QPixmap();pixmap.loadFromData(self.session.output_bytes(result))
            if key==self.current:self._preview=pixmap;self.fit_preview()
        def failed(message):self._preview_requested.discard(key);self.failed(message)
        self.session.request('export',key,done,failed,format='png',output='outputs/preview-'+uuid.uuid4().hex+'.png')

    def fit_preview(self):
        if self._preview is not None:self.preview.setPixmap(self._preview.scaled(self.preview.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))

    def resizeEvent(self,event):super().resizeEvent(event);self.fit_preview()

    def open_dialog(self):
        path,_=QFileDialog.getOpenFileName(self,tr('打开封面'),str(self.settings.value('cover/xcf_directory','')),'封面 (*.xcf *.psd *.2bytecover)')
        if path:self.open_document(path)

    def open_document(self,path,confirmed=False,after=None):
        path=Path(path);suffix=path.suffix.lower()
        if suffix=='.xcf':self.open_file_bytes(path.read_bytes(),suffix,name=path.stem,filename=str(path),after=after)
        elif suffix=='.2bytecover':self.open_model(CoverDocument.load(path),name=path.stem,after=after)
        elif suffix=='.psd':
            def prepare():
                try:return load_local_psd(path),None
                except ValueError:return None,psd_metadata(path)
            def loaded(value):
                doc,metadata=value
                if doc is not None:
                    bind_text(self.notice, '此旧 PSD 的原始文字/样式元数据校验通过，已重建为 GIMP 可编辑图层；原 PSD 保留。')
                    self.open_model(doc,name=path.stem,after=after)
                else:
                    plan=rebuild_plan(metadata)
                    self.show_psd_notes(plan)
                    self.open_file_bytes(path.read_bytes(),'.psd',name=path.stem,after=after,psd_rebuild=plan)
            self.job(prepare,loaded)

    def show_psd_notes(self,plan):
        notes='\n'.join(plan['warnings']) or '未发现可重建的文字记录；按 GIMP 兼容性导入。'
        bind_text(self.notice, 'PSD 导入：原件保留，文字外观需检查；详细差异见提示。')
        self.notice.setToolTip(notes)
        QMessageBox.information(self,tr('PSD 导入兼容性'),tr('{value0}\n\n请检查图层并指定模板槽位，然后另存 XCF。', value0=notes))

    def save_dialog(self,checked=False,*,save_as=False,after=None):
        key=self.current
        if not key:return
        def described(state):
            self.accept_state(state);target=state.get('file','')
            if save_as or not target:
                initial=target or str(Path(str(self.settings.value('cover/xcf_directory',self.library.root)))/'封面.xcf')
                target,_=QFileDialog.getSaveFileName(self,tr('保存封面（XCF）'),initial,'GIMP 可编辑封面 (*.xcf)')
                if not target:return
            if not target.lower().endswith('.xcf'):target+='.xcf'
            self.save_to(key,target,after,expected_file=state.get('file',''))
        self.session.request('describe',key,described,self.failed)

    def save_to(self,key,target,after=None,*,expected_file=None):
        bind_text(self.status, '正在保存活文档并验证 XCF…')
        def saved(receipt):
            self.accept_state(receipt['state'])
            if receipt['clean']:
                self.session.metadata(key,filename=receipt['file'],saved_time=receipt['time'])
                self.settings.setValue('cover/xcf_directory',str(Path(receipt['file']).parent));self.library.dismiss_xcf_draft(key)
                self.update_status()
                if after:after()
            else:self.status.setText(receipt['reason'])
        self.session.save(key,target,saved,self.failed,expected_file=expected_file)

    def export_dialog(self):
        if not self.current:return
        path,selected=QFileDialog.getSaveFileName(self,tr('导出封面图片'),str(Path(str(self.settings.value('cover/export_directory',self.library.root)))/'封面.png'),
                                                'PNG 图片 (*.png);;JPEG 图片 (*.jpg)')
        if not path:return
        fmt='jpg' if path.lower().endswith(('.jpg','.jpeg')) or selected.startswith('JPEG') else 'png'
        if not Path(path).suffix:path+='.'+fmt
        self.export_to(self.current,path,fmt)

    def export_to(self,key,path,fmt,after=None):
        bind_text(self.status, '正在从 GIMP 活文档导出…')
        def exported(result):
            try:
                atomic_bytes(path,self.session.output_bytes(result));self.session.metadata(key,result=str(Path(path).resolve()))
                self.settings.setValue('cover/export_directory',str(Path(path).parent));bind_text(self.status, '导出完成：{value0}', value0=str(path))
                if after:after(path)
            except (OSError,ValueError) as exc:self.failed(str(exc))
        self.session.request('export',key,exported,self.failed,format=fmt,output='outputs/export-'+uuid.uuid4().hex+'.'+fmt)

    def export_psd_dialog(self):
        key=self.current
        if not key:return
        message=('GIMP 3.2.6 的 PSD 导出会将文字及其描边/阴影变成像素；文字内容和 GIMP 的可编辑效果不能在 PSD 中继续修改。'
                 '\n独立图片层、图层名、位置、显隐和透明度保留。复杂混合、智能对象和外部效果不保证无损。'
                 '\n将先保存一份独立 XCF 母本，再导出 PSD。是否继续？')
        if QMessageBox.question(self,tr('PSD 交换格式限制'),message)!=QMessageBox.Yes:return
        path,_=QFileDialog.getSaveFileName(self,tr('导出 PSD'),str(Path(str(self.settings.value('cover/psd_directory',self.library.root)))/'封面.psd'),'Photoshop 交换文件 (*.psd)')
        if not path:return
        if not path.lower().endswith('.psd'):path+='.psd'
        # Never overwrite an existing XCF master as a side effect of PSD export.
        mother=Path(path).with_name(Path(path).stem+'-XCF母本-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:5]+'.xcf')
        def backed(result):
            try:atomic_bytes(mother,self.session.output_bytes(result))
            except (OSError,ValueError) as exc:self.failed(str(exc));return
            self.settings.setValue('cover/psd_directory',str(Path(path).parent));self.export_to(key,path,'psd')
        self.session.request('snapshot',key,backed,self.failed,output='outputs/psd-master-'+uuid.uuid4().hex+'.xcf')

    def open_result(self):
        path=self.session.meta.get(self.current,{}).get('result')
        if path and Path(path).is_file():QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def add_image(self):
        key=self.current
        if not key:return
        path,_=QFileDialog.getOpenFileName(self,tr('添加图片 / 透明贴图'),'','图片 (*.png *.jpg *.jpeg *.webp *.bmp)')
        if path:self.session.request('add-image',key,self.accept_state,self.failed,file=self.session.stage(Path(path).read_bytes(),Path(path).suffix),name=Path(path).stem)

    def add_text(self):
        key=self.current
        if not key:return
        text=self.quick.toPlainText() or '中文标题'
        def added(state):
            if self._quick_pending.get(key)==text:self._quick_pending.pop(key,None)
            self.accept_state(state);meta=self.session.meta[key];slots=dict(meta.get('slots',{}))
            if not slots.get('title'):slots['title']=next(l['id'] for l in state['layers'] if l.get('text') is not None);self.update_metadata(key,slots=slots)
            self.choose(key);self.present()
        self.session.request('add-text',key,added,self.failed,text=text)

    def change_title(self):
        key=self.current;slot=self.session.meta.get(key,{}).get('slots',{}).get('title')
        if not slot:self.add_text();return
        text=self.quick.toPlainText()
        def changed(state):
            if self._quick_pending.get(key)==text:self._quick_pending.pop(key,None)
            self.accept_state(state);self.refresh_preview()
        self.session.request('title',key,changed,self.failed,slot=slot,text=text)

    def replace_frame(self,checked=False,*,key=None):
        key=key or self.current
        if not self.frame:bind_text(self.status, '本次没有 Studio 冻结帧；可从 Studio 制作封面或添加本地图片。');return
        meta=self.session.meta.get(key,{});slot=meta.get('slots',{}).get('background')
        if not slot:bind_text(self.status, '请通过“更多 → 设置模板槽位”指定可替换底图。');return
        def replaced(state):self.accept_state(state);self.refresh_preview()
        self.session.request('replace-background',key,replaced,self.failed,slot=slot,file=self.session.stage(self.frame,'.png'),
                             strategy=meta.get('strategy','fill'),focus=meta.get('focus',[.5,.5]))

    def templates(self):
        picker=TemplatePicker(self.library,self.settings,self)
        if picker.exec()!=QDialog.Accepted:return
        if picker.selected.get('blank'):self.new_document()
        else:self.apply_template(picker.selected,picker.replace.isChecked())

    def apply_template(self,entry,replace=True):
        def applied(key):
            self.update_metadata(key,strategy=entry.get('strategy','fill'),focus=entry.get('focus',[.5,.5]))
            self.library.mark_used(entry);self.settings.setValue('cover/last_template',entry['id'])
            if replace and self.frame:self.replace_frame(key=key)
        if entry.get('xcf'):
            self.open_file_bytes(self.library.asset(entry,'xcf').read_bytes(),'.xcf',name=entry['name'],
                                 slots=entry.get('slots'),template=entry['id'],after=applied)
        else:
            path=self.library.asset(entry,'psd')
            def prepared(value):
                doc,metadata=value
                if doc is None:
                    plan=rebuild_plan(metadata);self.show_psd_notes(plan)
                    self.open_file_bytes(path.read_bytes(),'.psd',name=entry['name'],template=entry['id'],after=applied,
                                         psd_rebuild=plan,legacy_slots=entry.get('slots',{}))
                else:
                    mapping={psd_id(layer.id):layer.id for layer in doc.layers}
                    slots={role:mapping[value] for role,value in entry.get('slots',{}).items() if value in mapping}
                    def migrated(key):
                        applied(key)
                        bind_text(self.notice, '已由校验通过的旧 PSD 元数据重建可编辑文字。检查后选“更新此模板”保存 XCF；原 PSD 已备份并保留。')
                    self.open_model(doc,slots=slots,template=entry['id'],name=entry['name'],after=migrated)
            def prepare():
                try:return load_local_psd(path),None
                except ValueError:return None,psd_metadata(path)
            self.job(prepare,prepared)

    def save_template_dialog(self,checked=False,*,update=False):
        key=self.current;meta=self.session.meta.get(key,{})
        if not key:return
        template=meta.get('template','') if update else ''
        if update and not template:bind_text(self.status, '当前文档还没有模板母版，请先保存为新模板。');return
        default=self.library.get(template)['name'] if template else meta.get('name','新封面模板')
        name,ok=QInputDialog.getText(self,(tr('更新模板') if update else tr('保存为模板')),tr('模板名称'),text=default)
        if not ok or not name.strip():return
        self.save_template(key,name,template)

    def save_template(self,key,name,template='',after=None):
        def snapshot(result):
            try:
                meta=self.session.meta.get(key,{})
                entry=self.library.save_xcf(name,self.session.output_bytes(result),self.session.output_bytes(result['preview']),key=template or None,
                                           slots=meta.get('slots'),strategy=meta.get('strategy','fill'),focus=meta.get('focus',[.5,.5]))
                self.session.metadata(key,template=entry['id']);bind_text(self.status, '模板已保存：{value0}。普通保存和草稿不会改动模板母版。', value0=entry['name'])
                if after:after(entry)
            except (OSError,ValueError) as exc:self.failed(str(exc))
        self.session.request('snapshot',key,snapshot,self.failed,output='outputs/template-'+uuid.uuid4().hex+'.xcf',preview='outputs/template-'+uuid.uuid4().hex+'.png')

    def import_template(self):
        path,_=QFileDialog.getOpenFileName(self,tr('导入封面模板'),'','封面模板 (*.xcf *.psd)')
        if path:self.open_document(path,after=lambda key:bind_text(self.status, '模板文件已作为新文档打开。检查效果并设置槽位，再选择“保存为模板”。'))

    def slot_dialog(self):
        key=self.current
        if not key:return
        def described(state):
            self.accept_state(state);meta=self.session.meta.get(key,{});dialog=QDialog(self);bind_text(dialog, '模板槽位与换图方式', property='windowTitle')
            form=QFormLayout(dialog);boxes={}
            for role,label in [('background','可替换底图'),('title','主标题'),('subtitle','副标题')]:
                box=QComboBox();box.addItem('不指定','')
                for layer in state['layers']:
                    if layer['group']:continue
                    if (role=='background') != (layer['text'] is None):continue
                    box.addItem(layer['name']+' · '+str(layer['native_id']),layer['id'])
                box.setCurrentIndex(max(0,box.findData(meta.get('slots',{}).get(role))))
                boxes[role]=box;form.addRow(label,box)
            strategy=QComboBox();strategy.addItem('填满（裁切超出画布部分）','fill');strategy.addItem('适应（保留整张图片）','fit')
            strategy.setCurrentIndex(max(0,strategy.findData(meta.get('strategy','fill'))));form.addRow('换图方式',strategy)
            focus=QComboBox()
            for label,value in [('居中',[.5,.5]),('左侧主体',[0,.5]),('右侧主体',[1,.5]),('上方主体',[.5,0]),('下方主体',[.5,1])]:focus.addItem(label,value)
            focus.setCurrentIndex(max(0,focus.findData(meta.get('focus',[.5,.5]))));form.addRow('焦点',focus)
            note=QLabel('槽位随图层内部标识保存；改名、重排不影响。保存或更新模板后，下次复用生效。');note.setWordWrap(True);form.addRow(note)
            buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);form.addRow(buttons)
            if dialog.exec()==QDialog.Accepted:
                self.update_metadata(key,slots={role:box.currentData() for role,box in boxes.items() if box.currentData()},strategy=strategy.currentData(),focus=focus.currentData())
                self.select_document(self.list.currentItem())
        self.session.request('describe',key,described,self.failed)

    def restore_dialog(self):
        rows=self.library.drafts();legacy=self.library.draft()
        choices=[(Path(row.get('filename','')).name or '未命名封面')+' · '+time.strftime('%m-%d %H:%M:%S',time.localtime(row['time']))+' · '+row['document'][:6] for row in rows]
        if legacy:choices.append('上一版本草稿（PSD / .2bytecover）')
        if not choices:bind_text(self.status, '没有可恢复的未完成草稿。');return
        choice,ok=QInputDialog.getItem(self,'恢复草稿','选择独立文档快照；恢复不会冒充手动保存',choices,0,False)
        if not ok:return
        index=choices.index(choice)
        if index==len(rows):self.open_document(self.library.root/legacy['file']);return
        row=rows[index]
        self.open_file_bytes(self.library._draft_asset(row['file']).read_bytes(),'.xcf',name='恢复草稿',slots=row.get('slots'),template=row.get('template',''))
        bind_text(self.notice, '已恢复 {value0} 的草稿。请检查后保存为 XCF；原手动保存文件未覆盖。', value0=time.strftime('%H:%M:%S', time.localtime(row['time'])))

    def close_document(self):
        key=self.current
        if not key:return
        def described(state):
            def close():self.session.request('close',key,lambda _:None,self.failed,discard=False)
            if not state['dirty']:close();return
            answer=QMessageBox.question(self,tr('关闭封面'),tr('此文档有未保存修改。保存后关闭？'),QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel,QMessageBox.Cancel)
            if answer==QMessageBox.Save:self.choose(key);self.save_dialog(after=close)
            elif answer==QMessageBox.Discard:self.session.request('close',key,lambda _:None,self.failed,discard=True)
        self.session.request('describe',key,described,self.failed)

    def add_font(self):
        path,_=QFileDialog.getOpenFileName(self,tr('添加应用专用字体'),'','字体 (*.otf *.ttf)')
        if not path:return
        # GIMP reads this application-only directory. Never install system fonts.
        import hashlib
        data=Path(path).read_bytes();target=self.session.profile/'fonts'/(hashlib.sha256(data).hexdigest()+Path(path).suffix)
        atomic_bytes(target,data)
        self.session.request('fonts-refresh',self.current,lambda _:bind_text(self.status, '本地字体已刷新，可在 GIMP 字体列表选择；XCF 不嵌入字体。'),self.failed)

    def open_local(self):
        editor=CoverEditor(self.original,self);self._local.append(editor);editor.show()
