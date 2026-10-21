"""Studio manual edits → glossary learning candidates (typing, search & replace,
undo/redo, origin filtering). Uses the real SubtitleStudioPage like
test_studio_cue_controller, with an isolated LOCALAPPDATA."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.studio.studio_find_replace import replace_all, replace_next
from twobyteasr.timeline.studio_commands import MutationOrigin
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from tests.test_studio_cue_controller import _finish, _page


def _seed_text(page, cue_id: str, text: str):
    """Put a stable starting text in place directly (test fixture seeding)."""
    page._cue_lookup[cue_id].text = text
    page._manual_text_baselines[cue_id] = text
    page.undo_stack.clear()


def _only_candidate(page):
    pending = page._learning_store.pending()
    assert len(pending) == 1
    return pending[0]


def test_typing_correction_records_pending_then_undo_removes_and_redo_restores(tmp_path, monkeypatch):
    page = _page(tmp_path, monkeypatch)
    store = page._learning_store
    _seed_text(page, "a", "那维来特最强辅助")

    page.cue_controller.set_text("a", "那维莱特最强辅助")
    page.cue_controller.commit_manual_term_learning("a")
    candidate = _only_candidate(page)
    assert (candidate["original_term"], candidate["corrected_term"]) == ("那维来特", "那维莱特")
    assert candidate["origin"] == "user_edit"
    assert candidate["occurrence_count"] == 1

    # 撤销整条打字链 → 候选证据回退（不残留幽灵候选）
    page.undo_stack.undo()
    assert store.pending() == []
    assert page._cue_lookup["a"].text == "那维来特最强辅助"

    # 重做 → 重新提交后回到 1（不重复累计）
    page.undo_stack.redo()
    page.cue_controller.commit_manual_term_learning("a")
    candidate = _only_candidate(page)
    assert candidate["occurrence_count"] == 1
    _finish(page)


def test_two_independent_chains_undo_keeps_other_evidence(tmp_path, monkeypatch):
    page = _page(tmp_path, monkeypatch)
    store = page._learning_store
    _seed_text(page, "a", "那维来特登场")
    _seed_text(page, "b", "星见鸦很强")

    page.cue_controller.set_text("a", "那维莱特登场")
    page.cue_controller.commit_manual_term_learning("a")
    page.cue_controller.set_text("a", "那维莱特登场了")  # 同链继续，不产生新候选
    page.cue_controller.commit_manual_term_learning("a")
    page.select_cue("b")
    page.cue_controller.set_text("b", "星见雅很强")
    page.cue_controller.commit_manual_term_learning("b")
    candidates = {(item["original_term"], item["corrected_term"]): item for item in store.pending()}
    assert set(candidates) == {("那维来特", "那维莱特"), ("星见鸦", "星见雅")}
    assert all(item["occurrence_count"] == 1 for item in candidates.values())

    # 只撤销 b 的修改，a 的证据保留
    page.undo_stack.undo()
    pending = store.pending()
    assert [(item["original_term"], item["corrected_term"]) for item in pending] == [
        ("那维来特", "那维莱特")
    ]
    _finish(page)


def test_search_replace_records_origin_and_undo_reverts(tmp_path, monkeypatch):
    page = _page(tmp_path, monkeypatch)
    _seed_text(page, "a", "星见鸦今天打了几把排位")

    total, cues = replace_all(page, needle="星见鸦", replacement="星见雅", scope="all")
    assert total == 1 and cues == 1
    candidate = _only_candidate(page)
    assert candidate["origin"] == "search_replace"
    assert (candidate["original_term"], candidate["corrected_term"]) == ("星见鸦", "星见雅")

    page.undo_stack.undo()
    assert page._learning_store.pending() == []
    assert page._cue_lookup["a"].text == "星见鸦今天打了几把排位"
    page.undo_stack.redo()
    candidate = _only_candidate(page)
    assert candidate["occurrence_count"] == 1  # redo 幂等
    _finish(page)


def test_replace_next_learns_and_single_char_replacement_is_skipped(tmp_path, monkeypatch):
    page = _page(tmp_path, monkeypatch)
    _seed_text(page, "a", "尼奈说她很强")

    ok = replace_next(page, needle="尼奈", replacement="妮奈", scope="all")
    assert ok
    candidate = _only_candidate(page)
    assert (candidate["original_term"], candidate["corrected_term"]) == ("尼奈", "妮奈")
    assert candidate["origin"] == "search_replace"

    # 单字替换（她→他）不构成术语证据
    page.undo_stack.clear()
    replace_next(page, needle="她", replacement="他", scope="all")
    assert len(page._learning_store.pending()) == 1  # 仍然只有上一条
    _finish(page)


def test_ai_and_safe_fix_origins_never_become_manual_candidates(tmp_path, monkeypatch):
    page = _page(tmp_path, monkeypatch)
    store = page._learning_store
    _seed_text(page, "a", "那维来特来了")
    page.cue_controller.set_text("a", "那维莱特来了", origin=MutationOrigin.SAFE_FIX)
    page.cue_controller.commit_manual_term_learning("a")
    page.cue_controller.set_text("a", "那维莱特来了！", origin=MutationOrigin.LLM)
    page.cue_controller.commit_manual_term_learning("a")
    assert store.pending() == []
    _finish(page)


def test_reopen_project_does_not_recount(tmp_path, monkeypatch):
    page = _page(tmp_path, monkeypatch)
    _seed_text(page, "a", "那维来特登场")
    page.cue_controller.set_text("a", "那维莱特登场")
    page.cue_controller.commit_manual_term_learning("a")
    # 模拟重新播种基线后重复刷新（autosave / 重开工程路径不再产生新证据）
    page._manual_text_baselines["a"] = page._cue_lookup["a"].text
    page.cue_controller.commit_manual_term_learning("a")
    page.cue_controller.commit_manual_term_learning("a")
    candidate = _only_candidate(page)
    assert candidate["occurrence_count"] == 1
    _finish(page)
