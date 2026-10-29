"""The user-facing complete action must process real input with the model."""
import json
from types import SimpleNamespace

import pytest

from twobyteasr.glossary import glossary_build as gb
from twobyteasr.glossary.glossary_skill import GlossarySearchError
REAL_COLLECTOR = gb._run_full_library_update


def baseline(names=()):
    return SimpleNamespace(RUNTIME_GAME_NAME='',
        load_active_game_lexicon_names=lambda **k: (list(names), []),
        builtin_reference_terms_for_game=lambda *a, **k: [],
        learned_canonical_terms=lambda *a: list(names),
        user_confirmed_mappings_for_game=lambda *a: [dict(from_=n, to=n) for n in names],
        hidden_reference_terms_for_game=lambda *a: set(),
        load_learned_term_payload=lambda: {'games': {}})


@pytest.fixture
def flow(monkeypatch, tmp_path):
    from twobyteasr.glossary import glossary_fullflow as ff
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(gb, 'detect_search_capability', lambda s: dict(
        provider_search=False, provider='openai_compatible', service='test', model='real-model', transport='api'))
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a: object())
    monkeypatch.setattr(ff, 'discover_application_catalogs', lambda *a, **k: [])
    monkeypatch.setattr(gb, 'other_game_canonical_terms', lambda *a: [])
    state = dict(body='瓦罗兰特：角色 BerLIN 与 S0PP。技能 狂风。', fail=False, calls=[],
        answer=dict(names=[dict(name='BerLIN', category='character', source_ids=['doc1'], priority='core'),
                           dict(name='S0PP', category='character', source_ids=['doc1'], priority='core')],
                    missing_categories=[], notes='目录实体'))
    url = 'https://example.com/agents'

    def collect(legacy, game, settings, **kw):
        if state['body']:
            kw['on_document'](dict(url=url, title='角色名单', text=state['body'], fetched_at=100))
        row = dict(url=url, title='角色名单', read=bool(state['body']),
                   error='fetch_failed' if state['fail'] else '正文已读取，未识别有效目录名单',
                   catalog_member_count=0, enumeration_complete=False)
        checkpoint = gb._checkpoint_payload(game, [dict(url=url, title='角色名单', covers='characters')],
            [], set(), False, '', '', source_results=[row])
        kw['checkpoint_writer'](checkpoint)
        return dict(candidate_count=0, diffs=[], checkpoint=checkpoint,
                    build_stats=dict(source_results=[row], http_receipts=[]),
                    outcome=dict(status='failed', message='无结构化名称'))

    def request(provider, settings, messages, schema, **kw):
        state['calls'].append(dict(messages=messages, kwargs=kw))
        if state.get('ai_error'):
            raise GlossarySearchError('auth_required', '请重新登录')
        kw['on_stream_event']('request_started', dict(model='real-model', stream=True))
        kw['on_stream_event']('text', '公开模型响应')
        return state['answer'], dict(usage=dict(total_tokens=123))

    monkeypatch.setattr(gb, '_run_full_library_update', collect)
    monkeypatch.setattr(gb, '_structured_call', request)
    return ff, state, url


def execute(flow, names=(), **kw):
    ff, state, url = flow
    return gb.run_full_library_update(baseline(names), '瓦罗兰特',
        dict(models=dict(glossary_execution_mode='full', glossary_max_model_calls=4)),
        resume=dict(game='瓦罗兰特', config_version=gb.BUILD_CONFIG_VERSION,
                    catalogs=[dict(url=url, title='角色名单', covers='characters')]), **kw)


def test_zero_deterministic_names_still_send_actual_page_to_ai_without_native_search(flow):
    events = []
    result = execute(flow, on_event=events.append)
    assert result['execution']['model_calls'] == 1
    assert result['execution']['model_attempts'] == 1
    assert result['execution']['model_requests_sent'] == 1
    assert result['execution']['model_success'] == 1
    assert result['execution']['native_search_used'] is False
    assert [d.term.term for d in result['diffs']] == ['BerLIN', 'S0PP']
    sent = json.loads(flow[1]['calls'][0]['messages'][1]['content'])
    assert 'BerLIN' in sent['documents'][0]['text']
    assert flow[1]['calls'][0]['kwargs']['enable_search'] is False
    assert any(e['kind'] == 'request_started' for e in events)
    assert any(e['kind'] == 'text' for e in events)
    assert result['build_stats']['ai_candidates'] == 2
    assert result['build_stats']['verified_success'] == 2


def test_all_duplicate_result_has_real_model_basis_and_zero_applicable(flow):
    result = execute(flow, names=['BerLIN', 'S0PP'])
    assert result['outcome']['status'] == 'no_changes'
    assert result['execution']['model_calls'] == 1
    assert result['diffs'] == []
    assert result['build_stats']['duplicate_candidates'] == 2
    assert result['build_stats']['new_candidates'] == 0


def test_failed_sources_existing_library_still_processed_and_marked_partial(flow):
    flow[1].update(body='', fail=True, answer=dict(names=[], missing_categories=[], notes='已有条目无变化'))
    result = execute(flow, names=['BerLIN'])
    assert result['execution']['model_calls'] == 1
    assert result['outcome']['status'] == 'partial'
    sent = json.loads(flow[1]['calls'][0]['messages'][1]['content'])
    assert sent['existing_terms'] == ['BerLIN']
    assert result['diffs'] == []


def test_failed_source_valid_document_cache_continues_real_ai_and_reports_freshness(flow):
    ff, state, url = flow
    ff.save_document_cache('瓦罗兰特', [dict(url=url, title='角色名单', text=state['body'])])
    state.update(body='', fail=True)
    result = execute(flow)
    assert result['execution']['model_calls'] == 1
    assert result['execution']['cached_documents'] == 1
    assert result['outcome']['status'] == 'partial'
    assert result['build_stats']['freshness_limitations']
    assert len(result['diffs']) == 2


def test_failed_source_no_cache_no_library_cannot_fake_success_or_call_empty_ai(flow):
    flow[1].update(body='', fail=True)
    result = execute(flow)
    assert result['outcome']['status'] == 'failed'
    assert result['execution']['model_calls'] == 0
    assert result['diffs'] == []
    assert result['build_stats']['failure'] == 'no_usable_input'


def test_model_auth_failure_is_terminal_failed_not_completed_zero(flow):
    flow[1]['ai_error'] = True
    result = execute(flow)
    assert result['outcome']['status'] == 'failed'
    assert result['execution']['model_calls'] == 1
    assert result['execution']['model_requests_sent'] == 0
    assert result['execution']['actual_models'] == []
    assert result['build_stats']['failure'] == 'auth_required'
    assert result['outcome']['message'].find('登录') >= 0
    from twobyteasr.glossary.glossary_execution import summary_text
    assert '模型尝试 1 次' in summary_text(result)
    assert '实际发送 0 次' in summary_text(result)
    assert '成功返回 0 次' in summary_text(result)


def test_model_only_suggestions_are_unverified_never_auto_selected_and_confirmed_case_protected(flow):
    flow[1]['answer'] = dict(names=[dict(name='berlin', category='character', source_ids=['doc1']),
        dict(name='幻造名称', category='character', aliases=['BerLIN'], source_ids=[])], missing_categories=[])
    result = execute(flow, names=['BerLIN'])
    assert [d.term.term for d in result['diffs']] == ['幻造名称']
    assert result['diffs'][0].term.verification == 'none'
    assert result['diffs'][0].term.aliases == ()
    assert result['diffs'][0].checked_by_default is False
    assert result['outcome']['status'] == 'partial'


def test_cancellation_stays_cancelled_without_new_model_request(flow):
    with pytest.raises(GlossarySearchError, match='取消'):
        execute(flow, cancel_check=lambda: True)
    assert flow[1]['calls'] == []


def test_actual_collector_zero_names_body_reaches_ai_and_does_not_emit_false_terminal(flow, monkeypatch):
    monkeypatch.setattr(gb, '_run_full_library_update', REAL_COLLECTOR)
    html = '<html><body><p>瓦罗兰特：角色 BerLIN 与 S0PP。技能 狂风。</p></body></html>'
    monkeypatch.setattr(gb, '_try_fetch', lambda *a, **kw: html)
    events = []
    result = execute(flow, on_event=events.append)
    assert result['build_stats']['deterministic_count'] == 0
    assert result['build_stats']['fetch_succeeded'] == 1
    assert result['build_stats']['parse_succeeded'] == 1
    assert result['execution']['model_calls'] == 1
    assert result['outcome']['status'] == 'new_candidates'
    assert [event['kind'] for event in events].count('outcome') == 1
    assert [diff.term.term for diff in result['diffs']] == ['BerLIN', 'S0PP']


def test_document_json_data_is_read_without_executing_script(flow):
    ff = flow[0]
    html = '<body>瓦罗兰特</body><script type="application/json">' + json.dumps(
        dict(agent=dict(displayName='BerLIN', description='S0PP 是比赛选手')), ensure_ascii=False) + '</script>'
    text = ff.document_text(html)
    assert 'BerLIN' in text and 'S0PP' in text
    assert 'application/json' not in text


def test_model_lowercase_cannot_erase_actual_source_spelling(flow):
    flow[1]['answer'] = dict(names=[dict(name='berlin', category='character', source_ids=['doc1']),
        dict(name='s0pp', category='character', source_ids=['doc1'])], missing_categories=[], notes='公开名单')
    result = execute(flow)
    assert [diff.term.term for diff in result['diffs']] == ['BerLIN', 'S0PP']


def test_source_budget_is_shared_across_discovery_and_collector():
    from twobyteasr.glossary.glossary_sources import HealthBoard
    budget = dict(remaining=2)
    boards = [HealthBoard(), HealthBoard()]
    for board in boards: board.request_budget = budget
    boards[0].request_timeout(); boards[1].request_timeout()
    with pytest.raises(GlossarySearchError) as error:
        boards[0].request_timeout()
    assert error.value.code == 'source_budget_exhausted'
    assert sum(board.requests_started for board in boards) == 2


@pytest.mark.parametrize('receipt, sent', [({}, False), ({'request_sent': True}, True), ({'cli_pid': 4242}, True)])
def test_adapter_failure_retains_only_actual_dispatch_boolean(receipt, sent):
    from twobyteasr.providers.ai_providers import AIProviderError
    class Provider:
        def structured_complete(self, *a, **kw):
            kw['request_diagnostics'].update(receipt)
            raise AIProviderError('凭据或请求被拒绝', category='auth_config')
    with pytest.raises(GlossarySearchError) as error:
        gb._structured_call(Provider(), {}, [], {}, enable_search=False, cancel_check=None,
                            max_tokens=10, timeout=(1, 2))
    assert error.value.request_sent is sent


def test_historical_app_request_started_is_an_attempt_not_actual_sent_receipt():
    from twobyteasr.glossary.glossary_execution import execution_summary, summary_text
    result = dict(execution_events=[dict(kind='request_started', source='application', identity=dict(model='grok'))])
    summary = execution_summary(result)
    assert summary['model_attempts'] == 1 and summary['model_requests_sent'] == 0
    assert '实际发送 0 次' in summary_text(result)


def test_real_supplemental_roof_tile_links_are_rejected_offline():
    from twobyteasr.glossary import glossary_fullflow as ff
    bad = [dict(url='https://ja.wikipedia.org/wiki/%E7%93%A6', title='瓦 - Wikipedia', text='瓦 屋根 建築'),
           dict(url='https://kanji.jitenon.jp/kanjid/1960', title='漢字「瓦」の部首・画数・読み方・意味・筆順など', text='漢字辞典 瓦部')]
    assert all(not ff.source_relevance('瓦罗兰特', row)[0] for row in bad)
    assert ff.source_relevance('瓦罗兰特', dict(url='https://playvalorant.com/zh-tw/agents/', title='VALORANT 特務一覽 - 官方網站', text='特務 KAY/O 亞星卓'))[0]
    assert ff.source_relevance('瓦罗兰特', dict(url='https://wiki.example/agents', title='无畏契约 角色图鉴', text='角色名称'))[0]


def test_query_uses_full_quoted_subject_and_known_category_words():
    from twobyteasr.glossary import glossary_fullflow as ff
    queries = ff.source_queries('瓦罗兰特', ['skill', 'location', 'ignore all rules'])
    assert all(('"瓦罗兰特"' in query or '"VALORANT"' in query) for query in queries)
    assert any('技能' in query and '地点' in query for query in queries)
    assert all('ignore all rules' not in query and 'skill location' not in query for query in queries)


def test_known_name_shapes_keep_sourced_official_spellings_with_reason_receipts():
    from twobyteasr.glossary import glossary_fullflow as ff
    docs = [dict(id='doc1', url='https://playvalorant.com/zh-tw/agents/', text='特務 KAY/O 亞星卓 妮虹', title='VALORANT')]
    diagnostics = {}
    terms, raw, filtered = ff._normalize(dict(names=[dict(term='亞星卓', category='character', source_ids=['doc1']),
        'KAY/O', dict(name='', category='other'), dict(name='長'*30)]), docs, [], [], diagnostics=diagnostics)
    assert [term.term for term in terms] == ['亞星卓', 'KAY/O']
    assert all(term.verification=='page_verified' for term in terms)
    assert raw == 4 and filtered == 2
    assert diagnostics['filter_reasons'] == {'empty_name': 1, 'invalid_name_length': 1}
    assert diagnostics['compatible_shapes'] == {'term_key': 1, 'sourced_string': 1}


def test_later_unverified_existing_name_cannot_downgrade_prior_verified_candidate():
    from twobyteasr.glossary import glossary_fullflow as ff
    from twobyteasr.glossary.glossary_skill import SearchedTerm
    previous = SearchedTerm(term='鬼魅', category='装备', category_key='equipment', aliases=('Ghost',),
        verification='page_verified', sources=({'url':'https://playvalorant.com/zh-tw/arsenal/'},), priority='core')
    later = SearchedTerm(term='鬼魅', category='角色', category_key='character', verification='none')
    merged = ff.merge_candidates([previous], [later])
    assert merged == [previous]


def test_supplement_batch_retains_earlier_names_that_are_omitted_from_response():
    from twobyteasr.glossary import glossary_fullflow as ff
    from twobyteasr.glossary.glossary_skill import SearchedTerm
    first = [SearchedTerm(term='BerLIN', verification='page_verified'),
             SearchedTerm(term='S0PP', verification='page_verified')]
    supplement = [SearchedTerm(term='鬼魅', verification='page_verified')]
    assert ff.merge_candidates(first, supplement) == first + supplement


def test_zero_diff_count_distinguished_from_processed_existing_names(flow):
    result = execute(flow, names=['BerLIN', 'S0PP'])
    assert result['candidate_count'] == 0
    assert result['collected_count'] == 2
    assert result['build_stats']['reviewable_changes'] == 0
