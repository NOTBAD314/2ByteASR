from twobyteasr.recognition.recognition_profiles import ProjectProfileStore

def test_only_started_snapshot_wins_over_selected_saved_and_renamed(tmp_path):
    store = ProjectProfileStore(tmp_path/'profiles.json')
    a = store.create('实际用的', asr_config={'primary_asr_backend':'moss'})
    store.record_started(a.id, {'asr_config': {'primary_asr_backend':'qwen_audio'}})
    b = store.create('仅保存', asr_config={'primary_asr_backend':'firered'})
    store.set_last_selected(b.id)
    store.update(a.id, name='重命名')
    restored = store.startup_profile()
    assert restored.id == a.id and restored.name == '重命名'
    assert restored.asr_config['primary_asr_backend'] == 'qwen_audio'
    assert store.get(a.id).asr_config['primary_asr_backend'] == 'moss'

def test_deleted_used_snapshot_does_not_choose_another_provider(tmp_path):
    store = ProjectProfileStore(tmp_path/'profiles.json')
    a = store.create('用过')
    store.record_started(a.id, {'asr_config': {'primary_asr_backend':'qwen_audio'}})
    store.create('没用过')
    store.delete(a.id)
    assert store.startup_profile().asr_config['primary_asr_backend'] == 'qwen_audio'

def test_legacy_selected_fallback_and_custom_started(tmp_path):
    store = ProjectProfileStore(tmp_path/'profiles.json')
    a = store.create('旧记录')
    assert store.startup_profile().id == a.id
    store.record_started('', {'asr_config': {'primary_asr_backend':'moss'}})
    assert store.startup_profile().asr_config['primary_asr_backend'] == 'moss'
    assert store.startup_profile().id == '' and '已删除' not in store.startup_profile().name
