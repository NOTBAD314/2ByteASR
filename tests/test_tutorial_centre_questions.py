"""2026-11-27 (user: the tutorial window is ugly and complicated, newcomers feel forced to study;
they picked draft B 「我想…」): the chapters are questions in the newcomer's own words, six big
cards and the rest as pills, a search, details pushed in over the list, and nothing that reads
like homework (no numbers, counters, badges or task list)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def centre(app, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from twobyteasr.app import newbie_tasks, onboarding, tutorial_centre
    monkeypatch.setattr(onboarding, 'load_state', lambda: {'chapters_done': ['first']})
    monkeypatch.setattr(newbie_tasks, 'done_keys', lambda window, state: set())
    window = QWidget()
    dialog = tutorial_centre.TutorialCentre(window)
    yield dialog
    dialog.deleteLater()
    window.deleteLater()


def test_every_chapter_is_one_question_six_big_cards_and_the_rest_pills(centre):
    from twobyteasr.app import tutorial_chapters
    from twobyteasr.app.tutorial_centre import POPULAR, QUESTIONS
    ids = [chapter.id for chapter in tutorial_chapters.CATALOG]
    assert set(QUESTIONS) == set(ids)
    assert list(centre.cards) == list(POPULAR) and len(centre.cards) == 6
    assert sorted([*centre.cards, *centre.pills]) == sorted(ids)            # each chapter exactly once
    assert not set(centre.cards) & set(centre.pills)


def test_nothing_reads_like_homework(centre):
    from PySide6.QtWidgets import QLabel, QPushButton
    texts = [label.text() for label in centre.findChildren(QLabel)] + [b.text() for b in centre.findChildren(QPushButton)]
    assert not any('/ 15' in text or '新手任务' in text or '未学' in text or '你在这里' in text for text in texts)
    assert not centre.findChildren(QLabel, 'pathNode') and not centre.findChildren(QLabel, 'pill')
    assert not any(text.strip().isdigit() for text in texts)                     # no chapter numbers
    seen = [label for label in centre.findChildren(QLabel, 'seenTag')]
    assert len(seen) == 1 and seen[0].parentWidget() is centre.cards['first']   # only what was seen, softly


def test_search_finds_by_everyday_words_and_the_cards_close_up(centre, app):
    centre.show()
    app.processEvents()
    try:
        for typed in ('红线', '紅線', '折叠'):
            centre.search.setText(typed)
            app.processEvents()
            shown = [key for key, card in {**centre.cards, **centre.pills}.items() if card.isVisibleTo(centre)]
            assert shown == ['timeline'], (typed, shown)
            index = centre._grid.indexOf(centre.cards['timeline'])
            assert centre._grid.getItemPosition(index)[:2] == (0, 0)             # moved to the first place
            assert not centre.other_label.isVisibleTo(centre) and not centre.empty.isVisibleTo(centre)
        centre.search.setText('剪掉')
        app.processEvents()
        assert centre.cards['cut'].isVisibleTo(centre)
        centre.search.setText('xyzzy')
        app.processEvents()
        assert centre.empty.isVisibleTo(centre) and not centre.popular_label.isVisibleTo(centre)
        centre.search.clear()
        app.processEvents()
        assert all(card.isVisibleTo(centre) for card in [*centre.cards.values(), *centre.pills.values()])
    finally:
        centre.hide()


def test_a_card_opens_its_details_and_starts_the_chapter(centre, app):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    centre.show()
    app.processEvents()
    centre.cards['timeline'].click()
    app.processEvents()
    assert centre.detail_page.isVisible() and centre.pick == 'timeline'
    assert '看懂时间轴' in centre.preview_title.text() and '约 5 分钟' in centre.start_button.text()
    assert '✓' in centre.preview_learn.text()
    assert centre.picture.height() > 100
    centre.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert not centre.detail_page.isVisible() and centre.isVisible()             # Esc: back to the questions first
    centre.pills['editor'].click()
    app.processEvents()
    centre.back_button.click()
    assert not centre.detail_page.isVisible()
    centre.open_detail('first')
    assert '再看一遍' in centre.start_button.text()                              # seen: watch again
    centre.open_detail('cut')
    centre.start_button.click()
    import time
    deadline = time.monotonic() + 3
    while centre.result() != 1 and time.monotonic() < deadline:   # a shown dialog closes with its animation
        app.processEvents()
        time.sleep(0.01)
    assert centre.chosen == 'cut' and centre.result() == 1


def test_old_callers_with_a_tab_still_open_it(app, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from twobyteasr.app import onboarding, tutorial_centre
    monkeypatch.setattr(onboarding, 'load_state', lambda: {})
    dialog = tutorial_centre.TutorialCentre(QWidget(), tab='tasks')
    assert dialog.width() == 980 and 540 <= dialog.height() <= 620 and dialog.cards
    dialog.deleteLater()


def test_cards_keep_the_drafts_size_and_the_window_fits_them(app, monkeypatch):
    """2026-11-27 (user: on the host the window was mostly empty space, the cards tall boxes with
    a little text at the top, unlike the draft): the cards keep their own height, a wider window
    grows every size by one share, and the window is as tall as the questions (no scroll bar, no
    empty strip)."""
    import time
    from PySide6.QtWidgets import QWidget
    from twobyteasr.app import onboarding, tutorial_centre
    monkeypatch.setattr(onboarding, 'load_state', lambda: {})
    assert tutorial_centre._scale_for(980) == 1.0 and tutorial_centre._scale_for(1210) == 1.25
    assert tutorial_centre._scale_for(4000) == tutorial_centre.MOST_SCALE
    host = QWidget()
    host.resize(1680, 1000)
    host.show()
    dialog = tutorial_centre.TutorialCentre(host)
    try:
        dialog.show()
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        card = dialog.cards['first']
        tallest = max(other.heightForWidth(other.width()) for other in dialog.cards.values())
        assert card.height() <= tallest + 2, (card.height(), tallest)     # its row's tallest, not stretched
        assert not hasattr(card, 'learn_label')            # icon, question, minutes: no grey points
        # A small test screen squeezes the shown window; measure again at the width it got.
        from PySide6.QtCore import QSize
        dialog.resize(dialog.width(), dialog._fitted_height(QSize(dialog.width(), 4000)))
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        holder, viewport = dialog.scroll.widget(), dialog.scroll.viewport()
        pills = dialog._flow.parentWidget()
        assert pills.geometry().bottom() <= viewport.height(), 'the pills fit without scrolling'
        assert viewport.height() - pills.geometry().bottom() <= dialog._px(24), 'no empty strip below'
        assert holder.height() <= viewport.height() + 1
    finally:
        dialog.close()
        dialog.deleteLater()
        host.deleteLater()


def test_every_new_string_has_en_ja_and_traditional_chinese():
    from twobyteasr.app.tutorial_centre import QUESTIONS
    texts = list(QUESTIONS.values()) + ['遇到什么就点哪张卡，我陪你做一次。不用全部学～', '例如：剪掉开头', '大家最常问',
                                         '其他问题', '没找到这个问题。关掉这里，点顶栏的「问问兔白」直接问她。', '✓ 看过',
                                         '用示范工程练习，按 Esc 随时停下', '‹  换一个问题', '「{value0}」',
                                         '再看一遍（约 {value0} 分钟）', '开始（约 {value0} 分钟）',
                                         '搜索问题，跟着示范练习']
    catalogs = {lang: json.loads((Path('twobyteasr/locales') / f'{lang}.json').read_text('utf-8'))
                for lang in ('en', 'ja', 'zh-Hant')}
    missing = [(lang, text) for text in texts for lang, table in catalogs.items() if text not in table]
    assert not missing
