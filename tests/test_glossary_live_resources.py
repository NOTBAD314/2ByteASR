"""Real-Home audit borrowing guards; these fixtures never execute a model."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path

import pytest

from twobyteasr.acceptance.glossary_live_resources import validate_manifest, sha_file, install, BorrowedResources


@pytest.fixture
def declared(tmp_path):
    profile = tmp_path/'normal-ui-profile'; profile.mkdir()
    roles = {}
    for role in ('main', 'moss'):
        venv = tmp_path/role; (venv/'Scripts').mkdir(parents=True)
        python = venv/'Scripts/python.exe'; python.write_bytes(b'declared test executable; never launched')
        config = venv/'pyvenv.cfg'; config.write_text('fixture = true')
        roles[role] = dict(python=str(python), python_sha256=sha_file(python),
            venv_config=str(config), venv_config_sha256=sha_file(config))
    models = tmp_path/'existing-models'; models.mkdir()
    metadata = models/'config.json'; metadata.write_text('{"fixture":true}')
    protected = tmp_path/'original-settings.json'; protected.write_text('{}')
    manifest = tmp_path/'borrowed.json'
    value = dict(schema_version=1, roles=roles, model_root=dict(path=str(models),
        sentinels=[dict(path=str(metadata), sha256=sha_file(metadata))]),
        extra_protected_sources={str(protected): sha_file(protected)})
    manifest.write_text(json.dumps(value))
    return profile, manifest, value


def test_installed_roles_only_and_all_declared_sources_are_guarded(declared):
    profile, manifest, value = declared
    validated = validate_manifest(manifest, profile)
    assert set(validated['roles']) == {'main', 'moss'}
    assert value['model_root']['sentinels'][0]['path'] in validated['protected']
    assert set(value['extra_protected_sources']) <= set(validated['protected'])


def test_hash_mismatch_and_foreign_model_sentinel_fail_before_install(declared):
    profile, manifest, value = declared
    Path(value['roles']['main']['python']).write_bytes(b'changed input')
    with pytest.raises(ValueError, match='SHA mismatch'):
        validate_manifest(manifest, profile)
    value['roles']['main']['python_sha256'] = sha_file(value['roles']['main']['python'])
    sentinel = value['model_root']['sentinels'][0]
    sentinel['path'] = value['roles']['main']['venv_config']
    sentinel['sha256'] = value['roles']['main']['venv_config_sha256']
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='reside'):
        validate_manifest(manifest, profile)


def test_hook_refuses_normal_app_and_foreign_profile(declared, monkeypatch):
    profile, _, _ = declared
    monkeypatch.setenv('TWOBYTEASR_ACCEPTANCE_SCENARIO', 'completion-real')
    monkeypatch.setenv('TWOBYTEASR_TEST_ROOT', str(profile))
    with pytest.raises(ValueError, match='only be installed'):
        install(profile)
    monkeypatch.setenv('TWOBYTEASR_ACCEPTANCE_SCENARIO', 'glossary-live-home')
    monkeypatch.setenv('TWOBYTEASR_TEST_ROOT', str(profile.parent))
    with pytest.raises(ValueError, match='only be installed'):
        install(profile)


def test_borrowed_root_survives_ordinary_launcher_bootstrap(declared, monkeypatch):
    profile, manifest, value = declared
    from twobyteasr.system import runtime_registry
    from twobyteasr.runtime_paths import bootstrap_runtime_paths, get_runtime_paths, MODEL_ROOT_ENV
    monkeypatch.setenv('2BYTEASR_USER_DATA_ROOT', str(profile/'local'))
    original = runtime_registry.resolve_runtime_python
    resources = BorrowedResources(validate_manifest(manifest, profile), profile)
    try:
        paths = bootstrap_runtime_paths(install_root=Path(__file__).resolve().parents[1], persist=True)
        assert str(paths.model_root) == value['model_root']['path']
        assert get_runtime_paths().model_root == paths.model_root
        assert os.environ[MODEL_ROOT_ENV] == str(paths.model_root)
        assert runtime_registry.resolve_runtime_python('moss') == value['roles']['moss']['python']
        assert (profile/'local/2ByteASR/runtime_paths.json').is_file()
        assert all(row['unchanged'] for row in resources.protection())
    finally:
        resources.restore()
    assert runtime_registry.resolve_runtime_python is original


def test_private_access_copy_never_refreshes_and_cleanup_preserves_source(declared):
    profile, manifest, value = declared
    path = Path(__file__).resolve().parents[1]/'scripts/verify_glossary_live_home.py'
    spec = importlib.util.spec_from_file_location('live_home_driver_guard_test', path)
    driver = importlib.util.module_from_spec(spec); spec.loader.exec_module(driver)
    source = profile.parent/'source-cli'; source.mkdir()
    auth = source/'auth.json'
    row = dict(auth_mode='oidc', key='fixture-access-never-used', refresh_token='fixture-refresh-never-used',
        expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    auth.write_text(json.dumps({'fixture': row}))
    value['grok_home'] = dict(path=str(source), auth_sha256=sha_file(auth))
    manifest.write_text(json.dumps(value))
    validated = validate_manifest(manifest, profile)
    private = driver.prepare_private_cli(validated, profile, {'models': {'ai_service': 'grok_account'}})
    assert 'refresh_token' not in json.loads((private/'auth.json').read_text())['fixture']
    assert driver.cleanup_private_cli(private, profile)
    assert auth.is_file() and sha_file(auth) == value['grok_home']['auth_sha256']
    row['expires_at'] = (datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat()
    auth.write_text(json.dumps({'fixture': row}))
    with pytest.raises(ValueError, match='expires inside'):
        driver.prepare_private_cli(validated, profile, {'models': {'ai_service': 'grok_account'}})
    assert not (profile/'live-home-private-cli').exists()
