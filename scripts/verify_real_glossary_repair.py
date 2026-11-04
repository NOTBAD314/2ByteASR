"""Explicit normal-UI repair of the approved current 48-cue project and library.

This driver is intentionally not run by unit tests. The human-approved alias
manifest is hashed, and actual writable objects are declared separately from
the isolated settings/diagnostic profile. It never starts recognition.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def sha_file(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--real-project',type=Path,required=True)
    parser.add_argument('--real-glossary',type=Path,required=True)
    parser.add_argument('--approved-aliases',type=Path,required=True)
    parser.add_argument('--approved-sha256',required=True)
    parser.add_argument('--settings-source',type=Path)
    parser.add_argument('--credential-source',type=Path)
    parser.add_argument('--resources-manifest',type=Path)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--exe',type=Path)
    args=parser.parse_args()
    output=args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT/'tmp'):
        raise ValueError('Choose a fresh output under repository tmp')
    project=args.real_project.resolve();glossary=args.real_glossary.resolve()
    if not project.is_file() or project.suffix!='.2byteproj' or glossary.name!='learned_game_terms.json' or not glossary.is_file():
        raise ValueError('Declare the actual existing project and personal glossary JSON')
    aliases=args.approved_aliases.resolve()
    if not aliases.is_file() or not aliases.is_relative_to(ROOT/'tmp') or sha_file(aliases)!=args.approved_sha256.lower():
        raise ValueError('Explicit approved-alias manifest hash mismatch')
    approved=json.loads(aliases.read_text('utf-8-sig'))
    if (approved.get('library_id')!='瓦罗兰特' or {(row.get('source'),row.get('canonical')) for row in approved.get('mappings',())}
            !={('奥特曼','autumn'),('球球','CHIOCHOO')} or len(approved['mappings'])!=2):
        raise ValueError('This audit is limited to the two explicitly authorized aliases')
    raw=json.loads(project.read_text('utf-8-sig'))
    if raw.get('project_id')!='5fea2eace1084b3fa8414dd97bb237e9' or len(raw.get('cues',()))!=48:
        raise ValueError('This audit must use the verified current 48-cue object')
    if args.live and (not args.settings_source or not args.credential_source):
        raise ValueError('Live acceptance requires the existing settings and readonly encrypted credential source')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(output)
    from twobyteasr.test_isolation import install
    install()
    # Startup guard owns a pristine copy; the audit opens the declared real path
    # through normal Home navigation before making any review decision.
    startup=output/'input'/'current48.2byteproj';startup.parent.mkdir()
    shutil.copy2(project,startup)
    shutil.copy2(glossary,output/'input'/'glossary-before.json')
    protected={}
    if args.settings_source:
        if args.settings_source.name!='2byteasr_settings.json':raise ValueError('Unexpected settings filename')
        shutil.copy2(args.settings_source,output/'config'/'2byteasr_settings.json')
        protected[str(args.settings_source.resolve())]=sha_file(args.settings_source)
    if args.credential_source:
        if args.credential_source.name!='secrets.dat':raise ValueError('Unexpected credential filename')
        protected[str(args.credential_source.resolve())]=sha_file(args.credential_source)
    plan={'project_path':str(project),'glossary_path':str(glossary),'project_id':raw['project_id'],
        'project_sha256_before':sha_file(project),'glossary_sha256_before':sha_file(glossary),
        'approved_aliases_path':str(aliases),'approved_aliases_sha256':args.approved_sha256.lower(),
        'approved':approved,'live':bool(args.live),'protected':protected,
        'resources_manifest':str(args.resources_manifest.resolve()) if args.resources_manifest else ''}
    (output/'real-glossary-repair-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),'utf8')
    env=os.environ.copy()
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='real-glossary-repair-live' if args.live else 'real-glossary-repair',
        TWOBYTEASR_STARTUP_PROJECT=str(startup),TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_STARTUP_TRACE=str(output/'startup-trace.jsonl'),QT_QPA_PLATFORM='windows',
        QT_SCALE_FACTOR='1',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',HF_HUB_OFFLINE='1',
        TRANSFORMERS_OFFLINE='1',PYTHONUTF8='1')
    if args.live:
        env.update(TWOBYTEASR_ACCEPTANCE_SETTINGS_SOURCE=str(args.settings_source.resolve()),
            TWOBYTEASR_ACCEPTANCE_CREDENTIAL_SOURCE=str(args.credential_source.resolve()))
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_on_desktop(command,cwd=ROOT,env=env,output=output/'process',timeout=600 if args.live else 180)
    receipt=output/'real-glossary-repair-result.json'
    result=json.loads(receipt.read_text('utf8')) if receipt.is_file() else {'passed':False,'error':'No app receipt'}
    result['process_exit']=code
    result['passed']=bool(result.get('passed') and result.get('gui_shutdown') and code==0)
    (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'passed':result['passed'],'output':str(output),'error':result.get('error')},ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
