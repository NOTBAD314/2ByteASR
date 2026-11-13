"""2026-11-13 AI 词库校对 bilingual design A: source and translation share a
row, captions are counted once, and ✕ in one proposal bubble ignores only it."""
from types import SimpleNamespace

import pytest

from tests.test_bilingual_text_targets import APP, make_project
from twobyteasr.glossary.glossary_proofread import GlossaryProofreadPage, _StandalonePage, _issue


@pytest.fixture
def review(tmp_path):
    p = make_project()
    w = GlossaryProofreadPage(SimpleNamespace(studio_page=None))
    w._project = p
    w._project_path = str(tmp_path / 'work.2byteproj')
    w._standalone = _StandalonePage(p)
    w._bind_stack(w._standalone.session.undo_stack)
    w._build_rows(p, start_checks=False)
    yield w, p
    w._save_timer.stop()
    w._rematch_timer.stop()
    if hasattr(w, '_local_timer'):
        w._local_timer.stop()
    w.shutdown()
    w.close()
    w.deleteLater()
    APP.processEvents()


def both(w):
    w.text_targets.mode.setCurrentIndex(w.text_targets.mode.findData('both'))
    w.text_targets.track.setCurrentIndex(w.text_targets.track.findData('translation-records:zh-Hans'))
    w._apply_filter()


def test_translation_sits_beside_its_caption_and_visible_lists_every_text(review):
    w, _p = review
    assert not w.list.paired and all(right is None for _left, right in w.list.slots)
    both(w)
    assert w.list.paired
    keys = [w._rows[i]['cue_id'] for i in w.list.visible]
    translation = next(k for k in keys if k.startswith('translation:') and '"source-a"' in k)
    assert 'source-a' in keys and translation in keys  # visible still lists each text row
    slot = w.list.slot_of('source-a')
    assert slot == w.list.slot_of(translation) >= 0
    left, right = w.list.slots[slot]
    assert w._rows[left]['cue_id'] == 'source-a' and w._rows[right]['cue_id'] == translation
    assert len(w.list.slots) < len(w.list.visible)
    # Both texts of a caption carry its number; the chips count captions.
    assert w._by_id['source-a']['number'] == w._by_id[translation]['number']
    captions = len({w._rows[i]['cue_id'] for i in w.list.visible} - {translation} -
                   {k for k in keys if k.startswith('translation:')})
    assert f"{captions} 条" in w.filter_buttons['all'].text()
    # The header boxes drive the same model.
    w.columns_header.translation.setChecked(False)
    assert w.text_targets.mode_value() == 'original' and not w.list.paired
    w.columns_header.source.setChecked(False)  # never both off
    assert w.columns_header.source.isChecked() and w.text_targets.mode_value() == 'original'


def test_filtered_translation_brings_its_caption_as_context(review):
    w, _p = review
    both(w)
    translation = next(r['cue_id'] for r in w._rows if r['cue_id'].startswith('translation:') and '"source-a"' in r['cue_id'])
    w.list.set_visible([w._row_indexes[translation]])
    assert [w._rows[i]['cue_id'] for i in w.list.visible] == [translation]
    left, right = w.list.slots[0]
    assert w._rows[left]['cue_id'] == 'source-a' and w._rows[right]['cue_id'] == translation


def test_cross_in_one_bubble_ignores_only_that_group(review):
    w, p = review
    row = w._by_id['source-a']
    row['issues'] = [_issue('term', (0, 6), 'SHARED', 'Shared', checked=False),
                     _issue('near', (7, 18), 'Neuvillette', 'Neuvilette', checked=False)]
    w._apply_filter()
    assert len(w._unresolved(row)) == 2
    w._ignore_group('source-a', 0)
    assert row['issues'][0]['reviewed'] and not row['issues'][1]['reviewed']
    assert not row.get('review_dismissed')
    assert next(c.text for c in p.cues if c.id == 'source-a') == 'SHARED Neuvillette appears'
    w._undo()
    assert len(w._unresolved(w._by_id['source-a'])) == 2
    w._redo()
    # The last open one: ✕ ignores the caption like 忽略本行建议.
    w._ignore_group('source-a', 1)
    assert not w._unresolved(w._by_id['source-a'])


def test_bubble_paints_adopt_and_ignore_targets(review):
    w, _p = review
    row = w._by_id['source-a']
    row['issues'] = [_issue('term', (7, 18), 'Neuvillette', 'Neuvilette', checked=False)]
    w._apply_filter()
    w.resize(1400, 800)
    w.show()
    APP.processEvents()
    w.list.repaint()
    actions = {action for _rect, action, cue, _index in w.list._hit_boxes if cue == 'source-a'}
    assert {'check', 'ignore_group', 'detail', 'rowcheck', 'edit', 'play'} <= actions


def test_narrow_page_wraps_commands_without_horizontal_clipping(review):
    w, _p = review
    w.resize(1024, 720)
    w.show()
    for _ in range(5):
        APP.processEvents()
    viewport = w.page_scroll.viewport()
    assert w.page_scroll.widget().width() <= viewport.width()
    assert w.page_scroll.horizontalScrollBar().maximum() == 0
    for control in (w.search, w.ai_button, w.undo_button, w.batch_all, w.select_all):
        w.page_scroll.ensureWidgetVisible(control, 8, 8)
        APP.processEvents()
        from PySide6.QtCore import QPoint
        left = control.mapTo(viewport, QPoint()).x()
        assert left >= 0 and left + control.width() <= viewport.width()
