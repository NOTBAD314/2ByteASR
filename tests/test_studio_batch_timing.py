from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.studio.studio_batch_timing import TimingRules, preview, protected_cue_ids


def test_gap_fill_keeps_other_speaker_overlap_and_protected_times():
    cues = [
        StudioCue("a", 0, 700, "a", "speaker-1"),
        StudioCue("b", 900, 1300, "b", "speaker-1"),
        StudioCue("c", 500, 1100, "c", "speaker-2"),
    ]
    changes, issues = preview(cues, {"a", "b", "c"}, {"b", "c"},
                              TimingRules(min_gap=70, fill_gap=500), 3000)
    assert set(changes) == {"a"}
    assert changes["a"].end_ms == 830
    assert not issues
    assert cues[0].end_ms == 700


def test_alignment_targets_exclude_confirmed_locked_and_manual_boundaries():
    cues = [
        StudioCue("confirmed", 0, 600, "a"),
        StudioCue("locked", 700, 1200, "b", "protected-speaker"),
        StudioCue("manual", 1600, 2400, "c"),
        StudioCue("eligible", 2500, 3200, "d"),
    ]
    project = SubtitleProject(media=StudioMedia("media.mp4"), cues=cues, studio_state={
        "review_confirmations": {"confirmed": True},
        "caption_timeline": {"instances": {"manual": {"manual_timing": True}}},
    })
    assert protected_cue_ids(project, cues, {"protected-speaker"}) == {"confirmed", "locked", "manual"}


def test_overlap_rejection_is_checked_again_after_neighbour_is_reverted():
    cues = [
        StudioCue("a", 100, 300, "a", "speaker"),
        StudioCue("b", 330, 550, "b", "speaker"),
        StudioCue("c", 600, 800, "c", "speaker"),
    ]
    changes, issues = preview(cues, {"a", "b", "c"}, {"c"}, TimingRules(shift=100), 3000)
    assert not changes
    assert issues == {"a": "same_speaker_overlap", "b": "same_speaker_overlap"}


def test_too_small_minimum_gap_is_reported_without_cutting_the_left_cue():
    cues = [StudioCue("a", 100, 700, "a", "speaker"), StudioCue("b", 710, 950, "b", "speaker")]
    changes, issues = preview(cues, {"a", "b"}, set(), TimingRules(min_gap=50), 1000)
    assert not changes
    assert issues == {"a": "minimum_gap_requires_review"}


def test_gap_fill_does_not_cross_a_new_speaker_entrance():
    cues = [
        StudioCue("a", 0, 700, "a", "first"),
        StudioCue("b", 1100, 1400, "b", "first"),
        StudioCue("c", 850, 1000, "c", "second"),
    ]
    changes, issues = preview(cues, {"a"}, set(), TimingRules(fill_gap=500), 2000)
    assert not changes and issues == {"a": "other_speaker_overlap"}


def test_timing_presets_keep_other_studio_preferences(tmp_path, monkeypatch):
    import json
    from twobyteasr.studio import studio_batch_timing as module
    settings = tmp_path / "studio.json"
    settings.write_text(json.dumps({"caption_view": "bilingual"}), encoding="utf-8")
    monkeypatch.setattr(module, "studio_settings_path", lambda: settings)
    module.save_timing_preset("Review", {"shift": -120, "frame_snap": True})
    module.save_timing_preset("Captions", {"min_duration": 250})
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["caption_view"] == "bilingual"
    values = module.load_timing_presets()
    assert values["Review"]["shift"] == -120 and values["Review"]["frame_snap"] is True
    assert values["Captions"]["min_duration"] == 250


def test_measured_pause_is_not_filled_even_with_large_display_threshold():
    cues = [StudioCue("a", 0, 700, "a", "same"), StudioCue("b", 1000, 1600, "b", "same")]
    changes, issues = preview(
        cues, {"a"}, set(), TimingRules(fill_gap=500), 2000,
        preserves_pause=lambda left, right: (left.id, right.id) == ("a", "b"),
    )
    assert not changes and issues == {"a": "measured_pause"}
