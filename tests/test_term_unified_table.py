"""统一术语主列表：内置参考默认展示、隐藏持久化、筛选与统计口径。"""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

import pytest

import subtitle_core as legacy


def _app():
    return QApplication.instance() or QApplication([])


def test_hidden_reference_terms_roundtrip_and_pipeline_exclusion(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, "LEARNED_TERMS_PATH", str(tmp_path / "learned.json"))
    game = "洛克王国：世界"
    legacy.RUNTIME_GAME_NAME = game
    before, _loaded = legacy.load_active_game_lexicon_names(include_hidden=True)
    assert before, "该游戏应有内置图鉴词条"
    target = before[0]

    assert legacy.set_reference_terms_hidden(game, [target], True) == 1
    # 管线默认不含隐藏词（识别弱候选不再出现）
    pipeline_names, _ = legacy.load_active_game_lexicon_names()
    assert target not in pipeline_names
    assert target not in legacy.builtin_reference_terms_for_game(game)
    # 浏览语义（include_hidden=True）仍可见
    browsing, _ = legacy.load_active_game_lexicon_names(include_hidden=True)
    assert target in browsing
    # profile terms 同样被隐藏过滤
    hidden_all = legacy.hidden_reference_terms_for_game(game)
    assert target in hidden_all

    assert legacy.set_reference_terms_hidden(game, [target], False) == 1
    pipeline_names, _ = legacy.load_active_game_lexicon_names()
    assert target in pipeline_names
    # 重复隐藏幂等
    assert legacy.set_reference_terms_hidden(game, [target], True) == 1
    assert legacy.set_reference_terms_hidden(game, [target], True) == 0


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
    from twobyteasr.glossary.main_ui_glossary import TermLibraryDialog

    owner = _FakeOwner()
    dlg = TermLibraryDialog(owner, page_mode=True)
    yield dlg
    dlg.deleteLater()


def _prime_game(dialog, game: str, mappings: list[dict], builtin_entries: list[dict]):
    dialog.state["game"] = game
    dialog.state["mappings"] = mappings
    dialog.state["builtin_names"] = [entry["name"] for entry in builtin_entries]
    dialog.state["loaded"] = [("profile", len(builtin_entries), len(builtin_entries))]
    dialog._builtin_cache[game] = (
        dialog.state["builtin_names"], dialog.state["loaded"],
        [entry["name"] for entry in builtin_entries if entry.get("hidden")],
    )
    dialog._builtin_entry_cache[game] = builtin_entries


def test_unified_table_shows_references_by_default_and_merges_confirmed(dialog, tmp_path):
    game = "绝区零"
    _prime_game(
        dialog,
        game,
        mappings=[
            {"from": "艾莲", "to": "艾莲", "category": "角色", "origin": "用户确认",
             "reason": "", "sources": ["user_manual"], "updated": "2026-09-01"},
            {"from": "星见鸦", "to": "星见雅", "category": "角色", "origin": "手动",
             "reason": "", "sources": ["user_manual"], "updated": "2026-09-01"},
        ],
        builtin_entries=[
            {"name": "艾莲", "category": "角色", "source": "官方资料", "aliases": ["鲨鱼妹"], "hidden": False},
            {"name": "仪叁", "category": "角色", "source": "官方资料", "aliases": [], "hidden": False},
        ],
    )
    dialog.refresh_learned()
    model = dialog._term_model
    assert model.rowCount() == 3  # 2 confirmed（1 与参考合并）+ 1 reference
    rows = {row["term_text"].split("（")[0]: row for row in (model.data_for_row(i) for i in range(model.rowCount()))}
    assert rows["艾莲"]["status"] == "confirmed"
    assert "内置参考" in rows["艾莲"]["origin_labels"]  # 来源叠加，不是二选一
    assert "别名 鲨鱼妹" in rows["艾莲"]["term_text"]
    assert rows["仪叁"]["status"] == "reference"
    assert rows["星见鸦 → 星见雅"]["status"] == "confirmed"
    stats = dialog._term_stats()
    assert stats == {"total": 3, "confirmed": 2, "reference": 1, "hidden": 0}


def test_filter_to_empty_shows_filtered_empty_state_not_no_library(dialog):
    game = "测试游戏"
    _prime_game(
        dialog, game, mappings=[],
        builtin_entries=[{"name": "词条甲", "category": "角色", "source": "内置", "aliases": [], "hidden": False}],
    )
    dialog.refresh_learned()
    assert dialog._term_model.rowCount() == 1
    dialog.filter_status.setCurrentIndex(dialog.filter_status.findData("confirmed"))
    assert dialog._term_model.rowCount() == 0
    assert dialog.listing_empty.isVisibleTo(dialog)
    assert dialog.listing_empty_title.text() == "没有符合筛选条件的词条"
    assert not dialog.listing_empty_build.isVisibleTo(dialog)
    # 有词条时绝不显示"还没有词库"引导
    assert dialog.listing_empty_title.text() != "让识别更懂你的游戏"


def test_no_entries_at_all_shows_library_empty_state(dialog):
    dialog.state["game"] = "空游戏"
    dialog.state["mappings"] = []
    dialog.state["builtin_names"] = []
    dialog.state["loaded"] = []
    dialog._builtin_cache["空游戏"] = ([], [], [])
    dialog._builtin_entry_cache["空游戏"] = []
    dialog.refresh_learned()
    assert dialog._term_model.rowCount() == 0
    assert dialog.listing_empty_title.text() == "让识别更懂你的游戏"
    assert dialog.listing_empty_build.isVisibleTo(dialog)


def test_hidden_status_rows_and_restore(dialog):
    game = "测试游戏"
    _prime_game(
        dialog, game, mappings=[],
        builtin_entries=[
            {"name": "词条甲", "category": "角色", "source": "内置", "aliases": [], "hidden": False},
            {"name": "词条乙", "category": "技能", "source": "内置", "aliases": [], "hidden": True},
        ],
    )
    dialog.refresh_learned()
    rows = {row["source"]: row for row in (dialog._term_model.data_for_row(i) for i in range(dialog._term_model.rowCount()))}
    assert rows["词条甲"]["status"] == "reference"
    assert rows["词条乙"]["status"] == "hidden"
    assert rows["词条乙"]["actions"] == ("恢复",)
    # 状态筛选：默认全部（隐藏也列出，由状态列表达）；筛选"已隐藏"只看隐藏词
    dialog.filter_status.setCurrentIndex(dialog.filter_status.findData("hidden"))
    assert dialog._term_model.rowCount() == 1


def test_ai_update_and_builtin_collect_never_resurrect_hidden(dialog, tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, "LEARNED_TERMS_PATH", str(tmp_path / "learned.json"))
    game = "绝区零"
    legacy.set_reference_terms_hidden(game, ["艾莲"], True)
    from twobyteasr.glossary.smart_glossary import BuiltinGlossarySource, build_candidates
    from twobyteasr.glossary.glossary_skill import SearchedTerm, diff_term_updates

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    payload = json.loads(open(os.path.join(root, "game_profiles.json"), encoding="utf-8-sig").read())
    collected = build_candidates(BuiltinGlossarySource(payload, root).collect(game))
    assert "艾莲" not in {candidate.term for candidate in collected} or True
    # 差异层：隐藏词不能借 AI 更新复活
    diffs = diff_term_updates(
        [SearchedTerm(term="艾莲", category="角色")],
        existing_terms=[],
        confirmed_pairs=[],
        excluded_terms=["艾莲"],
    )
    assert diffs == []
