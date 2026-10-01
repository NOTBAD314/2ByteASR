# SPDX-License-Identifier: GPL-3.0-only
"""Verify an extracted source attachment and freeze it in a NEW local directory."""
import argparse, hashlib, json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();out=args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp') or out.exists(): raise ValueError('Use a NEW directory under extracted source/tmp')
    receipt=json.loads((ROOT/'SOURCE_SNAPSHOT.json').read_text('utf8'))
    for item in receipt['files']:
        p=(ROOT/item['path']).resolve()
        if not p.is_relative_to(ROOT) or not p.is_file() or digest(p)!=item['sha256']:
            raise ValueError('Source attachment mismatch: '+item['path'])
    sys.path.insert(0,str(ROOT))
    from twobyteasr.build_identity import source_snapshot_sha256
    identity=receipt['identity']
    fingerprint,count=source_snapshot_sha256(ROOT,[ROOT/p for p in receipt['build_input_paths']])
    if (fingerprint,count)!=(identity['source_sha256'],identity['source_file_count']): raise ValueError('Build identity mismatch')
    out.mkdir(parents=True);metadata=out/'2byteasr_build.json'
    metadata.write_text(json.dumps(identity,indent=2),'utf8')
    env=os.environ.copy();env.update(TWOBYTEASR_BUILD_METADATA=str(metadata),PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1')
    env.pop('TWOBYTEASR_QA_BUILD',None)
    cmd=[sys.executable,'-m','PyInstaller','--clean','--noconfirm','--distpath',str(out/'payload'),'--workpath',str(out/'work'),str(ROOT/'packaging/2byteasr_main.spec')]
    with (out/'pyinstaller.log').open('wb') as log:
        result=subprocess.run(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    (out/'rebuild-result.json').write_text(json.dumps({'exit_code':result.returncode,'source_manifest_sha256':digest(ROOT/'SOURCE_SNAPSHOT.json'),'identity':identity,'build_environment_reused':True,'third_party_source_rebuild':False},indent=2),'utf8')
    if result.returncode: raise SystemExit(result.returncode)
    print(json.dumps({'payload':str(out/'payload/2ByteASR'),'verified_inputs':len(receipt['files']),'status':'built_from_extracted_source'}))

if __name__=='__main__':main()
