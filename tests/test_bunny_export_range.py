"""An export range with no picture is stopped before it is encoded, and 兔白 sees why (2026-11-22).

User report: someone could not export; the in point sat at the video's end, so the range had no
picture and the export sat in 「压制」. 兔白 only had the two raw times and kept thinking.
"""
from __future__ import annotations

import os
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def _project(cue_end_ms=5000, timeline_cues=True):
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    project = SubtitleProject(media=StudioMedia(path='video.mp4', duration_ms=2000),
                              cues=[StudioCue('a', 0, 1000, '一'), StudioCue('b', 1500, cue_end_ms, '二')])
    project.validate()
    if timeline_cues:
        project.render_settings['_cue_domain'] = 'timeline'
    return project


def _points(project, start, end):
    from twobyteasr.timeline.studio_edit_sequence import sequence_of
    sequence = sequence_of(project)
    sequence.in_point_ms, sequence.out_point_ms = start, end


def test_an_in_point_after_the_picture_cannot_be_exported():
    from twobyteasr.projects.project_range import NO_PICTURE, picture_end_ms, range_problem, validated_range
    from twobyteasr.timeline.studio_edit_sequence import timeline_duration_ms
    project = _project()
    assert timeline_duration_ms(project) == 5000 and picture_end_ms(project) == 2000
    _points(project, 2000, None)                      # subtitles run on, the video does not
    assert range_problem(project) == NO_PICTURE
    with pytest.raises(ValueError):
        validated_range(project)
    _points(project, 500, None)                       # starts inside the picture: fine
    assert range_problem(project) == '' and validated_range(project) == (500, 5000)
    _points(project, None, None)
    assert range_problem(project) == ''


def test_a_range_shorter_than_a_frame_cannot_be_exported():
    from twobyteasr.projects.project_range import MIN_RANGE_MS, TOO_SHORT, range_problem
    project = _project(cue_end_ms=1800, timeline_cues=False)
    _points(project, 2000 - 20, None)                 # I pressed a moment before the end
    assert range_problem(project) == TOO_SHORT
    _points(project, 2000 - MIN_RANGE_MS, None)
    assert range_problem(project) == ''


def test_the_new_messages_are_translated():
    import json
    from pathlib import Path
    from twobyteasr.projects.project_range import NO_PICTURE, TOO_SHORT
    folder = Path(__file__).resolve().parents[1] / 'twobyteasr' / 'locales'
    for language in ('zh-Hant', 'en', 'ja', 'ko', 'de', 'es', 'fr', 'it', 'pt', 'ru'):
        table = json.loads((folder / f'{language}.json').read_text(encoding='utf-8'))
        assert table.get(NO_PICTURE) and table.get(TOO_SHORT), language


def test_she_is_told_what_the_range_means():
    from twobyteasr.app.bunny_persona import format_state
    from twobyteasr.app.bunny_tools import range_check
    project = _project()
    _points(project, 2000, None)
    check = range_check(project)
    assert '不能导出' in check and '入点已经在影片画面结束之后' in check
    assert '影片画面到 0:02.0 为止' in check and '共 0:03.0' in check
    shown = format_state({'range_check': check})
    assert shown.startswith('- 导出范围检查：') and '影片画面到' in shown      # not cut at 160 characters
    _points(project, None, None)
    assert range_check(project) == '影片画面到 0:02.0 为止，后面到 0:05.0 只有字幕'
    assert range_check(_project(cue_end_ms=1800, timeline_cues=False)) == ''


def test_she_sees_what_the_export_window_is_doing(monkeypatch):
    from twobyteasr.app import bunny_tools
    project = _project(cue_end_ms=1800, timeline_cues=False)
    pages = {name: object() for name in ('setup', 'failure', 'success')}
    workspace = SimpleNamespace(pages=SimpleNamespace(currentWidget=lambda: pages['setup']),
                                setup_page=pages['setup'], failure_page=pages['failure'],
                                success_page=pages['success'], _running=False)
    page = SimpleNamespace(export_workspace=workspace, project=project)
    assert bunny_tools.export_state(SimpleNamespace(export_workspace=None)) == ''
    assert bunny_tools.export_state(page) == '开着，还没开始导出'
    _points(project, 1980, None)
    assert '「导出」按钮是灰的：导出范围不到一帧画面' in bunny_tools.export_state(page)
    now = time.monotonic()
    workspace._running = True
    workspace._progress_payload = {'stage': 'encode'}
    workspace._progress_target = 37
    workspace._started_at = now - 125
    workspace._work_progress = SimpleNamespace(last_update=now - 95)
    text = bunny_tools.export_state(page)
    assert text.startswith('正在导出：视频编码 37%') and '已用 2:05' in text and '没有新进度（像是卡住了）' in text
    workspace._work_progress.last_update = now
    assert '卡住' not in bunny_tools.export_state(page)
    workspace._running = False
    workspace._last_failure = '编码器出错\n\n细节'
    workspace.pages = SimpleNamespace(currentWidget=lambda: pages['failure'])
    assert bunny_tools.export_state(page) == '导出失败：编码器出错 细节'


def test_a_traditional_chinese_question_finds_the_entry():
    from twobyteasr.app import bunny_troubleshoot
    from twobyteasr.app.bunny_lore import select, to_hans
    assert to_hans('導出不了，卡在壓制') == '导出不了，卡在压制'
    assert to_hans('导出 export') == '导出 export'
    for question in ('一直說導出不了影片 卡在壓制的片段', '輸出影片是0秒', '导出来只有 0 秒'):
        keys = [entry.key for entry in select(question, bunny_troubleshoot.entries(), limit=3)]
        assert keys and keys[0] == 'trouble:export:range_empty', (question, keys)


def test_the_prompt_sends_her_to_the_range_first():
    from twobyteasr.app import bunny_persona
    rules = bunny_persona.RULES
    assert '导出卡在压制' in rules and '「导出范围检查」' in rules and 'clear_in_out' in rules
    assert '（页面、有没有打开工程、文字 AI 设好没有、界面语言、版本）' not in rules   # the old, too-short list
