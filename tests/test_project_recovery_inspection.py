import json,os
from pathlib import Path
from types import SimpleNamespace
import pytest
from twobyteasr.projects import studio_project as persistence
from twobyteasr.projects.project_recovery_inspection import inspect_recovery
from twobyteasr.projects.studio_project_controller import StudioProjectController


def fixture(tmp_path,*,changed=True):
    p=persistence.SubtitleProject(media=persistence.StudioMedia(path=''),
        cues=[persistence.StudioCue('a',0,1000,'official')],
        asr_evidence={'seg:1':{'nested':[{'text':'é😀','tokens':(1,2,None)}]}})
    path=tmp_path/'project.2byteproj';persistence.save_project(p,path)
    (tmp_path/'autosave').mkdir()
    if changed:p.cues[0].text='recovered'
    candidate=persistence.save_autosave(p,path)
    os.utime(path,ns=(path.stat().st_atime_ns,path.stat().st_mtime_ns-1000000000))
    return path,persistence.load_project(path),Path(candidate)


def test_fingerprint_matches_persisted_content_without_changing_document(tmp_path):
    path,p,_=fixture(tmp_path)
    before=p.to_dict()
    expected=persistence._content_fingerprint_payload(before)
    assert persistence.project_content_fingerprint(p)==expected
    assert p.to_dict()==before
    p.cues[0].text='a real edit'
    assert persistence.project_content_fingerprint(p)!=expected


def test_prepared_recovery_uses_reader_result_without_main_thread_parse_or_hash(tmp_path,monkeypatch):
    path,p,candidate=fixture(tmp_path);inspection=inspect_recovery(path,p)
    assert inspection.matches(path,p,candidate) and not inspection.equivalent
    p._recovery_inspection=inspection
    from twobyteasr.projects import studio_project_controller as controller
    def forbidden(*a,**k):raise AssertionError('GUI must reuse the guarded reader result')
    monkeypatch.setattr(persistence,'project_content_fingerprint',forbidden)
    monkeypatch.setattr(controller,'load_project',forbidden)
    monkeypatch.setattr(controller,'recoverable_autosave',forbidden)
    page=SimpleNamespace(_studio_trace=lambda *a,**k:None,_studio_preferences=lambda:{'recovery_policy':'auto'})
    c=StudioProjectController(page,SimpleNamespace())
    value,recovered=StudioProjectController._resolve_project_recovery.__wrapped__(c,path,p,single_shot_fn=lambda *a:None)
    assert recovered and value.cues[0].text=='recovered' and p.cues[0].text=='official'


@pytest.mark.parametrize('which',['official','checkpoint','overlay','sidecar','new-checkpoint'])
def test_changed_recovery_inputs_reject_stale_preparation(tmp_path,which):
    path,p,candidate=fixture(tmp_path);inspection=inspect_recovery(path,p)
    assert inspection.matches(path,p)
    target={'official':path,'checkpoint':candidate,
        'overlay':candidate.with_name(candidate.name+'.overlay'),
        'sidecar':candidate.with_name(candidate.stem+'.fingerprint.json'),
        'new-checkpoint':candidate.with_name(candidate.stem+'.another.2byteproj')}[which]
    target.write_bytes(target.read_bytes()+b' ' if target.exists() else b'{}')
    assert not inspection.matches(path,p)


def test_equivalent_recovery_preserves_official_and_recovery_files(tmp_path):
    path,p,candidate=fixture(tmp_path,changed=False)
    files={x:x.read_bytes() for x in candidate.parent.iterdir()}
    inspection=inspect_recovery(path,p)
    assert inspection.equivalent and inspection.matches(path,p)
    assert all(x.read_bytes()==data for x,data in files.items())


def test_no_checkpoint_does_not_compute_fingerprint(tmp_path,monkeypatch):
    path,p,candidate=fixture(tmp_path)
    persistence.discard_autosave(candidate)
    monkeypatch.setattr(persistence,'project_content_fingerprint',lambda *a:pytest.fail('no recovery needs no hash'))
    assert inspect_recovery(path,p) is None
