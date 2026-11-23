from twobyteasr.app.bunny_memory import load_chat, save_chat
from twobyteasr.app.bunny_persona import build_messages


def test_quoted_tool_report_survives_masked_number(tmp_path, monkeypatch):
    monkeypatch.setattr('twobyteasr.app.bunny_memory.store_path', lambda: tmp_path/'memory.json')
    task = 'a123456789abcdefa123456789abcdef'
    save_chat('project', [('user', '报告工作台结果'),
        ('bunny', f'任务{task}已保存两条，数字「12345678901234」仍待核对。'),
        ('user', '密码 secret_value')], verified_ids=[task])
    output = load_chat('project')
    assert output == [('user', '报告工作台结果'),
        ('bunny', f'任务{task}已保存两条，数字「【已隐去】」仍待核对。')]


def test_explicit_studio_file_task_uses_compact_tools_and_state():
    messages = build_messages('请写出并读回审核报告',
        features=[('extra', '完整功能表', '位置测试')], core='完整手册标记',
        state={'page': '字幕工作台', 'project_open': True})
    assert 'review_issues' in messages[0]['content'] and 'write_file' in messages[0]['content']
    assert '完整手册标记' not in messages[-1]['content']
    assert '完整功能表' not in messages[0]['content']
