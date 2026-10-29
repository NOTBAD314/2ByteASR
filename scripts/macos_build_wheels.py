"""Build the five source-only packages on CI, never on an end user's Mac."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.macos_compat_native import acquire
from twobyteasr.system.macos_wheels import digest,inspect_wheel,verify_wheelhouse


def build_wheelhouse(python: Path, output: Path, root=ROOT) -> Path:
    if output.exists():raise RuntimeError('Wheelhouse output must be new')
    output.mkdir(parents=True);sources=output/'sources';sources.mkdir()
    lock_path=root/'packaging/macos/source-wheels.lock.json'
    lock=json.loads(lock_path.read_text('utf8'));env=dict(os.environ,MACOSX_DEPLOYMENT_TARGET='14.0',ARCHFLAGS='-arch arm64')
    rows=[]
    with (output/'build.log').open('wb') as log:
        subprocess.run([str(python),'-m','pip','install','--only-binary=:all:',*lock['build_requirements']],
                       env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
        for source in lock['sources']:
            archive=acquire(source,sources/(source['name']+'.tar.gz'))
            before=set(output.glob('*.whl'))
            subprocess.run([str(python),'-m','pip','wheel','--no-build-isolation','--no-deps','--wheel-dir',str(output),str(archive)],
                           env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
            produced=set(output.glob('*.whl'))-before
            if len(produced)!=1:raise RuntimeError('Expected one exact wheel for '+source['name'])
            wheel=produced.pop()
            with zipfile.ZipFile(wheel) as bundle:
                import email
                metadata=email.message_from_bytes(bundle.read(next(n for n in bundle.namelist() if n.endswith('.dist-info/METADATA'))))
            if metadata['Name'].lower().replace('_','-')!=source['name'].lower().replace('_','-') or metadata['Version']!=source['version']:
                raise RuntimeError('Built wheel metadata differs from source lock')
            rows.append(dict(file=wheel.name,package=source['name'],version=source['version'],sha256=digest(wheel),
                             source_sha256=source['sha256'],native=inspect_wheel(wheel)))
    record=dict(schema_version=1,target=lock['target'],source_lock_sha256=digest(lock_path),wheels=rows)
    (output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n','utf8')
    return verify_wheelhouse(root,directory=output)
