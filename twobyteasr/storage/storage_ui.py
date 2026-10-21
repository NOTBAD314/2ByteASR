"""Storage section embedded in the shared settings dialog."""
from __future__ import annotations
from dataclasses import asdict, replace
import json
from pathlib import Path
import threading
import time
from PySide6.QtCore import QObject, Qt, Signal, QUrl, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QSpinBox, QTreeWidget, QTreeWidgetItem, QMessageBox,
    QDialog, QPlainTextEdit, QDialogButtonBox, QFileDialog)
from .storage_service import StorageService, LABELS, GiB
from ..local_models.model_storage import format_bytes
from ..i18n import tr, bind_text
from ..app.lazy_pages import existing_page


def _write_maintenance_receipt(service, name, payload):
    """One bounded receipt in the guarded application state directory."""
    service.write_state_json(name, payload)


def _read_receipt(service, name):
    from .storage_service import safe_path
    path = service.state_root / name
    if not safe_path(path, (service.paths.user_data_root,)):
        return {}
    try:
        if path.stat().st_size > 256 * 1024: return {}
        result = json.loads(path.read_text('utf8'))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def _receipt_counts(receipt):
    counts = receipt.get('counts') or {}
    if not isinstance(counts, dict): counts = {}
    return {key: max(0, int(counts.get(key, len(receipt.get(key) or []))))
            for key in ('deleted', 'skipped', 'failed', 'pending')}


def _counts_text(counts):
    return (tr('已删除 ') + str(counts['deleted']) + tr('；已跳过 ') + str(counts['skipped']) +
            tr('；失败 ') + str(counts['failed']) + tr('；等待占用释放 ') + str(counts['pending']))


def _uv_result_text(receipt):
    status = dict(removed='维护完成', unchanged='维护已执行；没有可移除条目', skipped='已跳过', failed='维护失败', cancelled='已取消')
    measured = receipt.get('measurement_complete', False)
    logical = format_bytes(receipt.get('logical_removed_bytes', 0)) if measured else tr('未完成测量')
    delta = receipt.get('disk_free_delta')
    physical = (('+' if delta >= 0 else '-') + format_bytes(abs(delta))) if delta is not None else tr('未完成测量')
    return (tr(status.get(receipt.get('status'), '状态未知')) + tr('；逻辑删除：') + logical +
            tr('；卷空闲变化：') + physical + tr('（含其他进程活动）'))


def run_uv_maintenance(service, cancel, *, manual=False):
    from ..system.runtime_download_cache import prune_runtime_download_cache
    result = prune_runtime_download_cache(service.paths.install_root,
        data_root=service.paths.user_data_root, cancel=cancel, busy=service.manual_busy if manual else service.busy,
        resume_days=service.policy()['resume_days'], **({'mode':'clean'} if manual else {}))
    payload = asdict(result)
    payload['detail'] = payload['detail'][:4000]
    payload['time'] = time.time()
    try:
        _write_maintenance_receipt(service, 'last-uv-cleanup.json', payload)
    except (OSError, ValueError) as exc:
        result = replace(result, detail=result.detail + '\n' + tr('结果记录未保存：') + str(exc))
    return result


def maintain_registered_storage(service, cancel):
    """Idle work touches indexed cache files and exact model staging receipts."""
    from .storage_service import ScanResult, CacheItem, safe_path
    from ..local_models.model_download_cache import scan_download_transactions, cleanup_download_transaction
    if cancel.is_set() or service.busy() or not service.policy()['enabled']: return None
    service.forget_missing(limit=256)
    registered, leases = service._registered()
    scan = ScanResult()
    for path, row in registered.items():
        if cancel.is_set() or service.busy() or not service.policy()['enabled']: break
        if path in leases or not safe_path(path, service.roots): continue
        try:
            info = Path(path).stat()
            category, producer, source, rebuild, protected, used = row
            scan.items.append(CacheItem(path, category, info.st_size, used, producer, source,
                protected, rebuild, (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)))
        except OSError: continue
    result = service.clean(service.recommended(scan), cancel, automatic=True) if scan.items else None
    # The model tree itself is never scanned. The downloader alone owns these
    # receipts, and cleanup rechecks each receipt plus its model preparation lock.
    staging = service.paths.model_root / '.downloads'
    outcomes = []
    if not cancel.is_set() and not service.busy() and service.policy()['enabled']:
        for transaction in scan_download_transactions(staging, cancel=cancel):
            if cancel.is_set() or service.busy() or not service.policy()['enabled']: break
            outcome = cleanup_download_transaction(transaction, staging_root=staging,
                expired_only=True, resume_days=service.policy()['resume_days'],
                cancel=cancel, busy=lambda:service.busy() or not service.policy()['enabled'])
            outcomes.append(outcome)
    if outcomes:
        payload = dict(time=time.time(), logical_removed_bytes=sum(o['logical_bytes'] for o in outcomes),
            counts=dict(deleted=sum(len(o['removed']) for o in outcomes),
                        failed=sum(len(o['failures']) for o in outcomes),
                        skipped=sum(len(o['skipped']) for o in outcomes)),
            cancelled=cancel.is_set(), details=[])
        # One total of at most 100 short detail records, not 100 per transaction.
        for outcome in outcomes:
            for path in outcome['removed']:
                if len(payload['details']) < 100:
                    payload['details'].append(dict(status='deleted', path=path[:512]))
            for reason in outcome['skipped']:
                if len(payload['details']) < 100:
                    payload['details'].append(dict(status='skipped', reason=reason[:512]))
            for path, reason in outcome['failures'].items():
                if len(payload['details']) < 100:
                    payload['details'].append(dict(status='failed', path=path[:512], reason=reason[:512]))
        payload['truncated'] = sum(payload['counts'].values()) > len(payload['details'])
        _write_maintenance_receipt(service, 'last-model-download-cleanup.json', payload)
    # 2026-10-16 (user: runtimes 17 GB): superseded runtimes go first, so the
    # cache maintenance below can free the cached files only they linked to.
    if not cancel.is_set() and not service.busy() and service.policy()['enabled']:
        run_runtime_maintenance(service, cancel)
    marker = service.paths.managed_runtime_root / 'download-cache-maintenance.json'
    try:
        state = json.loads(marker.read_text('utf8')).get('state') if safe_path(marker, (service.paths.managed_runtime_root,)) else None
    except (OSError, ValueError, AttributeError): state = None
    # Interrupted installs ("installing" left by a pause, "paused", "failed")
    # no longer block maintenance for good: the prune keeps their resume data
    # for the retention days and maintains after that.
    if state in {'ready', 'installing', 'paused', 'failed'} and not cancel.is_set() and not service.busy() and service.policy()['enabled']:
        run_uv_maintenance(service, cancel)
    return result


def run_runtime_maintenance(service, cancel):
    """Remove superseded runtimes automatically; the receipt feeds the storage page."""
    from ..local_models.model_runtime_cleanup import remove_superseded_runtimes
    try:
        receipt = remove_superseded_runtimes(install_root=service.paths.install_root,
            data_root=service.paths.user_data_root, busy=service.busy, cancel=cancel.is_set)
    except Exception as exc:
        receipt = dict(time=time.time(), removed=[], kept=[], failures={'scan': str(exc)[:512]}, retained=0,
                       logical_removed_bytes=0, cancelled=cancel.is_set())
    if receipt is not None:
        try:
            _write_maintenance_receipt(service, 'last-runtime-cleanup.json', receipt)
        except (OSError, ValueError):
            pass
    return receipt


def app_busy(owner, *, manual=False):
    if owner is None: return False
    if getattr(owner, '_run_in_progress', False): return True
    workshop = existing_page(owner, 'workshop')
    if workshop:
        if getattr(workshop,'_removing',None) or getattr(workshop,'_mac_cpu_probe_running',False):return True
        from PySide6.QtCore import QProcess
        for dialog in getattr(workshop,'_download_dialogs',()):
            process=getattr(dialog,'process',None)
            if process and process.state()!=QProcess.ProcessState.NotRunning:return True
    studio = existing_page(owner, 'studio')
    exporter=getattr(studio,'export_workspace',None)
    export_worker=getattr(exporter,'_worker',None)
    if export_worker and export_worker.is_alive():return True
    # An open project can have mmap/background consumers. Defer maintenance until
    # it closes, without closing it on the user's behalf. This is intentionally conservative.
    project=getattr(studio,'project',None)
    if not manual and project and getattr(project.media,'path','') and not getattr(studio,'_close_requested',False):return True
    # Moving models/runtimes elsewhere (2026-10-17) holds them for its duration.
    from .storage_relocation import relocation_running
    if relocation_running():return True
    return False


def loaded_media_graph(owner):
    import copy
    studio=existing_page(owner,'studio')
    project=getattr(studio,'project',None)
    if project is None:return None
    controller=getattr(studio,'project_controller',None)
    session=getattr(controller,'session',None)
    project_path=getattr(session,'project_path',None) or Path.cwd()/'unsaved.2byteproj'
    consumers=[]
    video=getattr(studio,'video',None)
    if getattr(video,'_media_attached',False) and getattr(video,'_media_path',''):
        consumers.append(str(video._media_path))
    engine=getattr(studio,'audio_engine',None)
    audio_payload=getattr(engine,'_last_payload',{}) or {}
    if audio_payload.get('source_path'):consumers.append(str(audio_payload['source_path']))
    for layer in audio_payload.get('mix_layers',()) or ():
        if layer.get('source_path'):consumers.append(str(layer['source_path']))
    # SubtitleProject.to_dict() persists its runtime sequence back onto the
    # user's project. Inventory must only read the actual media graph.
    runtime=getattr(project,'_edit_sequence_runtime',None)
    sequence=asdict(runtime.sequence) if runtime is not None else copy.deepcopy(project.edit_sequence)
    graph=dict(schema_version=project.schema_version,media=dict(path=project.media.path),
        media_pool=[asdict(asset) for asset in project.media_pool],
        video_tracks=[asdict(track) for track in project.video_tracks],
        audio_tracks=[asdict(track) for track in project.audio_tracks],edit_sequence=sequence)
    return graph,str(project_path),tuple(consumers)


class StorageWorker(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()
    def __init__(self, fn):
        super().__init__(QApplication.instance())
        self.cancel = threading.Event(); self.fn=fn; self.thread=None
    def start(self):
        self.thread=threading.Thread(target=self.run,name='storage-maintenance',daemon=True)
        self.thread.start()
    def isRunning(self):
        return bool(self.thread and self.thread.is_alive())
    def run(self):
        try:
            value=self.fn(self.cancel)
            self.result.emit(value)
        except Exception as exc:
            try:self.error.emit(str(exc))
            except RuntimeError:pass
        finally:
            try:self.finished.emit()
            except RuntimeError:pass


class StoragePanel(QWidget):
    def __init__(self, parent=None, *, owner=None, service=None):
        super().__init__(parent)
        self.owner=owner;self._own_service=service is None;self.service=service or self._new_service()
        self.scan_result=None; self.worker=None
        self.setObjectName('storageCachePanel')
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(12)
        # 2026-10-17 (users: C: drive full): where runtimes and models are, and
        # moving both to another folder or drive (Windows; ADR 0129).
        self.location_label=QLabel();self.location_label.setObjectName('storageLocations')
        self.location_label.setWordWrap(True);self.location_label.setProperty('i18nUserText',True)
        self.location_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.move_button=None
        locations=QHBoxLayout();locations.addWidget(self.location_label,1)
        import os
        if os.name=='nt':
            self.move_button=bind_text(QPushButton(),'移到其他位置…');self.move_button.setObjectName('storageRelocate')
            self.move_button.clicked.connect(self.relocate);locations.addWidget(self.move_button,0,Qt.AlignmentFlag.AlignTop)
        layout.addLayout(locations);self._show_locations()
        self.summary=QLabel(tr('尚未扫描；统计将在后台执行。'));self.summary.setWordWrap(True);layout.addWidget(self.summary)
        buttons=QHBoxLayout()
        self.scan_button=bind_text(QPushButton(),'扫描占用'); self.scan_button.setObjectName('storageScan')
        self.cancel_button=bind_text(QPushButton(),'取消扫描／清理');self.cancel_button.setEnabled(False)
        buttons.addWidget(self.scan_button);buttons.addWidget(self.cancel_button);buttons.addStretch();layout.addLayout(buttons)
        self.tree=QTreeWidget();self.tree.setHeaderLabels([tr('类别／文件'),tr('逻辑大小'),tr('状态')]);self.tree.setMinimumHeight(170)
        self.tree.setColumnWidth(0,225);self.tree.setColumnWidth(1,90);layout.addWidget(self.tree)
        actions=QHBoxLayout()
        self.recommended=bind_text(QPushButton(),'清理推荐缓存');self.recommended.setObjectName('storageCleanRecommended')
        self.selected=bind_text(QPushButton(),'清理所选类别');self.details=bind_text(QPushButton(),'查看清理详情')
        self.open_button=bind_text(QPushButton(),'打开对应目录')
        for b in (self.recommended,self.selected,self.details,self.open_button): actions.addWidget(b)
        layout.addLayout(actions)
        policy=self.service.policy()
        self.enabled=QCheckBox(tr('自动清理已登记的本地缓存（软件运行且空闲时）'));self.enabled.setChecked(policy['enabled']);layout.addWidget(self.enabled)
        self.policy_controls={}
        for key,label,divisor,maximum in (
            ('budget_bytes','缓存预算 GiB',GiB,1024),('retention_days','缓存保留天数',1,3650),
            ('log_days','普通日志保留天数',1,3650),('log_budget_bytes','普通日志预算 MiB',1024**2,10240),
            ('resume_days','暂停下载保留天数',1,3650)):
            row=QHBoxLayout();row.addWidget(QLabel(tr(label)),1)
            control=QSpinBox();control.setRange(1,maximum);control.setValue(max(1,policy[key]//divisor));row.addWidget(control)
            layout.addLayout(row);self.policy_controls[key]=(control,divisor)
        hint=QLabel(tr('默认 10 GiB / 7 天；日志 14 天 / 200 MiB；暂停下载 14 天。模型、工程、原ASR文字及远程结果不参与预算。扫描不会更新使用时间。受保护内容超过预算时保留并说明。'))
        hint.setWordWrap(True);hint.setObjectName('settingsDescription');layout.addWidget(hint)
        extra=QHBoxLayout()
        self.uv=bind_text(QPushButton(),'清理运行库下载缓存（uv）');self.uv.setObjectName('storageUvPrune')
        self.models=bind_text(QPushButton(),'模型与历史删除残留…');self.models.setObjectName('storageModelResiduals')
        extra.addWidget(self.uv);extra.addWidget(self.models);layout.addLayout(extra)
        self.adopt_button=bind_text(QPushButton(),'确认登记已识别的历史缓存…');layout.addWidget(self.adopt_button)
        self.adopt_button.clicked.connect(self.adopt_legacy)
        media_actions=QHBoxLayout()
        self.save_media=bind_text(QPushButton(),'保存中间媒体为工程资产…');self.save_media.setObjectName('storageSaveMediaAsset')
        self.relink_media=bind_text(QPushButton(),'在工作台重新定位原素材');self.relink_media.setObjectName('storageRelinkOriginalMedia')
        media_actions.addWidget(self.save_media);media_actions.addWidget(self.relink_media);layout.addLayout(media_actions)
        self.save_media.clicked.connect(self.save_media_asset);self.relink_media.clicked.connect(self.open_media_relink)
        self.tree.itemSelectionChanged.connect(self._update_media_controls)
        self.tree.itemChanged.connect(lambda *_:self._update_clean_controls())
        self._update_media_controls()
        self.last=QLabel();self.last.setWordWrap(True);layout.addWidget(self.last);self._last_receipt()
        self.scan_button.clicked.connect(self.scan);self.cancel_button.clicked.connect(self.cancel)
        self.recommended.clicked.connect(lambda:self.clean(True));self.selected.clicked.connect(lambda:self.clean(False))
        self.details.clicked.connect(self.show_details);self.open_button.clicked.connect(self.open_directory)
        self.uv.clicked.connect(self.prune_uv);self.models.clicked.connect(self.open_models)
        self.destroyed.connect(self._stop_worker)
        self._toggle_clean(False)

    def _stop_worker(self,*args):
        if self.worker:self.worker.cancel.set()
    def _new_service(self):
        owner=self.owner
        return StorageService(busy=lambda:app_busy(owner),manual_busy=lambda:app_busy(owner,manual=True),media_references=lambda:loaded_media_graph(owner))
    def _show_locations(self):
        paths=self.service.paths
        self.location_label.setText(tr('运行环境：{path}',path=str(paths.managed_runtime_root))+'\n'+tr('模型：{path}',path=str(paths.model_root)))
    def relocate(self):
        from .storage_relocation_ui import choose_and_move
        choose_and_move(self,busy=lambda:app_busy(self.owner,manual=True) or bool(self.worker and self.worker.isRunning()),
                        on_moved=self._relocated)
    def _relocated(self,_result):
        from ..runtime_paths import get_runtime_paths
        # The download cache root and the model root changed with the move.
        if self._own_service:
            try:self.service=self._new_service()
            except (OSError,RuntimeError):pass
        self._show_locations()
        # 应用设置 saves its 模型下载目录 field on OK; it must not put the old folder back.
        dialog=self.window();edit=getattr(dialog,'model_root_edit',None)
        if edit is not None:
            old,new=edit.text(),str(get_runtime_paths().model_root);edit.setText(new)
            # The move already saved it: closing the dialog must not ask to save it again.
            saved=getattr(dialog,'_saved_values',None)
            if isinstance(saved,tuple) and saved and isinstance(saved[0],tuple):
                dialog._saved_values=(tuple((name,new if name==edit.objectName() and text==old else text)
                                            for name,text in saved[0]),*saved[1:])
        workshop=existing_page(self.owner,'workshop')
        if workshop is not None and callable(getattr(workshop,'refresh',None)):workshop.refresh()
        self.scan_result=None;self.tree.clear();self._update_clean_controls()
        self.summary.setText(tr('位置已改变；需要时请重新扫描。'))
    def policy_values(self):
        return dict(enabled=self.enabled.isChecked(), **{k:w.value()*d for k,(w,d) in self.policy_controls.items()})
    def save_policy(self): self.service.save_policy(self.policy_values())
    def _toggle_clean(self,value):
        self.recommended.setEnabled(value);self.selected.setEnabled(value)
    def _selected_categories(self):
        return {self.tree.topLevelItem(n).data(0,Qt.ItemDataRole.UserRole) for n in range(self.tree.topLevelItemCount())
            if self.tree.topLevelItem(n).checkState(0)==Qt.CheckState.Checked}
    def _update_clean_controls(self):
        scan=self.scan_result
        ready=bool(scan and not scan.cancelled and not (self.worker and self.worker.isRunning()))
        auto=self.service.recommended(scan) if ready else []
        manual=self.service.manual_items(scan,self._selected_categories()) if ready else []
        self.recommended.setEnabled(bool(auto));self.selected.setEnabled(bool(manual))
        self.recommended.setToolTip(tr('没有符合自动期限／预算且安全的已登记缓存') if not auto else tr('按自动保留期限／预算选择；不会处理未确认历史文件'))
        self.selected.setToolTip(tr('所选类别没有安全的可执行文件；请查看具体原因') if not manual else tr('手动立即清理；不受自动天数或预算限制'))
    def _run(self,fn,done):
        if self.worker and self.worker.isRunning():return
        worker=StorageWorker(fn);self.worker=worker
        self.scan_button.setEnabled(False);self.uv.setEnabled(False);self.cancel_button.setEnabled(True);self._toggle_clean(False)
        self.save_media.setEnabled(False);self.relink_media.setEnabled(False)
        worker.result.connect(done);worker.error.connect(lambda e:self.summary.setText(tr('操作未完成：')+e))
        worker.finished.connect(lambda:self._finished(worker));worker.start()
    def _finished(self,worker):
        self.scan_button.setEnabled(True);self.uv.setEnabled(True);self.cancel_button.setEnabled(False)
        worker.deleteLater()
        if self.worker is worker:self.worker=None
        self._update_media_controls()
        self._update_clean_controls()
    def scan(self):
        self.summary.setText(tr('正在后台扫描；结果尚不完整…'))
        self._run(lambda c:self.service.scan(c),self._scanned)
    def cancel(self):
        if self.worker:self.worker.cancel.set()
    def _scanned(self,result):
        self.scan_result=result;self.tree.clear()
        groups={}
        for item in result.items:groups.setdefault(item.category,[]).append(item)
        for category,items in groups.items():
            cleanable=sum(i.size for i in items if i.manual_cleanable)
            legacy=sum(1 for i in items if i.producer.endswith('_legacy') and i.manual_cleanable)
            status=tr('手动可清理 ')+format_bytes(cleanable)+(tr('；历史待确认 ')+str(legacy) if legacy else '')
            if category=='uv':status=tr('官方工具可执行清理；释放量完成后统计')
            top=QTreeWidgetItem([tr(LABELS.get(category,category)),format_bytes(sum(i.size for i in items)),status])
            top.setData(0,Qt.ItemDataRole.UserRole,category)
            top.setFlags(top.flags()|Qt.ItemFlag.ItemIsUserCheckable);top.setCheckState(0,Qt.CheckState.Unchecked);self.tree.addTopLevelItem(top)
            for item in sorted(items,key=lambda i:i.size,reverse=True)[:100]:
                state=item.reason or tr('手动可清理；自动期限／预算另行判断')
                if item.cleanable:state=self.service.automatic_reason(item)
                if item.warning:state+='；'+item.warning
                child=QTreeWidgetItem([Path(item.path).name,format_bytes(item.size),state])
                child.setToolTip(0,item.path);child.setToolTip(2,state+'\n'+item.producer);child.setData(0,Qt.ItemDataRole.UserRole,item.path);top.addChild(child)
            if len(items)>100:top.addChild(QTreeWidgetItem([tr('其余文件请查看完整详情'),str(len(items)-100),'']))
        state=tr('完整') if result.complete else tr('部分结果／已取消；不可作为完整统计')
        model=format_bytes(result.model_bytes) if result.model_bytes is not None else tr('未完成')
        unknown=sum(i.size for i in result.items if i.category=='unknown')
        tool=sum(i.size for i in result.items if i.category=='uv')
        protected=sum(i.size for i in result.items if not i.manual_cleanable and i.category not in {'unknown','uv'})
        # 2026-10-16 (user: runtimes 17 GB): runtimes are hard-linked to the
        # download cache; Explorer adds every link, this counts each file once.
        usage=result.runtime_usage;runtime=''
        if usage is not None:
            runtime='\n'+tr('运行环境实际占用 {size}',size=format_bytes(usage.unique_bytes))
            if usage.logical_bytes>usage.unique_bytes:
                runtime+=tr('（同一文件只算一次；资源管理器会把硬链接重复相加，显示约 {size}）',size=format_bytes(usage.logical_bytes))
            runtime+=tr('；其中只有下载缓存在用 {size}（维护下载缓存最多能释放这么多）',size=format_bytes(usage.cache_only_bytes))
            if not usage.deduplicated:runtime+=tr('；此磁盘不提供文件编号，按逻辑大小统计')
        self.summary.setText(tr('应用管理范围（逻辑）：')+format_bytes(result.total_bytes)+tr('；手动可清理（含待确认历史）：')+format_bytes(result.manual_cleanable_bytes)+
            tr('；实际占用／保护：')+format_bytes(protected)+tr('；归属未确认：')+format_bytes(unknown)+tr('；官方工具范围：')+format_bytes(tool)+tr('；模型单列：')+model+runtime+'\n'+state+
            ('\n'+'\n'.join(result.errors[:3]) if result.errors else ''))
        self._update_media_controls()
        self._update_clean_controls()

    def _selected_missing_media(self):
        selected=self.tree.currentItem()
        path=selected.data(0,Qt.ItemDataRole.UserRole) if selected else None
        item=next((i for i in self.scan_result.items if i.path==path),None) if self.scan_result else None
        # A current/saved project's dependency may replace the displayed reason.
        # That prevents deletion; it must not prevent explicitly preserving the
        # missing original's known local media copy. The producer rechecks its
        # ownership, identity and source before copying, and retains the cache.
        if (item and item.category=='media' and item.producer and item.source and
                item.rebuild=='local' and item.identity and
                Path(item.path).suffix.lower() in {'.mp4','.mkv','.mov','.avi','.webm'}):
            try:
                if not Path(item.source).is_file():return item
            except OSError:pass
        return None

    def _update_media_controls(self):
        enabled=bool(self._selected_missing_media() and not (self.worker and self.worker.isRunning()))
        self.save_media.setEnabled(enabled);self.relink_media.setEnabled(enabled)

    def save_media_asset(self):
        item=self._selected_missing_media()
        if not item:return
        destination,_=QFileDialog.getSaveFileName(self,tr('保存中间媒体为工程资产'),
            str(Path.home()/Path(item.path).name),tr('媒体文件 (*.mp4 *.mkv *.mov *.avi *.webm);;所有文件 (*)'))
        if not destination:return
        self.summary.setText(tr('正在后台保存并校验媒体资产；可以取消。原缓存将保留。'))
        from .storage_media_assets import save_cached_media_asset
        self._run(lambda cancel:save_cached_media_asset(self.service,item,destination,cancel=cancel),self._media_saved)

    def _media_saved(self,result):
        if result.status=='saved':
            self.summary.setText(tr('已保存媒体资产：')+result.destination+'\n'+
                tr('逻辑大小：')+format_bytes(result.logical_bytes)+'；SHA256: '+result.sha256+'\n'+result.detail)
        else:self.summary.setText(tr('媒体资产保存未完成：')+result.detail)

    def open_media_relink(self):
        if not self._selected_missing_media():return
        studio=existing_page(self.owner,'studio')
        availability=getattr(studio,'media_availability',None)
        if studio and getattr(studio,'project',None) and availability:
            self.window().accept()
            switch=getattr(self.owner,'_switch_page',None)
            if callable(switch):switch(studio)
            else:
                pages=getattr(self.owner,'pages',None)
                if pages is not None:pages.setCurrentWidget(studio)
            availability.show_media()
        else:
            QMessageBox.information(self,tr('重新定位原素材'),tr('请打开对应字幕工程，在工作台素材池选择脱机素材，再点“重新定位”。若先保存了中间媒体资产，可以选择该资产副本；检查音轨与时间映射后保存工程。'))
    def clean(self,recommended):
        if not self.scan_result:return
        if recommended:items=self.service.recommended(self.scan_result)
        else:
            items=self.service.manual_items(self.scan_result,self._selected_categories())
        if not items:
            QMessageBox.information(self,tr('存储与缓存'),tr('没有符合策略的可清理文件。'));return
        text=tr('所选范围：')+', '.join(sorted({tr(LABELS.get(i.category,i.category)) for i in items}))+'\n'+tr('文件数：')+str(len(items))+'；'+tr('预计逻辑删除量：')+format_bytes(sum(i.size for i in items))+'\n'+tr('手动清理不受自动保留天数或预算限制。历史文件将先批量复核并登记归属。活动租约、媒体唯一副本、未知归属或身份变化将跳过。')
        warnings=sorted({i.warning for i in items if i.warning})
        if warnings:text+='\n'+'\n'.join(warnings)
        if QMessageBox.question(self,tr('确认清理缓存'),text,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)!=QMessageBox.StandardButton.Yes:return
        self._run(lambda c:(self.service.clean(items,c,adopt_legacy=not recommended,allow_missing_aux=not recommended),self.service.scan(c)),self._cleaned)
    def _cleaned(self,result):
        if isinstance(result,tuple):result,scan=result;self._scanned(scan)
        else:self.scan_result=None;self.tree.clear()
        self._last_receipt()
        self.summary.setText(_counts_text({key:len(getattr(result,key)) for key in ('deleted','skipped','failed','pending')})+'\n'+tr('已删除逻辑大小：')+format_bytes(result.logical_removed_bytes)+'\n'+result.note+'\n'+(self.summary.text() if self.scan_result else tr('请重新扫描剩余范围')))
    def _last_receipt(self):
        import datetime
        lines=[]
        receipt=_read_receipt(self.service,'last-cleanup.json')
        try:
            stamp=datetime.datetime.fromtimestamp(receipt['time']).strftime('%Y-%m-%d %H:%M')
            lines.append(tr('上次缓存清理：')+stamp+tr('；逻辑删除 ')+format_bytes(receipt['logical_removed_bytes'])+'\n'+_counts_text(_receipt_counts(receipt)))
        except (OSError,ValueError,KeyError,TypeError,OverflowError):
            lines.append(tr('尚无缓存清理记录'))
        uv=_read_receipt(self.service,'last-uv-cleanup.json')
        try:
            stamp=datetime.datetime.fromtimestamp(uv['time']).strftime('%Y-%m-%d %H:%M')
            lines.append(tr('上次运行库缓存维护：')+stamp+'\n'+_uv_result_text(uv))
        except (ValueError,KeyError,TypeError,OverflowError):pass
        runtime=_read_receipt(self.service,'last-runtime-cleanup.json')
        try:
            stamp=datetime.datetime.fromtimestamp(runtime['time']).strftime('%Y-%m-%d %H:%M')
            lines.append(tr('上次自动清理旧版本运行环境：')+stamp+tr('；删除 ')+str(len(runtime['removed']))+tr(' 个，逻辑删除 ')+
                format_bytes(runtime['logical_removed_bytes'])+(tr('；保留 ')+str(len(runtime['kept']))+tr(' 个（原因见详情）') if runtime['kept'] else '')+
                (tr('；失败 ')+str(len(runtime['failures'])) if runtime['failures'] else ''))
        except (ValueError,KeyError,TypeError,OverflowError):pass
        self.last.setText('\n'.join(lines))
    def show_details(self):
        dialog=QDialog(self);dialog.setWindowTitle(tr('存储清理详情'));dialog.resize(760,520)
        layout=QVBoxLayout(dialog);text=QPlainTextEdit();text.setReadOnly(True)
        payload=dict(scan=asdict(self.scan_result) if self.scan_result else None,
            last_cleanup=_read_receipt(self.service,'last-cleanup.json'),
            last_uv_cleanup=_read_receipt(self.service,'last-uv-cleanup.json'),
            last_runtime_cleanup=_read_receipt(self.service,'last-runtime-cleanup.json'),
            last_model_download_cleanup=_read_receipt(self.service,'last-model-download-cleanup.json'))
        text.setPlainText(json.dumps(payload,ensure_ascii=False,indent=2));layout.addWidget(text)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons);dialog.exec()
    def open_directory(self):
        item=self.tree.currentItem()
        value=item.data(0,Qt.ItemDataRole.UserRole) if item else ''
        if value in LABELS:
            paths=[i.path for i in self.scan_result.items if i.category==value] if self.scan_result else []
            value=paths[0] if paths else str(self.service.paths.cache_root)
        path=Path(value).parent if value else self.service.paths.cache_root
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    def open_models(self):
        callback=getattr(self.owner,'_open_model_workshop',None)
        if callable(callback):
            self.window().accept()
            callback()
        else:
            QMessageBox.information(self,tr('模型与残留'),tr('请打开模型工坊 → 存储管理，查看模型与历史已删除残留。'))
    def prune_uv(self):
        text=tr('执行官方 uv cache clean，仅限应用专属下载缓存；可执行清理，释放量将在完成后统计。先离线检查环境和缓存依赖，使用安装互斥锁，不强制删除。已暂停安装的续传缓存也会移除，以后安装／修复可能需要重新下载。')
        if QMessageBox.question(self,tr('清理运行库下载缓存'),text,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)!=QMessageBox.StandardButton.Yes:return
        self._run(lambda c:(run_uv_maintenance(self.service,c,manual=True),self.service.scan(c)),self._uv_cleaned)

    def _uv_cleaned(self,result):
        if isinstance(result,tuple):result,scan=result;self._scanned(scan)
        self._last_receipt()
        self.summary.setText(_uv_result_text(asdict(result))+'\n'+result.detail)

    def adopt_legacy(self):
        items=[i for i in self.scan_result.items if i.producer.endswith('_legacy') and i.manual_cleanable] if self.scan_result else []
        if not items:
            QMessageBox.information(self,tr('历史缓存'),tr('请先扫描。仅有真实生成契约的旧缓存可登记，未知文件保持待确认。'));return
        text=tr('已识别文件：')+str(len(items))+tr('；逻辑占用：')+format_bytes(sum(i.size for i in items))+'\n'+tr('登记后可手动立即清理。历史未记录实际使用时间的文件继续排除自动清理；消费者已结束的一次性覆盖层除外。以后实际使用会更新。仅对应活动租约／会话跳过；唯一媒体副本保持保护。')
        warnings=sorted({i.warning for i in items if i.warning})
        if warnings:text+='\n'+'\n'.join(warnings)
        if QMessageBox.question(self,tr('确认缓存归属'),text,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)!=QMessageBox.StandardButton.Yes:return
        from .storage_legacy import adopt
        def adopted(value):
            receipt,scan=value;self._scanned(scan)
            self.summary.setText(tr('历史缓存已登记：')+str(receipt['registered'])+tr('；已跳过：')+str(len(receipt['skipped']))+'\n'+self.summary.text())
        self._run(lambda c:(adopt(self.service,items,cancel=c),self.service.scan(c)),adopted)


class IdleStorageMaintenance:
    """Run only after UI readiness, then at most once each six hours, no exit scan."""
    def __init__(self,owner):
        self.owner=owner;self.worker=None;self.cancel=threading.Event()
        self.timer=QTimer(owner);self.timer.setInterval(15*60*1000);self.timer.timeout.connect(self.check)
        QApplication.instance().aboutToQuit.connect(self.stop)
        QTimer.singleShot(60000,owner,self.check)
        self.last_attempt=0
    def stop(self):
        self.cancel.set();self.timer.stop()
        if self.worker:self.worker.cancel.set()
    def request_soon(self,delay_ms=5000):
        """After a successful install, maintain now instead of within six hours (2026-10-16).
        check() still waits until nothing else runs; the 15-minute timer retries until then."""
        if self.cancel.is_set():return
        self.last_attempt=0
        QTimer.singleShot(delay_ms,self.owner,self.check)
    def check(self):
        self.timer.start()
        if self.cancel.is_set() or app_busy(self.owner):return
        import time
        if time.time()-self.last_attempt<6*3600:return
        if self.worker and self.worker.isRunning():return
        service=StorageService(busy=lambda:self.cancel.is_set() or app_busy(self.owner),media_references=lambda:loaded_media_graph(self.owner))
        if not service.policy()['enabled']:return
        self.last_attempt=time.time()
        worker=StorageWorker(lambda cancel:maintain_registered_storage(service,cancel));self.worker=worker
        def finish():
            if self.worker is worker:self.worker=None
            worker.deleteLater()
        worker.finished.connect(finish);worker.start()
