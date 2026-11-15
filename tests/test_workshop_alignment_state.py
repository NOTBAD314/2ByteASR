import copy,json,sys
from pathlib import Path
from types import SimpleNamespace as NS
import pytest

from twobyteasr.recognition.qwen_family import normalize_models,head_requested,canonical_backend
from twobyteasr.recognition.alignment_backend import selected_backend
from twobyteasr.local_models import model_workshop as w
from twobyteasr.local_models import alignment_readiness as readiness


@pytest.mark.parametrize('old,expected',[('qwen_aligner','qwen_ultra_aligner'),('qwen_ultra_aligner','qwen_ultra_aligner'),('qwen_ultra_head','qwen_ultra_head')])
def test_one_family_preserves_explicit_head_and_frozen_tasks(old,expected):
    settings={'models':{'firered_asr_backend':old,'qwen_alignment_profile':'ultra-v5'}}
    frozen=copy.deepcopy(settings);normalize_models(settings['models'])
    assert canonical_backend(old)=='qwen_aligner'
    assert selected_backend(settings)==selected_backend(frozen)==expected
    settings['models']['qwen_alignment_head']=not head_requested(settings)
    assert selected_backend(frozen)==expected


def test_head_installation_is_not_an_enable_switch_and_other_choices_stay():
    for value in ['local','mfa_aligner','off']:
        models={'firered_asr_backend':value,'qwen_alignment_profile':'ultra-v5'}
        before=copy.deepcopy(models);normalize_models(models)
        assert models==before and not head_requested({'models':models})


def test_catalog_and_all_common_selectors_have_one_ultra():
    from twobyteasr.app.ui import TIMELINE_MODEL_CHOICES
    assert [m.key for m in w.MODELS if m.key.startswith('qwen_') and m.role=='timeline']==['qwen_aligner']
    assert [v for _,v,_ in TIMELINE_MODEL_CHOICES if v in {'qwen_aligner','qwen_ultra_aligner','qwen_ultra_head'}]==['qwen_aligner']
    assert w.model_for_backend('timeline','qwen_ultra_head').key=='qwen_aligner'
    assert w.model_for_backend('timeline','mfa_aligner').key=='mfa_aligner'


@pytest.fixture
def fake(monkeypatch,tmp_path):
    from twobyteasr.recognition import alignment_backend,asr,mfa_aligner
    exe=tmp_path/'python.exe';exe.write_bytes(b'python')
    directory=tmp_path/'ultra';directory.mkdir();(directory/'weight').write_bytes(b'weights')
    stat=readiness.file_identity(directory,['weight'])
    receipts={'qwen_ultra_aligner':{'status':'PASS','inference_verified':True,'ultra_directory':str(directory.resolve()),'ultra_file_stats':stat}}
    versions={'qwen-asr':'0.0.6','torch':'2','transformers':'4','numpy':'2','nagisa':'0.2.11','safetensors':'0.8'}
    monkeypatch.setattr(readiness,'_read_receipt',lambda key:receipts.get(key,{}))
    monkeypatch.setattr(readiness,'runtime_identity',lambda *a,**k:{'python':str(exe),'executable':readiness._stamp(exe),'packages':versions})
    monkeypatch.setattr(readiness,'runtime_matches',lambda *a:True)
    monkeypatch.setattr(alignment_backend,'readiness_matches',lambda key,p:bool(p.get('inference_verified')))
    monkeypatch.setattr(alignment_backend,'profile',lambda key:{'files':{'weight':'hash'}})
    monkeypatch.setattr(alignment_backend,'model_directory',lambda *a:str(directory))
    monkeypatch.setattr(asr,'_main_worker_python',lambda:str(exe))
    monkeypatch.setattr(mfa_aligner,'runtime_python',lambda:str(exe))
    records={key:NS(health=NS(value='INSTALLED')) for key in ['qwen_ultra_aligner','qwen_ultra_head','mfa_aligner','mfa_aligner_ja']}
    registry=NS(record=lambda key:records.get(key),install_root=tmp_path)
    return NS(exe=exe,directory=directory,receipts=receipts,records=records,registry=registry,versions=versions)


def test_real_base_proof_does_not_depend_on_head(fake):
    fake.records.pop('qwen_ultra_head')
    states=readiness.inspect(fake.registry)
    assert states['qwen_aligner']['ready']
    assert not states['qwen_ultra_head']['ready']


def test_only_head_cannot_imply_base_ready(fake):
    fake.records.pop('qwen_ultra_aligner')
    states=readiness.inspect(fake.registry)
    assert states['qwen_aligner']['state']=='missing' and not states['qwen_ultra_head']['ready']


@pytest.mark.parametrize('health',['PARTIAL','CORRUPT','UNREADABLE'])
def test_incomplete_or_damaged_files_cannot_be_selected(fake,health):
    fake.records['qwen_ultra_aligner'].health.value=health
    assert not readiness.inspect(fake.registry)['qwen_aligner']['ready']


def test_environment_missing_is_not_unknown_integration(fake,monkeypatch):
    from twobyteasr.recognition import asr
    monkeypatch.setattr(asr,'_main_worker_python',lambda:None)
    assert readiness.inspect(fake.registry)['qwen_aligner']['state']=='runtime_missing'


def test_missing_runtime_package_requires_configuration(fake):
    fake.versions.pop('qwen-asr')
    assert readiness.inspect(fake.registry)['qwen_aligner']['state']=='runtime_missing'


def test_changed_files_require_verification_not_download(fake):
    (fake.directory/'weight').write_bytes(b'new weights')
    state=readiness.inspect(fake.registry)['qwen_aligner']
    assert state['state']=='inference_pending' and state['files_ready']


def test_explicit_failure_keeps_its_reason(fake):
    fake.receipts['qwen_ultra_aligner']={'status':'FAIL','error':'RuntimeError: adapter failed'}
    state=readiness.inspect(fake.registry)['qwen_aligner']
    assert state['state']=='load_failed' and 'adapter failed' in state['reason']


def test_mfa_is_independent_of_main_and_uses_own_identity(fake,monkeypatch):
    from twobyteasr.recognition import asr
    monkeypatch.setattr(asr,'_main_worker_python',lambda:None)
    monkeypatch.setattr(readiness,'validation_identity',lambda *a:{'own':'MFA'})
    fake.receipts['mfa_aligner']={'status':'PASS','inference_verified':True,'availability_identity':{'own':'MFA'}}
    states=readiness.inspect(fake.registry)
    assert states['mfa_aligner']['ready'] and not states['qwen_aligner']['ready']


def test_mfa_old_unspecified_proof_is_not_ultra_success(fake,monkeypatch):
    monkeypatch.setattr(readiness,'validation_identity',lambda *a:{'own':'MFA'})
    fake.receipts['mfa_aligner']={'status':'PASS','inference_verified':True}
    assert readiness.inspect(fake.registry)['mfa_aligner']['state']=='inference_pending'


@pytest.mark.parametrize('state,label,enabled',[('runtime_missing','配置环境',True),('inference_pending','验证可用性',True),('checking','检查独立环境…',False),('installed','使用',True),('partial','补齐缺失文件',True),('unsupported_role','此用途不支持',False)])
def test_action_matches_actual_state(state,label,enabled):
    model=next(m for m in w.MODELS if m.key=='qwen_aligner')
    page=NS(_removing=set())
    text,allowed=w.ModelWorkshopPage._action_text(page,model,state)
    assert text==label and allowed is enabled


def test_tab_change_recomputes_actions_instead_of_only_filtering():
    called=[]
    page=NS(browser_role='primary',_refresh_role_subtitle=lambda:None,tab_group=NS(buttons=lambda:[]),_cards={},detail_model_key='none',_registry='existing',refresh=lambda **kw:called.append(kw))
    w.ModelWorkshopPage._set_role(page,'timeline')
    assert called==[{'registry':'existing','check_status':False}]


@pytest.mark.parametrize('language',['zh','en','zh-Hant'])
def test_late_materialization_and_language_replay_do_not_restore_placeholder(language):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.i18n import apply_ui_language
    app=QApplication.instance() or QApplication([])
    model=next(m for m in w.MODELS if m.key=='qwen_aligner')
    card=w._DeferredModelCard(model);card.set_action_state('使用',True);child=card.materialize()
    apply_ui_language(child,language)
    assert child.action.text()==w.translate('使用',language) and child.action.isEnabled()
    card.set_action_state('验证可用性',True);apply_ui_language(child,language)
    assert child.action.text()==w.translate('验证可用性',language)
    assert not w._metric_evidence(model,'accuracy','timeline')['available']
    card.deleteLater();app.processEvents()


def test_cancel_or_timeout_selection_has_a_terminal_and_no_late_commit():
    calls=[]
    page=NS(_selection_pending={'qwen_aligner':(9,'token')},_selection_failures={},_registry=None,refresh=lambda **kw:calls.append(kw))
    w.ModelWorkshopPage._selection_timeout(page,'qwen_aligner',9)
    assert not page._selection_pending and 'qwen_aligner' in page._selection_failures
    w.ModelWorkshopPage._selection_check_done(page,('qwen_aligner',9,'token','timeline','installed',None))
    assert len(calls)==1


@pytest.mark.parametrize('outcome',['success','failure','cancelled','timeout'])
def test_task_terminal_is_scoped_and_never_leaves_unrelated_model_busy(outcome):
    from twobyteasr.local_models.model_state_events import task_transition,active_task
    owner='test-operation-'+outcome
    task_transition(owner,['mfa_aligner'],'loading',active=True,operation='verify')
    assert active_task('mfa_aligner') and not active_task('qwen_ultra_aligner')
    task_transition(owner,['mfa_aligner'],'terminal',active=False,operation='verify',outcome=outcome)
    assert active_task('mfa_aligner') is None


def test_preparation_timeout_terminates_real_owner_only():
    from PySide6.QtCore import QProcess
    killed=[]
    owner=NS(process=NS(state=lambda:QProcess.ProcessState.Running,kill=lambda:killed.append(1)),_operation_timeout=False)
    w.ModelDownloadDialog._operation_timed_out(owner)
    assert owner._operation_timeout and killed==[1]


def test_readiness_only_change_refreshes_home_and_settings_without_file_change():
    from twobyteasr.app.ui import MainWindow
    calls=[];registry=NS(alignment_readiness={'qwen_aligner':{'ready':False}})
    page=NS(_registry=registry,_installed={'qwen_ultra_aligner'})
    win=NS(built_page=lambda _:page,_refresh_available_asr_choices=lambda:calls.append(1))
    MainWindow._on_model_inventory_refreshed(win)
    registry.alignment_readiness={'qwen_aligner':{'ready':True}}
    MainWindow._on_model_inventory_refreshed(win)
    assert calls==[1,1]


@pytest.mark.parametrize('state,head,expected_ready,expected_status',[
    ('inference_pending',False,False,'待验证'),
    ('selected',False,True,'当前使用'),
    ('experiment_unready',True,False,'实验精修待验证'),
])
def test_sidebar_uses_effective_family_readiness_not_old_official_files(state,head,expected_ready,expected_status):
    page=NS(runtime_settings={'models':{'firered_asr_backend':'qwen_aligner','qwen_alignment_head':head}},
            _installed={'qwen_aligner'},_model_state=lambda model,role:state)
    name,status,ready=w.ModelWorkshopPage._alignment_combo_value(page,'qwen_aligner')
    assert 'Ultra' in name and status==expected_status and ready is expected_ready
    assert ('精修' in name)==head


def test_workflow_updates_reuse_live_layout_items_and_widget_owners():
    from PySide6.QtWidgets import QApplication,QWidget
    from shiboken6 import getCppPointer,isValid
    app=QApplication.instance() or QApplication([])
    host=QWidget();flow=w._PillFlowLayout(host)
    page=NS(detail_workflow_host=host,detail_workflow_flow=flow)
    update=lambda steps:w.ModelWorkshopPage._set_workflow_steps(page,steps)
    update(['audio','align','words'])
    pointers=[getCppPointer(flow.itemAt(i))[0] for i in range(3)]
    for steps in [['text','words'],['audio','align','chars']]*20:
        update(steps);app.processEvents()
        assert [getCppPointer(flow.itemAt(i))[0] for i in range(3)]==pointers
        assert all(isValid(unit) and unit.parentWidget() is host for unit,_,_ in page._workflow_units)
    host.deleteLater();app.processEvents()


def test_picker_controls_never_show_as_unowned_windows_before_layout_adoption():
    from PySide6.QtCore import QObject,QEvent
    from PySide6.QtWidgets import QApplication,QPushButton
    from twobyteasr.local_models.model_picker_cards import PickerCard
    app=QApplication.instance() or QApplication([]);unowned=[]
    class Observe(QObject):
        def eventFilter(self,obj,event):
            if QEvent.type(event)==QEvent.Type.Show and isinstance(obj,QPushButton):
                if obj.objectName()=='pickerSecondary' and obj.parentWidget() is None:unowned.append(obj.objectName())
            return False
    observer=Observe();app.installEventFilter(observer)
    try:
        model=next(m for m in w.MODELS if m.api_preset)
        card=PickerCard(model,'primary',recommended=False,logo=lambda *a:None,accuracy={},online=True)
        assert card.configure.parentWidget() is card and not card.configure.isWindow()
        assert not unowned
        card.deleteLater();app.processEvents()
    finally:app.removeEventFilter(observer)


def test_selector_flags_reuse_indexes_without_qstandarditem_wrappers(monkeypatch,tmp_path):
    from PySide6.QtCore import QPersistentModelIndex,Qt
    from PySide6.QtGui import QStandardItemModel
    from PySide6.QtWidgets import QApplication,QComboBox
    from twobyteasr.app.ui import populate_available_asr_choices
    from twobyteasr.local_models import model_status_cache,model_state_events
    app=QApplication.instance() or QApplication([])
    class NoPythonItems(QStandardItemModel):
        def item(self,*args):raise AssertionError('Unsafe item wrapper path used')
    combos=[QComboBox() for _ in range(3)]
    for combo in combos:combo.setModel(NoPythonItems(combo))
    registry=NS(alignment_readiness={'qwen_aligner':{'state':'inference_pending','ready':False},'mfa_aligner':{'state':'installed','ready':True}})
    monkeypatch.setattr(model_status_cache,'cached_registry',lambda root:registry)
    monkeypatch.setattr(model_state_events,'active_task',lambda key:None)
    settings={'models':{'primary_asr_backend':'none','qwen_asr_backend':'off','firered_asr_backend':'qwen_aligner','qwen_alignment_head':False}}
    installed={'qwen_ultra_aligner','mfa_aligner','mfa_aligner_ja','firered_aed'}
    populate_available_asr_choices(*combos,settings,root=tmp_path,installed=installed)
    combo=combos[2];row=combo.findData('qwen_aligner');index=QPersistentModelIndex(combo.model().index(row,0))
    assert not combo.model().flags(index)&Qt.ItemFlag.ItemIsEnabled
    combo.blockSignals(True)
    for ready in [True,False]*10:
        registry.alignment_readiness['qwen_aligner'].update(ready=ready,state='installed' if ready else 'inference_pending')
        populate_available_asr_choices(*combos,settings,root=tmp_path,installed=installed)
        assert index.isValid() and combo.currentData()=='qwen_aligner' and combo.signalsBlocked()
        assert bool(combo.model().flags(index)&Qt.ItemFlag.ItemIsEnabled)==ready
    for combo in combos:combo.deleteLater()
    app.processEvents()


def test_explicit_head_readiness_is_shared_but_base_can_be_selected(monkeypatch):
    from twobyteasr.local_models.model_state_events import active_task
    monkeypatch.setattr('twobyteasr.local_models.model_state_events.active_task',lambda key:None)
    registry=NS(alignment_readiness={'qwen_aligner':{'state':'installed','ready':True},'qwen_ultra_head':{'state':'missing','ready':False}})
    settings={'models':{'firered_asr_backend':'qwen_aligner','qwen_alignment_head':True}}
    assert readiness.effective_snapshot(registry,'qwen_aligner',settings)['state']=='experiment_unready'
    assert readiness.effective_snapshot(registry,'qwen_aligner',settings,base_only=True)['ready']



@pytest.mark.parametrize('retire', ['none', 'timeout', 'settings_change'])
def test_selection_follows_latest_final_snapshot_without_dropping_user_request(monkeypatch, tmp_path, retire):
    import json
    from types import SimpleNamespace as NS
    from twobyteasr.local_models import model_status_cache, model_state_events
    from twobyteasr.local_models import model_workshop as w
    settings = {'models': {'firered_asr_backend': 'local'}}
    token = json.dumps(settings['models'], sort_keys=True)
    old = NS(installed_keys=lambda: {'qwen_ultra_aligner'})
    latest = NS(installed_keys=lambda: {'qwen_ultra_aligner'})
    requested, emitted, selected, refreshed = [], [], [], []
    monkeypatch.setattr(model_status_cache, 'registry_is_current', lambda root, value: value is latest)
    monkeypatch.setattr(model_status_cache, 'request_registry',
        lambda root, callback, **kw: requested.append((callback, kw)))
    monkeypatch.setattr(model_state_events, 'task_transition', lambda *a, **kw: None)
    page = NS(root=tmp_path, runtime_settings=settings, _registry=None,
        _selection_pending={'qwen_aligner': (9, token)}, _selection_failures={},
        selection_checked=NS(emit=emitted.append),
        refresh=lambda **kw: refreshed.append(kw),
        _model_state=lambda model, role: 'installed',
        _request_model_selection=lambda model, state, **kw: selected.append((model.key, state, kw)))
    payload = ('qwen_aligner', 9, token, 'timeline', 'installed', old)
    w.ModelWorkshopPage._selection_check_done(page, payload)
    assert page._selection_pending == {'qwen_aligner': (9, token)}
    assert len(requested) == 1 and not requested[0][1].get('force', False)
    assert not selected
    if retire == 'timeout':
        w.ModelWorkshopPage._selection_timeout(page, 'qwen_aligner', 9)
    elif retire == 'settings_change':
        settings['models']['firered_asr_backend'] = 'off'
    requested[0][0](latest)
    w.ModelWorkshopPage._selection_check_done(page, emitted.pop())
    if retire != 'none':
        assert not page._selection_pending and not selected
        return
    assert not page._selection_pending and page._registry is latest
    assert selected == [('qwen_aligner', 'installed', {'role': 'timeline'})]
    w.ModelWorkshopPage._selection_check_done(page, payload)
    assert len(requested) == len(selected) == 1
