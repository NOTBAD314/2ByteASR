"""Compiled opt-in after-cleanup audit; explicit real paths remain read-only."""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import traceback

PATH_KEYS = ('install_root','user_data_root','model_root','cache_root','project_root',
             'config_root','log_root','renderer_asset_root','temp_root')
MAX_PROTECTED_FILE = 32 * 1024 * 1024


def small_file_fingerprint(path):
    """No full video copies/hashes; missing, identity and SHA all stay explicit."""
    from .storage_service import safe_path
    path = Path(path).absolute()
    if not safe_path(path,(path.parent,)):
        raise ValueError(f'保护基线文件含链接或不可读取：{path}')
    try:info=path.lstat()
    except FileNotFoundError:return dict(exists=False)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_PROTECTED_FILE:
        raise ValueError(f'保护基线必须是小型独立普通文件：{path}')
    identity=[info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns]
    digest=hashlib.sha256()
    with path.open('rb') as reader:
        opened=os.fstat(reader.fileno())
        if [opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns]!=identity:
            raise ValueError(f'保护基线打开期间变化：{path}')
        for block in iter(lambda:reader.read(1024*1024),b''):digest.update(block)
    final=path.lstat()
    if [final.st_dev,final.st_ino,final.st_size,final.st_mtime_ns]!=identity:
        raise ValueError(f'保护基线读取期间变化：{path}')
    return dict(exists=True,identity=identity,sha256=digest.hexdigest(),size=info.st_size,mtime_ns=info.st_mtime_ns)


def readonly_service(paths, owner=None):
    from .storage_service import StorageService
    from .storage_ui import app_busy,loaded_media_graph
    class ActualReadOnlyService(StorageService):
        def __init__(self):
            super().__init__(paths,busy=lambda:app_busy(owner),manual_busy=lambda:app_busy(owner,manual=True),
                media_references=lambda:loaded_media_graph(owner))
            self.rejected_actions=[]
        def reject(self,action):
            self.rejected_actions.append(action)
            raise PermissionError('真实清理后审计只读；拒绝 '+action)
        def _db(self):return self.reject('write database')
        def _registered(self,*,read_only=False):
            if not read_only:return self.reject('mutable registry read')
            return super()._registered(read_only=True)
        def save_policy(self,policy):return self.reject('save policy')
        def write_state_json(self,name,payload):return self.reject('write receipt')
        def clean(self,*args,**kwargs):return self.reject('clean cache')
        def register(self,*args,**kwargs):return self.reject('register cache')
        def touch(self,*args,**kwargs):return self.reject('touch cache')
        @contextmanager
        def lease(self,*args,**kwargs):
            self.reject('lease cache');yield
    return ActualReadOnlyService()


def start(window,output):
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QDialogButtonBox
    from . import application_settings_ui,blank_project_audit
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .runtime_paths import RuntimePaths
    from .storage_ui import format_bytes,_receipt_counts
    from .modal_acceptance_driver import ModalAcceptanceDriver,cancel_without_settings_save_prompt
    output=Path(output);manifest_path=output/'real-storage-after-input.json'
    manifest=json.loads(manifest_path.read_text('utf8'))
    if manifest.get('schema_version')!=1:raise ValueError('Unknown read-only after manifest')
    paths=RuntimePaths(*(Path(manifest['roots'][key]) for key in PATH_KEYS))
    service=readonly_service(paths,window)
    original_init=application_settings_ui.ApplicationSettingsDialog.__init__
    class Audit(ModalAcceptanceDriver):
        def __init__(self):
            super().__init__(window,output,'real-storage-after',timeout=300)
            self.result.update(readonly=True,provider_calls=0,pid=os.getpid(),
                identity=load_build_identity().to_dict(),actual_user_data_root=str(paths.user_data_root),
                inventory_sha256=manifest['inventory_sha256'],input_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                historical_after_logical_bytes=manifest['historical_after_logical_bytes'],rejected_actions=service.rejected_actions)
        def click(self,widget):
            self.check('normal control visible before mouse input',widget is not None and widget.isVisible())
            QTest.mouseClick(widget,Qt.LeftButton)
        def shot(self,name):
            self.progress('capture-enter',name)
            panel=self.dialog.storage_panel
            def geometry(widget):
                point=widget.mapToGlobal(widget.rect().topLeft())
                return dict(visible=widget.isVisible(),rect=list(widget.rect().getRect()),global_rect=[point.x(),point.y(),widget.width(),widget.height()])
            tree=[]
            for n in range(panel.tree.topLevelItemCount()):
                row=panel.tree.topLevelItem(n)
                tree.append(dict(category=row.data(0,Qt.UserRole),texts=[row.text(k) for k in range(3)],
                    rect=list(panel.tree.visualItemRect(row).getRect()),expanded=row.isExpanded(),
                    leaves=[dict(path=row.child(i).data(0,Qt.UserRole),texts=[row.child(i).text(k) for k in range(3)],
                        rect=list(panel.tree.visualItemRect(row.child(i)).getRect())) for i in range(row.childCount())]))
            self.result.setdefault('paint_snapshots',[]).append(dict(name=name,summary_text=panel.summary.text(),last_receipt_text=panel.last.text(),
                panel=geometry(panel),summary=geometry(panel.summary),tree=geometry(panel.tree),rows=tree,
                dpr=window.devicePixelRatioF(),worker_none=panel.worker is None))
            _capture(window,output/(name+'-whole-window.png'));_capture(self.dialog,output/(name+'-settings.png'))
            self.result['screenshots'] += [name+'-whole-window.png',name+'-settings.png']
            self.progress('capture-return',name);self.checkpoint()
        def run(self):
            self.phase('normal Home Settings entry')
            yield .2
            seed_project=getattr(window.studio_page,'project',None)
            self.check('normal cold-start uses owned blank seed',seed_project is None or not seed_project.media.path)
            self.queue_action('open normal Home Settings',lambda:self.click(window.app_settings_button))
            yield lambda:self.dialog is not None and self.dialog.isVisible()
            dialog=self.dialog;panel=dialog.storage_panel
            self.check('actual service roots are explicit, UI/startup remains isolated',panel.service.paths==paths and not Path(os.environ['TWOBYTEASR_TEST_ROOT']).is_relative_to(paths.user_data_root))
            self.check('storage navigation uses normal Settings entry',dialog.navigation.item(2).text()=='存储与缓存')
            QTest.mouseClick(dialog.navigation.viewport(),Qt.LeftButton,pos=dialog.navigation.visualItemRect(dialog.navigation.item(2)).center())
            yield .3
            self.phase('actual read-only storage initial controls')
            self.check('real storage page visible and initial inventory unknown',panel.isVisible() and panel.scan_result is None)
            self.shot('01-actual-storage-after-unscanned')
            self.phase('actual read-only storage scan')
            self.click(panel.scan_button)
            self.check('actual scan runs asynchronously with cancellation',panel.cancel_button.isEnabled())
            yield lambda:panel.worker is None and panel.scan_result is not None
            # Qt must return to its event loop twice: result model then paint.
            yield .3
            self.phase('actual result controls repaint and receipt')
            panel.summary.update();panel.tree.viewport().update();panel.update();dialog.update();window.update()
            yield .3
            scan=panel.scan_result
            self.check('remaining actual inventory complete',scan.complete,scan.errors)
            self.check('painted total equals remaining scan, without candidate threshold',
                panel.summary.text().startswith('应用管理范围（逻辑）：'+format_bytes(scan.total_bytes)),panel.summary.text())
            self.check('unknown and UV amounts remain separate','归属未确认' in panel.summary.text() and '官方工具范围' in panel.summary.text(),panel.summary.text())
            categories=[]
            for n in range(panel.tree.topLevelItemCount()):
                row=panel.tree.topLevelItem(n);category=row.data(0,Qt.UserRole)
                categories.append(dict(category=category,size=row.text(1),status=row.text(2)))
                if category=='unknown':
                    row.setCheckState(0,Qt.Checked)
                    self.check('unknown ordinary scope has zero executable cleanup',not panel.selected.isEnabled())
                    row.setCheckState(0,Qt.Unchecked)
                if category=='uv':self.check('UV own category retains official maintenance affordance','完成后统计' in row.text(2) and panel.uv.isEnabled())
            receipt=json.loads((service.state_root/'last-cleanup.json').read_text('utf8'))
            counts=_receipt_counts(receipt)
            self.result.update(categories=categories,total_logical_bytes=scan.total_bytes,manual_candidate_bytes=scan.manual_cleanable_bytes,
                historical_after_delta=scan.total_bytes-manifest['historical_after_logical_bytes'],cleanup_receipt=receipt,
                roots=scan.roots,scan_errors=scan.errors)
            self.check('actual last cleanup receipt logical bytes exact',receipt['logical_removed_bytes']==manifest['expected_logical_removed_bytes'],receipt['logical_removed_bytes'])
            self.check('actual last cleanup deleted count exact',counts['deleted']==manifest['expected_deleted_count'],counts)
            self.check('actual last receipt painted from real service',format_bytes(receipt['logical_removed_bytes']) in panel.last.text(),panel.last.text())
            self.check('actual unknown and UV item categories agree with tree',
                {i.category for i in scan.items if i.category in {'unknown','uv'}}=={row['category'] for row in categories if row['category'] in {'unknown','uv'}})
            yield .3
            self.shot('02-actual-storage-after-repainted')
            self.phase('normal Settings Cancel and protected baseline comparison')
            dialog._saved_values=dialog._values()
            self.queue_action('normal Settings Cancel',lambda:self.click(dialog.buttons.button(QDialogButtonBox.Cancel)))
            yield lambda:not dialog.isVisible();self.dialog=None
            after={path:small_file_fingerprint(path) for path in manifest['protected_before']}
            self.result['protected_after']=after
            self.check('actual index, settings, libraries and current project SHA/mtime unchanged',after==manifest['protected_before'])
            self.check('read-only audit invoked no real mutation gate',not service.rejected_actions,service.rejected_actions)
        def finish(self):
            if self.finished:return
            self.stop();application_settings_ui.ApplicationSettingsDialog.__init__=original_init
            self.result['provider_calls']=blank_project_audit._provider_calls
            self.result['blocked_external_connections']=list(blank_project_audit._blocked_external_connections)
            self.result['gui_shutdown']=True
            self.checkpoint()
            def shutdown():
                try:
                    modal=QApplication.activeModalWidget()
                    if modal is not None and modal is not self.dialog:modal.reject()
                    if self.dialog and self.dialog.isVisible():cancel_without_settings_save_prompt(self.dialog)
                    window.close()
                except Exception:self.result['shutdown_error']=traceback.format_exc();self.result['passed']=False
                finally:self.checkpoint();self.close_diagnostics();QApplication.instance().quit()
            QTimer.singleShot(0,shutdown)
    audit=Audit();window._real_storage_after_audit=audit
    def observed(dialog,*args,**kwargs):
        audit.progress('settings-init-enter',dict(parent=audit._widget(args[0]) if args else None,
            advanced_owner=audit._widget(kwargs.get('advanced_owner'))))
        original_init(dialog,*args,**kwargs);dialog.storage_panel.service=service
        policy=service.policy();dialog.storage_panel.enabled.setChecked(policy['enabled'])
        for key,(control,divisor) in dialog.storage_panel.policy_controls.items():control.setValue(policy[key]//divisor)
        dialog.storage_panel._last_receipt();dialog._saved_values=dialog._values();audit.dialog=dialog
        # Preserve enabled affordances for the real scan. No mutation or UV
        # subprocess can escape this read-only audit if input strays.
        for widget in (dialog.storage_panel.uv,dialog.storage_panel.selected,dialog.storage_panel.recommended,
                       dialog.storage_panel.adopt_button,dialog.storage_panel.save_media,dialog.storage_panel.relink_media):
            widget.clicked.disconnect();widget.clicked.connect(lambda checked=False:None)
        audit.progress('settings-init-return')
    application_settings_ui.ApplicationSettingsDialog.__init__=observed
    audit.progress('settings-observer-installed')
    audit.begin(audit.run())
