"""Regression checks for failures found by Windows installed-model QA."""
import importlib.util
import json
import hashlib
from pathlib import Path

import pytest


def test_unknown_runtime_role_cannot_replace_main(tmp_path, monkeypatch):
    from twobyteasr.system import runtime_registry as registry
    monkeypatch.setattr(registry, 'runtimes_root', lambda: tmp_path)
    main = tmp_path/'main/Scripts/python.exe'
    main.parent.mkdir(parents=True)
    main.write_bytes(b'qa-interpreter')
    registry.register_runtime('main', str(main), source='test')
    before = registry.registry_path().read_bytes()
    with pytest.raises(ValueError):
        registry.register_runtime('typo-model-role', str(main), source='test')
    assert registry.registry_path().read_bytes() == before
    registry.reset_runtime_registry_cache()


def test_nano_never_uses_known_incompatible_modelscope_revision():
    from twobyteasr.repository_download import planned_sources
    lock=json.loads((Path(__file__).parents[1]/'dependencies.lock.json').read_text('utf8'))
    spec=lock['models']['funasr_nano']
    sources=planned_sources(spec,'AUTO')
    assert sources and all('MODELSCOPE' not in str(source) for source in sources)


def test_disk_failure_never_publishes_or_removes_existing_file(tmp_path,monkeypatch):
    path=Path(__file__).parents[1]/'scripts/download_file_fast.py'
    spec=importlib.util.spec_from_file_location('qa_recovery_downloader',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module.shutil,'disk_usage',lambda _:type('Disk',(),{'free':0})())
    output=tmp_path/'weight.bin';output.write_bytes(b'old-incomplete')
    with pytest.raises(OSError,match='磁盘空间不足'):
        module.download_from_source('https://example.invalid/weight',output,1000,True,4,'a'*64,0,10)
    assert output.read_bytes()==b'old-incomplete'


def test_missing_small_file_reuses_verified_weights_without_network(tmp_path,monkeypatch):
    from twobyteasr import repository_download as downloader
    destination=tmp_path/'model';destination.mkdir()
    weight=b'healthy-weight';config=b'{}'
    (destination/'weight.bin').write_bytes(weight)
    spec=dict(repository='QA/model',revision='fixed',required_files=['weight.bin','config.json'],
        sha256={'weight.bin':hashlib.sha256(weight).hexdigest(),'config.json':hashlib.sha256(config).hexdigest()})
    requested=[]
    def fetch(manifest,staging,relative):
        requested.append(relative)
        assert relative=='config.json', 'Valid installed weights must not access the network'
        path=staging/relative;path.write_bytes(config);return path
    monkeypatch.setattr(downloader,'_download_direct',fetch)
    downloader.download_model(model_key='model',spec=spec,destination=destination,mode='HF_OFFICIAL',staging_root=tmp_path/'stage')
    assert requested==['config.json']
    assert (destination/'weight.bin').read_bytes()==weight

