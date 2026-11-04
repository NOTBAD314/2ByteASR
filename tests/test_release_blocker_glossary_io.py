"""D01 fault injection at the real storage boundary (not a mock add API)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtWidgets import QApplication, QWidget
import subtitle_core as legacy
from twobyteasr.glossary import glossary_skill as gs
from twobyteasr.glossary import glossary_skill_ui as ui

APP = QApplication.instance() or QApplication([])

@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, "LEARNED_TERMS_PATH", str(tmp_path / "learned.json"))
    monkeypatch.setattr(gs, "update_history_path", lambda: tmp_path / "history.json")

def diff(term="好词", aliases=()):
    return gs.TermDiff("new", gs.SearchedTerm(term=term), suggested_aliases=aliases)

@pytest.mark.parametrize("error", [PermissionError("locked"), OSError(28, "disk full")])
def test_real_storage_raises_instead_of_duplicate(monkeypatch, error):
    monkeypatch.setattr(legacy, "atomic_write_json", lambda *a: (_ for _ in ()).throw(error))
    with pytest.raises(OSError): legacy.add_learned_mapping("测试", "词", "词")
    result = gs.apply_term_updates(legacy, "测试", [diff()])
    assert (result["added"], result["duplicates"], result["failed"]) == (0, 0, 1)

def test_alias_failure_preserves_success_and_retries_only_missing(monkeypatch):
    real = legacy.atomic_write_json
    calls = 0
    def flaky(path, payload):
        nonlocal calls
        calls += 1
        if calls == 2: raise PermissionError("alias locked")
        real(path, payload)
    monkeypatch.setattr(legacy, "atomic_write_json", flaky)
    selection = [diff(aliases=("别称",)), diff("另一词")]
    first = gs.apply_term_updates(legacy, "测试", selection)
    assert (first["added"], first["failed"], first["duplicates"]) == (2, 1, 0)
    assert first["failed_keys"] == [["别称", "好词"]]
    assert len(gs.load_update_sessions("测试")) == 1
    retry = gs.apply_term_updates(legacy, "测试", selection)
    assert (retry["added"], retry["failed"], retry["duplicates"]) == (1, 0, 2)
    assert legacy.add_learned_mapping("测试", "别称", "好词") is False

def test_history_failure_preserves_old_bytes_and_reports_separately(tmp_path, monkeypatch):
    import twobyteasr.recognition.cache as cache
    path = tmp_path / "history.json"
    path.write_text('{"sessions": []}', encoding="utf8")
    before = path.read_bytes()
    monkeypatch.setattr(cache, "atomic_write_json", lambda *a: (_ for _ in ()).throw(PermissionError("history locked")))
    result = gs.apply_term_updates(legacy, "测试", [diff()])
    assert result["added"] == 1 and result["failed"] == 0
    assert result["history_saved"] is False
    assert result["history_error"]
    assert path.read_bytes() == before

def test_corrupt_existing_store_is_not_overwritten(tmp_path):
    path = tmp_path / "learned.json"
    path.write_bytes(b'{broken old data')
    with pytest.raises((ValueError, OSError)):
        legacy.add_learned_mapping("测试", "新词", "新词")
    assert path.read_bytes() == b'{broken old data'

def test_review_keeps_failed_candidates_and_cancel_does_not_write(monkeypatch, tmp_path):
    owner = QWidget()
    owner.legacy = legacy
    dialog = ui.GlossaryUpdateReviewDialog(owner, "测试", {"diffs": [diff("甲"), diff("乙")]})
    closed = []
    monkeypatch.setattr(dialog, "_close", lambda: closed.append(True))
    real = legacy.atomic_write_json
    monkeypatch.setattr(legacy, "atomic_write_json", lambda *a: (_ for _ in ()).throw(PermissionError("locked")))
    dialog._apply()
    assert not closed
    assert len(dialog.model.checked_diffs()) == 2
    assert "失败" in dialog.detail.text()
    monkeypatch.setattr(legacy, "atomic_write_json", real)
    dialog._apply()
    assert closed == [True]
    before = (tmp_path / "learned.json").read_bytes()
    dialog._close()
    assert (tmp_path / "learned.json").read_bytes() == before
    owner.deleteLater()

def test_batch_reports_actual_applied_and_cancel_stops_next_game(monkeypatch):
    monkeypatch.setattr(ui, "run_term_search", lambda *a, **k: {"diffs": [diff()]})
    monkeypatch.setattr(legacy, "atomic_write_json", lambda *a: (_ for _ in ()).throw(PermissionError("locked")))
    worker = ui.BatchGlossaryUpdateWorker(legacy, ["甲游戏", "乙游戏"], {})
    results, summaries = [], []
    def got(game, result):
        results.append(result)
        worker.cancel()
    worker.game_diff.connect(got)
    worker.queue_finished.connect(summaries.append)
    worker.run()
    assert len(results) == 1
    assert results[0]["auto_applied"] == 0
    assert results[0]["auto_session"]["failed"] == 1
    assert summaries[0]["skipped"] == 1
    assert summaries[0]["done"] == 0 and summaries[0]["failed"] == 1

def test_failed_retry_preserves_explicit_selection(monkeypatch):
    owner = QWidget(); owner.legacy = legacy
    excluded = diff("排除")
    selected = diff("选择"); selected.checked_by_default = False
    dialog = ui.GlossaryUpdateReviewDialog(owner, "测试", {"diffs": [excluded, selected]})
    dialog.model.check_none()
    dialog.model.check_rows([row for row in range(dialog.model.rowCount()) if dialog.model.row_diff(row).term.term == '选择'], True)
    monkeypatch.setattr(legacy, "atomic_write_json", lambda *a: (_ for _ in ()).throw(PermissionError("locked")))
    dialog._apply()
    assert [d.term.term for d in dialog.model.checked_diffs()] == ["选择"]
    owner.deleteLater()

def test_bad_history_structure_not_reported_saved(tmp_path):
    path = tmp_path / "history.json"; path.write_text('{"sessions": {}}')
    before = path.read_bytes()
    result = gs.apply_term_updates(legacy, "测试", [diff()])
    assert result["history_saved"] is False
    assert path.read_bytes() == before

def test_batch_retains_review_data_and_stable_game_identity():
    from PySide6.QtCore import Qt
    owner = QWidget(); owner.legacy = legacy
    dialog = ui.BatchUpdateDialog(owner, ["游戏甲"], lambda: {})
    dialog._done = 0
    dialog.list.item(0).setCheckState(Qt.CheckState.Checked)
    result = {"diffs": [diff("失败词")], "auto_applied": 3,
              "auto_session": {"added": 3, "failed": 1, "failed_keys": [["失败词", "失败词"]]}}
    dialog._on_game_diff("游戏甲", result)
    assert dialog._selected_games() == ["游戏甲"]
    assert dialog._review_results["游戏甲"] == result
    assert "失败 1" in dialog.list.item(0).text()
    owner.deleteLater()
