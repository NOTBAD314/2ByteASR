from twobyteasr.recognition.recognition_profiles import ProjectProfileStore


def profile_values():
    return {
        "recognition_plan": "quality",
        "primary_asr": "moss",
        "timestamp_model": "local",
        "evidence_model": "qwen_local",
        "llm_enabled": True,
        "llm_config_ref": "deepseek-default",
        "glossary_ids": ["genshin"],
        "language": "zh",
        "subtitle_mode": "bilingual",
        "subtitle_style_preset": "game-default",
        "render_preset": "1080p-default",
        "export_format": "ass",
        "review_threshold": 0.72,
        "review_strategy": "risk_first",
    }


def test_profile_survives_restart_and_reloads_all_configuration_references(tmp_path):
    path = tmp_path / "profiles.json"
    created = ProjectProfileStore(path).create("原神", **profile_values())
    restarted = ProjectProfileStore(path)
    loaded = restarted.get(created.id)
    assert loaded is not None
    assert loaded.name == "原神"
    assert loaded.primary_asr == "moss"
    assert loaded.glossary_ids == ["genshin"]
    assert loaded.subtitle_style_preset == "game-default"
    assert loaded.render_preset == "1080p-default"
    assert loaded.export_format == "ass"
    assert loaded.review_threshold == 0.72


def test_profile_crud_and_rule_only_recommendation(tmp_path):
    store = ProjectProfileStore(tmp_path / "profiles.json")
    genshin = store.create("原神", **profile_values())
    copied = store.save_as(genshin.id, "直播切片", export_format="srt")
    assert store.rename(copied.id, "通用游戏视频").name == "通用游戏视频"
    used = store.mark_used(genshin.id, [tmp_path / "原神素材" / "a.mp4"])
    recommended, reason = store.recommend([tmp_path / "原神素材" / "b.mp4"])
    assert recommended.id == used.id
    assert reason == "最近用于同目录素材"
    explicit, reason = store.recommend(explicit_profile_id=copied.id)
    assert explicit.id == copied.id and reason == "用户明确选择"
    assert store.delete(copied.id)


def test_profile_recommendation_does_not_guess_game_type(tmp_path):
    store = ProjectProfileStore(tmp_path / "profiles.json")
    store.create("原神", **profile_values())
    profile, reason = store.recommend([tmp_path / "unknown" / "clip.mp4"])
    assert profile is None
    assert reason == ""
