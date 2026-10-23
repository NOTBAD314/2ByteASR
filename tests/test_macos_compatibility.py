"""Version/architecture routing tests; simulated hosts are not Mac acceptance."""
import base64
import json
from types import SimpleNamespace

import pytest

from twobyteasr.system import macos_compatibility as mc
from twobyteasr.app import update_manifest as um, updater


@pytest.mark.parametrize('release,arch,eligible', [
    ('14.4.1','arm64',True), ('14.0','arm64',True), ('15.7.9','arm64',True),
    ('26.0','arm64',True), ('14.10','aarch64',True),
    ('13.7.8','arm64',False), ('12.7.6','arm64',False),
    ('14.4.1','x86_64',False), ('15.0','AMD64',False), ('','arm64',False),
    ('14.bad','arm64',False)])
def test_eligibility_is_explicit_and_numeric(release,arch,eligible):
    for role in ('app','main','moss','mlx'):
        assert (not mc.compatibility_problem(role,system='darwin',machine=arch,release=release)) == eligible


def test_unsupported_mlx_host_stops_before_bootstrap_or_weights(tmp_path,monkeypatch):
    from twobyteasr.local_models import macos_model_prepare as prepare
    monkeypatch.setattr(mc,'sys',SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(prepare,'sys',SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(mc.platform,'machine',lambda:'arm64')
    monkeypatch.setattr(mc.platform,'mac_ver',lambda:('13.7.8',('','',''),''))
    monkeypatch.setattr(prepare,'download_archive',lambda *a:pytest.fail('download occurred'))
    with pytest.raises(RuntimeError,match='14.0'):
        prepare.prepare_mlx(tmp_path,models=tmp_path/'models',source='HF_OFFICIAL',keys=('mlx_qwen_aligner',))
    assert not (tmp_path/'models').exists()


def mac_entry(minimum='14.0',arch='arm64'):
    return dict(architecture=arch,minimum_macos=minimum,runtime_contract='macos-arm64-sonoma-v1',
                asset=dict(name='candidate.dmg',size=100,sha256='a'*64,urls=['https://example.org/candidate.dmg']))


def manifest(entries):
    return dict(schema=um.UPDATE_SCHEMA,product=um.PRODUCT,app_id=um.APP_ID,version='0.8.4',tag='v0.8.4',
                channel='stable',platform='windows',arch='x64',release_page='https://example.org/release',
                setup=dict(name='windows.exe',size=10,sha256='b'*64,urls=['https://example.org/windows.exe']),
                components={name:dict(content_sha256='c'*64,file_count=1,bytes=1) for name in um.COMPONENT_ORDER},
                macos_installers=entries)


def test_signed_mac_update_never_plans_windows_components(tmp_path,monkeypatch):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    key=Ed25519PrivateKey.generate()
    private=key.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption())
    public=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    monkeypatch.setitem(um.TRUSTED_UPDATE_KEYS,um.key_id_for(public),base64.b64encode(public).decode())
    data=json.dumps(manifest([mac_entry()])).encode()
    signature=um.sign_manifest(data,private)
    if isinstance(signature,dict):
        signature=json.dumps(signature).encode()
    monkeypatch.setattr(updater,'sys',SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(mc.platform,'machine',lambda:'arm64')
    monkeypatch.setattr(mc.platform,'mac_ver',lambda:('14.4.1',('','',''),''))
    monkeypatch.setattr(updater,'plan_update',lambda *a:pytest.fail('Windows plan used on Mac'))
    check=updater._evaluate(data,signature,'0.8.3','stable','https://example.org',0,tmp_path)
    assert check.installer_url=='https://example.org/candidate.dmg'
    assert check.plan.mode=='setup' and not check.can_self_update
    with pytest.raises(um.ManifestError,match='签名'):
        updater._evaluate(data.replace(b'candidate.dmg',b'injected0.dmg'),signature,'0.8.3','stable','',0,tmp_path)


@pytest.mark.parametrize('entries,release,arch', [
    ([], '14.4.1','arm64'), ([mac_entry('15.0')],'14.4.1','arm64'),
    ([mac_entry('14.4.2')],'14.4.1','arm64'), ([mac_entry()],'14.4.1','x86_64'),
    ([mac_entry('14.10')],'14.9.9','arm64'), ([mac_entry('bad')],'15.0','arm64'),
    ([mac_entry(),mac_entry()],'14.4.1','arm64')])
def test_unsupported_or_ambiguous_update_preserves_current(entries,release,arch):
    parsed=um.parse_update_manifest(json.dumps(manifest(entries)).encode())
    with pytest.raises(um.ManifestError):
        um.select_macos_installer(parsed,release=release,machine=arch)


def test_additive_mac_field_leaves_legacy_windows_manifest_intact():
    parsed=um.parse_update_manifest(json.dumps(manifest([mac_entry()])).encode())
    assert parsed.setup.name=='windows.exe'
    assert set(parsed.components)==set(um.COMPONENT_ORDER)
    assert um.select_macos_installer(parsed,release='14.4.1',machine='arm64').name=='candidate.dmg'


def test_mlx_without_metal_does_not_silently_switch_to_cpu(monkeypatch):
    import mlx_worker
    core=SimpleNamespace(default_device=lambda:'cpu',metal=SimpleNamespace(is_available=lambda:False))
    monkeypatch.setitem(__import__('sys').modules,'mlx',SimpleNamespace(core=core))
    monkeypatch.setitem(__import__('sys').modules,'mlx.core',core)
    with pytest.raises(RuntimeError,match='Metal'):
        mlx_worker._device_info()


def test_failed_mps_probe_is_isolated_and_stops_preparation(tmp_path,monkeypatch):
    from twobyteasr.local_models import macos_model_prepare as prepare
    seen=[]
    def failed(command,**kwargs):
        seen.append((command,kwargs))
        return SimpleNamespace(returncode=-6,stdout='',stderr='Metal initialization aborted')
    monkeypatch.setattr(prepare.subprocess,'run',failed)
    with pytest.raises(RuntimeError,match='尚未下载模型权重'):
        prepare.require_mps_runtime(tmp_path/'runtime/bin/python',tmp_path,dtype='bfloat16')
    assert seen[0][0][1:3]==['-I','-c'] and seen[0][1]['timeout']==180


def test_build_bootstrap_and_runtime_minimums_agree():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]/'packaging/macos'
    native=json.loads((root/'native-dependencies.lock.json').read_text('utf8'))
    bootstrap=json.loads((root/'bootstrap.lock.json').read_text('utf8'))
    assert native['minimum_macos']==bootstrap['compatibility']['minimum_macos']==mc.MINIMUM_MACOS
    assert bootstrap['compatibility']['architectures']==list(mc.ARCHITECTURES)


@pytest.mark.parametrize('error,category',[
    ('Library not loaded: libmpv.2.dylib','missing_library'),
    ('Symbol not found: _new_api','missing_symbol'),
    ('mach-o, but wrong incompatible architecture','architecture'),
    ('code signature invalid','signature_or_notarization'),
    ('MPS allocation failed','backend_initialization'),
    ('requires macOS 15.0','minimum_system')])
def test_diagnostics_separates_actionable_failures(error,category):
    assert mc.failure_category(error)==category
