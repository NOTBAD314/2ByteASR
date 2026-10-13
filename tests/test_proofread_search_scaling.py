"""Search/replace layout stays exact as the proofreading document grows."""
from __future__ import annotations

import copy
import os
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from twobyteasr.glossary_proofread import CaptionReviewList, TermIndex, line_units, wrap_units

APP = QApplication.instance() or QApplication([])


def issue(text, original, replacement):
    start = text.index(original)
    return dict(kind='term', span=(start, start + len(original)), original=original, replacement=replacement,
                checked=False, default=True, reason='', hit=None, options=(), evidence='', stale=False, reviewed=False)


def row(cue_id, text, issues=()):
    return dict(cue_id=cue_id, number='#1', time='0:00', start_ms=0, end_ms=2000,
                base=text, origin=text, speaker=('S01', '#638d85'), issues=list(issues),
                applied=False, remembered=None)


def uncached_layout(widget, item):
    return wrap_units(line_units(item['base'], widget._marks(item)), widget._text_width(),
                      widget.body_metrics, widget.below_metrics, widget.MARK_PAD)


def test_plain_units_keep_unicode_newlines_spaces_and_partial_ascii_words():
    text = '甲ABC__123  中😀\n中文  é2_3 末'
    assert [unit['top'] for unit in line_units(text, [])] == [
        '甲', 'ABC__123  ', '中', '😀', '\n', '中', '文', ' ', ' ', 'é', '2_3 ', '末']
    # A search hit can start/end inside a Latin word; the boundaries, spaces,
    # and caret indices are still those of the exact original text.
    mark = dict(start=3, end=6, below='replacement', style='find', ref=3)
    units = line_units(text, [mark])
    assert [unit['top'] for unit in units[:4]] == ['甲', 'AB', 'C__', '123  ']
    assert ''.join(unit['top'] for unit in units) == text
    assert all(unit['top'] == text[unit['start']:unit['end']] for unit in units)


@pytest.mark.parametrize('text, expected', [
    ('', []), ('   ', [' ', ' ', ' ']),
    ('a_b2   Z9', ['a_b2   ', 'Z9']),
    ('A \tB\r\nC', ['A ', '\t', 'B', '\r', '\n', 'C']),
    ('中A1，B2。', ['中', 'A1', '，', 'B2', '。']),
    ('éÉ１２abc', ['é', 'É', '１', '２', 'abc']),
    ('👨\u200d👩\u200d👧\u200d👦e\u0301', ['👨', '\u200d', '👩', '\u200d', '👧', '\u200d', '👦', 'e', '\u0301']),
    ('x\u00a0y\u3000z', ['x', '\u00a0', 'y', '\u3000', 'z']),
])
def test_plain_units_preserve_all_character_boundaries(text, expected):
    assert [unit['top'] for unit in line_units(text, [])] == expected
    for start in range(len(text) + 1):
        for end in (start, min(start + 1, len(text)), len(text)):
            mark = dict(start=start, end=end, below='', style='find_delete', ref=start)
            units = line_units(text, [mark])
            assert ''.join(unit['top'] for unit in units) == text
            assert [(unit['start'], unit['end']) for unit in units if unit['mark'] is mark] == [(start, end)]
            assert all(unit['top'] == text[unit['start']:unit['end']] for unit in units)


def test_non_equal_replacement_and_exclusion_keep_exact_wrapping_and_character_offsets():
    widget = CaptionReviewList()
    text = '古龙来了，古龙和 CHICHOO 继续向前，这是一句需要完整显示的长字幕。' * 3
    items = [row(f'cue-{i}', text) for i in range(120)]
    try:
        widget.resize(560, 600)
        widget.set_rows(items)
        for replacement in ('骨龙', 'CHICHOO', '新的完整技能名字', ''):
            widget.find = dict(needle='古龙', replace=replacement, excluded=frozenset({('cue-47', 0)}))
            widget._layout_rows()
            for item in (items[0], items[47], items[-1]):
                layout = widget._row_layout(item)
                expected = uncached_layout(widget, item)
                assert layout['lines'] == expected
                assert ''.join(unit['top'] for line in layout['lines'] for unit in line) == text
                assert all(unit['top'] == text[unit['start']:unit['end']]
                           for line in layout['lines'] for unit in line)
            assert widget._marks(items[47])[0]['below'] == '不替换'
            assert widget.offsets[-1] == sum(widget.heights)
            assert len(widget.offsets) == len(items) + 1
        widget.find = dict(needle='', replace=None, excluded=frozenset())
        widget._layout_rows()
        assert widget._row_layout(items[47])['lines'] == uncached_layout(widget, items[47])
    finally:
        widget.deleteLater()


def test_whole_term_groups_survive_search_replacement_and_font_width_changes():
    widget = CaptionReviewList()
    text = '看看疫病吐息和魔草巫灵，在这里使用疫病吐息。'
    item = row('cue', text, (issue(text, '疫病', '一命'), issue(text, '吐息', '突袭'), issue(text, '巫', '乌')))
    try:
        widget.terms = TermIndex((('疫病吐息', '技能'), ('魔草乌灵', '精灵')))
        widget.resize(720, 550)
        widget.set_rows([item])
        groups = copy.deepcopy(widget.groups(item))
        assert any(group['parts'] == [0, 1] and group['name'] == '疫病吐息' for group in groups)
        for font_size in (15, 24):
            font = QFont(widget.font())
            font.setPixelSize(font_size)
            widget.setFont(font)
            for width in (420, 810):
                widget.resize(width, 550)
                for needle, replacement in (('疫病', '这个技能'), ('魔草', 'Moss'), ('', None)):
                    widget.find = dict(needle=needle, replace=replacement, excluded=frozenset())
                    widget._layout_rows()
                    assert widget.groups(item) == groups
                    assert widget._row_layout(item)['lines'] == uncached_layout(widget, item)
                    assert widget.heights[0] == widget._row_height(item)
    finally:
        widget.deleteLater()


def test_layout_after_text_and_issue_edit_matches_fresh_widget():
    widget, fresh = CaptionReviewList(), CaptionReviewList()
    text = '这里的古龙和球球都来了。'
    item = row('cue', text, (issue(text, '古龙', '骨龙'), issue(text, '球球', 'CHICHOO')))
    try:
        for target in (widget, fresh):
            target.resize(540, 500)
            target.find = dict(needle='球球', replace='CHICHOO', excluded=frozenset())
        widget.set_rows([item])
        # A local checker can replace an issue while the text stays unchanged.
        item['issues'][0]['replacement'] = '新的名字'
        widget.refresh_row('cue')
        fresh.set_rows([copy.deepcopy(item)])
        assert widget._row_layout(item) == fresh._row_layout(fresh.rows[0])
        assert widget.heights == fresh.heights
    finally:
        widget.deleteLater()
        fresh.deleteLater()


def test_save_worker_keeps_one_revision_during_edit_undo_and_resave(tmp_path, monkeypatch):
    """Real writer pauses after capturing cues; live undo must not change its receipts."""
    import dataclasses
    import json
    import threading
    from PySide6.QtGui import QUndoStack
    from twobyteasr.glossary_proofread import _SaveThread
    from twobyteasr.studio_commands import BatchReplaceTextCommand
    from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle, project_backup_path

    project = SubtitleProject(media=StudioMedia(path='', duration_ms=6000),
                              styles=[SubtitleStyle('default', 'fixture')],
                              cues=[StudioCue('a', 0, 2000, '古龙来了'), StudioCue('b', 3000, 5000, '继续比赛')])
    project.validate()
    stack = QUndoStack()
    stack.push(BatchReplaceTextCommand(project, {'a': '骨龙来了'}, glossary_ids=[],
                                     review_receipt={'source': 'user_confirmed', 'operation': 'first'}))
    target = tmp_path / 'captions.2byteproj'
    worker = _SaveThread(project, target)
    captured, release = threading.Event(), threading.Event()
    original = dataclasses._asdict_inner
    worker_cues = worker.project.cues
    main_thread = threading.get_ident()
    held = False

    def pause_after_cues(value, factory):
        nonlocal held
        result = original(value, factory)
        if not held and value is worker_cues and threading.get_ident() != main_thread:
            held = True
            captured.set()
            if not release.wait(5):
                raise RuntimeError('save checkpoint timed out')
        return result

    monkeypatch.setattr(dataclasses, '_asdict_inner', pause_after_cues)
    worker.start()
    try:
        assert captured.wait(5)
        stack.push(BatchReplaceTextCommand(project, {'a': '远古巨龙来了'}, glossary_ids=[],
                                         review_receipt={'source': 'user_confirmed', 'operation': 'second'}))
        stack.undo()
        stack.undo()
        assert project.cues[0].text == '古龙来了'
    finally:
        release.set()
        assert worker.wait(5000)
    first = json.loads(target.read_text('utf8'))
    assert first['cues'][0]['text'] == '骨龙来了'
    assert first['studio_state']['manual_caption_text'] == {'a': '骨龙来了'}
    assert first['generation_metadata']['glossary_review_jobs'][-1]['applied_texts'] == {'a': '骨龙来了'}
    newest = _SaveThread(project, target)
    newest.start()
    assert newest.wait(5000)
    latest = json.loads(target.read_text('utf8'))
    assert latest['cues'][0]['text'] == '古龙来了'
    assert not latest['generation_metadata'].get('glossary_review_jobs')
    assert json.loads(project_backup_path(target).read_text('utf8')) == first
    worker.deleteLater()
    newest.deleteLater()


def test_failed_snapshot_keeps_page_edits_for_retry(tmp_path, monkeypatch):
    """Snapshot errors follow the same keep-edits/retry path as disk errors."""
    from PySide6.QtWidgets import QWidget
    from twobyteasr import glossary_proofread as module
    page = module.GlossaryProofreadPage.__new__(module.GlossaryProofreadPage)
    QWidget.__init__(page)
    project = object()
    page._project_path = str(tmp_path / 'captions.2byteproj')
    page._save_thread = None
    page._save_again = False
    page._save_error = ''
    page._live_project = lambda: (project, None)
    messages = []
    page._set_status = messages.append

    def fail(*_args):
        raise RuntimeError('snapshot unavailable')

    monkeypatch.setattr(module, '_SaveThread', fail)
    page._save_now()
    assert page._save_thread is None
    assert page._save_error == 'snapshot unavailable'
    assert messages and 'snapshot unavailable' in messages[-1]
    # The owning document has not been replaced or cleared.
    assert page._live_project()[0] is project
    page.deleteLater()


@pytest.mark.parametrize('unsupported', [False, True])
def test_save_snapshot_copies_json_values_and_falls_back_for_unknown_types(tmp_path, unsupported):
    from collections import OrderedDict
    from twobyteasr.glossary_proofread import _SaveThread
    from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle

    shared = {'words': [{'text': '古龙', 'start_ms': 0, 'end_ms': 1000}], 'bounds': (0, 1000)}
    project = SubtitleProject(media=StudioMedia(path='', duration_ms=2000),
                              styles=[SubtitleStyle('default', 'fixture')],
                              cues=[StudioCue('a', 0, 1000, '古龙')])
    project.asr_evidence = {'shared': shared}
    project.generation_metadata = {'shared': shared, 'flags': [True, None, 1, 1.5]}
    if unsupported:
        project.generation_metadata['custom'] = OrderedDict([('first', ['kept']), ('second', 2)])
    expected = copy.deepcopy(project)
    worker = _SaveThread(project, tmp_path / 'unused.2byteproj')
    try:
        snapshot = worker.project
        assert snapshot == expected
        assert snapshot.asr_evidence['shared'] is snapshot.generation_metadata['shared']
        snapshot.asr_evidence['shared']['words'][0]['text'] = '骨龙'
        snapshot.cues[0].text = '骨龙'
        assert project.asr_evidence['shared']['words'][0]['text'] == '古龙'
        assert project.cues[0].text == '古龙'
        if unsupported:
            assert type(snapshot.generation_metadata['custom']) is OrderedDict
            snapshot.generation_metadata['custom']['first'].append('private')
            assert project.generation_metadata['custom']['first'] == ['kept']
    finally:
        worker.deleteLater()
