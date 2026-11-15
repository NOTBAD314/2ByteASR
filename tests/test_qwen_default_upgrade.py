import copy,json
from pathlib import Path
from twobyteasr.storage.settings import DEFAULT_SETTINGS
from twobyteasr.recognition.alignment_backend import selected_backend,profile,readiness_matches
from twobyteasr.recognition import qwen_upgrade


def test_official_files_or_unverified_receipt_cannot_migrate_defaults(monkeypatch,tmp_path):
    settings=copy.deepcopy(DEFAULT_SETTINGS);settings['models']['firered_asr_backend']='qwen_aligner';before=copy.deepcopy(settings)
    monkeypatch.setattr(qwen_upgrade,'current_readiness',lambda root:None)
    assert not qwen_upgrade.activate_if_ready(settings,data_root=tmp_path,persist=False)
    assert settings==before
    p=profile('qwen_aligner')
    fake=dict(inference_verified=True,alignment_receipt={k:p[k] for k in ['model','model_revision','code','unit_policy']})
    fake['alignment_receipt']['alignment_identity']=p
    assert not readiness_matches('qwen_aligner',fake)


def test_actual_ready_migration_changes_only_future_qwen_selection(monkeypatch,tmp_path):
    settings=copy.deepcopy(DEFAULT_SETTINGS);settings['models']['firered_asr_backend']='qwen_aligner';settings['switches']['use_ja_ctc_aligner']=True
    frozen=copy.deepcopy(settings)
    monkeypatch.setattr(qwen_upgrade,'current_readiness',lambda root:{'alignment_receipt':{'model':'Ultra','model_revision':'fixed'}})
    assert qwen_upgrade.activate_if_ready(settings,data_root=tmp_path,persist=False)
    assert selected_backend(frozen)=='qwen_aligner'
    assert selected_backend(settings)=='qwen_ultra_aligner'
    assert settings['models']['firered_asr_backend']=='qwen_aligner'
    assert not settings['switches']['use_ja_ctc_aligner']
    assert settings['models']['primary_asr_backend']==frozen['models']['primary_asr_backend']
    assert settings['models']['qwen_asr_backend']==frozen['models']['qwen_asr_backend']


def test_other_timeline_choices_are_preserved_and_head_is_opt_in_after_upgrade(monkeypatch,tmp_path):
    monkeypatch.setattr(qwen_upgrade,'current_readiness',lambda root:{'alignment_receipt':{'model':'Ultra','model_revision':'fixed'}})
    settings=copy.deepcopy(DEFAULT_SETTINGS);settings['models']['firered_asr_backend']='mfa_aligner'
    qwen_upgrade.activate_if_ready(settings,data_root=tmp_path,persist=False)
    assert settings['models']['firered_asr_backend']=='mfa_aligner'
    settings['models']['firered_asr_backend']='qwen_ultra_head'
    qwen_upgrade.activate_if_ready(settings,data_root=tmp_path,persist=False)
    assert settings['models']['firered_asr_backend']=='qwen_ultra_head'


def test_model_file_stamp_change_invalidates_ready_proof(monkeypatch,tmp_path):
    from twobyteasr.recognition import alignment_backend,asr
    target=tmp_path/'model-readiness/qwen_ultra_aligner.json';target.parent.mkdir()
    folder=tmp_path/'Ultra';folder.mkdir();runtime=tmp_path/'python.exe'
    receipt=dict(inference_verified=True,ultra_directory=str(folder.resolve()),ultra_file_stats={'weight':[10,20]},runtime_python=str(runtime),alignment_receipt={})
    target.write_text(json.dumps(receipt),'utf8')
    monkeypatch.setattr(alignment_backend,'readiness_matches',lambda *a:True)
    monkeypatch.setattr(alignment_backend,'model_directory',lambda *a:str(folder))
    monkeypatch.setattr(asr,'_main_worker_python',lambda:runtime)
    from twobyteasr.local_models import alignment_readiness
    monkeypatch.setattr(alignment_readiness,'runtime_matches',lambda *a:True)
    monkeypatch.setattr(qwen_upgrade,'file_stamp',lambda p:{'weight':[10,20]})
    assert qwen_upgrade.current_readiness(tmp_path)
    monkeypatch.setattr(qwen_upgrade,'file_stamp',lambda p:{'weight':[10,21]})
    assert qwen_upgrade.current_readiness(tmp_path) is None
