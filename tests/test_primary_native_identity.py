"""Primary native identity contract; legacy switches cannot choose another ASR."""
import copy
import json
from types import SimpleNamespace
import pytest

from twobyteasr.storage.settings import DEFAULT_SETTINGS, _merge_known_settings
from twobyteasr.recognition.speaker_strategy import resolve
from twobyteasr.recognition.service import RunOptions
from twobyteasr.recognition.speaker_recovery import candidate_snapshot
from twobyteasr.projects.studio_project import project_from_runtime_cues, load_project, save_project
from twobyteasr.projects.speaker_organization import organize
from twobyteasr.recognition.recognition_profiles import ProjectProfileStore, ProjectProfile

@pytest.mark.parametrize('backend,expected', [('moss','moss'),('api','native'),('sensevoice','native')])
@pytest.mark.parametrize('retired', ['single','nemotron','moss','ecapa'])
def test_legacy_migration_is_idempotent_without_changing_primary(backend, expected, retired):
    supplied=copy.deepcopy(DEFAULT_SETTINGS)
    supplied['models'].update(primary_asr_backend=backend,speaker_source=retired)
    supplied['switches']['speaker_enabled']=False
    normalized,_=_merge_known_settings(DEFAULT_SETTINGS,supplied)
    again,_=_merge_known_settings(DEFAULT_SETTINGS,normalized)
    assert normalized==again
    assert normalized['models']['primary_asr_backend']==backend
    assert resolve(normalized, 'single')==expected
    assert normalized['models']['speaker_source']==expected

def test_frozen_options_use_primary_even_with_stale_single_snapshot():
    settings=copy.deepcopy(DEFAULT_SETTINGS)
    settings['models']['speaker_source']='single'
    legacy=SimpleNamespace(RUNTIME_SETTINGS=settings,canonicalize_runtime_game_name=str,runtime_game_identity=str)
    options=RunOptions(speaker_source='single',settings_snapshot_json=json.dumps(settings))
    assert options.create_runtime_context(legacy).speaker_source=='moss'

@pytest.mark.parametrize('labels', [('S01',),('S01','S02')])
def test_native_low_frequency_rows_survive_old_single_bookmark_and_editorial_merge(tmp_path,labels):
    from twobyteasr.exports.studio_subtitle_export import export_subtitle_artifacts, SubtitleExportOptions
    rows=[dict(start=i*2,end=i*2+1,text=f'保留人工{i} 22',speaker=s) for i,s in enumerate(labels)]
    evidence=candidate_snapshot(rows,source='single')
    evidence['processing']={'mode':'single','primary_backend':'moss'}
    cues=[SimpleNamespace(**r) for r in rows]
    p=project_from_runtime_cues(tmp_path/'missing.wav',cues,generation_metadata={'speaker_recovery':evidence})
    assert {c.speaker_id for c in p.cues}==set(labels)
    originals=copy.deepcopy(p.generation_metadata['speaker_recovery']['raw_segments'])
    if len(labels)>1:
        p=organize(p,[labels[1]],'merge',target=labels[0])
        p.speakers[0].name='人工改名'
        p.cues[0].text='人工合轨后内容'
    save_project(p,tmp_path/'copy.2byteproj')
    restored=load_project(tmp_path/'copy.2byteproj')
    assert [(c.text,c.speaker_id,c.start_ms,c.end_ms) for c in restored.cues]==[(c.text,c.speaker_id,c.start_ms,c.end_ms) for c in p.cues]
    assert restored.generation_metadata['speaker_recovery']['raw_segments']==originals
    outputs=export_subtitle_artifacts(restored,tmp_path/'export','native',SubtitleExportOptions(speaker_mode='per_speaker'))
    assert len(outputs)==1

def test_profile_snapshot_roles_are_authoritative_and_manual_change_marked_custom(tmp_path):
    store=ProjectProfileStore(tmp_path/'profiles.json')
    p=store.create('Qwen api',primary_asr='api',recognition_plan='api',
        asr_config={'primary_asr_backend':'api','firered_asr_backend':'off','qwen_asr_backend':'api'})
    changed=store.update_asr_config(p.id,{'primary_asr_backend':'moss','firered_asr_backend':'local','qwen_asr_backend':'local'})
    assert changed.name=='Qwen api'
    assert (changed.primary_asr,changed.timestamp_model,changed.evidence_model)==('moss','local','local')
    assert changed.recognition_plan=='custom'
    reloaded=store.get(p.id)
    assert reloaded.asr_config==changed.asr_config
    assert reloaded.primary_asr=='moss'

def test_model_without_native_speakers_is_still_selectable():
    from twobyteasr.providers.cloud_asr_jobs import validate_speaker_strategy
    from twobyteasr.providers.spark_asr import MODEL
    endpoint={'model':MODEL,'speaker_source':'native'}
    assert validate_speaker_strategy(endpoint) is endpoint
