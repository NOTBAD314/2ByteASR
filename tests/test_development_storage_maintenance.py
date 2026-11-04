"""Development cleanup only mutates explicitly approved isolated real files."""
import os
from pathlib import Path
import zipfile

import pytest

from scripts import maintain_development_storage as maintenance
REAL_REFERENCES=maintenance.historical_references
STRONG_REFERENCES=maintenance.referenced_paths


@pytest.fixture
def repository(tmp_path, monkeypatch):
    root=tmp_path/'repo'
    root.mkdir()
    (root/'AGENTS.md').write_text('isolated test root',encoding='utf8')
    for name in ('tmp','build','dist','releases','docs'):
        (root/name).mkdir()
    monkeypatch.setattr(maintenance,'process_paths',lambda root:set())
    monkeypatch.setattr(maintenance,'referenced_paths',lambda root:set())
    return root


def approve(plan,action='delete'):
    for item in plan['entries']:
        item.update(approved=True,action=action)
    return plan


def test_default_plan_is_read_only_and_needs_actual_boolean_approval(repository):
    leaf=repository/'tmp'/'owned.log'
    leaf.write_bytes(b'owned')
    plan=maintenance.make_plan(repository,[],scopes=['tmp/owned.log'])
    assert leaf.read_bytes()==b'owned'
    assert not plan['entries'][0]['approved']
    plan['entries'][0].update(approved='false',action='delete')
    assert maintenance.execute(plan,repository)['results']==[]
    assert leaf.exists()


def test_explicit_scope_does_not_traverse_unselected_huge_tree(repository,monkeypatch):
    (repository/'tmp'/'small.log').write_bytes(b'small')
    huge=repository/'tmp'/'huge-copy'
    huge.mkdir();(huge/'keep.log').write_bytes(b'keep')
    original=maintenance.snapshot
    visited=[]
    def limited(path,*args,**kwargs):
        visited.append(path)
        assert not path.is_relative_to(huge)
        return original(path,*args,**kwargs)
    monkeypatch.setattr(maintenance,'snapshot',limited)
    plan=maintenance.make_plan(repository,[],scopes=['tmp/small.log'])
    assert visited==[repository/'tmp'/'small.log']
    assert [item['path'] for item in plan['entries']]==[str(Path('tmp/small.log'))]


def test_one_level_scope_preserves_project_and_unknown_media_but_clears_declared_derivative(repository):
    folder=repository/'tmp'/'mixed'
    folder.mkdir()
    for name in ('project.2byteproj','original.mp4','render.mp4','evidence.json'):
        (folder/name).write_bytes(name.encode())
    plan=maintenance.make_plan(repository,[],scopes=['tmp/mixed'],scope_children=True,
                              derived_files=['tmp/mixed/render.mp4'])
    rows={Path(item['path']).name:item for item in plan['entries']}
    assert rows['project.2byteproj']['protected'] and rows['original.mp4']['protected']
    assert rows['evidence.json']['protected'] and not rows['render.mp4']['protected']
    result=maintenance.execute(approve(plan),repository)
    assert not (folder/'render.mp4').exists()
    assert all((folder/name).exists() for name in ('project.2byteproj','original.mp4','evidence.json'))
    assert sum(item.get('logical_removed_bytes',0) for item in result['results'])==len(b'render.mp4')


@pytest.mark.parametrize('name',['uncommitted.py','project.2byteproj','learned_game_terms.json','settings.json'])
def test_generated_declaration_cannot_override_source_or_user_contract(repository,name):
    leaf=repository/'tmp'/name
    leaf.write_bytes(b'user data')
    plan=maintenance.make_plan(repository,[],scopes=['tmp/'+name],derived_files=['tmp/'+name])
    assert plan['entries'][0]['protected']
    # Even a modified stale plan cannot override current asset classification.
    plan['entries'][0]['protected']=False
    result=maintenance.execute(approve(plan),repository)
    assert result['results'][0]['status']=='skipped' and leaf.exists()


def test_new_running_ancestor_protects_nested_dependencies(repository,monkeypatch):
    folder=repository/'dist'/'candidate'/'_internal'
    folder.mkdir(parents=True)
    leaf=folder/'dependency.dll';leaf.write_bytes(b'dependency')
    plan=maintenance.make_plan(repository,[],scopes=['dist/candidate/_internal/dependency.dll'])
    monkeypatch.setattr(maintenance,'process_paths',lambda root:{repository/'dist'/'candidate'})
    result=maintenance.execute(approve(plan),repository)
    assert result['results'][0]['status']=='skipped' and leaf.exists()


def test_new_referenced_descendant_protects_whole_planned_object(repository,monkeypatch):
    folder=repository/'tmp'/'handoff';folder.mkdir()
    leaf=folder/'handoff.log';leaf.write_bytes(b'current')
    plan=maintenance.make_plan(repository,[],scopes=['tmp/handoff'])
    monkeypatch.setattr(maintenance,'referenced_paths',lambda root:{leaf})
    result=maintenance.execute(approve(plan),repository)
    assert result['results'][0]['status']=='skipped' and leaf.exists()


def test_pins_protect_both_parent_and_descendant_scopes(repository):
    folder=repository/'tmp'/'pinned';folder.mkdir()
    leaf=folder/'keep.log';leaf.write_bytes(b'keep')
    parent=maintenance.make_plan(repository,[leaf],scopes=['tmp/pinned'])
    child=maintenance.make_plan(repository,[folder],scopes=['tmp/pinned/keep.log'])
    assert parent['entries'][0]['protected'] and child['entries'][0]['protected']


def test_archive_stream_verifies_bytes_before_source_deletion(repository,monkeypatch):
    folder=repository/'tmp'/'logs';folder.mkdir()
    leaf=folder/'large.log';content=b'0123456789'*210000;leaf.write_bytes(content)
    plan=approve(maintenance.make_plan(repository,[],scopes=['tmp/logs']),'archive')
    plan['entries'][0]['archive_path']='releases/logs-archive.zip'
    def no_whole_read(*args,**kwargs):
        raise AssertionError('Whole-member reads are prohibited; use a bounded stream')
    monkeypatch.setattr(zipfile.ZipFile,'read',no_whole_read)
    result=maintenance.execute(plan,repository)
    assert result['results'][0]['status']=='removed' and not folder.exists()
    with zipfile.ZipFile(repository/'releases'/'logs-archive.zip') as archive:
        with archive.open(Path('tmp/logs/large.log').as_posix()) as stream:
            assert stream.read()==content


def test_new_use_after_archive_keeps_source_and_reports_verified_archive(repository,monkeypatch):
    folder=repository/'tmp'/'logs';folder.mkdir()
    leaf=folder/'owned.log';leaf.write_bytes(b'owned')
    archive=repository/'releases'/'logs.zip'
    plan=approve(maintenance.make_plan(repository,[],scopes=['tmp/logs']),'archive')
    plan['entries'][0]['archive_path']='releases/logs.zip'
    monkeypatch.setattr(maintenance,'process_paths',lambda root:{folder} if archive.exists() else set())
    result=maintenance.execute(plan,repository)
    assert result['results'][0]['status']=='skipped'
    assert leaf.read_bytes()==b'owned' and archive.is_file()


def test_changed_metadata_and_failed_leaf_do_not_claim_removal(repository,monkeypatch):
    folder=repository/'tmp'/'logs';folder.mkdir()
    first=folder/'first.log';first.write_bytes(b'first')
    second=folder/'second.log';second.write_bytes(b'second')
    plan=approve(maintenance.make_plan(repository,[],scopes=['tmp/logs']))
    second.write_bytes(b'changed-content')
    assert maintenance.execute(plan,repository)['results'][0]['status']=='skipped'
    plan=approve(maintenance.make_plan(repository,[],scopes=['tmp/logs']))
    original=Path.unlink
    def reject_one(path,*args,**kwargs):
        if path==second:raise PermissionError('controlled lock')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',reject_one)
    result=maintenance.execute(plan,repository)['results'][0]
    assert result['status']=='failed' and result['remaining_path']
    assert not first.exists() and second.exists()
    assert result['logical_removed_bytes']==len(b'first') and result['failed']


def test_parent_escape_and_archive_inside_source_are_rejected(repository):
    outside=repository.parent/'outside.log';outside.write_bytes(b'outside')
    with pytest.raises(ValueError,match='escapes'):
        maintenance.make_plan(repository,[],scopes=['../outside.log'])
    folder=repository/'releases'/'logs';folder.mkdir()
    leaf=folder/'owned.log';leaf.write_bytes(b'owned')
    plan=approve(maintenance.make_plan(repository,[],scopes=['releases/logs']),'archive')
    plan['entries'][0]['archive_path']='releases/logs/recursive.zip'
    assert maintenance.execute(plan,repository)['results'][0]['status']=='skipped'
    assert leaf.exists() and outside.exists()


def test_cross_directory_link_is_protected(repository):
    outside=repository.parent/'outside';outside.mkdir()
    (outside/'user.log').write_bytes(b'outside')
    link=repository/'tmp'/'link'
    try:os.symlink(outside,link,target_is_directory=True)
    except OSError:pytest.skip('Host does not permit isolated test symlinks')
    plan=maintenance.make_plan(repository,[])
    row=next(row for row in plan['entries'] if Path(row['path']).name=='link')
    assert row['protected'] and row['issues']
    assert maintenance.execute(approve(plan),repository)['results'][0]['status']=='skipped'
    assert (outside/'user.log').read_bytes()==b'outside'


def test_current_reference_scan_is_exact_and_skips_copied_release_documents(repository,monkeypatch):
    (repository/'docs'/'PROJECT_STATE.md').write_text(
        '[project](../tmp/handoff/result.log)\n[app](../releases/final/candidate/App.exe)\n[launcher](../tmp/launcher.exe)',encoding='utf8')
    (repository/'releases'/'final'/'candidate'/'_internal').mkdir(parents=True)
    (repository/'tmp'/'_internal').mkdir()
    copied=repository/'releases'/'old'/'copied_source'/'docs'
    copied.mkdir(parents=True)
    (copied/'PROJECT_STATE.md').write_text('[obsolete](../../tmp/should-not-be-protected)',encoding='utf8')
    def forbidden(*args,**kwargs):raise AssertionError('No recursive release/source-tree traversal')
    monkeypatch.setattr(Path,'rglob',forbidden)
    refs=REAL_REFERENCES(repository)
    assert repository/'tmp'/'handoff'/'result.log' in refs
    assert repository/'releases'/'final'/'candidate' in refs
    assert repository/'tmp'/'launcher.exe' in refs and repository/'tmp' not in refs
    assert repository/'tmp'/'should-not-be-protected' not in refs
    assert not maintenance.referenced_paths(repository)


def frozen_fixture(root):
    import json
    folder=root/'releases'/'old'/'2ByteASR';folder.mkdir(parents=True)
    (folder/'2ByteASR.exe').write_bytes(b'MZtest executable')
    (folder/'2byteasr_build.json').write_text(json.dumps(dict(source_sha256='a'*64,source_file_count=10,build_channel='verified-test')),'utf8')
    (folder/'python310.dll').write_bytes(b'python')
    (folder/'PySide6').mkdir();(folder/'PySide6'/'Qt6Core.dll').write_bytes(b'qt')
    (folder/'raw_source').mkdir();(folder/'raw_source'/'app.py').write_text('frozen source copy','utf8')
    return folder


def test_verified_old_payload_with_weak_readme_link_can_be_approved(repository):
    folder=frozen_fixture(repository)
    (repository/'docs'/'PROJECT_STATE.md').write_text('[old](../releases/old/2ByteASR/2ByteASR.exe)','utf8')
    rel=str(folder.relative_to(repository))
    default=maintenance.make_plan(repository,[],scopes=[rel])
    assert default['entries'][0]['protected']
    plan=maintenance.make_plan(repository,[],scopes=[rel],generated_bundles=[rel])
    assert plan['entries'][0]['generated_proof'] and not plan['entries'][0]['protected']
    assert plan['entries'][0]['historical_reference']
    assert maintenance.execute(approve(plan),repository)['results'][0]['status']=='removed'


def test_bundle_declaration_never_overrides_added_real_project_or_changed_identity(repository):
    folder=frozen_fixture(repository);rel=str(folder.relative_to(repository))
    plan=maintenance.make_plan(repository,[],scopes=[rel],generated_bundles=[rel])
    (folder/'personal.2byteproj').write_bytes(b'real user project')
    result=maintenance.execute(approve(plan),repository)
    assert result['results'][0]['status']=='skipped' and (folder/'2ByteASR.exe').exists()
    (folder/'personal.2byteproj').unlink()
    (folder/'2ByteASR.exe').write_bytes(b'MZdifferent app')
    assert maintenance.execute(plan,repository)['results'][0]['status']=='skipped'


def test_archive_restore_contract_is_a_strong_reference(repository):
    folder=repository/'releases'/'local-archives'/'retained';folder.mkdir(parents=True)
    (folder/'external-release-dependencies.json').write_text('{"path":"releases/old/source.py"}','utf8')
    assert repository/'releases'/'old'/'source.py' in STRONG_REFERENCES(repository)


def test_one_user_config_does_not_protect_all_verified_old_payload(repository):
    folder=frozen_fixture(repository);rel=str(folder.relative_to(repository))
    config=folder/'2byteasr_settings.json';config.write_bytes(b'preserve exact user settings')
    plan=maintenance.make_plan(repository,[],scopes=[rel],generated_bundles=[rel])
    row=plan['entries'][0]
    assert not row['protected'] and row['retained_asset_paths']==[str(config.relative_to(repository))]
    result=maintenance.execute(approve(plan),repository)['results'][0]
    assert result['status']=='generated_payload_removed_assets_retained'
    assert config.read_bytes()==b'preserve exact user settings'
    assert not (folder/'2ByteASR.exe').exists()
