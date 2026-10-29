"""Role routing, view restoration and audio-only V1 regression gates."""
import copy
from types import SimpleNamespace
from twobyteasr.storage.settings import DEFAULT_SETTINGS
from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot, task_provider_snapshot
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context


def role_settings():
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings['models'].update(ai_service='grok_account', polish_transport='grok_cli',
        polish_provider='grok_oauth', polish_model='grok-4.7',
        group_provider='deepseek', group_model='deepseek-v4-pro',
        group_base_url='https://api.deepseek.com/v1', speaker_source='single')
    settings['switches']['unified_glm_processing'] = False
    return settings


def test_group_role_wins_over_global_service_and_snapshot_is_frozen(monkeypatch):
    from twobyteasr.providers import llm_config
    monkeypatch.setattr(llm_config, 'read_scoped_api_key', lambda *a: ('fixture', 'fixture'))
    settings = role_settings()
    group = resolve_provider_snapshot(settings, stage='group')
    polish = resolve_provider_snapshot(settings, stage='polish')
    assert (group.provider, group.model, group.endpoint()['base_url']) == ('deepseek', 'deepseek-v4-pro', 'https://api.deepseek.com/v1')
    assert polish.model == 'grok-4.7'
    context = RuntimeContext(provider_snapshots={'polish': polish, 'group': group})
    settings['models']['group_model'] = 'new-model'
    with activate_runtime_context(context):
        assert task_provider_snapshot('group') is group
        assert task_provider_snapshot('polish') is polish
    assert resolve_provider_snapshot(settings).fingerprint != group.fingerprint
    assert 'fixture' not in str(group.public_identity())


def test_unified_uses_group_and_empty_choice_is_not_replaced(monkeypatch):
    from twobyteasr.providers import llm_config
    monkeypatch.setattr(llm_config, 'read_scoped_api_key', lambda *a: ('fixture', 'fixture'))
    settings = role_settings()
    settings['switches']['unified_glm_processing'] = True
    assert resolve_provider_snapshot(settings, stage='polish').model == 'deepseek-v4-pro'
    settings['models']['group_model'] = ''
    assert resolve_provider_snapshot(settings).model == ''


def test_speaker_change_invalidates_group_cache(monkeypatch):
    from twobyteasr.providers import llm_config
    monkeypatch.setattr(llm_config, 'read_scoped_api_key', lambda *a: ('fixture', 'fixture'))
    settings = role_settings()
    before = resolve_provider_snapshot(settings)
    settings['models']['speaker_source'] = 'nemotron'
    assert resolve_provider_snapshot(settings).fingerprint != before.fingerprint


def test_legacy_task_entry_also_captures_current_speaker_and_settings():
    from twobyteasr.recognition.service import RunOptions
    settings=role_settings();settings['models']['speaker_source']='nemotron'
    options=RunOptions.from_legacy(SimpleNamespace(RUNTIME_SETTINGS=settings))
    settings['models']['speaker_source']='single'
    import json
    assert options.speaker_source=='nemotron'
    assert json.loads(options.settings_snapshot_json)['models']['speaker_source']=='nemotron'


def test_legacy_profile_migration_survives_real_settings_load_and_save(tmp_path, monkeypatch):
    import json
    from twobyteasr.providers import llm_config
    from twobyteasr.storage.settings import load_runtime_settings, save_runtime_settings
    monkeypatch.setattr(llm_config, 'read_scoped_api_key', lambda *a: ('fixture', 'fixture'))
    old = {'models': {'ai_service': 'deepseek', 'speaker_source': 'single',
        'provider_profiles': {'deepseek': {'model': 'deepseek-v4-pro',
            'base_url': 'https://api.deepseek.com/v1', 'protocol': 'auto'}}},
        'switches': {'prefer_arabic_numbers': False}}
    (tmp_path/'2byteasr_settings.json').write_text(json.dumps(old), encoding='utf8')
    settings, _, _ = load_runtime_settings(tmp_path)
    for _ in range(2):
        snapshot = resolve_provider_snapshot(settings)
        assert (snapshot.provider, snapshot.model) == ('deepseek', 'deepseek-v4-pro')
        assert settings['models']['speaker_source'] == 'single'
        assert settings['switches']['prefer_arabic_numbers'] is False
        save_runtime_settings(settings, tmp_path)
        settings, _, _ = load_runtime_settings(tmp_path)


def test_complete_roles_and_explicit_empty_cli_are_not_migrated(tmp_path, monkeypatch):
    from twobyteasr.providers import llm_config
    from twobyteasr.storage.settings import save_runtime_settings, load_runtime_settings
    monkeypatch.setattr(llm_config, 'read_scoped_api_key', lambda *a: ('fixture', 'fixture'))
    settings = role_settings()
    settings['models'].update(polish_model='', polish_base_url='')
    save_runtime_settings(settings, tmp_path)
    restored, _, _ = load_runtime_settings(tmp_path)
    assert resolve_provider_snapshot(restored, stage='group').model == 'deepseek-v4-pro'
    assert resolve_provider_snapshot(restored, stage='polish').model == ''
    assert restored['models']['polish_base_url'] == ''


def test_preflight_checks_each_role_snapshot(monkeypatch):
    from twobyteasr.providers import llm_config, ai_providers
    import subtitle_core as core
    import moss_firered_pipeline as pipeline
    monkeypatch.setattr(llm_config,'read_scoped_api_key',lambda *a:('fixture','fixture'))
    settings=role_settings()
    settings['models'].update(polish_transport='openai_compatible',polish_provider='custom',polish_model='proof-model',polish_base_url='https://proof.invalid/v1')
    snapshots={role:resolve_provider_snapshot(settings,stage=role) for role in ('polish','group')}
    context=RuntimeContext(provider_snapshot=snapshots['group'],provider_snapshots=snapshots,asr_settings_snapshot=settings)
    checked=[]
    monkeypatch.setattr(llm_config,'validate_endpoint',lambda endpoint,*a,**k:checked.append(endpoint['model']))
    with activate_runtime_context(context):
        pipeline._preflight_cloud_stages(core)
    assert checked==['proof-model','deepseek-v4-pro']


def test_mp3_enabled_v1_is_audio_only_clock_source(tmp_path):
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia
    from twobyteasr.playback.audio_graph import capture_audio_graph, preview_audio_layers
    from twobyteasr.studio.studio_video_flow import StudioVideoFlowMixin
    media = tmp_path/'voice.mp3'; media.touch()
    project = SubtitleProject(media=StudioMedia(path=str(media), duration_ms=10000))
    project.validate()
    asset = project.media_pool[0]
    asset.video_metadata['has_video'] = False
    asset.audio_metadata['has_audio'] = True
    layers = preview_audio_layers(capture_audio_graph(project), 2300)
    assert layers and layers[0]['audio_only_source']
    host = SimpleNamespace(_multitrack_preview_layers=lambda _: [], _multitrack_audio_layers=lambda _: layers)
    target = StudioVideoFlowMixin._multitrack_preview_target(host, 2300)
    assert target['mode'] == 'audio_only' and target['source_ms'] == 2300
