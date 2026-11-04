"""2026-10-15: manual Studio fixes saved into the project's glossary.

Only name-like fixes are written (an alias of an applied glossary term, or a
clean new name); pronoun flips and ordinary words stay out; undo removes the
rows a save added. The learned-terms file is redirected to tmp."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import subtitle_core as legacy
from twobyteasr.glossary import glossary_autosave as autosave
from twobyteasr.glossary.glossary_learning import GlossaryLearningStore, extract_term_replacements


@pytest.fixture
def learned(tmp_path, monkeypatch):
    path = tmp_path / "learned_game_terms.json"
    monkeypatch.setattr(legacy, "LEARNED_TERMS_PATH", str(path))
    return path


def _library(name, *terms):
    identity = legacy.create_learned_content(name, create_new=True)
    for term in terms:
        legacy.add_learned_mapping(identity, term, term, category="角色", origin="手动")
    return identity


def _rows(identity):
    return autosave._mapping_keys(legacy, identity)


@pytest.mark.parametrize("before, after, expected", [
    ("这把用福宁娜", "这把用芙宁娜", [("福宁娜", "芙宁娜")]),
    ("星见鸦很强", "星见雅很强", [("星见鸦", "星见雅")]),
    ("那个阿贝朵真强", "那个阿贝多真强", [("阿贝朵", "阿贝多")]),
    ("今天打迪路克的时候", "今天打迪卢克的时候", [("迪路克", "迪卢克")]),
    ("所以他就走了", "所以她就走了", []),       # a pronoun is never a term
    ("他老是迟到", "他老师迟到", []),           # 老是 is ordinary language
    ("我们在来一次", "我们再来一次", []),
    ("我用的是暗排", "我用的是安排", []),       # 安排 is an ordinary word
    ("那维来特很强", "那维莱特很强", []),       # unclear name edges: left for the user
])
def test_only_clean_name_fixes_are_saved_without_asking(before, after, expected):
    assert autosave.autosave_pairs(before, after) == expected


def test_a_term_of_the_applied_glossary_anchors_its_misheard_form():
    terms = ("那维莱特", "至冬国")
    assert autosave.autosave_pairs("那维来特很强", "那维莱特很强", canonical_terms=terms) == [("那维来特", "那维莱特")]
    assert autosave.autosave_pairs("我们去至东国", "我们去至冬国", canonical_terms=terms) == [("至东国", "至冬国")]
    assert autosave.autosave_pairs("所以他就走了", "所以她就走了", canonical_terms=("所以她",)) == []


def test_explicit_find_replace_pair_is_taken_as_typed_but_not_ordinary_words():
    assert autosave.autosave_pairs("布克", "布偶", explicit=True) == [("布克", "布偶")]
    assert autosave.autosave_pairs("老是", "老师", explicit=True) == []


def test_learning_never_offers_a_pronoun_flip():
    assert extract_term_replacements("所以他就走了", "所以她就走了") == []
    assert extract_term_replacements("他是星见鸦", "她是星见雅") == [("星见鸦", "星见雅")]


def test_save_goes_to_the_library_owning_the_term_and_undo_removes_only_new_rows(learned):
    genshin = _library("原神", "芙宁娜")
    other = _library("另一个游戏", "别的名字")
    snapshot, terms = autosave.applied_terms([other, genshin])
    assert "芙宁娜" in terms
    result = autosave.remember(snapshot, "福宁娜", "芙宁娜")
    assert (result.status, result.library_id) == (autosave.SAVED, genshin)
    assert result.added == [("福宁娜", "芙宁娜")]           # the canonical row already existed
    assert ("福宁娜", "芙宁娜") in _rows(genshin) and ("福宁娜", "芙宁娜") not in _rows(other)
    assert autosave.forget(result) == 1
    assert ("福宁娜", "芙宁娜") not in _rows(genshin) and ("芙宁娜", "芙宁娜") in _rows(genshin)


def test_new_name_with_one_library_adds_canonical_and_alias(learned):
    only = _library("星穹铁道")
    snapshot, _terms = autosave.applied_terms([only])
    result = autosave.remember(snapshot, "星见鸦", "星见雅")
    assert result.status == autosave.SAVED
    assert sorted(result.added) == [("星见雅", "星见雅"), ("星见鸦", "星见雅")]
    autosave.forget(result)
    assert _rows(only) == set()


def test_several_libraries_without_an_owner_are_not_guessed(learned):
    first, second = _library("游戏甲"), _library("游戏乙")
    snapshot, _terms = autosave.applied_terms([first, second])
    result = autosave.remember(snapshot, "星见鸦", "星见雅")
    assert result.status == autosave.AMBIGUOUS and not result.added
    assert _rows(first) == set() and _rows(second) == set()


def test_existing_alias_conflict_keeps_the_users_mapping(learned):
    library = _library("原神", "芙宁娜")
    legacy.add_learned_mapping(library, "福宁娜", "芙宁娜", origin="手动")
    snapshot, _terms = autosave.applied_terms([library])
    result = autosave.remember(snapshot, "福宁娜", "芙宁娜")
    assert result.status == autosave.EXISTS and result.added == []


def test_auto_saved_learning_entry_disappears_with_its_evidence(tmp_path):
    store = GlossaryLearningStore(tmp_path / "learning.json")
    store.record_manual_edit("星见鸦很强", "星见雅很强", origin="user_edit", token="ev-1")
    assert store.mark_auto_saved("星见鸦", "星见雅", "lib")
    assert store.pending() == []
    assert store.revert_evidence_tokens(["ev-1"]) == ["ev-1"]
    assert store.load()["candidates"] == []


# the real Studio page ------------------------------------------------------------
def test_studio_manual_fix_is_saved_and_undo_removes_it(tmp_path, monkeypatch, learned):
    from tests.test_studio_cue_controller import _finish, _page
    library = _library("原神", "芙宁娜")
    page = _page(tmp_path, monkeypatch)
    try:
        page.project.glossary_ids = [library]
        page._cue_lookup["a"].text = "这把用福宁娜"
        page._manual_text_baselines["a"] = "这把用福宁娜"
        page.undo_stack.clear()
        page.cue_controller.set_text("a", "这把用芙宁娜")
        page.cue_controller.commit_manual_term_learning("a")
        assert ("福宁娜", "芙宁娜") in _rows(library)
        assert "原神" in page.save_state.text() and "福宁娜" in page.save_state.text()
        assert page._learning_store.pending() == []          # saved, not waiting
        page.undo_stack.undo()
        assert ("福宁娜", "芙宁娜") not in _rows(library)
        assert ("芙宁娜", "芙宁娜") in _rows(library)
    finally:
        _finish(page)


def test_studio_pronoun_flip_and_projects_without_glossary_write_nothing(tmp_path, monkeypatch, learned):
    from tests.test_studio_cue_controller import _finish, _page
    library = _library("原神", "芙宁娜")
    page = _page(tmp_path, monkeypatch)
    try:
        page.project.glossary_ids = [library]
        page._cue_lookup["a"].text = "所以他就走了"
        page._manual_text_baselines["a"] = "所以他就走了"
        page.cue_controller.set_text("a", "所以她就走了")
        page.cue_controller.commit_manual_term_learning("a")
        page.project.glossary_ids = []
        page._cue_lookup["b"].text = "这把用福宁娜"
        page._manual_text_baselines["b"] = "这把用福宁娜"
        page.select_cue("b")
        page.cue_controller.set_text("b", "这把用芙宁娜")
        page.cue_controller.commit_manual_term_learning("b")
        assert _rows(library) == {("芙宁娜", "芙宁娜")}
    finally:
        _finish(page)
