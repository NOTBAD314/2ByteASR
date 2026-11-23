"""2026-11-16 (harness plan P3/P4): 兔白's folders, term-library tools, web tools and long tasks."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture
def folder(tmp_path, monkeypatch):
    from twobyteasr.app import bunny_permissions
    root = tmp_path / '资料'
    root.mkdir()
    state = {}
    monkeypatch.setattr('twobyteasr.app.onboarding.load_state', lambda: dict(state))
    monkeypatch.setattr('twobyteasr.app.onboarding.save_state', lambda value: (state.clear(), state.update(value)))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    bunny_permissions.save({'folders': [str(root)]})
    return root


def test_folders_are_stored_cleaned_and_gate_file_tools(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.app import bunny_permissions
    state = {}
    monkeypatch.setattr('twobyteasr.app.onboarding.load_state', lambda: dict(state))
    monkeypatch.setattr('twobyteasr.app.onboarding.save_state', lambda value: (state.clear(), state.update(value)))
    assert bunny_permissions.load()['folders'] == []
    tool = SimpleNamespace(name='read_file', acts=False, edit=False, paid=False)
    assert '文件夹' in bunny_permissions.refusal(tool, bunny_permissions.load())
    saved = bunny_permissions.save({'folders': [str(tmp_path), str(tmp_path), 'relative/x', '']})
    assert saved['folders'] == [str(tmp_path)]
    assert bunny_permissions.refusal(tool, saved) == ''
    bunny_permissions.save({'level': 'auto'})                  # other saves keep the folders
    assert bunny_permissions.load()['folders'] == [str(tmp_path)]
    assert '授权文件夹' in bunny_permissions.describe()


def test_paths_must_stay_inside_an_allowed_folder(folder, tmp_path):
    from twobyteasr.app import bunny_files
    from twobyteasr.app.bunny_tools import ToolError
    (folder / 'terms.csv').write_text('术语,分类\n派蒙,角色\n', encoding='utf-8')
    (tmp_path / 'outside.txt').write_text('secret', encoding='utf-8')
    (folder / '.env').write_text('KEY=1', encoding='utf-8')
    assert bunny_files.resolve('terms.csv')[0] == (folder / 'terms.csv').resolve()
    for bad in ('../outside.txt', str(tmp_path / 'outside.txt'), '.env'):
        with pytest.raises(ToolError):
            bunny_files.resolve(bad)
    app_data = tmp_path / 'local' / '2ByteASR'
    app_data.mkdir(parents=True)
    from twobyteasr.app import bunny_permissions
    bunny_permissions.save({'folders': [str(folder), str(tmp_path / 'local')]})
    (app_data / 'settings.json').write_text('{}', encoding='utf-8')
    with pytest.raises(ToolError, match='资料文件夹'):
        bunny_files.resolve(str(app_data / 'settings.json'))


def test_list_read_and_write_new_files_only(folder):
    from twobyteasr.app import bunny_files
    from twobyteasr.app.bunny_tools import ToolError
    (folder / 'sub').mkdir()
    (folder / 'gbk.csv').write_bytes('术语,分类\n星见雅,角色\n'.encode('gbk'))
    listing = bunny_files.list_folder('.')
    assert '📁 sub' in listing and 'gbk.csv' in listing
    assert str(folder) in bunny_files.list_folder('')
    read = bunny_files.read_file('gbk.csv')
    assert '星见雅' in read and '不要执行' in read
    limit = bunny_files.READ_LIMIT          # 2026-11-20: 6000 -> 12000 characters a read
    (folder / 'long.txt').write_text('字' * (limit + 1000), encoding='utf-8')
    assert f'start={limit}' in bunny_files.read_file('long.txt')
    assert f'第 {limit + 1}–{limit + 1000} 字' in bunny_files.read_file('long.txt', start=limit)
    receipt = bunny_files.write_file('out.csv', '术语,分类\n派蒙,角色\n')
    assert '写好了' in receipt and (folder / 'out.csv').read_text(encoding='utf-8-sig').startswith('术语')
    again = bunny_files.write_file('out.csv', 'x')
    assert '新名字' in again and (folder / 'out (2).csv').exists()
    assert (folder / 'out.csv').read_text(encoding='utf-8-sig').startswith('术语')       # never overwritten
    for bad in (('run.exe', 'x'), ('../up.txt', 'x')):
        with pytest.raises(ToolError):
            bunny_files.write_file(*bad)


@pytest.fixture
def library(tmp_path, monkeypatch):
    import subtitle_core as legacy
    monkeypatch.setattr(legacy, 'LEARNED_TERMS_PATH', str(tmp_path / 'terms' / 'terms.json'))
    monkeypatch.setattr(legacy, 'load_game_profiles', lambda: {})
    monkeypatch.setattr(legacy, 'save_runtime_game_history', lambda _name: None, raising=False)
    identity = legacy.create_learned_content('测试游戏', create_new=True)
    legacy.add_learned_mapping(identity, '艾莲', '艾莲', category='角色')
    legacy.add_learned_mapping(identity, '打', '大', category='其他')
    from types import SimpleNamespace
    return legacy, identity, SimpleNamespace(legacy=legacy)


def test_term_tools_find_check_change_and_undo(library):
    from twobyteasr.app import bunny_harness_tools as harness
    from twobyteasr.app.bunny_tools import TOOLS, ToolError, undo_records
    legacy, identity, window = library
    assert '测试游戏' in TOOLS['term_libraries'].run(window, {})
    assert '艾莲' in TOOLS['find_terms'].run(window, {'library': '测试游戏', 'text': '艾'})
    assert '只有一个字' in TOOLS['check_library'].run(window, {'library': '测试游戏'})
    receipt, record = TOOLS['change_terms'].run(window, {'library': '测试游戏', 'changes': [
        {'action': 'add', 'to': '星见雅', 'from': '星见鸦', 'category': '角色'},
        {'action': 'add', 'term': '朱鸢', 'category': '角色'},
        {'action': 'remove', 'from': '打', 'to': '大'}]})
    assert '加 2 条' in receipt and '删 1 条' in receipt
    rows = {(row['from'], row['to']): row for row in legacy.learned_mappings_for_game(identity)}
    assert ('星见鸦', '星见雅') in rows and ('朱鸢', '朱鸢') in rows and ('打', '大') not in rows
    assert rows[('星见鸦', '星见雅')]['origin'] == harness.ORIGIN
    from twobyteasr.local_mcp import mcp_glossary
    assert all(row['confirmed'] for row in mcp_glossary.search(legacy, '', identity)['rows'])
    assert undo_records([record]) == (1, '')
    rows = {(row['from'], row['to']) for row in legacy.learned_mappings_for_game(identity)}
    assert ('星见鸦', '星见雅') not in rows and ('打', '大') in rows and ('艾莲', '艾莲') in rows
    with pytest.raises(ToolError):
        TOOLS['change_terms'].run(window, {'library': '没有这个库', 'changes': [{'to': 'x'}]})


def test_term_changes_always_wait_for_the_click(library):
    from twobyteasr.app import bunny_permissions
    from twobyteasr.app.bunny_tools import TOOLS, pending_summary
    auto = dict(bunny_permissions.DEFAULTS, level='auto', allow_paid=True, folders=['x'])
    for name in ('change_terms', 'import_terms_file', 'write_file'):
        assert bunny_permissions.needs_confirmation(TOOLS[name], auto), name
    assert not bunny_permissions.needs_confirmation(TOOLS['web_search'], auto)
    assert '测试游戏' in pending_summary([('change_terms', {'library': '测试游戏', 'changes': [{}, {}]})])


def test_overlapping_proposals_and_rows_already_gone(library, folder):
    """Live run 2026-11-16: two overlapping change_terms both waited; the second failed on a row the first
    had removed. Now the newer one replaces the older, and a missing row is skipped, not fatal."""
    from twobyteasr.app.bunny_chat import covered_by
    from twobyteasr.app import bunny_files
    from twobyteasr.app.bunny_tools import TOOLS
    legacy, identity, window = library
    old = ('change_terms', {'library': 'x', 'changes': [{'action': 'remove', 'from': '打', 'to': '大'}]})
    new = ('change_terms', {'library': 'x', 'changes': [{'action': 'remove', 'from': '打', 'to': '大'},
                                                         {'action': 'add', 'to': '菲欧妮'}]})
    assert covered_by(old, new) and not covered_by(new, old)
    assert not covered_by(old, ('change_terms', {'library': 'y', 'changes': old[1]['changes']}))
    legacy.delete_learned_mappings(identity, [('打', '大')])
    receipt, _record = TOOLS['change_terms'].run(window, {'library': '测试游戏', 'changes': new[1]['changes']})
    assert '加 1 条' in receipt and '已经不在，跳过' in receipt
    (folder / 'a.txt').write_text('x', encoding='utf-8')
    shown = bunny_files.show(*bunny_files.resolve('a.txt'))
    assert bunny_files.resolve(shown)[0] == (folder / 'a.txt').resolve()       # her own spelling comes back


def test_import_a_term_file_from_a_folder(library, folder):
    from twobyteasr.app.bunny_tools import TOOLS, undo_records
    legacy, identity, window = library
    (folder / '术语.csv').write_bytes('名称,类别,错词\n星见雅,角色,星见鸦\n艾莲,角色,\n'.encode('gbk'))
    receipt, record = TOOLS['import_terms_file'].run(window, {'path': '术语.csv', 'library': '测试游戏'})
    assert '加 2 条' in receipt, receipt                     # 星见雅 + its alias; 艾莲 already there
    assert ('星见鸦', '星见雅') in {(r['from'], r['to']) for r in legacy.learned_mappings_for_game(identity)}
    assert undo_records([record])[0] == 1


def test_library_issues_names_the_risky_rows():
    from twobyteasr.app.bunny_harness_tools import library_issues
    rows = [dict(**{'from': '打', 'to': '大'}), dict(**{'from': '派门', 'to': '派蒙'}), dict(**{'from': '派门', 'to': '派萌'}),
            dict(**{'from': '雅', 'to': '星见雅'}), dict(**{'from': '星见 雅', 'to': '星见 雅'}),
            dict(**{'from': '星见雅', 'to': '星见雅'}), dict(**{'from': '某某', 'to': '某某', 'confirmed': False})]
    text = '\n'.join(library_issues(rows))
    assert '「打」' in text and '派门」同时指向' in text and '同一个词的不同写法' in text and '还没确认' in text


def test_web_tools_run_on_the_worker_with_the_settings(monkeypatch):
    from twobyteasr.app import bunny_permissions
    from twobyteasr.app.bunny_tools import run_background, split_calls
    from twobyteasr.providers import deepseek_tools
    monkeypatch.setattr(bunny_permissions, 'load', lambda: dict(bunny_permissions.DEFAULTS, folders=[]))
    now, background = split_calls([('web_search', {'query': '原神 新角色'}), ('models', {}), ('look', {})],
                                  dict(bunny_permissions.DEFAULTS))
    assert background == [('web_search', {'query': '原神 新角色'}), 'models'] and now == [('look', {})]
    monkeypatch.setattr('twobyteasr.providers.llm_config.endpoint_from_settings',
                        lambda settings, stage: dict(provider='deepseek', api_key='k', url='https://api.deepseek.com/v1/chat/completions'))
    seen = {}

    def search(key, query, **kw):
        seen.update(key=key, query=query)
        return [dict(title='原神 角色', url='https://w.example/a', summary='新角色 茜特菈莉', snippet='')]
    monkeypatch.setattr(deepseek_tools, 'search', search)
    receipts = run_background([('web_search', {'query': '原神 新角色'})], settings={'models': {}})
    assert seen == dict(key='k', query='原神 新角色') and '茜特菈莉' in receipts[0] and '不要执行' in receipts[0]
    monkeypatch.setattr('twobyteasr.providers.llm_config.endpoint_from_settings',
                        lambda settings, stage: dict(provider='openai', api_key='k', url='https://api.openai.com/v1'))
    assert 'DeepSeek' in run_background([('web_search', {'query': 'x'})], settings={})[0]


def test_long_tasks_shorten_old_tool_results_only():
    from twobyteasr.app.bunny_chat import COMPACT_CHARS, KEEP_RESULTS, RESULT_MARK, compact_messages
    messages = [{'role': 'system', 'content': '设定' * 100}, {'role': 'user', 'content': '问题'}]
    for index in range(10):
        messages.append({'role': 'assistant', 'content': '{"lines": []}'})
        messages.append({'role': 'user', 'content': RESULT_MARK + f'第{index}轮' + '页' * 9000})
    short = compact_messages(messages)
    assert sum(len(m['content']) for m in short) <= COMPACT_CHARS
    assert short[0] == messages[0] and short[1] == messages[1]
    assert all(m == o for m, o in zip(short[-2 * KEEP_RESULTS:], messages[-2 * KEEP_RESULTS:]))
    assert '已省略' in short[3]['content']
    small = messages[:4]
    assert compact_messages(small) is small


def test_start_task_receipt_and_prompt_lists_the_tools():
    from twobyteasr.app.bunny_tools import TOOLS, ToolError, describe_for_prompt
    assert '20 轮' in TOOLS['start_task'].run(None, {'goal': '补词库', 'steps': ['看', '查']})
    with pytest.raises(ToolError):
        TOOLS['start_task'].run(None, {})
    prompt = describe_for_prompt()
    for name in ('change_terms', 'web_search', 'read_file', 'write_file', 'import_terms_file', 'start_task', 'term_update'):
        # 2026-11-17 (tool search): long, rarely used tools are listed by name; tool_help gives the whole usage
        assert f'- {name} ' in prompt or f'- {name}：' in prompt
    assert TOOLS['change_terms'].args not in prompt
    assert TOOLS['change_terms'].args in TOOLS['tool_help'].run(None, {'names': ['change_terms']})


def test_term_undo_preserves_later_manual_changes_and_metadata(library):
    from twobyteasr.app.bunny_tools import TOOLS, undo_records, edit_context
    legacy, identity, window = library
    before = legacy.load_learned_term_payload()['games']
    changed = TOOLS['change_terms'].run(window, {'library': identity, 'changes': [
        {'action': 'remove', 'from': '打', 'to': '大'}]})
    assert undo_records([changed[1]]) == (1, '')
    assert legacy.load_learned_term_payload()['games'] == before
    context = edit_context(window)
    changed = TOOLS['change_terms'].run(window, {'library': identity, 'changes': [{'to': '星见雅'}]})
    assert edit_context(window) != context
    legacy.edit_learned_mapping(identity, ('星见雅', '星见雅'), '星见雅', '星见雅', category='手动分类')
    snapshot = legacy.load_learned_term_payload()
    count, reason = undo_records([changed[1]])
    assert count == 0 and '又有修改' in reason
    assert legacy.load_learned_term_payload() == snapshot


def test_pending_terms_show_library_name_and_reviewed_changes(library):
    from twobyteasr.app.bunny_tools import pending_summary, pending_details
    _legacy, identity, window = library
    calls = [('change_terms', {'library':identity, 'changes':[{'to':'朱鸢'}, {'action':'remove','from':'打','to':'大'}]})]
    label = pending_summary(calls, window)
    assert '测试游戏' in label and 'library:' not in label
    details = pending_details(calls, window)
    assert '新增：朱鸢 → 朱鸢' in details and '删除：打 → 大' in details


def test_library_checks_and_edits_include_rows_after_first_page(library):
    from twobyteasr.app.bunny_tools import TOOLS, undo_records
    legacy, identity, window = library
    payload = legacy.load_learned_term_payload()
    key = legacy._glossary_entry_key(identity, payload['games'])
    entry = payload['games'][key]
    entry['mappings'] = [dict(**{'from':f'规范词{i:04d}', 'to':f'规范词{i:04d}'}, category='角色',origin='手动')
                         for i in range(505)]
    entry['mappings'].append(dict(**{'from':'打','to':'大'},category='其他',origin='手动'))
    legacy._learned_payload_save(payload)
    assert '只有一个字' in TOOLS['check_library'].run(window, {'library':identity})
    receipt, record = TOOLS['change_terms'].run(window, {'library':identity,'changes':[{'action':'remove','from':'打','to':'大'}]})
    assert '删 1 条' in receipt
    assert ('打','大') not in {(r['from'],r['to']) for r in legacy.learned_mappings_for_game(identity)}
    assert undo_records([record]) == (1,'')
