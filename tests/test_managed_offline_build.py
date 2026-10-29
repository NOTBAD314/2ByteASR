"""MOSS's PEP 517 backends are pinned local artifacts, never hidden indexes."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('offline_installer',ROOT/'scripts/install_managed_backend.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)


@pytest.fixture
def bundled(tmp_path):
    root=tmp_path/'安装 包 (1)';(root/'scripts').mkdir(parents=True);(root/'wheels').mkdir()
    pins={};rows=[]
    for name,version in [('setuptools','80.9.0'),('wheel','0.45.1')]:
        filename=f'{name}-{version}-py3-none-any.whl'
        path=root/'wheels'/filename;path.write_bytes(('inert wheel fixture '+name).encode())
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        pins[name]={'version':version,'sha256':[digest]}
        rows.append({'file':filename,'sha256':digest})
    (root/'scripts/runtime_package_hashes.json').write_text(json.dumps({'build_backend':pins}),'utf8')
    (root/'wheels/model_wheels.json').write_text(json.dumps({'wheels':rows}),'utf8')
    return root


def test_only_verified_bundled_backends_are_exposed_offline(bundled,tmp_path):
    managed=tmp_path/'中文 运行环境';runtime=managed/'moss/generation';runtime.mkdir(parents=True)
    build=runtime/'build-constraints.txt';commands=[]
    source=bundled/'MOSS 源码'
    def uv(*arguments):
        commands.append(arguments)
        assert '--no-index' in arguments and '--offline' in arguments and '--no-deps' in arguments
        assert '--index-url' not in arguments
        wheelhouse=managed/arguments[arguments.index('--find-links')+1]
        assert sorted(p.name for p in wheelhouse.iterdir())==['setuptools-80.9.0-py3-none-any.whl','wheel-0.45.1-py3-none-any.whl']
        assert arguments[-1]==str(source)+'[torch-runtime]'
        assert arguments[arguments.index('--build-constraint')+1]==str(build.relative_to(managed))
        assert all('--hash=sha256:' in line for line in build.read_text('utf8').splitlines())
    installer.install_moss_source_offline(uv,bundled,source,runtime/'Scripts/python.exe',build,managed)
    assert len(commands)==1


@pytest.mark.parametrize('problem',['missing_file','missing_manifest_entry','wrong_manifest_hash','wrong_locked_hash'])
def test_missing_or_modified_build_wheel_fails_before_uv(bundled,tmp_path,problem):
    manifest=bundled/'wheels/model_wheels.json';data=json.loads(manifest.read_text('utf8'))
    wheel=bundled/'wheels'/data['wheels'][1]['file']
    if problem=='missing_file':wheel.unlink()
    elif problem=='missing_manifest_entry':data['wheels'].pop();manifest.write_text(json.dumps(data),'utf8')
    elif problem=='wrong_manifest_hash':wheel.write_bytes(b'changed')
    else:
        wheel.write_bytes(b'changed');data['wheels'][1]['sha256']=hashlib.sha256(wheel.read_bytes()).hexdigest();manifest.write_text(json.dumps(data),'utf8')
    managed=tmp_path/'managed';managed.mkdir();called=[]
    with pytest.raises(RuntimeError,match='MOSS'):
        installer.install_moss_source_offline(lambda *a:called.append(a),bundled,bundled/'source',managed/'python.exe',managed/'build.txt',managed)
    assert not called
