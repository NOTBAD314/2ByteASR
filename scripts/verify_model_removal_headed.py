"""Headed permanent-uninstall acceptance using owned fixtures only under tmp."""
from __future__ import annotations
import ctypes
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
import subprocess

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--language', choices=('zh','en','ja'), default='zh')
parser.add_argument('--out', type=Path)
args=parser.parse_args()
OUT=(args.out or (ROOT/'tmp'/'model-removal-headed-20261004')).absolute()
OUT.mkdir(parents=True,exist_ok=True)
PROFILE=OUT/('run-'+str(time.time_ns()))
PROFILE.mkdir()
MODELS=PROFILE/'models';MODELS.mkdir()
original_contract=json.loads((ROOT/'dependencies.lock.json').read_text('utf8'))
ACTUAL_UV=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'2ByteASR/runtimes/tools'/('uv-'+original_contract['managed_bootstrap']['uv_version'])/'uv.exe'
for key,value in {'TWOBYTEASR_TEST_ROOT':str(PROFILE),'TWOBYTEASR_USER_DATA_ROOT':str(PROFILE/'local'),
                  'TWOBYTEASR_MODEL_ROOT':str(MODELS),'PYTHONIOENCODING':'utf-8'}.items():os.environ[key]=value
os.environ.pop('QT_QPA_PLATFORM',None)
sys.path.insert(0,str(ROOT))

from PySide6.QtCore import QSettings,QTimer,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QMainWindow,QMessageBox,QScrollArea
from twobyteasr import model_removal
from twobyteasr.model_workshop import ModelWorkshopPage
from twobyteasr.runtime_paths import MODEL_ROOT_ENV,USER_DATA_ENV,reset_runtime_paths

os.environ[MODEL_ROOT_ENV]=str(MODELS);os.environ[USER_DATA_ENV]=str(PROFILE/'local');reset_runtime_paths()
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat,QSettings.UserScope,str(PROFILE/'qsettings'))
lock=json.loads((ROOT/'dependencies.lock.json').read_text('utf8'))
names=['model.pt','config.json']+[f'owned-fixture-{i:04d}.bin' for i in range(64)]
spec=dict(lock['models']['sensevoice']);spec.update(required_files=names,sha256={})
(PROFILE/'dependencies.lock.json').write_text(json.dumps({'models':{'sensevoice':spec},'managed_bootstrap':original_contract['managed_bootstrap']}),'utf8')
folder=MODELS/Path(spec['path']).name;folder.mkdir()
for name in names:(folder/name).write_bytes(b'owned fixture\n'*1024)
(PROFILE/'original.mp4').write_bytes(b'untouched source')

app=QApplication([])
from twobyteasr.i18n import save_language, tr, current_language
save_language(args.language)
from twobyteasr.theme_manager import apply_application_theme
apply_application_theme(app)
window=QMainWindow();window.setWindowTitle('2ByteASR 模型永久删除实测 · tmp 归属沙箱')
window._run_in_progress=False;window.worker=None
page=ModelWorkshopPage(PROFILE,{'models':{'primary_asr_backend':'moss','firered_asr_backend':'off','qwen_asr_backend':'off','speaker_source':'single'}},window)
window.setCentralWidget(page);window.resize(1450,900);window.show()
report={'profile':str(PROFILE),'actual_ui':True,'language':current_language(),'checks':[],'screenshots':[],'results':[]}
heartbeat=[0];ticks=QTimer();ticks.timeout.connect(lambda:heartbeat.__setitem__(0,heartbeat[0]+1));ticks.start(1)
real_execute=model_removal.execute_removal;thread_checks=[]
fixture_roots=[folder]
def observed_execute(*a,**kw):
    begin=heartbeat[0];worker_thread=threading.get_ident()
    result=real_execute(*a,**kw)
    thread_checks.append({'worker_thread':worker_thread,'gui_thread':gui_thread,'ui_ticks_during_delete':heartbeat[0]-begin})
    return result
model_removal.execute_removal=observed_execute
gui_thread=threading.get_ident();messages=[];results=[];external_choice=['unlink']
page.removal_finished.connect(results.append)

def check(name,passed):
    report['checks'].append({'name':name,'passed':bool(passed)})
    if not passed:raise AssertionError(name)

def shot(name):
    path=PROFILE/(name+'.png');window.grab().save(str(path));report['screenshots'].append(str(path))

def pump_until(predicate,timeout=90):
    end=time.monotonic()+timeout
    while not predicate():
        if time.monotonic()>end:raise TimeoutError('headed fixture deadline')
        QTest.qWait(25)

def modal_guard():
    modal=QApplication.activeModalWidget()
    if not isinstance(modal,QMessageBox):return
    text=modal.text();messages.append(text)
    if modal.standardButtons() & QMessageBox.Yes:
        title=modal.windowTitle()
        check('confirmation contains actual isolated path',any(str(p) in text for p in fixture_roots))
        if title==tr('解除外部模型关联'):
            check('external association defaults to detach and zero release',modal.button(QMessageBox.Yes).text()==tr('仅解除关联') and '0 B' in text)
            if external_choice[0]=='delete':
                destructive=next(b for b in modal.buttons() if b.text()==tr('永久删除外部模型文件…'))
                modal.grab().save(str(PROFILE/('external-confirmation-'+str(len(messages))+'.png')))
                QTest.mouseClick(destructive,Qt.LeftButton);return
        elif title==tr('永久删除外部模型文件'):
            check('external permanent delete requires second explicit confirmation',modal.button(QMessageBox.Yes).text()==tr('永久删除外部模型文件'))
        elif title==tr('永久删除模型文件'):
            check('managed permanent delete explicit wording',modal.button(QMessageBox.Yes).text()==tr('永久删除模型文件') and '共享运行环境' in text)
        elif title==tr('永久清理历史模型残留'):
            check('historical cleanup explicit wording',modal.button(QMessageBox.Yes).text()==tr('永久删除'))
        modal.grab().save(str(PROFILE/('confirmation-'+str(len(messages))+'.png')))
        QTest.mouseClick(modal.button(QMessageBox.Yes),Qt.LeftButton)
    else:
        check('completion provides a normal acknowledgement',modal.button(QMessageBox.Ok) is not None)
        modal.grab().save(str(PROFILE/('completion-'+str(len(messages))+'.png')))
        modal.accept()
guard=QTimer();guard.timeout.connect(modal_guard);guard.start(40)

def click_delete():
    page._view_model('sensevoice');QApplication.processEvents()
    check('real uninstall control enabled',page.detail_uninstall.isEnabled())
    # A normal user scrolls the detail pane to its management actions, notably
    # after a partial failure introduces extra (bounded) diagnostic text.
    scroller=page.detail_uninstall.parentWidget()
    while scroller is not None and not isinstance(scroller,QScrollArea):scroller=scroller.parentWidget()
    if scroller is not None:scroller.ensureWidgetVisible(page.detail_uninstall,0,12)
    QTest.qWait(50)
    point=page.detail_uninstall.mapTo(window,page.detail_uninstall.rect().center())
    check('real uninstall control visible within window',window.rect().contains(point) and page.detail_uninstall.isVisible())
    before=len(results)
    QTest.mouseClick(page.detail_uninstall,Qt.LeftButton)
    pump_until(lambda:len(results)>before and not page._removing)
    QApplication.processEvents();QTest.qWait(100)
    result=results[-1][1];check('production deletion result delivered',result is not None)
    report['results'].append({'removed':len(result.removed),'failures':result.failures,
                             'logical_bytes':result.logical_bytes,'exclusive_bytes':result.exclusive_bytes,
                             'disk_free_delta':result.disk_free_delta,'retained':result.retained})
    report['results'][-1]['detached']=result.detached
    return result

handle=None
try:
    QTest.qWait(700)
    check('independent speaker tab absent',all(b.property('role')!='speaker' for b in page.tab_group.buttons()))
    check('retired model entries absent',not {'nemotron','qwen_api','qwen31_flash','qwen_audio_asr_flash','qwen_audio_filetrans'} & set(page._cards))
    from twobyteasr.ui import ASR_API_PRESETS
    check('cloud Qwen presets contain only latest Filetrans',
          {key for key,value in ASR_API_PRESETS.items() if str(value.get('model','')).startswith('qwen')} == {'qwen31_filetrans','qwen_cloud_filetrans'}
          and 'dashscope' not in ASR_API_PRESETS)
    page.focus_primary_backend('api');QApplication.processEvents()
    check('setup API navigation focuses current Filetrans card',page.browser_role=='api' and page.detail_model_key=='qwen31_filetrans')
    check('Filetrans current-provider summary uses localized preset label',tr(ASR_API_PRESETS['qwen31_filetrans']['label']) in page.role_subtitle.text())
    configured=[];page.api_configure_requested.connect(configured.append)
    check('Filetrans configuration button visible',page.detail_configure.isVisibleTo(page))
    QTest.mouseClick(page.detail_configure,Qt.LeftButton)
    check('normal Filetrans configure control emits current provider',configured==['qwen31_filetrans'])
    for key in ('qwen31_filetrans', 'mai_latest'):
        card=page._cards[key];page._view_model(key);QApplication.processEvents()
        check(key+' card and detail titles localized',card.title_label.text()==tr(card.model.name) and page.detail_title.text()==tr(card.model.name))
        check(key+' scene localized',page.detail_description.text()==tr(card.model.summary))
        if args.language != 'zh':
            check(key+' new title has translated copy',page.detail_title.text()!=card.model.name)
            check(key+' online storage copy has no untranslated source', '本地磁盘占用' not in page.install_size_card.text() and '无需本地下载' not in page.install_size_card.text())
        shot(key+'-'+args.language)
    button=next(b for b in page.tab_group.buttons() if b.property('role')=='review')
    QTest.mouseClick(button,Qt.LeftButton);page._view_model('sensevoice');QTest.qWait(150);shot('before')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
    kernel.CreateFileW.restype=ctypes.c_void_p;kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.CreateFileW(str(folder/'model.pt'),0x80000000,1,None,3,0,None)
    check('real Windows fixture file held without delete sharing',handle!=ctypes.c_void_p(-1).value)
    first=click_delete()
    check('partial failure keeps occupied file and reports it',len(first.failures)==1 and (folder/'model.pt').exists())
    check('remaining partial model can still be uninstalled',page.detail_uninstall.isEnabled())
    shot('partial-failure')
    kernel.CloseHandle(handle);handle=None
    second=click_delete();check('retry permanently removes final occupied file',second.completed and not folder.exists())
    check('source and cloud accounts not part of deletion', (PROFILE/'original.mp4').read_bytes()==b'untouched source')
    check('no trash or hidden backup created',not (PROFILE/'.bin').exists() and not (PROFILE/'model_trash').exists())
    check('backend runs outside GUI thread',all(x['worker_thread']!=gui_thread for x in thread_checks))
    check('GUI events continue during actual permanent deletion',thread_checks[0]['ui_ticks_during_delete']>0)
    check('model registry refreshes actual missing state','sensevoice' not in page._installed)
    shot('permanent-complete')
    from twobyteasr.model_storage import ModelStorageDialog
    trash=PROFILE/'.bin'/folder.name;trash.mkdir(parents=True)
    fixture_roots.append(trash)
    for name in ('model.pt','config.json'):(trash/name).write_bytes(b'owned historical model fixture')
    (trash/'unknown.bin').write_bytes(b'unknown file kept')
    unknown=PROFILE/'.bin'/'unrelated';unknown.mkdir();(unknown/'weights.bin').write_bytes(b'not managed')
    storage=ModelStorageDialog(PROFILE,[c.model for c in page._cards.values()],lambda:set(),lambda *a:None,lambda *a:None,parent=window)
    storage.show();QTest.qWait(250)
    check('localized real historical-cleanup control',storage.history_cleanup_button.text()==tr('永久清理历史模型残留'))
    QTest.mouseClick(storage.history_cleanup_button,Qt.LeftButton)
    pump_until(lambda:storage._history_worker is None and not (trash/'model.pt').exists())
    QTest.qWait(100)
    check('historical registered files permanently removed',not (trash/'model.pt').exists() and not (trash/'config.json').exists())
    check('historical unknown files and unrelated bin directory preserved',(trash/'unknown.bin').read_bytes()==b'unknown file kept' and (unknown/'weights.bin').read_bytes()==b'not managed')
    storage.grab().save(str(PROFILE/'historical-cleanup-complete.png'))
    from twobyteasr.model_download_cache import write_transaction
    stage=MODELS/'.downloads/sensevoice/hf_official/fixture';stage.mkdir(parents=True)
    (stage/'model.pt.part.owned.000').write_bytes(b'published staging duplicate')
    (stage/'user-note.mp4').write_bytes(b'unknown asset retained')
    write_transaction(stage,model_key='sensevoice',destination=folder,files=['model.pt'],state='published')
    fixture_roots.append(stage)
    QTest.mouseClick(storage.residual_button,Qt.LeftButton)
    pump_until(lambda:storage._history_worker is None and not (stage/'model.pt.part.owned.000').exists())
    check('normal residual control removes receipted duplicate only',(stage/'user-note.mp4').read_bytes()==b'unknown asset retained')
    storage.grab().save(str(PROFILE/'download-residual-complete.png'))

    # Normal unused-runtime control with actual offline uv health checks. The
    # tool's location alone is substituted to avoid duplicating its large EXE.
    from twobyteasr import runtime_download_cache,model_runtime_cleanup
    from twobyteasr.runtime_paths import user_data_root
    managed=user_data_root()/'runtimes';managed.mkdir(parents=True,exist_ok=True)
    current=managed/'main/0123456789abcdef';old=managed/'main/fedcba9876543210'
    check('local pinned uv available without acquisition',ACTUAL_UV.is_file())
    runtime_calls=[]
    def offline_uv(argv,cancel):
        runtime_calls.append([str(x) for x in argv])
        completed=subprocess.run([str(ACTUAL_UV),*map(str,argv[1:])],stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf8',errors='replace',timeout=45,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if completed.returncode:raise RuntimeError(completed.stdout)
        return completed.stdout.strip()
    runtime_download_cache._run=offline_uv
    for environment in (current,old):
        offline_uv([ACTUAL_UV,'--no-config','--offline','--cache-dir',managed/'download-cache','venv',
                    '--python',sys._base_executable,'--no-python-downloads',environment],lambda:False)
        (environment/'managed-runtime.json').write_text(json.dumps({'role':'main','models':['fixture']}),'utf8')
        model_runtime_cleanup.write_runtime_inventory(environment)
    (managed/'registry.json').write_text(json.dumps({'runtimes':{'main':{'python_executable':str(current/'Scripts/python.exe')}}}),'utf8')
    uvstub=managed/'tools'/('uv-'+original_contract['managed_bootstrap']['uv_version'])/'uv.exe'
    uvstub.parent.mkdir(parents=True);uvstub.write_bytes(b'only executable location substituted')
    fixture_roots.extend([current,old])
    QTest.mouseClick(storage.runtime_cleanup_button,Qt.LeftButton)
    pump_until(lambda:storage._history_worker is None and not old.exists())
    check('normal runtime control removes unused inventoried environment after offline health',not old.exists() and (current/'Scripts/python.exe').exists())
    check('runtime cleanup never removes model weights or original user output',(PROFILE/'original.mp4').exists())
    report['runtime_commands']=runtime_calls
    storage.grab().save(str(PROFILE/'unused-runtime-complete.png'))
    storage.close();app.processEvents()

    # Reconfigure only this owned fixture to simulate a manually linked model.
    external_parent=PROFILE/'user-associated';external_parent.mkdir()
    external=external_parent/folder.name;external.mkdir()
    for name in names:(external/name).write_bytes(b'external fixture')
    fixture_roots.append(external)
    os.environ[MODEL_ROOT_ENV]=str(external_parent);reset_runtime_paths();page.refresh()
    detached=click_delete()
    check('normal external default action leaves every file intact',detached.detached==[str(external)] and all((external/name).exists() for name in names))
    check('detached external model remains unavailable after registry refresh','sensevoice' not in page._installed)
    shot('external-detached')
    from twobyteasr.model_associations import restore_model_association
    restore_model_association(external);page.refresh();external_choice[0]='delete'
    removed=click_delete()
    check('normal external permanent action has separate confirmation and real file deletion',removed.completed and not external.exists())
    shot('external-permanent-complete')
    report['status']='PASS'
except Exception as exc:
    report.update(status='FAIL',error=str(exc));shot('failure')
finally:
    if handle is not None:kernel.CloseHandle(handle)
    report['threads']=thread_checks;report['messages']=messages
    (PROFILE/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'status':report['status'],'result':str(PROFILE/'result.json'),'checks':len(report['checks'])},ensure_ascii=False))
    guard.stop();ticks.stop();window.close();app.processEvents()
sys.exit(0 if report['status']=='PASS' else 1)
