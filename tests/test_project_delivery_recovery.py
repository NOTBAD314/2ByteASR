import json
import wave
from pathlib import Path
from types import SimpleNamespace
import pytest
from twobyteasr.projects import studio_project as storage
from twobyteasr.recognition.recognition_result import recognition_project_path
from twobyteasr.recognition.recognition_recovery import recover_report


def cue():
    return SimpleNamespace(cue_id='c1',start=12.2,end=13.2,text='Andrea Kimi Antonelli',speaker='S00')


def test_long_title_uses_bounded_internal_path_and_short_temporary_name(tmp_path,monkeypatch):
    library=tmp_path/'Projects'
    monkeypatch.setattr(storage,'project_library_root',lambda:library)
    title='Austin GP： la Ferrari continua a pagare le difficoltà in qualifica？ - con Roberto Chinchero '+('titolo '*16)
    media=tmp_path/(title+'.wav')
    with wave.open(str(media),'wb') as stream:
        stream.setparams((1,2,16000,0,'NONE','not compressed'))
        stream.writeframes(b'\0\0'*32000)
    target=recognition_project_path(media,'a'*32)
    assert target.name=='project.2byteproj' and len(target.parent.name)<40
    from twobyteasr.recognition.recognition_result import media_identity_for_task
    metadata={'job_id':'a'*32,'media_identity':media_identity_for_task(media),'translations':{'c1':'安东内利'}}
    outputs=storage.create_studio_outputs(media,[cue()],txt_path='',generation_metadata=metadata)
    restored=storage.load_project(outputs['project'])
    assert restored.media.display_name==media.name
    assert restored.cues[0].text==cue().text
    assert restored.generation_metadata['translations']==metadata['translations']
    storage.save_project(restored,outputs['project'])  # existing file and backup
    assert not list(target.parent.glob('*.tmp'))


def test_same_title_and_distinct_jobs_never_collide(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'project_library_root',lambda:tmp_path/'Projects')
    assert recognition_project_path('same.mp4','a'*32)!=recognition_project_path('same.mp4','b'*32)
    assert storage.canonical_project_path(tmp_path/'A/same.mp4')!=storage.canonical_project_path(tmp_path/'B/same.mp4')


def test_old_project_name_is_returned_without_renaming(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'project_library_root',lambda:tmp_path)
    old=tmp_path/'old__task_1'/'old.2byteproj'
    old.parent.mkdir();old.write_text('{}','utf8')
    assert recognition_project_path('old.mp4','task')==old
    assert old.read_text('utf8')=='{}'


def test_save_failure_checkpoints_subtitles_and_translations_then_recovers_without_models(tmp_path,monkeypatch):
    library=tmp_path/'Projects'
    monkeypatch.setattr(storage,'project_library_root',lambda:library)
    monkeypatch.setattr('twobyteasr.runtime_paths.user_data_root',lambda:tmp_path/'data')
    target=recognition_project_path('original.mp4','save-test')
    actual_save=storage.save_project
    writes=[]
    def save(project,path,**kwargs):
        writes.append(str(path))
        if Path(path)==target:
            raise FileNotFoundError(2,'injected target save failure',str(path))
        return actual_save(project,path,**kwargs)
    monkeypatch.setattr(storage,'save_project',save)
    metadata={'job_id':'save-test','media_identity':{'fingerprint':'f'*64},
              'translations':{'c1':'安东内利'},'translation_records':{'c1':{'text':'安东内利','source_sha':'known'}}}
    outputs=storage.create_studio_outputs('original.mp4',[cue()],txt_path='',generation_metadata=metadata)
    assert outputs['project']=='' and outputs['generated_cue_count']==1
    assert outputs['project_save_diagnostic']['errno']==2
    checkpoint=storage.load_project(outputs['recovery_project'])
    assert checkpoint.cues[0].text==cue().text
    assert checkpoint.generation_metadata['translation_records']==metadata['translation_records']
    report=tmp_path/'report.json'
    report.write_text(json.dumps({'job_id':'save-test','media':{'path':'original.mp4'},
        'result':{'cue_count':1,'outputs':outputs}}),encoding='utf8')
    before=report.read_bytes()
    recovered=recover_report(report,recovery_root=tmp_path/'restored')
    restored=storage.load_project(recovered)
    assert restored.cues[0].text==cue().text
    assert restored.generation_metadata['translations']==metadata['translations']
    assert report.read_bytes()==before and len(writes)==2
    assert recover_report(report,recovery_root=tmp_path/'restored')==recovered
    assert len(writes)==2


def test_save_failure_outcome_shows_actual_generated_count():
    from twobyteasr.recognition.recognition_outcome import normalize_recognition_outcome
    outcome=normalize_recognition_outcome({'status':'degraded_success','result':{
        'cue_count':1392,'outputs':{'project_error':'No such file or directory','recovery_project':'retained.2byteproj'}}})
    assert outcome.final_cues==1392 and '可恢复' in outcome.title
