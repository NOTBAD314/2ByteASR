"""Manual official uv clean with a local wheel and a disposable installed runtime."""
from twobyteasr.test_isolation import install
install()

import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest
from twobyteasr.system.runtime_download_cache import clean_runtime_download_cache


def test_official_manual_clean_preserves_hardlinked_installed_package(tmp_path):
    tool=os.environ.get('TWOBYTEASR_TEST_UV_EXE','')
    actual_uv=Path(tool)
    if not tool or not actual_uv.is_file():pytest.skip('Explicit read-only local uv executable not supplied')
    root=Path(__file__).parents[1]
    contract=json.loads((root/'dependencies.lock.json').read_text('utf-8-sig'))
    data=tmp_path/'private-data';managed=data/'runtimes';cache=managed/'download-cache'
    managed.mkdir(parents=True)
    runtime=managed/'main/0123456789abcdef'
    def execute(argv):
        result=subprocess.run(list(map(str,argv)),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            text=True,encoding='utf8',errors='replace',timeout=45,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise RuntimeError(result.stdout)
        return result.stdout.strip()
    def uv(*args):
        return execute([actual_uv,'--no-config','--offline','--cache-dir',cache,*args])
    uv('venv','--python',sys._base_executable,'--no-python-downloads',runtime)
    wheel=tmp_path/'local_storage_probe-0.0.1-py3-none-any.whl'
    with zipfile.ZipFile(wheel,'w') as archive:
        archive.writestr('local_storage_probe/__init__.py','MARKER="offline-still-available"\n')
        archive.writestr('local_storage_probe-0.0.1.dist-info/METADATA','Metadata-Version: 2.1\nName: local-storage-probe\nVersion: 0.0.1\n')
        archive.writestr('local_storage_probe-0.0.1.dist-info/WHEEL','Wheel-Version: 1.0\nGenerator: local-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        archive.writestr('local_storage_probe-0.0.1.dist-info/RECORD','local_storage_probe/__init__.py,,\nlocal_storage_probe-0.0.1.dist-info/METADATA,,\nlocal_storage_probe-0.0.1.dist-info/WHEEL,,\nlocal_storage_probe-0.0.1.dist-info/RECORD,,\n')
    python=runtime/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    uv('pip','install','--python',python,'--link-mode','hardlink',wheel)
    (runtime/'managed-runtime.json').write_text(json.dumps({'role':'main','models':['local-storage-probe']}))
    (managed/'registry.json').write_text(json.dumps({'runtimes':{'main':{'python_executable':str(python)}}}))
    stub=managed/'tools'/('uv-'+contract['managed_bootstrap']['uv_version'])/actual_uv.name
    stub.parent.mkdir(parents=True);stub.write_bytes(b'executable location fixture')
    calls=[]
    def runner(argv,cancel):
        calls.append(list(map(str,argv)))
        return execute([actual_uv,*argv[1:]])
    result=clean_runtime_download_cache(root,data_root=data,runner=runner)
    assert result.status=='removed',result.detail
    assert result.measurement_complete and result.logical_removed_bytes>0
    clean_call=next(call for call in calls if call[-2:]==['cache','clean'])
    assert '--offline' in clean_call and str(cache) in clean_call and '--force' not in clean_call
    assert not any('prune' in call for call in calls)
    output=execute([python,'-I','-c','import local_storage_probe; print(local_storage_probe.MARKER)'])
    assert output=='offline-still-available' and python.exists()
    evidence=dict(operation='manual official uv cache clean',status=result.status,
        logical_removed_bytes=result.logical_removed_bytes,disk_free_delta=result.disk_free_delta,
        measurement_complete=result.measurement_complete,detail=result.detail,commands=calls,
        actual_uv=str(actual_uv),offline_import=output,fixture=str(tmp_path))
    (tmp_path/'uv-manual-offline-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),'utf8')
