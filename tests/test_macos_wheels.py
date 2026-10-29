import json
import struct
import zipfile

import pytest
from twobyteasr.system.macos_wheels import WHEELHOUSE,inspect_wheel,verify_wheelhouse,digest


def make_house(root):
    lock=root/'packaging/macos/source-wheels.lock.json';lock.parent.mkdir(parents=True)
    lock.write_text(json.dumps({'sources':[{'name':'example','version':'1.0','sha256':'a'*64}]}))
    directory=root/WHEELHOUSE;directory.mkdir(parents=True)
    wheel=directory/'example-1.0-py3-none-any.whl'
    with zipfile.ZipFile(wheel,'w') as z:z.writestr('example.py','value = 1')
    manifest=dict(target='darwin-arm64-cp310',source_lock_sha256=digest(lock),wheels=[dict(package='example',version='1.0',source_sha256='a'*64,file=wheel.name,sha256=digest(wheel))])
    (directory/'manifest.json').write_text(json.dumps(manifest))
    return directory,wheel,manifest


def test_bundled_source_only_packages_require_exact_hash_and_complete_inventory(tmp_path):
    folder,wheel,record=make_house(tmp_path)
    assert verify_wheelhouse(tmp_path)==folder
    wheel.write_bytes(b'changed')
    with pytest.raises(RuntimeError,match='checksum'):verify_wheelhouse(tmp_path)


def test_missing_bundled_cache_never_invokes_local_build_tools(tmp_path):
    with pytest.raises(RuntimeError,match='预编译依赖缓存'):verify_wheelhouse(tmp_path)


@pytest.mark.parametrize('arch,minimum',[(0x1000007,0xe0000),(0x100000c,0xf0000)])
def test_hidden_native_wheel_payload_must_fit_target(tmp_path,arch,minimum):
    wheel=tmp_path/'bad.whl'
    native=struct.pack('<8I',0xfeedfacf,arch,0,6,1,24,0,0)+struct.pack('<6I',0x32,24,1,minimum,0x1a0000,0)
    with zipfile.ZipFile(wheel,'w') as z:z.writestr('extension.so',native)
    with pytest.raises(RuntimeError,match='exceeds native target'):inspect_wheel(wheel)
