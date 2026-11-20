"""2026-11-19 (user picked draft B, 「学习路线」): the tutorial centre's chapters are one path of
numbered nodes, the next chapter to learn is marked, and the window has no square dark block."""
from __future__ import annotations

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


def test_every_chapter_is_a_numbered_node_on_one_path(centre):
    from twobyteasr.app import tutorial_chapters
    assert [key for _node, key in centre.path.nodes] == [chapter.id for chapter in tutorial_chapters.CATALOG]
    first = centre.nodes['first']
    assert first.text() == '✓' and first.property('done') is True        # learned: a tick
    second_id = tutorial_chapters.CATALOG[1].id
    assert centre.nodes[second_id].text() == '2'


def test_the_next_chapter_to_learn_is_marked_and_picked(centre):
    from PySide6.QtWidgets import QLabel
    from twobyteasr.app.tutorial_centre import recommended
    assert centre.path.next_up == recommended(centre.learned) == centre.pick
    here = centre.rows[centre.pick].findChildren(QLabel, 'pathHere')
    assert len(here) == 1
    assert centre.nodes[centre.pick].property('picked') is True
    other = next(key for key in centre.nodes if key != centre.pick)
    centre.select(other)
    assert centre.nodes[other].property('picked') is True and centre.path.picked == other
    assert centre.nodes[centre.path.next_up].property('picked') is False


def test_no_thick_frame_and_no_dark_block_behind_the_list(centre):
    sheet = centre.styleSheet()
    assert 'QDialog#tutorialCentre { background:' in sheet and 'border: 0;' in sheet.split('QDialog#tutorialCentre', 1)[1][:80]
    assert 'QStackedWidget#centreStack' in sheet and 'qt_scrollarea_viewport' in sheet
    assert centre.stack.objectName() == 'centreStack'


def test_the_points_to_learn_are_numbered(centre):
    text = centre.preview_learn.text()
    assert '1.</span>' in text and '2.</span>' in text


# 2026-11-19 (user: the real window looked much worse than the draft). Qt's rules differ from the
# draft's CSS: a radius over half the height draws square corners, labels stretch to the row, and
# min-width does not count the app's button padding.
def test_badges_keep_their_pill_shape_and_the_close_button_is_round(centre, app):
    from PySide6.QtWidgets import QLabel, QPushButton
    centre.resize(866, 713)
    centre.show()
    app.processEvents()
    try:
        for name in ('pathHere', 'pathMile', 'pill'):
            label = centre.findChildren(QLabel, name)[0]
            assert label.height() <= 22, (name, label.height())          # not stretched to the row
        close = centre.findChild(QPushButton, 'centreClose')
        assert (close.width(), close.height()) == (34, 34)
    finally:
        centre.hide()


def test_the_picked_row_is_highlighted_under_the_halo_not_over_it(centre):
    sheet = centre.styleSheet()
    assert 'QPushButton#chapterRow:checked' in sheet and 'background: transparent' in sheet.split('QPushButton#chapterRow', 1)[1][:260]
    assert centre.path.rows[centre.pick] is centre.rows[centre.pick]
    assert not centre.picture.pixmap().isNull() or centre.picture.height() == 180
