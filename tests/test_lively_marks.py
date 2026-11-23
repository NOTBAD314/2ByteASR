"""Caption Markdown grows ~~strike~~ / --strike-- and # headings; AI 生动标记 adds marks, never words (2026-11-20)."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.caption_style.text_marks import heading_scale, markdown_text, parse_markdown
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.studio import lively_marks


def _project(*texts):
    value = SubtitleProject(media=StudioMedia('', duration_ms=1000 * len(texts)), speakers=[StudioSpeaker('S01', '玩家')],
                            cues=[StudioCue(f'c{i}', i * 1000, i * 1000 + 900, text, speaker_id='S01')
                                  for i, text in enumerate(texts)])
    value.validate()
    return value


def test_strike_and_headings_parse_and_round_trip():
    text, marks, _ = parse_markdown('# 第一章\n这个 ~~不对~~ 那个 --也划掉-- 吧')
    assert text == '第一章\n这个 不对 那个 也划掉 吧'
    assert {'start': 0, 'end': 3, 'heading': 1} in marks
    assert [m for m in marks if m.get('strike')] == [{'start': 7, 'end': 9, 'strike': True},
                                                     {'start': 13, 'end': 16, 'strike': True}]
    shown = markdown_text(text, marks)
    assert shown == '# 第一章\n这个 ~~不对~~ 那个 ~~也划掉~~ 吧'
    assert parse_markdown(shown)[:2] == (text, marks)
    for level in range(1, 7):
        assert parse_markdown('#' * level + ' 标题 **粗**')[1][-1] == {'start': 0, 'end': 4, 'heading': level}
    assert [heading_scale({'heading': n}) for n in range(1, 7)] == sorted(
        (heading_scale({'heading': n}) for n in range(1, 7)), reverse=True)


def test_literal_hashes_dashes_and_tildes_stay_text():
    for plain in ('#不是标题', '####### 七个', 'a--b', '2--3--4', 'x ~~ y', '# 字面', '~~x~~'):
        if plain in ('#不是标题', '####### 七个', 'a--b', 'x ~~ y'):
            assert parse_markdown(plain)[:2] == (plain, [])
        assert parse_markdown(markdown_text(plain, []))[:2] == (plain, [])


def test_rendered_strike_and_heading_reach_glyphs_and_ass():
    QApplication.instance() or QApplication([])
    from types import SimpleNamespace
    from PySide6.QtGui import QFont
    from twobyteasr.rendering.marked_glyphs import marked_ass_text, shape_marked_text
    text, marks, _ = parse_markdown('# Big\nab ~~cut~~ end')
    font = QFont('Arial')
    font.setPixelSize(40)
    _plain, plain_pieces = shape_marked_text(text, font, [{'start': 0, 'end': 1, 'bold': False}], 0.0, 60)
    _marked, pieces = shape_marked_text(text, font, marks, 0.0, 60)
    first = lambda items: next(path for path, index, _color in items if index == 0).boundingRect().height()
    assert first(pieces) > first(plain_pieces) * 1.4                      # heading 1 is drawn 1.6 x
    from twobyteasr.rendering.marked_glyphs import STRIKE_COLOR
    bars = [path for path, index, color in pieces if color == STRIKE_COLOR]
    assert len(bars) == 3 and {index for path, index, color in pieces if color == STRIKE_COLOR} == {7, 8, 9}  # 'Big\nab cut end'
    style = SimpleNamespace(font_weight=400, bold=False, italic=False, primary_color='#FFFFFF', font_size=50)
    ass = marked_ass_text(text, marks, style)
    assert '\\b700\\i0\\fs80\\s0' in ass        # heading 1: bold, 1.6 x size
    assert '\\fs50\\s1' in ass and ass.count('\\s1') == 1


def test_word_timed_ass_keeps_strike_and_resets_after_it():
    QApplication.instance() or QApplication([])
    from types import SimpleNamespace
    from twobyteasr.caption_style.word_animation import compile_word_ass
    text, marks, _ = parse_markdown('甲~~乙丙~~丁')
    style = SimpleNamespace(font_weight=400, bold=False, italic=False, primary_color='#FFFFFF', font_size=50)
    plan = {'mode': 'word_reveal', 'color': '#FFD166', 'text': text, 'duration_ms': 400,
            'spans': [dict(char_start=i, char_end=i + 1, start_ms=i * 100, end_ms=i * 100 + 100, spoken=char)
                      for i, char in enumerate(text)]}
    ass = compile_word_ass(plan, text, '#FFFFFF', marks=marks, style=style)
    assert ass.count('\\s1') == 2 and ass.count('\\s0') == 2     # 乙丙 struck; 甲 and 丁 reset


class _Provider:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def complete(self, messages, **kwargs):
        sent = json.loads(messages[-1]['content'])['cues']
        self.calls.append(sent)
        return json.dumps({'cues': [{'cue_id': row['cue_id'], 'markdown': self.answer(row['text'])}
                                    for row in sent]}, ensure_ascii=False)


def test_ai_marks_never_change_words_and_skip_the_users_own_marks():
    QApplication.instance() or QApplication([])
    project = _project('今天终于打过了最后一关', '我才没有害怕', '一共3--4个', '這個遊戲太難了', '')
    project.cues[1].appearance_override = {'text_marks': [{'start': 0, 'end': 1, 'bold': True}]}
    rows, kept = lively_marks.candidates(project, [cue.id for cue in project.cues])
    assert [row[0] for row in rows] == ['c0', 'c2', 'c3'] and kept == 1

    def answer(text):
        if text.startswith('今天'):
            return '# 今天终于打过了==最后一关=='
        if text.startswith('一共'):
            return text                                 # escaped dashes come back as plain text
        return '这个游戏**太难了**'                      # 简体 answer for a 繁體 caption
    provider = _Provider(answer)
    result = lively_marks.request_lively_marks(rows, provider=provider)
    assert provider.calls[0][1]['text'] == '一共3\\-\\-4个'
    assert result['c0'] == [{'start': 7, 'end': 11, 'highlight': True}, {'start': 0, 'end': 11, 'heading': 1}]
    assert result['c3'] == [{'start': 4, 'end': 7, 'bold': True}]
    assert 'c2' not in result and result.rejected == 0 and not result.error

    changed = lively_marks.request_lively_marks([('c0', '今天终于打过了最后一关')],
                                                provider=_Provider(lambda text: '今天**终于**过关了'))
    assert dict(changed) == {} and changed.rejected == 1


def test_each_batch_names_its_own_count_and_limit():
    QApplication.instance() or QApplication([])

    class Recording(_Provider):
        def complete(self, messages, **kwargs):
            self.system = messages[0]['content']
            return super().complete(messages, **kwargs)
    rows = [(f'c{i}', f'第{i}句') for i in range(10)]
    provider = Recording(lambda text: text)
    lively_marks.request_lively_marks(rows, provider=provider)
    assert '这一批共 10 条，最多给 4 条加标记' in provider.system
    lively_marks.request_lively_marks(rows, provider=provider, density='lively')
    assert '最多给 6 条加标记' in provider.system
    assert lively_marks.batch_limit(1, 'light') == 1


def test_captions_drawn_by_an_ai_web_theme_are_reported():
    QApplication.instance() or QApplication([])
    project = _project('甲', '乙', '丙')
    project.style_recipes['theme-a'] = {'webTheme': {'html': '<div>{{text}}</div>'}}
    project.cues[1].style_id = 'theme-a-cue-1'
    project.cues[2].style_id = 'theme-a'
    assert lively_marks.web_theme_cue_ids(project, ['c0', 'c1', 'c2']) == ['c1', 'c2']


def test_overflowing_batches_are_halved():
    QApplication.instance() or QApplication([])

    class Truncating(_Provider):
        def complete(self, messages, **kwargs):
            if len(json.loads(messages[-1]['content'])['cues']) > 2:
                error = RuntimeError('truncated')
                error.category = 'structured_output_truncated'
                raise error
            return super().complete(messages, **kwargs)
    rows = [(f'c{i}', f'第{i}句') for i in range(5)]
    result = lively_marks.request_lively_marks(rows, provider=Truncating(lambda text: f'**{text}**'))
    assert sorted(result) == [f'c{i}' for i in range(5)] and not result.error


def test_applying_is_one_undo_step_and_respects_edits_made_meanwhile():
    QApplication.instance() or QApplication([])
    from PySide6.QtGui import QUndoStack
    from twobyteasr.timeline.studio_commands import SetCuesAppearanceCommand
    project = _project('第一句', '第二句', '第三句')
    sent = {cue.id: cue.text for cue in project.cues}
    result = {'c0': [{'start': 0, 'end': 3, 'heading': 2}], 'c1': [{'start': 1, 'end': 2, 'strike': True}],
              'c2': [{'start': 0, 'end': 1, 'bold': True}]}
    project.cues[2].text = '第三句改了'                    # edited while the request ran
    overrides = lively_marks.overrides_for(project, result, sent)
    assert sorted(overrides) == ['c0', 'c1']
    stack = QUndoStack()
    stack.push(SetCuesAppearanceCommand(project, overrides, 'AI 生动标记'))
    assert project.cues[0].appearance_override['text_marks'] == result['c0']
    assert project.cues[1].appearance_override['text_marks'] == result['c1']
    assert stack.count() == 1
    stack.undo()
    assert all(not cue.appearance_override.get('text_marks') for cue in project.cues)
