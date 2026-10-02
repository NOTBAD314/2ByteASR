# SPDX-License-Identifier: GPL-3.0-only
"""Pour official bottles with Homebrew from a fixed official core snapshot.

Lock updates are separate reviewed operations; this installer never selects
latest or rewrites expected values. Homebrew resolves dependencies/relocation.
"""
from __future__ import annotations
import argparse
import contextlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.macos_media_contract import digest,keg_version,formula_name,verify_media_formula,verify_keg_receipt,verify_binary_evidence,verify_required_filters


def install_action(formula: dict) -> str:
    # Reinstall only these media formulae if present, including the correct
    # version: a preinstalled receipt has not proved this acquisition yet.
    return 'reinstall' if formula.get('installed') else 'install'


@contextlib.contextmanager
def isolated_core_checkout(core_path: Path,selected: Path,boundary: Path):
    """Keep the runner's entire tap, including deliberate image modifications.

    Only formula metadata is switched. No keg/tool is removed or globally
    upgraded. Restore the original tap even if download/installation fails.
    The builder consumes the sealed installation receipt, never this restored
    (potentially different) metadata.
    """
    boundary=boundary.resolve();selected=selected.resolve()
    if not selected.is_relative_to(boundary) or selected==core_path.resolve():raise RuntimeError('Unsafe selected core boundary')
    backup=boundary/'runner-core-original'
    if backup.exists():raise RuntimeError('Original core backup already exists')
    present=core_path.exists() or core_path.is_symlink()
    if present:core_path.rename(backup)
    else:core_path.parent.mkdir(parents=True,exist_ok=True)
    activated=False
    try:
        selected.rename(core_path);activated=True
        yield
    finally:
        if activated:core_path.rename(selected)
        if present:backup.rename(core_path)


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--lock',type=Path,default=ROOT/'packaging/macos/native-dependencies.lock.json')
    args=parser.parse_args(argv)
    if sys.platform!='darwin' or platform.machine()!='arm64' or platform.mac_ver()[0].split('.')[0]!='15':
        raise SystemExit('The locked arm64_sequoia bottles require a native macOS 15 arm64 host')
    out=args.output.resolve()
    if 'tmp' not in {p.lower() for p in out.parts} or out.exists():raise SystemExit('Use a fresh isolated tmp media directory')
    out.mkdir(parents=True)
    lock=json.loads(args.lock.read_text('utf8'));core=lock['homebrew_core']
    selected_names={formula_name(name, expected):name for name,expected in lock['media'].items()}
    if len(selected_names)!=len(lock['media']):raise RuntimeError('Duplicate selected media formula')
    env=dict(os.environ)
    for key in ('HOMEBREW_FORCE_API_AUTO_UPDATE','HOMEBREW_API_DOMAIN','HOMEBREW_BOTTLE_DOMAIN','HOMEBREW_ARTIFACT_DOMAIN'):
        env.pop(key,None)
    env.update(HOMEBREW_NO_AUTO_UPDATE='1',HOMEBREW_NO_INSTALL_FROM_API='1',
               HOMEBREW_NO_INSTALL_CLEANUP='1',HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK='1',HOMEBREW_NO_ANALYTICS='1')
    record=dict(target='darwin-arm64',macos=platform.mac_ver()[0],lock_sha256=digest(args.lock),
                core_commit=core['commit'],passed=False,stage='inspect_host',media={})
    receipt=out/'media-install.json'
    def save():receipt.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n','utf8')
    def command(cmd,timeout=900):
        result=subprocess.run(list(map(str,cmd)),env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
        with (out/'install.log').open('a',encoding='utf8') as log:
            log.write('\nCOMMAND '+repr(list(map(str,cmd)))+'\n'+result.stdout+result.stderr)
        if result.returncode:raise RuntimeError(f'Command failed ({result.returncode}): {cmd}; see install.log')
        return result.stdout.strip()
    save()
    try:
        brew=shutil.which('brew')
        if not brew:raise RuntimeError('Runner Homebrew is missing')
        record['brew']=dict(path=brew,real_path=str(Path(brew).resolve()),version=command([brew,'--version']))
        record['before']=dict(path=os.environ.get('PATH'),environment={k:v for k,v in os.environ.items() if k.startswith('HOMEBREW_') and not any(s in k for s in ('TOKEN','KEY','SECRET','PASSWORD'))},
            installed=command([brew,'list','--versions']),config=command([brew,'config']),cache=command([brew,'--cache']))
        core_path=Path(command([brew,'--repository']))/'Library/Taps/homebrew/homebrew-core'
        record.update(stage='pin_official_core',core_path=str(core_path));save()
        if core_path.exists():record['before']['core_status']=command(['git','-C',core_path,'status','--porcelain'])
        selected=out/'selected-core';selected.mkdir()
        command(['git','init',selected]);command(['git','-C',selected,'remote','add','origin',core['repository']])
        command(['git','-C',selected,'fetch','--depth=1','origin',core['commit']])
        command(['git','-C',selected,'checkout','--detach',core['commit']])
        if command(['git','-C',selected,'rev-parse','HEAD'])!=core['commit']:raise RuntimeError('Core snapshot differs')
        for name,expected in lock['media'].items():
            if digest(selected/expected['formula_path'])!=expected['formula_sha256']:raise RuntimeError('Formula definition digest differs: '+name)
        with isolated_core_checkout(core_path,selected,out):
            before=json.loads(command([brew,'info','--json=v2',*selected_names]))
            (out/'formula-before.json').write_text(json.dumps(before,indent=2)+'\n','utf8')
            for formula in before['formulae']:
                name=selected_names[formula['name']];expected=lock['media'][name]
                declaration=verify_media_formula(formula,name,expected,require_installed=False)
                record['media'][name]=dict(declaration=declaration,installed_before=formula.get('installed',[]),action=install_action(formula))
            if set(record['media'])!=set(lock['media']):raise RuntimeError('Incomplete selected formula identities')
            record['stage']='fetch_selected_bottles';save()
            command([brew,'fetch','--bottle-tag='+core['bottle_tag'],*selected_names])
            for name,expected in lock['media'].items():
                selected_name=formula_name(name,expected)
                archive=Path(command([brew,'--cache','--bottle-tag='+core['bottle_tag'],selected_name]))
                if digest(archive)!=expected['arm64_sequoia_bottle']['sha256']:raise RuntimeError('Downloaded bottle digest differs: '+name)
                with tarfile.open(archive) as bundle:
                    roots={m.name.split('/')[1] for m in bundle if len(m.name.split('/'))>=2 and m.name.split('/')[0]==selected_name}
                    if roots!={keg_version(expected)}:raise RuntimeError('Bottle pkg_version differs: '+name)
                record['media'][name]['archive']=dict(path=str(archive),bytes=archive.stat().st_size,sha256=digest(archive),url=expected['arm64_sequoia_bottle']['url'],tag=core['bottle_tag'])
            record['stage']='homebrew_pour_and_relocate';save()
            for name,expected in lock['media'].items():command([brew,record['media'][name]['action'],'--force-bottle',formula_name(name,expected)])
            after=json.loads(command([brew,'info','--json=v2',*selected_names]))
            (out/'formula-after.json').write_text(json.dumps(after,indent=2)+'\n','utf8')
            cellar=Path(command([brew,'--cellar']))
            for formula in after['formulae']:
                name=selected_names[formula['name']];expected=lock['media'][name];entry=record['media'][name]
                verify_media_formula(formula,name,expected)
                keg=cellar/formula_name(name,expected)/keg_version(expected);rp=keg/'INSTALL_RECEIPT.json';tab=json.loads(rp.read_text('utf8'))
                verify_keg_receipt(tab,keg,name,expected)
                if tab.get('source',{}).get('tap_git_head')!=core['commit']:raise RuntimeError('Installed receipt did not use selected core snapshot: '+name)
                if digest(Path(entry['archive']['path']))!=entry['archive']['sha256']:raise RuntimeError('Bottle changed during installation: '+name)
                entry.update(keg=str(keg),receipt=tab,receipt_sha256=digest(rp),tools={})
                for binary in (['ffmpeg','ffprobe'] if name=='ffmpeg' else ['mpv']):
                    # Keg-only ffmpeg-full needs no global link/force-link.
                    # The selected keg precedes other programs only in this
                    # install process; the builder consumes sealed paths.
                    env['PATH']=str(keg/'bin')+os.pathsep+env['PATH']
                    selected_executable=shutil.which(binary,path=env['PATH'])
                    if not selected_executable:raise RuntimeError('Installed executable absent from PATH: '+binary)
                    real=Path(selected_executable).resolve();version=command([real,'--version' if binary=='mpv' else '-version'])
                    tool=dict(path_selected=selected_executable,path=str(real),sha256=digest(real),architecture=command(['/usr/bin/lipo','-archs',real]),exit_code=0,version=version.splitlines()[0],version_build_configuration=version)
                    verify_binary_evidence(tool,keg,expected);entry['tools'][binary]=tool
                    if binary=='ffmpeg':
                        filters=command([real,'-hide_banner','-filters'])
                        required=expected.get('required_filters',[])
                        verify_required_filters(filters,required)
                        entry['verified_filters']=required
        record.update(stage='verified',passed=True,runner_core_restored=True,selected_core_snapshot=str(selected),environment_used={k:env[k] for k in ('HOMEBREW_NO_AUTO_UPDATE','HOMEBREW_NO_INSTALL_FROM_API','HOMEBREW_NO_INSTALL_CLEANUP','HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK','HOMEBREW_NO_ANALYTICS')})
        (out/'brew-installed.txt').write_text(command([brew,'list','--versions'])+'\n','utf8')
        save();print(json.dumps(dict(passed=True,receipt=str(receipt),core_commit=core['commit'])))
        return 0
    except Exception as exc:
        record['error']=str(exc);save();raise


if __name__=='__main__':raise SystemExit(main())
