# SPDX-License-Identifier: GPL-3.0-only
"""Identity regression cases, including updated metadata over an old keg."""
import copy
import json
from pathlib import Path
import pytest
from scripts.macos_media_contract import (digest,keg_version,verify_media_formula,
    verify_keg_receipt,verify_binary_evidence,load_verified_tools)
from scripts.macos_install_media import install_action

LOCK=json.loads((Path(__file__).resolve().parents[1]/'packaging/macos/native-dependencies.lock.json').read_text('utf8'))


def formula(name,installed):
    e=LOCK['media'][name]
    return dict(name=name,versions=dict(stable=e['version']),revision=e['revision'],
                bottle=dict(stable=dict(files=dict(arm64_sequoia=e['arm64_sequoia_bottle']))),
                installed=[dict(version=v) for v in installed])


@pytest.mark.parametrize('name,old',[('ffmpeg','9.0.1_1'),('mpv','0.41.0_9')])
def test_updated_formula_never_proves_an_old_installed_revision(name,old):
    f=formula(name,[old])
    assert verify_media_formula(f,name,LOCK['media'][name],require_installed=False)['installed_checked'] is False
    with pytest.raises(RuntimeError,match='Installed keg differs'):verify_media_formula(f,name,LOCK['media'][name])
    assert install_action(f)=='reinstall'


@pytest.mark.parametrize('name',['ffmpeg','mpv'])
def test_missing_target_and_preinstalled_target_have_explicit_acquisition(name):
    e=LOCK['media'][name];f=formula(name,[])
    assert install_action(f)=='install'
    with pytest.raises(RuntimeError,match='Installed keg differs'):verify_media_formula(f,name,e)
    f['installed']=[dict(version=keg_version(e))]
    assert verify_media_formula(f,name,e)['installed_checked'] is True
    # Correct pkg_version alone does not prove selected bottle provenance.
    assert install_action(f)=='reinstall'


def sealed(tmp_path):
    lp=tmp_path/'lock.json';lp.write_text(json.dumps(LOCK),'utf8')
    record=dict(passed=True,target='darwin-arm64',core_commit=LOCK['homebrew_core']['commit'],lock_sha256=digest(lp),media={})
    for name,e in LOCK['media'].items():
        keg=tmp_path/name/keg_version(e);(keg/'bin').mkdir(parents=True)
        tab=dict(arch='arm64',poured_from_bottle=True,source=dict(versions=dict(stable=e['version']),tap_git_head=LOCK['homebrew_core']['commit']))
        rp=keg/'INSTALL_RECEIPT.json';rp.write_text(json.dumps(tab),'utf8')
        entry=dict(keg=str(keg),receipt_sha256=digest(rp),archive=dict(sha256=e['arm64_sequoia_bottle']['sha256'],url=e['arm64_sequoia_bottle']['url']),tools={})
        for binary in (['ffmpeg','ffprobe'] if name=='ffmpeg' else ['mpv']):
            p=keg/'bin'/binary;p.write_bytes(b'owned fixture executable')
            entry['tools'][binary]=dict(path=str(p),path_selected=str(p),sha256=digest(p),architecture='arm64',exit_code=0,version=binary+' '+e['version'])
        record['media'][name]=entry
    receipt=tmp_path/'media.json';receipt.write_text(json.dumps(record),'utf8')
    return lp,receipt,record


def test_builder_consumes_sealed_paths_without_path_or_rolling_metadata(tmp_path,monkeypatch):
    lp,rp,record=sealed(tmp_path)
    invoked=[]
    def output(cmd,**kwargs):
        invoked.append(cmd)
        if cmd[0]=='/usr/bin/lipo':return 'arm64\n'
        return next(t['version'] for e in record['media'].values() for t in e['tools'].values() if t['path']==cmd[0])+'\n'
    monkeypatch.setattr('scripts.macos_media_contract.subprocess.check_output',output)
    monkeypatch.setenv('PATH','another-untrusted-tool-directory')
    tools=load_verified_tools(rp,lp)
    assert set(tools)=={'ffmpeg','ffprobe','mpv'}
    assert {c[0] for c in invoked if c[0]!='/usr/bin/lipo'}=={t['path'] for t in tools.values()}
    Path(tools['ffmpeg']['path']).write_bytes(b'replaced')
    with pytest.raises(RuntimeError,match='digest differs'):load_verified_tools(rp,lp)


@pytest.mark.parametrize('case',['archive','architecture','old_keg','path','receipt'])
def test_acquisition_installation_and_execution_are_separate_checks(tmp_path,case,monkeypatch):
    lp,rp,record=sealed(tmp_path);e=record['media']['mpv'];tool=e['tools']['mpv']
    if case=='archive':e['archive']['sha256']='0'*64
    elif case=='architecture':tool['architecture']='x86_64'
    elif case=='old_keg':e['keg']=str(tmp_path/'mpv/0.41.0_9')
    elif case=='path':tool['path_selected']=str(tmp_path/'other/mpv')
    else:Path(e['keg'],'INSTALL_RECEIPT.json').write_text('{}','utf8')
    rp.write_text(json.dumps(record),'utf8')
    monkeypatch.setattr('scripts.macos_media_contract.subprocess.check_output',lambda cmd,**kw:'arm64\n' if cmd[0]=='/usr/bin/lipo' else next(t['version'] for entry in record['media'].values() for t in entry['tools'].values() if t['path']==cmd[0])+'\n')
    with pytest.raises((RuntimeError,FileNotFoundError)):load_verified_tools(rp,lp)


def test_receipt_revision_and_bottle_architecture_are_required(tmp_path):
    e=LOCK['media']['mpv'];keg=tmp_path/'mpv/0.41.0_10'
    tab=dict(arch='arm64',poured_from_bottle=True,source=dict(versions=dict(stable='0.41.0'),revision=9))
    with pytest.raises(RuntimeError,match='revision differs'):verify_keg_receipt(tab,keg,'mpv',e)
    tab['source']['revision']=10;verify_keg_receipt(tab,keg,'mpv',e)
    tab['poured_from_bottle']=False
    with pytest.raises(RuntimeError,match='poured bottle'):verify_keg_receipt(tab,keg,'mpv',e)
