# SPDX-License-Identifier: GPL-3.0-only
"""Package an existing release staging tree, then verify safe ZIP expansion.

This does not fetch dependencies, touch user data, or clear license blockers.
"""
import argparse, hashlib, importlib.metadata, json, os, shutil, sys, zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--stage',type=Path,required=True);ap.add_argument('--release',type=Path,required=True)
    ap.add_argument('--extract',type=Path,required=True);ap.add_argument('--review-commit',required=True)
    a=ap.parse_args();stage=a.stage.resolve();release=a.release.resolve();extract=a.extract.resolve()
    if not stage.is_relative_to(ROOT/'tmp') or not release.is_relative_to(ROOT/'releases') or not extract.is_relative_to(ROOT/'tmp') or extract.exists():raise ValueError('Only a staged tree and NEW local output under this workspace')
    evidence=stage.parent/'evidence';snapshot=json.loads((evidence/'snapshot-manifest.json').read_text('utf8'))
    version=snapshot['identity']['app_version']
    outputs=[release/f'2ByteASR-Source-{version}.zip',release/f'2ByteASR-ThirdParty-Materials-{version}.zip']
    if any(p.exists() for p in outputs):raise FileExistsError('Never overwrite an attachment')
    # Environment identity, not a claim that every package is embedded or rebuilt.
    environment={'python':sys.version.split()[0],'scope':'build environment; not bundled component inventory','packages':sorted([{'name':d.metadata['Name'],'version':d.version} for d in importlib.metadata.distributions()],key=lambda d:d['name'].lower())}
    (stage/'BUILD_ENVIRONMENT.json').write_text(json.dumps(environment,indent=2),'utf8')
    # Source-only docs/tests were captured when build_release froze the input.
    # Verify those fixed bytes instead of importing later live-worktree changes.
    attachment_manifest = evidence/'attachment-inputs.json'
    if not attachment_manifest.is_file():
        raise ValueError('Missing fixed attachment-inputs.json; do not fall back to the live worktree')
    for item in json.loads(attachment_manifest.read_text('utf8')):
        if digest(stage/item['path']) != item['sha256']:
            raise ValueError('Frozen attachment input mismatch: '+item['path'])
    files=[]
    for current,dirs,names in os.walk(stage):
        dirs[:]=[d for d in dirs if d not in {'.git','__pycache__','tmp'}]
        for name in names:
            p=Path(current)/name
            if p.is_symlink():raise ValueError('Unexpected symlink')
            rel=p.relative_to(stage).as_posix()
            if name.lower() in {'.env','secrets.json','secrets.dat','2byteasr_settings.json'}:raise ValueError('Personal configuration must not be copied: '+rel)
            files.append({'path':rel,'bytes':p.stat().st_size,'sha256':digest(p)})
    files.sort(key=lambda d:d['path'])
    paths=[p for p in (evidence/'source-paths.z').read_bytes().decode('utf8').split('\0') if p]
    receipt={'format':'2ByteASR-source-snapshot-1','identity':snapshot['identity'],'license_review_commit':a.review_commit,'build_input_paths':paths,'files':files,'not_a_clean_git_commit':True,'public_distribution_status':'blocked: exact C/D gaps in licenses/GPL3_ROUTE.md','prebuilt_dependencies_are_not_corresponding_source':True}
    (stage/'SOURCE_SNAPSHOT.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf8')
    release.mkdir(parents=True,exist_ok=True)
    for index,dest in enumerate(outputs):
        with zipfile.ZipFile(dest,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=3,allowZip64=True) as z:
            for item in files:
                is_material=item['path'].startswith('licenses/')
                if is_material==(index==1):z.write(stage/item['path'],item['path'])
            if index==0:z.write(stage/'SOURCE_SNAPSHOT.json','SOURCE_SNAPSHOT.json')
    extract.mkdir(parents=True)
    for archive in outputs:
        with zipfile.ZipFile(archive) as z:
            if z.testzip():raise ValueError('ZIP CRC failure')
            for member in z.infolist():
                if not (extract/member.filename).resolve().is_relative_to(extract):raise ValueError('Unsafe archive member')
            z.extractall(extract)
    for item in files:
        if digest(extract/item['path'])!=item['sha256']:raise ValueError('Extracted input mismatch: '+item['path'])
    result={'identity':snapshot['identity'],'source_manifest_sha256':digest(stage/'SOURCE_SNAPSHOT.json'),'artifacts':[{'file':p.name,'bytes':p.stat().st_size,'sha256':digest(p)} for p in outputs],'files_verified_after_extraction':len(files),'history_and_user_settings_excluded':True,'third_party_source_complete':False,'online_available':False}
    (release/'source-attachments.json').write_text(json.dumps(result,indent=2),'utf8')
    print(json.dumps(result))
if __name__=='__main__':main()
