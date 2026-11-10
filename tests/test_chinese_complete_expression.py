"""Production-entry regressions for the complete-expression Chinese policy."""
import copy
import json
from types import SimpleNamespace

import pytest
import subtitle_core as core
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
from twobyteasr.subtitle_rules import grouping
from twobyteasr.subtitle_rules.grouping_quality import BoundaryQuality, quality_for_segments
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules.segmentation_profiles import measure


@pytest.fixture(autouse=True)
def chinese_task():
    with language_scope('zh'), activate_runtime_context(
            RuntimeContext(task_language='zh', enable_domain_terms=False), legacy=core):
        yield


def sources(parts, *, gap=.0, speakers=None):
    rows, tokens, start = [], [], 1.
    for index, text in enumerate(parts):
        words = []
        for char in core.content_exact(text):
            words.append(core.WordUnit(start, start+.12, char, .99))
            tokens.append(dict(text=char, start=start, end=start+.12))
            start += .14
        rows.append(core.SpeechSegment(index+1, words[0].start, words[-1].end,
            text, .99, words, speaker=(speakers or ['S00']*len(parts))[index]))
        start += gap
    return rows, tokens


@pytest.mark.parametrize('parts', [
    ['他进我们罗隐的', '斩杀线了'],
    ['我们先走到前面', '然后看一下情况'],
    ['我们先走', '到前面然后', '看一下情况'],
    ['可以', '继续往前走'],
    ['没有', '强化手段'],
    ['我们先过去', '然后看下情况'],
])
@pytest.mark.parametrize('gap', [0., .18, .35])
def test_complete_expression_reassembles_asr_and_model_fragments(parts, gap):
    rows, tokens = sources(parts, gap=gap)
    original = copy.deepcopy(rows)
    expected = ''.join(parts)
    assert measure(expected, 'zh') <= 14
    cues = grouping.cues_from_resegmented_texts(rows, parts, tokens)
    assert [c.text for c in cues] == [expected]
    assert (cues[0].start, cues[0].end, cues[0].speaker) == (rows[0].start, rows[-1].end, 'S00')
    assert [c.text for c in grouping.fallback_group(rows, tokens)] == [expected]
    assert rows == original


@pytest.mark.parametrize('gap', [.18, .35])
def test_internal_pause_and_local_repair_window_do_not_resplit(gap):
    rows, tokens = sources(['我们先走到前面', '然后看一下情况'], gap=gap)
    merged = copy.deepcopy(rows[0])
    merged.text += rows[1].text
    merged.end = rows[1].end
    merged.words += rows[1].words
    quality = quality_for_segments([merged], tokens)
    assert quality.inspect([7, 14])
    assert quality.repair([7, 14])[0] == [14]
    assert quality._solve(0, 14, {7, 14}) == [14]
    assert quality.repair([14])[0] == [14]


def test_overlength_uses_clause_and_measured_pause():
    rows, tokens = sources(['他进我们罗隐的斩杀线了', '切罗隐就好了'], gap=.35)
    cues = grouping.cues_from_resegmented_texts(rows,
        ['他进我们罗隐的', '斩杀线了', '切罗隐就好了'], tokens)
    assert [c.text for c in cues] == ['他进我们罗隐的斩杀线了', '切罗隐就好了']
    assert all(measure(c.text, 'zh') <= 14 for c in cues)


@pytest.mark.parametrize('parts,gap,speakers', [
    (['对撞', '我们先走到前面'], .35, None),
    (['嗯', '不急', '等一下'], .35, None),
    (['他进我们罗隐的', '斩杀线了'], 3.1, None),
    (['他进我们罗隐的', '斩杀线了'], 0., ['S00', 'S01']),
    (['我去开门。', '你来接我。'], 0., None),
])
def test_independent_turns_and_hard_boundaries_stay(parts, gap, speakers):
    rows, tokens = sources(parts, gap=gap, speakers=speakers)
    cues = grouping.cues_from_resegmented_texts(rows, parts, tokens)
    assert [c.text for c in cues] == parts
    assert [c.speaker for c in cues] == [r.speaker for r in rows]


def test_explicit_protected_cut_and_overlapping_speakers():
    rows, tokens = sources(['我们先走到前面', '然后看一下情况'])
    quality = quality_for_segments(rows, tokens, protected=[7])
    assert quality.repair([7, 14])[0] == [7, 14]
    rows[1].speaker = 'S01'
    shift = rows[1].start-rows[0].start-.2
    rows[1].start -= shift
    rows[1].end -= shift
    for word in rows[1].words:
        word.start -= shift
        word.end -= shift
    cues = grouping.cues_from_resegmented_texts(rows, [r.text for r in rows])
    assert [(c.text, c.start, c.end, c.speaker) for c in cues] == [
        (r.text, r.start, r.end, r.speaker) for r in rows]


def test_raw_unicode_repetition_and_long_atom_conflict():
    text = '我想一下，想一下 e\u0301 👨‍👩‍👧‍👦 然后走'
    quality = BoundaryQuality(text)
    cuts, issues = quality.repair([quality.total])
    assert ''.join(quality.index.pieces(cuts)) == text
    assert len(cuts) == 1 and not issues
    atom = BoundaryQuality('SuperLongPlayerIdentifier')
    cuts, issues = atom.repair([atom.total])
    assert cuts == [atom.total]
    assert any(i['kind'] == 'length' for i in issues)
    for text in ['e\u0301，A12 👨‍👩‍👧‍👦', '𠮷 α你好', '1\u200d2']:
        assert measure(text, 'zh') == len(core.content_exact(text))


def test_studio_reselect_recovers_fragmented_range_even_when_model_keeps(monkeypatch):
    from twobyteasr.projects.studio_project import StudioCue, SubtitleProject, StudioMedia
    from twobyteasr.subtitle_rules.sentence_refine import refine_cues_with_llm
    from twobyteasr.subtitle_rules.sentence_refine_ranges import build_range_replacement
    cues = [StudioCue('a', 1000, 2000, '我们先走到前面'),
            StudioCue('b', 2180, 3200, '然后看一下情况')]
    project = SubtitleProject(media=StudioMedia(path='fixture.wav'), cues=cues)
    project.generation_metadata['language'] = {'code': 'zh'}
    calls = []
    def complete(messages, **kwargs):
        calls.append(messages)
        payload = json.loads(messages[1]['content'])
        return json.dumps({'results': [dict(cue_id=c['cue_id'], action='keep') for c in payload['cues']]})
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',
        lambda *a, **k: SimpleNamespace(complete=complete))
    result = refine_cues_with_llm(cues, project=project, runtime_settings={'models': {'group_model': 'stub'}}, boundary_only=True)
    assert len(result.ranges) == 1 and len(calls) == 1
    unit = result.ranges[0]
    action = result.actions[0]
    output = build_range_replacement(unit, action, project, {'a', 'b'})
    assert [c.text for c in output] == ['我们先走到前面然后看一下情况']
    assert (output[0].start_ms, output[0].end_ms) == (1000, 3200)
    cues[0].text, cues[1].text = '我们先过去', '然后看下情况'
    result = refine_cues_with_llm(cues, project=project, runtime_settings={'models': {'group_model': 'stub'}}, boundary_only=True)
    assert len(result.ranges) == 1
    output = build_range_replacement(result.ranges[0], result.actions[0], project, {'a', 'b'})
    assert [c.text for c in output] == ['我们先过去然后看下情况']


def test_studio_merge_translation_receipts_undo_save_and_export(tmp_path):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QUndoStack
    from twobyteasr.projects.studio_project import StudioCue, SubtitleProject, StudioMedia, save_project, load_project
    from twobyteasr.subtitle_rules.sentence_refine_ranges import make_ranges, build_range_replacement
    from twobyteasr.subtitle_rules.sentence_refine import CueRefineAction
    from twobyteasr.timeline.sentence_refine_command import RefineCuesCommand
    from twobyteasr.exports.studio_subtitle_export import export_language_layers
    app = QApplication.instance() or QApplication([])
    cues = [StudioCue('outside', 0, 800, '范围外'),
            StudioCue('a', 1000, 2000, '他进我们罗隐的', evidence_refs=['a-ref']),
            StudioCue('b', 2180, 3000, '斩杀线了', evidence_refs=['b-ref'])]
    project = SubtitleProject(media=StudioMedia(path='fixture.wav'), cues=cues)
    project.generation_metadata['translations'] = {'a': 'He is within', 'b': 'our kill range'}
    project.asr_evidence = {ref: dict(text=cue.text, start_ms=cue.start_ms, end_ms=cue.end_ms,
        speaker=cue.speaker_id, words=[]) for cue in cues for ref in cue.evidence_refs}
    project.render_settings['_cue_domain'] = 'timeline'
    project.studio_state['caption_timeline'] = {'instances': {'a': {}, 'b': {}}}
    project.validate()
    before = copy.deepcopy(project.cues)
    metadata = copy.deepcopy(project.generation_metadata)
    unit = make_ranges(cues[1:], project, 'zh', combine=True)[0]
    output = build_range_replacement(unit, CueRefineAction(unit.cue.id, 'split'), project, {c.id for c in cues})
    stack = QUndoStack()
    stack.push(RefineCuesCommand(project, [(1, 2, output)]))
    merged = project.cues[1]
    assert merged.text == '他进我们罗隐的斩杀线了'
    assert merged.evidence_refs == ['a-ref', 'b-ref']
    assert 'He is within' in project.generation_metadata['translations'][merged.id]
    assert 'our kill range' in project.generation_metadata['translations'][merged.id]
    assert project.cues[0] == before[0]
    save_project(project, tmp_path/'merged.2byteproj')
    reopened = load_project(tmp_path/'merged.2byteproj')
    assert reopened.cues == project.cues
    paths = export_language_layers(reopened, tmp_path/'srt', 'merged', layers=('original',))
    assert all(artifact.path.exists() for artifact in paths.artifacts)
    stack.undo()
    assert project.cues == before and project.generation_metadata == metadata
    stack.redo()
    assert project.cues[1].id == merged.id
    stack.clear()


def test_studio_protected_edges_locked_speakers_styles_and_selection():
    from twobyteasr.projects.studio_project import StudioCue, SubtitleProject, StudioMedia
    from twobyteasr.subtitle_rules.sentence_refine_ranges import make_ranges
    cues = [StudioCue('a', 1000, 2000, '我们先走到前面'), StudioCue('b', 2180, 3200, '然后看一下情况')]
    project = SubtitleProject(media=StudioMedia(path='fixture.wav'), cues=cues)
    project.studio_state['caption_timeline'] = {'instances': {'a': {'protected_end': True}}}
    assert len(make_ranges(cues, project, 'zh', combine=True)) == 2
    project.studio_state.clear()
    project.studio_state['locked_speakers'] = ['S00']
    assert len(make_ranges(cues, project, 'zh', combine=True)) == 2
    project.studio_state.clear()
    cues[1].style_id = 'another'
    assert len(make_ranges(cues, project, 'zh', combine=True)) == 2
    assert len(make_ranges(cues[:1], project, 'zh', combine=True)[0].originals) == 1


def test_quality_cache_dependency_only_invalidates_derived_stages(monkeypatch):
    from twobyteasr.recognition.cache import cache_stage_signature
    from twobyteasr.subtitle_rules import grouping_quality
    stages = ['grouped', 'grouped_local', 'final_timing', 'audio', 'polished', 'firered_primary']
    before = {stage: cache_stage_signature(stage) for stage in stages}
    monkeypatch.setattr(grouping_quality, 'QUALITY_VERSION', 'test-different-quality')
    after = {stage: cache_stage_signature(stage) for stage in stages}
    assert all(before[s] != after[s] for s in stages[:3])
    assert all(before[s] == after[s] for s in stages[3:])


def test_native_words_only_create_real_pause_when_reliable():
    rows, _ = sources(['我们先走到前面', '然后看一下情况'], gap=.35)
    merged = copy.deepcopy(rows[0])
    merged.text += rows[1].text
    merged.end = rows[1].end
    merged.words += rows[1].words
    merged.caption_arbitration['word_timing'] = {'basis': 'uniform_display_estimate'}
    assert not quality_for_segments([merged]).pauses
    merged.caption_arbitration['word_timing'] = {'basis': 'aligner_words'}
    quality = quality_for_segments([merged])
    assert quality.pauses[7] >= .35
    assert quality.repair([7, 14])[0] == [14]


@pytest.mark.parametrize('response', ['{"boundaries":[7,14]}', '{invalid-json'])
def test_full_grouping_entry_stub_and_failed_ai_follow_same_policy(monkeypatch, response):
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    rows, tokens = sources(['我们先走到前面', '然后看一下情况'], gap=.18)
    monkeypatch.setattr(grouping, 'provider_for_stage', lambda *a, **k: SimpleNamespace(complete=lambda *a, **k: response))
    monkeypatch.setattr(grouping, 'GROUPING_API_RETRIES', 1)
    snapshot = resolve_provider_snapshot({'models': {'ai_service': 'custom', 'provider_profiles': {
        'custom': {'base_url': 'http://127.0.0.1:1/v1', 'model': 'offline-fixture'}}}})
    cues = grouping.group_subtitles(rows, use_ai=True, firered_tokens=tokens, provider_snapshot=snapshot)
    assert [cue.text for cue in cues] == ['我们先走到前面然后看一下情况']


def test_non_chinese_profiles_and_exact_custom_guidance():
    from twobyteasr.subtitle_rules.segmentation_profiles import profile_for, fixed_constraints
    from twobyteasr.subtitle_rules.grouping_request import custom_grouping_guidance, compose_grouping_prompt
    assert [profile_for(tag).hard_max for tag in ['zh', 'ja', 'en']] == [14, 26, 84]
    text = '中位约8字，但我需要自己的字幕节奏'
    assert custom_grouping_guidance('zh', {'grouping_prompts': {'zh': text}}) == text
    prompt = compose_grouping_prompt('zh', 16, 5, text)
    assert text in prompt and 'cue maximum 14' in prompt
    assert 'preferred 10' not in fixed_constraints('zh')
    from twobyteasr.subtitle_rules.segmentation_profiles import project_language_tag
    legacy = SimpleNamespace(generation_metadata={}, cues=[SimpleNamespace(text='我们先走到前面然后看一下情况')])
    assert project_language_tag(legacy) == 'zh'
    legacy.generation_metadata['language'] = {'code': 'und'}
    assert project_language_tag(legacy) == 'und'


def test_indivisible_atom_is_local_review_at_final_delivery():
    from twobyteasr.subtitle_rules.output import validate_final_cues
    rows, _ = sources(['SuperLongPlayerIdentifier', '我们先走到前面然后看一下情况'], gap=3.1)
    cues = [core.SubtitleCue(i+1, row.start, row.end, row.text, speaker=row.speaker) for i, row in enumerate(rows)]
    validate_final_cues(cues, rows, rows[-1].end)
    assert [c.text for c in cues] == [row.text for row in rows]
    bad = copy.deepcopy(cues)
    bad[1].text += '我们继续往前走'
    with pytest.raises(RuntimeError, match='超过硬性长度'):
        validate_final_cues(bad, rows, rows[-1].end, validate_text=False)


def test_merged_model_response_cannot_erase_independent_short_turns():
    rows, tokens = sources(['嗯', '不急', '等一下'], gap=.35)
    cues = grouping.cues_from_resegmented_texts(rows, ['嗯不急等一下'], tokens)
    assert [c.text for c in cues] == ['嗯', '不急', '等一下']


def test_studio_api_failure_uses_same_local_policy_without_extra_requests(monkeypatch):
    from twobyteasr.projects.studio_project import StudioCue, SubtitleProject, StudioMedia
    from twobyteasr.subtitle_rules.sentence_refine import refine_cues_with_llm
    cues = [StudioCue('a', 1000, 2000, '我们先走到前面'), StudioCue('b', 2180, 3200, '然后看一下情况')]
    project = SubtitleProject(media=StudioMedia(path='fixture.wav'), cues=cues)
    project.generation_metadata['language'] = {'code': 'zh'}
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise ValueError('offline fixture')
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: SimpleNamespace(complete=fail))
    result = refine_cues_with_llm(cues, project=project, runtime_settings={'models': {'group_model': 'stub'}},
                                 boundary_only=True, max_attempts=1)
    assert len(calls) == 1 and result.llm_status == 'completed'
    assert result.actions[0].action == 'split' and not result.actions[0].split_after_chars
    assert next(iter(result.results.values()))['local_fallback']


def test_studio_long_source_windows_rejoin_in_their_original_coordinate_space(monkeypatch):
    from twobyteasr.projects.studio_project import StudioCue, SubtitleProject, StudioMedia
    from twobyteasr.subtitle_rules.sentence_refine import refine_cues_with_llm
    from twobyteasr.subtitle_rules.sentence_refine_ranges import build_range_replacement
    sentence = '我们先走到前面然后看一下情况。'
    text = sentence*90
    cue = StudioCue('long', 0, len(text)*150, text, evidence_refs=['e'])
    project = SubtitleProject(media=StudioMedia(path='fixture.wav'), cues=[cue])
    project.generation_metadata['language'] = {'code': 'zh'}
    project.asr_evidence = {'e': {'caption_arbitration': {'timing_evidence': {'independent_acoustic': True}},
        'words': [dict(text=c, start_ms=i*150, end_ms=i*150+130) for i,c in enumerate(text) if core.content_exact(c)]}}
    calls = []
    def complete(messages, **kwargs):
        payload = json.loads(messages[-1]['content'])
        calls.append(payload)
        results = []
        for row in payload['cues']:
            local = BoundaryQuality(row['text'])
            cuts, _ = local.repair([local.total])
            results.append(dict(cue_id=row['cue_id'], action='split',
                split_after_chars=[local.index.raw_edges[c]-1 for c in cuts[:-1]]))
        return json.dumps({'results': results})
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: SimpleNamespace(complete=complete))
    result = refine_cues_with_llm([cue], project=project, runtime_settings={'models': {'group_model': 'stub'}}, boundary_only=True)
    assert result.llm_status == 'completed' and len(calls) <= 2
    rebuilt = build_range_replacement(result.ranges[0], result.actions[0], project, {'long'})
    assert ''.join(c.text for c in rebuilt) == text
    assert all(measure(c.text, 'zh') <= 14 for c in rebuilt)


def test_manual_razor_protection_survives_save_and_undo(tmp_path):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QUndoStack
    from twobyteasr.projects.studio_project import StudioCue, SubtitleProject, StudioMedia, save_project, load_project
    from twobyteasr.timeline.studio_commands import split_cue_command
    from twobyteasr.subtitle_rules.sentence_refine_ranges import make_ranges
    app = QApplication.instance() or QApplication([])
    cue = StudioCue('manual', 1000, 4000, '我们先走到前面然后看一下情况')
    project = SubtitleProject(media=StudioMedia(path='fixture.wav'), cues=[cue])
    project.render_settings['_cue_domain'] = 'timeline'
    project.studio_state['caption_timeline'] = {'instances': {'manual': {}}}
    project.validate()
    stack = QUndoStack()
    stack.push(split_cue_command(project, 'manual', 2400, '我们先走到前面', '然后看一下情况'))
    assert len(make_ranges(project.cues, project, 'zh', combine=True)) == 2
    save_project(project, tmp_path/'protected.2byteproj')
    reopened = load_project(tmp_path/'protected.2byteproj')
    assert len(make_ranges(reopened.cues, reopened, 'zh', combine=True)) == 2
    stack.undo()
    assert len(project.cues) == 1 and project.cues[0].text == cue.text
    stack.clear()
