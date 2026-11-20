"""2026-11-19 (user): a caption edited under 有修改建议 / 待确认 stays where it
is, marked 已修改 (before → after), until the user moves on; a second spot on
the same caption stays reachable. Counts still follow the edit."""
from tests.test_proofread_retention import page, APP  # noqa: F401  (fixture)
from twobyteasr.glossary.glossary_proofread import change_summary


def visible(w):
    return [w._rows[n]['cue_id'] for n in w.list.visible]


def pick(w, key):
    w.filter_buttons[key].setChecked(True)
    w._filter_clicked()


def test_pending_edit_stays_listed_marked_and_second_spot_reachable(page):
    w, p = page
    pick(w, 'pending')
    assert visible(w) == ['middle', 'later'] and w._filter_counts['pending'] == 2
    w._edit_committed('later', '另一条骨龙')
    # Count follows the edit, the row does not jump away under the cursor.
    assert w._filter_counts['pending'] == 1
    assert visible(w) == ['middle', 'later']
    assert 'later' in w.list.held_ids
    assert w.list._held_note(w._by_id['later']) == '切换筛选后移出'
    assert change_summary(w._by_id['later']['origin'], w._by_id['later']['base']) == '古 → 骨'
    # Two spots on one caption: adopting the first keeps the second at hand.
    w._toggle_issue('middle', 0)
    assert visible(w) == ['middle', 'later'] and 'middle' not in w.list.held_ids  # still pending itself
    w._toggle_issue('middle', 1)
    assert p.cues[0].text == '大骨龙和火笼来了'
    assert visible(w) == ['middle', 'later'] and w.list.held_ids == {'middle', 'later'}
    assert w._filter_counts['pending'] == 0
    # Still editable: take one adoption back, then adopt again in place.
    w._toggle_issue('middle', 1)
    assert p.cues[0].text == '大骨龙和火龙来了' and 'middle' not in w.list.held_ids
    w._toggle_issue('middle', 1)
    assert visible(w) == ['middle', 'later']


def test_moving_on_releases_held_rows(page):
    w, p = page
    pick(w, 'pending')
    w._edit_committed('later', '另一条骨龙')
    assert visible(w) == ['middle', 'later']
    pick(w, 'pending')  # picking the same filter again is a refresh
    assert visible(w) == ['middle']
    w._edit_committed('middle', '大骨龙和火笼来了')
    pick(w, 'all')
    pick(w, 'pending')
    assert visible(w) == []


def test_search_or_speaker_change_releases_and_undo_keeps_place(page):
    w, p = page
    pick(w, 'suggested')
    w._edit_committed('later', '另一条骨龙')
    w._undo()  # full refresh path: the row neither jumps nor is lost
    assert visible(w) == ['middle', 'later'] and p.cues[1].text == '另一条古龙'
    w._redo()
    assert visible(w) == ['middle', 'later'] and 'later' in w.list.held_ids
    w.search.setText('古龙'); w._apply_filter()
    assert visible(w) == ['middle']
    w.search.setText(''); w._apply_filter()
    assert visible(w) == ['middle']


def test_explicit_ignore_still_leaves_at_once(page):
    w, p = page
    pick(w, 'suggested')
    w._toggle_issue('middle', 0); w._toggle_issue('middle', 1)
    assert 'middle' in visible(w)
    w._dismiss_group('middle', -1)
    assert visible(w) == ['later'] and 'middle' not in w._held[1]


def test_all_filter_needs_no_hold_and_held_row_paints(page):
    w, p = page
    pick(w, 'all')
    w._edit_committed('later', '另一条骨龙')
    assert w._held[1] == set() and visible(w) == ['middle', 'later']
    pick(w, 'pending')
    w._edit_committed('middle', '大骨龙和火笼来了')
    row = w._by_id['middle']
    assert w.list._has_status(row) and 'middle' in w.list.held_ids
    w.resize(1200, 700); w.show(); APP.processEvents()
    assert not w.grab().isNull()  # 已修改 · before → after · 切换筛选后移出 paints
    w.hide()
