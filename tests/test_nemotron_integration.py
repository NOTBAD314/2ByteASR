import json
from pathlib import Path


def test_historical_nemotron_policy_save_reopen_grouping_export(tmp_path):
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioSpeaker,StudioCue
    from twobyteasr.projects.speaker_organization import apply_new_project_policy,organize
    from twobyteasr.exports.studio_subtitle_export import export_subtitle_artifacts,SubtitleExportOptions
    p=SubtitleProject(media=StudioMedia('fixture.mp4',duration_ms=3000),
        speakers=[StudioSpeaker('NEMO_01'),StudioSpeaker('NEMO_02')],
        cues=[StudioCue('a',0,1000,'主声','NEMO_01'),StudioCue('b',1000,1600,'回话','NEMO_02')])
    p.generation_metadata['speaker_recovery']={'processing':{'mode':'nemotron'},'raw_segments':[]}
    apply_new_project_policy(p)
    assert len(p.speakers)==2 and not any(s.is_host for s in p.speakers)
    original=p.to_dict();grouped=organize(p,{'NEMO_02'},'background')
    reopened=SubtitleProject.from_dict(json.loads(json.dumps(grouped.to_dict())))
    restored=organize(reopened,{'GAME_BACKGROUND'},'restore')
    assert [(c.text,c.speaker_id) for c in restored.cues]==[(c['text'],c['speaker_id']) for c in original['cues']]
    artifacts=export_subtitle_artifacts(restored,tmp_path,'nemotron-contract',SubtitleExportOptions(frozenset({'srt','json'}),'both'))
    assert len(artifacts)==6 and all(a.path.is_file() for a in artifacts)
    lane=[a for a in artifacts if a.format=='srt' and a.speaker_id=='NEMO_02'][0]
    assert '回话' in lane.path.read_text('utf8') and '主声' not in lane.path.read_text('utf8')
    assert restored.generation_metadata['speaker_organization']['cue_origins']['b']=='NEMO_02'



def test_retired_backend_is_absent_from_current_sources_and_old_selection_disabled():
    from twobyteasr.local_models.model_workshop import MODELS
    from twobyteasr.app.ui import ASR_API_PRESETS
    from twobyteasr.recognition.speaker_strategy import resolve
    root=Path(__file__).parents[1]
    lock=json.loads((root/'dependencies.lock.json').read_text('utf8'))
    assert 'nemotron' not in lock['models'] and 'nemotron' not in lock['environments']
    assert not {'nemotron','qwen31_flash','qwen_audio_asr_flash','qwen_audio_filetrans'} & {m.key for m in MODELS}
    assert not {'qwen_filetrans','qwen31_flash','dashscope_qwen_audio'} & set(ASR_API_PRESETS)
    assert resolve({'models':{'speaker_source':'nemotron'}})=='single'
    assert {'qwen_local','qwen_aligner','qwen31_filetrans'} <= {m.key for m in MODELS}
    for file in ['nemotron_worker.py','scripts/install_nemotron.py','scripts/setup_nemotron_backend.ps1',
                 'twobyteasr/nemotron_diarization.py','twobyteasr/nemotron_stream.py']:
        assert not (root/file).exists()


def test_retired_settings_migration_is_idempotent_keeps_workspace_and_main_roles():
    from twobyteasr.storage.settings import _merge_known_settings,DEFAULT_SETTINGS
    models=dict(primary_asr_backend='moss',qwen_asr_backend='local',speaker_source='nemotron',
       qwen_asr_api_provider='qwen_filetrans',qwen_asr_api_model='qwen-audio-3.0-asr-flash-filetrans',
       qwen_asr_api_protocol='dashscope_filetrans',
       qwen_asr_api_url='https://my-workspace.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/asr/transcription',
       oss_bucket='my-private-bucket',oss_endpoint='oss-cn-beijing.aliyuncs.com')
    upgraded,warnings=_merge_known_settings(DEFAULT_SETTINGS,{'models':models})
    twice,second_warnings=_merge_known_settings(DEFAULT_SETTINGS,upgraded)
    assert upgraded==twice
    assert upgraded['models']['qwen_asr_api_model']=='qwen-audio-3.1-asr-flash-filetrans'
    assert upgraded['models']['qwen_asr_api_provider']=='qwen31_filetrans'
    assert upgraded['models']['qwen_asr_api_url']==models['qwen_asr_api_url']
    assert upgraded['models']['primary_asr_backend']=='moss' and upgraded['models']['qwen_asr_backend']=='local'
    assert upgraded['models']['speaker_source']=='single' and upgraded['models']['oss_bucket']==models['oss_bucket']
    assert any('retired' in x for x in warnings) and not any('retired' in x for x in second_warnings)
