# SPDX-License-Identifier: GPL-3.0-only
"""Freeze current working files into a new, immutable release staging directory.

Usage: python scripts/build_release.py --output tmp/release-YYYYMMDD/build-r1
No reset, clean, default dist output, user settings or model cache is used.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.git', '__pycache__', '.pytest_cache', '.mimosa', '.cache', 'tmp',
            'logs', 'reports', '.venv', '.venv-main', '.venv-moss'}
BAD_EXT = {'.pyc', '.pyo', '.log', '.2byteasr', '.2byteproj', '.mp4', '.mp3',
           '.mov', '.flv', '.wav', '.safetensors', '.ckpt', '.pt', '.pth'}
ROOT_FILES = {'.gitignore', 'LICENSE', 'PROJECT_LICENSE.md', 'SOURCE_DELIVERY.md', 'BUILD_FROM_SOURCE.md', 'SOURCE_ONLY_SCOPE.md', 'CONTRIBUTING.md', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md', '2byteasr_version.json',
              'dependencies.lock.json', 'game_profiles.json', 'glossary.txt',
              'requirements-main.txt', 'quick_start.py', 'subtitle_core.py',
              'moss_firered_pipeline.py', 'auto_asr.py', 'extract_target_speaker.py',
              'register_host_voiceprint.py'}


def digest(path):
    with path.open('rb') as stream:
        h = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage-only', action='store_true')
    parser.add_argument('--channel', default='release-candidate-20260929')
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / 'tmp') or out.exists():
        raise ValueError('Choose a NEW directory under repository tmp; existing outputs are never overwritten')
    stage = out / 'source'; stage.mkdir(parents=True)
    evidence = out / 'evidence'; evidence.mkdir()
    sys.path.insert(0, str(ROOT))
    from twobyteasr.build_identity import create_build_metadata, source_snapshot_files, source_snapshot_sha256
    identity = create_build_metadata(ROOT, channel=args.channel)
    source_files = source_snapshot_files(ROOT)
    selected = {p.relative_to(ROOT) for p in source_files}
    for name in ROOT_FILES: selected.add(Path(name))
    selected.update(p.relative_to(ROOT) for p in ROOT.glob('*_worker.py'))
    for folder in ('assets', 'licenses', 'lexicons', 'renderer', 'scripts', 'twobyteasr', 'packaging', '.github/workflows',
                   'installer', 'launcher', 'third_party', 'tools/ffmpeg', 'tools/mpv', 'tools/node'):
        for current, dirs, names in os.walk(ROOT / folder):
            dirs[:] = [n for n in dirs if n.lower() not in EXCLUDED and not n.endswith('.egg-info')]
            for name in names:
                p = Path(current) / name
                rel = p.relative_to(ROOT)
                if p.suffix.lower() in BAD_EXT or name.lower() in {'secrets.json','secrets.dat','.env'}: continue
                if p.is_symlink(): raise ValueError(f'Unexpected symlink in release input: {rel}')
                selected.add(rel)
    wheel_manifest = json.loads((ROOT/'packaging/model_wheels.json').read_text('utf8'))
    for item in wheel_manifest['wheels']:
        rel = Path('wheels')/item['file']
        if digest(ROOT/rel) != item['sha256']: raise ValueError(f'Wheel mismatch: {rel}')
        selected.add(rel)
    records = []
    for rel in sorted(selected):
        source = ROOT / rel
        if not source.is_file(): raise FileNotFoundError(rel)
        target = stage / rel; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        before = digest(source); after = digest(target)
        if before != after: raise ValueError(f'Input changed during snapshot: {rel}')
        records.append(dict(path=rel.as_posix(),bytes=target.stat().st_size,sha256=after))
    # Only source inventory is indexed. No Git commit or history is copied.
    flags = dict(cwd=stage,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    subprocess.run(['git','init','-q'], **flags)
    paths = evidence/'source-paths.z'
    paths.write_bytes(b'\0'.join(p.relative_to(ROOT).as_posix().encode('utf8') for p in source_files)+b'\0')
    subprocess.run(['git','-c','core.autocrlf=false','add','-f','--pathspec-from-file='+str(paths),'--pathspec-file-nul'], **flags)
    # Licenses from the exact build environment, without its config or cache.
    licenses = stage/'licenses/python'; licenses.mkdir(parents=True)
    distributions=[]
    for dist in importlib.metadata.distributions():
        name=dist.metadata.get('Name','unknown'); version=dist.version
        copied=[]
        for item in dist.files or []:
            parts=Path(str(item)).parts
            if not any(x.endswith(('.dist-info','.egg-info')) for x in parts): continue
            if not any(x.lower().startswith(('license','copying','notice')) for x in parts): continue
            p=dist.locate_file(item)
            if not p.is_file():continue
            target=licenses/(name+'-'+version)/Path(*parts[1:]);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(p,target);copied.append(target.relative_to(stage).as_posix())
        distributions.append(dict(name=name,version=version,license=dist.metadata.get('License-Expression') or dist.metadata.get('License'),license_files=copied))
    (licenses/'build-environment-inventory.json').write_text(json.dumps(distributions,ensure_ascii=False,indent=2),'utf8')
    (evidence/'snapshot-manifest.json').write_text(json.dumps(dict(identity=identity,files=records),ensure_ascii=False,indent=2),'utf8')
    metadata=evidence/'2byteasr_build.json';metadata.write_text(json.dumps(identity,indent=2),'utf8')
    (evidence/'snapshot.json').write_text(json.dumps(dict(root=str(stage),source_files=len(source_files),files=len(records),bytes=sum(x['bytes'] for x in records)),indent=2),'utf8')
    for checked_root in (ROOT, stage):
        current_hash, current_count = source_snapshot_sha256(checked_root)
        if (current_hash, current_count) != (identity['source_sha256'], identity['source_file_count']):
            raise RuntimeError(f'Source changed or staging input differs: {checked_root}; preserve evidence and use a fresh output')
    # The source attachment's documentation/tests are frozen at the same boundary.
    # Do not read the live worktree again after a long PyInstaller build.
    attachment_paths = []
    for name in ('setup_environment.bat', 'setup_2byteasr.bat', 'setup_moss_firered.bat',
                 'run_tests.bat', 'download_models.bat', 'README.md', 'README_EN.md', 'README_JA.md', 'ARCHITECTURE.md'):
        if (ROOT / name).is_file(): attachment_paths.append(ROOT / name)
    for folder in ('tests', 'docs/assets/readme', 'docs/deployment', 'website'):
        for current, dirs, names in os.walk(ROOT / folder):
            dirs[:] = [d for d in dirs if d.lower() not in EXCLUDED | {'node_modules', 'product-review', 'dist'}]
            attachment_paths.extend(Path(current) / n for n in names
                                    if Path(n).suffix.lower() not in {'.pyc', '.pyo', '.log'})
    attachment_paths.extend(ROOT.glob('docs/product-*.md'))
    attachment_paths.append(ROOT/'docs/windows-qa-preparation.zh-CN.md')
    extra_records = []
    for source in attachment_paths:
        rel = source.relative_to(ROOT); target = stage / rel
        if rel.as_posix() in {'tests/data/p9a_r2_deepseek_raw_responses.json',
                              'tests/fixtures/p14_real_task_report.json'}:
            continue  # Historical private raw tasks are not required build inputs.
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target)
        if digest(source) != digest(target): raise ValueError(f'Attachment input changed: {rel}')
        extra_records.append(dict(path=rel.as_posix(), bytes=target.stat().st_size, sha256=digest(target)))
    (evidence / 'attachment-inputs.json').write_text(json.dumps(extra_records, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(dict(stage=str(stage),identity=identity,files=len(records)),ensure_ascii=False),flush=True)
    if args.stage_only:return
    env=os.environ.copy();env['TWOBYTEASR_BUILD_METADATA']=str(metadata)
    env['PYTHONUTF8']='1';env.pop('TWOBYTEASR_QA_BUILD',None)
    work=out/'work';work.mkdir()
    with (evidence/'pyinstaller.log').open('wb') as log:
        subprocess.run([sys.executable,'-m','PyInstaller','--clean','--noconfirm',
                        '--distpath',str(out/'payload'),'--workpath',str(work),str(stage/'packaging/2byteasr_main.spec')],
                       cwd=stage,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    print(json.dumps(dict(payload=str(out/'payload/2ByteASR'),status='built')),flush=True)


if __name__ == '__main__': main()
