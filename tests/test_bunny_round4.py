"""兔白 round 4 (2026-11-16): line-break preference, health check, text edits, learning, recipes, costs,
the step checklist, suggestions, her action log and chats kept per project."""
from __future__ import annotations

import os
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture(autouse=True)
def no_saved_chats():
    """2026-11-16: each project's chat is kept; a test never inherits another test's chat."""
    from twobyteasr.app import bunny_memory
    bunny_memory.clear_chats()
    yield
    bunny_memory.clear_chats()

ALL = dict(level='auto', read_subtitles=True, read_diagnostics=True, remember=True, allow_paid=True, keep_chat=True)


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def private_notice():
    from twobyteasr.app.onboarding import load_state, save_state
    from twobyteasr.app.bunny_chat import NOTICE_KEY
    from twobyteasr.app.bunny_permissions import KEY, DEFAULTS
    save_state(dict(load_state(), **{NOTICE_KEY: True, KEY: dict(DEFAULTS)}))


@pytest.fixture
def settings(monkeypatch):
    """Her settings in memory only: never the user's file."""
    import subtitle_core
    from twobyteasr.app import bunny_subtitle_tools
    values = {'subtitle_language': {'recognition_language': 'zh'}}
    saved = []
    monkeypatch.setattr(subtitle_core, 'RUNTIME_SETTINGS', values, raising=False)
    monkeypatch.setattr(bunny_subtitle_tools, '_save', lambda current: saved.append(dict(current.get('grouping_prompts') or {})))
    return values, saved


@pytest.fixture
def studio(app, tmp_path, monkeypatch):
    from twobyteasr.app import bunny_chat
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    cues = [StudioCue(f'c{i}', i * 3000, i * 3000 + 2000, f'第{i}句元神', speaker_id='S01') for i in range(8)]
    cues.append(StudioCue('c8', 24_000, 26_000, '嘉宾说话', speaker_id='S02'))
    project = SubtitleProject(media=StudioMedia(path=str(tmp_path / 'video.mp4'), duration_ms=60_000), cues=cues,
                              speakers=[StudioSpeaker(id='S01', name='主播'), StudioSpeaker(id='S02', name='嘉宾')])
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, 'load', lambda *a, **k: None)
    monkeypatch.setattr(page, '_generate_waveform', lambda *a, **k: None)
    page.resize(1500, 900)
    page.show()
    page.open_project(save_project(project, tmp_path / 'studio.2byteproj'))
    app.processEvents()
    window = SimpleNamespace(built_page=lambda name: page if name == 'studio' else None)
    monkeypatch.setattr(bunny_chat, 'current_page', lambda _window: '字幕工作台')
    yield page, window
    page.undo_stack.setClean()
    page.close_page()


# ------------------------------------------------------------------ line-break preference
def test_her_line_break_rule_sits_in_its_own_section_and_comes_back_off(settings):
    from twobyteasr.app.bunny_tools import run_turn, undo_records
    from twobyteasr.app.bunny_subtitle_tools import SECTION, current_rules
    from twobyteasr.subtitle_rules.grouping_request import compose_grouping_prompt, custom_grouping_guidance
    values, saved = settings
    window = SimpleNamespace(built_page=lambda _name: None)
    first = run_turn(window, [('set_break_rule', {'rule': '每条尽量不超过10个字'})], ALL)
    assert '成功' in first.receipts[0] and current_rules('zh') == '每条尽量不超过10个字'
    custom = custom_grouping_guidance('zh', values)
    assert SECTION in custom and custom.endswith('每条尽量不超过10个字')
    assert '14' in custom.split(SECTION)[0]                        # the built-in guidance stays in front
    assert '每条尽量不超过10个字' in compose_grouping_prompt('zh', 14, 6, custom)
    # The user's own words outside her section are kept when she rewrites hers.
    values['grouping_prompts']['zh'] = '小兔纸自己写的规则\n' + SECTION + '\n旧的'
    second = run_turn(window, [('set_break_rule', {'rule': '语气词不要单独成条'})], ALL)
    assert values['grouping_prompts']['zh'] == f'小兔纸自己写的规则\n{SECTION}\n语气词不要单独成条'
    assert undo_records(second.undo) == (1, '') and current_rules('zh') == '旧的'
    again = run_turn(window, [('set_break_rule', {'rule': '新的'})], ALL)
    values['grouping_prompts']['zh'] = '后来小兔纸又改了'
    undone, why = undo_records(again.undo)
    assert undone == 0 and '又被改过' in why                           # never tramples a later change
    assert saved
    asked = run_turn(window, [('set_break_rule', {'rule': '更短'})], dict(ALL, level='ask'))
    assert asked.pending and '等小兔纸按「帮我做」' in asked.receipts[0]
    read = run_turn(window, [('break_rules', {})], ALL)
    assert '每条最多 14' in read.receipts[0] and '后来小兔纸又改了' not in read.receipts[0]


def test_a_trial_on_a_few_lines_reports_before_and_after(app, studio, monkeypatch, settings):
    from twobyteasr.app.bunny_tools import run_turn
    from twobyteasr.app.bunny_subtitle_tools import refine_report
    from twobyteasr.projects.studio_project import StudioCue
    from twobyteasr.providers import llm_config
    page, window = studio
    started = []

    class Worker:
        running = True

        def isRunning(self):
            return self.running
    worker = Worker()
    monkeypatch.setattr(llm_config, 'text_ai_key_missing', lambda settings, stage: False)
    monkeypatch.setattr(page, 'run_sentence_refine', lambda **kw: started.append(kw) or setattr(page, '_refine_worker', worker))
    waiting = run_turn(window, [('refine_cues', {'from': 2, 'count': 3})], dict(ALL, level='ask'))
    assert waiting.pending and not started                         # spends the Key: a click first
    done = run_turn(window, [('refine_cues', {'from': 2, 'count': 3})], ALL)
    assert '成功' in done.receipts[0] and started[0]['retry_ids'] == ['c1', 'c2', 'c3']
    assert refine_report(page) is None                             # still running
    cue = page.project.cues[2]
    page.project.cues[2:3] = [StudioCue('n1', cue.start_ms, cue.start_ms + 900, '第2', speaker_id='S01'),
                              StudioCue('n2', cue.start_ms + 900, cue.end_ms, '句元神', speaker_id='S01')]
    page.project.studio_state['ai_sentence_refine'] = {'last_status': 'completed', 'failed_cue_ids': []}
    worker.running = False
    page._bunny_refine_watch['started'] -= 5
    lines = refine_report(page)
    assert lines[0].startswith('试跑好了：1 条重新断了，2 条照旧')
    assert any('第 3 条：第2句元神 → 第2 | 句元神' in line for line in lines) and '全片都这样' in lines[-1]
    assert refine_report(page) == []                               # said once
    too_many = run_turn(window, [('refine_cues', {'from': 1, 'count': 40})], ALL)
    assert '没做成' in too_many.receipts[0]


# ------------------------------------------------------------------ health check, text edits
def test_the_health_check_names_lines_and_the_safe_fix_is_one_undo(app, studio):
    from twobyteasr.app.bunny_tools import run_turn, undo_records
    page, window = studio
    page.project.cues[1].text = '第1句  元神 '
    page.project.cues[5].end_ms = page.project.cues[5].start_ms + 150     # too short to read
    report = run_turn(window, [('check_subtitles', {'scope': 'all'})], ALL)
    assert '成功' in report.receipts[0] and '能安全自动修' in report.receipts[0]
    lines = report.receipts[0].splitlines()
    assert '第 6 条' in lines[1] and '较严重' in lines[1] and any('多余空格' in line and '第 2 条' in line for line in lines)
    before = [(cue.text, cue.start_ms, cue.end_ms) for cue in page.project.cues]
    fixed = run_turn(window, [('fix_subtitles', {})], ALL)
    assert '成功' in fixed.receipts[0]
    assert [(cue.text, cue.start_ms, cue.end_ms) for cue in page.project.cues] != before
    assert undo_records(fixed.undo) == (1, '')
    assert [(cue.text, cue.start_ms, cue.end_ms) for cue in page.project.cues] == before


def test_she_edits_text_replaces_words_and_merges_and_each_comes_back(app, studio):
    from twobyteasr.app.bunny_tools import run_turn, undo_records
    page, window = studio
    page.project.studio_state['manual_caption_text'] = {'c1': page.project.cues[1].text}
    edit = run_turn(window, [('edit_cue', {'number': 2, 'text': '第一句原神'}),
                             ('edit_cue', {'number': 2, 'text': 'The first line', 'layer': 'translation'})], ALL)
    assert all('成功' in line for line in edit.receipts), edit.receipts
    assert page.project.cues[1].text == '第一句原神'
    from twobyteasr.timeline.studio_commands import LEARNABLE_TEXT_ORIGINS
    assert edit.undo[0].commands[0].origin not in LEARNABLE_TEXT_ORIGINS
    assert page.project.generation_metadata['translations']['c1'] == 'The first line'
    swap = run_turn(window, [('replace_text', {'find': '元神', 'replace': '原神', 'scope': 'all'})], ALL)
    assert '成功' in swap.receipts[0] and '7 条字幕' in swap.receipts[0]
    assert not any('元神' in cue.text for cue in page.project.cues)
    merge = run_turn(window, [('merge_cues', {'from': 4, 'to': 5})], ALL)
    assert '成功' in merge.receipts[0] and len(page.project.cues) == 8
    mixed = run_turn(window, [('merge_cues', {'from': 7, 'to': 8})], ALL)
    assert '不是同一个说话人' in mixed.receipts[0]
    empty = run_turn(window, [('edit_cue', {'number': 1, 'text': '  '})], ALL)
    assert '没做成' in empty.receipts[0]
    assert undo_records(edit.undo + swap.undo + merge.undo) == (4, '')
    assert [cue.text for cue in page.project.cues][:3] == ['第0句元神', '第1句元神', '第2句元神']
    assert not page.project.generation_metadata.get('translations', {}).get('c1')


# ------------------------------------------------------------------ learning, recipes, costs
def test_what_the_user_keeps_correcting_shows_up_and_is_private_when_reading_is_off(app, studio):
    from twobyteasr.app.bunny_tools import run_turn, snapshot
    page, window = studio
    page._learning_store = SimpleNamespace(load=lambda: {'candidates': [
        {'status': 'pending', 'original_term': '元神', 'corrected_term': '原神', 'occurrence_count': 3},
        {'status': 'collecting', 'original_term': '一次', 'corrected_term': '一回', 'occurrence_count': 1},
        {'status': 'accepted', 'original_term': '旧', 'corrected_term': '新', 'occurrence_count': 9}]})
    state = snapshot(window)
    assert '元神→原神（改过 3 次，这个工程还剩 8 处）' == state['learned']
    read = run_turn(window, [('learned_edits', {})], ALL)
    assert '「元神」→「原神」' in read.receipts[0] and '一回' not in read.receipts[0] and '新' not in read.receipts[0]
    refused = run_turn(window, [('learned_edits', {})], dict(ALL, read_subtitles=False))
    assert '关掉了' in refused.receipts[0]


def test_a_recipe_is_saved_and_applied_in_one_undo(app, studio, settings):
    from twobyteasr.app import bunny_memory
    from twobyteasr.app.bunny_tools import run_turn, undo_records
    from twobyteasr.app.bunny_subtitle_tools import current_rules
    page, window = studio
    bunny_memory.clear()
    run_turn(window, [('set_break_rule', {'rule': '短一点'})], ALL)
    saved = run_turn(window, [('save_recipe', {'name': '原神'})], ALL)
    assert '存好配方「原神」' in saved.receipts[0] and '断句偏好「短一点」' in saved.receipts[0]
    recipe = next(row for row in bunny_memory.load() if row['kind'] == 'recipe')
    assert recipe['data']['speakers'] == ['主播', '嘉宾'] and '小兔纸的配方' in bunny_memory.prompt_block()
    run_turn(window, [('save_recipe', {'name': '原神'})], ALL)
    assert sum(row['kind'] == 'recipe' for row in bunny_memory.load()) == 1      # same name: updated
    recipe['data'] = dict(recipe['data'], speakers=['阿明', '小雨'], break_rule='更短',
                          style=dict(recipe['data']['style'], fill_color='#FFD400'))
    rows = [row if row['kind'] != 'recipe' else recipe for row in bunny_memory.load()]
    bunny_memory._write(rows)
    used = run_turn(window, [('use_recipe', {'name': '原神'})], ALL)
    assert '成功' in used.receipts[0], used.receipts
    assert [s.name for s in page.project.speakers] == ['阿明', '小雨'] and current_rules('zh') == '更短'
    count, why = undo_records(used.undo)
    assert not why and [s.name for s in page.project.speakers] == ['主播', '嘉宾'] and current_rules('zh') == '短一点'
    missing = run_turn(window, [('use_recipe', {'name': '没有'})], ALL)
    assert '没有叫「没有」的配方' in missing.receipts[0]
    refused = run_turn(window, [('save_recipe', {'name': 'x'})], dict(ALL, remember=False))
    assert '关掉了' in refused.receipts[0]
    bunny_memory.clear()


def test_costs_are_rough_and_say_so(app, studio, monkeypatch):
    from twobyteasr.app import bunny_subtitle_tools
    from twobyteasr.app.bunny_tools import run_turn
    from twobyteasr.providers import usage_ledger
    page, window = studio
    monkeypatch.setattr(bunny_subtitle_tools, '_rates', lambda stage='group': ('deepseek-v4-flash', dict(
        known=True, rates_low=['0.003', '0.15', '0.6'], rates_high=['0.006', '0.3', '1.2'])))
    estimate = run_turn(window, [('estimate_cost', {'what': 'refine_all'})], ALL)
    assert '9 条' in estimate.receipts[0] and '美元' in estimate.receipts[0] and '以服务商账单为准' in estimate.receipts[0]
    monkeypatch.setattr(bunny_subtitle_tools, '_rates', lambda stage='group': ('my-model', dict(known=False)))
    unknown = run_turn(window, [('estimate_cost', {'what': 'refine_all'})], ALL)
    assert '没有价目' in unknown.receipts[0]
    month = time.strftime('%Y-%m-%d')
    monkeypatch.setattr(usage_ledger, 'read_rows', lambda path=None: [
        dict(at=f'{month}T10:00:00', stage='group', cost=dict(known=True, low='0.01', high='0.02')),
        dict(at=f'{month}T11:00:00', stage='bunny_chat', cost=dict(known=False)),
        dict(at='2001-01-01T00:00:00', stage='group', cost=dict(known=True, low='5', high='5'))])
    used = run_turn(window, [('usage', {})], ALL)
    assert '这个月：2 次请求' in used.receipts[0] and '0.0100–0.0200' in used.receipts[0] and '1 次没有价目' in used.receipts[0]


# ------------------------------------------------------------------ the chat: steps, suggestions, log, saved chats
@pytest.fixture
def chat_env(app, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from twobyteasr.app import bunny_chat
    monkeypatch.setattr(bunny_chat.BunnyChat, 'FLOATING', False)
    monkeypatch.setattr(bunny_chat, 'ai_readiness', lambda settings: (True, 'DeepSeek · deepseek-chat'))
    window = QWidget()
    window.resize(1100, 720)
    window.show()
    app.processEvents()
    yield bunny_chat, window
    chat = getattr(window, '_bunny_chat', None)
    if chat is not None:
        chat.close_chat()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_steps_suggestions_and_her_log(app, chat_env, monkeypatch):
    from twobyteasr.app import bunny_persona
    from twobyteasr.app.bunny_tools import UndoRecord
    bunny_chat, window = chat_env
    monkeypatch.setattr(bunny_chat, 'current_page', lambda _window: '首页')
    chat = bunny_chat.open_bunny_chat(window)
    chat.reveal_all()
    reply = bunny_persona.parse_reply('{"lines": ["先选素材～"], "steps": ["选素材", "选识别方式", "开始识别"], "step_now": 1}', [])
    chat.say(reply)
    chat.reveal_all()
    assert chat.steps_label.isVisible() and '✓ 选素材' in chat.steps_label.text() and '▶ 2. 选识别方式' in chat.steps_label.text()
    assert '"steps"' in chat._reply_turn(reply)['content']
    chat.set_mode('thread' if chat.mode == 'dialog' else 'dialog')          # moving views must not hide it
    chat.reveal_all()
    assert chat.steps_label.isVisible()
    chat.say(bunny_persona.parse_reply('{"lines": ["做完啦"], "steps": []}', []))
    chat.reveal_all()
    assert not chat.steps_label.isVisible()
    chat.refresh_suggestions()
    labels = [chat.suggest_row.layout().itemAt(i).widget().text().removeprefix(bunny_chat.CHOICE_MARK) for i in range(chat.suggest_row.layout().count())]
    assert labels == ['我该怎么开始？', '打开最近一次识别结果'] and chat.suggest_row.isVisible()
    asked = []
    monkeypatch.setattr(chat, '_ask', lambda question: asked.append(question))
    chat.suggest_row.layout().itemAt(0).widget().click()
    assert asked == ['我该怎么开始？']
    undone = []
    record = UndoRecord('call', lambda: undone.append(1) or '', 0)
    chat._question = '把说话人改名'
    chat._log(['- rename_speaker(speaker=S01, name=阿明)：成功。改名了'], [record])
    dialog = chat.show_log()
    from PySide6.QtWidgets import QListWidget
    listing = dialog.findChild(QListWidget, 'bunnyLogList')
    assert listing.count() == 1 and '把说话人改名' in listing.item(0).text()
    listing.setCurrentRow(0)
    from PySide6.QtWidgets import QPushButton
    button = next(b for b in dialog.findChildren(QPushButton) if b.objectName() == 'bunnyLogUndo')
    assert button.isEnabled()
    button.click()
    assert undone == [1] and chat.log_entries[0]['undone'] and '已撤销' in listing.item(0).text()
    dialog.close()


def test_each_projects_chat_comes_back_unless_turned_off(app, chat_env, monkeypatch):
    from twobyteasr.app import bunny_memory, bunny_permissions
    bunny_chat, window = chat_env
    bunny_memory.clear_chats()
    bunny_memory.save_chat('home', [('user', '你好'), ('bunny', '嗨～'), ('bunny', '有事就问'), ('user', '我的 sk-abcdefgh12345678')])
    assert bunny_memory.load_chat('home') == [('user', '你好'), ('bunny', '嗨～'), ('bunny', '有事就问')]   # no secrets kept
    history = bunny_chat.history_from(bunny_memory.load_chat('home'))
    assert [turn['role'] for turn in history] == ['user', 'assistant'] and '有事就问' in history[1]['content']
    chat = bunny_chat.open_bunny_chat(window)
    chat.reveal_all()
    assert chat.transcript[:3] == [('user', '你好'), ('bunny', '嗨～'), ('bunny', '有事就问')]
    assert '欢迎回来～' in [text for _who, text in chat.transcript]
    chat.close_chat()
    app.processEvents()
    assert ('bunny', '欢迎回来～') in bunny_memory.load_chat('home')
    bunny_permissions.save({'keep_chat': False})
    chat = bunny_chat.open_bunny_chat(window)
    chat.reveal_all()
    assert ('user', '你好') not in chat.transcript
    bunny_permissions.save({'keep_chat': True})
    bunny_memory.clear_chats()
    assert bunny_memory.load_chat('home') == []


def test_right_click_asks_her_about_that_line(app, chat_env, studio):
    bunny_chat, window = chat_env
    page, _fake = studio
    window.built_page = lambda name: page if name == 'studio' else None
    chat = bunny_chat.ask_about_cue(window, 'c2')
    assert chat is not None and chat.input.text() == '第 3 条「第2句元神」：'
    assert bunny_chat.ask_about_cue(window, 'nope') is None


def test_waiting_buttons_name_the_new_edits():
    from twobyteasr.app.bunny_tools import pending_summary
    assert pending_summary([('replace_text', {'find': '元神', 'replace': '原神'})]) == '「元神」全换成「原神」'
    assert pending_summary([('edit_cue', {'number': 3, 'text': '你好', 'layer': 'translation'})]) == '第 3 条译文改成「你好」'
    assert pending_summary([('refine_cues', {'from': 4, 'count': 5})]) == '用 AI 试断第 4 条起 5 条'
    assert pending_summary([('set_break_rule', {'rule': ''})]) == '清掉断句偏好'
