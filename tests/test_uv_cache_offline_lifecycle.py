"""Real pinned uv, tiny local wheel and disposable venv; no network/models."""
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest
from twobyteasr.system.runtime_download_cache import prune_runtime_download_cache


def test_official_uv_prune_preserves_installed_package_offline(tmp_path):
    root=Path(__file__).parents[1]
    contract=json.loads((root/'dependencies.lock.json').read_text('utf-8-sig'))
    from twobyteasr.runtime_paths import user_data_root
    actual_uv=user_data_root()/'runtimes/tools'/('uv-'+contract['managed_bootstrap']['uv_version'])/'uv.exe'
    if os.name!='nt' or not actual_uv.is_file():pytest.skip('Pinned local Windows uv unavailable')
    data=tmp_path/'private-data';managed=data/'runtimes';cache=managed/'download-cache'
    managed.mkdir(parents=True)
    runtime=managed/'main/0123456789abcdef'
    def run(*args):
        result=subprocess.run([str(actual_uv),'--no-config','--offline','--cache-dir',str(cache),*map(str,args)],
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf8',errors='replace',timeout=45,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        assert result.returncode==0,result.stdout
        return result.stdout
    run('venv','--python',sys._base_executable,'--no-python-downloads',runtime)
    wheel=tmp_path/'local_storage_probe-0.0.1-py3-none-any.whl'
    with zipfile.ZipFile(wheel,'w') as archive:
        archive.writestr('local_storage_probe/__init__.py','MARKER="offline-still-available"\n')
        archive.writestr('local_storage_probe-0.0.1.dist-info/METADATA','Metadata-Version: 2.1\nName: local-storage-probe\nVersion: 0.0.1\n')
        archive.writestr('local_storage_probe-0.0.1.dist-info/WHEEL','Wheel-Version: 1.0\nGenerator: local-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        archive.writestr('local_storage_probe-0.0.1.dist-info/RECORD','local_storage_probe/__init__.py,,\nlocal_storage_probe-0.0.1.dist-info/METADATA,,\nlocal_storage_probe-0.0.1.dist-info/WHEEL,,\nlocal_storage_probe-0.0.1.dist-info/RECORD,,\n')
    python=runtime/'Scripts/python.exe'
    run('pip','install','--python',python,'--link-mode','hardlink',wheel)
    (runtime/'managed-runtime.json').write_text(json.dumps({'role':'main','models':['local-storage-probe']}))
    (managed/'registry.json').write_text(json.dumps({'runtimes':{'main':{'python_executable':str(python)}}}))
    # The runner substitutes only uv's executable location to avoid copying the
    # 50+MiB tool; all application-generated arguments and cache scope are real.
    stub=managed/'tools'/('uv-'+contract['managed_bootstrap']['uv_version'])/'uv.exe'
    stub.parent.mkdir(parents=True);stub.write_bytes(b'runner fixture')
    calls=[]
    def actual_runner(argv,cancel):
        calls.append([str(x) for x in argv])
        result=subprocess.run([str(actual_uv),*map(str,argv[1:])],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            text=True,encoding='utf8',errors='replace',timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise RuntimeError(result.stdout)
        return result.stdout.strip()
    result=prune_runtime_download_cache(root,data_root=data,runner=actual_runner)
    assert result.status=='removed',result.detail
    output=subprocess.check_output([str(python),'-I','-c','import local_storage_probe; print(local_storage_probe.MARKER)'],
        text=True,encoding='utf8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert output.strip()=='offline-still-available'
    assert '--force' not in calls[-1] and str(cache) in calls[-1]
    evidence={'status':result.status,'logical_removed_bytes':result.logical_removed_bytes,
        'disk_free_delta':result.disk_free_delta,'detail':result.detail,'commands':calls,
        'offline_import':output.strip(),'network_calls':0,'fixture':str(tmp_path)}
    (tmp_path/'uv-offline-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf8')
