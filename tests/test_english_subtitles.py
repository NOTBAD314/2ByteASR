"""English subtitles: language, text rules, line breaking (2026-10-14)."""
from types import SimpleNamespace

import pytest

from twobyteasr import english_segmentation as seg
from twobyteasr import english_text as en
from twobyteasr.language_rules import EN, JA, ZH, detect_language, normalize_language, qwen_language_name, \
    resolve_task_language


def segment(segment_id, start, end, text, speaker="S00"):
    return SimpleNamespace(segment_id=segment_id, start=start, end=end, text=text, speaker=speaker, timing_locked=False)


def test_english_is_a_task_language_and_auto_recognizes_it():
    assert normalize_language("en") == EN and normalize_language("English") == EN
    assert qwen_language_name("en") == "English"
    assert detect_language(["So today we're going to try the new boss fight, wish me luck"])[0] == EN
    # A Chinese stream with English names stays Chinese; Japanese stays Japanese.
    assert detect_language(["今天我们打 Boss，然后去 Mondstadt 看看风景，大家记得点赞关注"])[0] == ZH
    assert detect_language(["今日はボスを倒しに行きます、よろしくお願いします"])[0] == JA
    language, evidence = resolve_task_language("en", ["你好"])
    assert language == EN and evidence["decided_by"] == "manual"
    assert resolve_task_language("auto", ["", ""], asr_detected="English")[0] == EN


def test_settings_and_run_options_accept_english():
    from twobyteasr.service import RunOptions
    import copy
    from twobyteasr.settings import DEFAULT_SETTINGS, _merge_known_settings
    payload = copy.deepcopy(DEFAULT_SETTINGS)
    payload["subtitle_language"]["recognition_language"] = "en"
    merged, warnings = _merge_known_settings(DEFAULT_SETTINGS, payload)
    assert merged["subtitle_language"]["recognition_language"] == "en"
    assert not any("subtitle_language" in warning for warning in warnings)
    options = RunOptions(recognition_language="en", subtitle_output="bilingual")
    assert options.recognition_language == "en"
    with pytest.raises(ValueError):
        RunOptions(recognition_language="fr")


def test_english_cleanup_keeps_apostrophes_and_spaces():
    assert en.clean("i don’t think  i'm   ready ,  guys !") == "I don't think I'm ready, guys!"
    assert en.clean("the players’ base") == "the players' base"
    assert en.join(["Hello", "world.", "How are", "you?"]) == "Hello world. How are you?"
    assert en.clean("i.e. it works") == "i.e. it works"


def _lines(text, **kwargs):
    tokens = en.words(text)
    return [" ".join(tokens[a:b]) for a, b in seg.split_tokens(tokens, **kwargs)]


def test_long_sentences_break_between_words_at_good_places():
    text = ("Okay so the plan is that we go around the left side of the map, grab the shield "
            "and then we push into the boss room before the timer runs out")
    lines = _lines(text)
    assert " ".join(lines) == text                                   # nothing added, lost or split inside a word
    assert all(en.display_length(line) <= en.RULES.max_chars for line in lines)
    assert len(lines) >= 3
    endings = {en.word_core(line.split()[-1]) for line in lines[:-1]}
    assert not endings & (seg.DETERMINERS | seg.PREPOSITIONS | {"and", "is"})
    assert any(line.endswith("map,") for line in lines)              # the comma wins
    short = "Nice shot!"
    assert _lines(short) == [short]


def test_names_and_numbers_stay_together():
    text = "We need to get to Mondstadt Cathedral in about 10 minutes or the Fatui Harbinger will escape again"
    lines = _lines(text)
    joined = [" ".join(line.split()) for line in lines]
    assert not any(line.endswith("Mondstadt") for line in joined)
    assert not any(line.endswith(" 10") for line in joined)
    assert not any(line.endswith("Fatui") for line in joined)


def test_cue_times_come_from_aligned_words():
    words = "So we go left here and then we take the big bridge over the river to reach the castle gate".split()
    tokens = [{"text": word, "start": 1.0 + i * 0.3, "end": 1.0 + i * 0.3 + 0.25} for i, word in enumerate(words)]
    cues = seg.group_english([segment(1, 1.0, 1.0 + len(words) * 0.3, " ".join(words))], tokens)
    assert len(cues) >= 2 and " ".join(cue.text for cue in cues) == " ".join(words)
    first_word_of_second = cues[1].text.split()[0]
    index = words.index(first_word_of_second, len(cues[0].text.split()))
    assert cues[1].start == pytest.approx(tokens[index]["start"])
    assert all(cue.end > cue.start for cue in cues)


def test_ai_breaks_are_used_only_when_valid():
    text = "Alright everyone welcome back to the stream today we are finally going to beat the final boss together"
    tokens = en.words(text)
    good = [3, 9, 14]    # a new subtitle after "back", "are" and "the"
    expected = [(0, 4), (4, 10), (10, 15), (15, len(tokens))]
    assert seg.pieces_from_breaks(tokens, good) == expected
    assert seg.pieces_from_breaks(tokens, [99]) is None
    assert seg.pieces_from_breaks(tokens, []) is None                 # one piece would be too long

    def fake(messages):
        assert "Never change, add or remove words" in messages[0]["content"]
        return '{"breaks": {"1": [3, 9, 14]}}'
    cues = seg.group_english_with_ai([segment(1, 0.0, 6.0, text)], complete=fake)
    assert [cue.text for cue in cues] == [" ".join(tokens[a:b]) for a, b in expected]
    cues = seg.group_english_with_ai([segment(1, 0.0, 6.0, text)], complete=lambda _m: "not json")
    assert " ".join(cue.text for cue in cues) == text and all(len(cue.text) <= 42 for cue in cues)


def test_cleanup_inside_an_english_task_keeps_punctuation_chinese_unchanged():
    from twobyteasr.language_rules import language_scope
    from twobyteasr.text_rules import clean_subtitle_text
    with language_scope("en"):
        assert clean_subtitle_text("Wait, don't go — it's a trap!") == "Wait, don't go — it's a trap!"
    with language_scope("zh"):
        assert clean_subtitle_text("等一下，别走。") == "等一下别走"           # Chinese rules exactly as before


def test_english_translation_prompt_and_validation():
    from twobyteasr import subtitle_translation as st
    assert st.validate_translation("GG", "GG") is None                                   # short token may stay
    assert st.validate_translation("We need to grab the shield first", "我们得先拿护盾") is None
    assert st.validate_translation("We need to grab the shield first", "We need to grab the shield first") == "echo_source"
    assert st.validate_translation("We need to grab the shield first", "We must get the shield first") == "no_chinese"
    batch = st.TranslationBatch(lines=(st.BatchLine("c1", "Paimon is so loud", "", True),))
    messages = st.build_messages(batch, glossary_pairs=[("Paimon", "派蒙")], source_language="en")
    assert "英语游戏实况" in messages[0]["content"]
    assert '"en": "Paimon"' in messages[1]["content"] and st.EN_PROMPT_VERSION in messages[1]["content"]
    assert "日语游戏实况" in st.build_messages(batch)[0]["content"]                    # Japanese unchanged
    assert st.prompt_version_for("en") != st.prompt_version_for("ja")


def test_studio_refine_splits_english_only_at_spaces():
    from twobyteasr.language_rules import language_scope
    from twobyteasr.sentence_refine import refine_system_prompt, validate_action
    text = "Okay so the plan is simple, we go left and grab the shield"
    with language_scope("en"):
        good = validate_action(text, {"cue_id": "1", "action": "split", "split_after_chars": [text.index(",")]})
        assert good is not None and good.action == "split"
        assert validate_action(text, {"cue_id": "1", "action": "split", "split_after_chars": [2]}) is None   # inside "Okay"
        assert validate_action(text, {"cue_id": "1", "action": "space", "space_after_chars": [3]}).action == "keep"
    assert "Never cut inside a word" in refine_system_prompt("en")


def test_english_projects_get_english_reading_checks_and_merges():
    from twobyteasr.studio_commands import merge_cues_command
    from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject
    from twobyteasr.studio_qc import SubtitleQCEngine

    def project(code):
        cues = [StudioCue("a", 0, 2000, "This line is a normal English subtitle"),
                StudioCue("b", 2000, 3000, "and it keeps going")]
        return SubtitleProject(media=StudioMedia(path="x.mp4", duration_ms=4000), cues=cues,
                               generation_metadata={"language": {"code": code}})

    english = project("en")
    flagged = {issue.issue_type for issue in SubtitleQCEngine().analyze(english).issues if issue.cue_id == "a"}
    assert not flagged & {"high_cps", "line_too_long"}          # 19 characters/s and 38 per line read fine in English
    chinese = {issue.issue_type for issue in SubtitleQCEngine().analyze(project("")).issues if issue.cue_id == "a"}
    assert "line_too_long" in chinese                            # the Chinese limits stay as they were
    merge_cues_command(english, ["a", "b"]).redo()
    assert english.cues[0].text == "This line is a normal English subtitle and it keeps going"
