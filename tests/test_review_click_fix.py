"""2026-10-15: review card 1 carries click-to-fix marks; P flips 他/她.

The card hit-tests the marks through a text layout mirrored from its label;
the pixel check below makes sure the mirror lands on the painted marks."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioCue
from twobyteasr.studio import studio_review_ui
from twobyteasr.studio.studio_cards import ReviewCandidateCard
from twobyteasr.subtitle_rules.review_suggestions import review_suggestions
from twobyteasr.subtitle_rules.studio_qc import QCCandidate
from tests.test_review_replay_and_window_bounds import _page


def _app():
    return QApplication.instance() or QApplication([])


def _card(text, others=()):
    _app()
    rows = review_suggestions(text, others)
    card = ReviewCandidateCard(0, QCCandidate(text, ("Current",)), is_current=True, current_text=text,
                               suggestions=rows)
    card.resize(520, 110)
    card.show()
    for _ in range(3):
        _app().processEvents()
    return card, rows


def _accent_points(card):
    """Card points where the label painted the accent colour (the marks)."""
    from twobyteasr.design.theme_manager import theme_key
    from twobyteasr.design.ui_theme import theme_definition
    accent = QColor(theme_definition(theme_key()).accent)
    image = card.text_label.grab().toImage()
    ratio = image.devicePixelRatio() or 1
    points = []
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            pixel = image.pixelColor(x, y)
            if (abs(pixel.red() - accent.red()) + abs(pixel.green() - accent.green())
                    + abs(pixel.blue() - accent.blue())) < 40:
                points.append(card.text_label.mapTo(card, QPoint(int(x / ratio), int(y / ratio))))
    return points


def test_marks_are_hit_where_they_are_painted():
    card, rows = _card("然后他来到了那维来特的家", [("然后他来到了那维莱特的家", ("FireRed",))])
    try:
        assert [row.kind for row in rows] == ["pronoun", "model"]
        points = _accent_points(card)
        assert points, "the marks paint in the accent colour"
        hits = [card._mark_at(point) for point in points]
        assert sum(index >= 0 for index in hits) >= 0.8 * len(hits), hits
        assert {0, 1} <= set(hits)
        # Left edge of the text, before the first mark: plain caption text.
        assert card._mark_at(card.text_label.mapTo(card, QPoint(2, card.text_label.height() // 2))) == -1
    finally:
        card.close()


def test_click_on_a_mark_fixes_it_and_elsewhere_adopts_the_card():
    card, rows = _card("然后他来到了那维来特的家", [("然后他来到了那维莱特的家", ("FireRed",))])
    activated, adopted = [], []
    card.suggestion_activated.connect(lambda mark, option: activated.append((mark, option)))
    card.clicked.connect(adopted.append)
    try:
        point = next(point for point in _accent_points(card) if card._mark_at(point) == 1)
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        assert activated == [(1, 0)] and adopted == []
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(card.width() - 4, card.height() - 4))
        assert adopted == [0] and activated == [(1, 0)]
    finally:
        card.close()


def _fake_candidates(table):
    def candidates(project, cue):
        return tuple(QCCandidate(text, sources) for text, sources in table.get(cue.id, ((cue.text, ("Current",)),)))
    return candidates


def test_review_page_applies_one_mark_and_stays_on_the_caption(tmp_path, monkeypatch):
    cues = [StudioCue("a", 0, 2000, "然后他来到了那维来特的家"), StudioCue("b", 3000, 5000, "下一句")]
    app, page = _page(tmp_path, monkeypatch, cues)
    monkeypatch.setattr(studio_review_ui, "review_candidates", _fake_candidates({"a": (
        ("然后他来到了那维来特的家", ("Current",)), ("然后她来到了那维莱特的家", ("FireRed", "Qwen3-ASR")))}))
    try:
        page._set_review_mode(True)
        page.select_cue("a")
        page._refresh_review_summary_strip()
        app.processEvents()
        assert [row.original for row in page._review_suggestions] == ["他", "来"]
        card = page.review_dock_candidate_layout.itemAt(0).widget()
        assert isinstance(card, ReviewCandidateCard) and card._suggestions
        second = page.review_dock_candidate_layout.itemAt(1).widget()
        assert isinstance(second, ReviewCandidateCard) and not second._suggestions  # only card 1 is marked
        assert page._apply_review_suggestion(1)
        assert page._cue_lookup["a"].text == "然后他来到了那维莱特的家"
        assert page.selected_cue_id == "a"
        assert [row.original for row in page._review_suggestions] == ["他"]
        page.undo_stack.undo()
        assert page._cue_lookup["a"].text == "然后他来到了那维来特的家"
    finally:
        page.close_page()
        page.deleteLater()


def test_p_flips_the_caption_and_a_consistent_caption_still_gets_card_one(tmp_path, monkeypatch):
    cues = [StudioCue("a", 0, 2000, "他说他们马上到"), StudioCue("b", 3000, 5000, "下一句")]
    app, page = _page(tmp_path, monkeypatch, cues)
    monkeypatch.setattr(studio_review_ui, "review_candidates", _fake_candidates({}))
    try:
        assert page._review_shortcut_lookup.get("P") == "review_flip_pronoun"
        page._set_review_mode(True)
        page.select_cue("a")
        page._refresh_review_summary_strip()
        app.processEvents()
        layout = page.review_dock_candidate_layout
        widgets = [layout.itemAt(index).widget() for index in range(layout.count())]
        cards = [widget for widget in widgets if isinstance(widget, ReviewCandidateCard)]
        assert len(cards) == 1 and [row.original for row in cards[0]._suggestions] == ["他", "他"]
        assert not page._flip_review_pronouns()  # two people need a precise target
        assert page._canvas_editor is not None
        from PySide6.QtGui import QTextCursor
        page.subtitle_edit_input.moveCursor(QTextCursor.MoveOperation.Start)
        assert page._flip_editor_pronoun()
        assert page._cue_lookup['a'].text == '他说他们马上到'
        page._submit_caption_draft()
        assert page._cue_lookup['a'].text == '她说他们马上到'
        page._refresh_review_summary_strip()
        assert page._apply_review_suggestion(1)  # only the explicitly clicked second pronoun
        assert page._cue_lookup['a'].text == '她说她们马上到'
        page.select_cue("b")
        page._refresh_review_summary_strip()
        app.processEvents()
        widgets = [layout.itemAt(index).widget() for index in range(layout.count())]
        assert not any(isinstance(widget, ReviewCandidateCard) for widget in widgets)  # nothing to fix
    finally:
        page.close_page()
        page.deleteLater()


# 2026-10-17: alternatives are ruby chips above the questioned characters -------
def _centre(card, rect):
    return card.text_label.mapTo(card, rect.center().toPoint())


def test_each_chip_writes_its_own_alternative_and_the_sentence_stays_whole():
    from twobyteasr.studio.review_marked_text import BASE, MORE
    card, rows = _card("须弥的风景真好看", [("虚迷的风景真好看", ("MOSS",)), ("须迷的风景真好看", ("Qwen3-ASR",)),
                                    ("需米的风景真好看", ("FireRed",))])
    activated, menus, adopted = [], [], []
    card.suggestion_activated.connect(lambda mark, option: activated.append((mark, option)))
    card.suggestion_menu_requested.connect(lambda mark, _pos: menus.append(mark))
    card.clicked.connect(adopted.append)
    try:
        assert card.text_label.text() == "须弥的风景真好看"  # plain caption, no arrow or alternatives inline
        rects = card.text_label.chip_rects()
        assert sorted(rects) == [(0, MORE), (0, BASE), (0, 0), (0, 1)]  # two chips and "+1"
        assert rects[(0, 0)].bottom() <= rects[(0, BASE)].top()  # the chips sit above the word
        for key, rect in rects.items():
            assert card._hit_at(_centre(card, rect)) == key
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _centre(card, rects[(0, 1)]))
        assert activated == [(0, 1)]
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _centre(card, rects[(0, MORE)]))
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         _centre(card, rects[(0, BASE)]))
        assert menus == [0, 0] and activated == [(0, 1)] and adopted == []
        tips = [card._mark_tip(0, option) for option in (0, 1, MORE, BASE)]
        assert "MOSS" in tips[0] and "须迷" in tips[1] and "3" in tips[2]
    finally:
        card.close()


def test_chips_stay_apart_and_inside_on_a_narrow_card():
    from twobyteasr.studio.review_marked_text import BASE
    for width in (520, 300, 240):
        for text, others in (
                ("园神那维来特这波开大", [("原神那维莱特这波开打", ("MOSS",)), ("原神那维莱特这波开塔", ("Qwen3-ASR",))]),
                ("他说刀塔蛮好玩的", [("他说DOTA2满好玩的", ("MOSS",)), ("他说刀塔传奇满好玩的", ("Qwen3-ASR",))]),
                ("他说今天咱们去打副本然后再去刷那个材料", [("她说今天咱门去打附本然后在去刷那个才料", ("MOSS",))])):
            card, rows = _card(text, others)
            try:
                card.resize(width, 160)
                _app().processEvents()
                label = card.text_label
                rects = label.chip_rects()
                chips = [(key, rect) for key, rect in rects.items() if key[1] != BASE]
                assert chips
                for index, (key, rect) in enumerate(chips):
                    assert -0.5 <= rect.left() and rect.right() <= label.width() + 0.5, (width, text, key)
                    assert not any(rect.adjusted(0.5, 0.5, -0.5, -0.5).intersects(other) for _k, other in chips[index + 1:])
                assert label.heightForWidth(label.width()) <= label.height() + 1
            finally:
                card.close()


def test_a_line_break_is_a_sign_not_a_second_chip_band():
    card, rows = _card("这个角色的元素暴发\n伤害真的太离普了吧", [("这个角色的元素爆发\n伤害真的太离谱了吧", ("MOSS",))])
    try:
        card.resize(620, 110)
        _app().processEvents()
        label = card.text_label
        assert [row.original for row in rows] == ["暴", "普"]
        one_line = label.heightForWidth(10_000)
        assert label.heightForWidth(label.width()) == one_line  # both marks share one chip band
    finally:
        card.close()
