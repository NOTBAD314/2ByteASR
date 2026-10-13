"""AI glossary proofreading workspace (2026-10-09 M14; 2026-10-10 rework).

Every caption is listed and editable on entry; libraries are inherited from
the project; proposals live inside each caption's row. Since the evening of
2026-10-10 every action — a direct edit, adopting or un-adopting a proposal,
a right-click batch replace, Ctrl+H — is written to the project at once as
one undoable step that Studio, previews and exports read; a proposal is only
a proposal until it is adopted.
"""
from __future__ import annotations

import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont, QFontMetrics, QFontMetricsF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from twobyteasr.glossary_proofread import (adopt_text, issue_pair, line_units, parse_term_input,  # noqa: E402
                                           parse_term_lines, rebase_issue, rebase_issues, suggestion_mark, window_text,
                                           wrap_units)

APP = QApplication.instance() or QApplication([])


def test_term_lines_accept_canonicals_and_misheard_spellings():
    assert parse_term_lines("CHICHOO\n球球 → CHICHOO\nAutumn、Nobody=nobody\n\nCHICHOO") == [
        (None, "CHICHOO"), ("球球", "CHICHOO"), (None, "Autumn"), ("Nobody", "nobody")]
    assert parse_term_lines("a -> a") == [(None, "a")]
    assert parse_term_lines("  \n ") == []
    assert parse_term_lines("BerLIN\nS0pp\nZhe\nchiochoo → CHIOCHOO") == [
        (None, "BerLIN"), (None, "S0pp"), (None, "Zhe"), ("chiochoo", "CHIOCHOO")]


def test_term_input_needs_no_arrow_and_keeps_names_whole():
    """2026-10-10 (user): typing → is hard; left wrong, right correct."""
    assert parse_term_lines("古龙 - 骨龙\n古龙 骨龙\n球球\tCHICHOO\nCHICHOO\nautumn") == [
        ("古龙", "骨龙"), ("球球", "CHICHOO"), (None, "CHICHOO"), (None, "autumn")]
    assert parse_term_lines("球球 CHICHOO\nchiochoo CHIOCHOO") == [("球球", "CHICHOO"), ("chiochoo", "CHIOCHOO")]
    # A spreadsheet row with a third column keeps the first two.
    assert parse_term_lines("球球\tCHICHOO\t选手 ID") == [("球球", "CHICHOO")]
    # Hyphens and spaces inside names are not separators.
    assert parse_term_lines("Spider-Man\nX-Ray - 叉光") == [(None, "Spider-Man"), ("X-Ray", "叉光")]
    # Two different Latin words: a name or wrong → right? Ask, never guess.
    [entry] = parse_term_input("Lord Fire")
    assert entry["ambiguous"] and entry["canonical"] == "Lord Fire"
    [flipped] = parse_term_input("Lord Fire", {"Lord Fire": "pair"})
    assert (flipped["alias"], flipped["canonical"], flipped["ambiguous"]) == ("Lord", "Fire", False)
    [kept] = parse_term_input("Lord Fire", {"Lord Fire": "name"})
    assert (kept["alias"], kept["canonical"], kept["ambiguous"]) == (None, "Lord Fire", False)
    # Case and digits stay exactly as typed.
    assert parse_term_lines("berlin BerLIN\nS0pp") == [("berlin", "BerLIN"), (None, "S0pp")]


def test_long_text_keeps_the_changed_span_visible():
    # Fixed advances: the offscreen platform has no system fonts, and once any
    # test in the process has drawn an icon every family resolves to an icon
    # face in which CJK characters measure 0 px.
    metrics = SimpleNamespace(horizontalAdvance=lambda text: 14 * len(text))
    text = "前" * 40 + "CHIOCHOO" + "后" * 40
    start = text.index("CHIOCHOO")
    prefix, middle, suffix = window_text(text, start, start + 8, metrics, 260)
    assert middle == "CHIOCHOO"
    assert prefix.startswith("…") and suffix.endswith("…")
    assert metrics.horizontalAdvance(prefix + middle + suffix) <= 260 + metrics.horizontalAdvance("…")
    assert window_text("短句", 0, 1, metrics, 400) == ("", "短", "句")


def _issue(text, original, replacement, *, checked=False, kind="term"):
    a = text.index(original if not checked else replacement)
    b = a + len(original if not checked else replacement)
    return dict(kind=kind, span=(a, b), original=original, replacement=replacement, checked=checked,
                default=True, reason="", hit=None, options=(), evidence="", stale=False, reviewed=False)


def test_marks_show_only_the_wrong_characters_and_whole_latin_names():
    text = "这里出现了一只古龙"
    assert suggestion_mark(text, _issue(text, "古龙", "骨龙")) == (7, 8, "骨")
    text = "球球来了"
    assert suggestion_mark(text, _issue(text, "球球", "CHICHOO")) == (0, 2, "CHICHOO")
    text = "berlin来了"
    assert suggestion_mark(text, _issue(text, "berlin", "BerLIN")) == (0, 6, "BerLIN")
    text = "天黑黑药"
    assert suggestion_mark(text, _issue(text, "天黑黑", "天飞飞钥")) == (1, 3, "飞飞钥")


def test_long_sentences_wrap_with_each_replacement_under_its_word():
    font = QFont()
    font.setPixelSize(19)
    below = QFont(font)
    below.setPixelSize(16)
    top_metrics, below_metrics = QFontMetricsF(font), QFontMetricsF(below)
    text = "非常尴尬的一幕" * 6 + "还有古龙和球球"
    marks = [dict(start=text.index("古"), end=text.index("古") + 1, below="骨", style="suggest", ref=0),
             dict(start=text.index("球球"), end=text.index("球球") + 2, below="CHICHOO", style="suggest", ref=1)]
    units = line_units(text, marks)
    assert "".join(unit["top"] for unit in units) == text
    for width in (220, 360, 900):
        lines = wrap_units(units, width, top_metrics, below_metrics, 3)
        assert len(lines) >= 2 if width < 900 else True
        for line in lines:
            right = 0.0
            for unit in line:
                assert unit["x"] >= right - 1e-6  # nothing overlaps
                right = unit["x"] + unit["w"]
                if unit["mark"] is not None:
                    # The box is wide enough for the replacement written under it.
                    assert unit["w"] >= below_metrics.horizontalAdvance(unit["below"])
                    assert unit["w"] >= top_metrics.horizontalAdvance(unit["top"])
            assert right <= width or len(line) == 1


def test_adopted_state_follows_the_text_through_undo_and_redo():
    text = "这里古龙然后古龙"
    issue = _issue(text, "古龙", "骨龙")
    adopted = adopt_text(text, [issue])
    assert adopted == "这里骨龙然后古龙"
    rebase_issue(issue, text, adopted)
    assert issue["checked"] and issue["span"] == (2, 4)
    rebase_issue(issue, adopted, text)  # undo
    assert not issue["checked"] and issue["span"] == (2, 4) and not issue["stale"]
    rebase_issue(issue, text, "前面加字这里古龙然后古龙")  # an edit elsewhere shifts it
    assert issue["span"] == (6, 8) and not issue["checked"]
    rebase_issue(issue, "前面加字这里古龙然后古龙", "全部重写了")
    assert issue["stale"] and not issue["checked"]
    stammer = "这这次"
    deletion = dict(_issue(stammer, "这", ""), span=(0, 1))
    cleaned = adopt_text(stammer, [deletion])
    assert cleaned == "这次"
    rebase_issue(deletion, stammer, cleaned)
    assert deletion["checked"]
    rebase_issue(deletion, cleaned, stammer)
    assert not deletion["checked"] and deletion["span"] == (0, 1)


def test_a_replacement_that_is_undone_brings_the_proposal_back():
    """Batch 古龙→骨龙, then Ctrl+H 骨龙→X, then undo: the proposal was shown
    as "expired" for good (daily EXE check, 2026-10-10)."""
    text = "保一下古龙状态的人"
    issue = _issue(text, "古龙", "骨龙")
    issues = [issue]
    batch = "保一下骨龙状态的人"
    rebase_issues(issues, text, batch)
    assert issue["checked"] and not issue["stale"]
    away = "保一下X状态的人"
    rebase_issues(issues, batch, away)
    assert issue["stale"] and not issue["checked"]
    rebase_issues(issues, away, batch)  # undo of the second replacement
    assert issue["checked"] and not issue["stale"] and issue["span"] == (3, 5)
    rebase_issues(issues, batch, text)  # undo of the batch
    assert not issue["checked"] and not issue["stale"] and issue["span"] == (3, 5)
    rebase_issues(issues, text, "全部重写了")
    rebase_issues(issues, "全部重写了", "还是重写")
    assert issue["stale"]  # never brought back by an unrelated text


def test_batch_replace_uses_the_whole_word_not_one_character():
    row = dict(base="这里出现了一只古龙", origin="这里出现了一只古龙")
    issue = dict(_issue(row["base"], "古", "骨"), span=(7, 8))
    assert issue_pair(row, issue) == ("古龙", "骨龙")
    row["base"] = adopt_text(row["base"], [issue])
    issue["checked"] = True
    assert issue_pair(row, issue) == ("古龙", "骨龙")
    assert issue_pair(row, dict(issue, replacement="")) is None


def _wait(page, seconds=20):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        if not page.checks_running():
            for _ in range(5):
                APP.processEvents()
            return True
        time.sleep(0.02)
    return False


def _wait_saved(page, seconds=20):
    """Without Studio the project file is written on a background thread."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        if page._save_thread is None:
            for _ in range(5):
                APP.processEvents()
            return True
        time.sleep(0.02)
    return False


def _page():
    from twobyteasr.glossary_proofread import GlossaryProofreadPage
    return GlossaryProofreadPage(SimpleNamespace(studio_page=None, _prepare_glossary_for_task=lambda: True))


def _close(page):
    page.shutdown()
    page.deleteLater()
    APP.processEvents()


def _save(tmp_path, name, cues, glossary_ids=(), snapshot=None):
    from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
    project = SubtitleProject(media=StudioMedia(path="", duration_ms=8000),
                              cues=[StudioCue(cue_id, a, b, text) for cue_id, a, b, text in cues])
    project.glossary_ids = list(glossary_ids)
    if snapshot is not None:
        project.generation_metadata["terminology_snapshot"] = snapshot
    path = tmp_path / f"{name}.2byteproj"
    save_project(project, path)
    return path


def _library(name, *pairs, category="其他"):
    import subtitle_core as legacy
    for source, target in pairs:
        legacy.add_learned_mapping(name, source, target, category=category, origin="手动")
    return next(row["id"] for row in legacy.glossary_catalog() if row["name"] == name)


def _row(page, cue_id):
    return next(row for row in page._rows if row["cue_id"] == cue_id)


def test_every_caption_is_listed_readable_and_editable_without_a_library(tmp_path):
    """古龙 → 骨龙 is a direct edit: written to the project at once, no library."""
    import subtitle_core as legacy
    from twobyteasr.studio_project import load_project
    path = _save(tmp_path, "plain", [("c1", 0, 2000, "嗯 然后古龙首发"), ("c2", 2000, 4000, "非常尴尬的一幕"),
                                     ("c3", 4000, 6000, "我们看下一局")])
    catalog = [dict(row) for row in legacy.glossary_catalog()]
    page = _page()
    try:
        page.open_task(str(path), load_project(path))
        assert _wait(page)
        assert [row["base"] for row in page._rows] == ["嗯 然后古龙首发", "非常尴尬的一幕", "我们看下一局"]
        assert page.list.visible == [0, 1, 2] and page._selected_ids() == ()
        assert page.filter_buttons["all"].text().endswith("3 条")  # captions, with their unit
        page.filter_buttons["suggested"].click()
        assert page.list.visible == [] and "目前没有修改建议" in page.list.empty_text
        page.filter_buttons["all"].click()
        assert not page.undo_button.isEnabled() and page.apply_button.isHidden()
        # Typing goes through the inline editor; Enter commits once and closes it.
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QInputMethodEvent
        from PySide6.QtTest import QTest
        page.resize(1400, 800)
        page.show()
        APP.processEvents()
        applied = []
        page.applied.connect(applied.append)
        page._edit("c1")
        editor = page.list.editor
        assert editor.isVisible() and editor.text() == "嗯 然后古龙首发"
        editor.selectAll()
        commit = QInputMethodEvent("", [])
        commit.setCommitString("嗯 然后骨龙首发")
        QApplication.sendEvent(editor, commit)
        QTest.keyClick(editor, Qt.Key.Key_Return)
        APP.processEvents()
        assert not editor.isVisible() and page.list.editing() == ""
        # Written at once: the project changed, one undo step, saved shortly after.
        assert page._live_project()[0].cues[0].text == "嗯 然后骨龙首发"
        assert page.changed_values() == {"c1": "嗯 然后骨龙首发"} and page.pending_values() == {}
        assert page.undo_button.isEnabled() and "本页已改 1 条" in page.count_label.text()
        assert page.list._remember_action(_row(page, "c1")) == ("古龙", "骨龙")
        page._flush_save()
        assert _wait_saved(page) and applied and applied[-1] == str(path)
        saved = load_project(path)
        assert [cue.text for cue in saved.cues] == ["嗯 然后骨龙首发", "非常尴尬的一幕", "我们看下一局"]
        receipt = saved.generation_metadata["glossary_review_jobs"][-1]
        assert receipt["changes"] == [{"cue_id": "c1", "from": "嗯 然后古龙首发", "to": "嗯 然后骨龙首发",
                                       "manual": True, "kinds": []}]
        assert saved.studio_state["manual_caption_text"] == {"c1": "嗯 然后骨龙首发"}
        page.filter_buttons["changed"].click()
        assert page.list.visible == [0]
        assert [dict(row) for row in legacy.glossary_catalog()] == catalog  # no library touched
        page._undo()
        page._flush_save()
        assert load_project(path).cues[0].text == "嗯 然后古龙首发"
        assert _row(page, "c1")["base"] == "嗯 然后古龙首发" and page.redo_button.isEnabled()
        page._redo()
        page._flush_save()
        assert load_project(path).cues[0].text == "嗯 然后骨龙首发"
    finally:
        _close(page)


def test_new_terms_follow_the_single_chosen_library_and_ask_when_several(tmp_path):
    from PySide6.QtCore import Qt
    from twobyteasr.studio_project import load_project
    first = _library("目标甲", ("龙威", "龙威"))
    second = _library("目标乙", ("火狗", "火狗"))
    path = _save(tmp_path, "target", [("c1", 0, 2000, "嗯 然后古龙首发")], glossary_ids=[first])
    page = _page()
    try:
        page.open_task(str(path), load_project(path))
        assert _wait(page)
        assert page.target_combo.currentData() == first and "目标甲" in page.target_note.text()
        item = next(page.library_list.item(i) for i in range(page.library_list.count())
                    if page.library_list.item(i).data(Qt.ItemDataRole.UserRole) == second)
        item.setCheckState(Qt.CheckState.Checked)
        assert _wait(page)
        assert page.target_combo.currentData() == first  # an explicit, still-chosen target stays
        page.target_combo.setCurrentIndex(-1)
        page.target_combo.setEditText("")
        assert "请选择新词要加入哪一个" in page.target_note.text() and not page.add_button.isEnabled()
        first_item = next(page.library_list.item(i) for i in range(page.library_list.count())
                          if page.library_list.item(i).data(Qt.ItemDataRole.UserRole) == first)
        first_item.setCheckState(Qt.CheckState.Unchecked)
        assert _wait(page)
        assert page.target_combo.currentData() == second  # the one remaining library
        # Remembering a direct edit writes only to that target.
        page._edit_committed("c1", "嗯 然后骨龙首发")
        page._remember("c1")
        import subtitle_core as legacy
        from twobyteasr.terminology import snapshot_glossaries
        terms = {library.id: {(alias, term.canonical) for term in library.terms for alias in term.aliases}
                 for library in snapshot_glossaries(legacy, [first, second]).libraries}
        assert ("古龙", "骨龙") in terms[second] and ("古龙", "骨龙") not in terms[first]
        assert page.changed_values() == {"c1": "嗯 然后骨龙首发"}
        assert page._stack.count() == 1  # remembering is a library change, not a caption edit
    finally:
        _close(page)


def test_user_spellings_keep_their_case_from_library_to_subtitle(tmp_path):
    import subtitle_core as legacy
    from twobyteasr.studio_project import load_project
    from twobyteasr.terminology import snapshot_glossaries
    path = _save(tmp_path, "case", [("c1", 0, 2000, "berlin和s0pp还有zhe"), ("c2", 2000, 4000, "chiochoo来了")])
    page = _page()
    try:
        page.open_task(str(path), load_project(path))
        assert _wait(page)
        page.term_input.setPlainText("BerLIN\nS0pp\nZhe\nchiochoo CHIOCHOO")
        assert "chiochoo <b>→</b> CHIOCHOO" in page.term_preview.text()
        page.target_combo.setEditText("大小写词库")
        page._add_terms()
        assert _wait(page)
        identity = page._target_id()
        canonicals = {term.canonical for library in snapshot_glossaries(legacy, [identity]).libraries
                      for term in library.terms}
        assert {"BerLIN", "S0pp", "Zhe", "CHIOCHOO"} <= canonicals
        assert _row(page, "c1")["base"] == "berlin和s0pp还有zhe"  # proposals only, nothing written yet
        page._set_all(True)  # 采用全部建议: one step
        assert _row(page, "c1")["base"] == "BerLIN和S0pp还有Zhe" and _row(page, "c2")["base"] == "CHIOCHOO来了"
        assert page._stack.count() == 1
        page._flush_save()
        assert [cue.text for cue in load_project(path).cues] == ["BerLIN和S0pp还有Zhe", "CHIOCHOO来了"]
    finally:
        _close(page)


def test_ambiguous_term_lines_wait_for_a_decision(tmp_path):
    from twobyteasr.studio_project import load_project
    path = _save(tmp_path, "ambiguous", [("c1", 0, 2000, "lord来了")])
    page = _page()
    try:
        page.open_task(str(path), load_project(path))
        assert _wait(page)
        page.term_input.setPlainText("Lord Fire\n古龙 骨龙")
        assert "当作一个标准写法" in page.term_preview.text() and "pair:Lord Fire" in page.term_preview.text()
        page.target_combo.setEditText("歧义词库")
        page._add_terms()
        assert _wait(page)
        assert "需要先确认" in page.add_status.text() and page.term_input.toPlainText() == "Lord Fire"
        page._flip_term("pair:Lord Fire")
        assert "Lord <b>→</b> Fire" in page.term_preview.text()
    finally:
        _close(page)


def test_only_adopted_proposals_are_written_back(tmp_path):
    from twobyteasr.studio_project import load_project
    identity = _library("勾选检查", ("autumn", "Autumn"), ("CHIOCHOO", "CHICHOO"))
    path = _save(tmp_path, "ticked", [("c1", 0, 2000, "还是在等autumn出结果"), ("c2", 2000, 4000, "而且CHIOCHOO能奶自己"),
                                      ("c3", 4000, 6000, "非常尴尬的一幕")], glossary_ids=[identity])
    page = _page()
    try:
        page.open_task(str(path), load_project(path))
        assert _wait(page)
        assert [row["base"] for row in page._rows] == ["还是在等autumn出结果", "而且CHIOCHOO能奶自己", "非常尴尬的一幕"]
        assert all(not issue["checked"] for row in page._rows for issue in row["issues"])
        page._toggle_issue("c2", 0)  # adopt this one only
        assert _wait(page)
        page._flush_save()
        saved = {cue.id: cue.text for cue in load_project(path).cues}
        assert saved == {"c1": "还是在等autumn出结果", "c2": "而且CHICHOO能奶自己", "c3": "非常尴尬的一幕"}
        project = load_project(path)
        assert project.glossary_ids == [identity]
        receipt = project.generation_metadata["glossary_review_jobs"][-1]
        assert receipt["applied_cue_ids"] == ["c2"] and receipt["changes"][0]["kinds"] == ["term"]
        assert receipt["operation"] == "adopt"
        # Un-adopting writes the original back, as its own undoable step.
        page._toggle_issue("c2", next(i for i, issue in enumerate(_row(page, "c2")["issues"]) if issue["checked"]))
        assert _row(page, "c2")["base"] == "而且CHIOCHOO能奶自己" and page._stack.count() == 2
    finally:
        _close(page)


def test_changed_subtitles_are_never_overwritten_by_a_stale_review(tmp_path):
    from twobyteasr.studio_project import load_project
    identity = _library("陈旧检查", ("CHIOCHOO", "CHICHOO"))
    path = _save(tmp_path, "stale", [("c1", 0, 2000, "而且CHIOCHOO能奶自己")], glossary_ids=[identity])
    page = _page()
    try:
        page.open_task(str(path), load_project(path))
        assert _wait(page)
        page._project.cues[0].text = "用户刚刚改过这一句"
        page._toggle_issue("c1", 0)
        assert "已在别处改变" in page.status_label.text()
        assert page._project.cues[0].text == "用户刚刚改过这一句"
        assert _row(page, "c1")["base"] == "用户刚刚改过这一句" and _row(page, "c1")["issues"][0]["stale"]
        page._flush_save()
        assert load_project(path).cues[0].text == "而且CHIOCHOO能奶自己"  # nothing was written
    finally:
        _close(page)


def test_a_manual_edit_reanchors_or_expires_old_proposals(tmp_path):
    from twobyteasr.studio_project import load_project
    identity = _library("过期检查", ("CHIOCHOO", "CHICHOO"), ("autumn", "Autumn"))
    path = _save(tmp_path, "expire", [("c1", 0, 2000, "CHIOCHOO和autumn")], glossary_ids=[identity])
    page = _page()
    try:
        page.open_task(str(path), load_project(path))
        assert _wait(page)
        row = _row(page, "c1")
        page._toggle_issue("c1", 0)  # CHIOCHOO → CHICHOO is written
        assert row["base"] == "CHICHOO和autumn"
        left = next(issue for issue in row["issues"] if issue["original"] == "autumn")
        page._edit_committed("c1", "前面 CHICHOO和autumn")
        assert left["original"] == "autumn" and left["span"] == (11, 17) and not left["stale"]
        page._edit_committed("c1", "前面 CHICHOO和别人")
        assert left["stale"] and not left["checked"]
        assert page.changed_values() == {"c1": "前面 CHICHOO和别人"} and page._stack.count() == 3
    finally:
        _close(page)


def test_suspected_names_with_a_candidate_are_recommended(tmp_path):
    """2026-10-10 (user): the library candidate is recommended; one click adopts it."""
    from twobyteasr.studio_glossary_service import GlossaryReviewPreview
    from twobyteasr.studio_project import load_project
    path = _save(tmp_path, "assoc", [("c1", 0, 2000, "嗯 然后古龙首发"), ("c2", 2000, 4000, "对刚刚的水灵"),
                                     ("c3", 4000, 6000, "哦 又是盾")])
    page = _page()
    try:
        page.open_task(str(path), load_project(path))
        assert _wait(page)
        live = page._live_project()[0]
        texts = {cue.id: cue.text for cue in live.cues}
        pending = [
            {"cue_id": "c1", "span": [4, 6], "state": "missing_alias_or_candidate", "canonical_options": ["骨龙"]},
            {"cue_id": "c2", "span": [1, 3], "state": "missing_alias_or_candidate", "canonical_options": []},
            {"cue_id": "c3", "span": [0, 4], "state": "missing_alias_or_candidate", "canonical_options": ["墨鱿士"]},
        ]
        page._show_result(GlossaryReviewPreview((), {"pending_rows": pending, "checked_cues": 3}), live, False, texts)
        [issue] = _row(page, "c1")["issues"]
        assert (issue["kind"], issue["replacement"], issue["checked"], issue["default"]) == ("association", "骨龙", False, True)
        assert _row(page, "c2")["issues"] == []  # 刚刚 is an ordinary word
        assert _row(page, "c3")["issues"] == []  # particles are not a name
        page._toggle_issue("c1", 0)
        assert live.cues[0].text == "嗯 然后骨龙首发"
    finally:
        _close(page)


def test_late_results_never_touch_a_caption_edited_meanwhile(tmp_path):
    from twobyteasr.studio_glossary_service import GlossaryReviewPreview
    from twobyteasr.studio_project import load_project
    from twobyteasr.studio_text_tools import TextOccurrence
    path = _save(tmp_path, "late", [("c1", 0, 2000, "而且CHIOCHOO能奶自己")])
    page = _page()
    try:
        page.open_task(str(path), load_project(path))
        assert _wait(page)
        live = page._live_project()[0]
        texts_at_run = {cue.id: cue.text for cue in live.cues}
        page._edit_committed("c1", "而且CHICHOO能奶自己")  # the user's own fix lands first
        late = TextOccurrence("c1", 0, "CHIOCHOO", "CHIOCH00", (2, 10), source="ai_accepted", default_selected=True)
        page._show_result(GlossaryReviewPreview((late,), {"checked_cues": 1}), live, True, texts_at_run)
        assert live.cues[0].text == "而且CHICHOO能奶自己"
        assert not any(issue["replacement"] == "CHIOCH00" for issue in _row(page, "c1")["issues"])
        assert "丢弃" in page.status_label.text()
    finally:
        _close(page)


def test_preview_is_requested_by_stable_caption_id(tmp_path, monkeypatch):
    from twobyteasr.studio_project import load_project
    path = _save(tmp_path, "play", [("b", 2000, 4000, "第二句"), ("a", 0, 2000, "第一句")])
    page = _page()
    calls = []
    monkeypatch.setattr(page._player, "play", lambda project, cue_id: calls.append((project.project_id, cue_id)))
    try:
        page.open_task(str(path), load_project(path))
        assert [row["cue_id"] for row in page._rows] == ["a", "b"]  # time order, not file order
        page.search.setText("第二")
        page._apply_filter()  # typing is debounced
        assert page.list.visible == [1]
        page._play("b")
        assert calls == [(page._project.project_id, "b")]
    finally:
        _close(page)


def test_conflicting_spellings_are_decided_per_project_without_touching_glossaries(tmp_path):
    import subtitle_core as legacy
    from twobyteasr.studio_project import load_project
    from twobyteasr.terminology import snapshot_glossaries
    first = _library("冲突甲", ("CHIOCHOO", "CHIOCHOO"), category="选手 ID")
    second = _library("冲突乙", ("CHICHOO", "CHICHOO"), ("CHIOCHOO", "CHICHOO"), category="选手 ID")
    path = _save(tmp_path, "conflict", [("c1", 0, 2000, "而且CHIOCHOO能奶自己")], glossary_ids=[first, second])
    before = snapshot_glossaries(legacy, [first, second]).digest
    page = _page()
    try:
        page.open_task(str(path), load_project(path))
        assert _wait(page)
        assert not any(row["issues"] for row in page._rows if any(i["kind"] == "term" for i in row["issues"]))
        assert not page.conflicts.isHidden()
        [row] = page._conflict_rows
        assert row["key"] == "chiochoo" and row["count"] == 1
        assert {option["target"]: option["library_ids"] for option in row["options"]} == {
            "CHICHOO": (second,), "CHIOCHOO": (first,)}
        assert "冲突待处理" in page.library_summary.text()
        page._conflict_chosen("chiochoo", (second, "CHICHOO"))
        assert _wait(page)
        page._set_all(True)
        page._flush_save()
        assert load_project(path).cues[0].text == "而且CHICHOO能奶自己"
        receipt = load_project(path).generation_metadata["glossary_review_jobs"][-1]
        assert receipt["spelling_choices"] == [{"key": "chiochoo", "library_id": second, "target": "CHICHOO",
                                                "scope": "project_proofreading"}]
        reopened = _page()
        try:
            reopened.open_task(str(path), load_project(path))
            assert _wait(reopened)
            assert reopened._conflict_choices == {"chiochoo": (second, "CHICHOO")}
        finally:
            _close(reopened)
        assert snapshot_glossaries(legacy, [first, second]).digest == before
    finally:
        _close(page)




def test_libraries_are_inherited_from_the_recognition_snapshot_by_id(tmp_path):
    from twobyteasr.studio_project import load_project
    identity = _library("继承词库", ("CHIOCHOO", "CHICHOO"))
    _library("另一个游戏", ("CHIOCHOO", "别的写法"))
    path = _save(tmp_path, "inherit", [("c1", 0, 2000, "而且CHIOCHOO能奶自己")],
                 snapshot={"libraries": [{"id": identity, "name": "继承词库", "revision": "older"}]})
    page = _page()
    try:
        page.open_task(str(path), load_project(path))
        assert page._selected_ids() == (identity,)
        assert "沿用本次识别的词库" in page.library_summary.text() and "识别后已更新" in page.library_summary.text()
        assert _wait(page)
        [issue] = _row(page, "c1")["issues"]
        assert (issue["kind"], issue["replacement"], issue["checked"], issue["default"]) == ("term", "CHICHOO", False, True)
        assert "本地，未使用 AI" in page.status_label.text()
        assert page.target_combo.currentData() == identity
    finally:
        _close(page)


def test_results_for_a_replaced_project_are_dropped(tmp_path):
    from twobyteasr.studio_project import load_project
    identity = _library("切换检查", ("CHIOCHOO", "CHICHOO"))
    first = _save(tmp_path, "first", [("c1", 0, 2000, "而且CHIOCHOO能奶自己")], glossary_ids=[identity])
    second = _save(tmp_path, "second", [("x1", 0, 2000, "完全不同的工程")])
    page = _page()
    try:
        page.open_task(str(first), load_project(first))  # local run starts
        page.open_task(str(second), load_project(second))  # switch before it lands
        assert _wait(page)
        assert [row["cue_id"] for row in page._rows] == ["x1"]
        assert not any(row["issues"] for row in page._rows) and not page.pending_values()
    finally:
        _close(page)


def test_rows_show_the_speaker_display_name(tmp_path):
    from twobyteasr.studio_project import (StudioCue, StudioMedia, StudioSpeaker, SubtitleProject,
                                           load_project, save_project)
    project = SubtitleProject(media=StudioMedia(path="", duration_ms=2000),
                              cues=[StudioCue("c1", 0, 2000, "还是在等autumn出结果", speaker_id="S01")],
                              speakers=[StudioSpeaker("S01", "主播")])
    path = tmp_path / "speaker.2byteproj"
    save_project(project, path)
    page = _page()
    try:
        page.open_task(str(path), load_project(path))
        assert _row(page, "c1")["speaker"][0] == "主播"  # never the raw identity key
    finally:
        _close(page)


def test_completion_title_pill_is_a_button_only_with_an_action():
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent
    from twobyteasr.completion_widgets import CompletionTitle
    title = CompletionTitle("字幕已生成 · 部分AI校对未完成")
    title.resize(900, 80)
    clicks = []
    title.qualifier_clicked.connect(lambda: clicks.append(1))

    def press():
        pill = title.pill_rect()
        point = QPointF(pill.center())
        title.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, point, point, Qt.MouseButton.LeftButton,
                                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))

    press()
    assert clicks == []  # a status label without an action
    plain = title.pill_rect().width()
    title.set_qualifier_action("去 AI 校对 ›", "tip")
    assert title.pill_rect().width() > plain  # the action is visible in the pill
    press()
    assert clicks == [1]


def test_completion_task_line_names_a_changed_project_count():
    from twobyteasr.completion_summary import completion_summary
    outcome = SimpleNamespace(final_cues=49, polish_status="completed", polish_label="", core_errors=(),
                              review_issue_count=0, search_label="")
    same = completion_summary({}, outcome, project_loaded=True, project_cues=49)
    assert "49 条字幕 · 字幕工程已保存并载入" in same.task_lines
    changed = completion_summary({}, outcome, project_loaded=True, project_cues=9)
    assert "识别产出 49 条字幕 · 工程当前 9 条 · 字幕工程已保存并载入" in changed.task_lines


def test_edit_button_opens_the_editor_and_ctrl_h_enter_replaces_the_whole_project(tmp_path):
    """2026-10-10 (user): no resident 全部替换; Ctrl+H, Enter in the replace box,
    Esc closes; an input method's Enter never replaces; empty means delete,
    which asks for a second Enter."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from twobyteasr.studio_project import load_project
    path = _save(tmp_path, "editbutton", [("c1", 0, 2000, "原石不够了"), ("c2", 2000, 4000, "再去抽卡吧"),
                                          ("c3", 4000, 6000, "抽卡和原石抽卡")])
    page = _page()
    try:
        page.resize(1400, 800)
        page.show()
        page.open_task(str(path), load_project(path))
        assert _wait(page)
        assert not hasattr(page, "replace_button")
        APP.processEvents()
        page.list.repaint()
        [box] = [rect for rect, action, cue_id, _ in page.list._hit_boxes if action == "edit" and cue_id == "c2"]
        text_end = max(rect.right() for rect, action, cue_id, _ in page.list._hit_boxes
                       if action == "text" and cue_id == "c2")
        assert box.left() < text_end + 40  # next to the sentence, not at the far edge
        QTest.mouseClick(page.list, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, box.center().toPoint())
        for _ in range(5):
            APP.processEvents()
        assert page.list.editor.isVisible() and page.list.editing() == "c2"
        page.list.cancel_edit()
        # Ctrl+H opens the bar; nothing depends on a shortcut having been used before.
        assert page.replace_bar.isHidden()
        page.replace_toggle.setChecked(True)
        page.search.setText("抽卡")
        page.replace_input.setText("祈愿")
        page._refresh_replace_count()
        assert "将替换 3 处（2 条字幕）" in page.replace_count.text() and "即全部字幕里的「抽卡」" in page.replace_count.text()
        # An input method composing (and its committing Enter) never replaces.
        page.replace_input.setFocus()
        composing = QInputMethodEvent("qiyuan", [])
        QApplication.sendEvent(page.replace_input, composing)
        QTest.keyClick(page.replace_input, Qt.Key.Key_Return)
        assert page._stack is None or page._stack.count() == 0
        commit = QInputMethodEvent("", [])
        commit.setCommitString("")
        QApplication.sendEvent(page.replace_input, commit)
        page._ime_commit_at = 0.0
        QTest.keyClick(page.replace_input, Qt.Key.Key_Return)
        assert [row["base"] for row in page._rows] == ["原石不够了", "再去祈愿吧", "祈愿和原石祈愿"]
        assert page._stack.count() == 1  # one undo step for the whole project
        page._undo()
        assert [row["base"] for row in page._rows] == ["原石不够了", "再去抽卡吧", "抽卡和原石抽卡"]
        # Empty replacement deletes: the first Enter only warns.
        page.replace_input.setText("")
        QTest.keyClick(page.replace_input, Qt.Key.Key_Return)
        assert "再按一次 Enter 确认删除" in page.replace_count.text() and page._stack.index() == 0
        QTest.keyClick(page.replace_input, Qt.Key.Key_Return)
        assert _row(page, "c3")["base"] == "和原石"
        # Same text or no hit: nothing happens.
        index = page._stack.index()
        page.search.setText("不存在")
        page.replace_input.setText("x")
        QTest.keyClick(page.replace_input, Qt.Key.Key_Return)
        assert page._stack.index() == index
        QTest.keyClick(page.replace_input, Qt.Key.Key_Escape)
        assert page.replace_bar.isHidden()
    finally:
        _close(page)


def test_right_click_offers_the_proposal_words_for_the_whole_project(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMenu
    from twobyteasr.studio_project import load_project
    identity = _library("右键词库", ("古龙", "骨龙"))
    path = _save(tmp_path, "context", [("c1", 0, 2000, "这里出现了一只古龙"), ("c2", 2000, 4000, "古龙又来了古龙"),
                                       ("c3", 4000, 6000, "古代的事")], glossary_ids=[identity])
    page = _page()
    shown = []
    monkeypatch.setattr(page, "_show_menu", lambda menu, *_a: shown.append([a.text() for a in menu.actions()]))
    assert QMenu is not None
    try:
        page.open_task(str(path), load_project(path))
        assert _wait(page)
        row = _row(page, "c1")
        index = next(i for i, issue in enumerate(row["issues"]) if issue["replacement"])
        page._context_menu("c1", ("mark", "c1", index), None)
        [labels] = shown
        assert "批量替换「古龙」→「骨龙」…（3 处，2 条字幕）" in labels
        assert not any("『古』" in label for label in labels)  # never the lone character
        page.replace_everywhere("古龙", "骨龙", operation="context_replace")
        assert [r["base"] for r in page._rows] == ["这里出现了一只骨龙", "骨龙又来了骨龙", "古代的事"]
        assert page._stack.count() == 1
        page._flush_save()
        assert [cue.text for cue in load_project(path).cues] == ["这里出现了一只骨龙", "骨龙又来了骨龙", "古代的事"]
    finally:
        _close(page)


def test_one_spelling_per_sound_follows_the_first_or_the_users_edit(tmp_path):
    """2026-10-10 (user): once 原石 is written, later 源石 should follow it."""
    from twobyteasr.studio_project import load_project
    path = _save(tmp_path, "consistency", [("c1", 0, 2000, "原石不够了"), ("c2", 2000, 4000, "再抽一次源石"),
                                           ("c3", 4000, 6000, "继续攻势"), ("c4", 6000, 8000, "这个公式"),
                                           ("c5", 8000, 9000, "嗯然后古龙首发"), ("c6", 9000, 9900, "古龙叔叔看")])
    page = _page()
    try:
        page.open_task(str(path), load_project(path))
        assert _wait(page)
        [issue] = _row(page, "c2")["issues"]
        assert (issue["kind"], issue["original"], issue["replacement"], issue["default"]) == (
            "consistency", "源石", "原石", True)
        assert _row(page, "c3")["issues"] == [] and _row(page, "c4")["issues"] == []  # 攻势/公式 are different words
        # The user's own spelling spreads to the other captions.
        page._edit_committed("c5", "嗯然后骨龙首发")
        page._local_timer.setInterval(0)
        page._local_timer.start(0)
        end = time.monotonic() + 10
        while time.monotonic() < end and not _row(page, "c6")["issues"]:
            APP.processEvents()
            time.sleep(0.02)
        assert _wait(page)
        [issue] = _row(page, "c6")["issues"]
        assert (issue["kind"], issue["original"], issue["replacement"], issue["default"]) == (
            "consistency", "古龙", "骨龙", True)
        page._set_all(True)
        assert [row["base"] for row in page._rows if row["cue_id"] in {"c2", "c6"}] == ["再抽一次原石", "骨龙叔叔看"]
    finally:
        _close(page)


def test_two_recognizers_readings_are_offered(tmp_path, monkeypatch):
    """2026-10-10 (user): FireRed and Qwen heard 今天运气站/在, the caption kept 天命之暗."""
    from types import SimpleNamespace
    import twobyteasr.studio_qc as studio_qc
    from twobyteasr.studio_project import load_project
    readings = {"c1": ("就是那个什么今天运气站我这边暴风雪", "就是那个什么今天运气在我这边暴风雪"),
                "c2": ("这个阵容上分好爽啊", "这个阵容上分好爽啊")}

    def evidence(project, cue, **_kw):
        if cue.id not in readings:
            return ()
        firered, qwen = readings[cue.id]
        return (SimpleNamespace(label="MOSS", text=cue.text), SimpleNamespace(label="FireRed", text=firered),
                SimpleNamespace(label="Qwen", text=qwen))

    monkeypatch.setattr(studio_qc, "model_evidence", evidence)
    path = _save(tmp_path, "evidence", [("c1", 0, 3000, "就是那个什么天命之暗我这边暴风雪"),
                                        ("c2", 3000, 5000, "这个阵容上风好爽啊")])
    page = _page()
    try:
        page.open_task(str(path), load_project(path))
        assert _wait(page)
        options = [(i["kind"], i["original"], i["replacement"], i["default"]) for i in _row(page, "c1")["issues"]]
        assert options == [("evidence", "天命之暗", "今天运气站", False), ("evidence", "天命之暗", "今天运气在", False)]
        [agreed] = _row(page, "c2")["issues"]
        assert (agreed["kind"], agreed["replacement"], agreed["default"]) == ("evidence", "分", True)
        page._toggle_issue("c1", 1)  # pick Qwen's reading
        assert _row(page, "c1")["base"] == "就是那个什么今天运气在我这边暴风雪"
        first, second = _row(page, "c1")["issues"]
        assert second["checked"] and not first["checked"]
    finally:
        _close(page)


def test_click_after_scroll_before_repaint_hits_the_row_now_under_the_mouse(tmp_path):
    """Hit boxes from the previous paint must not decide a click (busy UI)."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from twobyteasr.studio_project import load_project
    path = _save(tmp_path, "staleclick", [(f"c{i}", i * 2000, i * 2000 + 1500, f"第{i}句字幕内容") for i in range(60)])
    page = _page()
    try:
        page.resize(1200, 600)
        page.show()
        page.open_task(str(path), load_project(path))
        assert _wait(page)
        page.list.repaint()
        [box] = [rect for rect, action, cue_id, _ in page.list._hit_boxes if action == "play" and cue_id == "c0"]
        page.list.bar.setValue(page.list.offsets[10])  # scrolled; no paint yet
        played = []
        page.list.play_requested.connect(played.append)
        QTest.mouseClick(page.list, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, box.center().toPoint())
        assert played == ["c10"]
        page._player.stop()
    finally:
        _close(page)


def test_an_applied_spelling_is_followed_not_unified_back(tmp_path):
    """After a write the edit is the project's text; 骨龙 (changed from 古龙) still wins."""
    from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, load_project, save_project
    project = SubtitleProject(media=StudioMedia(path="", duration_ms=8000), cues=[
        StudioCue("c1", 0, 2000, "古龙来了", original_text="古龙来了"),
        StudioCue("c2", 2000, 4000, "骨龙首发", original_text="古龙首发")])
    path = tmp_path / "applied.2byteproj"
    save_project(project, path)
    page = _page()
    try:
        page.open_task(str(path), load_project(path))
        assert _wait(page)
        assert [(i["kind"], i["replacement"], i["default"]) for i in _row(page, "c1")["issues"]] == [
            ("consistency", "骨龙", True)]
        assert _row(page, "c2")["issues"] == []
    finally:
        _close(page)


def test_interface_zoom_scales_the_list_and_returns_exactly(tmp_path):
    from twobyteasr import ui_zoom
    from twobyteasr.studio_project import load_project
    path = _save(tmp_path, "zoom", [(f"c{i}", i * 1000, i * 1000 + 900, "非常尴尬的一幕还有古龙" * 3) for i in range(30)])
    page = _page()
    try:
        page.resize(1400, 800)
        page.show()
        page.open_task(str(path), load_project(path))
        assert _wait(page)
        heights = list(page.list.heights)
        button = page.local_button.minimumHeight()
        page.list.bar.setValue(page.list.offsets[12])
        anchor = page.list._top_anchor()[0]
        ui_zoom.set_zoom_percent(150)
        ui_zoom.apply_to(page)
        APP.processEvents()
        assert page.list.body.pixelSize() == round(19 * 1.5)
        assert sum(page.list.heights) > sum(heights) and page.local_button.minimumHeight() == round(button * 1.5)
        assert page.list._top_anchor()[0] == anchor  # the same caption stays at the top
        assert page.left_panel.width() <= page.width() * 0.34 + 1
        ui_zoom.set_zoom_percent(100)
        ui_zoom.apply_to(page)
        page.resize(1400, 800)  # a top-level page grows to its zoomed minimum; the main window does not
        APP.processEvents()
        assert page.list.heights == heights and page.local_button.minimumHeight() == button
    finally:
        from twobyteasr import ui_zoom as zoom
        zoom.set_zoom_percent(100)
        _close(page)


def test_mark_colors_read_on_every_theme():
    from twobyteasr.glossary_proofread import contrast, mark_colors
    from twobyteasr.ui_theme import THEMES
    for theme in THEMES.values():
        colors = mark_colors(theme)
        assert contrast(colors["error_text"], colors["error_fill"]) >= 4.5, theme.key
        assert contrast(colors["fix_text"], colors["fix_fill"]) >= 4.5, theme.key
        assert contrast(colors["applied_text"], colors["applied_fill"]) >= 4.5, theme.key
        assert contrast(colors["error_line"], theme.surface) >= 3.0, theme.key
        # Error and fix fills are told apart, not one tint near the background.
        assert colors["error_fill"] != colors["fix_fill"]


# --------------------------------------------------------------------------
# 2026-10-10 night (user, five screenshots): real differences only, one
# group per whole name, select text in search results and batch replace.
# --------------------------------------------------------------------------

def test_a_proposal_marks_and_describes_only_the_characters_that_change():
    from twobyteasr.glossary_proofread import change_summary, suggestion_marks, text_changes
    text = "击杀之后切到魔草巫灵坍缩"
    issue = dict(_issue(text, "巫", "乌", kind="evidence"))
    assert suggestion_marks(text, issue) == [(8, 9, "乌")]
    # The same one-character change found as a two-character word.
    wide = dict(_issue(text, "草巫", "草乌", kind="evidence"))
    assert suggestion_marks(text, wide) == [(8, 9, "乌")]
    assert change_summary("草巫", "草乌") == "巫 → 乌"
    cases = {
        ("古龙大师", "骨龙大使"): "古 → 骨，师 → 使",  # two changes in one sentence
        ("草灵", "草巫灵"): "加上「巫」",  # insertion
        ("这这次", "这次"): "删去「这」",  # deletion of a repeat
        ("哈哈哈哈", "哈哈"): "删去「哈哈」",  # repeated characters
        ("天黑黑", "天飞飞钥"): "黑黑 → 飞飞钥",  # unequal lengths
        ("BerLIN来了", "berlin来了"): "BerLIN → berlin",  # Latin names stay whole
        ("疫病吐息", "一命突袭"): "疫病吐息 → 一命突袭",
    }
    for (before, after), summary in cases.items():
        assert change_summary(before, after) == summary, (before, after)
        # Every reported change, applied, gives exactly the other text.
        rebuilt, last = "", 0
        for i1, i2, j1, j2 in text_changes(before, after):
            rebuilt += before[last:i1] + after[j1:j2]
            last = i2
        assert rebuilt + before[last:] == after
    # Two separate changes are two marks, each over its own characters.
    text = "这位古龙大师"
    issue = dict(_issue(text, "古龙大师", "骨龙大使"))
    assert suggestion_marks(text, issue) == [(2, 3, "骨"), (5, 6, "使")]


def _terms():
    from twobyteasr.glossary_proofread import TermIndex
    return TermIndex([("疫病吐息", "skill"), ("突袭", "skill"), ("魔草巫灵", "spirit"), ("布克棱岩", "spirit"),
                      ("CHIOCHOO", "选手 ID"), ("CHICHOO", "选手 ID")])


def test_proposals_inside_one_whole_name_are_one_group():
    from twobyteasr.glossary_proofread import issue_groups
    terms = _terms()
    # 疫病吐息 is one skill: 疫病 → 一命 (both recognizers) and 吐息 → 突袭 (near
    # sound) are one decision, asked (the library already spells the skill).
    text = "两层疫病吐息"
    row = dict(base=text, issues=[dict(_issue(text, "疫病", "一命", kind="evidence")),
                                  dict(_issue(text, "吐息", "突袭", kind="near"), default=False)])
    [group] = issue_groups(row, terms)
    assert group["parts"] == [0, 1] and group["name"] == "疫病吐息" and group["pending"]
    assert not group["recommended"] and group["after"] == "两层一命突袭"
    # Adopting only together writes a name of the library: one recommended group.
    text = "最好还是直接切到不可冷眼"
    row = dict(base=text, issues=[dict(_issue(text, "最好", "最号", kind="ai")),
                                  dict(_issue(text, "不可", "布克", kind="near")),
                                  dict(_issue(text, "冷眼", "棱岩", kind="near"))])
    first, second = issue_groups(row, terms)
    assert first["parts"] == [0]  # an unrelated neighbour stays on its own
    assert second["parts"] == [1, 2] and second["formed"] == "布克棱岩" and second["recommended"]
    # Readings of the same characters are options of one decision.
    text = "什么天命之暗我这边"
    row = dict(base=text, issues=[dict(_issue(text, "天命之暗", "今天运气站", kind="evidence"), default=False),
                                  dict(_issue(text, "天命之暗", "今天运气在", kind="evidence"), default=False)])
    [group] = issue_groups(row, terms)
    assert group["options"] and group["pending"] and group["after"] is None
    # A library spelling chosen over another library spelling is not "breaking a name".
    text = "而且CHIOCHOO能奶自己"
    row = dict(base=text, issues=[dict(_issue(text, "CHIOCHOO", "CHICHOO"))])
    [group] = issue_groups(row, terms)
    assert not group["pending"] and group["recommended"]
    # The wrong case of a name is not the name written right.
    text = "chiochoo来了"
    row = dict(base=text, issues=[dict(_issue(text, "chiochoo", "CHIOCHOO"))])
    [group] = issue_groups(row, terms)
    assert group["name"] == "" and group["recommended"]


def _grouped_page(tmp_path, cues):
    from twobyteasr.studio_project import load_project
    path = _save(tmp_path, "groups", cues)
    page = _page()
    page.resize(1400, 800)
    page.show()
    page.open_task(str(path), load_project(path))
    assert _wait(page)
    page._terms = page.list.terms = _terms()
    return page, path


def test_a_whole_name_is_adopted_ignored_and_undone_as_one(tmp_path):
    page, path = _grouped_page(tmp_path, [("c1", 0, 2000, "两层疫病吐息"), ("c2", 2000, 4000, "击杀之后切到魔草巫灵坍缩"),
                                          ("c3", 4000, 6000, "最好还是直接切到不可冷眼")])
    try:
        rows = {cue_id: _row(page, cue_id) for cue_id in ("c1", "c2", "c3")}
        rows["c1"]["issues"] = [dict(_issue("两层疫病吐息", "疫病", "一命", kind="evidence"), reason="FireRed 和 Qwen 都听成「一命」"),
                                dict(_issue("两层疫病吐息", "吐息", "突袭", kind="near"), default=False)]
        rows["c2"]["issues"] = [dict(_issue("击杀之后切到魔草巫灵坍缩", "巫", "乌", kind="evidence"))]
        rows["c3"]["issues"] = [dict(_issue("最好还是直接切到不可冷眼", "不可", "布克", kind="near")),
                                dict(_issue("最好还是直接切到不可冷眼", "冷眼", "棱岩", kind="near"))]
        page._apply_filter()
        page.list.repaint()
        counts = page.proposal_counts()
        assert (counts["proposals"], counts["asked"]) == (3, 2)  # three decisions, two need a look
        # One line per group: one adopt box for the whole skill name, no
        # reasons until 详情 is opened.
        boxes = [index for _rect, action, cue_id, index in page.list._hit_boxes if action == "check" and cue_id == "c1"]
        assert boxes == [0]
        layout = page.list._row_layout(rows["c1"])
        assert [kind for kind, _value in layout["entries"]] == ["group"]
        page.list.expanded.add(("c1", 0))
        page.list.refresh_row("c1")
        details = [value[1]["text"] for kind, value in page.list._row_layout(rows["c1"])["entries"] if kind == "detail"]
        assert any("FireRed 和 Qwen 都听成「一命」" in line and "疫病 → 一命" in line for line in details)
        assert any("「疫病吐息」是所选词库里的技能名" in line for line in details)
        # 采用全部 leaves the asked groups alone, adopts the whole formed name.
        page._set_all(True)
        assert [row["base"] for row in page._rows] == ["两层疫病吐息", "击杀之后切到魔草巫灵坍缩", "最好还是直接切到布克棱岩"]
        assert page._stack.count() == 1
        # One click on either part adopts the whole skill name, one undo step.
        page._toggle_issue("c1", 1)
        assert rows["c1"]["base"] == "两层一命突袭" and all(i["checked"] for i in rows["c1"]["issues"])
        assert page._stack.count() == 2 and "疫病吐息 → 一命突袭" in page._stack.undoText()
        page._toggle_issue("c1", 0)  # taking it back is whole too
        assert rows["c1"]["base"] == "两层疫病吐息"
        page._undo()
        assert rows["c1"]["base"] == "两层一命突袭"
        page._undo()
        assert rows["c1"]["base"] == "两层疫病吐息" and not any(i["checked"] for i in rows["c1"]["issues"])
        # 忽略 answers the group without touching the caption.
        index = page._stack.index()
        page._dismiss_group("c2", 0)
        assert rows["c2"]["base"] == "击杀之后切到魔草巫灵坍缩" and page._stack.index() == index
        # Both asked groups are answered now (疫病吐息 adopted and taken back, 巫 ignored).
        assert page.proposal_counts()["asked"] == 0 and page._groups(rows["c2"])[0]["reviewed"]
        page._flush_save()
        from twobyteasr.studio_project import load_project
        assert [cue.text for cue in load_project(path).cues] == ["两层疫病吐息", "击杀之后切到魔草巫灵坍缩", "最好还是直接切到布克棱岩"]
    finally:
        _close(page)


def _drag_select(page, cue_id, start, end):
    """Select caption characters [start, end) with a real mouse drag."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    page.list.ensure_visible(cue_id)
    page.list.repaint()
    [line, *_] = [entry for entry in page.list._chars[cue_id]
                  if any(start <= index < end for _a, _b, index in entry[3])]
    boxes = {index: (a, b) for a, b, index in line[3]}
    y = int((line[0] + line[1]) / 2)
    first = QPoint(int(boxes[start][0] + 1), y)
    last = QPoint(int(boxes[end - 1][1] - 1), y)
    QTest.mousePress(page.list, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, first)
    for step in range(1, 5):
        QTest.mouseMove(page.list, first + (last - first) * step / 4)
    QTest.mouseRelease(page.list, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, last)


def test_select_text_in_search_results_then_batch_replace_typing_only_the_new_word(tmp_path, monkeypatch):
    """Search 布克 → select 布克 in a caption → right click 批量替换相同文字 →
    type only the new word → see the scope → exclude one hit → Enter → one undo."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    cues = [(f"f{i}", i * 1000, i * 1000 + 900, f"第{i}句普通的话") for i in range(60)]
    cues[3] = ("c1", 3000, 3900, "最好还是直接切到布克棱岩")
    cues[7] = ("c2", 7000, 7900, "啊 磨完之后再切到布克棱岩")
    cues[55] = ("c3", 55000, 55900, "切到布克棱岩没有什么问题布克")  # far below the visible part
    page, path = _grouped_page(tmp_path, cues)
    shown = []
    monkeypatch.setattr(page, "_show_menu", lambda menu, *_a: shown.append(menu))
    played = []
    page.list.play_requested.connect(played.append)
    try:
        page.search.setText("布克")
        page._apply_filter()
        assert [page._rows[i]["cue_id"] for i in page.list.visible] == ["c1", "c2", "c3"]
        _drag_select(page, "c2", 9, 11)
        assert page.list.selection() == ("c2", 9, 11, "布克")
        assert not played and (page._stack is None or page._stack.count() == 0)  # a drag is not a click
        page.list.repaint()
        page._context_menu("c2", None, None)  # right click: the selection is kept
        assert page.list.selection() is not None
        [menu] = shown
        [batch] = [action for action in menu.actions() if action.text().startswith("批量替换相同文字「布克」")]
        assert "4 处，3 条字幕" in batch.text()
        batch.trigger()
        assert page.search.text() == "布克" and page.replace_bar.isVisible()
        assert QApplication.focusWidget() is page.replace_input or not page.isActiveWindow()
        assert [page._rows[i]["cue_id"] for i in page.list.visible] == ["c1", "c2", "c3"]  # results kept
        page.replace_input.insert("布可")  # typed (an input method commits whole words)
        page._refresh_replace_count()
        assert "将替换 4 处（3 条字幕）" in page.replace_count.text()
        # The hit list covers c3 although it was never painted on screen.
        assert set(page.replace_plan()["values"]) == {"c1", "c2", "c3"}
        page._toggle_hit("c3", 12)  # keep the second 布克 of c3
        page._refresh_replace_count()
        assert "将替换 3 处（3 条字幕）" in page.replace_count.text() and "已排除 1 处" in page.replace_count.text()
        QTest.keyClick(page.replace_input, Qt.Key.Key_Return)
        assert [_row(page, c)["base"] for c in ("c1", "c2", "c3")] == [
            "最好还是直接切到布可棱岩", "啊 磨完之后再切到布可棱岩", "切到布可棱岩没有什么问题布克"]
        assert page._stack.count() == 1
        # The search result does not vanish: replaced captions stay listed.
        assert {"c1", "c2", "c3"} <= {page._rows[i]["cue_id"] for i in page.list.visible}
        page._undo()
        assert [_row(page, c)["base"] for c in ("c1", "c2", "c3")] == [
            "最好还是直接切到布克棱岩", "啊 磨完之后再切到布克棱岩", "切到布克棱岩没有什么问题布克"]
        assert all(_row(page, f"f{i}")["base"] == f"第{i}句普通的话" for i in (0, 10, 59))
    finally:
        _close(page)


def test_replacing_in_a_filtered_list_never_reaches_unlisted_captions(tmp_path):
    from twobyteasr.studio_project import load_project
    page, path = _grouped_page(tmp_path, [("c1", 0, 2000, "抽卡抽卡"), ("c2", 2000, 4000, "再去抽卡吧"),
                                          ("c3", 4000, 6000, "抽卡和原石")])
    try:
        page._write({"c2": "再去抽卡吧！"}, label="改一句", manual=True)
        page.filter_buttons["changed"].click()
        page.start_batch_replace("抽卡", "祈愿")
        assert [page._rows[i]["cue_id"] for i in page.list.visible] == ["c2"]
        plan = page.replace_plan()
        assert (plan["hits"], plan["outside"]) == (1, 3) and set(plan["values"]) == {"c2"}
        assert "列表以外的 3 处不改" in page.replace_count.text()
        page._replace_enter()
        assert [row["base"] for row in page._rows] == ["抽卡抽卡", "再去祈愿吧！", "抽卡和原石"]
        # The whole project is an explicit choice.
        page.replace_scope.setCurrentIndex(page.replace_scope.findData("project"))
        page._replace_enter()
        assert [row["base"] for row in page._rows] == ["祈愿祈愿", "再去祈愿吧！", "祈愿和原石"]
        # Literal text: punctuation is never a pattern, the case typed is kept.
        page.start_batch_replace("！", "?")
        page.replace_scope.setCurrentIndex(page.replace_scope.findData("project"))
        page._replace_enter()
        assert _row(page, "c2")["base"] == "再去祈愿吧?"
        page._flush_save()
        assert [cue.text for cue in load_project(path).cues] == ["祈愿祈愿", "再去祈愿吧?", "祈愿和原石"]
        # Timing is untouched by text replacement.
        assert [(cue.start_ms, cue.end_ms) for cue in load_project(path).cues] == [(0, 2000), (2000, 4000), (4000, 6000)]
    finally:
        _close(page)


def test_a_click_on_a_mark_adopts_but_a_drag_over_it_only_selects(tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    page, path = _grouped_page(tmp_path, [("c1", 0, 2000, "这里出现了一只古龙")])
    try:
        row = _row(page, "c1")
        row["issues"] = [dict(_issue(row["base"], "古龙", "骨龙"))]
        page._apply_filter()
        _drag_select(page, "c1", 5, 8)
        assert page.list.selection() == ("c1", 5, 8, "一只古") and row["base"] == "这里出现了一只古龙"
        # Only the caption's own characters can be selected, never the 骨 under 古.
        assert all(index < len(row["base"]) for line in page.list._chars["c1"] for _a, _b, index in line[3])
        page.list.repaint()
        [mark] = [rect for rect, action, cue_id, _ in page.list._hit_boxes if action == "mark" and cue_id == "c1"
                  and rect.top() < page.list._chars["c1"][0][1]]
        QTest.mouseClick(page.list, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, mark.center().toPoint())
        assert row["base"] == "这里出现了一只骨龙" and page.list.selection() is None
    finally:
        _close(page)


def test_unsaved_proofreading_is_never_dropped_when_the_save_fails(tmp_path, monkeypatch):
    import twobyteasr.studio_project as storage
    from twobyteasr.studio_project import load_project
    page, path = _grouped_page(tmp_path, [("c1", 0, 2000, "原来的字幕")])
    real_save = storage.save_project
    failing = {"on": True}

    def save(project, target, *a, **k):
        if failing["on"]:
            raise OSError("磁盘已满")
        return real_save(project, target, *a, **k)

    monkeypatch.setattr(storage, "save_project", save)
    answers = []

    def answer(box):
        answers.append(box.text())
        [retry] = [button for button in box.buttons() if button.text() == "重试保存"]
        [stay] = [button for button in box.buttons() if button.text() == "留在校对页"]
        (stay if failing["on"] else retry).click()

    monkeypatch.setattr(page, "_show_message", answer)
    left = []
    page.back_requested.connect(lambda: left.append(True))
    try:
        page._write({"c1": "校对后的字幕"}, label="改一句", manual=True)
        page._back()  # the save fails: stay, say so, keep the edit
        assert not left and answers and "磁盘已满" in answers[-1]
        assert _row(page, "c1")["base"] == "校对后的字幕"
        assert load_project(path).cues[0].text == "原来的字幕"
        failing["on"] = False  # the user retries and it works
        page._back()
        assert left and load_project(path).cues[0].text == "校对后的字幕"
    finally:
        monkeypatch.setattr(storage, "save_project", real_save)
        _close(page)


def test_leaving_by_another_page_writes_the_file_first(tmp_path):
    from twobyteasr.studio_project import load_project
    page, path = _grouped_page(tmp_path, [("c1", 0, 2000, "原来的字幕")])
    try:
        page._write({"c1": "校对后的字幕"}, label="改一句", manual=True)
        assert page._save_timer.isActive()
        page.hide()  # e.g. the header's 字幕工作台
        assert load_project(path).cues[0].text == "校对后的字幕"
    finally:
        _close(page)


def test_flush_save_never_reports_a_still_running_save_as_written():
    """A save slower than the wait (slow/network drive) used to be dropped and
    reported as written, so Studio could load and later overwrite the older
    file. The page now keeps the thread and says the file is still written."""
    from twobyteasr.glossary_proofread import GlossaryProofreadPage

    class SlowThread:
        def __init__(self):
            self.waits = 0

        def wait(self, _ms):
            self.waits += 1
            return False

    thread = SlowThread()
    page = SimpleNamespace(_save_timer=SimpleNamespace(isActive=lambda: False), _save_thread=thread,
                           _save_again=False, _save_error="", _save_now=lambda: None)
    assert GlossaryProofreadPage._flush_save(page) is False
    assert page._save_thread is thread and thread.waits == 1
    assert page._save_error
