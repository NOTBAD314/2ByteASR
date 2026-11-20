"""兔白 reads a recognition's raw JSON and names the step that went wrong (2026-11-18)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from twobyteasr.app import bunny_report


def _payload(*, heard=('zh', 'zh'), rows=None, control='automatic_only', speech=None, cues=None, gaps=(),
             polish=None, owner='API native sentence timestamps', basis=None, provider='mosi_moss_pro'):
    speech = speech if speech is not None else [[i * 10.0, i * 10.0 + 6.0] for i in range(60)]
    cues = cues if cues is not None else [[s, e] for s, e in speech]
    requests = []
    for index, language in enumerate(heard):
        requests.append({'event': 'asr_language_request', 'request_index': index, 'start': index * 300.0,
                         'end': (index + 1) * 300.0, 'requested_language': 'zh', 'language_control': control,
                         'raw_result_path': r'C:\Users\someone\AppData\Local\2ByteASR\cache\x\result.json',
                         'transcript': {'language': language, 'characters': 900}})
    events = [{'event': 'asr_language_control', 'language_control': control},
              {'event': 'audio_stream_selected', 'label': '音轨 2｜Microphone', 'offset_ms': 0.0, 'lead_ms': 0.0},
              *requests,
              {'event': 'display_boundary_phase', 'phase': 'final_half_open_display',
               'cues': [{'id': n, 'start_ms': round(s * 1000), 'end_ms': round(e * 1000), 'text': '秘密的字幕'}
                        for n, (s, e) in enumerate(cues)]},
              {'event': 'grouping_timing_evidence', 'boundary_basis_counts': basis or {'firered_word': 90, 'estimate': 2}}]
    for index, texts in (rows or {}).items():
        events.append({'event': 'asr_shard_ready', 'request_index': index,
                       'rows': [{'start': 1.0, 'end': 2.0, 'text': text} for text in texts]})
    return {
        'journal_version': 1, 'status': 'completed',
        'media': {'name': 'Game 2026.mp4', 'path': r'E:\videos\Game 2026.mp4'},
        'settings': {'subtitle_language': {'requested_language': 'zh'},
                     'models': {'primary_asr_backend': 'api', 'qwen_asr_api_provider': provider,
                                'qwen_asr_api_model': 'moss-transcribe-diarize-pro', 'firered_asr_backend': 'local',
                                'polish_model': 'deepseek-v4-flash', 'polish_api_key': 'sk-secret123456'}},
        'stages': [],
        'result': {'cue_count': len(cues), 'cache_owners': {'final_timing': owner},
                   'speech_coverage': {'duration': 600.0, 'speech_ranges': speech, 'gaps': list(gaps)},
                   'review_classification': {'TIMING_LOW_CONFIDENCE': 0}},
        'review_items': [],
        'polishing_summary': polish if polish is not None else {'success_cues': 100, 'fallback_cues': 0},
        'events': events,
        'task': {'last_error': ''},
    }


def _finding(analysis, step, words):
    return next((item for item in analysis.findings if item.step == step and words in item.title), None)


def test_moss_pro_hearing_the_wrong_language_is_named_with_the_fix():
    analysis = bunny_report.analyze(_payload(heard=('zh', 'ja')))
    found = _finding(analysis, '主力转写', '语言听错')
    assert found is not None and found.level == 'problem' and found.sure == '确定'
    assert '第 2 段' in found.detail and '日语' in found.detail
    advice = ' '.join(found.advice)
    assert '不能指定语言' in advice and '「主力转写」换一个' in advice and '只重新识别这一段字幕' in advice
    assert analysis.problems()[0] is found                                   # the most serious comes first
    # A service that is told the language: the advice is to choose the right one.
    told = bunny_report.analyze(_payload(heard=('ja',), control='request_parameter', provider='bailian'))
    assert '视频里说的话' in ' '.join(_finding(told, '主力转写', '语言听错').advice)


def test_text_in_the_wrong_script_counts_even_when_the_service_says_chinese():
    rows = {0: ['これはテストです', 'ゲームの話をしましょう', 'わかりました']}
    analysis = bunny_report.analyze(_payload(heard=('zh',), rows=rows))
    found = _finding(analysis, '主力转写', '语言听错')
    assert found is not None and '日语' in found.detail
    fine = bunny_report.analyze(_payload(heard=('zh',), rows={0: ['今天打BOSS', '这个OK']}))
    assert _finding(fine, '主力转写', '语言没有听错') is not None


def test_a_whole_film_offset_is_measured_against_the_detected_speech():
    speech = [[i * 10.0, i * 10.0 + 6.0] for i in range(60)]
    late = [[s + 1.0, e + 1.0] for s, e in speech]
    analysis = bunny_report.analyze(_payload(speech=speech, cues=late))
    found = _finding(analysis, '字幕时间轴', '晚了')
    assert found is not None and found.level == 'problem' and '1.0 秒' in found.title
    assert 'Alt+←' in found.advice[0] and '10 次' in found.advice[0]
    early = bunny_report.analyze(_payload(speech=speech, cues=[[s - 0.6, e - 0.6] for s, e in speech]))
    assert 'Alt+→' in _finding(early, '字幕时间轴', '早了').advice[0]
    aligned = bunny_report.analyze(_payload(speech=speech, cues=speech))
    assert _finding(aligned, '字幕时间轴', '没有整体提前或延后') is not None


def test_estimated_timing_points_to_the_aligner_and_smart_align():
    analysis = bunny_report.analyze(_payload(basis={'firered_word': 50, 'estimate': 20, 'source_segment': 30}))
    found = _finding(analysis, '字幕时间轴', '估出来')
    assert found is not None and '20 个是估算的' in found.detail and '整句时间' in found.detail
    assert 'Qwen3 对齐 · Ultra' in found.advice[0] and '智能修轴' in found.advice[1]


def test_speech_without_subtitles_and_failed_proofreading_are_problems():
    gaps = [{'start': i * 10.0, 'end': i * 10.0 + 3.0} for i in range(30)]
    analysis = bunny_report.analyze(_payload(gaps=gaps, polish={'success_cues': 80, 'fallback_cues': 20,
                                                                 'failure_categories': {'rate_limited': 20}}))
    gap = _finding(analysis, '主力转写', '没有字幕')
    assert gap.level == 'problem' and '30 处' in gap.detail and '25%' in gap.detail
    polish = _finding(analysis, 'AI 校对', '没有校对成')
    assert polish.level == 'problem' and 'rate_limited' in polish.detail and '重试' in polish.advice[0]


def test_the_summary_keeps_no_paths_keys_or_subtitle_text():
    payload = _payload(heard=('zh', 'ja'))
    payload['task']['last_error'] = r'C:\users\private\secret.wav sk-secret'
    payload['events'][1]['label'] = 'Mic confidential-label'
    text = bunny_report.analyze(payload).text()
    assert 'E:\\' not in text and 'C:\\' not in text and 'someone' not in text
    assert 'sk-secret' not in text and '秘密的字幕' not in text
    assert 'Game 2026.mp4' not in text and 'confidential-label' not in text
    assert '【有问题】' in text and len(text) <= 3600


def test_an_attached_task_does_not_follow_local_report_references(tmp_path, monkeypatch):
    from twobyteasr.recognition import task_journal
    def read_local(_path):
        pytest.fail('An attached task tried to load another file')
    monkeypatch.setattr(task_journal, 'report_payload', read_local)
    path = tmp_path / 'task.json'
    payload = _payload(heard=('zh', 'ja'))
    payload['task']['reports'] = [str(tmp_path / 'unrelated.json')]
    path.write_text(json.dumps(payload), encoding='utf-8')
    assert '语言听错' in bunny_report.analyze_file(path)
    payload['result']['cue_count'] = 'broken'
    assert '部分字段无法读取' in bunny_report.summarize(payload)


def test_the_users_own_file_is_analysed_in_full(tmp_path):
    path = tmp_path / 'run.json'
    path.write_text(json.dumps(_payload(heard=('zh', 'ja')), ensure_ascii=False), encoding='utf-8')
    assert '语言听错' in bunny_report.analyze_file(path)
    other = tmp_path / 'other.json'
    other.write_text('{"hello": 1}', encoding='utf-8')
    assert '不是识别任务的记录' in bunny_report.analyze_file(other)
    assert '读不出来' in bunny_report.analyze_file(tmp_path / 'missing.json')


def test_she_picks_the_open_projects_recognition_then_the_newest(monkeypatch, tmp_path):
    from twobyteasr.recognition import task_journal
    from twobyteasr.app import bunny_lookup, bunny_nav_tools
    monkeypatch.setattr(task_journal, 'task_root', lambda: tmp_path)
    (tmp_path / 'abc123').mkdir()
    (tmp_path / 'abc123' / 'task.json').write_text('{}', encoding='utf-8')
    newest = tmp_path / 'newest.json'
    monkeypatch.setattr(bunny_lookup, 'newest_report', lambda roots=None: newest)
    assert bunny_report.task_path('abc123') == (tmp_path / 'abc123' / 'task.json', '现在打开的工程是这次识别做出来的')
    assert bunny_report.task_path('nothere') == (newest, '最近一次识别')
    assert bunny_report.task_path('../etc')[0] == newest                     # never a path out of the folder
    monkeypatch.setattr(bunny_nav_tools, 'result_records', lambda limit=30, roots=None: [(tmp_path / 'one.json', None)])
    assert bunny_report.task_path('', 1) == (tmp_path / 'one.json', '识别记录第 1 条')
    assert bunny_report.task_path('', 5)[0] is None
    window = SimpleNamespace(built_page=lambda name: SimpleNamespace(project=SimpleNamespace(
        generation_metadata={'job_id': 'abc123'})) if name == 'studio' else None)
    assert bunny_report.project_job_id(window) == 'abc123'
    assert bunny_report.project_job_id(SimpleNamespace()) == ''


def test_the_tool_is_a_background_read_under_the_diagnostics_switch(monkeypatch, tmp_path):
    from twobyteasr.app import bunny_permissions
    from twobyteasr.app.bunny_tools import TOOLS, ToolError
    tool = TOOLS['analyze_recognition']
    assert tool.background and not (tool.acts or tool.edit or tool.paid)
    assert 'analyze_recognition' in bunny_permissions.DIAGNOSTIC_READS
    path = tmp_path / 'run.json'
    path.write_text(json.dumps(_payload(heard=('zh', 'ja')), ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(bunny_report, 'task_path', lambda job='', number=0: (path, '最近一次识别'))
    said = tool.run({}, {})
    assert said.startswith('（分析的是：最近一次识别）') and '语言听错' in said
    monkeypatch.setattr(bunny_report, 'task_path', lambda job='', number=0: (None, '这台电脑上还没有识别记录'))
    with pytest.raises(ToolError):
        tool.run({}, {})


@pytest.mark.parametrize('question', ['字幕错位了', '字幕和声音对不上', '识别出来全是日文', '为什么漏了好多字幕',
                                      '错字特别多', '识别又失败了'])
def test_recognition_trouble_is_analysed_before_she_answers(question):
    from twobyteasr.app import bunny_persona
    assert bunny_persona.auto_lookup(question) == 'analyze_recognition'


def test_a_dropped_recognition_json_becomes_its_analysis(tmp_path):
    from types import MethodType
    from twobyteasr.app.bunny_chat import BunnyChat
    fake = SimpleNamespace(ready=True)
    read = MethodType(BunnyChat._recognition_json, fake)
    path = tmp_path / 'Game 2026.json'
    path.write_text(json.dumps(_payload(heard=('zh', 'ja')), ensure_ascii=False), encoding='utf-8')
    text = read(str(path))
    assert text.startswith('（这是小兔纸拖进来的识别原始 JSON') and '语言听错' in text
    other = tmp_path / 'notes.json'
    other.write_text('{"a": 1}', encoding='utf-8')
    assert read(str(other)) == '' and read(str(tmp_path / 'notes.txt')) == ''
