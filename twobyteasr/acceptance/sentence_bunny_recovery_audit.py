"""Replay an explicitly supplied project through normal Studio and Bunny entry points."""
import hashlib
import json
from copy import deepcopy


def run(window, page, output, check, wait):
    from PySide6.QtWidgets import QApplication
    from ..app import bunny_chat, bunny_permissions
    from ..exports.studio_subtitle_export import _compile_format
    from ..projects.studio_project import load_project
    from ..providers import ai_providers, llm_config

    project = page.project
    case = json.loads((output/'fixture.replay.json').read_bytes())
    history = page._historical_refine_windows()
    check('all historical windows map by source evidence', len(history) == case['historical_windows'] and all(
        row['status'] == 'matched' for row in history)
        and len({key for row in history for key in row['cue_ids']}) == case['historical_cue_count'])
    chosen = [cue.id for cue in project.cues if cue.id in case['cue_ids']]
    check('all reported examples exist', set(chosen) == set(case['cue_ids']))
    remote = []
    report = {
        'research_job_id': history[0]['job_id'],
        'historical_windows': len(history),
        'historical_cue_ids': len({key for row in history for key in row['cue_ids']}),
        'provider': 'Controlled replay with source recording and word times',
    }
    (output/'audit-record.json').write_text(json.dumps(report, ensure_ascii=False), 'utf-8')
    long_reply = '\n'.join(f'第 {index} 行完整核验结果。' * 18 for index in range(16)) + '\n最後一行驗證字串'
    chat_calls = []
    retry_via_chat = False
    chain = []
    chain_folder = output / '当前工程历史回退与字词证据的多步骤核验记录'
    chain_folder.mkdir()
    chain_file = chain_folder / '核验明细和实际应用报告.json'
    long_report = {}

    class Replay:
        endpoint = {}
        provider_id = 'deepseek'
        model = 'deepseek-flash'

        def complete(self, messages, **kwargs):
            stage = kwargs['stage']
            if stage == 'sentence_refine':
                payload = json.loads(messages[-1]['content'])
                remote.append(payload)
                if len(remote) == 1:
                    return ''
                if len(remote) == 2:
                    return '{"results":'
                rows = []
                for cue in payload['cues']:
                    text = cue['text']
                    prefixes = case['responses'].get(text)
                    if retry_via_chat and text == '在我研读完老师们收集的各项调查报告之后':
                        prefixes = ['在我研读完']
                    split = prefixes is not None
                    rows.append(dict(cue_id=cue['cue_id'], action='split' if split else 'keep',
                                     break_after=[f'b{len(part):05d}' for part in prefixes or ()] if split else []))
                return json.dumps({'results': rows}, ensure_ascii=False)
            chat_calls.append(str(messages[-1]['content']))
            if retry_via_chat:
                received = str(messages[-1]['content'])
                chain.append(received)
                if len(chain) == 1:
                    return json.dumps({'tools': [
                        {'name': 'start_task', 'args': {'goal': '核对并处理断句', 'steps': ['读取', '重试', '保存', '核对']}},
                        {'name': 'read_file', 'args': {'path': 'audit-record.json'}},
                    ]}, ensure_ascii=False)
                if len(chain) == 2:
                    return '{"tools":[{"name":"ai_refine","args":{"scope":"failed"}}]}'
                if len(chain) == 3:
                    long_report.update(summary=received, history=[
                        dict(范围=row['range_id'], 证据=dict(来源=row['source_ids'], 字幕=row['cue_ids'],
                             时间=[row['start_ms'], row['end_ms']])) for row in history])
                    return json.dumps({'tools': [{'name': 'write_file', 'args': {'path': str(chain_file),
                        'content': json.dumps(long_report, ensure_ascii=False, separators=(',', ':'))}}]}, ensure_ascii=False)
                if len(chain) == 4:
                    return json.dumps({'tools': [{'name': 'read_file', 'args': {'path': str(chain_file)}}]})
                return json.dumps({'body': long_reply, 'suggest': ['查看核验', '返回工程']}, ensure_ascii=False)
            if len(chat_calls) == 1:
                return json.dumps({'tools': [{'name': 'read_file', 'args': {'path': 'audit-record.json'}}]})
            if len(chat_calls) == 2:
                return json.dumps({'tools': [
                    {'name': 'write_file', 'args': {'path': 'report.txt',
                        'content': f"历史窗口 {report['historical_windows']} 个，定位字幕 {report['historical_cue_ids']} 条。\n"}},
                    {'name': 'write_file', 'args': {'path': 'report.json', 'content': json.dumps(report, ensure_ascii=False)}},
                ]}, ensure_ascii=False)
            return json.dumps({'body': long_reply, 'suggest': ['查看核验', '返回工程']}, ensure_ascii=False)

    old_provider = ai_providers.provider_for_stage
    old_key_check = llm_config.text_ai_key_missing
    old_readiness = bunny_chat.ai_readiness
    old_permission = bunny_permissions.load()
    card = None
    try:
        ai_providers.provider_for_stage = lambda *args, **kwargs: Replay()
        llm_config.text_ai_key_missing = lambda *args: False
        bunny_chat.ai_readiness = lambda settings: (True, 'Controlled replay')
        bunny_permissions.save(dict(old_permission, level='auto', allow_paid=True, folders=[str(output)],
                                    keep_chat=True, remember=True))
        original = [(c.id, c.text, c.start_ms, c.end_ms) for c in project.cues]
        initial_refine_state = deepcopy(project.studio_state.get('ai_sentence_refine'))
        task_id = page.run_sentence_refine(whole_project=False, retry_ids=chosen)
        task = page._subtitle_tasks[task_id]
        # A parallel edit between a file read and a proposed write correctly
        # invalidates that tool turn. Test both flows without racing consent.
        wait(lambda: task.ended is not None)
        card = bunny_chat.open_bunny_chat(window)
        card.set_mode('thread')
        card.input.setText('读取 audit-record.json，生成 TXT 和 JSON 报告并核验写入')
        card.send()
        wait(lambda: not card.busy and task.ended is not None)
        card.reveal_all()
        (output/'initial-turn-counts.json').write_text(json.dumps(
            dict(chat=len(chat_calls), subtitle=len(remote), task=task.counts(), actions=card.action_log,
                 pending=[name for name, _ in card._pending_edits], history=card._history[-3:], requests=[
                dict(attempt=row.get('attempt'), category=row.get('category'), status=row.get('status'))
                for row in getattr(task, 'requests', ())]), ensure_ascii=False), 'utf-8')
        check('chat and subtitle requests each reached a terminal result', len(chat_calls) >= 3 and len(remote) >= 3)
        check('both file actions ran directly', not card.do_button.isVisible() and all(
            (output/name).stat().st_size > 0 for name in ('report.txt', 'report.json')))
        check('file contents and hashes read back', json.loads((output/'report.json').read_bytes()) == report and
              all(hashlib.sha256((output/name).read_bytes()).hexdigest() in chat_calls[2]
                  for name in ('report.txt', 'report.json')))
        card._copy_full_reply()
        check('complete long answer is copyable', QApplication.clipboard().text() == long_reply)
        before_size = card.size()
        card._toggle_chat_size()
        check('expanded chat preserves controls', card.width() >= before_size.width()
              and card.input.isVisible() and card.send_button.isVisible())
        card.grab().save(str(output/'bunny-expanded.png'))
        card._toggle_chat_size()
        check('chat restores size', card.size() == before_size)
        expected = case['expected_texts']
        check('known boundaries were changed', task.counts()['applied'] >= len(chosen) and all(
            any(c.text == text for c in project.cues) for text in expected))
        revised = [(c.id, c.text, c.start_ms, c.end_ms) for c in project.cues]
        page.undo_stack.undo()
        check('undo restores source subtitles and task state', [(c.id, c.text, c.start_ms, c.end_ms)
              for c in project.cues] == original and project.studio_state.get('ai_sentence_refine') == initial_refine_state)
        page.undo_stack.redo()
        check('redo restores revised subtitles and task state', [(c.id, c.text, c.start_ms, c.end_ms)
              for c in project.cues] == revised and project.studio_state['ai_sentence_refine']['task_id'] == task_id)
        saved = []
        page.project_controller.save(on_finished=lambda path, error: saved.append((path, error)))
        wait(lambda: bool(saved))
        check('formal save verifies applied output', saved[0][1] is None and task.counts()['saved_verified'] >= len(chosen))
        reopened = load_project(saved[0][0])
        check('saved project reloads exact cue sequence', [(c.id, c.text, c.start_ms, c.end_ms)
              for c in reopened.cues] == revised)
        subtitle = _compile_format(reopened, 'srt')
        (output/'saved-project.srt').write_text(subtitle, 'utf-8')
        check('reopened project produces repaired subtitle export', all(
            text in subtitle for text in expected))
        (output/'task-counts.json').write_text(json.dumps(task.counts(), ensure_ascii=False, indent=2), 'utf-8')
        retry_via_chat = True
        remote_start = len(remote)
        card.input.setText('读取当前工程的断句问题和历史修复记录，处理仍能自动修复的范围，'
                           '等任务结束后整理完整报告，保存到已授权工作目录并读回，告诉我实际修改和剩余问题。')
        card.send()
        wait(lambda: not card.busy and page._refine_task is not task and page._refine_task.ended is not None)
        repeated = page._refine_task
        ids = {key for row in history for key in row['cue_ids']}
        retried_ids = {key for payload in remote[remote_start:] for cue in payload['cues']
                       for key in cue['source_cue_ids']}
        previous_verified = {cue_id for row in project.studio_state['ai_sentence_refine'].get('historical_windows', ())
                             if row['range_id'] in project.studio_state['ai_sentence_refine'].get('verified_history', {})
                             for cue_id in row['cue_ids']}
        blocked = {cue_id for row in repeated.rows.values() if row.get('stop_reason') == 'no_legal_boundary'
                   for cue_id in row['cue_ids']}
        (output/'chain-counts.json').write_text(json.dumps(
            dict(rounds=len(chain), missing=sorted(ids-retried_ids-previous_verified-blocked), task=repeated.counts()),
            ensure_ascii=False), 'utf-8')
        check('bunny dispatched and followed the targeted task', not card.do_button.isVisible()
              and len(chain) >= 5 and repeated.task_id in chain[2] and '实际应用' in chain[2]
              and ids <= retried_ids | previous_verified | blocked
              and repeated.counts()['applied'] >= 2 and repeated.counts()['saved_verified'] >= 2)
        check('long structured report reached disk and the same chat read it back',
              chain_file.stat().st_size > 5000 and json.loads(chain_file.read_bytes()) == long_report
              and '核验明细和实际应用报告.json' in chain[4] and '实际应用' in chain[4])
        card.reveal_all()
        card._copy_full_reply()
        check('all text from this multi-step answer is copyable', QApplication.clipboard().text() == long_reply)
        card._save_chat()
        check('same project restores entire long reply from history', card._restore_chat(card._project_key())
              and any(who == 'bunny' and text == long_reply for who, text in card.transcript))
        (output/'historical-task-counts.json').write_text(json.dumps(
            repeated.counts(), ensure_ascii=False, indent=2), 'utf-8')
    finally:
        if card is not None:
            card.close_chat()
        bunny_permissions.save(old_permission)
        ai_providers.provider_for_stage = old_provider
        bunny_chat.ai_readiness = old_readiness
        llm_config.text_ai_key_missing = old_key_check
