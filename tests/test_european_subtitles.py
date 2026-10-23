"""Spanish, German, French, Portuguese, Italian and Russian subtitles (2026-10-19 user request).

The home 字幕语言 menu and the translation targets gain 西班牙语 / 德语 / 法语 /
葡萄牙语 / 意大利语 / 俄语. They follow the English route (word-based lines,
Qwen3-ForcedAligner timing) with their own word lists, lengths and prompts.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import subtitle_core  # noqa: F401  initialize the legacy facade
from twobyteasr.subtitle_rules import english_segmentation as seg
from twobyteasr.subtitle_rules import european_text as eu
from twobyteasr.subtitle_rules.language_rules import EUROPEAN, detect_language, language_scope, normalize_language, \
    qwen_language_name, resolve_task_language, supports

SAMPLES = {
    "es": "Bueno chicos hoy vamos a intentar derrotar al jefe final porque la semana pasada no pudimos hacerlo "
          "y la verdad es que me da un poco de miedo",
    "de": "Also Leute heute versuchen wir den letzten Boss zu besiegen weil wir es letzte Woche nicht geschafft "
          "haben und ehrlich gesagt habe ich ein bisschen Angst",
    "fr": "Bon les amis aujourd'hui on va essayer de battre le boss final parce que la semaine dernière on n'a pas "
          "réussi et franchement j'ai un peu peur",
    "pt": "Então pessoal hoje a gente vai tentar derrotar o chefe final porque na semana passada não conseguimos e "
          "sinceramente eu estou com um pouco de medo",
    "it": "Allora ragazzi oggi proviamo a sconfiggere il boss finale perché la settimana scorsa non ci siamo "
          "riusciti e sinceramente ho un po di paura",
    "ru": "Итак друзья сегодня мы попробуем победить финального босса потому что на прошлой неделе у нас не "
          "получилось и честно говоря мне немного страшно",
}


def segment(segment_id, start, end, text, speaker="S00"):
    return SimpleNamespace(segment_id=segment_id, start=start, end=end, text=text, speaker=speaker, timing_locked=False)


@pytest.mark.parametrize("code", EUROPEAN)
def test_each_language_is_a_task_language_and_auto_recognizes_it(code):
    assert normalize_language(code) == code and normalize_language(eu.ENGLISH_NAMES[code]) == code
    assert qwen_language_name(code) == eu.ENGLISH_NAMES[code]
    assert supports("qwen_aligner", "align", code) and not supports("firered_aed", "align", code)
    assert detect_language([SAMPLES[code]])[0] == code
    assert resolve_task_language("auto", ["", ""], asr_detected=eu.ENGLISH_NAMES[code])[0] == code


def test_other_languages_are_decided_as_before():
    assert detect_language(["Okay guys welcome back to the stream, let me know in the chat what you want"])[0] == "en"
    assert detect_language(["No way, that was insane, did you see that headshot from across the map"])[0] == "en"
    assert detect_language(["今天我们打 Boss，然后去 Mondstadt 看看风景，大家记得点赞关注"])[0] == "zh"
    assert detect_language(["今日はボスを倒しに行きます、よろしくお願いします"])[0] == "ja"
    assert detect_language(["안녕하세요 여러분 오늘도 방송 시작합니다"])[0] == "ko"


def test_settings_run_options_and_timeline_rule_accept_the_languages():
    import copy
    from twobyteasr.recognition.recognition_choices import language_timeline, spoken_language
    from twobyteasr.recognition.service import RunOptions
    from twobyteasr.storage.settings import DEFAULT_SETTINGS, _merge_known_settings
    payload = copy.deepcopy(DEFAULT_SETTINGS)
    payload["subtitle_language"].update(recognition_language="ru", translation_script="es")
    merged, warnings = _merge_known_settings(DEFAULT_SETTINGS, payload)
    assert (merged["subtitle_language"]["recognition_language"], merged["subtitle_language"]["translation_script"]) \
        == ("ru", "es")
    assert not any("subtitle_language" in warning for warning in warnings)
    assert RunOptions(recognition_language="de", translation_script="fr").recognition_language == "de"
    with pytest.raises(ValueError):
        RunOptions(recognition_language="xx")
    assert spoken_language(merged) == "ru"
    assert language_timeline("local", "es", merged)["rerouted"] is True


@pytest.mark.parametrize("code", EUROPEAN)
def test_lines_break_between_words_and_never_hang_on_a_function_word(code):
    lex = eu.lexicon(code)
    tokens = eu.words(SAMPLES[code])
    lines = [" ".join(tokens[a:b]) for a, b in seg.split_tokens(tokens, lexicon=lex)]
    assert " ".join(lines) == SAMPLES[code]
    # 2026-10-21: a subtitle holds two lines; these 125–145 character samples still need two or three.
    assert len(lines) >= 2 and all(eu.display_length(line) <= lex.rules.cue_max_chars for line in lines)
    hanging = lex.determiners | lex.prepositions | lex.subjects
    assert not [line for line in lines[:-1] if eu.word_core(line.split()[-1]) in hanging], lines


def test_german_keeps_the_clause_final_auxiliary_and_russian_lines_are_shorter():
    tokens = eu.words(SAMPLES["de"])
    lines = [" ".join(tokens[a:b]) for a, b in seg.split_tokens(tokens, lexicon=eu.lexicon("de"))]
    assert not any(line.split()[0] in {"haben", "habe"} and index and lines[index - 1].endswith("geschafft")
                   for index, line in enumerate(lines))
    assert eu.lexicon("ru").rules.max_chars == 39 and eu.lexicon("es").rules.max_chars == 42
    assert eu.lexicon("ru").rules.cue_max_chars == 78 and eu.lexicon("es").rules.cue_max_chars == 84
    # A German clause may end on its auxiliary before "und": "… geschafft haben | und ehrlich gesagt …".
    assert "weil wir es letzte Woche nicht geschafft haben" in lines
    # English is unchanged: the default lexicon is English.
    assert seg.split_tokens(["Nice", "shot!"]) == [(0, 2)]


def test_accented_and_cyrillic_words_match_aligner_times():
    text = "Mañana jugaremos otra vez con el equipo, ¿vale? Сегодня будет весело"
    tokens = eu.words(text)
    rows = [{"text": token.strip(",¿?"), "start": 1.0 + 0.4 * i, "end": 1.3 + 0.4 * i} for i, token in enumerate(tokens)]
    times = seg._word_times(segment(1, 1.0, 6.0, text), tokens, rows, eu.word_core)
    assert all(time is not None for time in times)
    assert eu.word_core("¿Mañana?") == "mañana" and eu.word_core("Сегодня,") == "сегодня"


def test_cleanup_keeps_accents_case_and_french_spacing():
    from twobyteasr.subtitle_rules.text_rules import clean_subtitle_text, content_only
    with language_scope("fr"):
        assert clean_subtitle_text("Quoi ?  C'est   déjà fini !") == "Quoi ? C'est déjà fini !"
    with language_scope("it"):
        assert clean_subtitle_text("i ragazzi  sono qui") == "i ragazzi sono qui"      # no English "I"
    with language_scope("es"):
        assert clean_subtitle_text("¿Qué  pasa, señor?") == "¿Qué pasa, señor?"
    assert content_only("¿Qué pasa?") == "quépasa" and content_only("Привет!") == "привет"


def test_european_finalize_uses_its_lengths():
    from twobyteasr.recognition.pipeline_runtime import finalize_cues
    from twobyteasr.recognition.transcript_data import SubtitleCue
    events = []
    legacy = SimpleNamespace(
        record_run_event=lambda name, **payload: events.append((name, payload)),
        snap_cue_starts_to_vad_onsets=lambda cues, *_a: cues,
        extend_cue_tails_by_speaker=lambda cues, *_a: cues,
        bridge_short_display_gaps=lambda cues, *_a: cues)
    cues = [SubtitleCue(1, 0.0, 0.5, "Сегодня мы попробуем победить босса", speaker="S01")]
    with language_scope("ru"):
        done = finalize_cues(cues, [], [], [], 10.0, 30, legacy)
    assert done[0].text == "Сегодня мы попробуем победить босса"
    assert any(name == "word_cues_finalized" and payload["language"] == "ru" for name, payload in events)


def test_translation_targets_prompts_and_checks():
    from twobyteasr.subtitle_rules import subtitle_translation as st
    assert set(EUROPEAN) <= set(st.TARGETS) and st.TARGET_LABELS["ru"] == "Русский"
    assert "es" not in st.targets_for("es") and "zh-Hans" in st.targets_for("es")
    assert st.normalize_target("Deutsch") == "de" and st.prompt_version_for("fr") == "fr-zh-subtitle-v1"
    src = SAMPLES["es"]
    assert st.validate_translation(src, "好了伙计们，今天我们要打败最终 boss", "zh-Hans", "es") is None
    assert st.validate_translation(src, src, "zh-Hans", "es") == "echo_source"
    assert st.validate_translation(SAMPLES["ru"], SAMPLES["ru"], "zh-Hans", "ru") == "echo_source"
    assert st.validate_translation("今天我们打 boss", "Hoy vamos a derrotar al jefe", "es", "zh") is None
    assert st.validate_translation("今天我们打 boss", "今天我们打 boss 啊", "es", "zh") == "not_spanish"
    assert st.validate_translation("今天我们打 boss", "Сегодня мы победим босса", "ru", "zh") is None
    assert st.validate_translation("今天我们打 boss", "Today we fight the boss", "ru", "zh") == "not_russian"
    batch = st.TranslationBatch(lines=(st.BatchLine("c1", "Bueno chicos", "", True),))
    messages = st.build_messages(batch, source_language="es")
    assert "西班牙语游戏实况" in messages[0]["content"] and "西班牙语字幕 → 简体中文字幕" in messages[1]["content"]
    assert "日语游戏实况" in st.build_messages(batch)[0]["content"]                     # Japanese unchanged


def test_studio_reading_checks_merges_and_refine_prompt():
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    from twobyteasr.subtitle_rules.sentence_refine import refine_system_prompt, validate_action
    from twobyteasr.subtitle_rules.studio_qc import SubtitleQCEngine
    from twobyteasr.timeline.studio_commands import merge_cues_command
    cues = [StudioCue("a", 0, 2500, "Bueno chicos, hoy vamos a derrotar al jefe"), StudioCue("b", 2500, 3500, "otra vez")]
    project = SubtitleProject(media=StudioMedia(path="x.mp4", duration_ms=4000), cues=cues,
                              generation_metadata={"language": {"code": "es"}})
    flagged = {issue.issue_type for issue in SubtitleQCEngine().analyze(project).issues if issue.cue_id == "a"}
    assert not flagged & {"high_cps", "line_too_long"}
    merge_cues_command(project, ["a", "b"]).redo()
    assert project.cues[0].text == "Bueno chicos, hoy vamos a derrotar al jefe otra vez"
    prompt = refine_system_prompt("de")
    assert "German subtitle cues" in prompt and "English" not in prompt.split("Return only")[0]
    text = "Bueno chicos, hoy vamos a derrotar al jefe"
    with language_scope("es"):
        assert validate_action(text, {"cue_id": "1", "action": "split", "split_after_chars": [text.index(",")]})
        assert validate_action(text, {"cue_id": "1", "action": "split", "split_after_chars": [2]}) is None


@pytest.fixture
def home(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.app import ui
    from twobyteasr.local_models import model_workshop as workshop
    from twobyteasr.local_models.model_registry import ModelRegistry
    from twobyteasr.recognition import asr
    app = QApplication.instance() or QApplication([])
    installed = {"qwen_aligner", "firered_aed", "qwen_asr"}
    monkeypatch.setattr(ModelRegistry, "installed_keys", lambda self: set(installed))
    monkeypatch.setattr(ui, "installed_model_keys", lambda root: set(installed))
    monkeypatch.setattr(workshop, "_readiness_status", lambda key: "PASS")
    monkeypatch.setattr(workshop, "_host_platform_tag", lambda: "win32-x86_64")
    monkeypatch.setattr(asr, "resolve_qwen_aligner_local_source", lambda: "fixture-qwen")
    monkeypatch.setitem(subtitle_core.RUNTIME_SETTINGS, "models", {
        **subtitle_core.RUNTIME_SETTINGS.get("models", {}),
        "primary_asr_backend": "none", "qwen_asr_backend": "local", "firered_asr_backend": "local"})
    monkeypatch.setitem(subtitle_core.RUNTIME_SETTINGS, "subtitle_language",
                        {"recognition_language": "auto", "output": "original", "translation_script": "zh-Hans"})
    win = ui.MainWindow([], subtitle_core, object(), None)
    yield win
    win.close()
    win.deleteLater()
    app.processEvents()


def test_home_menu_offers_the_six_languages(home):
    combo = home.recognition_language
    assert [combo.itemData(i) for i in range(combo.count())] == ["auto", "zh", "zh-Hant", "ja", "en", "ko", *EUROPEAN]
    assert [combo.itemText(combo.findData(code)) for code in EUROPEAN] == [eu.LABELS[code] for code in EUROPEAN]
    combo.setCurrentIndex(combo.findData("es"))
    assert subtitle_core.RUNTIME_SETTINGS["subtitle_language"]["recognition_language"] == "es"
    output = home.subtitle_output
    # 2026-10-21: the output choices name no language; the line under the row says it.
    # 2026-10-22: without a connected AI the item also says "（需要 API Key）" (and is greyed out).
    assert output.itemText(output.findData("bilingual")).startswith("原文 + 翻译（双语）")
    output.setCurrentIndex(output.findData("bilingual"))
    assert home.subtitle_language_summary.text() == "字幕会显示：西班牙语原文 + 简体中文翻译"
    output.setCurrentIndex(output.findData("original"))
    targets = [home.translation_script.itemData(i) for i in range(home.translation_script.count())]
    assert "es" not in targets and {"zh-Hans", "de", "ru"} <= set(targets)
    assert "西班牙语：按单词断句" in home.subtitle_language_hint.text()
    card = home.recognition_plan.cards["timeline"]
    assert card.model_label.text() == "Qwen3 对齐"
    assert card.description_label.text() == "字幕语言是西班牙语，FireRedASR2-AED 只用于中文"


def test_squeezed_aligner_words_are_shared_out_instead_of_flashing():
    # Real Russian clip (109.8 s): three garbled words came back inside 30 ms and
    # the subtitle lasted one frame. Faster than 20 ms a letter counts as unmeasured.
    text = "Я хотела бы рассказать вам которую выложила напишущейся про новую работу моя подруга"
    tokens = eu.words(text)
    rows = [{"text": token, "start": 107.4 + 0.3 * i, "end": 107.65 + 0.3 * i} for i, token in enumerate(tokens[:5])]
    rows += [{"text": token, "start": 109.80 + 0.01 * i, "end": 109.81 + 0.01 * i} for i, token in enumerate(tokens[5:], 5)]
    times = seg._word_times(segment(1, 107.4, 112.4, text), tokens, rows, eu.word_core)
    assert times[:5] == [(row["start"], row["end"]) for row in rows[:5]] and times[5:] == [None] * (len(tokens) - 5)
    cues = seg.group_english([segment(1, 107.4, 112.4, text)], rows, lexicon=eu.lexicon("ru"))
    assert all(cue.end - cue.start >= 0.5 for cue in cues), [(cue.text, cue.start, cue.end) for cue in cues]


def test_a_line_never_ends_on_a_number_word():
    # Real Italian clip: "scommetti che fra le due | fessure non passerà?"
    for code, number in (("it", "due"), ("es", "dos"), ("de", "zwei"), ("fr", "deux"), ("pt", "dois"), ("ru", "два")):
        assert number in eu.lexicon(code).determiners
    tokens = eu.words("scommetti che fra le due fessure non passerà perché la luce si comporta come una particella "
                      "e anche come onda")
    lines = [" ".join(tokens[a:b]) for a, b in seg.split_tokens(tokens, lexicon=eu.lexicon("it"))]
    assert not any(line.endswith(" due") for line in lines), lines


def test_aligner_words_outside_the_utterance_never_place_a_cut():
    # Real Russian clip (2026-10-21, 59.34–62.34 s): the aligner, which hears 0.3 s on either side,
    # stretched "дом" to 62.56 s; the cut landed after the sentence and the whole grouping stage
    # failed its source check ("断句阶段结果未通过来源正文、归属与时间校验").
    import dataclasses
    from twobyteasr.subtitle_rules.grouping_contract import validate_grouping_result
    text = "Подерживайте задув дом мяу как раз твоя задача!"
    rows = [{"text": "Подерживайте", "start": 59.04, "end": 59.36}, {"text": "задув", "start": 59.36, "end": 59.6},
            {"text": "дом", "start": 59.6, "end": 62.56}]
    utterance = segment(21, 59.34, 62.34, text)
    tokens = eu.words(text)
    times = seg._word_times(utterance, tokens, rows, eu.word_core)
    assert times[1] == (59.36, 59.6) and times[2] is None          # the stretched word counts as unmeasured
    assert times[0] is None                                        # 0.3 s early is outside too
    base = eu.lexicon("ru")
    one_line = dataclasses.replace(base, rules=dataclasses.replace(base.rules, cue_max_chars=39, cue_preferred_chars=30))
    cues = seg.group_english([utterance], rows, lexicon=one_line)
    assert len(cues) == 2 and all(59.34 <= cue.start < cue.end <= 62.34 for cue in cues), cues
    assert validate_grouping_result([{"segment_id": 21, "start": 59.34, "end": 62.34, "text": text, "speaker": "S00"}],
                                    cues)
    # With two-line subtitles (78 characters in Russian) the sentence stays whole.
    assert [cue.text for cue in seg.group_english([utterance], rows, lexicon=base)] == [text]


def test_a_sentence_whose_pieces_fail_the_source_check_stays_whole_with_a_review_note():
    from subtitle_core import capture_review_items
    from twobyteasr.recognition.cache import run_event_observer
    # Two spaces inside the first piece: the rebuilt piece would no longer match the source text.
    text = ("Bueno chicos hoy vamos a  intentar derrotar al jefe final porque la semana pasada no pudimos hacerlo "
            "y la verdad es que me da un poco de miedo")
    events = []
    with capture_review_items() as items, run_event_observer(lambda event, payload: events.append((event, payload))):
        cues = seg.group_english([segment(4, 10.0, 18.0, text)], (), lexicon=eu.lexicon("es"))
    assert [(cue.start, cue.end, cue.text) for cue in cues] == [(10.0, 18.0, text)]
    assert [item["category"] for item in items] == ["断句回退"] and items[0]["text"]
    assert any(event == "word_grouping_sentence_kept" and payload["reason"] == "text_mutation_rejected"
               for event, payload in events)


def test_italian_sentences_stay_whole_and_ai_breaks_are_checked():
    # Real Italian clip (2026-10-21): an 81-character sentence was cut into
    # "Così se un fotone verrà mandato | per un piano con | due fessure mentre le osserviamo".
    lex = eu.lexicon("it")
    whole = "Così se un fotone verrà mandato per un piano con due fessure mentre le osserviamo"
    assert [cue.text for cue in seg.group_english([segment(1, 0.68, 4.28, whole)], (), lexicon=lex)] == [whole]
    text = whole + " non passerà per nessuna delle due non osservandole passerà"
    tokens = eu.words(text)
    con, non = tokens.index("con"), len(tokens) - 3                 # "… con | due", "… due non | osservandole"
    assert seg.pieces_from_breaks(tokens, [con], lexicon=lex) is None
    assert seg.pieces_from_breaks(tokens, [non], lexicon=lex) is None
    cues = seg.group_english_with_ai([segment(1, 0.68, 7.28, text)], lexicon=lex,
                                     complete=lambda _m: '{"breaks": {"1": [%d, %d]}}' % (con, non))
    assert len(cues) == 2 and " ".join(cue.text for cue in cues) == text
    assert not any(cue.text.endswith((" con", " non")) for cue in cues[:-1]), [cue.text for cue in cues]
