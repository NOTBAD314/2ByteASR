from pathlib import Path


def test_same_path_atomic_save_invalidates_loaded_identity(tmp_path):
    from twobyteasr.studio.studio_readiness import project_file_identity
    target=tmp_path/'project.2byteproj'
    target.write_text('{"cues":[]}')
    first=project_file_identity(target)
    assert first == project_file_identity(target)
    replacement=tmp_path/'new.tmp'
    replacement.write_text('{"cues":[{"text":"字幕"}]}')
    replacement.replace(target)
    assert first != project_file_identity(target)
    target.unlink()
    assert project_file_identity(target) is None


def test_skipped_stage_has_terminal_report_record(tmp_path, monkeypatch):
    from twobyteasr.recognition import reporting
    media=tmp_path/'video.mp4';media.write_bytes(b'test')
    monkeypatch.setattr(reporting,'REPORT_ROOT',tmp_path)
    reporting.begin_media_report(media,{}, {})
    reporting.record_media_event('stage_skipped',index=6,label='独立文字复核',
        resource='未启用',reason='review_backend_off')
    stage=reporting.active_media_report()['stages'][0]
    assert stage['index']==6 and stage['status']=='skipped'
    assert stage['reason']=='review_backend_off'
