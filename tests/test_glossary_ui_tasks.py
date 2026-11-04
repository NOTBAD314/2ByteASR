"""VII 轮 UI 层：任务按钮语义（截图问题1回归）、任务栏、预览模型、主表引号去重。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

import subtitle_core as legacy
from twobyteasr.glossary import glossary_build as gbuild
from twobyteasr.glossary import glossary_task_manager as gtm
from twobyteasr.glossary.glossary_skill import SearchedTerm, TermDiff


def _app():
    return QApplication.instance() or QApplication([])


class _FakeGameBox:
    def currentText(self):
        return ""


class _FakeOwner(QWidget):
    def __init__(self):
        super().__init__()
        self.legacy = legacy
        self.game_box = _FakeGameBox()

    def _enabled_glossary_ids(self):
        return []

    def _save_glossary_settings(self):
        pass


@pytest.fixture()
def dialog(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(legacy, "LEARNED_TERMS_PATH", str(tmp_path / "learned.json"))
    gtm.GlossaryUpdateManager.reset()
    from twobyteasr.glossary.main_ui_glossary import TermLibraryDialog

    owner = _FakeOwner()
    dlg = TermLibraryDialog(owner, page_mode=True)
    yield dlg
    dlg._task_manager and dlg._task_manager.shutdown(wait_ms=300)
    gtm.GlossaryUpdateManager.reset()
    dlg.deleteLater()


def _stub_engine(monkeypatch, gate=None):
    def fake(legacy_, game, settings, *, report=None, cancel_check=None, resume=None,
             checkpoint_writer=None, on_candidates=None, on_event=None):
        if report is not None:
            report("分批整理", "批次 1/3", {"batch_done": 1, "batch_total": 3, "candidates": 12})
        if on_candidates is not None:
            on_candidates([SearchedTerm(term="青衣", category="角色", category_key="character")])
        if gate is not None:
            gate.wait(timeout=5)
        return {"diffs": [], "candidate_count": 12, "mode": "full"}

    monkeypatch.setattr(gbuild, "run_full_library_update", fake)


def _spin(app, condition, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    app.processEvents()
    return condition()


# ---------------------------------------------------------------- 截图问题 1 回归

def test_switching_game_keeps_task_visible_and_button_semantic(dialog, monkeypatch):
    """运行中任务：切到其它游戏 → 任务栏仍显示该任务；任务游戏按钮=更新中；其它游戏可发起。"""
    import threading

    app = _app()
    gate = threading.Event()
    _stub_engine(monkeypatch, gate=gate)

    dialog.state["game"] = "绝区零"
    manager = dialog._ensure_task_manager()
    task_id, created = manager.submit("绝区零", "full", {})
    assert created
    assert _spin(app, lambda: manager.get(task_id).status == "running")
    dialog._on_task_structure_changed()

    # 任务栏可见且指向任务游戏（offscreen 父窗口未 show，用"未显式隐藏"判定）
    strip = dialog.ai_task_strip
    assert strip is not None and not strip.isHidden()
    assert "绝区零" in strip._rows[task_id]["title"].text()
    assert "完整建库" in strip._rows[task_id]["title"].text()
    assert _spin(app, lambda: "批次 1/3" in strip._rows[task_id]["progress"].text())
    progress_text = strip._rows[task_id]["progress"].text()
    assert "批次 1/3" in progress_text

    # 该游戏按钮语义切换
    dialog._refresh_ai_update_buttons()
    assert dialog.ai_full_button.text() == "更新中（查看任务）"

    # 切到其它游戏：老 bug 是按钮无条件重亮且无任务可见——现在按钮仍可发起（排队语义）
    dialog.state["game"] = "原神"
    dialog._refresh_ai_update_buttons()
    assert dialog.ai_full_button.text() == "AI 完整建库"
    assert dialog.ai_full_button.isEnabled()
    assert dialog.ai_update_button.isEnabled()
    # 任务栏不因切游戏消失
    assert (not strip.isHidden()) and task_id in strip._rows

    gate.set()
    assert _spin(app, lambda: manager.get(task_id).status == "finished")


def test_pending_other_mode_button_semantic(dialog, monkeypatch):
    import threading

    app = _app()
    gate = threading.Event()
    _stub_engine(monkeypatch, gate=gate)
    dialog.state["game"] = "绝区零"
    manager = dialog._ensure_task_manager()
    task_id, _ = manager.submit("绝区零", "full", {})
    assert _spin(app, lambda: manager.get(task_id).status == "running")
    dialog._refresh_ai_update_buttons()
    # full 在跑：增量按钮保持原语义可点
    assert dialog.ai_update_button.text() == "日常增量更新"
    assert dialog.ai_update_button.isEnabled()
    gate.set()
    assert _spin(app, lambda: manager.get(task_id).status == "finished")


def test_direct_complete_button_without_native_search_freezes_full_mode_and_target(dialog, monkeypatch):
    from PySide6.QtTest import QTest
    import threading
    gate = threading.Event()
    _stub_engine(monkeypatch, gate=gate)
    monkeypatch.setattr('twobyteasr.glossary.glossary_skill.detect_search_capability', lambda _: dict(
        provider_search=False, service='deepseek', model='deepseek-v4-pro', reason='无原生搜索'))
    dialog._ai_update_needs_key = lambda settings: False   # a configured service (no-key note, 2026-10-15)
    dialog.state['game'] = '瓦罗兰特'
    dialog._refresh_ai_update_buttons()
    assert dialog.ai_full_button.menu() is None
    assert dialog.ai_full_button.text() == 'AI 完整建库'
    QTest.mouseClick(dialog.ai_full_button, Qt.MouseButton.LeftButton)
    manager = dialog._ensure_task_manager()
    tasks = list(manager._tasks.values())
    assert len(tasks) == 1
    task = tasks[0]
    assert task.mode == 'full'
    assert manager._settings_by_task[task.task_id]['models']['glossary_execution_mode'] == 'full'
    target = task.library_id
    dialog.state['game'] = '原神'
    assert task.library_id == target
    gate.set()
    assert _spin(_app(), lambda: task.status == 'finished')


def test_review_zero_selection_disables_apply_even_with_unverified_candidates(dialog):
    from twobyteasr.glossary.glossary_skill_ui import GlossaryUpdateReviewDialog
    result = dict(mode='full', outcome=dict(status='partial', message='未核实建议需逐条确认'),
        diffs=[TermDiff(change_type='unverifiable', term=SearchedTerm(term='未核实名称'), checked_by_default=False)])
    review = GlossaryUpdateReviewDialog(dialog.owner, '瓦罗兰特', result)
    assert not review.apply_button.isEnabled()
    review.model.check_filtered(True)
    assert review.apply_button.isEnabled()
    review.model.check_none()
    assert not review.apply_button.isEnabled()
    review.deleteLater()


def test_review_existing_names_are_not_presented_as_applicable_candidates(dialog):
    from twobyteasr.glossary.glossary_skill_ui import GlossaryUpdateReviewDialog
    result = dict(mode='full', candidate_count=0, collected_count=38, diffs=[],
        outcome=dict(status='partial', message='已整理的名称均已存在；来源不足，未确认覆盖。'),
        build_stats=dict(unique_candidates=38, duplicate_candidates=38))
    review = GlossaryUpdateReviewDialog(dialog.owner, '瓦罗兰特', result)
    assert review.model.rowCount() == 0
    assert not review.apply_button.isEnabled()
    assert review.apply_button.property('zeroApplicable') is True
    assert '待审阅变化 0' in review.summary_label.text()
    assert '已整理名称 38（已有重复 38）' in review.summary_label.text()
    assert '候选 38' not in review.summary_label.text()
    review.deleteLater()


def test_finish_attribution_when_on_other_game(dialog, monkeypatch):
    """当前页在原神，绝区零任务完成 → toast 归属绝区零并含计数。"""
    app = _app()
    _stub_engine(monkeypatch)
    toasts: list[str] = []
    dialog._show_toast = lambda text: toasts.append(text)
    dialog.state["game"] = "原神"
    manager = dialog._ensure_task_manager()
    diffs = [
        TermDiff(change_type="new", term=SearchedTerm(
            term="青衣", category="角色", category_key="character",
            sources=({"url": "https://a.b/c", "title": ""},), verification="page_verified")),
        TermDiff(change_type="alias_supplement", term=SearchedTerm(
            term="安比", category="角色", category_key="character", aliases=("安比姐",),
            sources=({"url": "https://a.b/c", "title": ""},))),
    ]
    result = {"diffs": diffs, "candidate_count": 2, "mode": "full"}
    dialog._on_task_finished("tid", "绝区零", result)
    assert toasts and "绝区零" in toasts[-1]
    assert "新增候选 1" in toasts[-1] and "别名补充 1" in toasts[-1]


# ---------------------------------------------------------------- 预览模型

def _diff(term, change="new", priority="core", verification="page_verified", category="角色", cross=False):
    return TermDiff(
        change_type=change,
        term=SearchedTerm(
            term=term, category=category, category_key="character",
            priority=priority, sources=({"url": "https://wiki.biligame.com/zzz/x", "title": ""},),
            verification=verification,
        ),
        cross_game=cross,
    )


def test_diff_table_model_filters_and_core_selection():
    _app()
    from twobyteasr.glossary.glossary_skill_ui import DiffTableModel

    diffs = [
        _diff("青衣"),
        _diff("闪念", change="alias_supplement", priority="optional"),
        _diff("马娘", cross=True),
        _diff("无源词", verification="none"),
    ]
    model = DiffTableModel()
    model.set_diffs(diffs)
    assert model.rowCount() == 4
    # 默认勾选：page_verified core=✓，optional alias=✓(checked_by_default 由 diff 决定…模型按 checked_by_default)
    # 筛选：只看跨游戏
    model.set_filters(change="cross")
    assert model.rowCount() == 1
    text = model.data(model.index(0, model.COLUMN_TERM), Qt.ItemDataRole.DisplayRole)
    assert "⚠跨游戏" in text
    # 筛选：别名补充
    model.set_filters(change="alias_supplement")
    assert model.rowCount() == 1
    # 核心词选择：跨游戏/无来源不得入选
    model.set_filters()
    model.check_core_verified()
    terms = [d.term.term for d in model.checked_diffs()]
    assert "青衣" in terms
    assert "马娘" not in terms and "无源词" not in terms
    model.check_none()
    assert model.checked_count() == 0


def test_review_dialog_large_table_and_detail_pane(dialog):
    _app()
    from twobyteasr.glossary.glossary_skill_ui import GlossaryUpdateReviewDialog

    diffs = [_diff(f"角色{index:03d}") for index in range(200)]
    result = {"diffs": diffs, "candidate_count": 200, "mode": "full",
              "model": "grok-test", "service": "Grok CLI",
              "search_evidence": True, "elapsed_seconds": 123.4,
              "build_stats": {"current_version": "1.8", "names_extracted": 300,
                              "names_processed": 300, "page_verified": 200,
                              "catalogs": [{"url": "https://x", "title": "t", "covers": "characters"}]}}
    content = GlossaryUpdateReviewDialog(dialog, "绝区零", result, dialog)
    assert content.model.rowCount() == 200
    assert content.table.verticalHeader().defaultSectionSize() > 0
    # 勾选计数刷新
    content.model.check_none()
    assert content.checked_label.text() == "总勾选 0；当前筛选中 0/200；筛选外 0"
    content.model.check_core_verified()
    assert content.checked_label.text().startswith("总勾选 200；当前筛选中 200/200")
    # 选中行 → 详情区含完整 URL
    content.table.selectRow(0)
    assert "wiki.biligame.com" in content.detail.toPlainText()
    # 筛选缩窄
    content.change_filter.setCurrentIndex(content.change_filter.findData("alias_supplement"))
    assert content.model.rowCount() == 0
    content.deleteLater()


# ---------------------------------------------------------------- 主表引号去重

def test_unified_rows_merge_quote_variants_and_self_alias(dialog):
    game = "绝区零"
    dialog.state["game"] = game
    dialog.state["mappings"] = [
        {"from": "11号", "to": "11号", "category": "角色", "origin": "用户确认",
         "reason": "", "sources": [], "updated": "2026-09-01"},
    ]
    dialog.state["builtin_names"] = ["「11号」", "11号", "席德"]
    dialog.state["loaded"] = [("profile", 3, 3)]
    dialog._builtin_cache[game] = (
        dialog.state["builtin_names"], dialog.state["loaded"], [],
    )
    dialog._builtin_entry_cache[game] = [
        {"name": "「11号」", "category": "角色", "source": "官方资料", "aliases": [], "hidden": False},
        {"name": "11号", "category": "角色", "source": "官方资料", "aliases": ["11号", "爱溪"], "hidden": False},
        {"name": "席德", "category": "角色", "source": "官方资料", "aliases": ["席德"], "hidden": False},
    ]
    rows = dialog._unified_term_rows()
    terms = [row["term_text"].split("（")[0] for row in rows]
    assert terms.count("11号") == 1          # 「11号」/11号 合并为一行
    assert "「11号」" not in terms
    row_11 = next(row for row in rows if row["term_text"].startswith("11号"))
    assert "爱溪" in row_11["term_text"]     # 引号变体的别名被合并保留
    assert "别名 席德" not in " ".join(       # 自重复别名不展示
        row["term_text"] for row in rows if row["term_text"].startswith("席德")
    )
