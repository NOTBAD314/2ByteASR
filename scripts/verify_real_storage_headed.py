"""Normal cold-start/settings audit against explicit real roots.

The default audit is read-only. Deletion requires the approved plan's exact SHA
and only the files and identities in that plan can reach the product service.
Other application settings and every startup write use the isolated QA profile.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--inventory',type=Path,required=True)
    parser.add_argument('--approved-plan',type=Path)
    parser.add_argument('--approved-sha256')
    parser.add_argument('--worker',action='store_true')
    args=parser.parse_args();output=args.output.resolve()
    if not output.is_relative_to(ROOT/'tmp'):raise ValueError('Audit output must be within repository tmp')
    if bool(args.approved_plan)!=bool(args.approved_sha256):raise ValueError('Plan and exact approval SHA must both be supplied')
    raw=args.inventory.read_bytes();inventory=json.loads(raw.decode('utf8'));roots=inventory['roots']
    approved={}
    if args.approved_plan:
        raw_plan=args.approved_plan.read_bytes()
        if hashlib.sha256(raw_plan).hexdigest()!=args.approved_sha256:raise ValueError('Approved plan SHA changed')
        plan=json.loads(raw_plan.decode('utf8'))
        if 'exact_items' in plan:
            if plan.get('schema_version')!=1 or Path(plan.get('user_data_root','')).resolve()!=Path(roots['user_data_root']).resolve():raise ValueError('Approved collection root differs from the explicit inventory')
            approved={i['path']:i for i in plan['exact_items'] if i.get('manual_cleanable') and i.get('rebuild')=='local' and i.get('category') not in {'uv','evidence','unknown'}}
            if len(approved)!=len(plan['exact_items']):raise ValueError('Approved collection includes a nonordinary or duplicate entry')
        else:
            if not plan.get('readonly') or not plan.get('index_unchanged'):raise ValueError('Approval must come from a read-only reviewed plan')
            approved={i['path']:i for i in plan['items'] if i.get('manual_cleanable')}
        if not approved:raise ValueError('Approved plan has no executable ordinary cache files')
    if not args.worker:
        if output.exists():raise ValueError('Fresh audit output required')
        output.mkdir(parents=True)
        os.environ['TWOBYTEASR_TEST_ROOT']=str(output)
        from twobyteasr.test_isolation import install
        install()
        from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,save_project
        seed=output/'input'/'seed.2byteproj';seed.parent.mkdir()
        save_project(SubtitleProject(media=StudioMedia(path='')),seed)
        env=os.environ.copy();env.update(TWOBYTEASR_TEST_ROOT=str(output),
            TWOBYTEASR_ACCEPTANCE_DIR=str(output),TWOBYTEASR_ACCEPTANCE_SCENARIO='storage-settings',
            TWOBYTEASR_STARTUP_PROJECT=str(seed),TWOBYTEASR_INVOKER_CWD=str(ROOT),
            TWOBYTEASR_STARTUP_TRACE=str(output/'startup-trace.jsonl'),
            TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',
            HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONUTF8='1')
        for key in ('QT_SCALE_FACTOR','QT_FONT_DPI','QT_ENABLE_HIGHDPI_SCALING','QT_SCALE_FACTOR_ROUNDING_POLICY'):env.pop(key,None)
        argv=[sys.executable,'-B',str(Path(__file__).resolve()),'--worker','--output',str(output),'--inventory',str(args.inventory.resolve())]
        if args.approved_plan:argv+=['--approved-plan',str(args.approved_plan.resolve()),'--approved-sha256',args.approved_sha256]
        from isolated_windows_desktop import run_on_desktop
        code=run_on_desktop(argv,cwd=ROOT,env=env,output=output/'process',timeout=420)
        result_path=output/'result.json'
        result=json.loads(result_path.read_text('utf8')) if result_path.is_file() else dict(passed=False,error='No GUI receipt')
        result['process_exit']=code;result['passed']=bool(result.get('passed') and code==0)
        result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        print(json.dumps(dict(passed=result['passed'],output=str(output),checks=len(result.get('checks',[]))),ensure_ascii=False))
        return 0 if result['passed'] else 1

    # Install the configuration boundary before any Qt/product UI imports.
    import faulthandler
    stack_log=(output/'thread-stacks.log').open('w',encoding='utf8')
    faulthandler.dump_traceback_later(30,repeat=True,file=stack_log)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.runtime_paths import RuntimePaths
    keys=('install_root','user_data_root','model_root','cache_root','project_root','config_root','log_root','renderer_asset_root','temp_root')
    actual_paths=RuntimePaths(*(Path(roots[k]) for k in keys))
    from twobyteasr.storage.storage_service import StorageService
    from twobyteasr.acceptance import storage_settings_audit
    from twobyteasr.app import application_settings_ui
    from twobyteasr.storage.storage_ui import app_busy,loaded_media_graph
    from twobyteasr.acceptance.blank_project_audit import _capture
    from PySide6.QtCore import QObject,QTimer,Qt
    from PySide6.QtWidgets import QApplication,QMessageBox,QPushButton,QLabel
    from PySide6.QtTest import QTest

    class GuardedService(StorageService):
        def __init__(self,owner):
            super().__init__(actual_paths,busy=lambda:app_busy(owner),manual_busy=lambda:app_busy(owner,manual=True),media_references=lambda:loaded_media_graph(owner))
            self.approved=bool(approved);self.cleaning=False
        def _db(self):
            if not self.approved or not self.cleaning:raise PermissionError('Real-data audit is read-only outside the approved cleanup transaction')
            return super()._db()
        def save_policy(self,policy):
            raise PermissionError('Real-data audit never changes storage policy')
        def write_state_json(self,name,payload):
            if not self.approved or not self.cleaning:raise PermissionError('Real-data audit does not write receipts before approved cleanup')
            return super().write_state_json(name,payload)
        def manual_items(self,scan,categories=None):
            items=super().manual_items(scan,categories)
            if not self.approved:return items
            return [i for i in items if i.path in approved and tuple(i.identity)==tuple(approved[i.path]['identity'])]
        def clean(self,items,*a,**kw):
            items=list(items)
            if not self.approved:raise PermissionError('No human-approved exact cache plan')
            if any(i.path not in approved or tuple(i.identity)!=tuple(approved[i.path]['identity']) for i in items):raise PermissionError('File or identity is outside the approved plan')
            self.cleaning=True
            try:return super().clean(items,*a,**kw)
            finally:self.cleaning=False

    def start(window,ignored_output):
        original=application_settings_ui.ApplicationSettingsDialog.__init__
        class Audit(QObject):
            def __init__(self):
                super().__init__(window);self.dialog=None;self.waiting=0;self.in_tick=False;self.deadline=time.monotonic()+300
                self.result=dict(passed=False,readonly=not bool(approved),checks=[],screenshots=[],provider_calls=0,
                    inventory_sha256=hashlib.sha256(raw).hexdigest(),approved_plan_sha256=args.approved_sha256,
                    actual_user_data_root=str(actual_paths.user_data_root))
                db=actual_paths.user_data_root/'storage/cache.sqlite3'
                self.db=db;self.before=(db.stat().st_mtime_ns,hashlib.sha256(db.read_bytes()).hexdigest()) if db.exists() else None
                self.steps=self.run();self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(30)
                QTimer.singleShot(400,self.open_settings)
            def open_settings(self):
                window._return_to_settings();QTest.mouseClick(window.app_settings_button,Qt.LeftButton)
            def check(self,name,value,detail=None):
                self.result['checks'].append(dict(name=name,passed=bool(value),detail=detail))
                if not value:raise AssertionError(name+': '+str(detail))
            def tick(self):
                if self.in_tick:return
                self.in_tick=True
                try:
                    now=time.monotonic()
                    if callable(self.waiting):
                        if not self.waiting():
                            if now>self.deadline:raise TimeoutError('Real storage GUI condition')
                            return
                    elif now<self.waiting:return
                    step=next(self.steps);self.waiting=step if callable(step) else time.monotonic()+float(step)
                    self.deadline=time.monotonic()+300
                except StopIteration:self.result['passed']=True;self.finish()
                except Exception:self.result['error']=traceback.format_exc();self.finish()
                finally:self.in_tick=False
            def shot(self,name):
                _capture(window,output/(name+'-whole-window.png'));_capture(self.dialog,output/(name+'.png'))
                self.result['screenshots'] += [name+'-whole-window.png',name+'.png']
            def confirm(self):
                try:
                    modal=QApplication.activeModalWidget()
                    if isinstance(modal,QMessageBox):
                        self.result['confirmation']=modal.text();QTest.mouseClick(modal.button(QMessageBox.Yes),Qt.LeftButton);return
                    for host in QApplication.topLevelWidgets():
                        for button in host.findChildren(QPushButton):
                            if button.isVisible() and button.text() in {'是','Yes','是(&Y)'}:
                                self.result['confirmation']=' / '.join(label.text() for label in host.findChildren(QLabel) if label.isVisible())
                                QTest.mouseClick(button,Qt.LeftButton);return
                    raise RuntimeError('Actual cleanup confirmation not found')
                except Exception:
                    self.result['error']=traceback.format_exc()
                    modal=QApplication.activeModalWidget()
                    if modal is not None:modal.reject()
                    QTimer.singleShot(0,self.finish)
            def run(self):
                yield lambda:self.dialog is not None and self.dialog.isVisible()
                dialog=self.dialog;panel=dialog.storage_panel
                rect=dialog.navigation.visualItemRect(dialog.navigation.item(2));QTest.mouseClick(dialog.navigation.viewport(),Qt.LeftButton,pos=rect.center());yield .1
                self.check('normal settings storage navigation visible',panel.isVisible())
                self.check('explicit actual roots preserved through test isolation',panel.service.paths==actual_paths)
                self.shot('01-real-storage-unscanned')
                QTest.mouseClick(panel.scan_button,Qt.LeftButton)
                self.check('scan starts asynchronously',panel.cancel_button.isEnabled())
                yield lambda:panel.worker is None and panel.scan_result is not None
                scan=panel.scan_result
                self.check('real legacy inventory is complete',scan.complete,scan.errors)
                self.check('real historical candidates are nonzero',scan.manual_cleanable_bytes>1024**3,scan.manual_cleanable_bytes)
                self.check('unknown and official maintenance shown separately','归属未确认' in panel.summary.text() and '官方工具范围' in panel.summary.text())
                groups=[]
                for n in range(panel.tree.topLevelItemCount()):
                    row=panel.tree.topLevelItem(n);category=row.data(0,Qt.UserRole)
                    groups.append(dict(category=category,size=row.text(1),status=row.text(2)))
                    if category=='unknown':
                        row.setCheckState(0,Qt.Checked)
                        self.check('zero executable ordinary scope has no enabled cleanup',not panel.selected.isEnabled())
                        row.setCheckState(0,Qt.Unchecked)
                    if category=='uv':self.check('uv amount unknown remains an explicit tool action','完成后统计' in row.text(2) and panel.uv.isEnabled())
                self.result['categories']=groups;self.result['total_logical_bytes']=scan.total_bytes;self.result['manual_candidate_bytes']=scan.manual_cleanable_bytes
                self.shot('02-real-storage-scanned')
                if approved:
                    current={i.path:i for i in scan.items}
                    self.result['approved_items']=len(approved)
                    self.result['approved_changed_or_missing']=[dict(path=p,reason='已批准身份变化／文件已不存在；保留或不计算释放')
                        for p,v in approved.items() if p not in current or tuple(current[p].identity)!=tuple(v['identity'])]
                    chosen={approved[i.path]['category'] for i in panel.service.manual_items(scan)}
                    for n in range(panel.tree.topLevelItemCount()):
                        row=panel.tree.topLevelItem(n)
                        if row.data(0,Qt.UserRole) in chosen:row.setCheckState(0,Qt.Checked)
                    self.check('approved exact scope enables normal manual button',panel.selected.isEnabled())
                    self.shot('03-approved-real-scope')
                    QTimer.singleShot(150,self.confirm);QTest.mouseClick(panel.selected,Qt.LeftButton)
                    yield lambda:panel.worker is None and panel.scan_result is not None
                    receipt=json.loads((panel.service.state_root/'last-cleanup.json').read_text('utf8'))
                    self.result['cleanup_receipt']=receipt
                    self.check('normal cleanup receipt includes actual logical and observed volume delta',receipt['logical_removed_bytes']>=0 and 'observed_free_delta' in receipt)
                    self.check('after cleanup inventory automatically refreshed',panel.scan_result.complete)
                    self.result['after_logical_bytes']=panel.scan_result.total_bytes
                    self.shot('04-real-storage-cleaned')
                else:
                    after=(self.db.stat().st_mtime_ns,hashlib.sha256(self.db.read_bytes()).hexdigest()) if self.db.exists() else None
                    self.check('real storage index remains byte-identical and untouched',after==self.before)
                dialog._saved_values=dialog._values();dialog.reject();yield .1
            def finish(self):
                self.timer.stop();application_settings_ui.ApplicationSettingsDialog.__init__=original
                if self.dialog and self.dialog.isVisible():self.dialog._saved_values=self.dialog._values();self.dialog.reject()
                from twobyteasr.acceptance import blank_project_audit
                self.result['provider_calls']=blank_project_audit._provider_calls
                self.result['blocked_external_connections']=list(blank_project_audit._blocked_external_connections)
                (output/'result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),'utf8')
                window.close();QTimer.singleShot(100,QApplication.instance().quit)
        audit=Audit();window._real_storage_audit=audit
        def observed(dialog,*a,**kw):
            original(dialog,*a,**kw);dialog.storage_panel.service=GuardedService(window);dialog.storage_panel._last_receipt();audit.dialog=dialog
            # UV has a separate human approval and cannot share ordinary-cache
            # approval. Keep its real visual affordance, block execution here.
            dialog.storage_panel.uv.clicked.disconnect()
            dialog.storage_panel.uv.clicked.connect(lambda:dialog.storage_panel.summary.setText('UV工具尚未取得此审计的独立授权；未执行'))
        application_settings_ui.ApplicationSettingsDialog.__init__=observed
    storage_settings_audit.start=start
    sys.argv=[str(ROOT/'quick_start.py')]
    import quick_start
    try:return quick_start.main()
    finally:faulthandler.cancel_dump_traceback_later();stack_log.close()


if __name__=='__main__':raise SystemExit(main())
