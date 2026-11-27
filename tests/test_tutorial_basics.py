"""Basic chapters for people who never used an editor (2026-11-27).

User: people do not know how to add subtitles and tracks, what the red and grey on the timeline
mean, how to open the folded speakers and scroll down to them, how to apply a change to a range,
how AI makes and repairs subtitles, translation, sentence breaks and video editing. Four chapters
(看懂时间轴 / 选字幕与套用范围 / AI 生成与修复字幕 / 剪视频入门); the tutorial project gains two
minor speakers so the folded row shows; the wheel over the track names (or Shift+wheel) scrolls
the rows, which nothing did before.
"""
import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QStackedWidget

from twobyteasr.app import tutorial_chapters
from twobyteasr.app.home_tour import tutorial_steps

PARTS = {'timeline': '时间轴', 'select': '选范围', 'ai': 'AI 工具', 'cut': '剪视频'}


def _app():
    return QApplication.instance() or QApplication([])


def _window():
    return SimpleNamespace(pages=QStackedWidget() if _app() else None, built_page=lambda _name: None)


def _words(part):
    return ' '.join(f'{step.text() if callable(step.text) else step.text} '
                    f'{step.note() if callable(step.note) else step.note}' for step in tutorial_steps(_window(), part))


@pytest.mark.parametrize('part', list(PARTS))
def test_each_basic_chapter_is_its_own_part(part):
    steps = tutorial_steps(_window(), part)
    assert 5 <= len(steps) <= 16
    assert {step.chapter for step in steps} == {PARTS[part]}
    assert steps[-1].target is None and steps[-1].next_label == '完成'
    assert tutorial_chapters.is_chapter(part) and part in tutorial_chapters.CHAPTERS
    # Every step that waits for the person can also be done for them.
    for step in steps:
        if step.done is not None and not step.show_next:
            assert step.actions, step.text


def test_the_basics_sit_in_the_catalogue_where_a_beginner_needs_them():
    ids = [chapter.id for chapter in tutorial_chapters.CATALOG]
    assert ids[:3] == ['first', 'how', 'timeline']
    assert ids.index('select') > ids.index('studio') and ids.index('ai') > ids.index('select')
    assert all(tutorial_chapters.BY_ID[key].group == '基础' for key in ('timeline', 'select', 'ai'))
    assert tutorial_chapters.BY_ID['cut'].group == '进阶' and ids.index('cut') < ids.index('audio')


def test_the_timeline_chapter_explains_colours_folding_and_scrolling():
    words = _words('timeline')
    for needed in ('字幕轨', 'V1', 'A1', '说话人的颜色', '播放头', '红色', '灰色', '黄色', '需要检查', '左右移动',
                   'Ctrl', '轨道名字', '上下滑', 'Shift', '次要角色', '展开', '收起来', '往下滑', '隐藏', '锁定',
                   '新建轨道', '新建字幕轨', '加一条字幕', 'Enter'):
        assert needed in words, needed


def test_the_selection_ai_and_cut_chapters_cover_what_people_asked():
    select, ai, cut = _words('select'), _words('ai'), _words('cut')
    for needed in ('Ctrl', '拖一个框', 'Ctrl+A', '应用到', '已选', '说话人', '全片', '选中的字幕', '入点到出点'):
        assert needed in select, needed
    for needed in ('AI 生成字幕', '只重新识别这一段字幕', 'AI 校对', 'AI 清理', 'AI 优化', '智能修轴', '重新识别',
                   'AI 断句', '不改字', '翻译', '双语', 'API Key', 'Ctrl+Z'):
        assert needed in ai, needed
    for needed in ('V1', 'Ctrl+K', 'Delete', '波纹删除', '转场', '素材', '入点到出点'):
        assert needed in cut, needed


def test_every_basic_chapter_string_has_en_ja_and_traditional_chinese():
    catalogs = {lang: json.loads((Path('twobyteasr/locales') / f'{lang}.json').read_text('utf-8'))
                for lang in ('en', 'ja', 'zh-Hant')}
    missing = []
    for part in PARTS:
        for step in tutorial_steps(_window(), part):
            for text in [step.text, step.note, step.next_label] + [action.label for action in step.actions]:
                if isinstance(text, str) and text:
                    missing += [(lang, text) for lang, table in catalogs.items() if text not in table]
    for key in PARTS:
        chapter = tutorial_chapters.BY_ID[key]
        for text in (chapter.title, *chapter.learn):
            missing += [(lang, text) for lang, table in catalogs.items() if text not in table]
    assert not missing


def test_the_tutorial_project_folds_its_two_minor_speakers():
    from twobyteasr.app.sample_project import ensure_tutorial_project
    from twobyteasr.projects.studio_project import load_project
    from twobyteasr.recognition.speaker_roles import group_members
    project = load_project(ensure_tutorial_project())
    names = {speaker.id: speaker.name for speaker in project.speakers}
    assert names == {'S00': '主播', 'S01': '嘉宾', 'S02': '小精灵', 'S03': '路人'}
    assert set(group_members(project)) == {'S02', 'S03'}
    assert [cue.id for cue in project.cues[:2]] == ['tutorial-1', 'tutorial-2']   # older chapters keep their lines


@pytest.fixture
def crowded():
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
    from twobyteasr.studio.studio_timeline import WaveformTimeline
    _app()
    widget = WaveformTimeline()
    widget.resize(1000, 230)
    speakers = [StudioSpeaker(f'S0{index}', name=f'说话人{index}') for index in range(6)]
    cues = [StudioCue(f'c{index}', index * 2000, index * 2000 + 1500, '一句', speaker_id=f'S0{index}')
            for index in range(6)]
    widget.set_project(SubtitleProject(media=StudioMedia(path='missing.mp4', duration_ms=60_000), cues=cues,
                                       speakers=speakers))
    widget.set_visible_window(0, 20_000)
    yield widget
    widget.close()
    widget.deleteLater()


def _wheel(widget, x, delta, modifiers=Qt.NoModifier):
    point = QPointF(x, 120)
    event = QWheelEvent(point, point, QPoint(0, 0), QPoint(0, delta), Qt.NoButton, modifiers,
                        Qt.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)
    return event


def test_the_wheel_over_track_names_or_with_shift_scrolls_the_rows(crowded):
    bar = crowded.vertical_scrollbar
    assert bar.maximum() > bar.minimum()            # six rows do not fit
    bar.setValue(bar.maximum())
    start, bottom = crowded.visible_start_ms, bar.value()
    assert _wheel(crowded, 100, 120).isAccepted()   # over the track names: rows go up, time stays
    assert bar.value() < bottom and crowded.visible_start_ms == start
    before = bar.value()
    _wheel(crowded, 100, -120)
    assert bar.value() > before
    before = bar.value()
    _wheel(crowded, 600, 120, Qt.ShiftModifier)     # Shift+wheel over the time area: rows too
    assert bar.value() < before and crowded.visible_start_ms == start
    crowded.set_visible_window(4_000, 4_000)
    before, start = bar.value(), crowded.visible_start_ms
    _wheel(crowded, 600, 120)                        # plain wheel over the time area: time, as before
    assert bar.value() == before and crowded.visible_start_ms < start
    duration = crowded.visible_duration_ms
    _wheel(crowded, 100, 120, Qt.ControlModifier)    # Ctrl still zooms, even over the names
    assert crowded.visible_duration_ms < duration and bar.value() == before
