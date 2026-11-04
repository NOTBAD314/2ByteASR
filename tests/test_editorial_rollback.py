from subtitle_core import (
    SubtitleCue,
    apply_isolated_single_character_rules_safely,
    content_only,
    resolve_isolated_single_character_cues,
)


def test_single_character_pass_never_reorders_overlapping_source_text():
    cues = [
        SubtitleCue(1, 0.0, 2.0, "前一段", speaker="S01"),
        SubtitleCue(2, 1.0, 1.5, "后一段", speaker="S01"),
    ]

    resolved, resolution = resolve_isolated_single_character_cues(cues)

    assert [cue.text for cue in resolved] == ["前一段", "后一段"]
    assert not resolution["omitted_ids"]


def test_meaningful_isolated_character_is_kept_when_it_cannot_merge():
    cues = [
        SubtitleCue(1, 0.0, 1.0, "前文很长", speaker="S01"),
        SubtitleCue(2, 4.0, 4.4, "有", speaker="S01"),
        SubtitleCue(3, 8.0, 9.0, "后文很长", speaker="S01"),
    ]

    resolved, resolution = resolve_isolated_single_character_cues(cues)

    assert [cue.text for cue in resolved] == ["前文很长", "有", "后文很长"]
    assert resolution["kept_ids"] == {2}
    assert not resolution["omitted_ids"]


def test_cosmetic_single_character_failure_rolls_back_instead_of_blocking_export(monkeypatch):
    import twobyteasr.subtitle_rules.segmentation as segmentation

    original = [
        SubtitleCue(1, 0.0, 1.0, "第一句", speaker="S01"),
        SubtitleCue(2, 1.0, 2.0, "第二句", speaker="S01"),
    ]

    def broken_pass(_cues):
        return list(reversed(_cues)), {"omitted_ids": set(), "merged_ids": set()}

    monkeypatch.setattr(segmentation, "resolve_isolated_single_character_cues", broken_pass)
    recovered = apply_isolated_single_character_rules_safely(original)

    assert content_only("".join(cue.text for cue in recovered)) == content_only("第一句第二句")
    assert [cue.text for cue in recovered] == ["第一句", "第二句"]
