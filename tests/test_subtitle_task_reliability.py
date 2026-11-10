"""Regression replay for lossless Studio refinement and input-owned task state."""

import copy
import json
from types import SimpleNamespace

import pytest

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.subtitle_rules.sentence_refine import refine_cues_with_llm
from twobyteasr.subtitle_rules.sentence_refine_contract import RefineError, boundary_candidates, parse_response
from twobyteasr.subtitle_rules.sentence_refine_ranges import make_ranges, build_range_replacement, input_version
from twobyteasr.studio.studio_task_progress import SubtitleTask

SETTINGS = {'models': {'group_model': 'fixture'}}


@pytest.mark.parametrize('language', ['en', 'de', 'ko'])
def test_word_language_source_edges_without_spaces_never_glue_words(monkeypatch, language):
    calls = install(monkeypatch, lambda request, kwargs, call: json.dumps({'results': [
        dict(cue_id=row['cue_id'], action='keep') for row in request['cues']]}))
    cues = [StudioCue('a', 0, 2000, 'This is a complete sentence.'),
            StudioCue('b', 2100, 4000, 'Here is another sentence.')]
    project = SubtitleProject(media=StudioMedia(path='fixture'), cues=cues,
                              generation_metadata={'language': {'code': language}})
    result = refine_cues_with_llm(cues, project=project, runtime_settings=SETTINGS, boundary_only=True)
    assert result.llm_status == 'completed' and len(calls) == 1
    assert len(result.ranges) == 2 and [unit.cue.text for unit in result.ranges] == [cue.text for cue in cues]


def test_word_language_existing_whitespace_stays_exact_when_ranges_keep(monkeypatch):
    install(monkeypatch, lambda request, kwargs, call: json.dumps({'results': [
        dict(cue_id=row['cue_id'], action='keep') for row in request['cues']]}))
    cues = [StudioCue('a', 0, 2000, 'This is a complete sentence. '),
            StudioCue('b', 2100, 4000, 'Here is another sentence.')]
    project = SubtitleProject(media=StudioMedia(path='fixture'), cues=cues,
                              generation_metadata={'language': {'code': 'en'}})
    result = refine_cues_with_llm(cues, project=project, runtime_settings=SETTINGS, boundary_only=True)
    assert result.llm_status == 'completed' and len(result.ranges) == 1
    assert result.ranges[0].cue.text == ''.join(cue.text for cue in cues)


def test_mixed_language_latin_edges_do_not_glue_in_a_chinese_project(monkeypatch):
    install(monkeypatch, lambda request, kwargs, call: json.dumps({'results': [
        dict(cue_id=row['cue_id'], action='keep') for row in request['cues']]}))
    cues = [StudioCue('a', 0, 2000, '先go.'), StudioCue('b', 2100, 4000, 'next now.')]
    project = SubtitleProject(media=StudioMedia(path='fixture'), cues=cues,
                              generation_metadata={'language': {'code': 'zh'}})
    result = refine_cues_with_llm(cues, project=project, runtime_settings=SETTINGS, boundary_only=True)
    assert result.llm_status == 'completed' and len(result.ranges) == 2


def install(monkeypatch, callback):
    calls = []

    def complete(messages, **kwargs):
        request = json.loads(messages[-1]['content'])
        calls.append((request, kwargs))
        return callback(request, kwargs, len(calls))

    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',
        lambda *args, **kwargs: SimpleNamespace(complete=complete, provider_id='fixture', model='fixture'))
    return calls


@pytest.mark.parametrize('wrapper', [lambda value: value, lambda value: '\ufeff ' + value,
    lambda value: '```json\n' + value + '\n```', lambda value: '结果如下\n' + value + '\n处理完毕',
    lambda value: value.replace('}]', '},]').replace(']}', '],}')])
def test_complete_unambiguous_json_is_repaired(wrapper):
    rows, _ = parse_response(wrapper('{"results":[{"cue_id":"a","action":"keep"}]}'))
    assert rows == [{'cue_id': 'a', 'action': 'keep'}]


@pytest.mark.parametrize('value,category', [('', 'empty_response'),
    ('{"results":[', 'incomplete_response'),
    ('{"results":[]} {"results":[{"cue_id":"a"}]}', 'ambiguous_response'),
    ('{"results":[],"results":[]}', 'duplicate_field'),
    ('{"cues":[]}', 'structure_error'), ('{"results":[null]}', 'structure_error')])
def test_ambiguous_or_incomplete_content_never_guessed(value, category):
    with pytest.raises(RefineError) as error:
        parse_response(value)
    assert error.value.category == category


def test_trailing_comma_repair_respects_quotes_and_escapes():
    value = r'{"results":[{"cue_id":"a","reason":"a,} \\\" x","action":"keep",},],}'
    rows, repairs = parse_response(value)
    assert ',}' in rows[0]['reason'] and repairs


def test_duplicate_fields_in_one_row_do_not_discard_other_rows(monkeypatch):
    def response(request, kwargs, call):
        if call == 1:
            return '{"results":[{"cue_id":"a","action":"keep"},{"cue_id":"b","action":"keep","action":"split"}]}'
        assert [row['cue_id'] for row in request['cues']] == ['b']
        return '{"results":[{"cue_id":"b","action":"keep"}]}'
    calls = install(monkeypatch, response)
    result = refine_cues_with_llm([StudioCue('a', 0, 1000, '第一句'), StudioCue('b', 2000, 3000, '第二句')],
                                  runtime_settings=SETTINGS, boundary_only=True)
    assert result.llm_status == 'completed' and len(result.actions) == 2 and len(calls) == 2
    assert result.requests[1]['input']['repair']['errors'][0]['category'] == 'duplicate_field'


@pytest.mark.parametrize('text,term', [('但是我们可以再试一次', '但是'), ('虽然天气有点冷', '虽然'),
    ('这场比赛非常精彩', '这场'), ('请使用OpenAI模型', 'OpenAI'), ('需要10 minutes时间', '10 minutes'),
    ('请等300万元到账', '300万元'), ('我们去星野爱弥斯城', '星野爱弥斯'),
    ('你好👨\u200d👩\u200d👧\u200d👦朋友', '👨\u200d👩\u200d👧\u200d👦'),
    ('咖啡e\u0301很好喝', 'e\u0301')])
def test_words_names_units_and_graphemes_are_protected(text, term):
    offsets = set(boundary_candidates(text, terms=[term]).values())
    start = text.index(term)
    assert not offsets.intersection(range(start, start + len(term) - 1))


def test_partial_batch_preserves_valid_range_and_repairs_only_missing(monkeypatch):
    def response(request, kwargs, call):
        ids = [row['cue_id'] for row in request['cues']]
        if call == 1:
            return json.dumps({'results': [{'cue_id': ids[0], 'action': 'keep'}]})
        assert ids == ['b'] and request['repair']['errors'][0]['category'] == 'range_identity_error'
        return '{"results":[{"cue_id":"b","action":"keep",},],}'
    calls = install(monkeypatch, response)
    cues = [StudioCue('a', 0, 1000, '第一句话'), StudioCue('b', 2000, 3000, '第二句话')]
    outcome = refine_cues_with_llm(cues, runtime_settings=SETTINGS, boundary_only=True)
    assert outcome.llm_status == 'completed' and len(outcome.actions) == 2 and len(calls) == 2
    assert outcome.results['b']['attempts'] == 2 and not outcome.results['b']['error']


def test_semantic_bad_break_is_targeted_then_preserved_on_budget_exhaustion(monkeypatch):
    install(monkeypatch, lambda request, kwargs, call:
        '{"results":[{"cue_id":"a","action":"split","split_after_chars":[0]}]}')
    cue = StudioCue('a', 0, 4000, '虽然这里很冷但是可以继续')
    result = refine_cues_with_llm([cue], runtime_settings=SETTINGS, boundary_only=True)
    assert result.llm_status == 'failed' and result.failed_cue_ids == ['a']
    assert len(result.requests) == 2 and result.results['a']['category'] in {'semantic_boundary', 'structure_error'}


def test_request_failure_categories_and_retry_budget(monkeypatch):
    def response(request, kwargs, call):
        raise RefineError('凭据无效', 'auth_error')
    calls = install(monkeypatch, response)
    result = refine_cues_with_llm([StudioCue('a', 0, 1000, '你好')], runtime_settings=SETTINGS)
    assert len(calls) == 1 and result.results['a']['category'] == 'auth_error'


def test_truncated_window_shrinks_without_duplicate_source_work(monkeypatch):
    def response(request, kwargs, call):
        if call == 1:
            kwargs['request_diagnostics']['finish_reason'] = 'length'
            return '{"results":['
        return json.dumps({'results': [{'cue_id': row['cue_id'], 'action': 'keep'} for row in request['cues']]})
    calls = install(monkeypatch, response)
    cues = [StudioCue(str(i), i * 2000, i * 2000 + 1000, '完整的话') for i in range(4)]
    result = refine_cues_with_llm(cues, runtime_settings=SETTINGS, boundary_only=True)
    assert len(calls) == 3 and len(result.actions) == 4 and result.llm_status == 'completed'
    assert [len(request['cues']) for request, _ in calls] == [4, 2, 2]


def test_cross_cue_word_can_be_recombined_and_source_whitespace_preserved():
    from twobyteasr.subtitle_rules.sentence_refine import CueRefineAction
    cues = [StudioCue('a', 0, 1000, '这'), StudioCue('b', 1100, 2500, '场比赛 好看')]
    project = SubtitleProject(media=StudioMedia(path='fixture'), cues=cues)
    units = make_ranges(cues, project, '', combine=True)
    assert len(units) == 1 and units[0].cue.text == '这场比赛 好看'
    parts = build_range_replacement(units[0], CueRefineAction(units[0].cue.id, 'split'), project, {'a', 'b'})
    assert len(parts) == 1 and parts[0].text == '这场比赛 好看'
    assert (parts[0].start_ms, parts[0].end_ms) == (0, 2500)


@pytest.mark.parametrize('mode', ['speaker', 'overlap', 'pause', 'style', 'scope'])
def test_real_boundaries_remain_independent(mode):
    cues = [StudioCue('a', 0, 1000, '嗯'), StudioCue('b', 1100, 2000, '好')]
    project = SubtitleProject(media=StudioMedia(path='fixture'), cues=cues)
    if mode == 'speaker':
        cues[1].speaker_id = 'S01'
    elif mode == 'overlap':
        cues[1].start_ms = 900
    elif mode == 'pause':
        cues[1].start_ms = 1800
    elif mode == 'style':
        cues[1].style_id = 'other'
    else:
        project.cues.insert(1, StudioCue('outside', 1000, 1100, '外部'))
    assert len(make_ranges(cues if mode != 'scope' else [cues[0], cues[-1]], project, '', combine=True)) == 2


def test_missing_word_timing_is_a_local_failure_without_text_loss():
    from twobyteasr.subtitle_rules.sentence_refine import CueRefineAction
    cue = StudioCue('a', 0, 4000, '这个东西很好但是还要等')
    p = SubtitleProject(media=StudioMedia(path='fixture'), cues=[cue])
    unit = make_ranges([cue], p, '')[0]
    with pytest.raises(RefineError) as error:
        build_range_replacement(unit, CueRefineAction('a', 'split', [5]), p, {'a'})
    assert error.value.category == 'time_mapping_error' and p.cues == [cue]


def test_input_version_covers_text_style_evidence_and_model():
    cue = StudioCue('a', 0, 1000, '原文', evidence_refs=['e'])
    p = SubtitleProject(media=StudioMedia(path='fixture'), cues=[cue], asr_evidence={'e': {'text': '原文'}})
    before = input_version([cue], p, {'model': 'a'})
    assert before != input_version([cue], p, {'model': 'b'})
    p.asr_evidence['e']['text'] = '变化'
    assert before != input_version([cue], p, {'model': 'a'})


def test_project_glossary_is_loaded_independently_of_recognition_context(monkeypatch):
    from twobyteasr.glossary.terminology import GlossarySnapshot, GlossaryLibrary, TermEntry
    calls = []
    def snapshot(legacy, ids):
        calls.append(list(ids))
        return GlossarySnapshot((GlossaryLibrary('stable', '词库', '1', (TermEntry('星野爱弥斯'),)),))
    monkeypatch.setattr('twobyteasr.glossary.terminology.snapshot_glossaries', snapshot)
    cue = StudioCue('a', 0, 3000, '我们去星野爱弥斯城')
    project = SubtitleProject(media=StudioMedia(path='fixture'), cues=[cue], glossary_ids=['显示名称'])
    unit = make_ranges([cue], project, '')[0]
    assert calls == [['显示名称']]
    start = cue.text.index('星野爱弥斯')
    assert not set(unit.candidates.values()).intersection(range(start, start+4))


def test_task_counts_unique_originals_and_does_not_complete_on_validation():
    task = SubtitleTask('AI 断句', ('a', 'b', 'c'))
    task.update(dict(range_id='b', cue_ids=['b'], status='validated'))
    task.update(dict(range_id='a', cue_ids=['a'], status='failed', final=False))
    assert task.counts()['processed'] == 0
    task.update(dict(range_id='b', cue_ids=['b'], status='applied', output_ids=['x', 'y', 'z']))
    task.update(dict(range_id='b', cue_ids=['b'], status='applied'))
    task.finish(cancelled=True)
    assert task.counts() == dict(applied=1, unchanged=0, review=0, failed=1, cancelled=1,
                                 suggestion=0, processed=2, total=3)
    assert '2/3' in task.summary()


def test_single_long_cue_has_disjoint_context_windows_and_one_owned_result(monkeypatch):
    text = '今天天气很好我们继续出发。' * 200

    def response(request, kwargs, call):
        rows = []
        for cue in request['cues']:
            selected = []
            cursor = 0
            for candidate in cue['boundary_candidates']:
                cursor += len(candidate['text'])
                if candidate['id'] and (cue['text'][:cursor].endswith('很好') or cue['text'][:cursor].endswith('出发。')):
                    selected.append(candidate['id'])
            rows.append(dict(cue_id=cue['cue_id'], action='split', break_after=selected))
        return json.dumps({'results': rows})
    calls = install(monkeypatch, response)
    result = refine_cues_with_llm([StudioCue('long', 0, 300000, text)], runtime_settings=SETTINGS,
                                  boundary_only=True)
    assert len(calls) >= 2 and sum(len(request['cues']) for request, _ in calls) >= 3
    assert result.llm_status == 'completed', {k:(v.get('category'), v.get('error')) for k,v in result.results.items()}
    assert ''.join(cue['text'] for request, _ in calls for cue in request['cues']) == text
    assert len(result.ranges) == 1 and set(result.results) == {'long'}
    assert len(result.actions) == 1 and result.actions[0].cue_id == 'long'
    assert ''.join(result.results['long']['validated_texts']) == text


def test_oversized_unbreakable_word_is_preserved_without_call(monkeypatch):
    calls = install(monkeypatch, lambda *args: pytest.fail('Unbreakable word must not be requested'))
    result = refine_cues_with_llm([StudioCue('word', 0, 4000, 'A' * 3000)],
                                  runtime_settings=SETTINGS, boundary_only=True)
    assert not calls and result.results['word']['category'] == 'constraint_conflict'


def test_json_compatibility_requires_explicit_parameter_evidence(monkeypatch):
    def response(request, kwargs, call):
        if call == 1:
            raise RefineError('response_format unsupported', 'unsupported_parameters')
        assert kwargs['response_format'] is None and kwargs['json_schema'] is None
        return '{"results":[{"cue_id":"a","action":"keep"}]}'
    calls = install(monkeypatch, response)
    result = refine_cues_with_llm([StudioCue('a', 0, 1000, '你好')], runtime_settings=SETTINGS)
    assert len(calls) == 2 and result.llm_status == 'completed'


def test_finished_task_drops_project_and_worker_ownership():
    import gc
    import weakref
    project = SubtitleProject(media=StudioMedia(path='fixture'), cues=[])
    reference = weakref.ref(project)
    task = SubtitleTask('AI 断句', ())
    task.project = project
    task.cancel_action = lambda: None
    task.finish()
    ended = task.ended
    task.finish(cancelled=True)
    assert task.ended == ended and not task.cancelled and task.cancel_action is None
    del project
    gc.collect()
    assert reference() is None and task.project is None


@pytest.mark.parametrize('failure_status', [400, 401])
def test_real_provider_http_json_compatibility_and_auth_do_not_mix(monkeypatch, failure_status):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from twobyteasr.providers import llm_config
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(body)
            status = failure_status if len(requests) == 1 else 200
            if status != 200:
                response = {'error': {'message': 'response_format unsupported', 'param': 'response_format',
                                      'code': 'unsupported_parameter' if status == 400 else 'invalid_api_key'}}
            else:
                response = {'choices': [{'message': {'content': '{"results":[{"cue_id":"a","action":"keep"}]}'},
                                         'finish_reason': 'stop'}]}
            data = json.dumps(response).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(llm_config, 'read_scoped_api_key', lambda *args: ('fixture-key', 'fixture'))
    settings = {'models': {'ai_service': 'custom', 'group_provider': 'custom',
        'group_model': 'fixture-model', 'group_base_url': f'http://127.0.0.1:{server.server_port}/v1',
        'group_protocol': 'openai_compatible_chat'}}
    try:
        result = refine_cues_with_llm([StudioCue('a', 0, 1000, '你好')], runtime_settings=settings,
                                      boundary_only=True)
        if failure_status == 400:
            assert result.llm_status == 'completed' and len(requests) == 2, result.requests
            assert requests[0].get('response_format') and 'response_format' not in requests[1]
        else:
            assert result.llm_status == 'failed' and len(requests) == 1, result.requests
            assert result.results['a']['category'] == 'auth_error'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
