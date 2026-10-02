# SPDX-License-Identifier: GPL-3.0-only
"""Identity regression cases, including updated metadata over an old keg."""
import copy
import json
from pathlib import Path
import pytest
from scripts.macos_media_contract import (digest,keg_version,formula_name,verify_required_filters,verify_media_formula,
    verify_keg_receipt,verify_binary_evidence,load_verified_tools)
from scripts.macos_install_media import install_action,isolated_core_checkout

LOCK=json.loads((Path(__file__).resolve().parents[1]/'packaging/macos/native-dependencies.lock.json').read_text('utf8'))


def test_full_formula_identity_and_keg_only_tools_cannot_be_replaced_by_plain_ffmpeg(tmp_path):
    expected=LOCK['media']['ffmpeg']
    selected=formula('ffmpeg',[keg_version(expected)])
    assert selected['name']=='ffmpeg-full'
    verify_media_formula(selected,'ffmpeg',expected)
    selected['name']='ffmpeg'
    with pytest.raises(RuntimeError,match='formula drift'):
        verify_media_formula(selected,'ffmpeg',expected)
    receipt=dict(arch='arm64',poured_from_bottle=True,source=dict(versions=dict(stable=expected['version']),revision=expected['revision']))
    verify_keg_receipt(receipt,tmp_path/'ffmpeg-full'/keg_version(expected),'ffmpeg',expected)
    with pytest.raises(RuntimeError,match='keg path'):
        verify_keg_receipt(receipt,tmp_path/'ffmpeg'/keg_version(expected),'ffmpeg',expected)


def test_version_and_archive_identity_do_not_substitute_for_real_ass_filter_capability():
    ordinary=' ... scale V->V Scale the input\n ... overlay VV->V Overlay\n'
    with pytest.raises(RuntimeError,match='ass'):
        verify_required_filters(ordinary,['ass','overlay','scale'])
    verify_required_filters(ordinary+' ... ass V->V Render ASS\n',['ass','overlay','scale'])


def test_native_ffmpeg9_two_flag_table_is_not_misreported_as_missing_filters():
    # Exact nonprivate CLI rows captured in run36971433917's install.log.
    actual='''
 .. amix              N->A       Audio mixing.
 .. ass               V->V       Render ASS subtitles onto input video using the libass library.
 .. concat            N->N       Concatenate audio and video streams.
 TS overlay           VV->V      Overlay a video source on top of the input.
 .. scale             V->V       Scale the input video size and/or convert the image format.
 .. subtitles         V->V       Render text subtitles onto input video using the libass library.
 .. trim              V->V       Pick one continuous section from the input, drop the rest.
'''
    required=['amix','ass','concat','overlay','scale','subtitles','trim']
    verify_required_filters(actual,required)
    with pytest.raises(RuntimeError,match='ass'):
        verify_required_filters(actual.replace(' .. ass ', ' .. missing_ass '),required)
    with pytest.raises(RuntimeError,match='ass'):
        verify_required_filters('Filters: ass\n  .. ass available by declaration\n', ['ass'])


def test_explicit_full_keg_libraries_survive_pyinstaller_same_basename_deduplication(tmp_path):
    from scripts.macos_build import selected_media_libraries
    from PyInstaller.building.datastruct import normalize_toc
    keg=tmp_path/'ffmpeg-full/9.0.2';(keg/'bin').mkdir(parents=True);(keg/'lib').mkdir()
    tool=keg/'bin/ffmpeg';tool.write_bytes(b'full executable')
    full=keg/'lib/libavfilter.11.dylib';full.write_bytes(b'full libass enabled')
    plain=tmp_path/'ffmpeg/9.0.2/lib/libavfilter.11.dylib';plain.parent.mkdir(parents=True);plain.write_bytes(b'no ass')
    inputs=[(p.name,str(p),'BINARY') for p in selected_media_libraries(tool)]
    # Dependency discovery appends mpv's standard libraries after explicit
    # entries; use PyInstaller's actual normalizer, not a duplicate algorithm.
    actual=normalize_toc(inputs+[(plain.name,str(plain),'BINARY')])
    assert actual==[(full.name,str(full),'BINARY')]


def test_packaged_media_checks_the_relocated_tool_with_no_homebrew_path(tmp_path,monkeypatch):
    from scripts.macos_build import finder_environment,verify_packaged_media
    app=tmp_path/'moved/App.app';tool=app/'Contents/Frameworks/tools/ffmpeg/bin/ffmpeg'
    tool.parent.mkdir(parents=True);tool.write_bytes(b'packaged and rewritten executable')
    commands=[]
    def output(cmd,**kwargs):
        commands.append((cmd,kwargs['env']))
        return 'ffmpeg version 9.0.2\n' if '-version' in cmd else ' ... ass V->V Render ASS\n'
    monkeypatch.setattr('scripts.macos_build.subprocess.check_output',output)
    record=verify_packaged_media(app,['ass'],finder_environment(tmp_path/'tmp/profile'))
    assert record['passed'] and record['path']==str(tool) and record['sha256']==digest(tool)
    assert all(c[0][0]==str(tool) and c[1]['PATH']=='/usr/bin:/bin:/usr/sbin:/sbin' for c in commands)
    with pytest.raises(RuntimeError,match='subtitles'):
        verify_packaged_media(app,['subtitles'],finder_environment(tmp_path/'tmp/profile'))


def formula(name,installed):
    e=LOCK['media'][name]
    return dict(name=formula_name(name,e),versions=dict(stable=e['version']),revision=e['revision'],
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
        keg=tmp_path/formula_name(name,e)/keg_version(e);(keg/'bin').mkdir(parents=True)
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
        if '-filters' in cmd:return '\n'.join(' ... '+name+' V->V Present' for name in LOCK['media']['ffmpeg']['required_filters'])
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
    def output(cmd,**kwargs):
        if cmd[0]=='/usr/bin/lipo':return 'arm64\n'
        if '-filters' in cmd:return '\n'.join(' ... '+name+' V->V Present' for name in LOCK['media']['ffmpeg']['required_filters'])
        return next(t['version'] for entry in record['media'].values() for t in entry['tools'].values() if t['path']==cmd[0])+'\n'
    monkeypatch.setattr('scripts.macos_media_contract.subprocess.check_output',output)
    with pytest.raises((RuntimeError,FileNotFoundError)):load_verified_tools(rp,lp)


def test_receipt_revision_and_bottle_architecture_are_required(tmp_path):
    e=LOCK['media']['mpv'];keg=tmp_path/'mpv/0.41.0_10'
    tab=dict(arch='arm64',poured_from_bottle=True,source=dict(versions=dict(stable='0.41.0'),revision=9))
    with pytest.raises(RuntimeError,match='revision differs'):verify_keg_receipt(tab,keg,'mpv',e)
    tab['source']['revision']=10;verify_keg_receipt(tab,keg,'mpv',e)
    tab['poured_from_bottle']=False
    with pytest.raises(RuntimeError,match='poured bottle'):verify_keg_receipt(tab,keg,'mpv',e)


@pytest.mark.parametrize('fail',[False,True])
def test_runner_dirty_core_and_unrelated_kegs_are_preserved_after_installation(tmp_path,fail):
    runner=tmp_path/'homebrew/Library/Taps/homebrew/homebrew-core'
    runner.mkdir(parents=True)
    (runner/'rustup.rb').write_bytes(b'image-specific modified formula')
    (runner/'openssl@1.1.rb').write_bytes(b'image-specific untracked formula')
    unrelated=tmp_path/'homebrew/Cellar/rustup/1/bin/rustup'
    unrelated.parent.mkdir(parents=True);unrelated.write_bytes(b'preinstalled unrelated tool')
    boundary=tmp_path/'tmp/media';selected=boundary/'selected-core';selected.mkdir(parents=True)
    (selected/'ffmpeg.rb').write_bytes(b'fixed reviewed media definition')
    def install():
        with isolated_core_checkout(runner,selected,boundary):
            assert (runner/'ffmpeg.rb').read_bytes()==b'fixed reviewed media definition'
            assert (boundary/'runner-core-original/rustup.rb').read_bytes()==b'image-specific modified formula'
            assert unrelated.read_bytes()==b'preinstalled unrelated tool'
            if fail:raise RuntimeError('Simulated download digest rejection')
    if fail:
        with pytest.raises(RuntimeError,match='digest rejection'):install()
    else:install()
    assert (runner/'rustup.rb').read_bytes()==b'image-specific modified formula'
    assert (runner/'openssl@1.1.rb').read_bytes()==b'image-specific untracked formula'
    assert (selected/'ffmpeg.rb').read_bytes()==b'fixed reviewed media definition'
    assert not (runner/'ffmpeg.rb').exists()
    assert not (boundary/'runner-core-original').exists()
    assert unrelated.read_bytes()==b'preinstalled unrelated tool'
